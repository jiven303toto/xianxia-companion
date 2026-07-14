from typing import Optional
import biz_fanren_game
import biz_fishing_game
from tg_game.features.fishing import biz_fishing_daily_auto
from tg_game.features.fishing.biz_fishing_miniapp_entry import parse_miniapp_entry_block

FISHING_STATE_LABELS = {
    "idle": "待开钓",
    "needs_basket": "待刷新鱼篓",
    "basket": "鱼篓已刷新",
    "waiting_bite": "等待鱼讯",
    "probe_ready": "可试探咬饵",
    "hook_ready": "可提竿",
    "catch_success": "提竿成功",
    "empty_hook": "空竿",
    "miniapp_canary": "等待 MiniApp 试钓",
    "miniapp_batch": "等待 MiniApp 钓满今日",
    "miniapp_canary_running": "MiniApp 试钓中",
    "miniapp_batch_running": "MiniApp 钓满今日中",
    "miniapp": "MiniApp 接管中",
    "miniapp_failed": "MiniApp 失败",
    "limit_checking": "满杆复核中",
    "finished": "今日竿数已满",
    "stopped": "已停止",
}


def _int_value(value: object, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _float_value(value: object, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _session_text(session: dict, key: str, default: str = "") -> str:
    return str(session.get(key) or default).strip() or default


def _sorted_items(value: object) -> list[tuple]:
    return sorted(value.items(), key=lambda item: item[0]) if isinstance(value, dict) else []


def build_fishing_view(raw_session: Optional[dict], daily_task: Optional[dict] = None) -> dict:
    session = raw_session or {}
    task = daily_task or {}
    state = _session_text(session, "state", "idle")
    daily_count = max(_int_value(session.get("daily_count")), 0)
    daily_limit = max(
        _int_value(session.get("daily_limit"), biz_fishing_game.FISHING_DAILY_LIMIT), 1
    )
    next_action_at = _float_value(session.get("next_action_at"))
    nest = _session_text(session, "nest", biz_fishing_game.FISHING_DEFAULT_NEST)
    nest_option = biz_fishing_game.get_fishing_nest_option(nest)
    nest_limit = max(
        _int_value(session.get("nest_limit"), int(nest_option.get("daily_limit") or 1)),
        0,
    )
    pond = _session_text(session, "pond", biz_fishing_game.FISHING_DEFAULT_POND)
    bait = _session_text(session, "bait", biz_fishing_game.FISHING_DEFAULT_BAIT)
    auto_probe = bool(_int_value(session.get("auto_probe"), 1))
    big_fish_preset = biz_fishing_game.FISHING_BIG_FISH_PRESET
    fishing_strategy = (
        "big_fish"
        if (
            pond == big_fish_preset["pond"]
            and bait == big_fish_preset["bait"]
            and auto_probe == bool(big_fish_preset.get("auto_probe"))
        )
        else "custom"
    )

    last_result_text = _session_text(session, "last_result_text")
    canary_passed = (
        state in {"catch_success", "finished"}
        and "MiniApp" in last_result_text
        and not _session_text(session, "last_error")
    )
    daily_next_run_at = _float_value(task.get("next_run_at"))

    return {
        "raw": session,
        "active": bool(_int_value(session.get("enabled"))),
        "state": state,
        "state_label": FISHING_STATE_LABELS.get(state, state),
        "pond": pond,
        "bait": bait,
        "pond_options": biz_fishing_game.FISHING_POND_OPTIONS,
        "bait_options": biz_fishing_game.FISHING_BAIT_OPTIONS,
        "big_fish_preset": big_fish_preset,
        "fishing_strategy": fishing_strategy,
        "auto_probe": auto_probe,
        "auto_until_limit": bool(_int_value(session.get("auto_until_limit"), 1)),
        "auto_nest": bool(_int_value(session.get("auto_nest"))),
        "nest": nest,
        "nest_options": biz_fishing_game.FISHING_NEST_OPTIONS,
        "nest_limit": nest_limit,
        "nest_used_count": max(_int_value(session.get("nest_used_count")), 0),
        "nest_remaining": max(_int_value(session.get("nest_remaining")), 0),
        "daily_count": daily_count,
        "daily_limit": daily_limit,
        "daily_text": f"{daily_count}/{daily_limit}",
        "rod_text": _session_text(session, "rod_text", "-"),
        "skill_text": _session_text(session, "skill_text", "-"),
        "current_nest": _session_text(session, "current_nest", "无"),
        "baits": _sorted_items(session.get("baits")),
        "nest_baits": _sorted_items(session.get("nest_baits")),
        "catches": _sorted_items(session.get("catches")),
        "last_fish_name": _session_text(session, "last_fish_name", "-"),
        "last_result_text": last_result_text,
        "canary_passed": canary_passed,
        "daily_auto_enabled": bool(_int_value(task.get("enabled"))),
        "daily_run_time": biz_fishing_daily_auto.normalize_run_time(
            task.get("strategy") or biz_fishing_daily_auto.DEFAULT_RUN_TIME
        ),
        "daily_next_run_at": daily_next_run_at,
        "daily_next_run_display": (
            biz_fanren_game.format_timestamp(daily_next_run_at)
            if daily_next_run_at
            else "-"
        ),
        "daily_last_error": _session_text(task, "last_error"),
        "miniapp_entry": parse_miniapp_entry_block(last_result_text),
        "last_command_text": _session_text(session, "last_command_text"),
        "last_error": _session_text(session, "last_error"),
        "next_action_at": next_action_at,
        "next_action_display": (
            biz_fanren_game.format_timestamp(next_action_at) if next_action_at else "-"
        ),
        "command_preview": biz_fishing_game.build_start_command(pond, bait),
    }
