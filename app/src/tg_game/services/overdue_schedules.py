from __future__ import annotations

import json
import time
from collections import Counter
from typing import Optional

import biz_fishing_game
import biz_sect_game

from tg_game.features.pagoda import biz_pagoda_state as pagoda_state
from tg_game.features.tianxing.biz_tianxing_runtime import (
    normalize_config as normalize_tianxing_config,
    normalize_state as normalize_tianxing_state,
    normalize_timeline as normalize_tianxing_timeline,
    tick_craft_loop,
    tick_tianxing_timeline,
)
from tg_game.runtime.executors import (
    DIVINATION_BATCH_COMMAND_INTERVAL_SECONDS,
    DIVINATION_COMMAND,
    get_companion_auto_task_command_prefixes,
    run_queue_backed_schedules_once,
)
from tg_game.storage import OUTGOING_BLOCKING_STATUSES, Storage
from tg_game.telegram.network_guard import is_network_paused


OVERDUE_GRACE_SECONDS = 60
TIANXING_COMMAND_PREFIXES = (
    ".观命",
    ".天机盘",
    ".消劫",
    ".闭关修炼",
    ".定命",
    ".推命",
    ".改命",
    ".炼制",
)
SKIP_REASON_LABELS = {
    "inactive_group": "非当前活动群",
    "pending": "已在队列",
    "sending": "正在发送",
    "awaiting_confirm": "等待 Bot 回包",
    "needs_manual_confirm": "需要人工确认",
    "waiting_workflow": "等待回包状态机",
    "network_paused": "网络熔断",
    "fused": "已停用或熔断",
    "dry_run": "演练模式",
    "direct_executor": "旧直发调度",
    "executor_rechecked_no_queue": "执行器复核后无需入队",
    "duplicate_schedule": "同类调度已处理",
    "executor_error": "执行器异常",
}
COMPANION_TASK_LABELS = {
    "pagoda_tower": "自动闯塔",
    "tianji_trial_daily": "每日天机试炼",
    "estate_miniapp_hunt_daily": "每日洞府寻宝",
    "dream_seek": "自动入梦寻图",
    "divination_chain": "自动天机代卜",
    "wild_experience": "自动野外历练",
    "companion_voyage": "自动侍妾远航",
    "mulan_support_plan": "自动慕兰",
    "artifact_touch": "自动抚摸法宝",
    "artifact_trial": "自动器灵试炼",
    "artifact_nurture": "自动温养器灵",
    "xinggong_starboard": "自动星辰采集",
    "wanling_roam": "自动一键放养",
    "small_world_auto": "自动小世界",
    "small_world_preach_auto": "自动神迹布道",
}


def _table_exists(storage: Storage, table_name: str) -> bool:
    with storage.connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (str(table_name),),
        ).fetchone()
    return bool(row)


def _table_rows(storage: Storage, table_name: str, profile_id: int) -> list[dict]:
    if not _table_exists(storage, table_name):
        return []
    with storage.connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM {table_name} WHERE profile_id=? ORDER BY rowid",
            (int(profile_id),),
        ).fetchall()
    return [dict(row) for row in rows]


def _load_json_object(value: object) -> dict:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _matches_command_prefix(text: object, prefixes: tuple[str, ...]) -> bool:
    command_text = str(text or "").strip()
    for raw_prefix in prefixes:
        prefix = str(raw_prefix or "").strip()
        if not prefix:
            continue
        if command_text == prefix or command_text.startswith(f"{prefix} "):
            return True
    return False


def _find_blocking_outgoing(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    command_prefixes: tuple[str, ...],
) -> Optional[dict]:
    if not command_prefixes or not chat_id:
        return None
    statuses = tuple(OUTGOING_BLOCKING_STATUSES)
    placeholders = ",".join("?" for _ in statuses)
    params: list[object] = [int(profile_id), int(chat_id), *statuses]
    thread_clause = "thread_id IS NULL"
    if thread_id is not None:
        thread_clause = "thread_id=?"
        params.append(int(thread_id))
    with storage.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM outgoing_commands
            WHERE profile_id=? AND chat_id=?
              AND status IN ({placeholders})
              AND {thread_clause}
            ORDER BY updated_at DESC, created_at DESC, id DESC
            """,
            params,
        ).fetchall()
    priority = {
        "needs_manual_confirm": 0,
        "awaiting_confirm": 1,
        "sending": 2,
        "pending": 3,
    }
    matched = [
        dict(row)
        for row in rows
        if _matches_command_prefix(row["text"], command_prefixes)
    ]
    if not matched:
        return None
    matched.sort(key=lambda row: priority.get(str(row.get("status") or ""), 99))
    return matched[0]


def _current_group_matches(
    *,
    chat_id: int,
    active_chat_ids: set[int],
    target_chat_id: Optional[int],
) -> bool:
    if not chat_id:
        return False
    if target_chat_id is not None and int(chat_id) != int(target_chat_id):
        return False
    return int(chat_id) in active_chat_ids


def _item(
    *,
    profile_id: int,
    profile_name: str,
    source: str,
    task_id: object,
    task_key: str,
    task_name: str,
    enabled: bool,
    due_at: object,
    chat_id: object,
    thread_id: object,
    current_group: bool,
    executor: str,
    command_prefixes: tuple[str, ...] = (),
    waiting_workflow: bool = False,
    fused: bool = False,
    dry_run: bool = False,
) -> dict:
    return {
        "profile_id": int(profile_id),
        "profile_name": str(profile_name or f"profile{profile_id}"),
        "source": source,
        "task_id": int(task_id or 0),
        "task_key": str(task_key or source),
        "task_name": str(task_name or task_key or source),
        "enabled": bool(enabled),
        "due_at": float(due_at or 0),
        "chat_id": int(chat_id or 0),
        "thread_id": int(thread_id) if thread_id is not None else None,
        "current_group": bool(current_group),
        "executor": executor,
        "command_prefixes": tuple(command_prefixes),
        "waiting_workflow": bool(waiting_workflow),
        "fused": bool(fused),
        "dry_run": bool(dry_run),
        "status": "pending_audit",
        "reason": "",
        "queued_commands": [],
    }


def collect_schedule_items(
    storage: Storage,
    *,
    target_chat_id: Optional[int],
) -> tuple[list[dict], int]:
    items: list[dict] = []
    profiles = storage.list_profiles()
    for profile in profiles:
        profile_id = int(profile.id)
        active_bindings = [
            binding
            for binding in storage.list_chat_bindings(profile_id)
            if bool(binding.is_active)
        ]
        active_chat_ids = {int(binding.chat_id) for binding in active_bindings}
        primary_binding = next(
            (
                binding
                for binding in active_bindings
                if target_chat_id is None
                or int(binding.chat_id) == int(target_chat_id)
            ),
            None,
        )
        profile_name = str(profile.name or f"profile{profile_id}")

        for task in _table_rows(storage, "companion_auto_tasks", profile_id):
            chat_id = int(task.get("chat_id") or 0)
            feature_key = str(task.get("feature_key") or "").strip()
            items.append(
                _item(
                    profile_id=profile_id,
                    profile_name=profile_name,
                    source="companion_auto",
                    task_id=task.get("id"),
                    task_key=feature_key,
                    task_name=COMPANION_TASK_LABELS.get(feature_key, feature_key),
                    enabled=bool(task.get("enabled")),
                    due_at=task.get("next_run_at"),
                    chat_id=chat_id,
                    thread_id=task.get("thread_id"),
                    current_group=_current_group_matches(
                        chat_id=chat_id,
                        active_chat_ids=active_chat_ids,
                        target_chat_id=target_chat_id,
                    ),
                    executor="companion",
                    command_prefixes=get_companion_auto_task_command_prefixes(task),
                )
            )

        for session in _table_rows(storage, "fishing_sessions", profile_id):
            chat_id = int(session.get("chat_id") or 0)
            command_info = biz_fishing_game.build_next_auto_command(session) or {}
            command_text = str(command_info.get("command") or "").strip()
            items.append(
                _item(
                    profile_id=profile_id,
                    profile_name=profile_name,
                    source="fishing",
                    task_id=session.get("id"),
                    task_key="fishing",
                    task_name="自动钓鱼",
                    enabled=bool(session.get("enabled")),
                    due_at=session.get("next_action_at"),
                    chat_id=chat_id,
                    thread_id=session.get("thread_id"),
                    current_group=_current_group_matches(
                        chat_id=chat_id,
                        active_chat_ids=active_chat_ids,
                        target_chat_id=target_chat_id,
                    ),
                    executor="fishing",
                    command_prefixes=(command_text,) if command_text else (),
                )
            )

        for batch in _table_rows(storage, "divination_batches", profile_id):
            if str(batch.get("status") or "") != "active":
                continue
            chat_id = int(batch.get("chat_id") or 0)
            last_dispatch_at = float(batch.get("last_dispatch_at") or 0)
            items.append(
                _item(
                    profile_id=profile_id,
                    profile_name=profile_name,
                    source="divination_batch",
                    task_id=batch.get("id"),
                    task_key="divination_batch",
                    task_name="批量天机代卜",
                    enabled=True,
                    due_at=(
                        last_dispatch_at + DIVINATION_BATCH_COMMAND_INTERVAL_SECONDS
                        if last_dispatch_at
                        else 0
                    ),
                    chat_id=chat_id,
                    thread_id=batch.get("thread_id"),
                    current_group=_current_group_matches(
                        chat_id=chat_id,
                        active_chat_ids=active_chat_ids,
                        target_chat_id=target_chat_id,
                    ),
                    executor="divination",
                    command_prefixes=(DIVINATION_COMMAND,),
                )
            )

        for task in _table_rows(
            storage, "companion_heart_tribulation_tasks", profile_id
        ):
            chat_id = int(task.get("chat_id") or 0)
            workflow_state = str(task.get("workflow_state") or "").strip()
            items.append(
                _item(
                    profile_id=profile_id,
                    profile_name=profile_name,
                    source="heart_tribulation",
                    task_id=task.get("id"),
                    task_key="heart_tribulation",
                    task_name="自动共历心劫",
                    enabled=bool(task.get("enabled")),
                    due_at=task.get("next_run_at"),
                    chat_id=chat_id,
                    thread_id=task.get("thread_id"),
                    current_group=_current_group_matches(
                        chat_id=chat_id,
                        active_chat_ids=active_chat_ids,
                        target_chat_id=target_chat_id,
                    ),
                    executor="direct",
                    command_prefixes=(".我的侍妾", ".共历心劫"),
                    waiting_workflow=workflow_state not in {"", "idle"},
                )
            )

        for session in _table_rows(storage, "fanren_sessions", profile_id):
            chat_id = int(session.get("chat_id") or 0)
            current_group = _current_group_matches(
                chat_id=chat_id,
                active_chat_ids=active_chat_ids,
                target_chat_id=target_chat_id,
            )
            stopped = bool(str(session.get("stopped_reason") or "").strip())
            fanren_tasks = (
                (
                    "cultivation",
                    "修为闭关检查",
                    bool(session.get("enabled")),
                    session.get("next_check_time"),
                ),
                (
                    "rift",
                    "自动探寻裂缝",
                    bool(session.get("auto_rift_enabled")),
                    session.get("rift_next_check_time"),
                ),
                (
                    "yuanying",
                    "自动元婴出窍",
                    bool(session.get("auto_yuanying_enabled")),
                    session.get("yuanying_next_check_time"),
                ),
            )
            for task_key, task_name, enabled, due_at in fanren_tasks:
                if not enabled and not float(due_at or 0):
                    continue
                items.append(
                    _item(
                        profile_id=profile_id,
                        profile_name=profile_name,
                        source="fanren",
                        task_id=session.get("id"),
                        task_key=task_key,
                        task_name=task_name,
                        enabled=enabled,
                        due_at=due_at,
                        chat_id=chat_id,
                        thread_id=session.get("thread_id"),
                        current_group=current_group,
                        executor="direct",
                        fused=stopped,
                    )
                )

        for session in _table_rows(storage, "sect_sessions", profile_id):
            chat_id = int(session.get("chat_id") or 0)
            current_group = _current_group_matches(
                chat_id=chat_id,
                active_chat_ids=active_chat_ids,
                target_chat_id=target_chat_id,
            )
            for enabled_key, next_key, _source_key, task_name in (
                biz_sect_game.SECT_RESUME_COUNTDOWN_FIELDS
            ):
                enabled = bool(session.get(enabled_key)) and bool(session.get("enabled"))
                due_at = session.get(next_key)
                if not enabled and not float(due_at or 0):
                    continue
                items.append(
                    _item(
                        profile_id=profile_id,
                        profile_name=profile_name,
                        source="sect",
                        task_id=session.get("id"),
                        task_key=enabled_key,
                        task_name=task_name,
                        enabled=enabled,
                        due_at=due_at,
                        chat_id=chat_id,
                        thread_id=session.get("thread_id"),
                        current_group=current_group,
                        executor="direct",
                    )
                )

        if _table_exists(storage, "tianxing_profile_state"):
            with storage.connect() as conn:
                row = conn.execute(
                    "SELECT * FROM tianxing_profile_state WHERE profile_id=?",
                    (profile_id,),
                ).fetchone()
            if row:
                raw = dict(row)
                state = normalize_tianxing_state(
                    _load_json_object(raw.get("state_json"))
                )
                config = normalize_tianxing_config(
                    _load_json_object(raw.get("config_json"))
                )
                timeline = normalize_tianxing_timeline(
                    _load_json_object(raw.get("timeline_json"))
                )
                chat_id = int(
                    state.get("craft_loop_chat_id")
                    or (primary_binding.chat_id if primary_binding else 0)
                    or 0
                )
                thread_id = state.get("craft_loop_thread_id")
                if thread_id is None and primary_binding is not None:
                    thread_id = primary_binding.thread_id
                current_group = _current_group_matches(
                    chat_id=chat_id,
                    active_chat_ids=active_chat_ids,
                    target_chat_id=target_chat_id,
                )
                if bool(config.get("timeline_enabled")):
                    active_step = dict(timeline.get("active_step") or {})
                    phase = str(timeline.get("phase") or "").strip()
                    waiting = phase == "sent_waiting_ack"
                    due_at = float(
                        timeline.get("blocked_until")
                        or active_step.get("ack_due_at")
                        or 0
                    )
                    items.append(
                        _item(
                            profile_id=profile_id,
                            profile_name=profile_name,
                            source="tianxing_timeline",
                            task_id=profile_id,
                            task_key="tianxing_timeline",
                            task_name="天星宗探索时间线",
                            enabled=True,
                            due_at=due_at,
                            chat_id=chat_id,
                            thread_id=thread_id,
                            current_group=current_group,
                            executor="tianxing_timeline",
                            command_prefixes=TIANXING_COMMAND_PREFIXES,
                            waiting_workflow=waiting,
                            dry_run=bool(config.get("timeline_dry_run_enabled")),
                        )
                    )
                if bool(state.get("craft_loop_enabled")):
                    phase = str(state.get("craft_loop_phase") or "idle")
                    last_command = str(
                        state.get("craft_loop_last_command") or ""
                    ).strip()
                    waiting = phase in {"await_predict", "await_predict_panel"} or (
                        phase == "await_craft" and last_command.startswith(".炼制 ")
                    )
                    items.append(
                        _item(
                            profile_id=profile_id,
                            profile_name=profile_name,
                            source="tianxing_craft_loop",
                            task_id=profile_id,
                            task_key="tianxing_craft_loop",
                            task_name="天星宗推命炼制循环",
                            enabled=True,
                            due_at=state.get("craft_loop_ack_due_at") if waiting else 0,
                            chat_id=chat_id,
                            thread_id=thread_id,
                            current_group=current_group,
                            executor="tianxing_craft_loop",
                            command_prefixes=TIANXING_COMMAND_PREFIXES,
                            waiting_workflow=waiting,
                        )
                    )
    return items, len(profiles)


def _latest_outgoing_id(storage: Storage) -> int:
    with storage.connect() as conn:
        row = conn.execute("SELECT COALESCE(MAX(id), 0) FROM outgoing_commands").fetchone()
    return int(row[0] or 0)


def _new_outgoing_commands(
    storage: Storage, *, after_id: int, profile_id: int
) -> list[dict]:
    with storage.connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM outgoing_commands
            WHERE id>? AND profile_id=?
            ORDER BY id
            """,
            (int(after_id), int(profile_id)),
        ).fetchall()
    return [dict(row) for row in rows]


def _pagoda_request_queued(storage: Storage, profile_id: int) -> bool:
    account = storage.get_external_account(int(profile_id), "asc_aiopenai") or {}
    payload = _load_json_object(account.get("me_json"))
    return pagoda_state.has_active_pagoda_request(payload)


async def _apply_item(storage: Storage, item: dict, *, now: float) -> list[dict]:
    before_id = _latest_outgoing_id(storage)
    executor = str(item.get("executor") or "")
    profile_id = int(item["profile_id"])
    task_id = int(item.get("task_id") or 0)
    if executor == "companion":
        await run_queue_backed_schedules_once(
            storage,
            profile_id,
            companion_task_ids=(task_id,),
        )
    elif executor == "fishing":
        await run_queue_backed_schedules_once(
            storage,
            profile_id,
            fishing_session_ids=(task_id,),
        )
    elif executor == "divination":
        await run_queue_backed_schedules_once(
            storage,
            profile_id,
            include_divination_batch=True,
        )
    elif executor == "tianxing_timeline":
        tick_tianxing_timeline(storage, profile_id, now=now)
    elif executor == "tianxing_craft_loop":
        tick_craft_loop(storage, profile_id, now=now)
    return _new_outgoing_commands(
        storage,
        after_id=before_id,
        profile_id=profile_id,
    )


async def reconcile_overdue_schedules(
    storage: Storage,
    *,
    target_chat_id: Optional[int],
    apply: bool,
    now: Optional[float] = None,
    overdue_grace_seconds: int = OVERDUE_GRACE_SECONDS,
) -> dict:
    started = time.monotonic()
    current_time = float(time.time() if now is None else now)
    cutoff = current_time - max(int(overdue_grace_seconds or 0), 0)
    items, profile_count = collect_schedule_items(
        storage,
        target_chat_id=target_chat_id,
    )
    skip_reasons: Counter[str] = Counter()
    overdue_count = 0
    eligible_count = 0
    requeued_count = 0
    queued_command_count = 0
    failed_count = 0
    seen_overdue_tasks: set[tuple[int, str, str]] = set()

    for item in items:
        if not bool(item.get("enabled")):
            item["status"] = "disabled"
            item["reason"] = "disabled"
            continue
        if float(item.get("due_at") or 0) > cutoff:
            item["status"] = "future"
            item["reason"] = "future"
            continue

        overdue_count += 1
        if not bool(item.get("current_group")):
            item["status"] = "skipped"
            item["reason"] = "inactive_group"
        elif (
            int(item["profile_id"]),
            str(item.get("source") or ""),
            str(item.get("task_key") or ""),
        ) in seen_overdue_tasks:
            item["status"] = "skipped"
            item["reason"] = "duplicate_schedule"
        elif bool(item.get("fused")):
            item["status"] = "skipped"
            item["reason"] = "fused"
        elif bool(item.get("dry_run")):
            item["status"] = "skipped"
            item["reason"] = "dry_run"
        elif bool(item.get("waiting_workflow")):
            item["status"] = "skipped"
            item["reason"] = "waiting_workflow"
        elif is_network_paused(storage, int(item["profile_id"]), now=current_time):
            item["status"] = "skipped"
            item["reason"] = "network_paused"
        else:
            blocker = _find_blocking_outgoing(
                storage,
                profile_id=int(item["profile_id"]),
                chat_id=int(item.get("chat_id") or 0),
                thread_id=item.get("thread_id"),
                command_prefixes=tuple(item.get("command_prefixes") or ()),
            )
            if blocker:
                item["status"] = "skipped"
                item["reason"] = str(blocker.get("status") or "pending")
                item["blocking_command_id"] = int(blocker.get("id") or 0)
            elif str(item.get("executor") or "") == "direct":
                item["status"] = "skipped"
                item["reason"] = "direct_executor"
            else:
                item["status"] = "eligible"
                item["reason"] = ""
                eligible_count += 1

        if item["status"] != "skipped" or item["reason"] != "inactive_group":
            seen_overdue_tasks.add(
                (
                    int(item["profile_id"]),
                    str(item.get("source") or ""),
                    str(item.get("task_key") or ""),
                )
            )

        if item["status"] == "skipped":
            skip_reasons[str(item.get("reason") or "unknown")] += 1
            continue
        if item["status"] != "eligible" or not apply:
            continue

        try:
            commands = await _apply_item(storage, item, now=current_time)
        except Exception as exc:
            item["status"] = "failed"
            item["reason"] = "executor_error"
            item["error"] = str(exc)
            failed_count += 1
            skip_reasons["executor_error"] += 1
            continue
        local_pagoda_request = (
            str(item.get("task_key") or "") == "pagoda_tower"
            and _pagoda_request_queued(storage, int(item["profile_id"]))
        )
        if commands or local_pagoda_request:
            item["status"] = "requeued"
            item["queued_commands"] = [
                {
                    "id": int(command.get("id") or 0),
                    "text": str(command.get("text") or ""),
                }
                for command in commands
            ]
            requeued_count += 1
            queued_command_count += len(commands)
            if local_pagoda_request:
                item["queued_locally"] = "MiniApp 闯塔"
        else:
            item["status"] = "skipped"
            item["reason"] = "executor_rechecked_no_queue"
            skip_reasons["executor_rechecked_no_queue"] += 1

    result_items = [
        item
        for item in items
        if item.get("status")
        in {"eligible", "requeued", "skipped", "failed"}
    ]
    skipped_count = sum(skip_reasons.values())
    return {
        "mode": "apply" if apply else "check",
        "profiles_checked": profile_count,
        "tasks_checked": len(items),
        "overdue_count": overdue_count,
        "eligible_count": eligible_count,
        "requeued_count": requeued_count,
        "queued_command_count": queued_command_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
        "skip_reasons": dict(sorted(skip_reasons.items())),
        "items": result_items,
        "elapsed_seconds": time.monotonic() - started,
    }


def format_reconcile_result(result: dict) -> str:
    lines = [
        f"调度补偿模式: {result.get('mode') or 'check'}",
        (
            "调度补偿统计: "
            f"profiles={int(result.get('profiles_checked') or 0)} "
            f"checked={int(result.get('tasks_checked') or 0)} "
            f"overdue={int(result.get('overdue_count') or 0)} "
            f"eligible={int(result.get('eligible_count') or 0)} "
            f"requeued={int(result.get('requeued_count') or 0)} "
            f"commands={int(result.get('queued_command_count') or 0)} "
            f"skipped={int(result.get('skipped_count') or 0)} "
            f"failed={int(result.get('failed_count') or 0)}"
        ),
    ]
    skip_reasons = dict(result.get("skip_reasons") or {})
    if skip_reasons:
        reason_text = ", ".join(
            f"{SKIP_REASON_LABELS.get(reason, reason)}={count}"
            for reason, count in skip_reasons.items()
        )
        lines.append(f"调度补偿跳过: {reason_text}")
    for item in result.get("items") or []:
        status = str(item.get("status") or "")
        if status == "eligible":
            status_text = "待补偿"
        elif status == "requeued":
            status_text = "已重新入队"
        elif status == "failed":
            status_text = "执行失败"
        else:
            reason = str(item.get("reason") or "")
            status_text = f"跳过:{SKIP_REASON_LABELS.get(reason, reason)}"
        commands = ", ".join(
            str(command.get("text") or "")
            for command in item.get("queued_commands") or []
        )
        suffix = f" commands={commands}" if commands else ""
        if item.get("queued_locally"):
            suffix += f" local={item['queued_locally']}"
        lines.append(
            "调度补偿明细: "
            f"profile={int(item.get('profile_id') or 0)} "
            f"task={item.get('task_name') or item.get('task_key')} "
            f"result={status_text}{suffix}"
        )
    lines.append(f"调度补偿耗时: {float(result.get('elapsed_seconds') or 0):.2f}s")
    return "\n".join(lines)
