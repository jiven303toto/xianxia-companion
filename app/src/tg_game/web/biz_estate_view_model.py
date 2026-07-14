from typing import Optional
from tg_game.features.estate.biz_estate_miniapp import (
    build_estate_miniapp_entry_view,
    build_estate_miniapp_hunt,
    build_estate_miniapp_snapshot,
    is_estate_miniapp_hunt_limit_reached,
)
from tg_game.web.biz_web_display_formatting import (
    build_scenery_entries,
    coerce_json_dict,
    coerce_json_list,
    collect_display_names,
    resolve_payload_display_name,
)


def _estate_hunt_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def build_estate_miniapp_hunt_button(hunt: dict) -> dict:
    used = _estate_hunt_int(hunt.get("used"))
    limit = _estate_hunt_int(hunt.get("limit"))
    if is_estate_miniapp_hunt_limit_reached({"dongfu": {"miniapp_hunt": hunt}}):
        return {
            "action": "/runtime/estate/miniapp-hunt-canary",
            "command_text": "",
            "label": "今日寻宝已满",
            "css_class": "limit-reached",
            "disabled": True,
            "status_override": f"今日寻宝已满（{used}/{limit}）" if limit else "今日寻宝已满",
        }
    return {
        "action": "/runtime/estate/miniapp-hunt-canary",
        "command_text": "",
        "label": "MiniApp 自动寻宝至上限",
        "css_class": "",
        "disabled": False,
        "status_override": "",
    }


def build_dongfu_pavilion_slots_view(
    raw_value, game_items_dict: Optional[dict] = None
) -> dict[str, str]:
    raw_slots = coerce_json_dict(raw_value)
    if not raw_slots:
        return {}

    def sort_key(item) -> tuple[int, str]:
        slot_key = str(item[0] or "").strip()
        return (0, f"{int(slot_key):09d}") if slot_key.isdigit() else (1, slot_key)

    slots = {}
    for slot_key, slot_value in sorted(raw_slots.items(), key=sort_key):
        normalized_slot = str(slot_key or "").strip() or "?"
        slot_label = (
            f"{normalized_slot}号位" if normalized_slot.isdigit() else normalized_slot
        )
        slot_dict = coerce_json_dict(slot_value)
        item_payload = coerce_json_dict(slot_dict.get("item_json")) or slot_dict
        item_id = str(
            item_payload.get("item_id") or slot_dict.get("item_id") or ""
        ).strip()
        item_name = str(
            item_payload.get("name")
            or slot_dict.get("name")
            or resolve_payload_display_name(item_id, game_items_dict or {})
            or ""
        ).strip()
        quantity = int(item_payload.get("quantity") or slot_dict.get("quantity") or 0)
        if item_name and quantity > 1:
            item_name = f"{item_name}*{quantity}"
        slots[slot_label] = item_name or item_id or "空"
    return slots


def build_dongfu_view(payload: dict, game_items_dict: Optional[dict] = None) -> dict:
    dongfu = coerce_json_dict((payload or {}).get("dongfu"))
    inventory = coerce_json_dict((payload or {}).get("inventory"))
    storage_bag_options = [
        name
        for name in [
            *collect_display_names(inventory.get("items"), game_items_dict),
            *[
                name
                for name in collect_display_names(
                    inventory.get("materials"), game_items_dict
                )
                if name != "灵石"
            ],
        ]
        if name
    ]
    unlocked_scenery_entries = build_scenery_entries(
        dongfu.get("unlocked_scenery"), game_items_dict
    )
    scenery_slot_entries = build_scenery_entries(
        dongfu.get("scenery_slots"), game_items_dict
    )
    scenery_options = [
        entry.get("name")
        for entry in [*unlocked_scenery_entries, *scenery_slot_entries]
        if entry.get("name")
    ]
    miniapp_hunt = build_estate_miniapp_hunt(dongfu.get("miniapp_hunt"))
    return {
        "raw": dongfu,
        "lingmai_level": int(dongfu.get("lingmai_level") or 0),
        "jingshi_level": int(dongfu.get("jingshi_level") or 0),
        "danfang_level": int(dongfu.get("danfang_level") or 0),
        "qishi_level": int(dongfu.get("qishi_level") or 0),
        "shouyuan_level": int(dongfu.get("shouyuan_level") or 0),
        "dazhen_level": int(dongfu.get("dazhen_level") or 0),
        "dazhen_active": bool(int(dongfu.get("dazhen_active") or 0)),
        "dazhen_mode": str(dongfu.get("dazhen_mode") or "").strip(),
        "lingqi_pool": round(float(dongfu.get("lingqi_pool") or 0), 2),
        "pavilion_slots": build_dongfu_pavilion_slots_view(
            dongfu.get("pavilion_slots"), game_items_dict
        ),
        "scenery_slots": scenery_slot_entries,
        "unlocked_scenery": unlocked_scenery_entries,
        "storage_bag_options": sorted(set(storage_bag_options)),
        "scenery_options": scenery_options,
        "messages": coerce_json_list(dongfu.get("messages")),
        "last_update_time": str(dongfu.get("last_update_time") or "").strip(),
        "miniapp_entry": build_estate_miniapp_entry_view(
            dongfu.get("miniapp_entry")
        ),
        "miniapp_snapshot": build_estate_miniapp_snapshot(
            dongfu.get("miniapp_snapshot")
        ),
        "miniapp_hunt": miniapp_hunt,
        "miniapp_hunt_button": build_estate_miniapp_hunt_button(miniapp_hunt),
    }
