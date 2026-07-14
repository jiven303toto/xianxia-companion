from __future__ import annotations

import json
import re
from pathlib import Path


BOT_SCAN_SNAPSHOT_NAME = "telegram_game_bot_scan.json"
TIANZUN_BOT_PATTERN = re.compile(r"^hantianzun(\d+)_bot$", re.IGNORECASE)


def build_command_target_context(
    settings,
    active_profile,
    *,
    get_primary_command_chat,
    bot_username: str,
) -> dict:
    command_chat = None
    if active_profile:
        command_chat = get_primary_command_chat(active_profile.id, bot_username)
    return {
        "bound_chat_id": command_chat.chat_id
        if command_chat
        else settings.bound_chat_id,
        "bound_thread_id": command_chat.thread_id
        if command_chat
        else settings.bound_thread_id,
        "bound_chat_type": command_chat.chat_type
        if command_chat
        else settings.bound_chat_type,
        "bound_bot_username": command_chat.bot_username
        if command_chat and command_chat.bot_username
        else "",
        "bound_bot_id": command_chat.bot_id
        if command_chat and command_chat.bot_id is not None
        else settings.bound_bot_id,
        "command_chat_ready": bool(command_chat or settings.bound_chat_id),
    }


def build_sect_command_target_context(
    settings,
    active_profile,
    *,
    get_primary_command_chat,
    default_bot_username: str,
    sect_bot_username: str,
    sect_chat=None,
) -> dict:
    fallback_context = build_command_target_context(
        settings,
        active_profile,
        get_primary_command_chat=get_primary_command_chat,
        bot_username=default_bot_username,
    )
    if not sect_chat and active_profile:
        sect_chat = get_primary_command_chat(active_profile.id, sect_bot_username)
    return {
        "sect_bound_chat_id": sect_chat.chat_id
        if sect_chat
        else fallback_context["bound_chat_id"],
        "sect_bound_thread_id": sect_chat.thread_id
        if sect_chat
        else fallback_context["bound_thread_id"],
        "sect_bound_chat_type": sect_chat.chat_type
        if sect_chat
        else fallback_context["bound_chat_type"],
        "sect_bound_bot_username": (
            sect_chat.bot_username
            if sect_chat and sect_chat.bot_username
            else sect_bot_username
        ),
        "sect_command_chat_ready": bool(
            (sect_chat and sect_chat.chat_id) or fallback_context["bound_chat_id"]
        ),
    }


def normalize_chat_binding_bot_ids(binding) -> list[int]:
    if not binding:
        return []
    bot_ids = list(getattr(binding, "bot_ids", None) or [])
    primary_bot_id = getattr(binding, "bot_id", None)
    try:
        normalized_primary = int(primary_bot_id) if primary_bot_id is not None else None
    except (TypeError, ValueError):
        normalized_primary = None
    if (
        not bot_ids
        and normalized_primary is not None
        and normalized_primary not in bot_ids
    ):
        bot_ids = [normalized_primary, *bot_ids]
    deduped = []
    for bot_id in bot_ids:
        try:
            normalized = int(bot_id)
        except (TypeError, ValueError):
            continue
        if normalized not in deduped:
            deduped.append(normalized)
    return deduped


def load_chat_binding_bot_scan(storage, binding) -> dict:
    empty = {"available": False, "bot_ids": set(), "scanned_at": ""}
    if not binding:
        return empty
    path = Path(storage.path).with_name(BOT_SCAN_SNAPSHOT_NAME)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        snapshot_chat_id = int(payload.get("chat_id"))
        snapshot_thread_id = payload.get("thread_id")
        if snapshot_thread_id is not None:
            snapshot_thread_id = int(snapshot_thread_id)
        binding_thread_id = getattr(binding, "thread_id", None)
        if binding_thread_id is not None:
            binding_thread_id = int(binding_thread_id)
        if (
            snapshot_chat_id != int(binding.chat_id)
            or snapshot_thread_id != binding_thread_id
        ):
            return empty
        return {
            "available": True,
            "bot_ids": {
                int(value) for value in payload.get("bot_ids", []) if int(value) > 0
            },
            "scanned_at": str(payload.get("scanned_at") or ""),
        }
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return empty


def build_chat_binding_bot_ids_view(
    storage, binding, *, active_bot_ids: set[int] | None = None
) -> list[dict]:
    if not binding:
        return []
    bot_ids = list(getattr(binding, "bot_ids", None) or [])
    primary_bot_id = getattr(binding, "bot_id", None)
    try:
        normalized_primary = int(primary_bot_id) if primary_bot_id is not None else None
    except (TypeError, ValueError):
        normalized_primary = None
    if (
        not bot_ids
        and normalized_primary is not None
        and normalized_primary not in bot_ids
    ):
        bot_ids = [normalized_primary, *bot_ids]
    username_map = storage.get_chat_binding_bot_usernames(
        binding.profile_id,
        binding.chat_id,
        thread_id=binding.thread_id,
    )
    rows = []
    for bot_id in bot_ids:
        normalized_bot_id = int(bot_id)
        username = str(username_map.get(normalized_bot_id) or "").strip().lstrip("@")
        normalized_username = username.lower()
        number_match = TIANZUN_BOT_PATTERN.fullmatch(normalized_username)
        is_main_bot = normalized_username == "fanrenxiuxian_bot"
        is_primary = normalized_bot_id == normalized_primary or is_main_bot
        is_live = active_bot_ids is not None and normalized_bot_id in active_bot_ids
        rows.append(
            {
                "value": normalized_bot_id,
                "label": str(bot_id),
                "username": username,
                "username_label": f"@{username}" if username else "未知",
                "is_primary": is_primary,
                "is_main_bot": is_main_bot,
                "is_live": is_live,
                "status_label": (
                    "主 Bot"
                    if is_primary
                    else "群上存活"
                    if is_live
                    else "历史保留"
                    if active_bot_ids is not None
                    else "待扫描"
                ),
                "sort_number": int(number_match.group(1)) if number_match else -1,
            }
        )
    rows.sort(
        key=lambda row: (
            0 if row["is_main_bot"] else 1 if row["is_live"] else 2,
            -int(row["sort_number"]),
            str(row["username"] or "").lower(),
            -int(row["value"]),
        )
    )
    return rows


def ensure_chat_binding_bot_ids(storage, profile_id: int, chat_id: int, thread_id=None) -> None:
    binding = storage.get_chat_binding(profile_id, chat_id, thread_id=thread_id)
    if not binding:
        return
    current = normalize_chat_binding_bot_ids(binding)
    if current:
        return
    default_ids = storage.get_chat_binding_bot_ids(
        profile_id, chat_id, thread_id=thread_id
    )
    storage.set_chat_binding_bot_ids(
        profile_id, chat_id, default_ids, thread_id=thread_id
    )


def build_shared_template_context(
    storage,
    settings,
    active_profile,
    *,
    build_command_target_context,
    build_sect_treasury_items,
    build_chat_binding_bot_ids_view,
    ensure_chat_binding_bot_ids,
    is_admin_profile,
    get_authorized_user_id_text,
    is_fishing_module_available,
    is_artifact_module_available,
    is_yuanying_stage,
    is_small_world_module_available,
    has_joined_sect,
    asc_provider: str,
) -> dict:
    external_account = (
        storage.get_external_account(active_profile.id, asc_provider)
        if active_profile
        else None
    )
    chats = storage.list_chat_bindings(active_profile.id) if active_profile else []
    for chat in chats:
        ensure_chat_binding_bot_ids(active_profile.id, chat.chat_id, chat.thread_id)
    if active_profile:
        chats = storage.list_chat_bindings(active_profile.id)
    current_binding = None
    current_binding_bot_rows = []
    if active_profile:
        current_binding = storage.get_chat_binding(
            active_profile.id,
            settings.bound_chat_id,
            thread_id=settings.bound_thread_id,
        ) or storage.get_primary_chat_binding(active_profile.id)
        bot_scan = load_chat_binding_bot_scan(storage, current_binding)
        current_binding_bot_rows = build_chat_binding_bot_ids_view(
            current_binding,
            active_bot_ids=bot_scan["bot_ids"] if bot_scan["available"] else None,
        )
    else:
        bot_scan = {"available": False, "bot_ids": set(), "scanned_at": ""}
    bot_total = len(current_binding_bot_rows)
    return {
        **build_command_target_context(active_profile),
        "current_sect_name": active_profile.sect_name if active_profile else "",
        "sect_treasury_items": build_sect_treasury_items(active_profile),
        "external_account": external_account,
        "is_admin_profile": is_admin_profile(active_profile),
        "authorized_user_id": get_authorized_user_id_text(),
        "chats": chats,
        "current_chat_binding_bot_rows": current_binding_bot_rows,
        "current_chat_binding_bot_total": bot_total,
        "current_chat_binding_bot_scan_available": bot_scan["available"],
        "current_chat_binding_bot_scanned_at": bot_scan["scanned_at"],
        "current_chat_binding": current_binding,
        "fishing_module_available": is_fishing_module_available(active_profile),
        "artifact_module_available": is_artifact_module_available(active_profile),
        "yuanying_stage_available": is_yuanying_stage(active_profile),
        "small_world_module_available": is_small_world_module_available(active_profile),
        "sect_module_available": has_joined_sect(active_profile),
    }
