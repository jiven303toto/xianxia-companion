import biz_fishing_game


def _int_value(value: object, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _session_text(session: dict, key: str, default: str = "") -> str:
    return str(session.get(key) or default).strip() or default


def _session_int(session: dict, key: str, default: int = 0) -> int:
    return _int_value(session.get(key), default)


def _fishing_session_nest_name(session: dict) -> str:
    current_nest = biz_fishing_game.nest_name_from_text(
        _session_text(session, "current_nest")
    )
    if current_nest:
        return current_nest
    return _session_text(session, "nest", biz_fishing_game.FISHING_DEFAULT_NEST)


def build_session_updates_from_reply(
    session: dict,
    parsed: dict,
    *,
    parent_command: str,
    parent_message_id: int,
    bot_message_id: int,
    now: float,
) -> dict:
    event = str(parsed.get("event") or "")
    daily_count = max(_session_int(session, "daily_count"), 0)
    daily_limit = max(
        _session_int(session, "daily_limit", biz_fishing_game.FISHING_DAILY_LIMIT), 1
    )
    updates = {
        "last_command_text": parent_command,
        "last_command_msg_id": int(parent_message_id or 0),
        "last_bot_msg_id": int(bot_message_id or 0),
        "last_result_text": str(parsed.get("raw_text") or "")[:4000],
        "last_action_at": now,
        "last_error": "",
    }
    if event == "basket":
        daily_count = max(_int_value(parsed.get("daily_count")), 0)
        daily_limit = max(
            _int_value(parsed.get("daily_limit"), biz_fishing_game.FISHING_DAILY_LIMIT), 1
        )
        limit_reached = daily_count >= daily_limit
        updates.update(
            {
                "state": "finished" if limit_reached else "basket",
                "daily_count": daily_count,
                "daily_limit": daily_limit,
                "rod_text": str(parsed.get("rod") or ""),
                "skill_text": str(parsed.get("skill") or ""),
                "current_nest": str(parsed.get("current_nest") or "无"),
                "nest_remaining": max(_int_value(parsed.get("nest_remaining")), 0),
                "baits": parsed.get("baits") or {},
                "nest_baits": parsed.get("nest_baits") or {},
                "catches": parsed.get("catches") or {},
                "next_action_at": 0 if limit_reached else now,
            }
        )
        if limit_reached:
            updates["enabled"] = False
    elif event == "status":
        state = str(parsed.get("state") or "idle")
        delay_seconds = max(_int_value(parsed.get("delay_seconds")), 0)
        parsed_daily_count = parsed.get("daily_count")
        parsed_daily_limit = parsed.get("daily_limit")
        if parsed_daily_count is not None:
            daily_count = max(_int_value(parsed_daily_count), 0)
        if parsed_daily_limit is not None:
            daily_limit = max(
                _int_value(parsed_daily_limit, biz_fishing_game.FISHING_DAILY_LIMIT), 1
            )
        limit_reached = bool(parsed.get("limit_reached")) or (
            parsed_daily_count is not None and daily_count >= daily_limit
        )
        if limit_reached:
            updates.update(
                {
                    "enabled": False,
                    "state": "finished",
                    "daily_count": daily_count,
                    "daily_limit": daily_limit,
                    "pond": str(
                        parsed.get("pond")
                        or session.get("pond")
                        or biz_fishing_game.FISHING_DEFAULT_POND
                    ),
                    "next_action_at": 0,
                }
            )
            return updates
        updates.update(
            {
                "state": state,
                "pond": str(
                    parsed.get("pond")
                    or session.get("pond")
                    or biz_fishing_game.FISHING_DEFAULT_POND
                ),
                "next_action_at": now + delay_seconds + 1 if delay_seconds else now,
            }
        )
        if parsed_daily_count is not None:
            updates["daily_count"] = daily_count
        if parsed_daily_limit is not None:
            updates["daily_limit"] = daily_limit
    elif event in {"catch_success", "empty_hook"}:
        if parent_command in {
            biz_fishing_game.FISHING_HOOK_COMMAND,
            biz_fishing_game.FISHING_PROBE_COMMAND,
        }:
            daily_count = min(daily_count + 1, daily_limit)
        if (
            parent_command == biz_fishing_game.FISHING_STATUS_COMMAND
            and _session_text(session, "state") == "limit_checking"
            and daily_count >= daily_limit
        ):
            updates.update(
                {
                    "enabled": False,
                    "state": "finished",
                    "daily_count": daily_count,
                    "daily_limit": daily_limit,
                    "last_fish_name": str(
                        parsed.get("fish_name")
                        or session.get("last_fish_name")
                        or ""
                    ),
                    "skill_text": str(
                        parsed.get("skill") or session.get("skill_text") or ""
                    ),
                    "next_action_at": 0,
                }
            )
            return updates
        limit_reached = daily_count >= daily_limit
        updates.update(
            {
                "state": "limit_checking" if limit_reached else event,
                "daily_count": daily_count,
                "daily_limit": daily_limit,
                "last_fish_name": str(
                    parsed.get("fish_name") or session.get("last_fish_name") or ""
                ),
                "skill_text": str(parsed.get("skill") or session.get("skill_text") or ""),
                "next_action_at": (
                    now
                    if limit_reached
                    else now + biz_fishing_game.FISHING_RESULT_RECOVERY_SECONDS
                ),
            }
        )
        nest_remaining = max(_session_int(session, "nest_remaining"), 0)
        if nest_remaining:
            next_nest_remaining = max(nest_remaining - 1, 0)
            updates["nest_remaining"] = next_nest_remaining
            updates["current_nest"] = biz_fishing_game.format_current_nest(
                _fishing_session_nest_name(session),
                next_nest_remaining,
            )
    elif event == "nest_ready":
        nest = str(
            parsed.get("nest") or session.get("nest") or biz_fishing_game.FISHING_DEFAULT_NEST
        )
        nest_remaining = max(_int_value(parsed.get("nest_uses")), 0)
        updates.update(
            {
                "state": _session_text(session, "state", "idle"),
                "current_nest": biz_fishing_game.format_current_nest(
                    nest,
                    nest_remaining,
                ),
                "nest_remaining": nest_remaining,
                "nest_used_count": max(_session_int(session, "nest_used_count"), 0) + 1,
                "next_action_at": now,
            }
        )
    elif event == "nest_active":
        nest = str(
            parsed.get("nest") or session.get("nest") or biz_fishing_game.FISHING_DEFAULT_NEST
        )
        nest_remaining = max(_int_value(parsed.get("nest_remaining")), 0)
        updates.update(
            {
                "state": _session_text(session, "state", "idle"),
                "current_nest": biz_fishing_game.format_current_nest(
                    nest,
                    nest_remaining,
                ),
                "nest_remaining": nest_remaining,
                "next_action_at": now,
            }
        )
    elif event == "nest_failed":
        updates.update(
            {
                "enabled": bool(_session_int(session, "enabled")),
                "auto_nest": False,
                "state": _session_text(session, "state", "basket"),
                "last_error": f"打窝失败：{parsed.get('missing') or '资源不足'}",
                "next_action_at": now,
            }
        )
    elif event == "nest_daily_limit":
        nest_limit = max(_session_int(session, "nest_limit"), 0)
        if nest_limit <= 0:
            nest_limit = int(
                biz_fishing_game.get_fishing_nest_option(
                    _session_text(session, "nest", biz_fishing_game.FISHING_DEFAULT_NEST)
                ).get("daily_limit")
                or 1
            )
        updates.update(
            {
                "enabled": bool(_session_int(session, "enabled")),
                "auto_nest": False,
                "state": _session_text(session, "state", "basket"),
                "nest_used_count": nest_limit,
                "last_error": "自动打窝已停止：今日此类窝料已经用尽。",
                "next_action_at": now,
            }
        )
    elif event == "missing_bait":
        updates.update(
            {
                "enabled": False,
                "state": "stopped",
                "last_error": (
                    f"缺少鱼饵：{parsed.get('bait') or session.get('bait') or ''}"
                ),
                "next_action_at": 0,
            }
        )
    elif event == "missing_rod":
        updates.update(
            {
                "enabled": False,
                "state": "stopped",
                "last_error": "缺少钓竿，自动钓鱼已停止",
                "next_action_at": 0,
            }
        )
    elif event == "daily_limit":
        updates.update(
            {
                "enabled": False,
                "state": "finished",
                "daily_count": daily_limit,
                "daily_limit": daily_limit,
                "next_action_at": 0,
            }
        )
    return updates
