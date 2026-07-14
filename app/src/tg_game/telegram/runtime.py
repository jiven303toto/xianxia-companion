import asyncio
import contextvars
import logging
import time
from contextlib import suppress
from pathlib import Path

from telethon import TelegramClient, events

from tg_game.config import get_settings
from tg_game.features.tianxing import maybe_queue_daily_observe
from tg_game.runtime_status import build_runtime_status, dump_runtime_status
from tg_game.services.external_sync import (
    ASC_PROVIDER,
    get_effective_external_cookie,
    get_external_keepalive_poll_seconds,
    is_external_account_expired,
    mark_external_account_failure,
    should_keep_external_session_fresh,
    sync_external_account,
)
from tg_game.storage import Storage
from tg_game.storage import OUTGOING_CONFIRM_TIMEOUT_SECONDS
from tg_game.telegram.network_guard import (
    is_network_send_error,
    mark_network_send_failure,
)
from tg_game.telegram.resume_guard import (
    TELEGRAM_LONG_RESUME_DEFER_SECONDS,
    TELEGRAM_LONG_RESUME_SECONDS,
    TELEGRAM_RESUME_COUNTDOWN_SPACING_SECONDS,
    TELEGRAM_RESUME_MODE_SECONDS,
    TELEGRAM_RESUME_OFFLINE_GAP_SECONDS,
    TELEGRAM_RESUME_SETTLE_SECONDS,
    TELEGRAM_WORKER_HEARTBEAT_SECONDS,
    defer_long_resume_countdowns,
    prepare_network_resume_if_ready,
    prepare_resume_protection,
    read_profile_worker_heartbeat,
    write_profile_worker_heartbeat,
)
from tg_game.telegram.send_utils import send_message_with_thread_fallback


logger = logging.getLogger(__name__)
_current_profile_id: contextvars.ContextVar[int] = contextvars.ContextVar(
    "_current_profile_id", default=0
)
_admin_profile_id: int = 0
DIVINATION_COMMAND = ".卜筮问天"
WORKER_RECONCILE_SECONDS = 5
XINGGONG_TIANJI_REFRESH_DEBOUNCE_SECONDS = 8
TELEGRAM_NETWORK_PAUSE_SLEEP_SECONDS = 5
XINGGONG_TIANJI_REFRESH_COMMAND_PREFIXES = (
    ".我的侍妾",
    ".每日问安",
    ".启阵",
    ".助阵",
    ".观星台",
    ".观星",
    ".扩建星台",
    ".牵引星辰",
    ".收集精华",
    ".安抚星辰",
    ".赠予侍妾",
    ".灵力反哺",
    ".侍妾卜算",
)


class _AdminLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if _admin_profile_id <= 0:
            return True
        current = _current_profile_id.get(0)
        if current <= 0:
            return True
        return current == _admin_profile_id


def _has_expired_external_session(storage: Storage, profile_id: int) -> bool:
    external_account = storage.get_external_account(int(profile_id), ASC_PROVIDER)
    return is_external_account_expired(external_account)


def _read_profile_worker_heartbeat(storage: Storage, profile_id: int) -> float:
    return read_profile_worker_heartbeat(storage, profile_id)


def _write_profile_worker_heartbeat(
    storage: Storage,
    profile_id: int,
    *,
    now: float,
) -> None:
    write_profile_worker_heartbeat(storage, profile_id, now=now)


def _prepare_resume_protection(
    storage: Storage,
    profile_id: int,
    *,
    now: float,
    gap_seconds: float,
) -> int:
    return prepare_resume_protection(
        storage,
        profile_id,
        now=now,
        gap_seconds=gap_seconds,
    )


def _defer_long_resume_countdowns(
    storage: Storage,
    profile_id: int,
    *,
    now: float,
) -> int:
    return defer_long_resume_countdowns(storage, profile_id, now=now)


def _prepare_network_resume_if_ready(
    storage: Storage,
    profile_id: int,
    *,
    now: float,
) -> bool:
    return prepare_network_resume_if_ready(storage, profile_id, now=now)


def _is_xinggong_tianji_refresh_command(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized.startswith("."):
        return False
    return any(
        normalized == prefix or normalized.startswith(f"{prefix} ")
        for prefix in XINGGONG_TIANJI_REFRESH_COMMAND_PREFIXES
    )


async def _refresh_tianji_payload_once(storage: Storage, profile_id: int) -> None:
    external_account = storage.get_external_account(int(profile_id), ASC_PROVIDER) or {}
    cookie_text = (
        (external_account or {}).get("cookie_text") or get_effective_external_cookie(storage)
    ).strip()
    if not cookie_text:
        logger.warning(
            "Xinggong Tianji refresh skipped profile=%s reason=no_cookie", profile_id
        )
        return
    try:
        await asyncio.to_thread(
            sync_external_account,
            storage,
            int(profile_id),
            cookie_text=cookie_text,
        )
        confirmed_count = storage.confirm_awaiting_outgoing_commands_by_prefixes(
            int(profile_id),
            XINGGONG_TIANJI_REFRESH_COMMAND_PREFIXES,
            recent_seconds=OUTGOING_CONFIRM_TIMEOUT_SECONDS,
            reason="confirmed by Tianji payload refresh",
        )
        logger.info("Xinggong Tianji payload refreshed profile=%s", profile_id)
        if confirmed_count:
            logger.info(
                "Xinggong Tianji payload confirmed %s outgoing command(s) profile=%s",
                confirmed_count,
                profile_id,
            )
    except Exception as exc:
        mark_external_account_failure(storage, int(profile_id), exc, cookie_text=cookie_text)
        logger.warning(
            "Xinggong Tianji refresh failed profile=%s error=%s", profile_id, exc
        )


async def _run_xinggong_tianji_refresh_worker(
    storage: Storage,
    profile_id: int,
    state: dict,
) -> None:
    entry = state.setdefault(int(profile_id), {"version": 0, "task": None})
    try:
        while True:
            target_version = int(entry.get("version") or 0)
            await asyncio.sleep(XINGGONG_TIANJI_REFRESH_DEBOUNCE_SECONDS)
            if int(entry.get("version") or 0) != target_version:
                continue
            await _refresh_tianji_payload_once(storage, int(profile_id))
            if int(entry.get("version") or 0) == target_version:
                break
    except asyncio.CancelledError:
        raise
    finally:
        if entry.get("task") is asyncio.current_task():
            entry["task"] = None


def _schedule_xinggong_tianji_refresh(
    client: TelegramClient,
    storage: Storage,
    profile_id: int,
    command_text: str,
) -> None:
    if not _is_xinggong_tianji_refresh_command(command_text):
        return
    state = getattr(client, "_tg_game_xinggong_tianji_refresh_state", None)
    if state is None:
        state = {}
        setattr(client, "_tg_game_xinggong_tianji_refresh_state", state)
    entry = state.setdefault(int(profile_id), {"version": 0, "task": None})
    entry["version"] = int(entry.get("version") or 0) + 1
    task = entry.get("task")
    if task and not task.done():
        logger.info(
            "Xinggong Tianji refresh rescheduled profile=%s version=%s",
            profile_id,
            entry["version"],
        )
        return
    task = asyncio.create_task(
        _run_xinggong_tianji_refresh_worker(storage, int(profile_id), state)
    )
    entry["task"] = task
    background_tasks = getattr(client, "_tg_game_background_tasks", None)
    if background_tasks is None:
        background_tasks = set()
        setattr(client, "_tg_game_background_tasks", background_tasks)
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    logger.info(
        "Xinggong Tianji refresh scheduled profile=%s version=%s command=%s",
        profile_id,
        entry["version"],
        command_text,
    )


def _record_sent_outgoing_message(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    fallback_thread_id: int | None,
    text: str,
    message: object,
) -> None:
    message_id = int(getattr(message, "id", None) or 0)
    if message_id <= 0:
        return

    reply_to = getattr(message, "reply_to", None)
    reply_to_msg_id = getattr(reply_to, "reply_to_msg_id", None)
    thread_id = None
    for candidate in [
        getattr(reply_to, "reply_to_top_id", None),
        getattr(message, "reply_to_top_id", None),
        getattr(reply_to, "top_msg_id", None),
        getattr(message, "top_msg_id", None),
        fallback_thread_id,
    ]:
        if candidate:
            thread_id = int(candidate)
            break
    binding = storage.resolve_chat_binding_for_event(
        int(profile_id),
        int(chat_id),
        thread_id,
        int(reply_to_msg_id) if reply_to_msg_id else None,
    )
    if binding and binding.thread_id:
        thread_id = int(binding.thread_id)

    profile = storage.get_profile(int(profile_id))
    sender_text = str(getattr(profile, "telegram_user_id", "") or "").strip()
    sender_id = int(sender_text) if sender_text.isdigit() else 0
    if sender_id <= 0:
        sender_id = int(getattr(message, "sender_id", None) or 0)
    sender_username = str(getattr(profile, "telegram_username", "") or "").strip()

    storage.upsert_bound_message(
        profile_id=int(profile_id),
        chat_id=int(chat_id),
        thread_id=thread_id,
        message_id=message_id,
        reply_to_msg_id=int(reply_to_msg_id) if reply_to_msg_id else None,
        sender_id=sender_id,
        sender_username=sender_username,
        direction="outgoing",
        is_bot=False,
        text=text,
    )


async def _refresh_external_sessions(storage: Storage) -> None:
    while True:
        try:
            for profile in storage.list_profiles():
                if not profile.telegram_verified_at:
                    continue
                external_account = storage.get_external_account(
                    profile.id, ASC_PROVIDER
                )
                if not should_keep_external_session_fresh(profile, external_account):
                    continue
                cookie_text = (
                    (external_account or {}).get("cookie_text")
                    or get_effective_external_cookie(storage)
                ).strip()
                if not cookie_text:
                    continue
                try:
                    await asyncio.to_thread(
                        sync_external_account,
                        storage,
                        profile.id,
                        cookie_text=cookie_text,
                    )
                except Exception as exc:
                    mark_external_account_failure(
                        storage, profile.id, exc, cookie_text=cookie_text
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram external keepalive failed")
        await asyncio.sleep(get_external_keepalive_poll_seconds())


async def _dispatch_outgoing_commands(
    client: TelegramClient,
    storage: Storage,
    profile_id: int,
) -> None:
    last_confirm_sweep_at = 0.0
    last_loop_at = 0.0
    last_heartbeat_write_at = 0.0
    last_resume_prepare_at = 0.0
    while True:
        command = None
        try:
            now = time.time()
            previous_seen_at = last_loop_at or _read_profile_worker_heartbeat(
                storage, profile_id
            )
            resume_gap = now - previous_seen_at if previous_seen_at > 0 else 0.0
            if (
                resume_gap >= TELEGRAM_RESUME_OFFLINE_GAP_SECONDS
                and now - last_resume_prepare_at >= TELEGRAM_RESUME_OFFLINE_GAP_SECONDS
            ):
                failed_count = _prepare_resume_protection(
                    storage,
                    profile_id,
                    now=now,
                    gap_seconds=resume_gap,
                )
                last_resume_prepare_at = now
                last_heartbeat_write_at = now
                last_loop_at = now
                logger.warning(
                    "Resume protection entered profile=%s gap_seconds=%.1f stale_outgoing_failed=%s",
                    profile_id,
                    resume_gap,
                    failed_count,
                )
                await asyncio.sleep(TELEGRAM_RESUME_SETTLE_SECONDS)
                continue
            if now - last_heartbeat_write_at >= TELEGRAM_WORKER_HEARTBEAT_SECONDS:
                _write_profile_worker_heartbeat(storage, profile_id, now=now)
                last_heartbeat_write_at = now
            last_loop_at = now
            if now - last_confirm_sweep_at >= 15:
                interrupted_count = storage.expire_sending_outgoing_commands(
                    profile_id,
                    timeout_seconds=OUTGOING_CONFIRM_TIMEOUT_SECONDS,
                )
                if interrupted_count:
                    logger.warning(
                        "Marked %s interrupted sending outgoing command(s) as failed for profile=%s",
                        interrupted_count,
                        profile_id,
                    )
                expired_count = storage.expire_awaiting_outgoing_commands(
                    profile_id,
                    timeout_seconds=OUTGOING_CONFIRM_TIMEOUT_SECONDS,
                )
                if expired_count:
                    logger.warning(
                        "Marked %s outgoing command(s) as needing manual confirmation for profile=%s",
                        expired_count,
                        profile_id,
                    )
                last_confirm_sweep_at = now
            if _prepare_network_resume_if_ready(storage, profile_id, now=now):
                await asyncio.sleep(TELEGRAM_NETWORK_PAUSE_SLEEP_SECONDS)
                continue
            if _has_expired_external_session(storage, profile_id):
                await asyncio.sleep(1)
                continue
            daily_tianxing = maybe_queue_daily_observe(
                storage,
                profile_id,
                now=now,
            )
            if daily_tianxing.get("queued"):
                logger.info(
                    "Tianxing daily command queued profile=%s command=%s",
                    profile_id,
                    daily_tianxing.get("command"),
                )
            command = storage.claim_next_outgoing_command(profile_id)
            if not command:
                await asyncio.sleep(0.5)
                continue

            chat_id = int(command.get("chat_id") or 0)
            thread_id = command.get("thread_id")
            reply_to_msg_id = command.get("reply_to_msg_id")
            bot_username = command.get("bot_username") or ""
            text = (command.get("text") or "").strip()
            if not chat_id or not text:
                storage.mark_outgoing_command_failed(
                    command["id"], "Missing chat_id or text"
                )
                continue

            latest_command = storage.get_outgoing_command(int(command["id"]))
            if (
                not latest_command
                or str(latest_command.get("status") or "") != "sending"
            ):
                continue

            message = await send_message_with_thread_fallback(
                client,
                chat_id,
                text,
                thread_id=(
                    int(reply_to_msg_id)
                    if reply_to_msg_id
                    else int(thread_id)
                    if thread_id
                    else None
                ),
                storage=storage,
                profile_id=profile_id,
                bot_username=bot_username,
                log_prefix=f"Outgoing queue profile={profile_id}",
                guard_network_pause=True,
            )
            if text == DIVINATION_COMMAND and message is not None and chat_id:
                batch = storage.get_active_divination_batch(profile_id, chat_id)
                if batch:
                    planned_rounds = max(
                        int(batch.get("target_count") or 0)
                        - int(batch.get("initial_count") or 0),
                        0,
                    )
                    current_sent = max(int(batch.get("sent_count") or 0), 0)
                    current_completed = max(int(batch.get("completed_count") or 0), 0)
                    if (
                        planned_rounds > 0
                        and int(batch.get("pending_command_msg_id") or 0)
                        != int(message.id)
                        and current_sent <= current_completed
                    ):
                        storage.update_divination_batch(
                            int(batch["id"]),
                            thread_id=int(thread_id)
                            if thread_id
                            else batch.get("thread_id"),
                            sent_count=min(current_sent + 1, planned_rounds),
                            pending_command_msg_id=int(message.id),
                        )
            if message is not None:
                try:
                    _record_sent_outgoing_message(
                        storage,
                        profile_id=profile_id,
                        chat_id=chat_id,
                        fallback_thread_id=int(thread_id) if thread_id else None,
                        text=text,
                        message=message,
                    )
                except Exception:
                    logger.exception(
                        "Failed to record sent outgoing command profile=%s chat=%s text=%r",
                        profile_id,
                        chat_id,
                        text,
                    )
            storage.mark_outgoing_command_sent(command["id"])
            _schedule_xinggong_tianji_refresh(client, storage, profile_id, text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if is_network_send_error(exc):
                mark_network_send_failure(storage, profile_id, exc)
            if "command" in locals() and command and command.get("id"):
                storage.mark_outgoing_command_failed(command["id"], str(exc))
            logger.exception(
                "Failed to dispatch queued outgoing command for profile=%s", profile_id
            )
            await asyncio.sleep(1)


def _build_client(session_name: str) -> TelegramClient:
    settings = get_settings()
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise RuntimeError(
            "Missing TELEGRAM_API_ID or TELEGRAM_API_HASH in environment"
        )
    session_name = (session_name or "").strip()
    session_path = Path(session_name)
    if session_name and not session_path.is_absolute() and session_path.parent == Path("."):
        session_name = str(settings.database_path.parent / session_name)
    return TelegramClient(
        session_name,
        int(settings.telegram_api_id),
        settings.telegram_api_hash,
    )


async def _register_handlers(
    client: TelegramClient,
    *,
    profile_id: int,
    session_name: str,
) -> None:
    from tg_game.runtime import build_router

    settings = get_settings()
    storage = Storage(settings.database_path)
    client._tg_game_storage = storage
    client._tg_game_profile_id = int(profile_id)
    client._tg_game_session_name = session_name
    router = build_router(storage, runtime_profile_id=int(profile_id))
    await router.startup(client)

    def _should_log_chat(event):
        chat_id = getattr(event, "chat_id", None)
        if chat_id is None:
            return False
        message = getattr(event, "message", None)
        reply_to = getattr(message, "reply_to", None) if message else None
        reply_to_msg_id = getattr(reply_to, "reply_to_msg_id", None)
        thread_id = None
        for candidate in [
            getattr(reply_to, "reply_to_top_id", None),
            getattr(message, "reply_to_top_id", None) if message else None,
            getattr(reply_to, "top_msg_id", None),
            getattr(message, "top_msg_id", None) if message else None,
        ]:
            if candidate:
                thread_id = candidate
                break
        return (
            storage.resolve_chat_binding_for_event(
                int(profile_id), chat_id, thread_id, reply_to_msg_id
            )
            is not None
        )

    @client.on(events.NewMessage(incoming=True, outgoing=True))
    async def _incoming_handler(event):
        if settings.telegram_log_messages and _should_log_chat(event):
            if _current_profile_id.get(0) == _admin_profile_id:
                logger.info(
                    "Message received profile=%s chat=%s sender=%s text=%r",
                    profile_id,
                    event.chat_id,
                    event.sender_id,
                    event.raw_text or "",
                )
        await router.dispatch(client, event)

    @client.on(events.MessageEdited(incoming=True))
    async def _edited_handler(event):
        if settings.telegram_log_messages and _should_log_chat(event):
            if _current_profile_id.get(0) == _admin_profile_id:
                logger.info(
                    "Message edited profile=%s chat=%s sender=%s text=%r",
                    profile_id,
                    event.chat_id,
                    event.sender_id,
                    event.raw_text or "",
                )
        await router.dispatch(client, event)

    client._tg_game_outgoing_task = asyncio.create_task(
        _dispatch_outgoing_commands(client, storage, int(profile_id))
    )


async def _cancel_client_background_tasks(client: TelegramClient) -> None:
    background_tasks = list(
        getattr(client, "_tg_game_background_tasks", set()) or set()
    )
    alive_tasks = [task for task in background_tasks if task and not task.done()]
    for task in alive_tasks:
        task.cancel()
    if alive_tasks:
        results = await asyncio.gather(*alive_tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception) and not isinstance(
                result, asyncio.CancelledError
            ):
                logger.warning(
                    "Background task exited with error during shutdown: %r", result
                )
    setattr(client, "_tg_game_background_tasks", set())


async def _shutdown_client(client: TelegramClient) -> None:
    await _cancel_client_background_tasks(client)
    outgoing_task = getattr(client, "_tg_game_outgoing_task", None)
    if outgoing_task:
        outgoing_task.cancel()
        with suppress(asyncio.CancelledError):
            await outgoing_task
    if client.is_connected():
        try:
            await asyncio.shield(client.disconnect())
        except Exception:
            logger.exception("Telegram client disconnect failed")
    try:
        await asyncio.shield(asyncio.wait_for(client.disconnected, timeout=8))
    except asyncio.TimeoutError:
        logger.warning("Timed out waiting for Telegram client.disconnected")
    except Exception:
        logger.exception("Waiting for Telegram client.disconnected failed")
    await asyncio.sleep(0.1)


async def _run_profile_worker(profile_id: int) -> None:
    _current_profile_id.set(int(profile_id))
    settings = get_settings()
    storage = Storage(settings.database_path)
    while True:
        client = None
        try:
            profile = storage.get_profile(int(profile_id))
            if not profile or not profile.telegram_verified_at:
                await asyncio.sleep(WORKER_RECONCILE_SECONDS)
                continue
            preferred_session_name = (profile.telegram_session_name or "").strip()
            if not preferred_session_name:
                await asyncio.sleep(WORKER_RECONCILE_SECONDS)
                continue
            resolved_session_name = preferred_session_name
            client = _build_client(resolved_session_name)
            await client.connect()
            if not await client.is_user_authorized():
                logger.warning(
                    "Telegram session for profile=%s is not authorized yet; worker waiting",
                    profile_id,
                )
                await client.disconnect()
                await asyncio.sleep(WORKER_RECONCILE_SECONDS)
                continue
            me = await client.get_me()
            logger.info(
                "Telegram worker connected profile=%s telegram_id=%s username=%s phone=%s",
                profile_id,
                getattr(me, "id", None),
                getattr(me, "username", None),
                getattr(me, "phone", None),
            )
            now = time.time()
            previous_seen_at = _read_profile_worker_heartbeat(storage, int(profile.id))
            if previous_seen_at > 0:
                resume_gap = now - previous_seen_at
                failed_count = _prepare_resume_protection(
                    storage,
                    int(profile.id),
                    now=now,
                    gap_seconds=resume_gap,
                )
                if resume_gap >= TELEGRAM_RESUME_OFFLINE_GAP_SECONDS:
                    logger.warning(
                        "Resume protection prepared before worker start profile=%s gap_seconds=%.1f stale_outgoing_failed=%s",
                        profile.id,
                        resume_gap,
                        failed_count,
                    )
            else:
                _write_profile_worker_heartbeat(storage, int(profile.id), now=now)
            if resolved_session_name != (profile.telegram_session_name or ""):
                storage.bind_profile_telegram_account(
                    profile.id,
                    telegram_user_id=str(
                        getattr(me, "id", "") or profile.telegram_user_id
                    ),
                    telegram_username=(
                        getattr(me, "username", "") or profile.telegram_username
                    ),
                    telegram_phone=(getattr(me, "phone", "") or profile.telegram_phone),
                    telegram_session_name=resolved_session_name,
                )
            await _register_handlers(
                client,
                profile_id=int(profile.id),
                session_name=resolved_session_name,
            )
            await client.run_until_disconnected()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram worker failed for profile=%s", profile_id)
            await asyncio.sleep(2)
        finally:
            if client is not None:
                try:
                    await asyncio.shield(_shutdown_client(client))
                except Exception:
                    logger.exception(
                        "Telegram worker shutdown failed for profile=%s", profile_id
                    )


async def _resolve_worker_targets(storage: Storage) -> dict[int, str]:
    targets = {}
    for profile in storage.list_profiles():
        if not profile.telegram_verified_at:
            continue
        preferred_session_name = (profile.telegram_session_name or "").strip()
        if not preferred_session_name:
            continue
        targets[int(profile.id)] = preferred_session_name
    return targets


async def _main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s"
    )
    logger.info("Telegram runtime started")
    started_at = time.time()
    settings = get_settings()
    storage = Storage(settings.database_path)
    storage.init_schema()
    storage.set_runtime_state(
        "telegram_runtime_status",
        dump_runtime_status(build_runtime_status("telegram", started_at=started_at)),
    )
    storage.maybe_cleanup_bound_messages(min_interval_seconds=0)

    global _admin_profile_id
    authorized_user_id = str(settings.authorized_user_id or "").strip()
    if authorized_user_id:
        admin_profile = storage.get_profile_by_telegram_user_id(authorized_user_id)
        if admin_profile:
            _admin_profile_id = int(admin_profile.id)
            logging.getLogger().addFilter(_AdminLogFilter())
            logger.info(
                "日志过滤器已启用，仅显示管理员 profile=%d 的消息", _admin_profile_id
            )

    keepalive_task = asyncio.create_task(_refresh_external_sessions(storage))
    worker_tasks: dict[int, asyncio.Task] = {}
    worker_sessions: dict[int, str] = {}
    try:
        while True:
            targets = await _resolve_worker_targets(storage)

            for profile_id, session_name in list(worker_sessions.items()):
                if targets.get(profile_id) == session_name:
                    continue
                task = worker_tasks.pop(profile_id, None)
                worker_sessions.pop(profile_id, None)
                if task:
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
                    logger.info(
                        "Stopped Telegram worker for profile=%s due to runtime target change",
                        profile_id,
                    )

            for profile_id, session_name in targets.items():
                existing_task = worker_tasks.get(profile_id)
                if existing_task and not existing_task.done():
                    continue
                worker_sessions[profile_id] = session_name
                worker_tasks[profile_id] = asyncio.create_task(
                    _run_profile_worker(profile_id)
                )
                logger.info(
                    "Started Telegram worker for profile=%s session=%s",
                    profile_id,
                    session_name,
                )

            completed_profile_ids = [
                profile_id
                for profile_id, task in worker_tasks.items()
                if task.done() and profile_id not in targets
            ]
            for profile_id in completed_profile_ids:
                worker_tasks.pop(profile_id, None)
                worker_sessions.pop(profile_id, None)

            await asyncio.sleep(WORKER_RECONCILE_SECONDS)
    finally:
        keepalive_task.cancel()
        with suppress(asyncio.CancelledError):
            await keepalive_task
        worker_task_list = list(worker_tasks.values())
        for task in worker_task_list:
            task.cancel()
        if worker_task_list:
            await asyncio.gather(*worker_task_list, return_exceptions=True)
        worker_tasks.clear()
        worker_sessions.clear()
        await asyncio.sleep(0.3)


def run_telegram_runtime() -> None:
    asyncio.run(_main())
