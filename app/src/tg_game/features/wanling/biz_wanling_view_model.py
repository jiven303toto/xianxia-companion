import time
from typing import Optional
from tg_game.features.countdowns.biz_countdowns_view_model import (
    format_countdown_display,
    format_datetime_display_seconds,
    format_remaining_delta,
)
from tg_game.features.wanling.biz_wanling_roam import (
    WANLING_ROAM_DURATION_SECONDS,
    WANLING_ROAM_MAX_BEASTS,
    WANLING_ROAM_RETURN_BUFFER_SECONDS,
    list_spirit_beast_names,
    list_spirit_beasts,
    pack_wanling_roam_strategy,
    parse_wanling_roam_timestamp,
    unpack_wanling_roam_strategy,
)


def _now_ts(now_ts: Optional[float] = None) -> float:
    if now_ts is None:
        return time.time()
    return float(now_ts or 0)


def build_wanling_roam_auto_view(
    raw_task: Optional[dict],
    *,
    min_next_run_at: float = 0.0,
    now_ts: Optional[float] = None,
) -> dict:
    task = raw_task or {}
    active = bool(task) and bool(task.get("enabled"))
    next_run_at = float(task.get("next_run_at") or 0)
    if active and min_next_run_at > next_run_at:
        next_run_at = min_next_run_at
    now = _now_ts(now_ts)
    return {
        "active": active,
        "enabled": active,
        "next_run_at": next_run_at,
        "next_run_target": next_run_at if active and next_run_at > now else 0,
        "next_run_display": (
            format_remaining_delta(next_run_at, now_ts=now)
            if active and next_run_at > 0
            else "待命"
        ),
        "last_error": str(task.get("last_error") or "").strip(),
    }


def build_wanling_roam_state(
    payload: dict,
    *,
    now_ts: Optional[float] = None,
) -> dict:
    now = _now_ts(now_ts)
    entries = []
    for beast in list_spirit_beasts(payload or {}):
        finish_ts = parse_wanling_roam_timestamp(beast.get("mission_finish_time"))
        if finish_ts > 0:
            finish_ts += WANLING_ROAM_RETURN_BUFFER_SECONDS
        else:
            last_roam_ts = parse_wanling_roam_timestamp(beast.get("last_roam_time"))
            if last_roam_ts > 0:
                finish_ts = last_roam_ts + WANLING_ROAM_DURATION_SECONDS
        name = str(beast.get("name") or beast.get("id") or "灵兽").strip()
        status = str(beast.get("status") or "").strip()
        entries.append(
            {
                "name": name,
                "status": status,
                "finish_ts": finish_ts,
                "finish_display": format_datetime_display_seconds(finish_ts),
                "active": finish_ts > now,
            }
        )
    active_entries = [entry for entry in entries if entry["active"]]
    next_finish_ts = min(
        (entry["finish_ts"] for entry in active_entries if entry["finish_ts"] > 0),
        default=0.0,
    )
    return {
        "available": bool(entries),
        "beast_count": len(entries),
        "active_count": len(active_entries),
        "ready_count": max(len(entries) - len(active_entries), 0),
        "entries": sorted(
            entries,
            key=lambda entry: (
                0 if entry["active"] else 1,
                entry["finish_ts"] or 9999999999,
                entry["name"],
            ),
        ),
        "next_finish_ts": next_finish_ts,
        "next_finish_target": next_finish_ts if next_finish_ts > now else 0,
        "next_finish_display": format_countdown_display(
            next_finish_ts,
            ready_text="可放养",
            now_ts=now,
        ),
        "next_finish_time_display": format_datetime_display_seconds(next_finish_ts),
    }


def build_wanling_roam_config_view(payload: dict, raw_task: Optional[dict]) -> dict:
    available_names = list_spirit_beast_names(payload)
    available_set = set(available_names)
    selected_names = unpack_wanling_roam_strategy((raw_task or {}).get("strategy"))
    valid_selected_names = [name for name in selected_names if name in available_set]
    selected_set = set(valid_selected_names)
    extra_selected = [name for name in selected_names if name not in available_names]
    option_names = [*available_names, *extra_selected]
    return {
        "available_names": available_names,
        "selected_names": valid_selected_names,
        "selected_count": len(valid_selected_names),
        "max_beasts": WANLING_ROAM_MAX_BEASTS,
        "options": [
            {
                "name": name,
                "selected": name in selected_set,
                "missing": name not in available_names,
            }
            for name in option_names
        ],
        "strategy": pack_wanling_roam_strategy(valid_selected_names),
    }
