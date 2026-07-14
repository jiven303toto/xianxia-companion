from datetime import datetime, timedelta, timezone
import re
from typing import Optional
from tg_game.web.biz_web_display_formatting import (
    build_payload_stat_items_with_defaults,
    coerce_json_dict,
    coerce_json_list,
)


def build_pagoda_view(payload: dict, *, today_text: str) -> dict:
    raw_progress = coerce_json_dict((payload or {}).get("pagoda_progress"))
    highest_floor = int(raw_progress.get("highest_floor") or 0)
    last_attempt_date = str(raw_progress.get("last_attempt_date") or "").strip()
    return {
        "highest_floor": highest_floor,
        "highest_floor_text": f"第 {highest_floor} 层" if highest_floor else "-",
        "is_in_pagoda": bool(raw_progress.get("is_in_pagoda")),
        "last_attempt_date": last_attempt_date,
        "attempted_today": bool(last_attempt_date[:10] == str(today_text or "")),
        "failed_floor": int((payload or {}).get("pagoda_failed_floor") or 0),
        "resets_today": int((payload or {}).get("pagoda_resets_today") or 0),
        "claimed_floors": coerce_json_list((payload or {}).get("pagoda_claimed_floors")),
    }


def build_pagoda_today_view(storage, profile_id: int, chat_id: Optional[int]) -> dict:
    empty = {
        "attempt_count": 0,
        "success_count": 0,
        "failed_count": 0,
        "no_reply_count": 0,
        "latest_time_display": "-",
        "latest_status": "今日暂无记录",
        "floor_text": "-",
        "reward_lines": [],
    }
    if (
        not storage
        or not hasattr(storage, "list_bound_messages")
        or not profile_id
        or not chat_id
    ):
        return empty

    now_local = datetime.now(timezone(timedelta(hours=8)))
    day_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    commands = [
        message
        for message in storage.list_bound_messages(
            profile_id=profile_id,
            chat_id=chat_id,
            search_query=".闯塔",
            limit=500,
        )
        if str(message.get("text") or "").strip() == ".闯塔"
        and str(message.get("direction") or "") == "outgoing"
        and float(message.get("created_at") or 0) >= day_start
    ]
    if not commands:
        return empty

    records = []
    for command in commands:
        reply = storage.get_latest_bot_reply_message(
            int(chat_id),
            int(command.get("message_id") or 0),
            int(profile_id),
        )
        reply_text = str((reply or {}).get("text") or "").strip()
        status = "无回包"
        if reply_text:
            status = "失败" if "今日已挑战失败" in reply_text else "成功"
        records.append((command, reply, reply_text, status))

    latest_success = next((record for record in records if record[3] == "成功"), None)
    command, reply, reply_text, status = latest_success or records[0]
    observed_at = float((reply or {}).get("created_at") or command.get("created_at") or 0)
    floor_match = re.search(r"本次共闯过\s*(\d+)\s*层", reply_text)
    reward_lines = []
    for line in reply_text.splitlines():
        normalized = line.strip().lstrip("- ").strip()
        if normalized.startswith(("修为 ", "宗门贡献", "获得了", "威望 ")):
            reward_lines.append(normalized)

    return {
        "attempt_count": len(records),
        "success_count": sum(record[3] == "成功" for record in records),
        "failed_count": sum(record[3] == "失败" for record in records),
        "no_reply_count": sum(record[3] == "无回包" for record in records),
        "latest_time_display": datetime.fromtimestamp(
            observed_at, tz=timezone.utc
        ).astimezone(timezone(timedelta(hours=8))).strftime("%H:%M:%S"),
        "latest_status": status,
        "floor_text": f"{floor_match.group(1)} 层" if floor_match else "-",
        "reward_lines": reward_lines,
    }


def build_dice_state(raw_value, default_summary_keys: Optional[list[str]] = None) -> dict:
    raw_stats = coerce_json_dict(raw_value)
    total_won = int(raw_stats.get("total_won") or 0)
    total_lost = int(raw_stats.get("total_lost") or 0)
    return {
        "raw": raw_stats,
        "total_plays": int(raw_stats.get("total_plays") or 0),
        "wins": int(raw_stats.get("wins") or 0),
        "losses": int(raw_stats.get("losses") or 0),
        "total_won": total_won,
        "total_lost": total_lost,
        "net_total": total_won - total_lost,
        "summary_items": build_payload_stat_items_with_defaults(
            raw_stats,
            default_keys=default_summary_keys,
        ),
    }


def build_ghost_gambling_view(
    payload: dict,
    *,
    parse_timestamp,
    format_timestamp,
) -> dict:
    data = payload or {}
    last_bet_time_text = str(data.get("last_bet_time") or "").strip()
    last_bet_time_ts = parse_timestamp(last_bet_time_text)
    return {
        "daily_loss_amount": int(data.get("daily_loss_amount") or 0),
        "last_bet_date": str(data.get("last_bet_date") or "").strip(),
        "last_bet_time": last_bet_time_text,
        "last_bet_time_ts": last_bet_time_ts,
        "last_bet_time_display": format_timestamp(last_bet_time_ts),
    }


def build_divination_view(
    payload: dict,
    *,
    parse_timestamp,
    format_day_from_timestamp,
    today_text: str,
) -> dict:
    data = payload or {}
    last_divination_text = str(data.get("last_divination_date") or "").strip()
    last_divination_ts = parse_timestamp(last_divination_text)
    last_divination_day = ""
    if last_divination_ts:
        last_divination_day = format_day_from_timestamp(last_divination_ts)
    elif last_divination_text:
        last_divination_day = last_divination_text[:10]
    raw_today_count = max(int(data.get("divination_count_today") or 0), 0)
    return {
        "last_divination_date": last_divination_text,
        "last_divination_ts": last_divination_ts,
        "last_divination_display": last_divination_day,
        "today_count": raw_today_count if last_divination_day == today_text else 0,
    }


def build_character_view(payload: dict) -> dict:
    data = payload or {}
    return {
        "shenshi_points": int(data.get("shenshi_points") or 0),
    }


def build_taiyi_view(payload: dict) -> dict:
    data = payload or {}
    return {
        "taiyi_shenshi_points": int(data.get("taiyi_shenshi_points") or 0),
    }


def build_divination_batch_view(raw_batch: Optional[dict]) -> dict:
    batch = raw_batch or {}
    initial_count = max(int(batch.get("initial_count") or 0), 0)
    target_count = max(int(batch.get("target_count") or 0), 0)
    sent_count = max(int(batch.get("sent_count") or 0), 0)
    completed_count = max(int(batch.get("completed_count") or 0), 0)
    planned_rounds = max(target_count - initial_count, 0)
    return {
        "raw": batch,
        "active": bool(batch) and str(batch.get("status") or "") == "active",
        "status": str(batch.get("status") or "").strip(),
        "initial_count": initial_count,
        "target_count": target_count,
        "sent_count": sent_count,
        "completed_count": completed_count,
        "planned_rounds": planned_rounds,
        "remaining_rounds": max(planned_rounds - completed_count, 0),
        "pending_command_msg_id": int(batch.get("pending_command_msg_id") or 0),
        "last_error": str(batch.get("last_error") or "").strip(),
        "created_at": float(batch.get("created_at") or 0),
    }


def build_other_play_view(
    payload: dict,
    *,
    today_text: str,
    parse_timestamp,
    format_timestamp,
    format_day_from_timestamp,
) -> dict:
    data = payload or {}
    gambling_stats = coerce_json_dict(data.get("gambling_stats"))
    divination = build_divination_view(
        data,
        parse_timestamp=parse_timestamp,
        format_day_from_timestamp=format_day_from_timestamp,
        today_text=today_text,
    )
    tianji_dice = coerce_json_dict(data.get("tianji_dice")) or coerce_json_dict(
        gambling_stats.get("tianji_dice")
    )
    linglong_dice = coerce_json_dict(data.get("linglong_dice")) or coerce_json_dict(
        gambling_stats.get("linglong_dice")
    )
    return {
        "pagoda": build_pagoda_view(data, today_text=today_text),
        "gambling_karma": float(data.get("gambling_karma") or 0),
        "divination": divination,
        "divination_count_today": divination["today_count"],
        "ghost_gambling": build_ghost_gambling_view(
            data,
            parse_timestamp=parse_timestamp,
            format_timestamp=format_timestamp,
        ),
        "tianji_dice": build_dice_state(
            tianji_dice,
            default_summary_keys=[
                "total_plays",
                "wins",
                "losses",
                "total_won",
                "total_lost",
            ],
        ),
        "linglong_dice": build_dice_state(
            linglong_dice,
            default_summary_keys=[
                "total_plays",
                "wins",
                "losses",
                "total_won",
            ],
        ),
    }
