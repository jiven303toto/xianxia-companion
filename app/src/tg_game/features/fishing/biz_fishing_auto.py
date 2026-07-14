import time
from typing import Optional
import biz_fishing_game


FISHING_LIMIT_CONFIRM_STATES = {"limit_checking", "finished"}
FISHING_START_STATES = {"idle", "catch_success", "caught", "empty_hook", "basket"}


def _session_text(session: dict, key: str, default: str = "") -> str:
    return str(session.get(key) or default).strip() or default


def _session_int(session: dict, key: str, default: int = 0) -> int:
    try:
        value = session.get(key) if session.get(key) is not None else default
        return int(value)
    except (TypeError, ValueError):
        return default


def _session_float(session: dict, key: str, default: float = 0.0) -> float:
    try:
        value = session.get(key) if session.get(key) is not None else default
        return float(value)
    except (TypeError, ValueError):
        return default


def _build_start_command_from_session(session: dict) -> str:
    return biz_fishing_game.build_start_command(
        _session_text(session, "pond", biz_fishing_game.FISHING_DEFAULT_POND),
        _session_text(session, "bait", biz_fishing_game.FISHING_DEFAULT_BAIT),
    )


def _has_active_nest(session: dict) -> bool:
    if max(_session_int(session, "nest_remaining"), 0) > 0:
        return True
    current_nest = _session_text(session, "current_nest")
    return bool(biz_fishing_game.nest_name_from_text(current_nest))


def _nest_bait_shortage(session: dict, option: dict) -> str:
    baits = session.get("baits") if isinstance(session.get("baits"), dict) else {}
    missing = []
    for bait, required_count in (option.get("bait_requirements") or {}).items():
        available = int(baits.get(bait) or 0)
        required = int(required_count or 0)
        if available < required:
            missing.append(f"{bait}x{required}")
    return "、".join(missing)


def _build_auto_nest_command(session: dict) -> Optional[dict]:
    if not _session_int(session, "auto_nest"):
        return None
    if _has_active_nest(session):
        return None
    option = biz_fishing_game.get_fishing_nest_option(
        _session_text(session, "nest", biz_fishing_game.FISHING_DEFAULT_NEST)
    )
    nest_limit = _session_int(session, "nest_limit", int(option.get("daily_limit") or 0))
    if nest_limit <= 0:
        nest_limit = int(option.get("daily_limit") or 1)
    if _session_int(session, "nest_used_count") >= nest_limit:
        return None
    shortage = _nest_bait_shortage(session, option)
    if shortage:
        return {
            "command": _build_start_command_from_session(session),
            "reason": "start_without_nest_bait",
            "session_updates": {
                "auto_nest": False,
                "last_error": f"自动打窝已跳过：缺少{shortage}",
            },
        }
    return {"command": biz_fishing_game.build_nest_command(option["name"]), "reason": "nest"}


def build_next_auto_command(
    session: Optional[dict], now: Optional[float] = None
) -> Optional[dict]:
    if not session or not _session_int(session, "enabled"):
        return None
    current_time = time.time() if now is None else float(now)
    state = _session_text(session, "state", "idle")
    daily_count = max(_session_int(session, "daily_count"), 0)
    daily_limit = max(
        _session_int(session, "daily_limit", biz_fishing_game.FISHING_DAILY_LIMIT), 1
    )
    next_action_at = _session_float(session, "next_action_at")
    if next_action_at and next_action_at > current_time:
        return None

    if state == "needs_basket":
        return {"command": biz_fishing_game.FISHING_BASKET_COMMAND, "reason": "refresh_basket"}

    if daily_count >= daily_limit:
        if state in FISHING_LIMIT_CONFIRM_STATES:
            return {"command": biz_fishing_game.FISHING_BASKET_COMMAND, "reason": "confirm_limit"}
        return None

    if state == "waiting_bite":
        return {"command": biz_fishing_game.FISHING_STATUS_COMMAND, "reason": "check_bite"}
    if state == "probe_ready":
        if _session_int(session, "auto_probe", 1):
            return {"command": biz_fishing_game.FISHING_PROBE_COMMAND, "reason": "probe_bite"}
        return {"command": biz_fishing_game.FISHING_HOOK_COMMAND, "reason": "hook_without_probe"}
    if state == "hook_ready":
        return {"command": biz_fishing_game.FISHING_HOOK_COMMAND, "reason": "hook"}
    if state in FISHING_START_STATES:
        nest_command = _build_auto_nest_command(session)
        if nest_command:
            return nest_command
        return {
            "command": _build_start_command_from_session(session),
            "reason": "start",
        }
    return None
