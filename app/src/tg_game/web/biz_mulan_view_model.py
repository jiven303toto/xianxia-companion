from datetime import datetime, timezone
from typing import Optional
import biz_fanren_game
from tg_game.features import biz_mulan_feature as mulan_feature
from tg_game.web.biz_web_display_formatting import SHANGHAI_TZ

def mulan_message_matches_thread(message: dict, thread_id: Optional[int]) -> bool:
    if not thread_id:
        return True
    target_thread_id = int(thread_id)
    return target_thread_id in {
        int(message.get("thread_id") or 0),
        int(message.get("reply_to_msg_id") or 0),
    }


def mulan_message_has_current_profile_parent(
    storage,
    *,
    message: dict,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    command_texts: set[str],
    parent_messages: Optional[dict[int, dict]] = None,
) -> bool:
    reply_to_msg_id = int((message or {}).get("reply_to_msg_id") or 0)
    if reply_to_msg_id <= 0:
        return False
    parent = (
        parent_messages.get(reply_to_msg_id)
        if parent_messages is not None
        else storage.get_bound_message(chat_id, reply_to_msg_id, profile_id)
    )
    if not parent or int(parent.get("is_bot") or 0):
        return False
    if str(parent.get("direction") or "").strip() != "outgoing":
        return False
    if thread_id and int(parent.get("thread_id") or 0) not in {int(thread_id)}:
        return False
    return str(parent.get("text") or "").strip() in command_texts


def find_latest_mulan_message(
    storage,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    search_queries: list[str],
    command_texts: set[str],
    predicate,
) -> Optional[dict]:
    for query in search_queries:
        messages = storage.list_bound_messages(
            profile_id=profile_id,
            chat_id=chat_id,
            search_query=query,
            limit=80,
        )
        parent_messages = storage.get_bound_messages_by_message_ids(
            chat_id,
            [
                int(message.get("reply_to_msg_id") or 0)
                for message in messages
                if int(message.get("is_bot") or 0)
                and mulan_message_matches_thread(message, thread_id)
            ],
            profile_id,
        )
        for message in messages:
            if not int(message.get("is_bot") or 0):
                continue
            if not mulan_message_matches_thread(message, thread_id):
                continue
            if not mulan_message_has_current_profile_parent(
                storage,
                message=message,
                profile_id=profile_id,
                chat_id=chat_id,
                thread_id=thread_id,
                command_texts=command_texts,
                parent_messages=parent_messages,
            ):
                continue
            text = str(message.get("text") or "").strip()
            if text and predicate(text):
                return message
    return None


def mulan_preview_lines(text: str, limit: int = 8) -> list[str]:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    return lines[: max(int(limit or 1), 1)]


def is_mulan_support_ack_text(text: str) -> bool:
    raw_text = str(text or "")
    return (
        raw_text.startswith("【慕兰烽烟】")
        and "领了【" in raw_text
        and "正赶往天南边境" in raw_text
    )


def build_mulan_state(
    storage=None,
    profile=None,
    command_chat=None,
    auto_support_task: Optional[dict] = None,
    *,
    format_timestamp=None,
) -> dict:
    formatter = format_timestamp or biz_fanren_game.format_timestamp
    state = mulan_feature.parse_mulan_panel_text("")
    state.update(
        {
            "commands": mulan_feature.MULAN_MANUAL_COMMANDS,
            "panel_command": mulan_feature.MULAN_PANEL_COMMAND,
            "support_commands": mulan_feature.MULAN_SUPPORT_COMMANDS,
            "merit_commands": mulan_feature.MULAN_MERIT_COMMANDS,
            "merit_exchange_items": list(mulan_feature.MULAN_MERIT_EXCHANGE_FALLBACK_ITEMS),
            "utility_commands": mulan_feature.MULAN_UTILITY_COMMANDS,
            "wanling_commands": mulan_feature.MULAN_WANLING_COMMANDS,
            "wanling_patrol_routes": mulan_feature.MULAN_WANLING_PATROL_ROUTES,
            "panel_time": "",
            "latest_result_lines": [],
            "latest_result_time": "",
        }
    )
    if not storage or not profile or not command_chat:
        recommendation = mulan_feature.build_mulan_recommendation(state)
        state["recommendation"] = recommendation
        state["support_disabled"] = bool(recommendation.get("blocked"))
        state["auto_support"] = mulan_feature.build_mulan_auto_support_view(
            auto_support_task, recommendation
        )
        return state

    panel_ts = 0.0
    panel_message = find_latest_mulan_message(
        storage,
        profile.id,
        command_chat.chat_id,
        command_chat.thread_id,
        ["慕兰烽烟", "边境军功"],
        {mulan_feature.MULAN_PANEL_COMMAND_TEXT},
        lambda text: text.startswith("【慕兰烽烟】") and "个人战绩" in text,
    )
    if panel_message:
        state.update(
            mulan_feature.parse_mulan_panel_text(
                str(panel_message.get("text") or "")
            )
        )
        panel_ts = float(
            panel_message.get("updated_at") or panel_message.get("created_at") or 0
        )
        state["panel_time"] = formatter(panel_ts) if panel_ts else ""

    result_message = find_latest_mulan_message(
        storage,
        profile.id,
        command_chat.chat_id,
        command_chat.thread_id,
        ["慕兰烽烟"],
        mulan_feature.MULAN_VALID_SUPPORT_COMMANDS,
        lambda text: (
            bool(mulan_feature.parse_mulan_support_result_text(text))
            or is_mulan_support_ack_text(text)
        ),
    )
    if result_message:
        result_text = str(result_message.get("text") or "")
        state["latest_result_lines"] = mulan_preview_lines(result_text)
        result_ts = float(
            result_message.get("updated_at") or result_message.get("created_at") or 0
        )
        state["latest_result_time"] = formatter(result_ts) if result_ts else ""
        support_result = mulan_feature.parse_mulan_support_result_text(result_text)
        if (support_result or is_mulan_support_ack_text(result_text)) and (
            not panel_ts or result_ts >= panel_ts
        ):
            state["status"] = "已支援"
            for key in ("status", "military_merit", "streak"):
                value = str(support_result.get(key) or "").strip()
                if value:
                    state[key] = value
            if support_result.get("matched_order_hit"):
                matched_orders = str(state.get("matched_orders") or "").strip()
                if matched_orders in {"", "-", "0", "0 次"}:
                    state["matched_orders"] = "1 次"
            if result_ts:
                state["latest_support"] = (
                    datetime.fromtimestamp(result_ts, tz=timezone.utc)
                    .astimezone(SHANGHAI_TZ)
                    .strftime("%Y-%m-%d")
                )
            mulan_feature.refresh_mulan_summary(state)

    command_sender_text = str(
        getattr(command_chat, "telegram_user_id", "")
        or getattr(profile, "telegram_user_id", "")
        or ""
    ).strip()
    rank_reply = storage.get_latest_bot_reply_for_command(
        command_chat.chat_id,
        mulan_feature.MULAN_RANK_COMMAND_TEXT,
        profile_id=profile.id,
        thread_id=command_chat.thread_id,
        sender_id=(int(command_sender_text) if command_sender_text.isdigit() else None),
        sender_username=(getattr(profile, "telegram_username", "") or ""),
    )
    rank_items = mulan_feature.parse_mulan_merit_exchange_items(
        str((rank_reply or {}).get("text") or "")
    )
    if rank_items:
        state["merit_exchange_items"] = rank_items

    recommendation = mulan_feature.build_mulan_recommendation(state)
    state["recommendation"] = recommendation
    state["support_disabled"] = bool(recommendation.get("blocked"))
    state["auto_support"] = mulan_feature.build_mulan_auto_support_view(
        auto_support_task, recommendation
    )
    return state
