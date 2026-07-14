from typing import Optional
import biz_fanren_game

from .biz_tianji_trial_miniapp import TIANJI_REMNANT_COMMAND, TIANJI_TRIAL_COMMAND
from .biz_tianji_trial_remnant_view import (
    apply_tianji_trial_entry_state,
    build_tianji_exchange_items,
    parse_tianji_remnant_exchange_items,
    parse_tianji_remnant_panel_text,
    tianji_remnant_day_key,
    tianji_remnant_summary,
)
from .biz_tianji_trial_view_state import build_tianji_trial_view

TIANJI_REMNANT_COMMAND_TEXT = TIANJI_REMNANT_COMMAND
TIANJI_TRIAL_COMMAND_TEXT = TIANJI_TRIAL_COMMAND
TIANJI_EXCHANGE_COMMAND_TEXT = ".天机兑换"
TIANJI_REMNANT_COMMANDS = [
    {"label": "天机残痕", "command": TIANJI_REMNANT_COMMAND_TEXT},
    {"label": "天机试炼", "command": TIANJI_TRIAL_COMMAND_TEXT},
    {"label": "兑换清单", "command": TIANJI_EXCHANGE_COMMAND_TEXT},
]
TIANJI_EXCHANGE_FALLBACK_ITEMS = [
]
TIANJI_EXCHANGE_REFRESH_HINT = "先发送兑换清单刷新今日可兑换物品。"
TIANJI_EXCHANGE_STALE_HINT = "兑换清单已过期，请重新发送兑换清单。"


def get_latest_tianji_remnant_reply(
    storage,
    profile,
    command_chat,
    command_text: str,
    *,
    sender_id: Optional[int],
    sender_username: str,
    predicate,
) -> Optional[dict]:
    reply = storage.get_latest_bot_reply_for_command(
        command_chat.chat_id,
        command_text,
        profile_id=profile.id,
        thread_id=command_chat.thread_id,
        sender_id=sender_id,
        sender_username=sender_username,
    )
    if reply and predicate(str(reply.get("text") or "")):
        return reply

    command_query = """
        SELECT * FROM bound_messages
        WHERE chat_id=? AND is_bot=0 AND text=?
    """
    command_params = [int(command_chat.chat_id), command_text]
    if command_chat.thread_id:
        command_query += " AND (thread_id=? OR reply_to_msg_id=?)"
        command_params.extend([int(command_chat.thread_id), int(command_chat.thread_id)])
    sender_clauses = ["profile_id=?"]
    sender_params = [int(profile.id)]
    if sender_id is not None:
        sender_clauses.append("sender_id=?")
        sender_params.append(int(sender_id))
    if sender_username:
        sender_clauses.append("LOWER(COALESCE(sender_username, ''))=?")
        sender_params.append(sender_username.strip().lower().lstrip("@"))
    command_query += f" AND ({' OR '.join(sender_clauses)})"
    command_params.extend(sender_params)
    command_query += " ORDER BY created_at DESC, id DESC LIMIT 10"

    with storage.connect() as conn:
        command_rows = conn.execute(command_query, command_params).fetchall()
        for command_row in command_rows:
            reply_query = """
                SELECT * FROM bound_messages
                WHERE chat_id=? AND is_bot=1
                  AND message_id>? AND created_at>=?
            """
            reply_params = [
                int(command_chat.chat_id),
                int(command_row["message_id"]),
                float(command_row["created_at"] or 0),
            ]
            if command_chat.thread_id:
                reply_query += " AND (thread_id=? OR reply_to_msg_id=?)"
                reply_params.extend(
                    [int(command_chat.thread_id), int(command_chat.thread_id)]
                )
            reply_query += " ORDER BY message_id ASC, created_at ASC, id ASC LIMIT 10"
            for reply_row in conn.execute(reply_query, reply_params).fetchall():
                reply_dict = dict(reply_row)
                if predicate(str(reply_dict.get("text") or "")):
                    return reply_dict
    return None


def build_tianji_remnant_state(
    storage=None,
    profile=None,
    command_chat=None,
    payload: Optional[dict] = None,
    *,
    get_latest_reply=get_latest_tianji_remnant_reply,
    format_timestamp=biz_fanren_game.format_timestamp,
) -> dict:
    state = parse_tianji_remnant_panel_text("")
    state.update(
        {
            "commands": TIANJI_REMNANT_COMMANDS,
            "exchange_items": list(TIANJI_EXCHANGE_FALLBACK_ITEMS),
            "exchange_quantity_options": [],
            "exchange_hint": TIANJI_EXCHANGE_REFRESH_HINT,
            "exchange_time": "",
            "can_exchange": False,
            "panel_time": "",
            "miniapp": build_tianji_trial_view(payload or {}),
        }
    )
    if not storage or not profile or not command_chat:
        (
            state["exchange_items"],
            state["exchange_quantity_options"],
            state["can_exchange"],
        ) = build_tianji_exchange_items(state["exchange_items"], state.get("balance"))
        return state

    command_sender_text = str(
        getattr(command_chat, "telegram_user_id", "")
        or getattr(profile, "telegram_user_id", "")
        or ""
    ).strip()
    command_sender_id = (
        int(command_sender_text) if command_sender_text.isdigit() else None
    )
    command_sender_username = getattr(profile, "telegram_username", "") or ""
    panel_reply = get_latest_reply(
        storage,
        profile,
        command_chat,
        TIANJI_REMNANT_COMMAND_TEXT,
        sender_id=command_sender_id,
        sender_username=command_sender_username,
        predicate=lambda text: text.startswith("【天机残痕】"),
    )
    if panel_reply:
        state.update(parse_tianji_remnant_panel_text(panel_reply.get("text") or ""))
        panel_ts = float(panel_reply.get("created_at") or panel_reply.get("updated_at") or 0)
        state["panel_time"] = format_timestamp(panel_ts) if panel_ts else ""
        state = apply_tianji_trial_entry_state(state, panel_ts=panel_ts)

    exchange_reply = get_latest_reply(
        storage,
        profile,
        command_chat,
        TIANJI_EXCHANGE_COMMAND_TEXT,
        sender_id=command_sender_id,
        sender_username=command_sender_username,
        predicate=lambda text: text.startswith("【天机兑换】") and "可兑换" in text,
    )
    exchange_items = parse_tianji_remnant_exchange_items(
        str((exchange_reply or {}).get("text") or "")
    )
    if exchange_items:
        exchange_ts = float(
            exchange_reply.get("created_at") or exchange_reply.get("updated_at") or 0
        )
        if exchange_ts and tianji_remnant_day_key(exchange_ts) != tianji_remnant_day_key():
            exchange_items = []
            state["exchange_hint"] = TIANJI_EXCHANGE_STALE_HINT
        else:
            if exchange_ts:
                state["exchange_time"] = format_timestamp(exchange_ts)
            if state.get("balance") in ("", "-"):
                exchange_state = parse_tianji_remnant_panel_text(
                    exchange_reply.get("text") or ""
                )
                if exchange_state.get("balance") not in ("", "-"):
                    state["balance"] = exchange_state["balance"]
                    state["summary"] = tianji_remnant_summary(state)
            state["exchange_hint"] = ""
    if exchange_items:
        state["exchange_items"] = exchange_items
    (
        state["exchange_items"],
        state["exchange_quantity_options"],
        state["can_exchange"],
    ) = build_tianji_exchange_items(state["exchange_items"], state.get("balance"))
    return state
