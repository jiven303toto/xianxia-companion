from tg_game.web.biz_web_display_formatting import coerce_json_list

SMALL_WORLD_MIN_MAJOR_STAGE = "化神"
MAJOR_STAGE_ORDER = (
    "练气",
    "筑基",
    "结丹",
    "元婴",
    "化神",
    "半步炼虚",
    "炼虚",
    "合体",
    "大乘",
    "渡劫",
)


def major_stage_rank(stage_name: str) -> int:
    normalized = str(stage_name or "").strip()
    for index, major_stage in enumerate(MAJOR_STAGE_ORDER):
        if major_stage in normalized:
            return index
    return -1


def is_small_world_module_available(active_profile) -> bool:
    if not active_profile:
        return False
    return major_stage_rank(getattr(active_profile, "stage_name", "")) >= major_stage_rank(
        SMALL_WORLD_MIN_MAJOR_STAGE
    )


def is_yuanying_stage(active_profile) -> bool:
    if not active_profile:
        return False
    return major_stage_rank(getattr(active_profile, "stage_name", "")) >= major_stage_rank(
        "元婴"
    )


def payload_has_artifact_spirit(payload) -> bool:
    if not isinstance(payload, dict):
        return False
    inventory = payload.get("inventory") or {}
    items = inventory.get("items") if isinstance(inventory, dict) else []
    for item in coerce_json_list(items):
        if not isinstance(item, dict):
            continue
        spirit = item.get("spirit")
        if isinstance(spirit, dict) and spirit:
            return True
        if isinstance(spirit, str) and spirit.strip():
            return True
    return False
