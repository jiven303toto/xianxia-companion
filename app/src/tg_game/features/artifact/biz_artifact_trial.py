import re


ARTIFACT_TRIAL_FEATURE_KEY = "artifact_trial"
ARTIFACT_TRIAL_AWAIT_REPLY_STATE = "artifact_trial_await_reply"
ARTIFACT_TRIAL_BOT_COOLDOWN_STATE = "artifact_trial_bot_cooldown"
ARTIFACT_TRIAL_STOPPED_RESOURCES_STATE = "artifact_trial_stopped_resources"
ARTIFACT_TRIAL_DEFAULT_ARTIFACT_NAME = "玄天斩灵剑"
ARTIFACT_TRIAL_ROUTES = ("静修", "寻宝", "斗战")
ARTIFACT_TRIAL_SPIRIT_STONE_COST = 1800
ARTIFACT_TRIAL_SOUL_WOOD_COST = 1


def _parse_quantity(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return max(int(value), 0)
    text = str(value or "").strip()
    if not text:
        return default
    match = re.search(r"\d+", text)
    if not match:
        return default
    return max(int(match.group(0)), 0)


def normalize_artifact_trial_artifact_name(value: object) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "").strip())
    return (normalized or ARTIFACT_TRIAL_DEFAULT_ARTIFACT_NAME)[:60]


def normalize_artifact_trial_route(value: object) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized in ARTIFACT_TRIAL_ROUTES else ARTIFACT_TRIAL_ROUTES[0]


def build_artifact_trial_command(artifact_name: object, route: object) -> str:
    return (
        f".器灵试炼 "
        f"{normalize_artifact_trial_artifact_name(artifact_name)} "
        f"{normalize_artifact_trial_route(route)}"
    )


def pack_artifact_trial_strategy(artifact_name: object, route: object) -> str:
    artifact = normalize_artifact_trial_artifact_name(artifact_name)
    normalized_route = normalize_artifact_trial_route(route)
    return f"{normalized_route}|{artifact}"[:100]


def unpack_artifact_trial_strategy(value: object) -> tuple[str, str]:
    raw = str(value or "").strip()
    if "|" in raw:
        route_text, artifact_text = raw.split("|", 1)
        return (
            normalize_artifact_trial_artifact_name(artifact_text),
            normalize_artifact_trial_route(route_text),
        )
    return (
        normalize_artifact_trial_artifact_name(raw),
        ARTIFACT_TRIAL_ROUTES[0],
    )


def _item_name_matches_soul_wood(item_id: str, item_name: str) -> bool:
    return item_id == "养魂木" or item_name == "养魂木"


def build_artifact_trial_resource_state(
    payload: dict,
    game_items_dict: dict,
    *,
    spirit_stone_cost: int = ARTIFACT_TRIAL_SPIRIT_STONE_COST,
    soul_wood_cost: int = ARTIFACT_TRIAL_SOUL_WOOD_COST,
) -> dict:
    inventory = (payload or {}).get("inventory") if isinstance(payload, dict) else {}
    inventory = inventory if isinstance(inventory, dict) else {}
    materials = inventory.get("materials") if isinstance(inventory.get("materials"), dict) else {}
    items = inventory.get("items") if isinstance(inventory.get("items"), list) else []
    game_items = game_items_dict if isinstance(game_items_dict, dict) else {}

    spirit_stones = _parse_quantity(materials.get("mat_001"))
    soul_wood = 0
    for item_id, raw_count in materials.items():
        normalized_id = str(item_id or "").strip()
        meta = game_items.get(normalized_id) or {}
        item_name = str(meta.get("name") or normalized_id).strip()
        if _item_name_matches_soul_wood(normalized_id, item_name):
            soul_wood += _parse_quantity(raw_count)

    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue
        item_id = str(raw_item.get("item_id") or raw_item.get("id") or "").strip()
        meta = game_items.get(item_id) or {}
        item_name = str(raw_item.get("name") or meta.get("name") or item_id).strip()
        if _item_name_matches_soul_wood(item_id, item_name):
            soul_wood += _parse_quantity(raw_item.get("quantity"), default=1)

    missing = []
    if spirit_stones < spirit_stone_cost:
        missing.append(f"灵石 {spirit_stones}/{spirit_stone_cost}")
    if soul_wood < soul_wood_cost:
        missing.append(f"养魂木 {soul_wood}/{soul_wood_cost}")

    return {
        "ok": not missing,
        "spirit_stones": spirit_stones,
        "soul_wood": soul_wood,
        "spirit_stone_cost": spirit_stone_cost,
        "soul_wood_cost": soul_wood_cost,
        "missing": missing,
        "error_text": "资源不足：" + "，".join(missing) + "。"
        if missing
        else "",
    }
