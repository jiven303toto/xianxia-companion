import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from tg_game.features.companion.biz_companion_voyage import (
    parse_chinese_duration_seconds,
)


SHANGHAI_TZ = timezone(timedelta(hours=8))


def coerce_json_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def coerce_json_dict(value) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def parse_optional_int(raw_value) -> Optional[int]:
    text = str(raw_value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def extract_reply_field(reply_text: str, label: str) -> str:
    if not reply_text:
        return ""
    pattern = rf"-\s*{re.escape(label)}:\s*([^\n]+)"
    match = re.search(pattern, reply_text)
    return match.group(1).strip() if match else ""


def parse_iso_datetime(raw_value) -> Optional[datetime]:
    text = str(raw_value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def format_datetime_display(raw_value) -> str:
    parsed = parse_iso_datetime(raw_value)
    if not parsed:
        return "-"
    return parsed.astimezone(SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M")


def format_datetime_display_seconds(raw_value) -> str:
    if raw_value is None:
        return "-"
    if isinstance(raw_value, (int, float)):
        if float(raw_value or 0) <= 0:
            return "-"
        return datetime.fromtimestamp(float(raw_value), tz=timezone.utc).astimezone(SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S")
    parsed = parse_iso_datetime(raw_value)
    if not parsed:
        return "-"
    return parsed.astimezone(SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M:%S")


def format_remaining_delta(end_time: Optional[datetime]) -> str:
    if not end_time:
        return "可施展"
    now = datetime.now(timezone.utc)
    remaining_seconds = int((end_time.astimezone(timezone.utc) - now).total_seconds())
    if remaining_seconds <= 0:
        return "可施展"
    total_minutes = math.ceil(remaining_seconds / 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours <= 0:
        return f"{minutes}分钟"
    if minutes == 0:
        return f"{hours}小时"
    return f"{hours}小时{minutes}分钟"


def format_cooldown_from_last(raw_value, cooldown_hours: int) -> str:
    parsed = parse_iso_datetime(raw_value)
    if not parsed:
        return "可施展"
    end_time = parsed + timedelta(hours=max(int(cooldown_hours or 0), 0))
    return format_remaining_delta(end_time)


def cooldown_target_timestamp(raw_value, cooldown_hours: int) -> float:
    parsed = parse_iso_datetime(raw_value)
    if not parsed:
        return 0.0
    end_time = parsed + timedelta(hours=max(int(cooldown_hours or 0), 0))
    return end_time.astimezone(timezone.utc).timestamp()


def stringify_payload_stat_value(value) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return value.strip() or "-"
    if isinstance(value, list):
        return (
            "、".join(str(item).strip() for item in value if str(item).strip()) or "-"
        )
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value or "").strip() or "-"


def payload_stat_label(key: str) -> str:
    normalized = str(key or "").strip()
    labels = {
        "total_plays": "总局数",
        "wins": "胜场",
        "losses": "负场",
        "draws": "平局",
        "total_won": "累计赢取",
        "total_lost": "累计亏损",
        "win_streak": "连胜",
        "loss_streak": "连败",
        "today_loss": "今日亏损",
        "today_lost": "今日亏损",
        "daily_loss": "今日亏损",
        "loss_today": "今日亏损",
        "today_profit": "今日盈利",
        "daily_profit": "今日盈利",
        "guard_limit": "道心守护上限",
        "daily_loss_limit": "道心守护上限",
        "loss_limit": "道心守护上限",
        "protection_limit": "道心守护上限",
        "guard_used": "道心守护已亏损",
        "loss_used": "道心守护已亏损",
        "selected_dice": "指定骰子",
        "豹子次数": "豹子次数",
    }
    if normalized in labels:
        return labels[normalized]
    return normalized.replace("_", " ").strip() or "-"


def build_payload_stat_items(raw_stats: dict) -> list[dict]:
    items = []
    for key, value in (raw_stats or {}).items():
        if value in (None, "", [], {}):
            continue
        items.append(
            {
                "key": str(key or "").strip(),
                "label": payload_stat_label(key),
                "value": stringify_payload_stat_value(value),
            }
        )
    return items


def build_payload_stat_items_with_defaults(
    raw_stats: dict, default_keys: Optional[list[str]] = None
) -> list[dict]:
    defaults = [
        str(key or "").strip() for key in (default_keys or []) if str(key or "").strip()
    ]
    if not defaults:
        return build_payload_stat_items(raw_stats)
    items = []
    seen = set()
    for key in defaults:
        seen.add(key)
        value = raw_stats.get(key)
        items.append(
            {
                "key": key,
                "label": payload_stat_label(key),
                "value": (
                    stringify_payload_stat_value(value)
                    if value not in (None, "", [], {})
                    else ""
                ),
            }
        )
    for item in build_payload_stat_items(raw_stats):
        if item["key"] in seen:
            continue
        items.append(item)
    return items


def payload_name_list(value) -> list[str]:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") or text.startswith("{"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if parsed is not None:
                return payload_name_list(parsed)
        return [text] if text else []
    if isinstance(value, dict):
        name = (
            value.get("name")
            or value.get("title")
            or value.get("item_name")
            or value.get("technique_name")
            or value.get("badge_name")
            or ""
        )
        text = str(name or "").strip()
        return [text] if text else []
    if isinstance(value, list):
        names = []
        for item in value:
            names.extend(payload_name_list(item))
        return names
    return []


def resolve_payload_display_name(raw_value, game_items_dict: dict) -> str:
    text = str(raw_value or "").strip()
    if not text:
        return ""
    meta = game_items_dict.get(text) or {}
    return str(meta.get("name") or text).strip()


def payload_named_entries(value, game_items_dict: dict) -> list[dict]:
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("[") or text.startswith("{"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if parsed is not None:
                return payload_named_entries(parsed, game_items_dict)
        display = resolve_payload_display_name(text, game_items_dict)
        return [{"id": text, "name": display}] if display else []
    if isinstance(value, dict):
        named_keys = {
            "name",
            "title",
            "item_name",
            "technique_name",
            "badge_name",
            "formation_name",
        }
        id_keys = {"item_id", "id", "badge_id", "technique_id", "formation_id"}
        if not any(value.get(key) for key in named_keys | id_keys):
            entries = []
            for raw_key, raw_item in value.items():
                nested_entries = payload_named_entries(raw_item, game_items_dict)
                if nested_entries:
                    entries.extend(nested_entries)
                    continue
                if isinstance(raw_item, (int, float)) and int(raw_item) <= 0:
                    continue
                if isinstance(raw_item, str) and not raw_item.strip():
                    continue
                key_text = str(raw_key or "").strip()
                if not key_text:
                    continue
                display_name = resolve_payload_display_name(key_text, game_items_dict)
                entries.append({"id": key_text, "name": display_name or key_text})
            return entries
        raw_id = str(
            value.get("item_id")
            or value.get("id")
            or value.get("badge_id")
            or value.get("technique_id")
            or value.get("formation_id")
            or ""
        ).strip()
        display_name = str(
            value.get("name")
            or value.get("title")
            or value.get("item_name")
            or value.get("technique_name")
            or value.get("badge_name")
            or value.get("formation_name")
            or resolve_payload_display_name(raw_id, game_items_dict)
            or ""
        ).strip()
        return [{"id": raw_id, "name": display_name}] if display_name else []
    if isinstance(value, list):
        entries = []
        for item in value:
            entries.extend(payload_named_entries(item, game_items_dict))
        return entries
    return []


def collect_display_names(value, game_items_dict: Optional[dict] = None) -> list[str]:
    names = []
    seen = set()
    for raw_name in payload_name_list(value):
        name = str(raw_name or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    for entry in payload_named_entries(value, game_items_dict or {}):
        name = str(entry.get("name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


FISHING_REQUIRED_ROD_NAME = "青竹钓竿"


def profile_has_fishing_rod(
    payload: dict, game_items_dict: Optional[dict] = None
) -> bool:
    inventory = coerce_json_dict((payload or {}).get("inventory"))
    return FISHING_REQUIRED_ROD_NAME in collect_display_names(
        inventory.get("items"), game_items_dict or {}
    )


SCENERY_CODE_NAME_MAP = {
    "scenery_001": "一柄青竹蜂云剑的剑影",
    "scenery_002": "嗜血妖蝠的头骨",
    "scenery_003": "天道金榜的拓印",
    "scenery_004": "风希的一缕残念",
    "scenery_005": "琉璃塔顶的刻痕",
    "scenery_006": "异界商人的信物",
    "scenery_007": "伏诛妖兽的精魄",
    "scenery_008": "虚天殿的残垣",
    "scenery_009": "通天仙门",
    "scenery_010": "坠魔谷封魔碑",
}


def resolve_scenery_display_name(
    raw_value, game_items_dict: Optional[dict] = None
) -> str:
    text = str(raw_value or "").strip()
    if not text:
        return ""
    normalized = text.lower()
    mapped = SCENERY_CODE_NAME_MAP.get(normalized)
    if mapped:
        return mapped
    return resolve_payload_display_name(text, game_items_dict or {})


def build_scenery_entries(value, game_items_dict: Optional[dict] = None) -> list[dict]:
    entries = []
    seen = set()
    for item in coerce_json_list(value):
        if isinstance(item, dict):
            raw_id = str(
                item.get("item_id")
                or item.get("id")
                or item.get("name")
                or item.get("item_name")
                or ""
            ).strip()
            name = str(item.get("name") or item.get("item_name") or "").strip()
            if raw_id and not name:
                name = resolve_scenery_display_name(raw_id, game_items_dict)
            elif name:
                name = resolve_scenery_display_name(name, game_items_dict)
            if name and name not in seen:
                seen.add(name)
                entries.append({"id": raw_id or name, "name": name})
            continue

        raw_id = str(item or "").strip()
        name = resolve_scenery_display_name(raw_id, game_items_dict)
        if name and name not in seen:
            seen.add(name)
            entries.append({"id": raw_id or name, "name": name})
    return entries


def payload_name_summary(value, game_items_dict: dict) -> str:
    names = []
    seen = set()
    for entry in payload_named_entries(value, game_items_dict):
        name = str(entry.get("name") or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return ", ".join(names) if names else "-"


def format_external_artifacts(character: dict) -> str:
    equipped_ids = coerce_json_list(character.get("equipped_treasure_id"))
    inventory = character.get("inventory") or {}
    items = inventory.get("items") or []
    treasure_by_id = {
        str(item.get("item_id") or ""): item for item in items if isinstance(item, dict)
    }
    lines = []
    for treasure_id in equipped_ids:
        item = treasure_by_id.get(str(treasure_id)) or {}
        name = (item.get("name") or str(treasure_id or "")).strip()
        durability = item.get("durability")
        max_durability = item.get("max_durability")
        if durability is not None and max_durability is not None:
            lines.append(f"- {name}: {durability}/{max_durability}")
        elif name:
            lines.append(f"- {name}")
    return "\n".join(lines)


def first_equipped_artifact_name(character: dict) -> str:
    equipped_ids = coerce_json_list(character.get("equipped_treasure_id"))
    inventory = character.get("inventory") or {}
    items = inventory.get("items") or []
    treasure_by_id = {
        str(item.get("item_id") or ""): item for item in items if isinstance(item, dict)
    }
    for treasure_id in equipped_ids:
        item = treasure_by_id.get(str(treasure_id)) or {}
        name = str(item.get("name") or "").strip()
        if name:
            return name
    return ""


def equipped_artifact_names_text(character: dict) -> str:
    equipped_ids = coerce_json_list(character.get("equipped_treasure_id"))
    inventory = character.get("inventory") or {}
    items = inventory.get("items") or []
    treasure_by_id = {
        str(item.get("item_id") or ""): item for item in items if isinstance(item, dict)
    }
    names = []
    for treasure_id in equipped_ids:
        item = treasure_by_id.get(str(treasure_id)) or {}
        name = str(item.get("name") or treasure_id or "").strip()
        if name:
            names.append(name)
    return "、".join(names)


def build_equipped_artifact_details(character: dict) -> str:
    details = format_external_artifacts(character).strip()
    return details or "未装备法宝"


def format_sect_position(character: dict) -> str:
    positions = []
    if int(character.get("is_sect_elder") or 0):
        positions.append("长老")
    if int(character.get("is_grand_elder") or 0):
        positions.append("太上长老")
    return " / ".join(positions)


def recipe_craft_name(recipe_name: str) -> str:
    text = str(recipe_name or "").strip()
    for suffix in ["丹方", "单方", "图纸", "配方"]:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)].strip()
    return text


def format_payload_display_text(raw_value, game_items_dict: dict) -> str:
    summary = payload_name_summary(raw_value, game_items_dict)
    return summary if summary and summary != "-" else ""


def format_market_effects(raw_value) -> str:
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return ""
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text
        return format_market_effects(parsed)
    if isinstance(raw_value, list):
        parts = [
            part for part in (format_market_effects(item) for item in raw_value) if part
        ]
        return "；".join(parts)
    if isinstance(raw_value, dict):
        parts = []
        for key, value in raw_value.items():
            key_text = str(key or "").strip()
            value_text = format_market_effects(value)
            if key_text and value_text:
                parts.append(f"{key_text}: {value_text}")
            elif key_text:
                parts.append(key_text)
            elif value_text:
                parts.append(value_text)
        return "；".join(parts)
    text = str(raw_value or "").strip()
    return text


def wild_deep_sender_label(row: dict) -> str:
    username = str(row.get("command_sender_username") or "").strip().lstrip("@")
    if username:
        return f"@{username}"
    sender_id = int(row.get("command_sender_id") or 0)
    return str(sender_id) if sender_id else "未知用户"


def wild_deep_result_label(text: str) -> str:
    raw = str(text or "")
    if not raw.strip():
        return "未回包"
    if "【推命命中】" in raw:
        return "推命命中"
    if "【推命落空】" in raw:
        return "推命落空"
    if "【改命回天】" in raw:
        return "改命回天"
    if any(
        token in raw
        for token in ("失败", "不敌", "落败", "无功而返", "冷却", "不足", "无法", "未能")
    ):
        return "失败"
    if any(
        token in raw
        for token in ("成功", "妖兽伏诛", "采得", "满载而归", "获得修为", "获得 【")
    ):
        return "成功"
    return "未归类"


def compact_log_text(text: str, limit: int = 160) -> str:
    compact = re.sub(r"\s+", " ", str(text or "").strip())
    if len(compact) <= limit:
        return compact
    return compact[: max(0, int(limit) - 1)].rstrip() + "…"


def markdown_fence_text(text: str) -> str:
    return str(text or "").replace("```", "'''").strip()
