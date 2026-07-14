import re
from typing import Callable, Optional

from tg_game.dungeon_defs import DUNGEON_DEFINITIONS


def get_dungeon_definition(dungeon_key: str) -> dict:
    normalized_key = str(dungeon_key or "").strip().lower()
    for entry in DUNGEON_DEFINITIONS:
        if entry["key"] == normalized_key:
            return entry
    return DUNGEON_DEFINITIONS[0]


def build_dungeon_message_rows(
    messages: list[dict],
    *,
    chat_id: int,
    format_timestamp: Callable[[object], str],
) -> list[dict]:
    rows = []
    for message in messages[:80]:
        text = str(message.get("text") or "").strip()
        is_bot = bool(message.get("is_bot"))
        sender_username = str(message.get("sender_username") or "").strip()
        sender_display = (
            "机器人"
            if is_bot
            else (f"@{sender_username.lstrip('@')}" if sender_username else "队伍消息")
        )
        rows.append(
            {
                **message,
                "message_id": int(message.get("message_id") or 0),
                "chat_id": int(message.get("chat_id") or chat_id),
                "text": text,
                "reply_preview": "",
                "sender_display": sender_display,
                "created_at_display": format_timestamp(message.get("created_at") or 0),
            }
        )
    return rows


def list_dungeon_feed_source_messages(
    storage,
    chat_id: int,
    dungeon_key: str,
    profile_id: Optional[int] = None,
) -> list[dict]:
    # Dungeon feed stays chat-wide so all profiles in the same group share it.
    messages = storage.list_bound_messages(
        profile_id=None,
        chat_id=chat_id,
        limit=300,
    )
    dungeon_def = get_dungeon_definition(dungeon_key)
    prefixes = dungeon_def.get("command_prefixes") or []
    prefixes = [
        str(prefix or "").strip() for prefix in prefixes if str(prefix or "").strip()
    ]
    reply_prefixes = dungeon_def.get("reply_prefixes") or []
    reply_prefixes = [
        str(p or "").strip() for p in reply_prefixes if str(p or "").strip()
    ]
    messages_by_id = {
        int(msg.get("message_id") or 0): msg
        for msg in messages
        if int(msg.get("message_id") or 0)
    }
    allowed_command_ids = {
        int(msg.get("message_id") or 0)
        for msg in messages
        if not bool(msg.get("is_bot"))
        and any(
            str(msg.get("text") or "").strip().startswith(prefix) for prefix in prefixes
        )
    }

    def _has_allowed_ancestor(msg: dict) -> bool:
        message_id = int(msg.get("message_id") or 0)
        if message_id in allowed_command_ids:
            return True
        if not bool(msg.get("is_bot")):
            return False
        bot_text = str(msg.get("text") or "").strip()
        if any(bot_text.startswith(p) for p in reply_prefixes):
            return True
        reply_to = int(msg.get("reply_to_msg_id") or 0)
        depth = 0
        while reply_to and depth < 8:
            parent = messages_by_id.get(reply_to) or storage.get_bound_message(
                chat_id, reply_to
            )
            if not parent:
                return False
            parent_id = int(parent.get("message_id") or 0)
            parent_text = str(parent.get("text") or "").strip()
            if parent_id in allowed_command_ids:
                return True
            if not bool(parent.get("is_bot")):
                return any(parent_text.startswith(prefix) for prefix in prefixes)
            reply_to = int(parent.get("reply_to_msg_id") or 0)
            depth += 1
        return False

    dungeon_messages = [msg for msg in messages if _has_allowed_ancestor(msg)]
    dungeon_messages.sort(
        key=lambda msg: float(msg.get("created_at") or 0), reverse=True
    )
    return dungeon_messages


def build_dungeon_messages(
    storage,
    chat_id: int,
    dungeon_key: str,
    profile_id: Optional[int] = None,
    *,
    format_timestamp: Callable[[object], str],
) -> list[dict]:
    filtered = list_dungeon_feed_source_messages(
        storage, chat_id, dungeon_key, profile_id=profile_id
    )
    return build_dungeon_message_rows(
        filtered,
        chat_id=chat_id,
        format_timestamp=format_timestamp,
    )


def extract_dungeon_command_buttons(dungeon_def: dict) -> list[str]:
    buttons = []
    seen = set()
    for line in dungeon_def.get("help_lines") or []:
        text = str(line or "").strip()
        match = re.search(r"`([^`]+)`", text)
        command_text = (match.group(1) if match else "").strip()
        if not command_text or command_text in seen:
            continue
        seen.add(command_text)
        buttons.append(command_text)
    return buttons


def extract_dungeon_cleanup_targets(dungeon_messages: list[dict]) -> list[dict]:
    team_keywords = ("队伍", "队长", "成员", "房间")
    usernames = []
    seen = set()
    for message in dungeon_messages:
        text = str(message.get("text") or "")
        reply_preview = str(message.get("reply_preview") or "")
        haystack = f"{text}\n{reply_preview}"
        if not any(keyword in haystack for keyword in team_keywords):
            continue
        for username in re.findall(r"@([A-Za-z0-9_]{3,})", haystack):
            normalized = username.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            usernames.append(username)
    for message in dungeon_messages:
        if bool(message.get("is_bot")):
            continue
        sender_username = str(message.get("sender_username") or "").strip().lstrip("@")
        normalized = sender_username.lower()
        if sender_username and normalized not in seen:
            seen.add(normalized)
            usernames.append(sender_username)
    return [
        {"value": username, "label": f"@{username}", "command": f".请离 @{username}"}
        for username in usernames[:12]
    ]
