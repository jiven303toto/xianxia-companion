import logging
import time
from typing import Dict, List, Optional
from tg_game import pagoda_auto
from tg_game.config import get_settings
from tg_game.runtime.context import EventContext
from tg_game.runtime.executors import (
    BaseExecutor,
    FanrenExecutor,
    GeneralGameExecutor,
    SectExecutor,
    observe_fishing_reply,
    observe_companion_heart_tribulation_event,
    reschedule_artifact_touch_auto_on_reply,
)
from tg_game.features.xinggong.biz_xinggong_star_board import (
    XINGGONG_STARBOARD_FEATURE_KEY,
    XINGGONG_STARBOARD_INSUFFICIENT_ERROR,
    XINGGONG_STARBOARD_PULL_PREFIX,
    extract_starboard_pull_target,
    is_starboard_insufficient_reply,
)
from tg_game.features.tianxing import ensure_schema as ensure_tianxing_schema
from tg_game.features.tianxing import handle_bot_reply as handle_tianxing_bot_reply
from tg_game.services import module_registry
from tg_game.services.external_sync import is_authorized_profile
from tg_game.services.stock_sync import sync_stock_market_message
from tg_game.storage import OUTGOING_CONFIRM_TIMEOUT_SECONDS, Storage
from tg_game.dungeon_defs import is_dungeon_command_text, is_dungeon_reply_text
from tg_game.services.stock_sync import sync_stock_market_message, is_stock_related

logger = logging.getLogger(__name__)

COMPANION_VOYAGE_FEATURE_KEY = "companion_voyage"
COMPANION_VOYAGE_START_PREFIX = ".侍妾远航"
COMPANION_VOYAGE_RETURN_COMMAND = ".远航归来"
COMPANION_VOYAGE_STATUS_COMMAND = ".远航状态"
COMPANION_VOYAGE_RECHECK_SECONDS = 60
COMPANION_VOYAGE_RETURN_DELAY_SECONDS = 10
COMPANION_VOYAGE_RETURN_WAITING_ERROR = (
    "侍妾已归航待结算，已改为先发送 .远航归来。"
)
COMPANION_VOYAGE_ACTIVE_COMMAND_STATUSES = {
    "pending",
    "sending",
    "awaiting_confirm",
    "needs_manual_confirm",
}


def _is_xinggong_starboard_insufficient_reply(text: str) -> bool:
    return is_starboard_insufficient_reply(text)


def _extract_xinggong_starboard_pull_target(command_text: str) -> str:
    return extract_starboard_pull_target(command_text)


def _is_companion_voyage_return_waiting_reply(text: str) -> bool:
    normalized = " ".join(str(text or "").split())
    return (
        "远航归来" in normalized
        and (
            "待结算" in normalized
            or "尚未结算" in normalized
            or "等你接引" in normalized
        )
    )


def _is_companion_voyage_start_command(command_text: str) -> bool:
    normalized = str(command_text or "").strip()
    return normalized == COMPANION_VOYAGE_START_PREFIX or normalized.startswith(
        f"{COMPANION_VOYAGE_START_PREFIX} "
    )


def _has_active_companion_voyage_return_command(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
) -> bool:
    latest_command = storage.get_latest_outgoing_command(
        chat_id,
        profile_id=profile_id,
        text=COMPANION_VOYAGE_RETURN_COMMAND,
        thread_id=thread_id,
    )
    if not latest_command:
        return False
    status = str(latest_command.get("status") or "").strip()
    if status not in COMPANION_VOYAGE_ACTIVE_COMMAND_STATUSES:
        return False
    if status == "needs_manual_confirm":
        updated_at = float(latest_command.get("updated_at") or 0)
        return (
            updated_at > 0
            and time.time() - updated_at < OUTGOING_CONFIRM_TIMEOUT_SECONDS
        )
    return True


def _disable_xinggong_starboard_auto_on_insufficient_reply(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    reply_to_msg_id: int,
    reply_text: str,
) -> bool:
    if not _is_xinggong_starboard_insufficient_reply(reply_text):
        return False
    parent = storage.get_bound_message(chat_id, reply_to_msg_id, profile_id)
    if not parent or int(parent.get("is_bot") or 0):
        return False
    if str(parent.get("direction") or "").strip() != "outgoing":
        return False
    command_text = str(parent.get("text") or "").strip()
    target_star = _extract_xinggong_starboard_pull_target(command_text)
    if not target_star:
        return False
    task = storage.get_companion_auto_task(
        profile_id, chat_id, XINGGONG_STARBOARD_FEATURE_KEY
    )
    if not task or not bool(task.get("enabled")):
        return False
    storage.disable_companion_auto_task(
        profile_id,
        chat_id,
        XINGGONG_STARBOARD_FEATURE_KEY,
        last_error=XINGGONG_STARBOARD_INSUFFICIENT_ERROR,
    )
    thread_id = parent.get("thread_id")
    for candidate in {
        command_text,
        f"{XINGGONG_STARBOARD_PULL_PREFIX} {target_star}",
        *(
            f"{XINGGONG_STARBOARD_PULL_PREFIX} {slot} {target_star}"
            for slot in range(1, 17)
        ),
    }:
        storage.cancel_pending_outgoing_commands(
            profile_id,
            chat_id,
            text=candidate,
            thread_id=int(thread_id) if thread_id is not None else None,
            require_exact_thread=True,
        )
    return True


def _repair_companion_voyage_auto_on_return_waiting_reply(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    reply_to_msg_id: int,
    reply_text: str,
) -> bool:
    if not _is_companion_voyage_return_waiting_reply(reply_text):
        return False
    parent = storage.get_bound_message(chat_id, reply_to_msg_id, profile_id)
    if not parent or int(parent.get("is_bot") or 0):
        return False
    if str(parent.get("direction") or "").strip() != "outgoing":
        return False
    command_text = str(parent.get("text") or "").strip()
    if not _is_companion_voyage_start_command(command_text):
        return False
    task = storage.get_companion_auto_task(
        profile_id, chat_id, COMPANION_VOYAGE_FEATURE_KEY
    )
    if not task or not bool(task.get("enabled")):
        return False
    thread_id = parent.get("thread_id")
    resolved_thread_id = int(thread_id) if thread_id is not None else None
    if not _has_active_companion_voyage_return_command(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=resolved_thread_id,
    ):
        storage.enqueue_outgoing_command(
            profile_id=profile_id,
            chat_id=chat_id,
            text=COMPANION_VOYAGE_RETURN_COMMAND,
            thread_id=resolved_thread_id,
            chat_type=str(task.get("chat_type") or "group"),
            bot_username=str(task.get("bot_username") or ""),
        )
        storage.enqueue_outgoing_command(
            profile_id=profile_id,
            chat_id=chat_id,
            text=COMPANION_VOYAGE_STATUS_COMMAND,
            thread_id=resolved_thread_id,
            chat_type=str(task.get("chat_type") or "group"),
            bot_username=str(task.get("bot_username") or ""),
            delay_seconds=COMPANION_VOYAGE_RETURN_DELAY_SECONDS,
        )
    storage.update_companion_auto_task(
        int(task["id"]),
        last_run_at=time.time(),
        next_run_at=time.time() + COMPANION_VOYAGE_RECHECK_SECONDS,
        last_error=COMPANION_VOYAGE_RETURN_WAITING_ERROR,
    )
    return True


def _reschedule_pagoda_auto_on_failed_reply(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    reply_to_msg_id: int,
    reply_text: str,
) -> bool:
    if not pagoda_auto.is_failed_today_reply(reply_text):
        return False
    parent = storage.get_bound_message(chat_id, reply_to_msg_id, profile_id)
    if not parent or int(parent.get("is_bot") or 0):
        return False
    if str(parent.get("direction") or "").strip() != "outgoing":
        return False
    if str(parent.get("text") or "").strip() != pagoda_auto.COMMAND:
        return False
    task = storage.get_companion_auto_task(
        profile_id,
        chat_id,
        pagoda_auto.FEATURE_KEY,
    )
    if not task or not bool(task.get("enabled")):
        return False
    thread_id = parent.get("thread_id")
    task_thread_id = task.get("thread_id")
    if task_thread_id is not None and thread_id is not None:
        if int(task_thread_id) != int(thread_id):
            return False
    now_ts = time.time()
    storage.update_companion_auto_task(
        int(task["id"]),
        workflow_state="failed_today",
        next_run_at=pagoda_auto.resolve_next_run_at(
            task.get("strategy"),
            now=now_ts,
            force_tomorrow=True,
        ),
        last_error=pagoda_auto.FAILED_TODAY_ERROR,
    )
    return True


def _sender_first_name(sender: object) -> str:
    return str(getattr(sender, "first_name", "") or "").strip()


def _custom_title_from_permissions(permissions: object) -> str:
    for holder in [permissions, getattr(permissions, "participant", None)]:
        title = str(getattr(holder, "custom_title", "") or "").strip()
        if title:
            return title
    return ""


def _is_dungeon_reply_chain(
    storage: Storage, chat_id: int, reply_to_msg_id: Optional[int]
) -> bool:
    current_id = int(reply_to_msg_id or 0)
    depth = 0
    while current_id and depth < 8:
        parent = storage.get_bound_message(chat_id, current_id)
        if not parent:
            return False
        parent_text = str(parent.get("text") or "").strip()
        if not bool(parent.get("is_bot")) and is_dungeon_command_text(parent_text):
            return True
        current_id = int(parent.get("reply_to_msg_id") or 0)
        depth += 1
    return False


class Router:
    def __init__(
        self,
        storage: Storage,
        executors: List[BaseExecutor],
        runtime_profile_id: Optional[int] = None,
    ):
        self.storage = storage
        self.executors = executors
        self.runtime_profile_id = (
            int(runtime_profile_id) if runtime_profile_id else None
        )

    async def startup(self, client: object) -> None:
        self.storage.init_schema()
        ensure_tianxing_schema(self.storage)
        settings = get_settings()
        profile = self._resolve_runtime_profile()
        if profile:
            self.storage.sync_env_chat_binding(
                profile_id=profile.id,
                chat_id=settings.bound_chat_id,
                thread_id=settings.bound_thread_id,
                chat_type=settings.bound_chat_type,
                bot_username="",
                bot_id=settings.bound_bot_id,
                telegram_user_id=profile.telegram_user_id,
                replace_existing=True,
            )
        for executor in self.executors:
            await executor.startup(client, self.storage)

    async def dispatch(self, client: object, event: object) -> bool:
        context = self._build_context(client, event)
        auto_added_bot_sender = False
        if context.chat_binding and context.sender_id and not context.is_bot_sender:
            auto_added_bot_sender = await self._maybe_add_hantianzun_bot(client, context)
            if auto_added_bot_sender and context.profile and context.chat_id is not None:
                refreshed_binding = self.storage.get_chat_binding(
                    context.profile.id,
                    context.chat_id,
                    thread_id=context.thread_id,
                )
                if refreshed_binding:
                    context.chat_binding = refreshed_binding
        if context.chat_binding and context.message_id:
            should_store_message = bool(context.is_outgoing)
            if not should_store_message:
                if auto_added_bot_sender or context.is_bot_sender:
                    should_store_message = await context.bot_message_targets_profile()
                else:
                    should_store_message = context.is_profile_owner()
            # 副本消息白名单存储：不限用户，所有 profile 的副本指令和 bot 回复链都存
            if not should_store_message and context.text:
                if not context.is_bot_sender:
                    should_store_message = is_dungeon_command_text(context.text)
                else:
                    should_store_message = _is_dungeon_reply_chain(
                        self.storage,
                        context.chat_id or 0,
                        context.reply_to_msg_id,
                    ) or is_dungeon_reply_text(context.text)
            # 股市 bot 消息无条件存储（不限用户）
            if not should_store_message and context.text:
                should_store_message = is_stock_related(context.text)
            # 非副本/非股市消息仅管理员 profile 存储
            if not should_store_message:
                should_store_message = is_authorized_profile(
                    self.storage, context.profile
                )
            if should_store_message:
                existing_message = self.storage.get_bound_message(
                    context.chat_id or 0,
                    context.message_id,
                    context.profile.id if context.profile else None,
                )
                sender = getattr(context.event, "sender", None)
                sender_username = (getattr(sender, "username", "") or "") or str(
                    (existing_message or {}).get("sender_username") or ""
                )
                is_bot_sender = context.is_bot_sender or bool(
                    (existing_message or {}).get("is_bot")
                ) or auto_added_bot_sender
                if not is_bot_sender:
                    is_bot_sender = self.storage.is_known_bot_sender(
                        context.chat_id or 0,
                        context.sender_id,
                        context.chat_binding.bot_username
                        if context.chat_binding
                        else "",
                        profile_id=context.profile.id if context.profile else None,
                    )
                if not is_bot_sender and context.chat_binding:
                    allowed_bot_ids = context.allowed_bot_ids
                    if context.sender_id is not None and int(context.sender_id) in allowed_bot_ids:
                        is_bot_sender = True
                self.storage.upsert_bound_message(
                    profile_id=context.profile.id if context.profile else None,
                    chat_id=context.chat_id or 0,
                    thread_id=context.thread_id,
                    message_id=context.message_id,
                    reply_to_msg_id=context.reply_to_msg_id,
                    sender_id=context.sender_id
                    or (existing_message or {}).get("sender_id"),
                    sender_username=sender_username,
                    direction="outgoing" if context.is_outgoing else "incoming",
                    is_bot=is_bot_sender,
                    text=context.text,
                )
                stored_message = self.storage.get_bound_message(
                    context.chat_id or 0,
                    context.message_id,
                    context.profile.id if context.profile else None,
                ) or {
                    "profile_id": context.profile.id if context.profile else None,
                    "chat_id": context.chat_id or 0,
                    "message_id": context.message_id,
                    "is_bot": is_bot_sender,
                    "text": context.text,
                }
                sync_stock_market_message(
                    self.storage,
                    stored_message,
                )
                if (
                    context.profile
                    and context.chat_id is not None
                    and is_bot_sender
                    and context.reply_to_msg_id
                ):
                    self.storage.confirm_outgoing_command_by_reply(
                        context.profile.id,
                        context.chat_id,
                        context.reply_to_msg_id,
                    )
                    try:
                        handle_tianxing_bot_reply(
                            self.storage,
                            profile_id=context.profile.id,
                            chat_id=context.chat_id,
                            text=context.text,
                            reply_to_msg_id=context.reply_to_msg_id,
                            message_id=context.message_id or 0,
                            thread_id=context.thread_id,
                        )
                    except Exception:
                        logger.exception(
                            "Tianxing observer failed for profile=%s chat=%s",
                            context.profile.id,
                            context.chat_id,
                        )
                    if _disable_xinggong_starboard_auto_on_insufficient_reply(
                        self.storage,
                        profile_id=context.profile.id,
                        chat_id=context.chat_id,
                        reply_to_msg_id=context.reply_to_msg_id,
                        reply_text=context.text,
                    ):
                        logger.warning(
                            "Disabled Xinggong starboard auto for profile=%s chat=%s reason=insufficient cultivation",
                            context.profile.id,
                            context.chat_id,
                        )
                    if _repair_companion_voyage_auto_on_return_waiting_reply(
                        self.storage,
                        profile_id=context.profile.id,
                        chat_id=context.chat_id,
                        reply_to_msg_id=context.reply_to_msg_id,
                        reply_text=context.text,
                    ):
                        logger.warning(
                            "Repaired companion voyage auto for profile=%s chat=%s reason=return waiting",
                            context.profile.id,
                            context.chat_id,
                        )
                    if _reschedule_pagoda_auto_on_failed_reply(
                        self.storage,
                        profile_id=context.profile.id,
                        chat_id=context.chat_id,
                        reply_to_msg_id=context.reply_to_msg_id,
                        reply_text=context.text,
                    ):
                        logger.warning(
                            "Rescheduled pagoda auto for profile=%s chat=%s reason=failed today",
                            context.profile.id,
                            context.chat_id,
                        )
                    if reschedule_artifact_touch_auto_on_reply(
                        self.storage,
                        profile_id=context.profile.id,
                        chat_id=context.chat_id,
                        reply_to_msg_id=int(context.reply_to_msg_id or 0),
                        reply_text=context.text,
                        reply_created_at=float(
                            (stored_message or {}).get("created_at") or time.time()
                        ),
                    ):
                        logger.warning(
                            "Rescheduled artifact touch auto for profile=%s chat=%s reason=bot cooldown reply",
                            context.profile.id,
                            context.chat_id,
                        )
        try:
            await observe_companion_heart_tribulation_event(context, self.storage)
        except Exception:
            logger.exception("Heart tribulation observer failed")
        try:
            observe_fishing_reply(context, self.storage)
        except Exception:
            logger.exception("Fishing observer failed")
        for executor in self.executors:
            try:
                handled = await executor.handle(context, self.storage)
            except Exception as exc:
                logger.exception("Executor %s failed", executor.key)
                continue
            if handled:
                return True
        return False

    def _build_context(self, client: object, event: object) -> EventContext:
        profile = self._resolve_runtime_profile()
        chat_binding = None
        module_settings: Dict[str, object] = {}
        if profile:
            self.storage.ensure_module_settings(
                profile.id, module_registry.list_modules()
            )
            module_settings = {
                setting.module_key: setting
                for setting in self.storage.list_module_settings(profile.id)
            }
            chat_id = getattr(event, "chat_id", None)
            if chat_id is not None:
                message = getattr(event, "message", None)
                reply_to = getattr(message, "reply_to", None) if message else None
                reply_to_msg_id = getattr(reply_to, "reply_to_msg_id", None)
                message_id = getattr(event, "id", None)
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
                if thread_id is None and message_id:
                    existing_message = self.storage.get_bound_message(
                        chat_id,
                        int(message_id),
                        profile_id=profile.id,
                    )
                    if existing_message and existing_message.get("thread_id") is not None:
                        thread_id = int(existing_message.get("thread_id") or 0) or None
                chat_binding = self.storage.resolve_chat_binding_for_event(
                    profile.id, chat_id, thread_id, reply_to_msg_id
                )
        return EventContext(
            client=client,
            event=event,
            profile=profile,
            chat_binding=chat_binding,
            module_settings=module_settings,
            runtime_profile_id=self.runtime_profile_id,
        )

    async def _maybe_add_hantianzun_bot(
        self, client: object, context: EventContext
    ) -> bool:
        if not context.profile or context.chat_id is None or context.sender_id is None:
            return False
        sender = getattr(context.event, "sender", None)
        if sender is None:
            try:
                sender = await context.event.get_sender()
            except Exception:
                sender = None
        if not sender or not bool(getattr(sender, "bot", False)):
            return False
        if _sender_first_name(sender) != "韩天尊":
            return False
        custom_title = await self._get_sender_custom_title(client, context, sender)
        if "天尊" not in custom_title:
            return False
        binding = self.storage.add_chat_binding_bot_id(
            context.profile.id,
            context.chat_id,
            context.sender_id,
            bot_username=getattr(sender, "username", "") or "",
            thread_id=context.thread_id,
        )
        return binding is not None

    async def _get_sender_custom_title(
        self, client: object, context: EventContext, sender: object
    ) -> str:
        direct_title = str(getattr(sender, "title", "") or "").strip()
        if direct_title:
            return direct_title
        chat = None
        try:
            chat = await context.event.get_chat()
        except Exception:
            chat = None
        if chat is None:
            chat = context.chat_id
        try:
            permissions = await client.get_permissions(chat, sender)
            title = _custom_title_from_permissions(permissions)
            if title:
                return title
        except Exception:
            pass
        try:
            permissions = await client.get_permissions(chat, context.sender_id)
            title = _custom_title_from_permissions(permissions)
            if title:
                return title
        except Exception:
            pass
        try:
            from telethon import functions
            result = await client(
                functions.channels.GetParticipantRequest(
                    channel=chat,
                    participant=sender,
                )
            )
            title = str(getattr(result.participant, "custom_title", "") or "").strip()
            if title:
                return title
        except Exception:
            pass
        try:
            from telethon import functions
            result = await client(
                functions.channels.GetParticipantRequest(
                    channel=chat,
                    participant=context.sender_id,
                )
            )
            return str(getattr(result.participant, "custom_title", "") or "").strip()
        except Exception:
            return ""

    def _resolve_runtime_profile(self):
        if self.runtime_profile_id is not None:
            return self.storage.get_profile(self.runtime_profile_id)
        return self.storage.get_active_profile()


def build_router(storage: Storage, runtime_profile_id: Optional[int] = None) -> Router:
    return Router(
        storage=storage,
        executors=[FanrenExecutor(), SectExecutor(), GeneralGameExecutor()],
        runtime_profile_id=runtime_profile_id,
    )
