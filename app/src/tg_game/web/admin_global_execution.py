import json
import re
import time
import uuid
from datetime import datetime, timezone, timedelta

from tg_game import pagoda_auto
from tg_game.features.beast_merge import biz_beast_merge_daily_auto
from tg_game.features.beast_merge import biz_beast_merge_state
from tg_game.features.estate import biz_estate_hunt_daily_auto
from tg_game.features.estate.biz_estate_miniapp import (
    is_estate_miniapp_hunt_limit_reached,
    mark_estate_miniapp_hunt_limit_reached,
    queue_estate_miniapp_hunt_request,
)
from tg_game.features.pagoda import biz_pagoda_state as pagoda_state
from tg_game.features.tianji_trial import queue_tianji_trial_request
from tg_game.features.tianji_trial import biz_tianji_trial_daily_auto
from tg_game.features.wild_experience import (
    biz_wild_experience_miniapp as wild_experience_miniapp,
)
from tg_game.storage import Storage


STATE_KEY = "admin_global_execution"
DEFAULT_BOT_USERNAME = "fanrenxiuxian_bot"
PAGODA_COMMAND = pagoda_auto.COMMAND
BATCH_TIMEOUT_SECONDS = 15 * 60
PAGODA_BATCH_TIMEOUT_SECONDS = 30 * 60
BEAST_MERGE_BATCH_TIMEOUT_SECONDS = 30 * 60
WILD_EXPERIENCE_BATCH_TIMEOUT_SECONDS = 30 * 60
TERMINAL_STATUSES = {"success", "failed", "skipped"}
SHANGHAI_TZ = timezone(timedelta(hours=8))
SCHEDULE_POLL_SECONDS = 15
TASK_ORDER = ("estate", "tianji", "pagoda", "beast_merge", "wild_experience")

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
    "beast_merge": {
        "title": "噬金虫进化",
        "button": "敕令诸元神·噬金虫进化",
        "feature_key": biz_beast_merge_daily_auto.FEATURE_KEY,
        "default_run_time": biz_beast_merge_daily_auto.DEFAULT_RUN_TIME,
    },
    "wild_experience": {
        "title": "野外历练",
        "button": "敕令诸元神·野外历练",
        "feature_key": wild_experience_miniapp.FEATURE_KEY,
        "default_run_time": wild_experience_miniapp.DEFAULT_RUN_TIME,
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
                "strategy": "均衡" if kind == "wild_experience" else "",
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
            "strategy": (
                wild_experience_miniapp.normalize_strategy(raw.get("strategy"))
                if kind == "wild_experience"
                else ""
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
        "phase": "waiting_previous",
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


def _tianji_reward(payload: dict) -> str:
    trial = (
        payload.get("tianji_trial")
        if isinstance(payload.get("tianji_trial"), dict)
        else {}
    )
    run = trial.get("miniapp_run") if isinstance(trial.get("miniapp_run"), dict) else {}
    reward = int(run.get("reward_trace") or 0)
    return f"残痕 +{reward}" if reward else "—"


def _pagoda_reward(payload: dict) -> str:
    reward_lines = pagoda_state.build_pagoda_miniapp_view(payload).get("reward_lines") or []
    return "、".join(str(line) for line in reward_lines if str(line).strip()) or "—"


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

    updated_payload = storage.update_external_account_payload(
        int(profile.id),
        "asc_aiopenai",
        queue_request,
    )
    if limit_reached:
        item["status"] = "skipped"
        dongfu = (
            updated_payload.get("dongfu")
            if isinstance(updated_payload.get("dongfu"), dict)
            else {}
        )
        hunt = (
            dongfu.get("miniapp_hunt")
            if isinstance(dongfu.get("miniapp_hunt"), dict)
            else {}
        )
        item["reward"] = _estate_reward(hunt)


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

    updated_payload = storage.update_external_account_payload(
        int(profile.id),
        "asc_aiopenai",
        queue_request,
    )
    if completed_today:
        item["status"] = "skipped"
        item["reward"] = _tianji_reward(updated_payload)


def _start_pagoda_item(
    storage: Storage,
    profile,
    item: dict,
) -> None:
    item["scheduled_at"] = time.time()
    item["phase"] = "queued"
    account, payload = _load_external(storage, profile.id)
    if not _profile_ready(profile, account, item):
        item["status"] = "failed"
        return
    completed_today = pagoda_state.was_pagoda_completed_today(payload)
    if completed_today or pagoda_auto.attempted_today_from_payload(
        payload,
        now=time.time(),
    ):
        item["status"] = "skipped"
        if completed_today:
            item["reward"] = _pagoda_reward(payload)
        return
    storage.cancel_pending_outgoing_commands(
        int(profile.id),
        int(item["chat_id"]),
        text=PAGODA_COMMAND,
        thread_id=item["thread_id"],
        require_exact_thread=True,
    )
    queued_payload = storage.update_external_account_payload(
        int(profile.id),
        "asc_aiopenai",
        lambda latest: pagoda_state.queue_pagoda_request(
            latest,
            chat_id=item["chat_id"],
            thread_id=item["thread_id"],
            chat_type=item["chat_type"],
            bot_username=item["bot_username"],
        ),
    )
    if not pagoda_state.has_active_pagoda_request(queued_payload):
        item["status"] = "failed"
        return


def _dispatch_next_pagoda_item(storage: Storage, items: list[dict]) -> None:
    for item in items:
        if item.get("status") in TERMINAL_STATUSES:
            continue
        if float(item.get("scheduled_at") or 0) > 0:
            return
        profile = storage.get_profile(int(item.get("profile_id") or 0))
        if profile is None:
            item["status"] = "failed"
            item["scheduled_at"] = time.time()
            continue
        _start_pagoda_item(storage, profile, item)
        if item.get("status") not in TERMINAL_STATUSES:
            return


def _start_beast_merge_item(storage: Storage, profile, item: dict) -> None:
    account, _payload = _load_external(storage, profile.id)
    if not _profile_ready(profile, account, item):
        item["status"] = "failed"
        return
    limit_reached = False

    def queue_request(latest: dict) -> dict:
        nonlocal limit_reached
        if biz_beast_merge_state.is_beast_merge_daily_limit_reached(latest):
            limit_reached = True
            return latest
        return biz_beast_merge_state.queue_beast_merge_request(
            latest,
            chat_id=item["chat_id"],
            thread_id=item["thread_id"],
            chat_type=item["chat_type"],
            bot_username=item["bot_username"],
        )

    updated_payload = storage.update_external_account_payload(
        int(profile.id),
        "asc_aiopenai",
        queue_request,
    )
    if limit_reached:
        item["status"] = "skipped"
        item["reward"] = _beast_merge_reward(updated_payload)


def _start_wild_experience_item(
    storage: Storage,
    profile,
    item: dict,
    *,
    strategy: str,
) -> None:
    item["scheduled_at"] = time.time()
    item["phase"] = "queued"
    account, payload = _load_external(storage, profile.id)
    if not _profile_ready(profile, account, item):
        item["status"] = "failed"
        return
    if wild_experience_miniapp.is_completed_today(payload):
        item["status"] = "skipped"
        item["reward"] = wild_experience_miniapp.build_reward_summary(payload)
        return
    queued_payload = storage.update_external_account_payload(
        int(profile.id),
        "asc_aiopenai",
        lambda latest: wild_experience_miniapp.queue_request(
            latest,
            strategy=strategy,
            chat_id=item["chat_id"],
            thread_id=item["thread_id"],
            chat_type=item["chat_type"],
            bot_username=item["bot_username"],
        ),
    )
    if not wild_experience_miniapp.get_active_request(queued_payload):
        item["status"] = "failed"


def _dispatch_next_wild_experience_item(
    storage: Storage,
    items: list[dict],
    *,
    strategy: str,
) -> None:
    for item in items:
        if item.get("status") in TERMINAL_STATUSES:
            continue
        if float(item.get("scheduled_at") or 0) > 0:
            return
        profile = storage.get_profile(int(item.get("profile_id") or 0))
        if profile is None:
            item["status"] = "failed"
            item["scheduled_at"] = time.time()
            continue
        _start_wild_experience_item(
            storage,
            profile,
            item,
            strategy=strategy,
        )
        if item.get("status") not in TERMINAL_STATUSES:
            return


def start_batch(
    storage: Storage,
    kind: str,
    profiles: list,
    *,
    fallback_chat_id: int = 0,
    fallback_thread_id: int | None = None,
    fallback_chat_type: str = "group",
    source: str = "manual",
    strategy: str = "均衡",
) -> dict:
    if kind not in TASKS:
        raise ValueError("Unknown global execution task")
    state = refresh_state(storage)
    if state.get("active_kind"):
        raise BatchBusyError("已有全局任务正在执行")
    normalized_strategy = wild_experience_miniapp.normalize_strategy(strategy)
    if kind == "wild_experience":
        disable_profile_automations(storage, kind, profiles)

    now = time.time()
    items = []
    for profile in sorted(profiles, key=lambda value: int(value.id)):
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
        elif kind == "beast_merge":
            _start_beast_merge_item(storage, profile, item)
        items.append(item)

    if kind == "pagoda":
        _dispatch_next_pagoda_item(storage, items)
    elif kind == "wild_experience":
        _dispatch_next_wild_experience_item(
            storage,
            items,
            strategy=normalized_strategy,
        )

    batch = {
        "id": uuid.uuid4().hex,
        "kind": kind,
        "status": "running",
        "source": str(source or "manual"),
        "strategy": normalized_strategy if kind == "wild_experience" else "",
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
            elif kind == "wild_experience":
                commands = [
                    f".野外历练 {strategy}"
                    for strategy in wild_experience_miniapp.STRATEGY_OPTIONS
                ]
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
    strategy: str = "均衡",
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
    if kind == "wild_experience":
        schedule["strategy"] = wild_experience_miniapp.normalize_strategy(strategy)
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
    for kind in TASK_ORDER:
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
            strategy=str(schedule.get("strategy") or "均衡"),
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


def _beast_merge_reward(payload: dict) -> str:
    beast_merge = (
        payload.get("beast_merge")
        if isinstance(payload.get("beast_merge"), dict)
        else {}
    )
    run = beast_merge.get("run") if isinstance(beast_merge.get("run"), dict) else {}
    rounds = run.get("runs") if isinstance(run.get("runs"), list) else []
    trace_reward = sum(
        max(0, int(round_result.get("trace_reward") or 0))
        for round_result in rounds
        if isinstance(round_result, dict)
    )
    best_score = max(
        [
            max(0, int(run.get("best_score") or 0)),
            *[
                max(0, int(round_result.get("score") or 0))
                for round_result in rounds
                if isinstance(round_result, dict)
            ],
        ]
    )
    reward = []
    if trace_reward:
        reward.append(f"残痕 +{trace_reward}")
    if best_score:
        reward.append(f"最佳 {best_score} 分")
    return "、".join(reward) or "—"


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
        item["reward"] = _estate_reward(hunt)
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
        item["reward"] = _tianji_reward(payload)
        return
    if status and status not in {"idle", "queued"}:
        item["status"] = (
            "skipped"
            if any(marker in error for marker in ("上限", "已完成", "次数已满"))
            else "failed"
        )


def _refresh_beast_merge_item(storage: Storage, item: dict) -> None:
    _account, payload = _load_external(storage, item["profile_id"])
    beast_merge = (
        payload.get("beast_merge")
        if isinstance(payload.get("beast_merge"), dict)
        else {}
    )
    request = (
        beast_merge.get("request")
        if isinstance(beast_merge.get("request"), dict)
        else {}
    )
    run = beast_merge.get("run") if isinstance(beast_merge.get("run"), dict) else {}
    request_status = str(request.get("status") or "").strip()
    if request_status in {"queued", "resolving", "running"}:
        item["status"] = request_status
        return

    status = str(run.get("status") or "").strip()
    if request_status in {"failed", "interrupted"} or status in {
        "failed",
        "interrupted",
    }:
        item["status"] = "failed"
        return
    if request_status != "completed" and status != "completed":
        return

    completed = int(run.get("completed_runs") or 0)
    item["status"] = "success" if completed > 0 else "skipped"
    item["reward"] = _beast_merge_reward(payload)


def _refresh_pagoda_item(storage: Storage, item: dict) -> None:
    _account, payload = _load_external(storage, int(item["profile_id"]))
    request = pagoda_state.get_pagoda_request(payload)
    request_status = str(request.get("status") or "")
    if request_status in {"queued", "resolving", "running"}:
        item["status"] = request_status
        item["phase"] = str(request.get("phase") or request_status)
        return
    root = payload.get("pagoda_miniapp") if isinstance(payload.get("pagoda_miniapp"), dict) else {}
    run = root.get("run") if isinstance(root.get("run"), dict) else {}
    status = str(run.get("status") or "")
    item["phase"] = str(run.get("phase") or status)
    if status in {"failed", "interrupted"}:
        item["status"] = "failed"
        return
    if status == "skipped":
        item["status"] = "skipped"
        item["reward"] = _pagoda_reward(payload)
        return
    if status != "settled":
        return
    item["status"] = "success"
    item["reward"] = _pagoda_reward(payload)


def _refresh_wild_experience_item(storage: Storage, item: dict) -> None:
    _account, payload = _load_external(storage, int(item["profile_id"]))
    request = wild_experience_miniapp.get_active_request(payload)
    if request:
        request_status = str(request.get("status") or "queued")
        item["status"] = (
            "queued" if request_status == "retry_wait" else request_status
        )
        item["phase"] = request_status
        return
    state = (
        payload.get(wild_experience_miniapp.STATE_KEY)
        if isinstance(payload.get(wild_experience_miniapp.STATE_KEY), dict)
        else {}
    )
    run = state.get("run") if isinstance(state.get("run"), dict) else {}
    status = str(run.get("status") or "")
    item["phase"] = status
    if status == "completed":
        item["status"] = "success"
        item["reward"] = wild_experience_miniapp.build_reward_summary(payload)
    elif status == "skipped":
        item["status"] = "skipped"
        item["reward"] = wild_experience_miniapp.build_reward_summary(payload)
    elif status == "failed":
        item["status"] = "failed"


def refresh_state(storage: Storage) -> dict:
    state = _load_state(storage)
    active_kind = state.get("active_kind")
    batch = state["batches"].get(active_kind) if active_kind else None
    if not isinstance(batch, dict) or batch.get("status") != "running":
        state["active_kind"] = ""
        return state

    now = time.time()
    timeout_seconds = {
        "beast_merge": BEAST_MERGE_BATCH_TIMEOUT_SECONDS,
        "pagoda": PAGODA_BATCH_TIMEOUT_SECONDS,
        "wild_experience": WILD_EXPERIENCE_BATCH_TIMEOUT_SECONDS,
    }.get(active_kind, BATCH_TIMEOUT_SECONDS)
    timed_out = now - float(batch.get("started_at") or 0) >= timeout_seconds
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
        elif active_kind == "pagoda":
            if not float(item.get("scheduled_at") or 0):
                continue
            _refresh_pagoda_item(storage, item)
        elif active_kind == "wild_experience":
            if not float(item.get("scheduled_at") or 0):
                continue
            _refresh_wild_experience_item(storage, item)
        else:
            _refresh_beast_merge_item(storage, item)

    if active_kind == "pagoda" and not timed_out:
        _dispatch_next_pagoda_item(storage, batch.get("items") or [])
    elif active_kind == "wild_experience" and not timed_out:
        _dispatch_next_wild_experience_item(
            storage,
            batch.get("items") or [],
            strategy=wild_experience_miniapp.normalize_strategy(
                batch.get("strategy")
            ),
        )

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
        "strategy": wild_experience_miniapp.normalize_strategy(
            schedule.get("strategy")
        ),
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
        phase = str(item.get("phase") or "")
        status_label = {
            "queued": (
                "等待入口"
                if kind in {
                    "estate",
                    "tianji",
                    "pagoda",
                    "beast_merge",
                    "wild_experience",
                }
                else "等待发送"
            ),
            "resolving": "获取入口",
            "running": (
                "正在寻宝"
                if kind == "estate"
                else "正在试炼"
                if kind == "tianji"
                else "正在闯塔"
                if kind == "pagoda"
                else "正在进化"
                if kind == "beast_merge"
                else "正在历练"
                if kind == "wild_experience"
                else "执行中"
            ),
            "success": "成功",
            "failed": "失败",
            "skipped": "无需执行",
        }.get(status, "等待执行")
        if kind == "pagoda" and status == "queued" and phase == "waiting_previous":
            status_label = "等待前序元神"
        elif kind == "pagoda" and status == "running" and phase == "start":
            status_label = "读取塔况（start）"
        elif kind == "pagoda" and status == "running" and phase == "challenge":
            status_label = "服务端结算（challenge）"
        elif kind == "wild_experience" and phase == "retry_wait":
            status_label = "等待补跑"
        items.append(
            {
                "profile_name": item.get("profile_name") or f"Profile {item.get('profile_id')}",
                "status": status,
                "status_label": status_label,
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
        "strategy": wild_experience_miniapp.normalize_strategy(
            schedule.get("strategy")
        ),
        "strategy_options": (
            list(wild_experience_miniapp.STRATEGY_OPTIONS)
            if kind == "wild_experience"
            else []
        ),
    }


def _loading_message(card: dict | None) -> str:
    if not card:
        return ""
    return (
        f"正在执行{card['title']}：已完成 {card['done']}/{card['total']}，"
        f"成功 {card['counts']['success']}，失败 {card['counts']['failed']}，"
        f"无需执行 {card['counts']['skipped']}"
    )


def build_status(storage: Storage, *, kind: str = "") -> dict:
    state = refresh_state(storage)
    active_kind = str(state.get("active_kind") or "")
    requested_kind = str(kind or active_kind)
    if requested_kind and requested_kind not in TASKS:
        raise ValueError("Unknown global execution task")

    card = None
    if requested_kind:
        card = _card_view(
            requested_kind,
            state["batches"].get(requested_kind),
            state["schedules"][requested_kind],
        )
    active_card = card if requested_kind == active_kind else None
    if active_kind and active_card is None:
        active_card = _card_view(
            active_kind,
            state["batches"].get(active_kind),
            state["schedules"][active_kind],
        )
    return {
        "active": bool(active_kind),
        "active_kind": active_kind,
        "loading_message": _loading_message(active_card),
        "card": card,
    }


def build_dashboard(storage: Storage) -> dict:
    state = refresh_state(storage)
    cards = [
        _card_view(
            kind,
            state["batches"].get(kind),
            state["schedules"][kind],
        )
        for kind in TASK_ORDER
    ]
    active_kind = state.get("active_kind") or ""
    active_card = next((card for card in cards if card["kind"] == active_kind), None)
    return {
        "active": bool(active_kind),
        "active_kind": active_kind,
        "loading_message": _loading_message(active_card),
        "cards": cards,
    }
