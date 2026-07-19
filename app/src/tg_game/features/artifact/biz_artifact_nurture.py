import re

from tg_game.features.artifact.biz_artifact_trial import (
    build_artifact_trial_resource_state,
)


ARTIFACT_NURTURE_FEATURE_KEY = "artifact_nurture"
ARTIFACT_NURTURE_AWAIT_REPLY_STATE = "artifact_nurture_await_reply"
ARTIFACT_NURTURE_BOT_COOLDOWN_STATE = "artifact_nurture_bot_cooldown"
ARTIFACT_NURTURE_INTERNAL_WAIT_STATE = "artifact_nurture_internal_wait"
ARTIFACT_NURTURE_STOPPED_RESOURCES_STATE = "artifact_nurture_stopped_resources"
ARTIFACT_NURTURE_DEFAULT_TARGET_NAME = "玄天斩灵剑"
ARTIFACT_NURTURE_DEFAULT_COOLDOWN_SECONDS = 6 * 3600
ARTIFACT_NURTURE_REPLY_WAIT_SECONDS = 180
ARTIFACT_NURTURE_SPIRIT_STONE_COST = 3000
ARTIFACT_NURTURE_SOUL_WOOD_COST = 3


def normalize_artifact_nurture_target_name(value: object) -> str:
    normalized = re.sub(r"\s+", " ", str(value or "").strip())
    return (normalized or ARTIFACT_NURTURE_DEFAULT_TARGET_NAME)[:60]


def build_artifact_nurture_command(target_name: object) -> str:
    return f".温养器灵 {normalize_artifact_nurture_target_name(target_name)}"


def pack_artifact_nurture_strategy(target_name: object) -> str:
    return normalize_artifact_nurture_target_name(target_name)[:100]


def unpack_artifact_nurture_strategy(value: object) -> str:
    return normalize_artifact_nurture_target_name(value)


def build_artifact_nurture_resource_state(
    payload: dict,
    game_items_dict: dict,
) -> dict:
    return build_artifact_trial_resource_state(
        payload,
        game_items_dict,
        spirit_stone_cost=ARTIFACT_NURTURE_SPIRIT_STONE_COST,
        soul_wood_cost=ARTIFACT_NURTURE_SOUL_WOOD_COST,
    )
