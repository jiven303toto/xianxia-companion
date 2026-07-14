import json
import sqlite3
from pathlib import Path
from typing import Optional
import biz_sect_game

from tg_game.web.biz_web_display_formatting import (
    coerce_json_dict,
    coerce_json_list,
    resolve_payload_display_name,
)


def format_market_price(raw_value, game_items_dict: dict) -> str:
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return "-"
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return text
        return format_market_price(parsed, game_items_dict)
    if isinstance(raw_value, dict):
        parts = []
        for item_id, quantity in raw_value.items():
            display_name = resolve_payload_display_name(item_id, game_items_dict)
            qty = biz_sect_game._parse_int(quantity, 0)
            if qty > 0:
                parts.append(f"{display_name}*{qty}")
            elif display_name:
                parts.append(display_name)
        return "、".join(parts) if parts else "-"
    if isinstance(raw_value, list):
        parts = []
        for item in raw_value:
            formatted = format_market_price(item, game_items_dict)
            if formatted != "-":
                parts.append(formatted)
        return "、".join(parts) if parts else "-"
    text = str(raw_value or "").strip()
    return text or "-"


def market_price_parts(raw_value, game_items_dict: dict) -> list[dict]:
    if isinstance(raw_value, str):
        text = raw_value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return [{"name": text, "quantity": 0}]
        return market_price_parts(parsed, game_items_dict)
    if isinstance(raw_value, dict):
        parts = []
        for item_id, quantity in raw_value.items():
            display_name = resolve_payload_display_name(item_id, game_items_dict)
            parts.append(
                {
                    "name": display_name or str(item_id or "").strip(),
                    "quantity": max(biz_sect_game._parse_int(quantity, 0), 0),
                }
            )
        return sorted(parts, key=lambda item: (item["name"], item["quantity"]))
    if isinstance(raw_value, list):
        parts = []
        for item in raw_value:
            parts.extend(market_price_parts(item, game_items_dict))
        return parts
    text = str(raw_value or "").strip()
    return [{"name": text, "quantity": 0}] if text else []


def market_price_sort_key(raw_value, game_items_dict: dict) -> tuple:
    parts = market_price_parts(raw_value, game_items_dict)
    if not parts:
        return ((1, "", 0),)
    normalized_parts = sorted(
        parts,
        key=lambda part: (
            0 if str(part.get("name") or "").strip() == "灵石" else 1,
            str(part.get("name") or "").strip(),
            int(part.get("quantity") or 0),
        ),
    )
    return tuple(
        (
            0 if str(part.get("name") or "").strip() == "灵石" else 1,
            str(part.get("name") or "").strip(),
            int(part.get("quantity") or 0),
        )
        for part in normalized_parts
    )


def reverse_market_price_sort_key(sort_key: tuple) -> tuple:
    reversed_parts = []
    for priority, name, quantity in sort_key or ():
        reversed_parts.append((priority, name, -int(quantity or 0)))
    return tuple(reversed_parts)


def market_price_preview(
    raw_value, game_items_dict: dict, max_parts: int = 3
) -> dict:
    parts = market_price_parts(raw_value, game_items_dict)
    full_parts = []
    for part in parts:
        name = str(part.get("name") or "").strip()
        quantity = int(part.get("quantity") or 0)
        if not name:
            continue
        full_parts.append(f"{name}*{quantity}" if quantity > 0 else name)
    if not full_parts:
        return {"preview_text": "-", "full_text": "-", "item_count": 0}
    preview_parts = full_parts[:max_parts]
    preview_text = "、".join(preview_parts)
    if len(full_parts) > max_parts:
        preview_text = f"{preview_text} 等{len(full_parts)}项"
    return {
        "preview_text": preview_text,
        "full_text": "、".join(full_parts),
        "item_count": len(full_parts),
    }


def item_type_label(raw_type: str, *, is_material: bool = False) -> str:
    item_type_map = {
        "material": "材料",
        "elixir": "丹药",
        "recipe": "图纸",
        "quest_item": "任务道具",
        "treasure": "法宝",
        "badge": "徽章",
        "talisman": "符箓",
        "formation": "阵法",
        "seed": "种子",
        "special_item": "特殊物品",
        "special_tool": "特殊工具",
        "recipe_internal": "特殊配方",
        "loot_box": "宝箱",
    }
    normalized = str(raw_type or "").strip()
    if normalized:
        return item_type_map.get(normalized, normalized)
    return "材料" if is_material else "-"


def inventory_item_matches_query(item: dict, query: str) -> bool:
    normalized_query = str(query or "").strip().lower()
    if not normalized_query:
        return True
    haystack = " ".join(
        str(value or "")
        for value in (
            item.get("name"),
            item.get("item_id"),
            item.get("type"),
            item.get("raw_type"),
            item.get("description"),
        )
    ).lower()
    return normalized_query in haystack


def profile_display_label(profile) -> str:
    return (
        getattr(profile, "game_name", None)
        or getattr(profile, "display_name", None)
        or getattr(profile, "account_name", None)
        or getattr(profile, "name", "")
    )


def telegram_session_file_path(storage, session_name: str) -> Optional[Path]:
    name = str(session_name or "").strip()
    if not name:
        return None
    path = Path(name)
    if not path.is_absolute() and path.parent == Path("."):
        path = Path(storage.path).parent / path
    if path.suffix != ".session":
        path = Path(str(path) + ".session")
    return path


def read_telegram_session_display_name(storage, profile) -> str:
    path = telegram_session_file_path(
        storage, getattr(profile, "telegram_session_name", "")
    )
    if not path or not path.is_file():
        return ""
    telegram_user_id = str(getattr(profile, "telegram_user_id", "") or "").strip()
    telegram_username = (
        str(getattr(profile, "telegram_username", "") or "").strip().lstrip("@").lower()
    )
    conn = None
    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        if telegram_user_id:
            row = conn.execute(
                "SELECT name FROM entities WHERE id=? LIMIT 1",
                (int(telegram_user_id),),
            ).fetchone()
            if row and str(row["name"] or "").strip():
                return str(row["name"]).strip()
        if telegram_username:
            row = conn.execute(
                "SELECT name FROM entities WHERE lower(username)=? LIMIT 1",
                (telegram_username,),
            ).fetchone()
            if row and str(row["name"] or "").strip():
                return str(row["name"]).strip()
    except (OSError, sqlite3.Error, ValueError):
        return ""
    finally:
        if conn is not None:
            conn.close()
    return ""


def resolve_profile_telegram_name(
    storage,
    profile,
    external_account: dict | None,
    *,
    session_display_name_reader=read_telegram_session_display_name,
) -> str:
    account = external_account or {}
    me_payload = coerce_json_dict(account.get("me_json"))
    first_name = str(me_payload.get("first_name") or "").strip()
    last_name = str(me_payload.get("last_name") or "").strip()
    full_name = " ".join(part for part in (first_name, last_name) if part)
    if full_name:
        return full_name
    session_display_name = session_display_name_reader(storage, profile)
    return session_display_name or "未记录"


def build_profile_telegram_name_map(
    storage,
    profiles: list,
    *,
    external_account_reader,
) -> dict:
    return {
        profile.id: resolve_profile_telegram_name(
            storage,
            profile,
            external_account_reader(profile),
        )
        for profile in profiles
    }


def build_inventory_items_from_payload(
    payload: dict, game_items_dict: dict
) -> list[dict]:
    inventory_data = coerce_json_dict((payload or {}).get("inventory"))
    raw_materials = coerce_json_dict(inventory_data.get("materials"))
    raw_items = coerce_json_list(inventory_data.get("items"))
    equipped_id_list = (payload or {}).get("equipped_treasure_id")
    equipped_ids = (
        {
            str(item_id or "").strip()
            for item_id in (equipped_id_list or [])
            if str(item_id or "").strip()
        }
        if isinstance(equipped_id_list, list)
        else set()
    )
    inventory_items = []
    for mat_id, count in raw_materials.items():
        if mat_id == "mat_001":
            continue
        meta = game_items_dict.get(mat_id, {})
        quantity_value = max(biz_sect_game._parse_int(count, 0), 0)
        inventory_items.append(
            {
                "item_id": mat_id,
                "name": meta.get("name", mat_id),
                "description": meta.get("description", ""),
                "type": item_type_label("material"),
                "raw_type": "material",
                "quantity": quantity_value,
                "quantity_value": quantity_value,
                "durability": None,
                "max_durability": None,
                "is_artifact": False,
                "show_durability": False,
            }
        )
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        item = dict(raw_item)
        raw_t = item.get("type", "")
        raw_type = str(raw_t or "").strip()
        item_id = str(item.get("item_id") or "").strip()
        quantity_value = max(biz_sect_game._parse_int(item.get("quantity"), 1), 1)
        item["raw_type"] = raw_t
        item["type"] = item_type_label(raw_type)
        item["quantity"] = quantity_value
        item["quantity_value"] = quantity_value
        item["is_artifact"] = raw_type == "treasure" or item_id in equipped_ids
        item["show_durability"] = (
            bool(item.get("is_artifact"))
            and item.get("durability") is not None
            and item.get("max_durability") is not None
        )
        inventory_items.append(item)
    for item in inventory_items:
        if str(item.get("item_id") or "").strip() in equipped_ids:
            item["is_equipped"] = True
    inventory_items.sort(
        key=lambda item: (
            -int(item.get("quantity_value") or item.get("quantity") or 0),
            0 if item.get("is_equipped") else 1,
            str(item.get("type") or ""),
            str(item.get("name") or item.get("item_id") or ""),
        )
    )
    return inventory_items


def build_inventory_bulk_sell_command(inventory_items: list[dict]) -> str:
    trade_parts = []
    for item in inventory_items:
        raw_type = str(item.get("raw_type") or "").strip()
        if raw_type not in {"material", "recipe", "elixir"}:
            continue
        name = str(item.get("name") or item.get("item_id") or "").strip()
        if name in {"增元丹", "合气丹"}:
            continue
        quantity = max(biz_sect_game._parse_int(item.get("quantity"), 0), 0)
        if not name or quantity <= 0:
            continue
        trade_parts.append(f"{name}*{quantity}")
    if not trade_parts:
        return ""
    return f".上架 凝血草*1 换 {' '.join(trade_parts)}"


def build_profile_inventory_search(
    profiles: list,
    query: str,
    *,
    game_items_dict: dict,
    payload_reader,
) -> dict:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return {"query": "", "results": [], "total": 0}
    grouped = {}
    for profile in profiles:
        payload = payload_reader(profile)
        inventory_data = coerce_json_dict((payload or {}).get("inventory"))
        raw_materials = coerce_json_dict(inventory_data.get("materials"))
        searchable_items = build_inventory_items_from_payload(payload, game_items_dict)
        spirit_stones = max(biz_sect_game._parse_int(raw_materials.get("mat_001"), 0), 0)
        if spirit_stones:
            searchable_items.append(
                {
                    "item_id": "mat_001",
                    "name": "灵石",
                    "description": "随身储物资产",
                    "type": "资产",
                    "raw_type": "currency",
                    "quantity": spirit_stones,
                    "quantity_value": spirit_stones,
                }
            )
        for item in searchable_items:
            if not inventory_item_matches_query(item, normalized_query):
                continue
            item_id = str(item.get("item_id") or "").strip()
            name = str(item.get("name") or item_id or "未知物品").strip()
            item_type = str(item.get("type") or "").strip()
            key = (item_id, name, item_type)
            group = grouped.setdefault(
                key,
                {
                    "item_id": item_id,
                    "name": name,
                    "type": item_type,
                    "quantity": 0,
                    "profiles": {},
                },
            )
            quantity = max(
                biz_sect_game._parse_int(
                    item.get("quantity_value") or item.get("quantity"), 0
                ),
                0,
            )
            group["quantity"] += quantity
            profile_entry = group["profiles"].setdefault(
                profile.id,
                {
                    "profile_id": profile.id,
                    "profile_name": profile_display_label(profile),
                    "telegram_label": (
                        f"@{profile.telegram_username}"
                        if getattr(profile, "telegram_username", None)
                        else (getattr(profile, "telegram_user_id", "") or "未绑定")
                    ),
                    "quantity": 0,
                },
            )
            profile_entry["quantity"] += quantity
    results = []
    for group in grouped.values():
        group["profiles"] = sorted(
            group["profiles"].values(),
            key=lambda entry: (
                str(entry["profile_name"]).lower(),
                int(entry["profile_id"]),
            ),
        )
        results.append(group)
    results.sort(
        key=lambda item: (
            -int(item["quantity"] or 0),
            str(item["name"]),
            str(item["item_id"]),
        )
    )
    return {"query": normalized_query, "results": results, "total": len(results)}
