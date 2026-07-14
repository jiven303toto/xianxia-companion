from datetime import datetime, timezone
from typing import Optional
import biz_fanren_game
import biz_sect_game
from tg_game.features.xinggong import biz_xinggong_miniapp as xinggong_miniapp
from tg_game.features.xinggong.biz_xinggong_star_board import (
    build_star_options,
    coerce_dict_value,
    get_starboard_platform,
    iter_starboard_plot_states,
    normalize_starboard_target,
)
from tg_game.web.biz_web_display_formatting import (
    SHANGHAI_TZ,
    format_datetime_display_seconds,
    format_remaining_delta,
    parse_iso_datetime,
    resolve_payload_display_name,
)


def _now_ts(now_ts: Optional[float] = None) -> float:
    return float(now_ts if now_ts is not None else biz_fanren_game.time.time())


def _coerce_time_timestamp(value) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value or 0)
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except (TypeError, ValueError):
        pass
    parsed = parse_iso_datetime(text)
    if not parsed:
        return 0.0
    return parsed.astimezone(timezone.utc).timestamp()


def _friendly_title(key: str) -> str:
    mapping = {
        "last_star_formation_time": "上次星力加持",
        "star_name": "星辰名称",
        "effect": "加持效果",
        "status": "状态",
        "description": "加持说明",
        "expiry_time": "加持到期",
        "success_rate_buff": "闭关成功率",
        "yield_multiplier": "收益倍率",
    }
    key_text = str(key or "").strip()
    if key_text in mapping:
        return mapping[key_text]
    return "星力属性"


def _friendly_value(key: str, value):
    if value is None:
        return "-"
    if isinstance(value, (int, float)):
        if key and "time" in key:
            return format_datetime_display_seconds(value)
        return str(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "-"
        if key and "time" in key:
            return format_datetime_display_seconds(text)
        return text
    return str(value)


def _format_remaining_seconds(seconds: float) -> str:
    remaining = max(int(seconds or 0), 0)
    if remaining <= 0:
        return "已结束"
    hours, rem = divmod(remaining, 3600)
    minutes, sec = divmod(rem, 60)
    if hours > 0:
        return f"剩余{hours}时{minutes}分{sec}秒"
    if minutes > 0:
        return f"剩余{minutes}分{sec}秒"
    return f"剩余{sec}秒"


def _friendly_star_buff_value(key: str, value):
    if key == "success_rate_buff":
        try:
            numeric = float(value or 0)
        except (TypeError, ValueError):
            return _friendly_value(key, value)
        text = str(int(numeric)) if numeric.is_integer() else f"{numeric:g}"
        return f"+{text}%"
    if key == "yield_multiplier":
        try:
            numeric = float(value or 0)
        except (TypeError, ValueError):
            return _friendly_value(key, value)
        return f"{numeric:g}倍"
    return _friendly_value(key, value)


def build_xinggong_starboard_auto_view(
    raw_task: Optional[dict], *, now_ts: Optional[float] = None
) -> dict:
    task = raw_task or {}
    active = bool(task) and bool(task.get("enabled"))
    next_run_at = float(task.get("next_run_at") or 0)
    now = _now_ts(now_ts)
    return {
        "active": active,
        "enabled": active,
        "target_star": normalize_starboard_target(task.get("strategy")),
        "next_run_at": next_run_at,
        "next_run_target": next_run_at if active and next_run_at > now else 0,
        "next_run_display": (
            format_remaining_delta(datetime.fromtimestamp(next_run_at, tz=timezone.utc))
            if active and next_run_at > 0
            else "待命"
        ),
        "last_error": str(task.get("last_error") or "").strip(),
    }


def build_companion_gift_items(
    payload: dict, game_items_dict: Optional[dict] = None
) -> list[dict]:
    items = []
    if not isinstance(payload, dict):
        return items
    inventory = payload.get("inventory") or {}
    if not isinstance(inventory, dict):
        return items
    materials = inventory.get("materials") or {}
    bag_items = inventory.get("items") or []
    game_items = game_items_dict or {}
    if isinstance(materials, dict):
        for mat_key, qty in materials.items():
            name = resolve_payload_display_name(mat_key, game_items)
            items.append(
                {
                    "value": name,
                    "label": "{}（{}个）".format(name, qty),
                    "quantity": qty,
                }
            )
    if isinstance(bag_items, list):
        for item in bag_items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            qty = item.get("quantity") or 1
            items.append(
                {
                    "value": name,
                    "label": "{}（{}个）".format(name, qty),
                    "quantity": qty,
                }
            )
    return items


def build_xinggong_state(
    payload: dict,
    *,
    sect_position: str = "",
    sect_session=None,
    starboard_auto_task: Optional[dict] = None,
    starboard_pull_result: Optional[dict] = None,
    game_items_dict: Optional[dict] = None,
    now_ts: Optional[float] = None,
) -> dict:
    source_payload = payload if isinstance(payload, dict) else {}
    session = sect_session or {}
    now = _now_ts(now_ts)
    star_platform = get_starboard_platform(source_payload)
    star_formation = coerce_dict_value(source_payload.get("star_formation"))
    active_buffs = coerce_dict_value(source_payload.get("active_buffs"))
    active_star_formation = coerce_dict_value(active_buffs.get("star_formation"))

    active_star_formation_items = []
    star_formation_items = []
    for key in ("description", "success_rate_buff", "yield_multiplier", "expiry_time"):
        if key not in active_star_formation:
            continue
        value = active_star_formation.get(key)
        if isinstance(value, (dict, list)):
            continue
        active_star_formation_items.append(
            {
                "key": f"active_buffs.star_formation.{key}",
                "label": _friendly_title(key),
                "value": _friendly_star_buff_value(key, value),
            }
        )
    for key, value in star_formation.items():
        if key == "last_star_formation_time":
            continue
        if isinstance(value, (dict, list)):
            continue
        star_formation_items.append(
            {
                "key": key,
                "label": _friendly_title(key),
                "value": _friendly_value(key, value),
            }
        )

    nested_last_star_formation_time = star_formation.get("last_star_formation_time")
    active_star_formation_expiry_ts = _coerce_time_timestamp(
        active_star_formation.get("expiry_time")
    )
    root_last_star_formation_time = source_payload.get("last_star_formation_time")
    session_last_companion_assist_time_ts = _coerce_time_timestamp(
        session.get("last_companion_assist_time")
    )
    last_star_formation_time_ts = max(
        _coerce_time_timestamp(nested_last_star_formation_time),
        _coerce_time_timestamp(root_last_star_formation_time),
    )
    last_star_formation_time = (
        last_star_formation_time_ts if last_star_formation_time_ts > 0 else None
    )
    active_buff_remaining_seconds = (
        max(int(active_star_formation_expiry_ts - now), 0)
        if active_star_formation_expiry_ts > 0
        else 0
    )
    star_formation_view = {
        "available": bool(
            active_star_formation_items
            or star_formation_items
            or star_formation
            or active_star_formation
            or last_star_formation_time
        ),
        "raw": star_formation,
        "active_buff": active_star_formation,
        "active_entries": active_star_formation_items,
        "profile_entries": star_formation_items,
        "entries": [*active_star_formation_items, *star_formation_items],
        "last_star_formation_time": last_star_formation_time,
        "last_star_formation_time_display": format_datetime_display_seconds(
            last_star_formation_time
        ),
        "active_buff_expiry_time": active_star_formation_expiry_ts,
        "active_buff_expiry_display": format_datetime_display_seconds(
            active_star_formation_expiry_ts
        ),
        "active_buff_remaining_seconds": active_buff_remaining_seconds,
        "active_buff_remaining_display": _format_remaining_seconds(
            active_buff_remaining_seconds
        ),
        "active_buff_is_active": active_buff_remaining_seconds > 0,
    }

    plots = []
    for plot in iter_starboard_plot_states(source_payload, now=now):
        plot_id = str(plot.get("slot") or "").strip()
        if plot.get("empty_slot"):
            plots.append(
                {
                    "plot_id": plot_id,
                    "star_name": "",
                    "status": "空闲",
                    "raw_status": "",
                    "start_time_text": "",
                    "cooldown_remaining": 0,
                    "cooldown_total": 0,
                    "cooldown_pct": 0,
                    "is_ready": True,
                    "collectable": False,
                    "needs_comfort": False,
                }
            )
            continue
        star_name = str(plot.get("star_name") or "").strip()
        status = str(plot.get("status") or "").strip()
        start_ts = float(plot.get("start_ts") or 0)
        cooldown_remaining = int(plot.get("cooldown_remaining") or 0)
        cooldown_total = int(plot.get("cooldown_total") or 0)
        needs_comfort = bool(plot.get("needs_comfort"))
        collectable = bool(plot.get("collectable"))
        is_ready = bool(plot.get("is_ready"))
        display_status = status or "空闲"
        if collectable:
            display_status = "精华已成 · 待收集"
        plots.append(
            {
                "plot_id": plot_id,
                "star_name": star_name or "未牵引",
                "status": display_status,
                "raw_status": status,
                "start_time_text": (
                    datetime.fromtimestamp(start_ts, tz=timezone.utc)
                    .astimezone(SHANGHAI_TZ)
                    .strftime("%Y-%m-%d %H:%M")
                    if start_ts > 0
                    else ""
                ),
                "cooldown_remaining": cooldown_remaining,
                "cooldown_total": cooldown_total,
                "cooldown_pct": (
                    int(100 * (cooldown_total - cooldown_remaining) / cooldown_total)
                    if cooldown_total > 0
                    else 0
                ),
                "is_ready": is_ready,
                "collectable": collectable,
                "needs_comfort": needs_comfort,
            }
        )

    inventory = source_payload.get("inventory")
    star_options = build_star_options(sect_position, inventory)
    last_companion_greet_date = biz_sect_game._parse_date_key(
        source_payload.get("last_companion_greet_date")
    )
    greeted_today = bool(
        last_companion_greet_date
        and last_companion_greet_date == biz_sect_game.current_date_key(now)
    )
    assist_next_time = float(session.get("companion_assist_next_check_time") or 0)
    assist_pending_msg_id = int(session.get("companion_assist_pending_reply_msg_id") or 0)
    assist_pending_at = float(session.get("companion_assist_pending_at") or 0)
    if session_last_companion_assist_time_ts > 0:
        assist_cd_end = (
            session_last_companion_assist_time_ts
            + biz_sect_game.COMPANION_ASSIST_COOLDOWN_SECONDS
        )
    else:
        assist_cd_end = 0
    if assist_cd_end and assist_cd_end > now:
        assist_status = "冷却中"
    elif (
        assist_pending_msg_id
        and assist_pending_at
        and now <= assist_pending_at + biz_sect_game.COMPANION_ASSIST_REPLY_WINDOW_SECONDS
    ):
        assist_status = "待助阵"
    else:
        assist_status = "可助阵"
    assist_cd_remaining_seconds = max(int(assist_cd_end - now), 0) if assist_cd_end else 0
    companion = source_payload.get("companion") or {}
    if not isinstance(companion, dict):
        companion = {}

    return {
        "platform_size": int(star_platform.get("size") or 0),
        "plots": plots,
        "star_options": star_options,
        "starboard_auto_state": build_xinggong_starboard_auto_view(
            starboard_auto_task,
            now_ts=now,
        ),
        "starboard_auto_result": starboard_pull_result or {},
        "starboard_auto_history": xinggong_miniapp.build_xinggong_starboard_payload_history(
            source_payload,
            now_ts=now,
        ),
        "companion_name": str(companion.get("name") or "").strip() or "无",
        "companion_affection": int(companion.get("affection") or 0),
        "last_companion_greet_date": last_companion_greet_date,
        "companion_greeted_today": greeted_today,
        "companion_gift_items": build_companion_gift_items(
            source_payload,
            game_items_dict,
        ),
        "star_formation_view": star_formation_view,
        "auto_companion_assist_enabled": bool(
            session.get("auto_companion_assist_enabled")
        ),
        "companion_assist_next_check_time": assist_next_time,
        "companion_assist_next_check_display": (
            biz_fanren_game.format_timestamp(assist_next_time)
            if assist_next_time
            else "未设置"
        ),
        "companion_assist_status_display": assist_status,
        "companion_assist_pending_at": assist_pending_at,
        "companion_assist_pending_window_display": (
            f"{biz_fanren_game.format_timestamp(assist_pending_at)} 起 60 秒"
            if assist_pending_at
            else "-"
        ),
        "companion_assist_cooldown_display": (
            format_datetime_display_seconds(assist_cd_end) if assist_cd_end else "可助阵"
        ),
        "companion_assist_cooldown_remaining_seconds": assist_cd_remaining_seconds,
        "companion_assist_cooldown_remaining_display": (
            _format_remaining_seconds(assist_cd_remaining_seconds)
            if assist_cd_remaining_seconds
            else "可助阵"
        ),
        "companion_assist_cooldown_end_time": assist_cd_end,
        "last_star_formation_time": last_star_formation_time_ts,
        "last_star_formation_time_display": format_datetime_display_seconds(
            last_star_formation_time
        ),
    }
