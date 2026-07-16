import json
import re
import time
import uuid
from datetime import datetime, timezone, timedelta

from tg_game import pagoda_auto
from tg_game.features.estate import biz_estate_hunt_daily_auto
from tg_game.features.estate.biz_estate_miniapp import (
    is_estate_miniapp_hunt_limit_reached,
    mark_estate_miniapp_hunt_limit_reached,
    queue_estate_miniapp_hunt_request,
)
from tg_game.features.tianji_trial import queue_tianji_trial_request
from tg_game.features.tianji_trial import biz_tianji_trial_daily_auto
from tg_game.storage import OUTGOING_CONFIRM_TIMEOUT_SECONDS, Storage


STATE_KEY = "admin_global_execution"
DEFAULT_BOT_USERNAME = "fanrenxiuxian_bot"
PAGODA_COMMAND = ".闯塔"
PAGODA_PROFILE_INTERVAL_SECONDS = 15
BATCH_TIMEOUT_SECONDS = 15 * 60
TERMINAL_STATUSES = {"success", "failed", "skipped"}
ACTIVE_OUTGOING_STATUSES = {"pending", "sending", "awaiting_confirm"}
SHANGHAI_TZ = timezone(timedelta(hours=8))
SCHEDULE_POLL_SECONDS = 15

TASKS = {
    "estate": {
        "title": "洞府巡宝",
        "button": "敕令诸元神·洞府巡宝",
        "feature_key": biz_estate_hunt_daily_auto.FEATURE_KEY,
        "default_run_time": biz_estate_hunt_daily_auto.DEFAULT_RUN_TIME,
    },
    "tianji": {
        "title": "天机问阵",
        "button": "敕令诸元神·天机问阵",
        "feature_key": biz_tianji_trial_daily_auto.FEATURE_KEY,
        "default_run_time": biz_tianji_trial_daily_auto.DEFAULT_RUN_TIME,
    },
    "pagoda": {
        "title": "古塔问道",
        "button": "敕令诸元神·古塔问道",
        "feature_key": pagoda_auto.FEATURE_KEY,
        "default_run_time": pagoda_auto.DEFAULT_RUN_TIME,
    },
}


class BatchBusyError(RuntimeError):
    pass


def _empty_state() -> dict:
    return {
        "active_kind": "",
        "batches": {},
        "schedules": {
            kind: {
                "enabled": False,
                "run_time": task["default_run_time"],
                "last_started_day": "",
                "last_started_at": 0,
            }
            for kind, task in TASKS.items()
        },
    }


def _load_state(storage: Storage) -> dict:
    try:
        state = json.loads(storage.get_runtime_state(STATE_KEY) or "{}")
    except (TypeError, json.JSONDecodeError):
        state = {}
    if not isinstance(state, dict):
        return _empty_state()
    batches = state.get("batches")
    if not isinstance(batches, dict):
        batches = {}
    raw_schedules = state.get("schedules")
    if not isinstance(raw_schedules, dict):
        raw_schedules = {}
    schedules = {}
    for kind, task in TASKS.items():
        raw = raw_schedules.get(kind)
        raw = raw if isinstance(raw, dict) else {}
        schedules[kind] = {
            "enabled": bool(raw.get("enabled")),
            "run_time": pagoda_auto.normalize_run_time(
                raw.get("run_time") or task["default_run_time"]
            ),
            "last_started_day": str(raw.get("last_started_day") or ""),
            "last_started_at": float(raw.get("last_started_at") or 0),
        }
    return {
        "active_kind": str(state.get("active_kind") or ""),
        "batches": batches,
        "schedules": schedules,
    }


def _save_state(storage: Storage, state: dict) -> None:
    storage.set_runtime_state(
        STATE_KEY,
        json.dumps(state, ensure_ascii=False, separators=(",", ":")),
    )


def _load_external(storage: Storage, profile_id: int) -> tuple[dict, dict]:
    account = storage.get_external_account(int(profile_id), "asc_aiopenai") or {}
    try:
        payload = json.loads(account.get("me_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        payload = {}
    return account, payload if isinstance(payload, dict) else {}


def _profile_display_name(profile) -> str:
    name = str(getattr(profile, "name", "") or f"Profile {profile.id}")
    return re.sub(r"-\d+$", "", name) or f"Profile {profile.id}"


def _target_for_profile(
    storage: Storage,
    profile_id: int,
    *,
    fallback_chat_id: int,
    fallback_thread_id: int | None,
    fallback_chat_type: str,
) -> dict:
    binding = storage.get_primary_chat_binding(
        int(profile_id), bot_username=DEFAULT_BOT_USERNAME
    ) or storage.get_primary_chat_binding(int(profile_id))
    return {
        "chat_id": int(binding.chat_id if binding else fallback_chat_id or 0),
        "thread_id": binding.thread_id if binding else fallback_thread_id,
        "chat_type": str(
            binding.chat_type if binding else fallback_chat_type or "group"
        ),
        "bot_username": str(
            binding.bot_username if binding and binding.bot_username else DEFAULT_BOT_USERNAME
        ),
    }


def _new_item(profile, target: dict, now: float) -> dict:
    return {
        "profile_id": int(profile.id),
        "profile_name": _profile_display_name(profile),
        "status": "queued",
        "reward": "—",
        "queued_at": now,
        "chat_id": int(target.get("chat_id") or 0),
        "thread_id": target.get("thread_id"),
        "command_id": 0,
        "scheduled_at": 0,
    }


def _profile_ready(
    profile,
    account: dict,
    target: dict,
    *,
    require_external_account: bool = True,
) -> bool:
    if not int(target.get("chat_id") or 0):
        return False
    if not str(getattr(profile, "telegram_session_name", "") or "").strip():
        return False
    if not getattr(profile, "telegram_verified_at", None):
        return False
    return bool(account) if require_external_account else True


def _local_now(now: float | None = None) -> datetime:
    return datetime.fromtimestamp(float(now or time.time()), tz=timezone.utc).astimezone(
        SHANGHAI_TZ
    )


def _day_key(now: float | None = None) -> str:
    return _local_now(now).date().isoformat()


def _tianji_completed_today(payload: dict, now: float | None = None) -> bool:
    trial = (
        payload.get("tianji_trial")
        if isinstance(payload.get("tianji_trial"), dict)
        else {}
    )
    run = trial.get("miniapp_run") if isinstance(trial.get("miniapp_run"), dict) else {}
    if str(run.get("status") or "") != "settled" and not bool(run.get("ok")):
        return False
    updated_at = str(run.get("updated_at") or "")
    if not updated_at:
        rounds = run.get("rounds") if isinstance(run.get("rounds"), list) else []
        updated_at = str((rounds[-1] if rounds else {}).get("updated_at") or "")
    return updated_at[:10] == _day_key(now)


def _pagoda_succeeded_today(
    storage: Storage,
    profile_id: int,
    chat_id: int,
    *,
    now: float | None = None,
) -> bool:
    current = _local_now(now)
    day_start = current.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    messages = storage.list_bound_messages(
        profile_id=int(profile_id),
        chat_id=int(chat_id),
        search_query=PAGODA_COMMAND,
        limit=500,
    )
    for command in messages:
        if (
            str(command.get("direction") or "") != "outgoing"
            or str(command.get("text") or "").strip() != PAGODA_COMMAND
            or float(command.get("created_at") or 0) < day_start
        ):
            continue
        reply = storage.get_latest_bot_reply_message(
            int(chat_id),
            int(command.get("message_id") or 0),
            int(profile_id),
        )
        reply_text = str((reply or {}).get("text") or "")
        if reply_text and "今日已挑战失败" not in reply_text:
            return True
    return False


def _start_estate_item(storage: Storage, profile, item: dict) -> None:
    account, _payload = _load_external(storage, profile.id)
    if not _profile_ready(profile, account, item):
        item["status"] = "failed"
        return
    limit_reached = False

    def queue_request(latest: dict) -> dict:
        nonlocal limit_reached
        if is_estate_miniapp_hunt_limit_reached(latest):
            limit_reached = True
            return mark_estate_miniapp_hunt_limit_reached(latest)
        return queue_estate_miniapp_hunt_request(
            latest,
            chat_id=item["chat_id"],
            thread_id=item["thread_id"],
            chat_type=item["chat_type"],
            bot_username=item["bot_username"],
        )

    storage.update_external_account_payload(
        int(profile.id),
        "asc_aiopenai",
        queue_request,
    )
    if limit_reached:
        item["status"] = "skipped"


def _start_tianji_item(storage: Storage, profile, item: dict) -> None:
    account, _payload = _load_external(storage, profile.id)
    if not _profile_ready(profile, account, item):
        item["status"] = "failed"
        return
    completed_today = False

    def queue_request(latest: dict) -> dict:
        nonlocal completed_today
        if _tianji_completed_today(latest):
            completed_today = True
            return latest
        return queue_tianji_trial_request(
            latest,
            chat_id=item["chat_id"],
            thread_id=item["thread_id"],
            chat_type=item["chat_type"],
            bot_username=item["bot_username"],
        )

    storage.update_external_account_payload(
        int(profile.id),
        "asc_aiopenai",
        queue_request,
    )
    if completed_today:
        item["status"] = "skipped"


def _start_pagoda_item(
    storage: Storage,
    profile,
    item: dict,
    *,
    delay_seconds: int,
) -> None:
    account, _payload = _load_external(storage, profile.id)
    if not _profile_ready(
        profile,
        account,
        item,
        require_external_account=False,
    ):
        item["status"] = "failed"
        return
    if _pagoda_succeeded_today(
        storage,
        profile.id,
        item["chat_id"],
    ):
        item["status"] = "skipped"
        return
    latest = storage.get_latest_outgoing_command(
        item["chat_id"],
        profile_id=profile.id,
        text=PAGODA_COMMAND,
        thread_id=item["thread_id"],
    )
    if latest and str(latest.get("status") or "") in ACTIVE_OUTGOING_STATUSES:
        item["command_id"] = int(latest["id"])
        item["scheduled_at"] = float(latest.get("scheduled_at") or 0)
        return
    item["command_id"] = storage.enqueue_outgoing_command(
        profile_id=profile.id,
        chat_id=item["chat_id"],
        text=PAGODA_COMMAND,
        thread_id=item["thread_id"],
        chat_type=item["chat_type"],
        bot_username=item["bot_username"],
        delay_seconds=delay_seconds,
    )
    item["scheduled_at"] = item["queued_at"] + delay_seconds


def start_batch(
    storage: Storage,
    kind: str,
    profiles: list,
    *,
    fallback_chat_id: int = 0,
    fallback_thread_id: int | None = None,
    fallback_chat_type: str = "group",
    source: str = "manual",
) -> dict:
    if kind not in TASKS:
        raise ValueError("Unknown global execution task")
    state = refresh_state(storage)
    if state.get("active_kind"):
        raise BatchBusyError("已有全局任务正在执行")

    now = time.time()
    items = []
    for index, profile in enumerate(sorted(profiles, key=lambda value: int(value.id))):
        target = _target_for_profile(
            storage,
            profile.id,
            fallback_chat_id=fallback_chat_id,
            fallback_thread_id=fallback_thread_id,
            fallback_chat_type=fallback_chat_type,
        )
        item = _new_item(profile, target, now)
        item["chat_type"] = target["chat_type"]
        item["bot_username"] = target["bot_username"]
        if kind == "estate":
            _start_estate_item(storage, profile, item)
        elif kind == "tianji":
            _start_tianji_item(storage, profile, item)
        else:
            _start_pagoda_item(
                storage,
                profile,
                item,
                delay_seconds=index * PAGODA_PROFILE_INTERVAL_SECONDS,
            )
        items.append(item)

    batch = {
        "id": uuid.uuid4().hex,
        "kind": kind,
        "status": "running",
        "source": str(source or "manual"),
        "started_at": now,
        "finished_at": 0,
        "items": items,
    }
    state["batches"][kind] = batch
    state["active_kind"] = kind if any(
        item["status"] not in TERMINAL_STATUSES for item in items
    ) else ""
    if not state["active_kind"]:
        batch["status"] = "completed"
        batch["finished_at"] = now
    _save_state(storage, state)
    return state


def is_schedule_enabled(storage: Storage, kind: str) -> bool:
    if kind not in TASKS:
        return False
    return bool(_load_state(storage)["schedules"][kind]["enabled"])


def managed_state(storage: Storage) -> dict:
    schedules = _load_state(storage)["schedules"]
    return {kind: bool(schedule["enabled"]) for kind, schedule in schedules.items()}


def disable_profile_automations(storage: Storage, kind: str, profiles: list) -> int:
    if kind not in TASKS:
        raise ValueError("Unknown global execution task")
    feature_key = TASKS[kind]["feature_key"]
    disabled = 0
    for profile in profiles:
        for task in storage.list_active_companion_auto_tasks(int(profile.id)):
            if str(task.get("feature_key") or "") != feature_key:
                continue
            storage.update_companion_auto_task(
                int(task["id"]),
                enabled=0,
                next_run_at=0,
                last_error="已由“诸元神巡令”统一托管。",
            )
            disabled += 1
            commands = []
            if kind == "tianji":
                commands = [
                    biz_tianji_trial_daily_auto.REMNANT_COMMAND,
                    biz_tianji_trial_daily_auto.TRIAL_COMMAND,
                ]
            elif kind == "pagoda":
                commands = [PAGODA_COMMAND]
            for command in commands:
                storage.cancel_pending_outgoing_commands(
                    int(profile.id),
                    int(task.get("chat_id") or 0),
                    text=command,
                    thread_id=task.get("thread_id"),
                    require_exact_thread=True,
                )
    return disabled


def set_schedule(
    storage: Storage,
    kind: str,
    *,
    enabled: bool,
    run_time: str,
    profiles: list,
    now: float | None = None,
) -> dict:
    if kind not in TASKS:
        raise ValueError("Unknown global execution task")
    state = refresh_state(storage)
    schedule = state["schedules"][kind]
    normalized_time = pagoda_auto.normalize_run_time(run_time)
    was_enabled = bool(schedule.get("enabled"))
    time_changed = normalized_time != str(schedule.get("run_time") or "")
    schedule["enabled"] = bool(enabled)
    schedule["run_time"] = normalized_time
    if enabled and (not was_enabled or time_changed):
        current = _local_now(now)
        if current.strftime("%H:%M") >= normalized_time:
            schedule["last_started_day"] = current.date().isoformat()
    _save_state(storage, state)
    if enabled:
        disable_profile_automations(storage, kind, profiles)
    return state


def run_due_schedule(
    storage: Storage,
    profiles: list,
    *,
    fallback_chat_id: int = 0,
    fallback_thread_id: int | None = None,
    fallback_chat_type: str = "group",
    now: float | None = None,
) -> str:
    state = refresh_state(storage)
    if state.get("active_kind"):
        return ""
    current = _local_now(now)
    today = current.date().isoformat()
    current_time = current.strftime("%H:%M")
    for kind in ("estate", "tianji", "pagoda"):
        schedule = state["schedules"][kind]
        if not schedule.get("enabled"):
            continue
        disable_profile_automations(storage, kind, profiles)
        if schedule.get("last_started_day") == today:
            continue
        if current_time < str(schedule.get("run_time") or "00:05"):
            continue
        start_batch(
            storage,
            kind,
            profiles,
            fallback_chat_id=fallback_chat_id,
            fallback_thread_id=fallback_thread_id,
            fallback_chat_type=fallback_chat_type,
            source="schedule",
        )
        state = _load_state(storage)
        schedule = state["schedules"][kind]
        schedule["last_started_day"] = today
        schedule["last_started_at"] = float(now or time.time())
        _save_state(storage, state)
        return kind
    return ""


def _estate_reward(hunt: dict) -> str:
    reward = str(
        hunt.get("automation_total_loot_text") or hunt.get("loot_text") or ""
    ).strip()
    contribution = int(
        hunt.get("automation_total_contribution") or hunt.get("contribution") or 0
    )
    parts = []
    if reward and reward != "-":
        parts.append(reward)
    if contribution:
        parts.append(f"贡献 +{contribution}")
    return "、".join(parts) or "—"


def _refresh_estate_item(storage: Storage, item: dict) -> None:
    _account, payload = _load_external(storage, item["profile_id"])
    dongfu = payload.get("dongfu") if isinstance(payload.get("dongfu"), dict) else {}
    request = (
        dongfu.get("miniapp_hunt_request")
        if isinstance(dongfu.get("miniapp_hunt_request"), dict)
        else {}
    )
    hunt = dongfu.get("miniapp_hunt") if isinstance(dongfu.get("miniapp_hunt"), dict) else {}
    status = str(hunt.get("status") or "").strip()
    request_status = str(request.get("status") or "").strip()
    if request and request_status == "queued":
        item["status"] = "queued"
        return
    if request and request_status == "resolving":
        item["status"] = "resolving"
        return
    if request and request_status == "running":
        item["status"] = "running"
        return
    if status == "limit_reached":
        item["status"] = "skipped"
        return
    if status == "failed":
        item["status"] = "failed"
        return
    if status and status != "queued":
        item["status"] = "success"
        item["reward"] = _estate_reward(hunt)


def _refresh_tianji_item(storage: Storage, item: dict) -> None:
    _account, payload = _load_external(storage, item["profile_id"])
    trial = (
        payload.get("tianji_trial")
        if isinstance(payload.get("tianji_trial"), dict)
        else {}
    )
    request = trial.get("miniapp_request") if isinstance(trial.get("miniapp_request"), dict) else {}
    run = trial.get("miniapp_run") if isinstance(trial.get("miniapp_run"), dict) else {}
    request_status = str(request.get("status") or "").strip()
    if request and request_status == "queued":
        item["status"] = "queued"
        return
    if request and request_status == "resolving":
        item["status"] = "resolving"
        return
    if request and request_status == "running":
        item["status"] = "running"
        return
    status = str(run.get("status") or "").strip()
    error = str(run.get("error") or "")
    completed = int(run.get("completed_runs") or 0)
    reward = int(run.get("reward_trace") or 0)
    if status == "settled" or bool(run.get("ok")):
        item["status"] = "success" if completed or reward else "skipped"
        item["reward"] = f"残痕 +{reward}" if reward else "—"
        return
    if status and status not in {"idle", "queued"}:
        item["status"] = (
            "skipped"
            if any(marker in error for marker in ("上限", "已完成", "次数已满"))
            else "failed"
        )


def _pagoda_reply(storage: Storage, item: dict) -> dict:
    queued_at = float(item.get("queued_at") or 0)
    messages = storage.list_bound_messages(
        profile_id=item["profile_id"],
        chat_id=item["chat_id"],
        search_query=PAGODA_COMMAND,
        limit=50,
    )
    command = next(
        (
            message
            for message in messages
            if str(message.get("direction") or "") == "outgoing"
            and str(message.get("text") or "").strip() == PAGODA_COMMAND
            and float(message.get("created_at") or 0) >= queued_at - 1
        ),
        None,
    )
    if not command:
        return {}
    return storage.get_latest_bot_reply_message(
        item["chat_id"],
        int(command.get("message_id") or 0),
        item["profile_id"],
    ) or {}


def _pagoda_reward(reply_text: str) -> str:
    lines = []
    for line in str(reply_text or "").splitlines():
        normalized = line.strip().lstrip("- ").strip()
        if normalized.startswith(("修为 ", "宗门贡献", "获得了", "威望 ")):
            lines.append(normalized)
    return "、".join(lines) or "—"


def _refresh_pagoda_item(storage: Storage, item: dict) -> None:
    command = storage.get_outgoing_command(int(item.get("command_id") or 0))
    if not command:
        item["status"] = "failed"
        return
    status = str(command.get("status") or "").strip()
    if status in ACTIVE_OUTGOING_STATUSES:
        item["status"] = "running"
        return
    if status in {"failed", "needs_manual_confirm"}:
        item["status"] = "failed"
        return
    if status in {"confirmed", "sent"}:
        reply = _pagoda_reply(storage, item)
        reply_text = str(reply.get("text") or "")
        item["status"] = "failed" if "今日已挑战失败" in reply_text else "success"
        item["reward"] = _pagoda_reward(reply_text)


def _backfill_pagoda_rewards(storage: Storage, state: dict) -> bool:
    batch = state.get("batches", {}).get("pagoda")
    if not isinstance(batch, dict):
        return False
    changed = False
    for item in batch.get("items") or []:
        if item.get("status") != "success" or str(item.get("reward") or "—") != "—":
            continue
        reply = _pagoda_reply(storage, item)
        reward = _pagoda_reward(reply.get("text") or "")
        if reward == "—":
            continue
        item["reward"] = reward
        changed = True
    return changed


def refresh_state(storage: Storage) -> dict:
    state = _load_state(storage)
    pagoda_reward_updated = _backfill_pagoda_rewards(storage, state)
    active_kind = state.get("active_kind")
    batch = state["batches"].get(active_kind) if active_kind else None
    if not isinstance(batch, dict) or batch.get("status") != "running":
        state["active_kind"] = ""
        if pagoda_reward_updated:
            _save_state(storage, state)
        return state

    now = time.time()
    timed_out = now - float(batch.get("started_at") or 0) >= BATCH_TIMEOUT_SECONDS
    for item in batch.get("items") or []:
        if item.get("status") in TERMINAL_STATUSES:
            continue
        if timed_out:
            item["status"] = "failed"
            continue
        if active_kind == "estate":
            _refresh_estate_item(storage, item)
        elif active_kind == "tianji":
            _refresh_tianji_item(storage, item)
        else:
            _refresh_pagoda_item(storage, item)

    if all(
        item.get("status") in TERMINAL_STATUSES
        for item in batch.get("items") or []
    ):
        batch["status"] = "completed"
        batch["finished_at"] = now
        state["active_kind"] = ""
    _save_state(storage, state)
    return state


def _time_text(value: object) -> str:
    try:
        timestamp = float(value or 0)
    except (TypeError, ValueError):
        timestamp = 0
    if not timestamp:
        return "—"
    return datetime.fromtimestamp(
        timestamp,
        tz=timezone.utc,
    ).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")


def _schedule_view(schedule: dict, *, now: float | None = None) -> dict:
    current = _local_now(now)
    run_time = pagoda_auto.normalize_run_time(schedule.get("run_time"))
    hour, minute = (int(part) for part in run_time.split(":"))
    enabled = bool(schedule.get("enabled"))
    next_run_at = 0.0
    next_run_display = "未开启"
    if enabled:
        today = current.date().isoformat()
        target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if schedule.get("last_started_day") != today and current < target:
            next_run_at = target.timestamp()
            next_run_display = target.strftime("%Y-%m-%d %H:%M")
        elif schedule.get("last_started_day") != today:
            next_run_display = "等待调度"
        else:
            target += timedelta(days=1)
            next_run_at = target.timestamp()
            next_run_display = target.strftime("%Y-%m-%d %H:%M")
    return {
        "enabled": enabled,
        "run_time": run_time,
        "last_run_at": float(schedule.get("last_started_at") or 0),
        "last_run_display": _time_text(schedule.get("last_started_at")),
        "next_run_at": next_run_at,
        "next_run_display": next_run_display,
    }


def _card_view(kind: str, batch: dict | None, schedule: dict) -> dict:
    raw_items = list((batch or {}).get("items") or [])
    items = []
    for item in raw_items:
        status = str(item.get("status") or "queued")
        items.append(
            {
                "profile_name": item.get("profile_name") or f"Profile {item.get('profile_id')}",
                "status": status,
                "status_label": {
                    "queued": (
                        "等待入口" if kind in {"estate", "tianji"} else "等待发送"
                    ),
                    "resolving": "获取入口",
                    "running": (
                        "正在寻宝"
                        if kind == "estate"
                        else "正在试炼"
                        if kind == "tianji"
                        else "执行中"
                    ),
                    "success": "成功",
                    "failed": "失败",
                    "skipped": "无需执行",
                }.get(status, "等待执行"),
                "reward": item.get("reward") or "—",
            }
        )
    counts = {
        key: sum(item.get("status") == key for item in raw_items)
        for key in (
            "queued",
            "resolving",
            "running",
            "success",
            "failed",
            "skipped",
        )
    }
    done = counts["success"] + counts["failed"] + counts["skipped"]
    return {
        "kind": kind,
        **TASKS[kind],
        "status": str((batch or {}).get("status") or "idle"),
        "status_label": (
            "执行中"
            if (batch or {}).get("status") == "running"
            else "已完成"
            if batch
            else "未执行"
        ),
        "started_at": _time_text((batch or {}).get("started_at")),
        "total": len(raw_items),
        "done": done,
        "counts": counts,
        "items": items,
        "schedule": _schedule_view(schedule),
    }


def build_dashboard(storage: Storage) -> dict:
    state = refresh_state(storage)
    cards = [
        _card_view(
            kind,
            state["batches"].get(kind),
            state["schedules"][kind],
        )
        for kind in ("estate", "tianji", "pagoda")
    ]
    active_kind = state.get("active_kind") or ""
    active_card = next((card for card in cards if card["kind"] == active_kind), None)
    loading_message = ""
    if active_card:
        loading_message = (
            f"正在执行{active_card['title']}：已完成 {active_card['done']}/{active_card['total']}，"
            f"成功 {active_card['counts']['success']}，失败 {active_card['counts']['failed']}，"
            f"无需执行 {active_card['counts']['skipped']}"
        )
    return {
        "active": bool(active_kind),
        "active_kind": active_kind,
        "loading_message": loading_message,
        "cards": cards,
    }
