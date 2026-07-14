import json
import time
from typing import Any, Optional
from tg_game.storage import (
    OUTGOING_AWAITING_CONFIRM_STATUS,
    OUTGOING_BLOCKING_STATUSES,
    OUTGOING_CONFIRM_TIMEOUT_SECONDS,
    OUTGOING_NEEDS_MANUAL_CONFIRM_STATUS,
    Storage,
)

from .biz_tianxing_parser import (
    TIANXING_CHANGE_FATE_SECONDS,
    TIANXING_PREDICTION_SECONDS,
    TIANXING_ROUTES,
    TIANXING_STARS,
    command_for_action,
    family_for_command,
    get_day_key,
    looks_like_tianxing_text,
    parse_tianxing_text,
)


FEATURE_KEY = "tianxing"
TIANXING_SECT_NAME = "天星宗"
TIANXING_BOT_USERNAME = "fanrenxiuxian_bot"
DAILY_SET_STAR_PRIORITY = ("贪狼", "太阴")
TIMELINE_PHASES = {
    "planning",
    "waiting_send",
    "sent_waiting_ack",
    "state_confirmed",
    "downstream_released",
    "ack_timeout",
    "calibrating",
    "blocked_replan",
}
STRATEGIC_ACTIONS = {"set_star", "predict", "change_fate", "craft", "retreat"}
CRAFT_LOOP_PHASES = {
    "idle",
    "await_predict",
    "await_predict_panel",
    "await_craft",
    "done",
    "stopped",
    "error",
}
ACK_TIMEOUT_SECONDS = 90
CALIBRATION_BACKOFF_SECONDS = 5 * 60
EXPLORATION_PANEL_FRESH_SECONDS = CALIBRATION_BACKOFF_SECONDS


def is_tianxing_profile(storage: Optional[Storage], profile_id: Optional[int]) -> bool:
    if not storage or not profile_id:
        return False
    profile = storage.get_profile(int(profile_id))
    sect_name = str(getattr(profile, "sect_name", "") or "").strip()
    return sect_name.strip("【】[] ") == TIANXING_SECT_NAME


def default_state() -> dict[str, Any]:
    return {
        "last_observed_at": 0,
        "last_action": "",
        "last_result": "",
        "last_error": "",
        "available_stars": [],
        "available_stars_source": "",
        "available_stars_day": "",
        "observed_stars": [],
        "observed_stars_day": "",
        "observed_stars_at": 0,
        "daily_observe_queued_day": "",
        "daily_observe_queued_at": 0,
        "daily_set_star_queued_day": "",
        "daily_set_star_queued_at": 0,
        "fixed_star": "",
        "fixed_star_day": "",
        "current_prediction": "",
        "current_prediction_until": 0,
        "current_prediction_until_source": "",
        "current_prediction_set_at": 0,
        "last_panel_checked_at": 0,
        "prediction_consumed_route": "",
        "prediction_consumed_at": 0,
        "current_change": "",
        "current_change_until": 0,
        "current_change_until_source": "",
        "tianji_value": 0,
        "calamity_count": 0,
        "hit_count": 0,
        "miss_count": 0,
        "change_count": 0,
        "last_route": "",
        "last_star_effect": "",
        "last_tianji_gain": 0,
        "last_contrib_gain": 0,
        "last_bonus_gain": 0,
        "auto_pending_action": "",
        "auto_pending_command": "",
        "auto_pending_msg_id": 0,
        "auto_pending_sent_at": 0,
        "auto_pending_due_at": 0,
        "released_routes": {},
        "craft_loop_enabled": False,
        "craft_loop_item": "玄铁剑",
        "craft_loop_target_count": 30,
        "craft_loop_remaining": 0,
        "craft_loop_completed": 0,
        "craft_loop_phase": "idle",
        "craft_loop_last_error": "",
        "craft_loop_chat_id": 0,
        "craft_loop_thread_id": None,
        "craft_loop_chat_type": "group",
        "craft_loop_bot_username": TIANXING_BOT_USERNAME,
        "craft_loop_last_command": "",
        "craft_loop_last_command_sent_at": 0,
        "craft_loop_ack_due_at": 0,
        "craft_loop_started_at": 0,
        "craft_loop_finished_at": 0,
        "recent": [],
    }


def default_config() -> dict[str, Any]:
    return {
        "auto_panel_enabled": True,
        "auto_observe_enabled": True,
        "auto_clear_calamity_enabled": True,
        "auto_set_star_enabled": False,
        "set_star_name": "",
        "auto_predict_enabled": False,
        "auto_change_fate_enabled": False,
        "timeline_enabled": False,
        "timeline_dry_run_enabled": True,
        "strategy_dry_run_enabled": True,
        "craft_farm_enabled": False,
        "craft_farm_dry_run_enabled": True,
        "craft_farm_item": "玄铁剑",
        "craft_farm_quantity": 1,
        "retreat_farm_enabled": False,
        "retreat_farm_dry_run_enabled": True,
        "deep_retreat_consume_enabled": False,
        "duel_route_enabled": False,
        "route_priority": ["探索", "闭关", "炼制", "斗法"],
        "change_route_priority": ["探索"],
        "min_tianji_for_change": 6,
        "ack_timeout_sec": ACK_TIMEOUT_SECONDS,
        "calibration_backoff_sec": CALIBRATION_BACKOFF_SECONDS,
    }


def default_timeline() -> dict[str, Any]:
    return {
        "phase": "planning",
        "route": "",
        "steps": [],
        "active_step_index": -1,
        "active_step": {},
        "released_routes": {},
        "blocked_until": 0,
        "last_error": "",
        "updated_at": 0,
    }


def normalize_config(value: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    config = default_config()
    if isinstance(value, dict):
        config.update(value)
    for key in (
        "auto_panel_enabled",
        "auto_observe_enabled",
        "auto_clear_calamity_enabled",
        "auto_set_star_enabled",
        "auto_predict_enabled",
        "auto_change_fate_enabled",
        "timeline_enabled",
        "timeline_dry_run_enabled",
        "strategy_dry_run_enabled",
        "craft_farm_enabled",
        "craft_farm_dry_run_enabled",
        "retreat_farm_enabled",
        "retreat_farm_dry_run_enabled",
        "deep_retreat_consume_enabled",
        "duel_route_enabled",
    ):
        config[key] = _coerce_bool(config.get(key), default_config()[key])
    config["route_priority"] = _normalize_route_list(
        config.get("route_priority"), default_config()["route_priority"]
    )
    config["change_route_priority"] = _normalize_route_list(
        config.get("change_route_priority"), default_config()["change_route_priority"]
    )
    config["set_star_name"] = str(config.get("set_star_name") or "").strip()
    config["min_tianji_for_change"] = max(0, int(config.get("min_tianji_for_change") or 0))
    config["craft_farm_item"] = str(config.get("craft_farm_item") or "玄铁剑").strip() or "玄铁剑"
    config["craft_farm_quantity"] = max(1, int(config.get("craft_farm_quantity") or 1))
    config["ack_timeout_sec"] = max(1, int(config.get("ack_timeout_sec") or ACK_TIMEOUT_SECONDS))
    config["calibration_backoff_sec"] = max(
        1, int(config.get("calibration_backoff_sec") or CALIBRATION_BACKOFF_SECONDS)
    )
    return config


def normalize_state(value: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    state = default_state()
    if isinstance(value, dict):
        state.update(value)
    if not isinstance(state.get("available_stars"), list):
        state["available_stars"] = []
    if not isinstance(state.get("observed_stars"), list):
        state["observed_stars"] = []
    if (
        not state.get("observed_stars")
        and str(state.get("available_stars_source") or "") == "observe"
        and str(state.get("available_stars_day") or "")
    ):
        state["observed_stars"] = list(state.get("available_stars") or [])
        state["observed_stars_day"] = str(state.get("available_stars_day") or "")
        state["observed_stars_at"] = float(state.get("last_observed_at") or 0)
    if not isinstance(state.get("released_routes"), dict):
        state["released_routes"] = {}
    if not isinstance(state.get("recent"), list):
        state["recent"] = []
    state["craft_loop_enabled"] = _coerce_bool(state.get("craft_loop_enabled"), False)
    state["craft_loop_item"] = str(state.get("craft_loop_item") or "玄铁剑").strip() or "玄铁剑"
    state["craft_loop_target_count"] = max(1, int(state.get("craft_loop_target_count") or 30))
    state["craft_loop_remaining"] = max(0, int(state.get("craft_loop_remaining") or 0))
    state["craft_loop_completed"] = max(0, int(state.get("craft_loop_completed") or 0))
    if state.get("craft_loop_phase") not in CRAFT_LOOP_PHASES:
        state["craft_loop_phase"] = "idle"
    state["craft_loop_last_error"] = str(state.get("craft_loop_last_error") or "")
    state["craft_loop_chat_id"] = int(state.get("craft_loop_chat_id") or 0)
    raw_thread_id = state.get("craft_loop_thread_id")
    state["craft_loop_thread_id"] = int(raw_thread_id) if raw_thread_id not in (None, "") else None
    state["craft_loop_chat_type"] = str(state.get("craft_loop_chat_type") or "group").strip() or "group"
    state["craft_loop_bot_username"] = (
        str(state.get("craft_loop_bot_username") or TIANXING_BOT_USERNAME).strip()
        or TIANXING_BOT_USERNAME
    )
    state["craft_loop_last_command"] = str(state.get("craft_loop_last_command") or "").strip()
    state["craft_loop_last_command_sent_at"] = float(state.get("craft_loop_last_command_sent_at") or 0)
    state["craft_loop_ack_due_at"] = float(state.get("craft_loop_ack_due_at") or 0)
    state["craft_loop_started_at"] = float(state.get("craft_loop_started_at") or 0)
    state["craft_loop_finished_at"] = float(state.get("craft_loop_finished_at") or 0)
    return state


def normalize_timeline(value: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    timeline = default_timeline()
    if isinstance(value, dict):
        timeline.update(value)
    if timeline.get("phase") not in TIMELINE_PHASES:
        timeline["phase"] = "planning"
    if not isinstance(timeline.get("steps"), list):
        timeline["steps"] = []
    if not isinstance(timeline.get("active_step"), dict):
        timeline["active_step"] = {}
    if not isinstance(timeline.get("released_routes"), dict):
        timeline["released_routes"] = {}
    return timeline


def ensure_schema(storage: Storage) -> None:
    with storage.connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tianxing_profile_state (
                profile_id INTEGER PRIMARY KEY,
                state_json TEXT NOT NULL DEFAULT '{}',
                config_json TEXT NOT NULL DEFAULT '{}',
                timeline_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tianxing_audit_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                profile_id INTEGER,
                chat_id INTEGER NOT NULL DEFAULT 0,
                thread_id INTEGER,
                message_id INTEGER NOT NULL DEFAULT 0,
                reply_to_msg_id INTEGER NOT NULL DEFAULT 0,
                family TEXT NOT NULL DEFAULT '',
                event_type TEXT NOT NULL DEFAULT '',
                action TEXT NOT NULL DEFAULT '',
                result TEXT NOT NULL DEFAULT '',
                route TEXT NOT NULL DEFAULT '',
                phase TEXT NOT NULL DEFAULT '',
                command_text TEXT NOT NULL DEFAULT '',
                detail_json TEXT NOT NULL DEFAULT '{}',
                raw_text TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tianxing_audit_profile_created
            ON tianxing_audit_events(profile_id, created_at DESC, id DESC);
            """
        )


def get_profile_record(storage: Storage, profile_id: int) -> dict[str, Any]:
    ensure_schema(storage)
    now = time.time()
    with storage.connect() as conn:
        row = conn.execute(
            "SELECT * FROM tianxing_profile_state WHERE profile_id=?",
            (int(profile_id),),
        ).fetchone()
        if not row:
            conn.execute(
                """
                INSERT INTO tianxing_profile_state
                (profile_id, state_json, config_json, timeline_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    int(profile_id),
                    json.dumps(default_state(), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(default_config(), ensure_ascii=False, separators=(",", ":")),
                    json.dumps(default_timeline(), ensure_ascii=False, separators=(",", ":")),
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM tianxing_profile_state WHERE profile_id=?",
                (int(profile_id),),
            ).fetchone()
    return _decode_record(dict(row)) if row else {}


def save_profile_record(
    storage: Storage,
    profile_id: int,
    *,
    state: Optional[dict[str, Any]] = None,
    config: Optional[dict[str, Any]] = None,
    timeline: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    current = get_profile_record(storage, profile_id)
    next_state = normalize_state(state if state is not None else current.get("state"))
    next_config = normalize_config(config if config is not None else current.get("config"))
    next_timeline = normalize_timeline(timeline if timeline is not None else current.get("timeline"))
    now = time.time()
    with storage.connect() as conn:
        conn.execute(
            """
            INSERT INTO tianxing_profile_state
            (profile_id, state_json, config_json, timeline_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET
                state_json=excluded.state_json,
                config_json=excluded.config_json,
                timeline_json=excluded.timeline_json,
                updated_at=excluded.updated_at
            """,
            (
                int(profile_id),
                json.dumps(next_state, ensure_ascii=False, separators=(",", ":")),
                json.dumps(next_config, ensure_ascii=False, separators=(",", ":")),
                json.dumps(next_timeline, ensure_ascii=False, separators=(",", ":")),
                now,
                now,
            ),
        )
    return {"state": next_state, "config": next_config, "timeline": next_timeline}


def set_profile_config(storage: Storage, profile_id: int, updates: dict[str, Any]) -> dict[str, Any]:
    record = get_profile_record(storage, profile_id)
    config = normalize_config({**record.get("config", {}), **(updates or {})})
    return save_profile_record(storage, profile_id, config=config)["config"]


def append_audit_event(
    storage: Storage,
    *,
    profile_id: Optional[int],
    chat_id: int = 0,
    thread_id: Optional[int] = None,
    message_id: int = 0,
    reply_to_msg_id: int = 0,
    family: str = "",
    event_type: str,
    action: str = "",
    result: str = "",
    route: str = "",
    phase: str = "",
    command_text: str = "",
    detail: Optional[dict[str, Any]] = None,
    raw_text: str = "",
) -> int:
    ensure_schema(storage)
    with storage.connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO tianxing_audit_events (
                profile_id, chat_id, thread_id, message_id, reply_to_msg_id,
                family, event_type, action, result, route, phase, command_text,
                detail_json, raw_text, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(profile_id) if profile_id is not None else None,
                int(chat_id or 0),
                int(thread_id) if thread_id is not None else None,
                int(message_id or 0),
                int(reply_to_msg_id or 0),
                str(family or "")[:80],
                str(event_type or "")[:80],
                str(action or "")[:80],
                str(result or "")[:80],
                str(route or "")[:40],
                str(phase or "")[:80],
                str(command_text or "")[:200],
                json.dumps(detail or {}, ensure_ascii=False, separators=(",", ":"))[:4000],
                str(raw_text or "")[:4000],
                time.time(),
            ),
        )
        return int(cursor.lastrowid)


def list_audit_events(storage: Storage, profile_id: int, limit: int = 20) -> list[dict[str, Any]]:
    ensure_schema(storage)
    safe_limit = max(1, min(int(limit or 20), 100))
    with storage.connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM tianxing_audit_events
            WHERE profile_id=?
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (int(profile_id), safe_limit),
        ).fetchall()
    return [dict(row) for row in rows]


def send_command(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    command: str,
    family: str,
    thread_id: Optional[int] = None,
    chat_type: str = "group",
    bot_username: str = "",
    dry_run: bool = True,
    delay_seconds: int = 0,
) -> dict[str, Any]:
    normalized_command = str(command or "").strip()
    normalized_family = str(family or family_for_command(normalized_command)).strip()
    if not profile_id or not chat_id or not normalized_command:
        return {"queued": False, "dry_run": bool(dry_run), "reason": "missing command context"}
    if not is_tianxing_profile(storage, profile_id):
        return {"queued": False, "dry_run": bool(dry_run), "reason": "not_tianxing_profile"}
    if not dry_run:
        command_id = _enqueue_if_not_blocking(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            command=normalized_command,
            thread_id=thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            delay_seconds=delay_seconds,
        )
        if not command_id:
            append_audit_event(
                storage,
                profile_id=profile_id,
                chat_id=chat_id,
                thread_id=thread_id,
                family=normalized_family,
                event_type="command_blocked",
                command_text=normalized_command,
                detail={"reason": "active_tianxing_outgoing"},
            )
            return {
                "queued": False,
                "dry_run": False,
                "command": normalized_command,
                "reason": "active_tianxing_outgoing",
            }
        append_audit_event(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            family=normalized_family,
            event_type="command_queued",
            command_text=normalized_command,
            detail={"dry_run": False},
        )
        return {"queued": True, "dry_run": False, "command_id": command_id, "command": normalized_command}
    append_audit_event(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        family=normalized_family,
        event_type="command_planned" if dry_run else "command_queued",
        command_text=normalized_command,
        detail={"dry_run": bool(dry_run)},
    )
    return {"queued": False, "dry_run": True, "command": normalized_command}


def handle_bot_reply(
    storage: Storage,
    *,
    profile_id: Optional[int],
    chat_id: int,
    text: str,
    reply_to_msg_id: Optional[int],
    message_id: int = 0,
    thread_id: Optional[int] = None,
    family: str = "",
    now: Optional[float] = None,
) -> dict[str, Any]:
    current_time = float(time.time() if now is None else now)
    if profile_id is None or not reply_to_msg_id:
        append_audit_event(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            message_id=message_id,
            reply_to_msg_id=reply_to_msg_id or 0,
            family=family,
            event_type="reply_unattributed",
            raw_text=text,
            detail={"reason": "missing profile_id or reply_to_msg_id"},
        )
        return {"handled": False, "reason": "unattributed"}
    if not is_tianxing_profile(storage, profile_id):
        return {"handled": False, "reason": "not_tianxing_profile"}

    parent = storage.get_bound_message(chat_id, int(reply_to_msg_id), int(profile_id))
    if not parent or int(parent.get("is_bot") or 0) or str(parent.get("direction") or "") != "outgoing":
        append_audit_event(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            message_id=message_id,
            reply_to_msg_id=int(reply_to_msg_id),
            family=family,
            event_type="reply_unattributed",
            raw_text=text,
            detail={"reason": "reply parent is not this profile outgoing command"},
        )
        return {"handled": False, "reason": "parent_not_profile_outgoing"}

    command_text = str(parent.get("text") or "").strip()
    resolved_family = family or family_for_command(command_text)
    if not resolved_family and not looks_like_tianxing_text(text):
        return {"handled": False, "reason": "not_tianxing"}
    if not resolved_family:
        resolved_family = "tianxing_modifier"
    parsed = parse_tianxing_text(text, now=current_time, family=resolved_family)
    if not parsed.get("is_tianxing"):
        return {"handled": False, "reason": "not_tianxing"}

    route = _route_from_parsed(parsed)
    append_audit_event(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id if thread_id is not None else parent.get("thread_id"),
        message_id=message_id,
        reply_to_msg_id=int(reply_to_msg_id),
        family=resolved_family,
        event_type="reply_parsed",
        action=str(parsed.get("action") or ""),
        result=str(parsed.get("result") or ""),
        route=route,
        command_text=command_text,
        detail={"parsed": {k: v for k, v in parsed.items() if k != "raw_text"}},
        raw_text=text,
    )
    if parsed.get("unknown"):
        return {"handled": True, "changed": False, "parsed": parsed, "reason": "unknown_text"}

    record = get_profile_record(storage, int(profile_id))
    timeline_before = normalize_timeline(record.get("timeline"))
    active_step = dict(timeline_before.get("active_step") or {})
    if (
        timeline_before.get("phase") == "ack_timeout"
        and str(active_step.get("command") or "").strip() == command_text
    ):
        append_audit_event(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id if thread_id is not None else parent.get("thread_id"),
            message_id=message_id,
            reply_to_msg_id=int(reply_to_msg_id),
            family=resolved_family,
            event_type="reply_late_after_timeout",
            action=str(parsed.get("action") or ""),
            result=str(parsed.get("result") or ""),
            route=route,
            command_text=command_text,
            detail={"timeline_phase": "ack_timeout", "active_step": active_step},
            raw_text=text,
        )
        return {
            "handled": True,
            "changed": False,
            "parsed": parsed,
            "reason": "late_after_timeout",
        }

    state = apply_parsed_to_state(record.get("state"), parsed, now=current_time)
    timeline = update_timeline_on_confirmation(timeline_before, parsed, command_text, now=current_time)
    save_profile_record(storage, int(profile_id), state=state, timeline=timeline)
    parent_thread_id = thread_id if thread_id is not None else parent.get("thread_id")
    _confirm_craft_prediction_from_panel_evidence(
        storage,
        profile_id=int(profile_id),
        chat_id=chat_id,
        thread_id=parent_thread_id,
        parsed=parsed,
        now=current_time,
    )
    craft_loop = _advance_craft_loop_on_reply(
        storage,
        profile_id=int(profile_id),
        chat_id=chat_id,
        thread_id=parent_thread_id,
        command_text=command_text,
        parsed=parsed,
        now=current_time,
    )
    _schedule_craft_calibration_if_needed(
        storage,
        profile_id=int(profile_id),
        chat_id=chat_id,
        thread_id=parent_thread_id,
        command_text=command_text,
        parsed=parsed,
        now=current_time,
    )
    _schedule_retreat_calibration_if_needed(
        storage,
        profile_id=int(profile_id),
        chat_id=chat_id,
        thread_id=parent_thread_id,
        command_text=command_text,
        parsed=parsed,
        now=current_time,
    )
    _schedule_exploration_panel_calibration_if_needed(
        storage,
        profile_id=int(profile_id),
        chat_id=chat_id,
        thread_id=parent_thread_id,
        command_text=command_text,
        parsed=parsed,
        now=current_time,
    )
    auto_advance = _maybe_auto_advance_exploration_timeline(
        storage,
        profile_id=int(profile_id),
        chat_id=chat_id,
        thread_id=parent_thread_id,
        timeline_before=timeline_before,
        timeline_after=timeline,
        command_text=command_text,
        now=current_time,
    )
    if not auto_advance:
        auto_advance = _maybe_advance_exploration_after_panel_calibration(
            storage,
            profile_id=int(profile_id),
            chat_id=chat_id,
            thread_id=parent_thread_id,
            timeline_before=timeline_before,
            command_text=command_text,
            parsed=parsed,
            now=current_time,
        )
    if auto_advance:
        timeline = get_profile_record(storage, int(profile_id))["timeline"]
    return {
        "handled": True,
        "changed": True,
        "parsed": parsed,
        "state": state,
        "timeline": timeline,
        "auto_advance": auto_advance,
        "craft_loop": craft_loop,
    }


def _maybe_auto_advance_exploration_timeline(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    timeline_before: dict[str, Any],
    timeline_after: dict[str, Any],
    command_text: str,
    now: float,
) -> Optional[dict[str, Any]]:
    if timeline_before.get("phase") != "sent_waiting_ack":
        return None
    if timeline_after.get("phase") != "state_confirmed":
        return None
    active_before = dict(timeline_before.get("active_step") or {})
    if str(active_before.get("command") or "").strip() != str(command_text or "").strip():
        return None
    route = str(timeline_after.get("route") or active_before.get("route") or "").strip()
    if route != "探索":
        return None
    record = get_profile_record(storage, int(profile_id))
    config = normalize_config(record.get("config"))
    if not config.get("timeline_enabled") or config.get("timeline_dry_run_enabled"):
        return None
    binding = storage.resolve_chat_binding_for_event(
        int(profile_id),
        int(chat_id),
        thread_id,
        None,
    )
    return start_or_advance_timeline(
        storage,
        profile_id=int(profile_id),
        chat_id=int(chat_id),
        route=route,
        thread_id=thread_id,
        chat_type=getattr(binding, "chat_type", "group") if binding else "group",
        bot_username=(
            getattr(binding, "bot_username", "") if binding else ""
        )
        or TIANXING_BOT_USERNAME,
        now=now,
    )


def apply_parsed_to_state(
    current: Optional[dict[str, Any]], parsed: dict[str, Any], *, now: Optional[float] = None
) -> dict[str, Any]:
    current_time = float(time.time() if now is None else now)
    state = normalize_state(current)
    state["last_observed_at"] = current_time
    state["last_action"] = str(parsed.get("action") or "")
    state["last_result"] = str(parsed.get("result") or "")
    route = _route_from_parsed(parsed)
    if route:
        state["last_route"] = route
    if parsed.get("action") == "天机盘" and parsed.get("result") == "panel":
        state["last_panel_checked_at"] = current_time
    for key in (
        "available_stars",
        "available_stars_source",
        "available_stars_day",
        "fixed_star",
        "fixed_star_day",
        "current_prediction",
        "current_prediction_until",
        "current_prediction_until_source",
        "current_prediction_set_at",
        "current_change",
        "current_change_until",
        "current_change_until_source",
        "tianji_value",
        "calamity_count",
        "hit_count",
        "miss_count",
        "change_count",
        "last_star_effect",
        "last_tianji_gain",
        "last_contrib_gain",
        "last_bonus_gain",
    ):
        if key in parsed:
            state[key] = parsed[key]
    if parsed.get("action") == "观命" and parsed.get("result") == "observe":
        observed_stars = [
            star
            for star in (parsed.get("available_stars") if isinstance(parsed.get("available_stars"), list) else [])
            if star in TIANXING_STARS
        ]
        state["observed_stars"] = observed_stars
        state["observed_stars_day"] = str(parsed.get("available_stars_day") or get_day_key(current_time))
        state["observed_stars_at"] = current_time
    if parsed.get("result") in {"prediction_hit", "prediction_miss", "change_triggered"}:
        previous_route = str(state.get("current_prediction") or parsed.get("prediction_consumed_route") or route)
        state["prediction_consumed_route"] = previous_route
        state["prediction_consumed_at"] = current_time
        if parsed.get("result") in {"prediction_hit", "prediction_miss"} and route == "炼制" and previous_route == "炼制":
            state["current_prediction"] = ""
            state["current_prediction_until"] = 0
            state["current_prediction_until_source"] = ""
            state["current_prediction_set_at"] = 0
    if parsed.get("result") == "prediction_miss":
        state["calamity_count"] = int(state.get("calamity_count") or 0) + int(parsed.get("calamity_delta") or 1)
    if parsed.get("result") == "change_triggered":
        state["current_change"] = ""
        state["current_change_until"] = 0
        state["current_change_until_source"] = ""
    if parsed.get("change_pending_until") and state.get("current_change"):
        state["current_change_until"] = parsed["change_pending_until"]
    if parsed.get("action") == "消劫" and parsed.get("result") == "success":
        state["calamity_count"] = max(0, int(state.get("calamity_count") or 0) - 1)
    recent = list(state.get("recent") or [])
    recent.append({
        "ts": current_time,
        "action": state["last_action"],
        "result": state["last_result"],
        "route": route,
    })
    state["recent"] = recent[-20:]
    return state


def build_manual_plan(action: str = "panel", arg: str = "", *, config: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    normalized_action = str(action or "").strip()
    normalized_arg = str(arg or "").strip()
    normalized_config = normalize_config(config)
    command = command_for_action(normalized_action, normalized_arg)
    if not command:
        return {"allowed": False, "action": normalized_action, "reason": "unknown action"}
    if normalized_action == "set_star" and not normalized_config.get("auto_set_star_enabled"):
        return _dry_or_block_plan(normalized_action, command, normalized_config)
    if normalized_action == "predict" and not normalized_config.get("auto_predict_enabled"):
        return _dry_or_block_plan(normalized_action, command, normalized_config)
    if normalized_action == "change_fate" and not normalized_config.get("auto_change_fate_enabled"):
        return _dry_or_block_plan(normalized_action, command, normalized_config)
    dry_run = normalized_action in STRATEGIC_ACTIONS and normalized_config.get("strategy_dry_run_enabled")
    return {
        "allowed": True,
        "dry_run": bool(dry_run),
        "action": normalized_action,
        "arg": normalized_arg,
        "command": command,
        "family": family_for_command(command),
    }


def maybe_queue_daily_observe(
    storage: Optional[Storage],
    profile_id: Optional[int],
    *,
    now: Optional[float] = None,
) -> dict[str, Any]:
    current_time = float(time.time() if now is None else now)
    if not storage or not profile_id:
        return {"queued": False, "stage": "skipped", "reason": "missing profile context"}
    if not is_tianxing_profile(storage, profile_id):
        return {"queued": False, "stage": "skipped", "reason": "not_tianxing_profile"}

    record = get_profile_record(storage, int(profile_id))
    state = normalize_state(record.get("state"))
    config = normalize_config(record.get("config"))
    day_key = get_day_key(current_time)
    observed_stars = _today_observed_stars(state, current_time)
    if observed_stars:
        return _maybe_queue_daily_set_star(
            storage,
            int(profile_id),
            state=state,
            config=config,
            available_stars=observed_stars,
            day_key=day_key,
            now=current_time,
        )
    if _has_today_observe_result(state, current_time):
        return {"queued": False, "stage": "observed", "reason": "no daily preferred stars"}
    if not config.get("auto_observe_enabled"):
        return {"queued": False, "stage": "disabled", "reason": "auto_observe disabled"}
    if str(state.get("daily_observe_queued_day") or "") == day_key:
        return {"queued": False, "stage": "waiting_observe", "reason": "daily observe already queued"}

    binding = _get_tianxing_command_binding(storage, int(profile_id))
    if not binding:
        return {"queued": False, "stage": "blocked", "reason": "missing chat binding"}
    command_id = _enqueue_if_not_blocking(
        storage,
        profile_id=int(profile_id),
        chat_id=int(binding.chat_id),
        command=".观命",
        thread_id=binding.thread_id,
        chat_type=binding.chat_type,
        bot_username=binding.bot_username or TIANXING_BOT_USERNAME,
    )
    state["daily_observe_queued_day"] = day_key
    state["daily_observe_queued_at"] = current_time
    save_profile_record(storage, int(profile_id), state=state)
    append_audit_event(
        storage,
        profile_id=int(profile_id),
        chat_id=int(binding.chat_id),
        thread_id=binding.thread_id,
        family="tianxing_daily_observe",
        event_type="daily_observe_queued" if command_id else "daily_observe_blocked",
        command_text=".观命",
        detail={"day": day_key, "command_id": command_id},
    )
    if not command_id:
        return {"queued": False, "stage": "blocked", "reason": "observe command already blocking"}
    return {
        "queued": True,
        "stage": "observe",
        "command": ".观命",
        "command_id": command_id,
    }


def tick_tianxing_timeline(
    storage: Optional[Storage],
    profile_id: Optional[int],
    *,
    now: Optional[float] = None,
) -> dict[str, Any]:
    current_time = float(time.time() if now is None else now)
    if not storage or not profile_id:
        return {"queued": False, "stage": "skipped", "reason": "missing profile context"}
    if not is_tianxing_profile(storage, profile_id):
        return {"queued": False, "stage": "skipped", "reason": "not_tianxing_profile"}

    record = get_profile_record(storage, int(profile_id))
    config = normalize_config(record.get("config"))
    if not config.get("timeline_enabled"):
        return {"queued": False, "stage": "disabled", "reason": "timeline disabled"}
    if config.get("timeline_dry_run_enabled"):
        return {"queued": False, "stage": "disabled", "reason": "timeline dry-run enabled"}

    binding = _get_tianxing_command_binding(storage, int(profile_id))
    if not binding:
        return {"queued": False, "stage": "blocked", "reason": "missing chat binding"}
    if _has_active_tianxing_outgoing(
        storage,
        profile_id=int(profile_id),
        chat_id=int(binding.chat_id),
        thread_id=binding.thread_id,
        now=current_time,
    ):
        return {"queued": False, "stage": "blocked", "reason": "active_tianxing_outgoing"}

    timeline = start_or_advance_timeline(
        storage,
        profile_id=int(profile_id),
        chat_id=int(binding.chat_id),
        route="探索",
        thread_id=binding.thread_id,
        chat_type=binding.chat_type,
        bot_username=binding.bot_username or TIANXING_BOT_USERNAME,
        now=current_time,
    )
    return {
        **timeline,
        "queued": _has_active_tianxing_outgoing(
            storage,
            profile_id=int(profile_id),
            chat_id=int(binding.chat_id),
            thread_id=binding.thread_id,
            now=current_time,
        ),
        "stage": str(timeline.get("phase") or "blocked_replan"),
    }


def start_craft_loop(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int] = None,
    chat_type: str = "group",
    bot_username: str = "",
    item: str = "玄铁剑",
    target_count: int = 30,
    now: Optional[float] = None,
) -> dict[str, Any]:
    current_time = float(time.time() if now is None else now)
    if not is_tianxing_profile(storage, profile_id):
        return {"active": False, "phase": "error", "reason": "not_tianxing_profile"}
    normalized_item = str(item or "玄铁剑").strip() or "玄铁剑"
    safe_count = max(1, int(target_count or 1))
    record = get_profile_record(storage, profile_id)
    state = normalize_state(record.get("state"))
    state.update(
        {
            "craft_loop_enabled": True,
            "craft_loop_item": normalized_item,
            "craft_loop_target_count": safe_count,
            "craft_loop_remaining": safe_count,
            "craft_loop_completed": 0,
            "craft_loop_phase": "idle",
            "craft_loop_last_error": "",
            "craft_loop_chat_id": int(chat_id),
            "craft_loop_thread_id": int(thread_id) if thread_id is not None else None,
            "craft_loop_chat_type": str(chat_type or "group").strip() or "group",
            "craft_loop_bot_username": str(bot_username or TIANXING_BOT_USERNAME).strip()
            or TIANXING_BOT_USERNAME,
            "craft_loop_last_command": "",
            "craft_loop_last_command_sent_at": 0,
            "craft_loop_ack_due_at": 0,
            "craft_loop_started_at": current_time,
            "craft_loop_finished_at": 0,
        }
    )
    save_profile_record(storage, profile_id, state=state)
    append_audit_event(
        storage,
        profile_id=profile_id,
        chat_id=int(chat_id),
        thread_id=thread_id,
        family="tianxing_craft_loop",
        event_type="craft_loop_started",
        route="炼制",
        detail={"item": normalized_item, "target_count": safe_count, "at": current_time},
    )
    return tick_craft_loop(storage, profile_id=profile_id, now=current_time)


def stop_craft_loop(
    storage: Storage,
    *,
    profile_id: int,
    now: Optional[float] = None,
    reason: str = "manual_stop",
) -> dict[str, Any]:
    current_time = float(time.time() if now is None else now)
    if not is_tianxing_profile(storage, profile_id):
        return {"active": False, "phase": "error", "reason": "not_tianxing_profile"}
    record = get_profile_record(storage, profile_id)
    state = normalize_state(record.get("state"))
    state["craft_loop_enabled"] = False
    state["craft_loop_phase"] = "stopped"
    state["craft_loop_last_error"] = ""
    state["craft_loop_last_command"] = ""
    state["craft_loop_ack_due_at"] = 0
    save_profile_record(storage, profile_id, state=state)
    append_audit_event(
        storage,
        profile_id=profile_id,
        chat_id=int(state.get("craft_loop_chat_id") or 0),
        thread_id=state.get("craft_loop_thread_id"),
        family="tianxing_craft_loop",
        event_type="craft_loop_stopped",
        route="炼制",
        detail={"reason": reason, "at": current_time},
    )
    return _craft_loop_result(state, queued=False, stage="stopped")


def tick_craft_loop(
    storage: Optional[Storage],
    profile_id: Optional[int],
    *,
    now: Optional[float] = None,
) -> dict[str, Any]:
    current_time = float(time.time() if now is None else now)
    if not storage or not profile_id:
        return {"queued": False, "stage": "skipped", "reason": "missing profile context"}
    if not is_tianxing_profile(storage, profile_id):
        return {"queued": False, "stage": "skipped", "reason": "not_tianxing_profile"}

    record = get_profile_record(storage, int(profile_id))
    state = normalize_state(record.get("state"))
    config = normalize_config(record.get("config"))
    if not state.get("craft_loop_enabled"):
        return _craft_loop_result(state, queued=False, stage="disabled")
    if config.get("timeline_enabled"):
        return stop_craft_loop(
            storage,
            profile_id=int(profile_id),
            now=current_time,
            reason="exploration_timeline_enabled",
        )
    if int(state.get("craft_loop_remaining") or 0) <= 0:
        state["craft_loop_enabled"] = False
        state["craft_loop_phase"] = "done"
        state["craft_loop_last_command"] = ""
        state["craft_loop_ack_due_at"] = 0
        state["craft_loop_finished_at"] = current_time
        save_profile_record(storage, int(profile_id), state=state)
        return _craft_loop_result(state, queued=False, stage="done")

    chat_id = int(state.get("craft_loop_chat_id") or 0)
    thread_id = state.get("craft_loop_thread_id")
    chat_type = str(state.get("craft_loop_chat_type") or "group")
    bot_username = str(state.get("craft_loop_bot_username") or TIANXING_BOT_USERNAME)
    if not chat_id:
        binding = _get_tianxing_command_binding(storage, int(profile_id))
        if not binding:
            return _craft_loop_blocked(storage, int(profile_id), state, "missing chat binding")
        chat_id = int(binding.chat_id)
        thread_id = binding.thread_id
        chat_type = binding.chat_type
        bot_username = binding.bot_username or TIANXING_BOT_USERNAME
        state["craft_loop_chat_id"] = chat_id
        state["craft_loop_thread_id"] = thread_id
        state["craft_loop_chat_type"] = chat_type
        state["craft_loop_bot_username"] = bot_username
        save_profile_record(storage, int(profile_id), state=state)

    phase = str(state.get("craft_loop_phase") or "idle")
    last_command = str(state.get("craft_loop_last_command") or "")
    if _promote_craft_loop_from_existing_prediction(
        storage,
        profile_id=int(profile_id),
        state=state,
        chat_id=chat_id,
        thread_id=thread_id,
        now=current_time,
    ):
        phase = str(state.get("craft_loop_phase") or "idle")
        last_command = str(state.get("craft_loop_last_command") or "")
    if phase == "await_predict":
        return _craft_loop_waiting_or_timeout(
            storage,
            int(profile_id),
            state,
            chat_id=chat_id,
            thread_id=thread_id,
            now=current_time,
            timeout_reason="推命回包超时，已改为查盘校准。",
            calibrate_prediction_on_timeout=True,
        )
    if phase == "await_predict_panel":
        return _craft_loop_waiting_or_timeout(
            storage,
            int(profile_id),
            state,
            chat_id=chat_id,
            thread_id=thread_id,
            now=current_time,
            timeout_reason="查盘校准回包超时，循环已停止。",
        )
    if phase == "await_craft" and last_command.startswith(".炼制 "):
        return _craft_loop_waiting_or_timeout(
            storage,
            int(profile_id),
            state,
            chat_id=chat_id,
            thread_id=thread_id,
            now=current_time,
            timeout_reason="炼制回包超时，循环已停止。",
        )

    if _has_active_tianxing_outgoing(
        storage,
        profile_id=int(profile_id),
        chat_id=chat_id,
        thread_id=thread_id,
        now=current_time,
    ):
        return _craft_loop_waiting_on_other_tianxing(storage, int(profile_id), state)

    if phase in {"idle", "stopped", "error", "done"}:
        command = ".推命 炼制"
        next_phase = "await_predict"
        event_type = "craft_loop_predict_queued"
    elif phase == "await_craft":
        command = _craft_loop_craft_command(state)
        next_phase = "await_craft"
        event_type = "craft_loop_craft_queued"
    else:
        return _craft_loop_blocked(storage, int(profile_id), state, "unsupported craft loop phase")

    command_id = _enqueue_if_not_blocking(
        storage,
        profile_id=int(profile_id),
        chat_id=chat_id,
        command=command,
        thread_id=thread_id,
        chat_type=chat_type,
        bot_username=bot_username,
        now=current_time,
    )
    if not command_id:
        return _craft_loop_blocked(storage, int(profile_id), state, "command already blocking")

    state["craft_loop_phase"] = next_phase
    state["craft_loop_last_error"] = ""
    state["craft_loop_last_command"] = command
    state["craft_loop_last_command_sent_at"] = current_time
    state["craft_loop_ack_due_at"] = current_time + float(config.get("ack_timeout_sec") or ACK_TIMEOUT_SECONDS)
    save_profile_record(storage, int(profile_id), state=state)
    append_audit_event(
        storage,
        profile_id=int(profile_id),
        chat_id=chat_id,
        thread_id=thread_id,
        family="tianxing_craft_loop",
        event_type=event_type,
        route="炼制",
        phase=next_phase,
        command_text=command,
        detail={
            "command_id": command_id,
            "remaining": int(state.get("craft_loop_remaining") or 0),
            "completed": int(state.get("craft_loop_completed") or 0),
        },
    )
    return _craft_loop_result(state, queued=True, stage=next_phase, command=command, command_id=command_id)


def build_timeline_plan(
    route: str,
    *,
    state: Optional[dict[str, Any]] = None,
    config: Optional[dict[str, Any]] = None,
    now: Optional[float] = None,
) -> dict[str, Any]:
    current_time = float(time.time() if now is None else now)
    normalized_route = _normalize_route(route)
    normalized_state = normalize_state(state)
    normalized_config = normalize_config(config)
    if not normalized_route:
        return {"active": False, "phase": "blocked_replan", "reason": "unknown route"}
    if not normalized_config.get("timeline_enabled"):
        return {"active": False, "phase": "blocked_replan", "route": normalized_route, "reason": "timeline disabled"}

    steps = []
    if normalized_config.get("auto_set_star_enabled") and not _has_today_fixed_star(
        normalized_state,
        current_time,
    ):
        available_stars = (
            _today_observed_stars(normalized_state, current_time)
            if normalized_route == "探索"
            else _today_available_stars(normalized_state, current_time)
        )
        if not available_stars:
            if normalized_route == "探索" and _has_today_observe_result(
                normalized_state,
                current_time,
            ):
                return {
                    "active": True,
                    "phase": "blocked_replan",
                    "route": normalized_route,
                    "reason": "no preferred star available today",
                }
            if normalized_config.get("auto_observe_enabled"):
                steps.append(_timeline_step("observe", ""))
            elif normalized_route != "探索" and normalized_config.get("auto_panel_enabled"):
                steps.append(_timeline_step("panel", normalized_route))
            else:
                return {
                    "active": True,
                    "phase": "blocked_replan",
                    "route": normalized_route,
                    "reason": (
                        "missing today's observe result"
                        if normalized_route == "探索"
                        else "missing today's available stars"
                    ),
                }
        else:
            star = _select_set_star(normalized_config, available_stars)
            if not star:
                return {
                    "active": True,
                    "phase": "blocked_replan",
                    "route": normalized_route,
                    "reason": "no preferred star available today",
                }
            steps.append(_timeline_step("set_star", star))
    if steps:
        return {
            "active": True,
            "phase": "waiting_send",
            "route": normalized_route,
            "steps": steps,
            "active_step_index": 0,
            "active_step": steps[0],
            "dry_run": bool(normalized_config.get("timeline_dry_run_enabled")),
        }

    prediction = str(normalized_state.get("current_prediction") or "")
    prediction_until = float(normalized_state.get("current_prediction_until") or 0)
    if prediction != normalized_route or prediction_until <= current_time:
        if not normalized_config.get("auto_predict_enabled"):
            return {
                "active": True,
                "phase": "blocked_replan",
                "route": normalized_route,
                "reason": "auto_predict disabled",
            }
        steps.append(_timeline_step("predict", normalized_route))
    if steps:
        return {
            "active": True,
            "phase": "waiting_send",
            "route": normalized_route,
            "steps": steps,
            "active_step_index": 0,
            "active_step": steps[0],
            "dry_run": bool(normalized_config.get("timeline_dry_run_enabled")),
        }

    if (
        normalized_route == "探索"
        and normalized_config.get("auto_panel_enabled")
        and str(normalized_state.get("current_prediction_until_source") or "") != "panel"
    ):
        steps.append(_timeline_step("panel", normalized_route))
        return {
            "active": True,
            "phase": "waiting_send",
            "route": normalized_route,
            "steps": steps,
            "active_step_index": 0,
            "active_step": steps[0],
            "dry_run": bool(normalized_config.get("timeline_dry_run_enabled")),
        }

    needs_change = normalized_route in set(normalized_config.get("change_route_priority") or [])
    change = str(normalized_state.get("current_change") or "")
    change_until = float(normalized_state.get("current_change_until") or 0)
    if needs_change and (change != normalized_route or change_until <= current_time):
        if not normalized_config.get("auto_change_fate_enabled"):
            return {
                "active": True,
                "phase": "blocked_replan",
                "route": normalized_route,
                "reason": "auto_change_fate disabled",
            }
        steps.append(_timeline_step("change_fate", normalized_route))

    if steps:
        return {
            "active": True,
            "phase": "waiting_send",
            "route": normalized_route,
            "steps": steps,
            "active_step_index": 0,
            "active_step": steps[0],
            "dry_run": bool(normalized_config.get("timeline_dry_run_enabled")),
        }

    if (
        needs_change
        and normalized_route == "探索"
        and normalized_config.get("auto_panel_enabled")
        and str(normalized_state.get("current_change_until_source") or "") != "panel"
    ):
        steps.append(_timeline_step("panel", normalized_route))
        return {
            "active": True,
            "phase": "waiting_send",
            "route": normalized_route,
            "steps": steps,
            "active_step_index": 0,
            "active_step": steps[0],
            "dry_run": bool(normalized_config.get("timeline_dry_run_enabled")),
        }

    if not steps:
        return {
            "active": True,
            "phase": "state_confirmed",
            "route": normalized_route,
            "steps": [],
            "reason": "state already confirmed",
        }
    return {
        "active": True,
        "phase": "waiting_send",
        "route": normalized_route,
        "steps": steps,
        "active_step_index": 0,
        "active_step": steps[0],
        "dry_run": bool(normalized_config.get("timeline_dry_run_enabled")),
    }


def start_or_advance_timeline(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    route: str,
    thread_id: Optional[int] = None,
    chat_type: str = "group",
    bot_username: str = "",
    now: Optional[float] = None,
) -> dict[str, Any]:
    current_time = float(time.time() if now is None else now)
    if not is_tianxing_profile(storage, profile_id):
        return {
            "active": False,
            "phase": "blocked_replan",
            "reason": "not_tianxing_profile",
            "next_time": current_time + CALIBRATION_BACKOFF_SECONDS,
        }
    record = get_profile_record(storage, profile_id)
    state = normalize_state(record.get("state"))
    config = normalize_config(record.get("config"))
    timeline = normalize_timeline(record.get("timeline"))

    if timeline.get("phase") == "sent_waiting_ack":
        active = dict(timeline.get("active_step") or {})
        ack_due_at = float(active.get("ack_due_at") or 0)
        if ack_due_at > current_time:
            return {"phase": "sent_waiting_ack", "active_step": active, "next_time": ack_due_at}
        timeline["phase"] = "ack_timeout"
        timeline["last_error"] = "ack timeout; scheduled panel calibration"
        timeline["blocked_until"] = current_time + config["calibration_backoff_sec"]
        timeline["active_step"] = {
            **active,
            "status": "ack_timeout",
            "calibration_due_at": timeline["blocked_until"],
        }
        if not config.get("timeline_dry_run_enabled"):
            _enqueue_if_not_blocking(
                storage,
                profile_id=profile_id,
                chat_id=chat_id,
                command=".天机盘",
                thread_id=thread_id,
                chat_type=chat_type,
                bot_username=bot_username,
                delay_seconds=config["calibration_backoff_sec"],
                now=current_time,
            )
        save_profile_record(storage, profile_id, timeline=timeline)
        append_audit_event(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            family="tianxing_timeline",
            event_type="timeline_ack_timeout",
            route=str(timeline.get("route") or route),
            phase="ack_timeout",
            detail={"active_step": active},
        )
        return {"phase": "ack_timeout", "next_time": timeline["blocked_until"]}

    if timeline.get("phase") == "ack_timeout":
        blocked_until = float(timeline.get("blocked_until") or 0)
        if blocked_until > current_time:
            return {"phase": "ack_timeout", "next_time": blocked_until}

    plan = build_timeline_plan(route, state=state, config=config, now=current_time)
    if not plan.get("active"):
        return plan
    if plan.get("phase") == "blocked_replan":
        timeline = {
            **timeline,
            "phase": "blocked_replan",
            "route": plan.get("route") or route,
            "steps": [],
            "active_step_index": -1,
            "active_step": {},
            "last_error": str(plan.get("reason") or ""),
            "updated_at": current_time,
        }
        save_profile_record(storage, profile_id, timeline=timeline)
        return {**plan, "next_time": current_time + config["calibration_backoff_sec"]}
    if plan.get("phase") == "state_confirmed":
        timeline = {
            **timeline,
            "phase": "state_confirmed",
            "route": plan["route"],
            "steps": [],
            "active_step_index": -1,
            "active_step": {},
            "updated_at": current_time,
        }
        save_profile_record(storage, profile_id, timeline=timeline)
        return release_route(storage, profile_id, plan["route"], source="timeline_state_confirmed", now=current_time)

    steps = list(plan.get("steps") or [])
    active = dict(steps[0])
    active["status"] = "dry_run" if plan.get("dry_run") else "sent_waiting_ack"
    active["sent_at"] = current_time
    active["ack_due_at"] = current_time + config["ack_timeout_sec"]
    timeline = {
        **timeline,
        "phase": "waiting_send" if plan.get("dry_run") else "sent_waiting_ack",
        "route": plan["route"],
        "steps": steps,
        "active_step_index": 0,
        "active_step": active,
        "last_error": "dry-run: command not sent" if plan.get("dry_run") else "",
        "updated_at": current_time,
    }
    if not plan.get("dry_run"):
        _enqueue_if_not_blocking(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            command=active["command"],
            thread_id=thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            now=current_time,
        )
    save_profile_record(storage, profile_id, timeline=timeline)
    append_audit_event(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        family="tianxing_timeline",
        event_type="timeline_step_planned" if plan.get("dry_run") else "timeline_step_queued",
        route=plan["route"],
        phase=timeline["phase"],
        command_text=active["command"],
        detail={"dry_run": bool(plan.get("dry_run")), "step": active},
    )
    return {"phase": timeline["phase"], "active_step": active, "dry_run": bool(plan.get("dry_run"))}


def update_timeline_on_confirmation(
    current: Optional[dict[str, Any]],
    parsed: dict[str, Any],
    command_text: str,
    *,
    now: Optional[float] = None,
) -> dict[str, Any]:
    current_time = float(time.time() if now is None else now)
    timeline = normalize_timeline(current)
    if timeline.get("phase") not in {"sent_waiting_ack", "waiting_send"}:
        return timeline
    active = dict(timeline.get("active_step") or {})
    if active.get("command") and str(active.get("command")) != str(command_text or "").strip():
        return timeline
    action = str(active.get("action") or "")
    route = str(active.get("route") or _route_from_parsed(parsed))
    if action == "panel" and parsed.get("action") != "天机盘":
        return timeline
    if action == "predict" and parsed.get("current_prediction") != route:
        return timeline
    if action == "change_fate" and parsed.get("current_change") != route:
        return timeline
    if action == "set_star" and not parsed.get("fixed_star"):
        return timeline
    active["status"] = "confirmed"
    active["confirmed_at"] = current_time
    timeline["phase"] = "state_confirmed"
    timeline["active_step"] = active
    timeline["updated_at"] = current_time
    return timeline


def release_route(
    storage: Storage,
    profile_id: int,
    route: str,
    *,
    source: str,
    now: Optional[float] = None,
) -> dict[str, Any]:
    current_time = float(time.time() if now is None else now)
    record = get_profile_record(storage, profile_id)
    state = normalize_state(record.get("state"))
    timeline = normalize_timeline(record.get("timeline"))
    normalized_route = _normalize_route(route)
    release = {"released_at": current_time, "source": source}
    state["released_routes"][normalized_route] = release
    timeline["released_routes"][normalized_route] = release
    timeline["phase"] = "downstream_released"
    timeline["updated_at"] = current_time
    save_profile_record(storage, profile_id, state=state, timeline=timeline)
    return {"phase": "downstream_released", "route": normalized_route, "released": True}


def is_route_released(
    storage: Storage,
    profile_id: int,
    route: str,
    *,
    require_change_fate: bool = False,
    now: Optional[float] = None,
    max_age_seconds: int = 3600,
    require_prediction: bool = False,
) -> bool:
    current_time = float(time.time() if now is None else now)
    record = get_profile_record(storage, profile_id)
    state = normalize_state(record.get("state"))
    normalized_route = _normalize_route(route)
    release = (state.get("released_routes") or {}).get(normalized_route) or {}
    released_at = float(release.get("released_at") or 0)
    if released_at <= 0 or current_time - released_at > max_age_seconds:
        return False
    prediction_ok = (
        state.get("current_prediction") == normalized_route
        and float(state.get("current_prediction_until") or 0) > current_time
        and (
            not require_prediction
            or str(state.get("current_prediction_until_source") or "") == "panel"
        )
    )
    if require_prediction and not prediction_ok:
        return False
    if not require_change_fate:
        return True
    return (
        state.get("current_change") == normalized_route
        and float(state.get("current_change_until") or 0) > current_time
        and str(state.get("current_change_until_source") or "") == "panel"
    )


def _block_exploration_route_gate(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    chat_type: str,
    bot_username: str,
    command: str,
    queue_enabled: bool,
    phase: str,
    reason: str,
    event_type: str,
    now: float,
    next_time: float,
    detail: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    command_id = None
    if queue_enabled and command:
        command_id = _enqueue_if_not_blocking(
            storage,
            profile_id=int(profile_id),
            chat_id=int(chat_id or 0),
            command=command,
            thread_id=thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
        )
    append_audit_event(
        storage,
        profile_id=int(profile_id),
        chat_id=int(chat_id or 0),
        thread_id=thread_id,
        family="tianxing_exploration_gate",
        event_type=event_type,
        route="探索",
        phase=phase,
        command_text=command if queue_enabled else "",
        detail={
            "reason": reason,
            "queued": command_id is not None,
            "command_id": command_id,
            "at": now,
            **(detail or {}),
        },
    )
    return {
        "allowed": False,
        "route": "探索",
        "high_risk_allowed": False,
        "phase": phase,
        "reason": reason,
        "next_time": next_time,
        "command": command if queue_enabled else "",
        "command_id": command_id,
    }


def build_exploration_gate(
    storage: Storage,
    profile_id: int,
    *,
    now: Optional[float] = None,
    high_risk: bool = False,
) -> dict[str, Any]:
    current_time = float(time.time() if now is None else now)
    record = get_profile_record(storage, profile_id)
    state = normalize_state(record.get("state"))
    if not _has_today_observe_result(state, current_time):
        return {
            "allowed": False,
            "route": "探索",
            "high_risk_allowed": False,
            "reason": "缺少今日观命结果",
        }
    if not _has_today_fixed_star(state, current_time):
        return {
            "allowed": False,
            "route": "探索",
            "high_risk_allowed": False,
            "reason": "缺少今日定命",
        }
    released = is_route_released(
        storage,
        profile_id,
        "探索",
        require_change_fate=True,
        require_prediction=True,
        now=current_time,
    )
    if released:
        return {"allowed": True, "route": "探索", "high_risk_allowed": True}
    return {
        "allowed": False,
        "route": "探索",
        "high_risk_allowed": False,
        "reason": "探索路线未确认改命放行" if high_risk else "缺少已确认的改命 探索",
    }


def build_exploration_route_gate(
    storage: Optional[Storage],
    *,
    profile_id: Optional[int],
    chat_id: int,
    thread_id: Optional[int] = None,
    chat_type: str = "group",
    bot_username: str = "",
    high_risk: bool = False,
    now: Optional[float] = None,
) -> dict[str, Any]:
    current_time = float(time.time() if now is None else now)
    if not storage or not profile_id:
        return {
            "allowed": False,
            "route": "探索",
            "phase": "blocked_replan",
            "reason": "缺少天星宗 profile 上下文，探索自动化已阻断",
            "next_time": current_time + CALIBRATION_BACKOFF_SECONDS,
        }
    if not is_tianxing_profile(storage, profile_id):
        return {
            "allowed": True,
            "active": False,
            "route": "探索",
            "phase": "not_tianxing_profile",
            "reason": "非天星宗 profile，跳过天星探索 gate",
            "next_time": current_time,
        }
    record = get_profile_record(storage, int(profile_id))
    state = normalize_state(record.get("state"))
    config = normalize_config(record.get("config"))
    if not _has_today_observe_result(state, current_time):
        return _block_exploration_route_gate(
            storage,
            profile_id=int(profile_id),
            chat_id=int(chat_id or 0),
            thread_id=thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            command=".观命",
            queue_enabled=bool(config.get("auto_observe_enabled")),
            phase="sent_waiting_ack" if config.get("auto_observe_enabled") else "blocked_replan",
            reason="等待今日观命结果" if config.get("auto_observe_enabled") else "缺少今日观命结果",
            event_type="observe_required",
            now=current_time,
            next_time=current_time + config["ack_timeout_sec"],
            detail={
                "available_stars_source": state.get("available_stars_source"),
                "available_stars_day": state.get("available_stars_day"),
                "observed_stars_day": state.get("observed_stars_day"),
            },
        )
    if not _has_today_fixed_star(state, current_time):
        available_stars = _today_observed_stars(state, current_time)
        star = _select_set_star(config, available_stars)
        command = f".定命 {star}" if star else ""
        return _block_exploration_route_gate(
            storage,
            profile_id=int(profile_id),
            chat_id=int(chat_id or 0),
            thread_id=thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            command=command,
            queue_enabled=bool(config.get("auto_set_star_enabled") and command),
            phase="sent_waiting_ack" if config.get("auto_set_star_enabled") and command else "blocked_replan",
            reason="等待今日定命" if config.get("auto_set_star_enabled") and command else "缺少今日定命",
            event_type="set_star_required",
            now=current_time,
            next_time=current_time + config["ack_timeout_sec"],
            detail={"available_stars": available_stars, "selected_star": star},
        )
    if (
        str(state.get("current_prediction") or "") != "探索"
        or float(state.get("current_prediction_until") or 0) <= current_time
    ):
        return _block_exploration_route_gate(
            storage,
            profile_id=int(profile_id),
            chat_id=int(chat_id or 0),
            thread_id=thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            command=".推命 探索",
            queue_enabled=bool(config.get("auto_predict_enabled")),
            phase="sent_waiting_ack" if config.get("auto_predict_enabled") else "blocked_replan",
            reason="等待推命 探索" if config.get("auto_predict_enabled") else "缺少有效推命 探索",
            event_type="predict_required",
            now=current_time,
            next_time=current_time + config["ack_timeout_sec"],
            detail={
                "current_prediction": state.get("current_prediction"),
                "current_prediction_until": state.get("current_prediction_until"),
            },
        )
    last_panel_checked_at = float(state.get("last_panel_checked_at") or 0)
    if (
        last_panel_checked_at <= 0
        or current_time - last_panel_checked_at > EXPLORATION_PANEL_FRESH_SECONDS
    ):
        return _block_exploration_route_gate(
            storage,
            profile_id=int(profile_id),
            chat_id=int(chat_id or 0),
            thread_id=thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            command=".天机盘",
            queue_enabled=bool(config.get("auto_panel_enabled")),
            phase="sent_waiting_ack" if config.get("auto_panel_enabled") else "blocked_replan",
            reason="等待天机盘查盘确认推命 探索" if config.get("auto_panel_enabled") else "缺少近期天机盘查盘确认",
            event_type="panel_required",
            now=current_time,
            next_time=current_time + config["ack_timeout_sec"],
            detail={"last_panel_checked_at": last_panel_checked_at},
        )
    gate = build_exploration_gate(
        storage,
        int(profile_id),
        now=current_time,
        high_risk=high_risk,
    )
    if gate.get("allowed"):
        return {
            **gate,
            "phase": "downstream_released",
            "next_time": current_time,
        }
    timeline = start_or_advance_timeline(
        storage,
        profile_id=int(profile_id),
        chat_id=int(chat_id or 0),
        route="探索",
        thread_id=thread_id,
        chat_type=chat_type,
        bot_username=bot_username,
        now=current_time,
    )
    phase = str(timeline.get("phase") or "blocked_replan")
    next_time = float(
        timeline.get("next_time")
        or (timeline.get("active_step") or {}).get("ack_due_at")
        or current_time + CALIBRATION_BACKOFF_SECONDS
    )
    reason = str(gate.get("reason") or "缺少已确认的改命 探索")
    append_audit_event(
        storage,
        profile_id=int(profile_id),
        chat_id=int(chat_id or 0),
        thread_id=thread_id,
        family="tianxing_exploration_gate",
        event_type="route_blocked",
        route="探索",
        phase=phase,
        detail={
            "reason": reason,
            "high_risk": bool(high_risk),
            "timeline": timeline,
        },
    )
    return {
        **gate,
        "allowed": False,
        "phase": phase,
        "reason": reason,
        "next_time": next_time,
        "timeline": timeline,
    }


def build_craft_farm_plan(
    storage: Storage,
    profile_id: int,
    *,
    last_reply_text: str = "",
    now: Optional[float] = None,
) -> dict[str, Any]:
    if not is_tianxing_profile(storage, profile_id):
        return {"active": False, "stage": "not_tianxing_profile", "reason": "not_tianxing_profile"}
    record = get_profile_record(storage, profile_id)
    config = normalize_config(record.get("config"))
    state = normalize_state(record.get("state"))
    if not config.get("craft_farm_enabled"):
        return {"active": False, "stage": "disabled", "reason": "craft farm disabled"}
    prediction_until = float(state.get("current_prediction_until") or 0)
    current_time = float(time.time() if now is None else now)
    if str(state.get("current_prediction") or "") != "炼制" or prediction_until <= current_time:
        return {"active": True, "stage": "timeline_required", "route": "炼制"}
    if last_reply_text:
        parsed = parse_tianxing_text(last_reply_text, now=now, family="tianxing_craft_farm")
        if parsed.get("action") == "炼制" and parsed.get("result") == "settlement":
            if parsed.get("last_tianji_gain") is None and "【推命" not in last_reply_text:
                return {
                    "active": True,
                    "stage": "waiting_calibration",
                    "command": ".天机盘",
                    "reason": "炼制成功但缺少天星推命结算",
                }
    return {
        "active": True,
        "stage": "dry_run" if config.get("craft_farm_dry_run_enabled") else "ready",
        "command": _craft_command(config),
        "route": "炼制",
    }


def advance_craft_farm(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int] = None,
    chat_type: str = "group",
    bot_username: str = "",
    now: Optional[float] = None,
) -> dict[str, Any]:
    current_time = float(time.time() if now is None else now)
    if not is_tianxing_profile(storage, profile_id):
        return {"active": False, "stage": "not_tianxing_profile", "reason": "not_tianxing_profile"}
    record = get_profile_record(storage, profile_id)
    config = normalize_config(record.get("config"))
    plan = build_craft_farm_plan(storage, profile_id, now=current_time)
    if not plan.get("active"):
        return plan
    if plan.get("stage") == "timeline_required":
        timeline = start_or_advance_timeline(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            route="炼制",
            thread_id=thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            now=current_time,
        )
        return {
            **plan,
            "timeline": timeline,
            "phase": timeline.get("phase") or "blocked_replan",
            "next_time": timeline.get("next_time")
            or (timeline.get("active_step") or {}).get("ack_due_at")
            or current_time + config["calibration_backoff_sec"],
        }
    command = str(plan.get("command") or "").strip()
    if not command:
        return {**plan, "stage": "blocked", "reason": "missing craft command"}
    latest = storage.get_latest_outgoing_command(
        chat_id,
        profile_id=profile_id,
        text=command,
        thread_id=thread_id,
    )
    if latest and str(latest.get("status") or "") in OUTGOING_BLOCKING_STATUSES:
        return {**plan, "stage": "waiting_reply", "command": command}
    append_audit_event(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        family="tianxing_craft_farm",
        event_type="craft_planned" if config.get("craft_farm_dry_run_enabled") else "craft_queued",
        route="炼制",
        command_text=command,
        detail={"dry_run": bool(config.get("craft_farm_dry_run_enabled"))},
    )
    if config.get("craft_farm_dry_run_enabled"):
        return {**plan, "stage": "dry_run", "command": command}
    command_id = storage.enqueue_outgoing_command(
        profile_id=profile_id,
        chat_id=chat_id,
        text=command,
        thread_id=thread_id,
        chat_type=chat_type,
        bot_username=bot_username,
    )
    return {**plan, "stage": "queued", "command": command, "command_id": command_id}


def build_retreat_farm_plan(
    storage: Storage,
    profile_id: int,
    *,
    deep_retreat: bool = False,
) -> dict[str, Any]:
    if not is_tianxing_profile(storage, profile_id):
        return {"active": False, "stage": "not_tianxing_profile", "reason": "not_tianxing_profile"}
    record = get_profile_record(storage, profile_id)
    config = normalize_config(record.get("config"))
    if not config.get("retreat_farm_enabled"):
        return {"active": False, "stage": "disabled", "reason": "retreat farm disabled"}
    if deep_retreat and not config.get("deep_retreat_consume_enabled"):
        return {
            "active": True,
            "stage": "deep_retreat_no_change_fate",
            "command": "",
            "reason": "deep retreat does not consume 闭关改命 by default",
        }
    return {
        "active": True,
        "stage": "dry_run" if config.get("retreat_farm_dry_run_enabled") else "ready",
        "command": ".闭关修炼",
        "route": "闭关",
    }


def build_retreat_route_gate(
    storage: Optional[Storage],
    *,
    profile_id: Optional[int],
    chat_id: int,
    thread_id: Optional[int] = None,
    chat_type: str = "group",
    bot_username: str = "",
    deep_retreat: bool = False,
    now: Optional[float] = None,
) -> dict[str, Any]:
    current_time = float(time.time() if now is None else now)
    if not storage or not profile_id:
        return {"allowed": True, "active": False, "reason": "missing Tianxing context"}
    if not is_tianxing_profile(storage, profile_id):
        return {"allowed": True, "active": False, "reason": "not_tianxing_profile"}
    record = get_profile_record(storage, int(profile_id))
    config = normalize_config(record.get("config"))
    if not config.get("retreat_farm_enabled"):
        return {"allowed": True, "active": False, "reason": "retreat farm disabled"}
    if deep_retreat and not config.get("deep_retreat_consume_enabled"):
        return {
            "allowed": True,
            "active": True,
            "route": "闭关",
            "stage": "deep_retreat_no_change_fate",
            "reason": "deep retreat does not consume 闭关改命 by default",
        }
    state = normalize_state(record.get("state"))
    prediction_until = float(state.get("current_prediction_until") or 0)
    if str(state.get("current_prediction") or "") == "闭关" and prediction_until > current_time:
        return {
            "allowed": True,
            "active": True,
            "route": "闭关",
            "phase": "state_confirmed",
        }
    timeline = start_or_advance_timeline(
        storage,
        profile_id=int(profile_id),
        chat_id=int(chat_id or 0),
        route="闭关",
        thread_id=thread_id,
        chat_type=chat_type,
        bot_username=bot_username,
        now=current_time,
    )
    phase = str(timeline.get("phase") or "blocked_replan")
    next_time = float(
        timeline.get("next_time")
        or (timeline.get("active_step") or {}).get("ack_due_at")
        or current_time + config["calibration_backoff_sec"]
    )
    append_audit_event(
        storage,
        profile_id=int(profile_id),
        chat_id=int(chat_id or 0),
        thread_id=thread_id,
        family="tianxing_retreat_farm",
        event_type="route_blocked",
        route="闭关",
        phase=phase,
        detail={
            "reason": "缺少已确认的推命 闭关",
            "deep_retreat": bool(deep_retreat),
            "timeline": timeline,
        },
    )
    return {
        "allowed": False,
        "active": True,
        "route": "闭关",
        "phase": phase,
        "reason": "缺少已确认的推命 闭关",
        "next_time": next_time,
        "timeline": timeline,
    }


def get_status_snapshot(storage: Storage, profile_id: int) -> dict[str, Any]:
    record = get_profile_record(storage, profile_id)
    state = normalize_state(record.get("state"))
    config = normalize_config(record.get("config"))
    return {
        "state": state,
        "config": config,
        "timeline": normalize_timeline(record.get("timeline")),
        "recent_audit_events": list_audit_events(storage, profile_id, limit=10),
        "craft_loop_view": _build_craft_loop_view(storage, profile_id, state),
    }


def _build_craft_loop_view(
    storage: Storage,
    profile_id: int,
    state: dict[str, Any],
    *,
    now: Optional[float] = None,
) -> dict[str, Any]:
    current_time = float(time.time() if now is None else now)
    enabled = bool(state.get("craft_loop_enabled"))
    phase = str(state.get("craft_loop_phase") or "idle")
    last_command = str(state.get("craft_loop_last_command") or "").strip()
    ack_due_at = float(state.get("craft_loop_ack_due_at") or 0)
    started_at = float(state.get("craft_loop_started_at") or 0)
    finished_at = float(state.get("craft_loop_finished_at") or 0)
    chat_id = int(state.get("craft_loop_chat_id") or 0)
    thread_id = state.get("craft_loop_thread_id")
    latest = (
        storage.get_latest_outgoing_command(
            chat_id,
            profile_id=profile_id,
            text=last_command,
            thread_id=thread_id,
        )
        if enabled and chat_id and last_command
        else None
    )
    active_other = (
        _get_active_tianxing_outgoing(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            now=current_time,
        )
        if enabled and chat_id and not last_command
        else None
    )
    action_text = "循环未开启"
    detail_text = ""
    if enabled:
        if phase == "await_predict":
            action_text = f"{_craft_loop_command_status_label(latest)} {last_command or '.推命 炼制'}，等待 bot 回包"
            detail_text = _craft_loop_wait_detail(ack_due_at, current_time)
        elif phase == "await_predict_panel":
            action_text = f"推命回包超时，{_craft_loop_command_status_label(latest)} {last_command or '.天机盘'} 校准"
            detail_text = _craft_loop_wait_detail(ack_due_at, current_time)
        elif phase == "await_craft":
            if last_command:
                action_text = f"{_craft_loop_command_status_label(latest)} {last_command}，等待 bot 回包"
                detail_text = _craft_loop_wait_detail(ack_due_at, current_time)
            else:
                action_text = f"推命炼制已就绪，等待发送 {_craft_loop_craft_command(state)}"
        elif active_other:
            action_text = f"暂停等待其他天星命令完成：{str(active_other.get('text') or '').strip()}"
            detail_text = _craft_loop_outgoing_status_label(active_other)
        elif phase == "idle":
            action_text = "等待下一轮 tick 排 .推命 炼制"
        elif phase == "done":
            action_text = "循环已完成"
        elif phase == "stopped":
            action_text = "循环已停止"
        elif phase == "error":
            action_text = str(state.get("craft_loop_last_error") or "循环异常停止。")
        else:
            action_text = phase
    duration_text = "-"
    duration_until = finished_at if finished_at > 0 else (current_time if enabled and started_at > 0 else 0)
    if started_at > 0 and duration_until > 0:
        duration_text = _format_craft_loop_duration(int(round(duration_until - started_at)))
    return {
        "action_text": action_text,
        "detail_text": detail_text,
        "last_command": last_command,
        "ack_due_at": ack_due_at,
        "started_at": started_at,
        "finished_at": finished_at,
        "started_text": _format_craft_loop_clock(started_at) if started_at > 0 else "-",
        "finished_text": _format_craft_loop_clock(finished_at) if finished_at > 0 else "-",
        "duration_text": duration_text,
        "latest_command_status": str((latest or {}).get("status") or ""),
    }


def _craft_loop_command_status_label(command: Optional[dict[str, Any]]) -> str:
    status = str((command or {}).get("status") or "").strip()
    if status in {"pending", "sending"}:
        return "已排队"
    if status in {"awaiting_confirm", "needs_manual_confirm"}:
        return "已发送"
    if status == "confirmed":
        return "已确认"
    return "已排队"


def _craft_loop_outgoing_status_label(command: Optional[dict[str, Any]]) -> str:
    if not command:
        return ""
    status = str(command.get("status") or "").strip()
    if status == "pending":
        return "命令已排队，等待发送。"
    if status in {"sending", "awaiting_confirm"}:
        return "命令已发送，等待 bot 回包。"
    if status == "needs_manual_confirm":
        return "命令等待人工确认窗口结束。"
    return status


def _craft_loop_wait_detail(ack_due_at: float, now: float) -> str:
    if ack_due_at <= 0:
        return ""
    if ack_due_at <= now:
        return "已到回包截止时间，等待 worker 处理。"
    remaining = int(round(ack_due_at - now))
    return f"最晚等到 {_format_craft_loop_clock(ack_due_at)}，剩余约 {_format_craft_loop_duration(remaining)}。"


def _format_craft_loop_clock(timestamp: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(float(timestamp)))


def _format_craft_loop_duration(seconds: int) -> str:
    safe_seconds = max(0, int(seconds))
    if safe_seconds < 60:
        return f"{safe_seconds} 秒"
    minutes, rest = divmod(safe_seconds, 60)
    return f"{minutes} 分 {rest} 秒" if rest else f"{minutes} 分"


def _decode_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_id": int(row.get("profile_id") or 0),
        "state": normalize_state(_loads(row.get("state_json"))),
        "config": normalize_config(_loads(row.get("config_json"))),
        "timeline": normalize_timeline(_loads(row.get("timeline_json"))),
        "created_at": float(row.get("created_at") or 0),
        "updated_at": float(row.get("updated_at") or 0),
    }


def _loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    raw = str(value).strip().lower()
    if raw in {"1", "true", "yes", "on", "enable", "enabled", "开", "开启"}:
        return True
    if raw in {"0", "false", "no", "off", "disable", "disabled", "关", "关闭"}:
        return False
    return bool(default)


def _normalize_route(value: str) -> str:
    raw = str(value or "").strip()
    return raw if raw in TIANXING_ROUTES else ""


def _normalize_route_list(value: Any, default: list[str]) -> list[str]:
    raw_items = value if isinstance(value, list) else []
    result = []
    for item in raw_items:
        route = _normalize_route(str(item))
        if route and route not in result:
            result.append(route)
    return result or list(default)


def _has_today_fixed_star(state: dict[str, Any], now: float) -> bool:
    return bool(state.get("fixed_star")) and str(state.get("fixed_star_day") or "") == get_day_key(now)


def _has_today_observe_result(state: dict[str, Any], now: float) -> bool:
    return str(state.get("observed_stars_day") or "") == get_day_key(now) and (
        bool(_today_observed_stars(state, now))
        or float(state.get("observed_stars_at") or 0) > 0
    )


def _today_available_stars(state: dict[str, Any], now: float) -> list[str]:
    if str(state.get("available_stars_day") or "") != get_day_key(now):
        return []
    stars = state.get("available_stars") if isinstance(state.get("available_stars"), list) else []
    return [star for star in stars if star in TIANXING_STARS]


def _today_observed_stars(state: dict[str, Any], now: float) -> list[str]:
    if str(state.get("observed_stars_day") or "") != get_day_key(now):
        return []
    stars = state.get("observed_stars") if isinstance(state.get("observed_stars"), list) else []
    return [star for star in stars if star in TIANXING_STARS]


def _set_star_candidates(config: dict[str, Any]) -> list[str]:
    target = str(config.get("set_star_name") or "").strip()
    candidates = []
    if target in TIANXING_STARS:
        candidates.append(target)
    for star in DAILY_SET_STAR_PRIORITY:
        if star not in candidates:
            candidates.append(star)
    return candidates


def _select_set_star(config: dict[str, Any], available_stars: list[str]) -> str:
    available = set(available_stars or [])
    for star in _set_star_candidates(config):
        if star in available:
            return star
    return ""


def _get_tianxing_command_binding(storage: Storage, profile_id: int):
    return storage.get_primary_chat_binding(
        int(profile_id),
        bot_username=TIANXING_BOT_USERNAME,
    ) or storage.get_primary_chat_binding(int(profile_id))


def _maybe_queue_daily_set_star(
    storage: Storage,
    profile_id: int,
    *,
    state: dict[str, Any],
    config: dict[str, Any],
    available_stars: list[str],
    day_key: str,
    now: float,
) -> dict[str, Any]:
    if _has_today_fixed_star(state, now):
        return {"queued": False, "stage": "done", "reason": "today star already fixed"}
    if not config.get("auto_set_star_enabled"):
        return {"queued": False, "stage": "observed", "reason": "auto_set_star disabled"}
    if str(state.get("daily_set_star_queued_day") or "") == day_key:
        return {"queued": False, "stage": "waiting_set_star", "reason": "daily set-star already queued"}

    star = _select_set_star(config, available_stars)
    if not star:
        return {"queued": False, "stage": "blocked", "reason": "no preferred star available today"}
    binding = _get_tianxing_command_binding(storage, int(profile_id))
    if not binding:
        return {"queued": False, "stage": "blocked", "reason": "missing chat binding"}

    command = f".定命 {star}"
    command_id = _enqueue_if_not_blocking(
        storage,
        profile_id=int(profile_id),
        chat_id=int(binding.chat_id),
        command=command,
        thread_id=binding.thread_id,
        chat_type=binding.chat_type,
        bot_username=binding.bot_username or TIANXING_BOT_USERNAME,
    )
    state["daily_set_star_queued_day"] = day_key
    state["daily_set_star_queued_at"] = now
    save_profile_record(storage, int(profile_id), state=state)
    append_audit_event(
        storage,
        profile_id=int(profile_id),
        chat_id=int(binding.chat_id),
        thread_id=binding.thread_id,
        family="tianxing_daily_set_star",
        event_type="daily_set_star_queued" if command_id else "daily_set_star_blocked",
        command_text=command,
        detail={"day": day_key, "star": star, "command_id": command_id},
    )
    if not command_id:
        return {"queued": False, "stage": "blocked", "reason": "set-star command already blocking"}
    return {
        "queued": True,
        "stage": "set_star",
        "star": star,
        "command": command,
        "command_id": command_id,
    }


def _route_from_parsed(parsed: dict[str, Any]) -> str:
    for key in ("current_prediction", "current_change", "prediction_consumed_route", "last_route"):
        route = _normalize_route(str(parsed.get(key) or ""))
        if route:
            return route
    action = str(parsed.get("action") or "")
    return _normalize_route(action)


def _dry_or_block_plan(action: str, command: str, config: dict[str, Any]) -> dict[str, Any]:
    if config.get("strategy_dry_run_enabled"):
        return {
            "allowed": True,
            "dry_run": True,
            "action": action,
            "command": command,
            "family": family_for_command(command),
            "reason": "strategy dry-run",
        }
    return {"allowed": False, "dry_run": False, "action": action, "command": command, "reason": "disabled"}


def _timeline_step(action: str, route: str) -> dict[str, Any]:
    command = command_for_action(action, route)
    return {
        "action": action,
        "route": route,
        "command": command,
        "family": family_for_command(command),
        "status": "pending",
    }


def _is_outgoing_command_blocking(
    command: Optional[dict[str, Any]],
    *,
    now: Optional[float] = None,
    manual_confirm_block_seconds: float = OUTGOING_CONFIRM_TIMEOUT_SECONDS,
) -> bool:
    if not command:
        return False
    status = str(command.get("status") or "").strip()
    if status not in OUTGOING_BLOCKING_STATUSES:
        return False
    if status != OUTGOING_NEEDS_MANUAL_CONFIRM_STATUS:
        return True
    updated_at = float(command.get("updated_at") or command.get("created_at") or 0)
    if updated_at <= 0:
        return True
    current_time = float(time.time() if now is None else now)
    return current_time - updated_at < float(manual_confirm_block_seconds)


def _has_active_tianxing_outgoing(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    now: Optional[float] = None,
) -> bool:
    return (
        _get_active_tianxing_outgoing(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            now=now,
        )
        is not None
    )


def _get_active_tianxing_outgoing(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    now: Optional[float] = None,
) -> Optional[dict[str, Any]]:
    statuses = tuple(OUTGOING_BLOCKING_STATUSES)
    placeholders = ",".join("?" for _ in statuses)
    params: list[Any] = [int(profile_id), int(chat_id), *statuses]
    thread_filter = "thread_id IS NULL"
    if thread_id is not None:
        thread_filter = "thread_id=?"
        params.append(int(thread_id))
    with storage.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM outgoing_commands
            WHERE profile_id=?
              AND chat_id=?
              AND status IN ({placeholders})
              AND {thread_filter}
              AND (
                text IN ('.观命', '.天机盘', '.消劫', '.闭关修炼')
                OR text LIKE '.定命 %'
                OR text LIKE '.推命 %'
                OR text LIKE '.改命 %'
                OR text LIKE '.炼制 %'
              )
            ORDER BY updated_at DESC, created_at DESC, id DESC
            """,
            params,
        ).fetchall()
    for row in rows:
        command = dict(row)
        if _is_outgoing_command_blocking(command, now=now):
            return command
    return None


def _enqueue_if_not_blocking(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    command: str,
    thread_id: Optional[int],
    chat_type: str,
    bot_username: str,
    delay_seconds: int = 0,
    now: Optional[float] = None,
) -> Optional[int]:
    latest = storage.get_latest_outgoing_command(
        chat_id,
        profile_id=profile_id,
        text=command,
        thread_id=thread_id,
    )
    if _is_outgoing_command_blocking(latest, now=now):
        return None
    return int(
        storage.enqueue_outgoing_command(
            profile_id=profile_id,
            chat_id=chat_id,
            text=command,
            thread_id=thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            delay_seconds=delay_seconds,
        )
    )


def _craft_loop_result(
    state: dict[str, Any],
    *,
    queued: bool,
    stage: str,
    command: str = "",
    command_id: Optional[int] = None,
) -> dict[str, Any]:
    result = {
        "active": bool(state.get("craft_loop_enabled")),
        "phase": str(state.get("craft_loop_phase") or "idle"),
        "stage": stage,
        "queued": bool(queued),
        "item": str(state.get("craft_loop_item") or "玄铁剑"),
        "target_count": int(state.get("craft_loop_target_count") or 0),
        "remaining": int(state.get("craft_loop_remaining") or 0),
        "completed": int(state.get("craft_loop_completed") or 0),
        "last_error": str(state.get("craft_loop_last_error") or ""),
    }
    if command:
        result["command"] = command
    if command_id is not None:
        result["command_id"] = command_id
    return result


def _craft_loop_craft_command(state: dict[str, Any]) -> str:
    item = str(state.get("craft_loop_item") or "玄铁剑").strip() or "玄铁剑"
    return f".炼制 {item}"


def _craft_loop_blocked(
    storage: Storage,
    profile_id: int,
    state: dict[str, Any],
    reason: str,
) -> dict[str, Any]:
    state["craft_loop_last_error"] = reason
    save_profile_record(storage, profile_id, state=state)
    return _craft_loop_result(state, queued=False, stage="blocked")


def _craft_loop_waiting_on_other_tianxing(
    storage: Storage,
    profile_id: int,
    state: dict[str, Any],
) -> dict[str, Any]:
    state["craft_loop_last_error"] = ""
    save_profile_record(storage, profile_id, state=state)
    return _craft_loop_result(state, queued=False, stage="waiting_other_tianxing")


def _craft_loop_waiting_or_timeout(
    storage: Storage,
    profile_id: int,
    state: dict[str, Any],
    *,
    chat_id: int,
    thread_id: Optional[int],
    now: float,
    timeout_reason: str,
    calibrate_prediction_on_timeout: bool = False,
) -> dict[str, Any]:
    ack_due_at = float(state.get("craft_loop_ack_due_at") or 0)
    if ack_due_at <= 0 or ack_due_at > now:
        return _craft_loop_result(
            state,
            queued=False,
            stage="waiting_reply",
            command=str(state.get("craft_loop_last_command") or ""),
        )
    _fail_latest_craft_loop_command(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        command_text=str(state.get("craft_loop_last_command") or ""),
        sent_at=float(state.get("craft_loop_last_command_sent_at") or 0),
        reason=timeout_reason,
    )
    if calibrate_prediction_on_timeout:
        return _craft_loop_queue_predict_panel_calibration(
            storage,
            profile_id,
            state,
            chat_id=chat_id,
            thread_id=thread_id,
            now=now,
        )
    state["craft_loop_enabled"] = False
    state["craft_loop_phase"] = "error"
    state["craft_loop_last_error"] = timeout_reason
    state["craft_loop_last_command"] = ""
    state["craft_loop_ack_due_at"] = 0
    state["craft_loop_finished_at"] = now
    save_profile_record(storage, profile_id, state=state)
    append_audit_event(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        family="tianxing_craft_loop",
        event_type="craft_loop_timeout",
        route="炼制",
        phase="error",
        detail={"reason": timeout_reason, "at": now},
    )
    return _craft_loop_result(state, queued=False, stage="error")


def _craft_loop_queue_predict_panel_calibration(
    storage: Storage,
    profile_id: int,
    state: dict[str, Any],
    *,
    chat_id: int,
    thread_id: Optional[int],
    now: float,
) -> dict[str, Any]:
    command = ".天机盘"
    chat_type = str(state.get("craft_loop_chat_type") or "group")
    bot_username = str(state.get("craft_loop_bot_username") or TIANXING_BOT_USERNAME)
    record = get_profile_record(storage, profile_id)
    config = normalize_config(record.get("config"))
    command_id = _enqueue_if_not_blocking(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        command=command,
        thread_id=thread_id,
        chat_type=chat_type,
        bot_username=bot_username,
        now=now,
    )
    if not command_id:
        state["craft_loop_phase"] = "await_predict_panel"
        state["craft_loop_last_error"] = ""
        state["craft_loop_last_command"] = command
        state["craft_loop_last_command_sent_at"] = now
        state["craft_loop_ack_due_at"] = now + float(config.get("ack_timeout_sec") or ACK_TIMEOUT_SECONDS)
        save_profile_record(storage, profile_id, state=state)
        return _craft_loop_result(state, queued=False, stage="await_predict_panel", command=command)
    state["craft_loop_phase"] = "await_predict_panel"
    state["craft_loop_last_error"] = ""
    state["craft_loop_last_command"] = command
    state["craft_loop_last_command_sent_at"] = now
    state["craft_loop_ack_due_at"] = now + float(config.get("ack_timeout_sec") or ACK_TIMEOUT_SECONDS)
    save_profile_record(storage, profile_id, state=state)
    append_audit_event(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        family="tianxing_craft_loop",
        event_type="craft_loop_predict_panel_queued",
        route="炼制",
        phase="await_predict_panel",
        command_text=command,
        detail={"reason": "predict_reply_timeout", "command_id": command_id, "at": now},
    )
    return _craft_loop_result(
        state,
        queued=True,
        stage="await_predict_panel",
        command=command,
        command_id=command_id,
    )


def _fail_latest_craft_loop_command(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    command_text: str,
    sent_at: float,
    reason: str,
) -> None:
    normalized_command = str(command_text or "").strip()
    if not normalized_command:
        return
    statuses = tuple(OUTGOING_BLOCKING_STATUSES)
    placeholders = ",".join("?" for _ in statuses)
    params: list[Any] = [int(profile_id), int(chat_id), normalized_command, *statuses]
    thread_filter = "thread_id IS NULL"
    if thread_id is not None:
        thread_filter = "thread_id=?"
        params.append(int(thread_id))
    time_filter = ""
    if sent_at > 0:
        time_filter = "AND created_at>=?"
        params.append(float(sent_at) - 1)
    with storage.connect() as conn:
        row = conn.execute(
            f"""
            SELECT id
            FROM outgoing_commands
            WHERE profile_id=?
              AND chat_id=?
              AND text=?
              AND status IN ({placeholders})
              AND {thread_filter}
              {time_filter}
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
    if not row:
        return
    storage.mark_outgoing_command_failed(int(row["id"]), reason)


def _confirm_latest_craft_loop_command(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    command_text: str,
) -> None:
    latest = storage.get_latest_outgoing_command(
        chat_id,
        profile_id=profile_id,
        text=command_text,
        thread_id=thread_id,
    )
    if latest and str(latest.get("status") or "") in OUTGOING_BLOCKING_STATUSES:
        storage.mark_outgoing_command_confirmed(
            int(latest["id"]),
            reason="confirmed by tianxing craft loop reply",
        )


def _has_live_craft_prediction(state: dict[str, Any], now: float) -> bool:
    return (
        str(state.get("current_prediction") or "").strip() == "炼制"
        and float(state.get("current_prediction_until") or 0) > float(now)
    )


def _confirm_latest_craft_prediction_command(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    reason: str,
) -> bool:
    params: list[Any] = [
        int(profile_id),
        int(chat_id),
        ".推命 炼制",
        OUTGOING_AWAITING_CONFIRM_STATUS,
        OUTGOING_NEEDS_MANUAL_CONFIRM_STATUS,
    ]
    thread_filter = "thread_id IS NULL"
    if thread_id is not None:
        thread_filter = "(thread_id=? OR thread_id IS NULL)"
        params.append(int(thread_id))
    with storage.connect() as conn:
        row = conn.execute(
            f"""
            SELECT *
            FROM outgoing_commands
            WHERE profile_id=?
              AND chat_id=?
              AND text=?
              AND status IN (?, ?)
              AND {thread_filter}
            ORDER BY updated_at DESC, created_at DESC, id DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
    if not row:
        return False
    storage.mark_outgoing_command_confirmed(int(row["id"]), reason=reason)
    return True


def _confirm_craft_prediction_from_panel_evidence(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    parsed: dict[str, Any],
    now: float,
) -> bool:
    if parsed.get("action") != "天机盘" or parsed.get("result") != "panel":
        return False
    if str(parsed.get("current_prediction") or "").strip() != "炼制":
        return False
    if float(parsed.get("current_prediction_until") or 0) <= float(now):
        return False
    confirmed = _confirm_latest_craft_prediction_command(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        reason="confirmed by tianxing panel craft prediction",
    )
    if confirmed:
        append_audit_event(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            family="tianxing_craft_loop",
            event_type="craft_predict_confirmed_by_panel",
            route="炼制",
            command_text=".推命 炼制",
            detail={"at": now},
        )
    return confirmed


def _promote_craft_loop_from_existing_prediction(
    storage: Storage,
    *,
    profile_id: int,
    state: dict[str, Any],
    chat_id: int,
    thread_id: Optional[int],
    now: float,
) -> bool:
    if not state.get("craft_loop_enabled"):
        return False
    if not _has_live_craft_prediction(state, now):
        return False
    phase = str(state.get("craft_loop_phase") or "idle")
    last_command = str(state.get("craft_loop_last_command") or "").strip()
    if phase == "await_craft" and last_command.startswith(".炼制 "):
        return False
    if phase not in {"idle", "stopped", "error", "done", "await_predict", "await_craft"}:
        return False
    _confirm_latest_craft_prediction_command(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        reason="confirmed by existing tianxing craft prediction",
    )
    if phase == "await_craft" and not last_command:
        return False
    state["craft_loop_phase"] = "await_craft"
    state["craft_loop_last_error"] = ""
    state["craft_loop_last_command"] = ""
    state["craft_loop_ack_due_at"] = 0
    save_profile_record(storage, profile_id, state=state)
    append_audit_event(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        family="tianxing_craft_loop",
        event_type="craft_loop_existing_prediction_ready",
        route="炼制",
        phase="await_craft",
        command_text=".推命 炼制",
        detail={"at": now},
    )
    return True


def _advance_craft_loop_on_reply(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    command_text: str,
    parsed: dict[str, Any],
    now: float,
) -> Optional[dict[str, Any]]:
    record = get_profile_record(storage, profile_id)
    state = normalize_state(record.get("state"))
    if not state.get("craft_loop_enabled"):
        return None
    phase = str(state.get("craft_loop_phase") or "idle")
    normalized_command = str(command_text or "").strip()
    if phase == "await_predict" and normalized_command == ".推命 炼制":
        if str(parsed.get("current_prediction") or "") != "炼制":
            state["craft_loop_enabled"] = False
            state["craft_loop_phase"] = "error"
            state["craft_loop_last_error"] = "推命未确认炼制，循环已停止。"
            state["craft_loop_last_command"] = ""
            state["craft_loop_ack_due_at"] = 0
            state["craft_loop_finished_at"] = now
            save_profile_record(storage, profile_id, state=state)
            return _craft_loop_result(state, queued=False, stage="error")
        _confirm_latest_craft_loop_command(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            command_text=normalized_command,
        )
        state["craft_loop_phase"] = "await_craft"
        state["craft_loop_last_error"] = ""
        state["craft_loop_last_command"] = ""
        state["craft_loop_ack_due_at"] = 0
        save_profile_record(storage, profile_id, state=state)
        append_audit_event(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            family="tianxing_craft_loop",
            event_type="craft_loop_predict_confirmed",
            route="炼制",
            phase="await_craft",
            command_text=normalized_command,
            detail={"remaining": int(state.get("craft_loop_remaining") or 0), "at": now},
        )
        return _craft_loop_result(state, queued=False, stage="await_craft")

    if phase == "await_predict_panel" and normalized_command == ".天机盘":
        _confirm_latest_craft_loop_command(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            command_text=normalized_command,
        )
        if not _has_live_craft_prediction(apply_parsed_to_state(state, parsed, now=now), now):
            state["craft_loop_enabled"] = False
            state["craft_loop_phase"] = "error"
            state["craft_loop_last_error"] = "查盘未确认炼制推命，循环已停止。"
            state["craft_loop_last_command"] = ""
            state["craft_loop_ack_due_at"] = 0
            state["craft_loop_finished_at"] = now
            save_profile_record(storage, profile_id, state=state)
            append_audit_event(
                storage,
                profile_id=profile_id,
                chat_id=chat_id,
                thread_id=thread_id,
                family="tianxing_craft_loop",
                event_type="craft_loop_predict_panel_rejected",
                route="炼制",
                phase="error",
                command_text=normalized_command,
                detail={"current_prediction": parsed.get("current_prediction"), "at": now},
            )
            return _craft_loop_result(state, queued=False, stage="error")
        state["craft_loop_phase"] = "await_craft"
        state["craft_loop_last_error"] = ""
        state["craft_loop_last_command"] = ""
        state["craft_loop_ack_due_at"] = 0
        save_profile_record(storage, profile_id, state=state)
        append_audit_event(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            family="tianxing_craft_loop",
            event_type="craft_loop_predict_confirmed_by_panel",
            route="炼制",
            phase="await_craft",
            command_text=normalized_command,
            detail={"remaining": int(state.get("craft_loop_remaining") or 0), "at": now},
        )
        return _craft_loop_result(state, queued=False, stage="await_craft")

    expected_craft = _craft_loop_craft_command(state)
    if phase == "await_craft" and normalized_command == expected_craft:
        _confirm_latest_craft_loop_command(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            command_text=normalized_command,
        )
        if parsed.get("action") != "炼制" or parsed.get("result") != "prediction_hit":
            state["craft_loop_enabled"] = False
            state["craft_loop_phase"] = "error"
            state["craft_loop_last_error"] = "炼制未命中推命，循环已停止。"
            state["craft_loop_last_command"] = ""
            state["craft_loop_ack_due_at"] = 0
            state["craft_loop_finished_at"] = now
            save_profile_record(storage, profile_id, state=state)
            append_audit_event(
                storage,
                profile_id=profile_id,
                chat_id=chat_id,
                thread_id=thread_id,
                family="tianxing_craft_loop",
                event_type="craft_loop_craft_rejected",
                route="炼制",
                phase="error",
                command_text=normalized_command,
                detail={"parsed_result": parsed.get("result"), "at": now},
            )
            return _craft_loop_result(state, queued=False, stage="error")
        remaining = max(0, int(state.get("craft_loop_remaining") or 0) - 1)
        state["craft_loop_remaining"] = remaining
        state["craft_loop_completed"] = int(state.get("craft_loop_completed") or 0) + 1
        state["craft_loop_last_error"] = ""
        state["craft_loop_last_command"] = ""
        state["craft_loop_ack_due_at"] = 0
        if remaining <= 0:
            state["craft_loop_enabled"] = False
            state["craft_loop_phase"] = "done"
            state["craft_loop_finished_at"] = now
            stage = "done"
        else:
            state["craft_loop_phase"] = "idle"
            stage = "idle"
        save_profile_record(storage, profile_id, state=state)
        append_audit_event(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            family="tianxing_craft_loop",
            event_type="craft_loop_craft_confirmed",
            route="炼制",
            phase=str(state.get("craft_loop_phase") or ""),
            command_text=normalized_command,
            detail={
                "remaining": remaining,
                "completed": int(state.get("craft_loop_completed") or 0),
                "at": now,
            },
        )
        return _craft_loop_result(state, queued=False, stage=stage)

    return None


def _craft_command(config: dict[str, Any]) -> str:
    item = str(config.get("craft_farm_item") or "玄铁剑").strip() or "玄铁剑"
    quantity = max(1, int(config.get("craft_farm_quantity") or 1))
    return f".炼制 {item}*{quantity}"


def _schedule_craft_calibration_if_needed(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    command_text: str,
    parsed: dict[str, Any],
    now: float,
) -> None:
    if not is_tianxing_profile(storage, profile_id):
        return
    if family_for_command(command_text) != "tianxing_craft_farm":
        return
    if parsed.get("action") != "炼制":
        return
    if parsed.get("result") in {"prediction_hit", "prediction_miss", "change_triggered"}:
        return
    if parsed.get("last_tianji_gain") is not None or parsed.get("last_contrib_gain") is not None:
        return
    latest = storage.get_latest_outgoing_command(
        chat_id,
        profile_id=profile_id,
        text=".天机盘",
        thread_id=thread_id,
    )
    if _is_outgoing_command_blocking(latest, now=now):
        return
    storage.enqueue_outgoing_command(
        profile_id=profile_id,
        chat_id=chat_id,
        text=".天机盘",
        thread_id=thread_id,
    )
    append_audit_event(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        family="tianxing_craft_farm",
        event_type="craft_calibration_queued",
        route="炼制",
        command_text=".天机盘",
        detail={"reason": "craft settlement missing Tianxing prediction result", "at": now},
    )


def _schedule_retreat_calibration_if_needed(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    command_text: str,
    parsed: dict[str, Any],
    now: float,
) -> None:
    if not is_tianxing_profile(storage, profile_id):
        return
    if family_for_command(command_text) != "tianxing_retreat_farm":
        return
    if parsed.get("action") != "闭关":
        return
    if parsed.get("result") in {"prediction_hit", "prediction_miss", "change_triggered"}:
        return
    if parsed.get("last_tianji_gain") is not None or parsed.get("last_contrib_gain") is not None:
        return
    latest = storage.get_latest_outgoing_command(
        chat_id,
        profile_id=profile_id,
        text=".天机盘",
        thread_id=thread_id,
    )
    if _is_outgoing_command_blocking(latest, now=now):
        return
    storage.enqueue_outgoing_command(
        profile_id=profile_id,
        chat_id=chat_id,
        text=".天机盘",
        thread_id=thread_id,
    )
    append_audit_event(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        family="tianxing_retreat_farm",
        event_type="retreat_calibration_queued",
        route="闭关",
        command_text=".天机盘",
        detail={"reason": "retreat settlement missing Tianxing prediction result", "at": now},
    )


def _is_exploration_downstream_command(command_text: str) -> bool:
    command = str(command_text or "").strip()
    return command.startswith(".野外历练") or command.startswith(".探寻裂缝")


def _is_exploration_settlement_repair_signal(command_text: str, parsed: dict[str, Any]) -> bool:
    if not _is_exploration_downstream_command(command_text):
        return False
    if parsed.get("result") in {"prediction_hit", "prediction_miss", "change_triggered"}:
        return True
    return bool(parsed.get("change_pending_until"))


def _schedule_exploration_panel_calibration_if_needed(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    command_text: str,
    parsed: dict[str, Any],
    now: float,
) -> None:
    if not is_tianxing_profile(storage, profile_id):
        return
    if not _is_exploration_settlement_repair_signal(command_text, parsed):
        return
    record = get_profile_record(storage, profile_id)
    config = normalize_config(record.get("config"))
    if (
        not config.get("timeline_enabled")
        or config.get("timeline_dry_run_enabled")
        or not config.get("auto_panel_enabled")
    ):
        return
    if _has_active_tianxing_outgoing(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        now=now,
    ):
        append_audit_event(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            family="tianxing_exploration_repair",
            event_type="panel_calibration_blocked",
            route="探索",
            command_text=".天机盘",
            detail={"reason": "active Tianxing outgoing command", "at": now},
        )
        return
    binding = storage.resolve_chat_binding_for_event(profile_id, chat_id, thread_id, None)
    command_id = _enqueue_if_not_blocking(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        command=".天机盘",
        thread_id=thread_id,
        chat_type=getattr(binding, "chat_type", "group") if binding else "group",
        bot_username=(getattr(binding, "bot_username", "") if binding else "")
        or TIANXING_BOT_USERNAME,
        now=now,
    )
    if not command_id:
        return
    timeline = normalize_timeline(record.get("timeline"))
    timeline = {
        **timeline,
        "phase": "calibrating",
        "route": "探索",
        "steps": [_timeline_step("panel", "探索")],
        "active_step_index": 0,
        "active_step": {
            **_timeline_step("panel", "探索"),
            "status": "sent_waiting_ack",
            "sent_at": now,
            "ack_due_at": now + config["ack_timeout_sec"],
            "source": "exploration_settlement_repair",
        },
        "last_error": "",
        "updated_at": now,
    }
    save_profile_record(storage, profile_id, timeline=timeline)
    append_audit_event(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        family="tianxing_exploration_repair",
        event_type="panel_calibration_queued",
        route="探索",
        command_text=".天机盘",
        detail={"reason": "exploration settlement consumed or touched Tianxing state", "command_id": command_id},
    )


def _maybe_advance_exploration_after_panel_calibration(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    timeline_before: dict[str, Any],
    command_text: str,
    parsed: dict[str, Any],
    now: float,
) -> Optional[dict[str, Any]]:
    if str(command_text or "").strip() != ".天机盘":
        return None
    if parsed.get("action") != "天机盘" or parsed.get("result") != "panel":
        return None
    if (
        timeline_before.get("phase") != "calibrating"
        or str(timeline_before.get("route") or "") != "探索"
    ):
        return None
    active = dict(timeline_before.get("active_step") or {})
    if str(active.get("source") or "") != "exploration_settlement_repair":
        return None
    record = get_profile_record(storage, profile_id)
    config = normalize_config(record.get("config"))
    if not config.get("timeline_enabled") or config.get("timeline_dry_run_enabled"):
        return None
    binding = storage.resolve_chat_binding_for_event(profile_id, chat_id, thread_id, None)
    return start_or_advance_timeline(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        route="探索",
        thread_id=thread_id,
        chat_type=getattr(binding, "chat_type", "group") if binding else "group",
        bot_username=(getattr(binding, "bot_username", "") if binding else "")
        or TIANXING_BOT_USERNAME,
        now=now,
    )
