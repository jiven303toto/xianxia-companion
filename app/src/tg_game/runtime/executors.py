import asyncio
import json
import logging
import re
import secrets
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Callable, Iterable, Optional
import biz_artifact_game
import biz_basic_game
import biz_battle_game
import biz_breakthrough_game
import biz_companion_game
import biz_diplomacy_game
import biz_dungeon_game
import biz_estate_game
import biz_fanren_game
import biz_fishing_game
import biz_market_game
from tg_game import pagoda_auto
import biz_sect_game
import biz_shop_game
import biz_small_world_game
import biz_stock_game
import biz_inventory_game

from tg_game.runtime.context import EventContext
from tg_game.runtime.queue_service import has_blocking_outgoing_command
from tg_game.features.artifact.biz_artifact_touch_auto import (
    ARTIFACT_TOUCH_DEFAULT_INTERVAL_SECONDS,
    ARTIFACT_TOUCH_MIN_INTERVAL_SECONDS,
    normalize_artifact_touch_command,
    normalize_artifact_touch_interval,
    unpack_artifact_touch_strategy,
)
from tg_game.features.artifact.biz_artifact_nurture import (
    ARTIFACT_NURTURE_AWAIT_REPLY_STATE,
    ARTIFACT_NURTURE_BOT_COOLDOWN_STATE,
    ARTIFACT_NURTURE_DEFAULT_COOLDOWN_SECONDS,
    ARTIFACT_NURTURE_FEATURE_KEY,
    ARTIFACT_NURTURE_INTERNAL_WAIT_STATE,
    ARTIFACT_NURTURE_REPLY_WAIT_SECONDS,
    ARTIFACT_NURTURE_STOPPED_RESOURCES_STATE,
    build_artifact_nurture_command,
    build_artifact_nurture_resource_state,
    normalize_artifact_nurture_target_name,
    unpack_artifact_nurture_strategy,
)
from tg_game.features.artifact.biz_artifact_trial import (
    build_artifact_trial_command,
    build_artifact_trial_resource_state,
    normalize_artifact_trial_artifact_name,
    normalize_artifact_trial_route,
    unpack_artifact_trial_strategy,
)
from tg_game.features.companion.biz_companion_cooldown import (
    SIMPLE_COOLDOWN_AUTO_FEATURES,
    normalize_wild_experience_strategy,
    resolve_simple_cooldown_next_run_at,
)
from tg_game.features.companion.biz_companion_voyage import (
    COMPANION_VOYAGE_STRATEGY_OPTIONS,
    build_companion_voyage_state_from_reply,
    is_companion_panel_text,
    normalize_companion_voyage_strategy,
    parse_chinese_duration_seconds,
)
from tg_game.features.beast_merge import biz_beast_merge_daily_auto
from tg_game.features.beast_merge import biz_beast_merge_miniapp as beast_merge_miniapp
from tg_game.features.beast_merge import biz_beast_merge_state
from tg_game.features.estate import biz_estate_miniapp as estate_miniapp
from tg_game.features.estate import biz_estate_hunt_daily_auto
from tg_game.features.estate.biz_estate_miniapp import (
    extract_estate_miniapp_entry,
    merge_estate_miniapp_payload,
)
from tg_game.features.pagoda import biz_pagoda_miniapp as pagoda_miniapp
from tg_game.features.pagoda import biz_pagoda_state as pagoda_state
from tg_game.features.tianji_trial import biz_tianji_trial_daily_auto
from tg_game.features.tianji_trial import biz_tianji_trial_miniapp as tianji_trial_miniapp
from tg_game.features.tianji_trial import biz_tianji_trial_remnant_state
from tg_game.features.tianji_trial.biz_tianji_trial_remnant_view import (
    parse_tianji_remnant_panel_text,
)
from tg_game.features.luoyun_spirit_tree import (
    biz_luoyun_spirit_tree_daily_auto,
)
from tg_game.features.luoyun_spirit_tree import (
    biz_luoyun_spirit_tree_miniapp as luoyun_spirit_tree_miniapp,
)
from tg_game.features.wild_experience import (
    biz_wild_experience_miniapp as wild_experience_miniapp,
)
from tg_game.features.fishing.biz_fishing_replies import build_session_updates_from_reply
from tg_game.features.fishing import biz_fishing_miniapp as fishing_miniapp
from tg_game.features.fishing import biz_fishing_daily_auto
from tg_game.features.fishing.biz_fishing_miniapp import (
    append_miniapp_entry_block,
    extract_fishing_miniapp_entry,
)
from tg_game.features import biz_mulan_feature as mulan_feature
from tg_game.features.tianxing import build_exploration_route_gate, tick_craft_loop, tick_tianxing_timeline
from tg_game.features.small_world.biz_small_world_auto import (
    SMALL_WORLD_ACTION_COMMANDS,
    SMALL_WORLD_ACTION_STATES_BY_COMMAND,
    build_auto_action_commands,
    build_quench_command_from_collect_reply,
    build_quench_reply_state,
    resolve_awaited_action_command,
    select_next_action_command,
)
from tg_game.features.xinggong.biz_xinggong_star_board import (
    XINGGONG_STARBOARD_COLLECT_COMMAND,
    XINGGONG_STARBOARD_COMFORT_COMMAND,
    XINGGONG_STARBOARD_PENDING_CHECK_SECONDS,
    XINGGONG_STARBOARD_PULL_PREFIX,
    XINGGONG_STARBOARD_READY_CHECK_SECONDS,
    XINGGONG_STARBOARD_FEATURE_KEY,
    XINGGONG_STARBOARD_RECHECK_SECONDS,
    build_starboard_commands,
    build_starboard_next_check_time,
    build_starboard_pending_candidates,
    get_starboard_plots,
    normalize_starboard_target,
)
from tg_game.features.xinggong import biz_xinggong_miniapp as xinggong_miniapp
from tg_game.features.wanling.biz_wanling_roam import (
    WANLING_ROAM_AUTO_AFTER_RETURN_SECONDS,
    WANLING_ROAM_COMMAND,
    WANLING_ROAM_COMMAND_DELAY_SECONDS,
    WANLING_ROAM_COMMAND_SEQUENCE,
    WANLING_ROAM_DURATION_SECONDS,
    WANLING_ROAM_FEATURE_KEY,
    WANLING_ROAM_POST_SEND_GRACE_SECONDS,
    WANLING_ROAM_RECHECK_SECONDS,
    WANLING_ROAM_RETURN_BUFFER_SECONDS,
    build_wanling_roam_cancel_commands,
    build_wanling_roam_command_sequence,
    is_wanling_profile,
    parse_wanling_roam_timestamp,
    resolve_wanling_roam_next_finish_at,
)
from tg_game.services.cultivation_sync import sync_cultivation_session
from tg_game.services.external_sync import ASC_PROVIDER, read_cached_external_payload
from tg_game.services import profile_rebirth
from tg_game.storage import (
    OUTGOING_CONFIRM_TIMEOUT_SECONDS,
    OUTGOING_CONFIRMED_STATUSES,
    CompatDb as SQLiteCompatDb,
    Storage,
    telegram_resume_gap_state_key,
    telegram_resume_until_state_key,
)
from tg_game.telegram.network_guard import is_network_paused
from tg_game.telegram.send_utils import send_message_with_thread_fallback

logger = logging.getLogger(__name__)

DIVINATION_COMMAND = ".卜筮问天"
DIVINATION_BATCH_COMMAND_INTERVAL_SECONDS = 60
DIVINATION_BATCH_POLL_SECONDS = 5
FANREN_RECENT_REPLY_WINDOW_SECONDS = 30
COMPANION_AUTO_POLL_SECONDS = 5
FISHING_AUTO_POLL_SECONDS = 2
PAGODA_LEASE_RENEW_INTERVAL_SECONDS = 60
COMPANION_HEART_TRIBULATION_EMPTY_SLEEP_SECONDS = 5
COMPANION_HEART_TRIBULATION_ACTIVE_POLL_SECONDS = 2
COMPANION_HEART_TRIBULATION_IDLE_SLEEP_MAX_SECONDS = 60
AUTO_COMMAND_MANUAL_CONFIRM_BLOCK_SECONDS = OUTGOING_CONFIRM_TIMEOUT_SECONDS
COMPANION_AUTO_POST_SEND_GRACE_SECONDS = 1800
COMPANION_AUTO_RESUME_MODE_SECONDS = 30 * 60
COMPANION_AUTO_RESUME_TASK_SPACING_SECONDS = 60
COMPANION_AUTO_LONG_RESUME_SECONDS = 4 * 3600
COMPANION_AUTO_LONG_RESUME_DEFER_SECONDS = 15 * 60
ARTIFACT_TOUCH_FEATURE_KEY = "artifact_touch"
ARTIFACT_TOUCH_COOLDOWN_BUFFER_SECONDS = 10
ARTIFACT_TOUCH_REPLY_WAIT_SECONDS = 180
ARTIFACT_TOUCH_PROBE_DELAY_SECONDS = 10
ARTIFACT_TOUCH_AWAIT_REPLY_STATE = "artifact_touch_await_reply"
ARTIFACT_TOUCH_PROBE_PENDING_STATE = "artifact_touch_probe_pending"
ARTIFACT_TOUCH_BOT_COOLDOWN_STATE = "artifact_touch_bot_cooldown"
ARTIFACT_TOUCH_INTERNAL_WAIT_STATE = "artifact_touch_internal_wait"
ARTIFACT_TRIAL_FEATURE_KEY = "artifact_trial"
ARTIFACT_TRIAL_COOLDOWN_BUFFER_SECONDS = 10
ARTIFACT_TRIAL_REPLY_WAIT_SECONDS = 180
ARTIFACT_TRIAL_DEFAULT_COOLDOWN_SECONDS = 8 * 3600
ARTIFACT_TRIAL_AWAIT_REPLY_STATE = "artifact_trial_await_reply"
ARTIFACT_TRIAL_BOT_COOLDOWN_STATE = "artifact_trial_bot_cooldown"
ARTIFACT_TRIAL_INTERNAL_WAIT_STATE = "artifact_trial_internal_wait"
ARTIFACT_TRIAL_STOPPED_RESOURCES_STATE = "artifact_trial_stopped_resources"
ARTIFACT_NURTURE_COOLDOWN_BUFFER_SECONDS = 10
COMPANION_PANEL_COMMAND = ".我的侍妾"
COMPANION_VOYAGE_FEATURE_KEY = "companion_voyage"
COMPANION_VOYAGE_STATUS_COMMAND = ".远航状态"
COMPANION_VOYAGE_RETURN_COMMAND = ".远航归来"
COMPANION_VOYAGE_RECHECK_SECONDS = 60
COMPANION_VOYAGE_RETURN_DELAY_SECONDS = 10
COMPANION_VOYAGE_PREFLIGHT_RECHECK_SECONDS = 60
COMPANION_VOYAGE_PREFLIGHT_RECENT_SEND_SECONDS = 30 * 60
COMPANION_VOYAGE_PREFLIGHT_COMMAND_DELAY_SECONDS = 60
SMALL_WORLD_PANEL_WAIT_SECONDS = 60
SMALL_WORLD_PANEL_RETRY_SECONDS = 10
SMALL_WORLD_ACTION_REPLY_WAIT_SECONDS = 180
MULAN_PANEL_WAIT_SECONDS = 60
MULAN_STEP_RETRY_SECONDS = 10
MULAN_SPY_REPLY_WAIT_SECONDS = 60
MULAN_COLLECT_REPORT_REPLY_WAIT_SECONDS = 60
MULAN_VERIFY_REPORT_REPLY_WAIT_SECONDS = 60
MULAN_PUBLIC_REPORT_REPLY_WAIT_SECONDS = 60
MULAN_SUPPORT_REPLY_WAIT_SECONDS = 180
MULAN_DAILY_RUN_MINUTE = 5
COMPANION_PANEL_FRESH_SECONDS = 120
COMPANION_VOYAGE_ACTIVE_COMMAND_STATUSES = {
    "pending",
    "sending",
    "awaiting_confirm",
}
COMPANION_VOYAGE_PREFLIGHT_SIMPLE_FEATURES = (
    "divination_chain",
    "dream_seek",
)
COMPANION_PANEL_COOLDOWN_LABELS = {
    "dream_seek": "入梦寻图",
    "divination_chain": "天机代卜",
    "heart_tribulation": "共历心劫",
}
COMPANION_AUTO_RESUME_HIGH_RISK_FEATURES = {
    ARTIFACT_TOUCH_FEATURE_KEY,
    ARTIFACT_TRIAL_FEATURE_KEY,
    ARTIFACT_NURTURE_FEATURE_KEY,
    WANLING_ROAM_FEATURE_KEY,
    XINGGONG_STARBOARD_FEATURE_KEY,
    biz_luoyun_spirit_tree_daily_auto.FEATURE_KEY,
    biz_fishing_daily_auto.FEATURE_KEY,
    COMPANION_VOYAGE_FEATURE_KEY,
    biz_small_world_game.SMALL_WORLD_AUTO_FEATURE_KEY,
    biz_small_world_game.SMALL_WORLD_PREACH_AUTO_FEATURE_KEY,
    mulan_feature.MULAN_AUTO_SUPPORT_FEATURE_KEY,
}
COMPANION_HEART_TRIBULATION_COMMAND = ".共历心劫"
COMPANION_HEART_TRIBULATION_ALLOWED_BOT_IDS = set()
COMPANION_HEART_TRIBULATION_STEP_TIMEOUT_SECONDS = 300
COMPANION_HEART_TRIBULATION_EDIT_STALL_SECONDS = 600
COMPANION_HEART_TRIBULATION_SETTLEMENT_KEYWORD = "【坠魔心劫·结算】"
COMPANION_HEART_TRIBULATION_ROUND1_LOCK_KEYWORD = "【坠魔心劫·第1轮已定】"
COMPANION_HEART_TRIBULATION_ROUND2_LOCK_KEYWORD = "【坠魔心劫·第2轮已定】"
COMPANION_HEART_TRIBULATION_IDLE_STATE = "idle"
COMPANION_HEART_TRIBULATION_SENDING_PANEL_STATE = "sending_panel_command"
COMPANION_HEART_TRIBULATION_AWAIT_PANEL_STATE = "await_panel_reply"
COMPANION_HEART_TRIBULATION_AWAIT_TRIBULATION_STATE = "await_tribulation_reply"
COMPANION_HEART_TRIBULATION_AWAIT_ROUND1_EDIT_STATE = "await_round1_edit"
COMPANION_HEART_TRIBULATION_AWAIT_ROUND2_EDIT_STATE = "await_round2_edit"
COMPANION_HEART_TRIBULATION_AWAIT_SETTLEMENT_STATE = "await_settlement_edit"
COMPANION_HEART_TRIBULATION_FAILED_STATE = "failed_stopped"
COMPANION_HEART_TRIBULATION_ROUND_RETRY_SECONDS = 20
COMPANION_HEART_TRIBULATION_ROUND_RETRY_MAX = 1
COMPANION_HEART_TRIBULATION_ACTIVE_STATES = {
    COMPANION_HEART_TRIBULATION_SENDING_PANEL_STATE,
    COMPANION_HEART_TRIBULATION_AWAIT_PANEL_STATE,
    COMPANION_HEART_TRIBULATION_AWAIT_TRIBULATION_STATE,
    COMPANION_HEART_TRIBULATION_AWAIT_ROUND1_EDIT_STATE,
    COMPANION_HEART_TRIBULATION_AWAIT_ROUND2_EDIT_STATE,
    COMPANION_HEART_TRIBULATION_AWAIT_SETTLEMENT_STATE,
}
COMPANION_AUTO_FEATURES = {
    pagoda_auto.FEATURE_KEY: {
        "command": "",
    },
    biz_tianji_trial_daily_auto.FEATURE_KEY: {
        "command": biz_tianji_trial_daily_auto.REMNANT_COMMAND,
    },
    biz_estate_hunt_daily_auto.FEATURE_KEY: {
        "command": biz_estate_hunt_daily_auto.COMMAND_LABEL,
    },
    biz_beast_merge_daily_auto.FEATURE_KEY: {
        "command": "",
    },
    biz_luoyun_spirit_tree_daily_auto.FEATURE_KEY: {
        "command": "",
    },
    biz_fishing_daily_auto.FEATURE_KEY: {
        "command": "",
    },
    **SIMPLE_COOLDOWN_AUTO_FEATURES,
    ARTIFACT_TOUCH_FEATURE_KEY: {
        "command": ".抚摸法宝",
        "interval_seconds": ARTIFACT_TOUCH_DEFAULT_INTERVAL_SECONDS,
    },
    ARTIFACT_TRIAL_FEATURE_KEY: {
        "command": ".器灵试炼",
    },
    ARTIFACT_NURTURE_FEATURE_KEY: {
        "command": ".温养器灵",
    },
    WANLING_ROAM_FEATURE_KEY: {
        "command": WANLING_ROAM_COMMAND,
    },
    XINGGONG_STARBOARD_FEATURE_KEY: {
        "command": ".观星台",
    },
    COMPANION_VOYAGE_FEATURE_KEY: {
        "command": ".侍妾远航",
    },
    biz_small_world_game.SMALL_WORLD_AUTO_FEATURE_KEY: {
        "command": biz_small_world_game.SMALL_WORLD_PANEL_COMMAND,
    },
    biz_small_world_game.SMALL_WORLD_PREACH_AUTO_FEATURE_KEY: {
        "command": biz_small_world_game.SMALL_WORLD_PREACH_COMMAND,
    },
    mulan_feature.MULAN_AUTO_SUPPORT_FEATURE_KEY: {
        "command": mulan_feature.MULAN_PANEL_COMMAND_TEXT,
    },
}


def get_companion_auto_task_command_prefixes(task: dict) -> tuple[str, ...]:
    feature_key = str(task.get("feature_key") or "").strip()
    commands: list[str] = []
    feature = COMPANION_AUTO_FEATURES.get(feature_key) or {}
    base_command = str(feature.get("command") or "").strip()
    if base_command:
        commands.append(base_command)

    if feature_key == biz_tianji_trial_daily_auto.FEATURE_KEY:
        commands.extend(
            [
                biz_tianji_trial_daily_auto.REMNANT_COMMAND,
                biz_tianji_trial_daily_auto.TRIAL_COMMAND,
            ]
        )
    elif feature_key == biz_estate_hunt_daily_auto.FEATURE_KEY:
        commands.append(".洞府")
    elif feature_key == ARTIFACT_TOUCH_FEATURE_KEY:
        command_text, _interval_seconds = _unpack_artifact_touch_strategy(
            task.get("strategy") or ""
        )
        commands.append(command_text)
    elif feature_key == ARTIFACT_TRIAL_FEATURE_KEY:
        artifact_name, route = _unpack_artifact_trial_strategy(
            task.get("strategy") or ""
        )
        commands.append(_build_artifact_trial_command(artifact_name, route))
    elif feature_key == ARTIFACT_NURTURE_FEATURE_KEY:
        target_name = _unpack_artifact_nurture_strategy(task.get("strategy") or "")
        commands.append(_build_artifact_nurture_command(target_name))
    elif feature_key == WANLING_ROAM_FEATURE_KEY:
        commands.extend(build_wanling_roam_cancel_commands(task.get("strategy") or ""))
    elif feature_key == XINGGONG_STARBOARD_FEATURE_KEY:
        commands.extend(
            [
                ".观星台",
                XINGGONG_STARBOARD_COMFORT_COMMAND,
                XINGGONG_STARBOARD_COLLECT_COMMAND,
                XINGGONG_STARBOARD_PULL_PREFIX,
            ]
        )
    elif feature_key == COMPANION_VOYAGE_FEATURE_KEY:
        strategy = _normalize_companion_voyage_strategy(task.get("strategy"))
        commands.extend(
            [
                COMPANION_PANEL_COMMAND,
                COMPANION_VOYAGE_STATUS_COMMAND,
                COMPANION_VOYAGE_RETURN_COMMAND,
                f".侍妾远航 {strategy}",
            ]
        )
    elif feature_key == biz_small_world_game.SMALL_WORLD_AUTO_FEATURE_KEY:
        commands.extend(
            [
                biz_small_world_game.SMALL_WORLD_PANEL_COMMAND,
                *SMALL_WORLD_ACTION_COMMANDS,
            ]
        )
    elif feature_key == biz_small_world_game.SMALL_WORLD_PREACH_AUTO_FEATURE_KEY:
        commands.append(biz_small_world_game.SMALL_WORLD_PREACH_COMMAND)
    elif feature_key == mulan_feature.MULAN_AUTO_SUPPORT_FEATURE_KEY:
        commands.extend(
            [
                mulan_feature.MULAN_PANEL_COMMAND_TEXT,
                mulan_feature.MULAN_SPY_COMMAND_TEXT,
                mulan_feature.MULAN_COLLECT_REPORT_COMMAND_TEXT,
                *mulan_feature.MULAN_VALID_SUPPORT_COMMANDS,
                mulan_feature.MULAN_VERIFY_REPORT_COMMAND_PREFIX,
                ".公开军报",
            ]
        )
        commands.extend(
            part
            for part in _mulan_workflow_parts(task.get("workflow_state"))
            if part.startswith(".")
        )
    elif feature_key == "wild_experience":
        commands.append(
            f".野外历练 {_normalize_wild_experience_strategy(task.get('strategy'))}"
        )

    return tuple(dict.fromkeys(command for command in commands if command))
def _refresh_companion_payload(storage: Storage, profile_id: int):
    from tg_game.clients.asc_client import AscAuthError
    from tg_game.services.external_sync import (
    ASC_PROVIDER,
        get_effective_external_cookie,
        mark_external_account_failure,
        sync_external_account,
    )

    external_account = storage.get_external_account(profile_id, ASC_PROVIDER) or {}
    cookie_text = (
        (external_account or {}).get("cookie_text") or get_effective_external_cookie(storage)
    ).strip()
    if not cookie_text:
        logger.warning(
            "Force refresh companion payload skipped profile=%s reason=no_cookie",
            profile_id,
        )
        return None

    try:
        return sync_external_account(storage, profile_id, cookie_text=cookie_text)
    except AscAuthError as exc:
        mark_external_account_failure(
            storage, profile_id, exc, cookie_text=cookie_text
        )
        logger.warning(
            "Force refresh companion payload auth failed profile=%s error=%s",
            profile_id,
            exc,
        )
        return None
    except Exception as exc:
        logger.warning(
            "Force refresh companion payload failed profile=%s error=%s",
            profile_id,
            exc,
        )
        return None


def _refresh_divination_payload(storage: Storage, profile_id: int):
    from tg_game.clients.asc_client import AscAuthError
    from tg_game.services.external_sync import (
    ASC_PROVIDER,
        get_effective_external_cookie,
        mark_external_account_failure,
        sync_external_account,
    )

    external_account = storage.get_external_account(profile_id, ASC_PROVIDER) or {}
    cookie_text = (
        (external_account or {}).get("cookie_text") or get_effective_external_cookie(storage)
    ).strip()
    if not cookie_text:
        logger.warning(
            "Force refresh divination payload skipped profile=%s reason=no_cookie",
            profile_id,
        )
        return None

    try:
        return sync_external_account(storage, profile_id, cookie_text=cookie_text)
    except AscAuthError as exc:
        mark_external_account_failure(
            storage, profile_id, exc, cookie_text=cookie_text
        )
        logger.warning(
            "Force refresh divination payload auth failed profile=%s error=%s",
            profile_id,
            exc,
        )
        return None
    except Exception as exc:
        logger.warning(
            "Force refresh divination payload failed profile=%s error=%s",
            profile_id,
            exc,
        )
        return None


def _binding_bot_ids(context: EventContext) -> list[int]:
    bot_ids = list(getattr(context.chat_binding, "bot_ids", None) or [])
    primary_bot_id = getattr(context.chat_binding, "bot_id", None)
    try:
        normalized_primary = int(primary_bot_id) if primary_bot_id is not None else None
    except (TypeError, ValueError):
        normalized_primary = None
    if not bot_ids and normalized_primary is not None and normalized_primary not in bot_ids:
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


def _is_context_sender_allowed_bot(context: EventContext) -> bool:
    try:
        return int(context.sender_id or 0) in _binding_bot_ids(context)
    except (TypeError, ValueError):
        return False


def _record_estate_miniapp_payload(
    context: EventContext,
    storage: Storage,
    *,
    entry: Optional[dict] = None,
    snapshot: Optional[dict] = None,
    hunt: Optional[dict] = None,
    hunt_limits: Optional[dict] = None,
) -> bool:
    if not context.profile:
        return False
    entry = entry or extract_estate_miniapp_entry(context.event, context.text)
    if not entry and not snapshot and not hunt_limits:
        return False
    external_account = storage.get_external_account(context.profile.id, ASC_PROVIDER) or {}
    try:
        payload = json.loads(external_account.get("me_json") or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    updated_payload = merge_estate_miniapp_payload(
        payload,
        entry=entry,
        snapshot=snapshot,
        hunt=hunt,
        hunt_limits=hunt_limits,
    )
    storage.upsert_external_account(
        context.profile.id,
        ASC_PROVIDER,
        str(
            external_account.get("telegram_user_id")
            or context.profile.telegram_user_id
            or ""
        ),
        str(
            external_account.get("telegram_username")
            or context.profile.telegram_username
            or ""
        ),
        str(external_account.get("status") or "connected"),
        str(external_account.get("cookie_text") or ""),
        updated_payload,
        str(external_account.get("api_token") or ""),
    )
    return True


def _save_estate_daily_payload(
    storage: Storage,
    profile_id: int,
    payload: dict,
) -> None:
    external_account = storage.get_external_account(int(profile_id), ASC_PROVIDER) or {}
    storage.upsert_external_account(
        int(profile_id),
        ASC_PROVIDER,
        str(external_account.get("telegram_user_id") or ""),
        str(external_account.get("telegram_username") or ""),
        str(external_account.get("status") or "connected"),
        str(external_account.get("cookie_text") or ""),
        payload,
        str(external_account.get("api_token") or ""),
    )


def _update_external_payload(
    storage: Storage,
    profile_id: int,
    transform: Callable[[dict], dict],
) -> dict:
    return storage.update_external_account_payload(
        int(profile_id),
        ASC_PROVIDER,
        transform,
    )


def _cancel_legacy_pagoda_outgoing(storage: Storage, profile_id: int) -> int:
    cancelled = 0
    for binding in storage.list_chat_bindings(int(profile_id)):
        cancelled += storage.cancel_pending_outgoing_commands(
            int(profile_id),
            int(binding.chat_id),
            text=pagoda_auto.COMMAND,
            thread_id=binding.thread_id,
            require_exact_thread=True,
        )
    return cancelled


def _disable_legacy_wild_experience(storage: Storage, profile_id: int) -> int:
    disabled = 0
    for task in storage.list_active_companion_auto_tasks(int(profile_id)):
        if str(task.get("feature_key") or "") != wild_experience_miniapp.FEATURE_KEY:
            continue
        storage.update_companion_auto_task(
            int(task["id"]),
            enabled=0,
            next_run_at=0,
            workflow_state="retired",
            last_error="群命令野外历练已失效，功能已迁移至“诸元神巡令”。",
        )
        for strategy in wild_experience_miniapp.STRATEGY_OPTIONS:
            storage.cancel_pending_outgoing_commands(
                int(profile_id),
                int(task.get("chat_id") or 0),
                text=f".野外历练 {strategy}",
                thread_id=task.get("thread_id"),
                require_exact_thread=True,
            )
        disabled += 1
    return disabled


async def _run_pending_wild_experience(
    client: object,
    storage: Storage,
    profile_id: int,
    payload: Optional[dict] = None,
) -> bool:
    _ = payload
    execution_owner = secrets.token_hex(16)
    current_payload = _update_external_payload(
        storage,
        int(profile_id),
        lambda latest: wild_experience_miniapp.claim_request(
            latest,
            execution_owner,
        ),
    )
    if not wild_experience_miniapp.is_request_owned(
        current_payload,
        execution_owner,
    ):
        return False
    request = wild_experience_miniapp.get_active_request(current_payload)
    current_payload = _update_external_payload(
        storage,
        int(profile_id),
        lambda latest: wild_experience_miniapp.mark_request_running(
            latest,
            execution_owner,
        ),
    )
    result = await wild_experience_miniapp.run_public_production_flow(
        client,
        discovery_storage=storage,
        strategy=request.get("strategy"),
    )
    if not result.get("ok") and result.get("status") != "retry_pending":
        logger.warning(
            "Wild experience MiniApp failed: %s",
            result.get("error"),
        )
    _update_external_payload(
        storage,
        int(profile_id),
        lambda latest: wild_experience_miniapp.finish_request(
            latest,
            result,
            execution_owner,
        ),
    )
    return True


async def _run_pending_estate_public_hunt(
    client: object,
    storage: Storage,
    profile_id: int,
    payload: Optional[dict] = None,
) -> bool:
    _ = payload
    execution_owner = secrets.token_hex(16)
    current_payload = _update_external_payload(
        storage,
        int(profile_id),
        lambda latest: estate_miniapp.claim_estate_miniapp_hunt_request(
            latest,
            execution_owner,
        ),
    )
    if not estate_miniapp.is_estate_miniapp_hunt_request_owned(
        current_payload,
        execution_owner,
    ):
        return False
    hunt_request = estate_miniapp.get_pending_estate_miniapp_hunt_request(
        current_payload
    )

    def mark_running() -> None:
        nonlocal current_payload
        current_payload = _update_external_payload(
            storage,
            int(profile_id),
            lambda latest: estate_miniapp.mark_estate_miniapp_hunt_request_status(
                latest,
                "running",
                execution_owner=execution_owner,
            ),
        )

    result = await estate_miniapp.run_estate_public_miniapp_production_hunt_flow(
        client,
        discovery_storage=storage,
        capture_source=(
            f"estate-public-hunt:{int(profile_id)}:"
            f"{int(float(hunt_request.get('requested_at') or 0))}"
        ),
        max_reveals=int(hunt_request.get("max_reveals") or 8),
        min_ap_to_settle=int(hunt_request.get("min_ap_to_settle") or 0),
        progress_callback=mark_running,
    )
    if not result.get("ok"):
        logger.warning(
            "Estate public MiniApp hunt failed: %s",
            estate_miniapp.sanitize_estate_miniapp_secret_text(result.get("error")),
        )
    snapshot = result.get("snapshot") if isinstance(result.get("snapshot"), dict) else None
    hunt = result.get("hunt") if isinstance(result.get("hunt"), dict) else None
    _update_external_payload(
        storage,
        int(profile_id),
        lambda latest: estate_miniapp.merge_estate_miniapp_payload(
            latest,
            entry=(
                result.get("entry")
                if isinstance(result.get("entry"), dict)
                else None
            ),
            snapshot=snapshot,
            hunt=hunt,
        )
        if estate_miniapp.is_estate_miniapp_hunt_request_owned(
            latest,
            execution_owner,
        )
        else latest,
    )
    return True


async def _run_pending_beast_merge_public(
    client: object,
    storage: Storage,
    profile_id: int,
    payload: Optional[dict] = None,
) -> bool:
    _ = payload
    execution_owner = secrets.token_hex(16)
    current_payload = _update_external_payload(
        storage,
        int(profile_id),
        lambda latest: biz_beast_merge_state.claim_beast_merge_request(
            latest,
            execution_owner,
        ),
    )
    if not biz_beast_merge_state.is_beast_merge_request_owned(
        current_payload,
        execution_owner,
    ):
        return False

    def save_progress(progress: dict) -> None:
        nonlocal current_payload
        current_payload = _update_external_payload(
            storage,
            int(profile_id),
            lambda latest: biz_beast_merge_state.apply_beast_merge_progress(
                latest,
                progress,
                execution_owner=execution_owner,
            ),
        )

    result = await beast_merge_miniapp.run_beast_merge_public_production_flow(
        client,
        discovery_storage=storage,
        progress_callback=save_progress,
    )
    if not result.get("ok"):
        logger.warning(
            "Beast merge public MiniApp flow failed: %s",
            beast_merge_miniapp.sanitize_beast_merge_secret_text(
                result.get("error")
            ),
        )
    _update_external_payload(
        storage,
        int(profile_id),
        lambda latest: biz_beast_merge_state.finish_beast_merge_request(
            latest,
            result,
            execution_owner=execution_owner,
        ),
    )
    return True


async def _run_pending_pagoda_public(
    client: object,
    storage: Storage,
    profile_id: int,
    payload: Optional[dict] = None,
) -> bool:
    _ = payload
    execution_owner = secrets.token_hex(16)
    current_payload = _update_external_payload(
        storage,
        int(profile_id),
        lambda latest: pagoda_state.claim_pagoda_request(
            latest,
            execution_owner,
        ),
    )
    if not pagoda_state.is_pagoda_request_owned(current_payload, execution_owner):
        return False

    def mark_running(phase: str = "start") -> None:
        nonlocal current_payload
        current_payload = _update_external_payload(
            storage,
            int(profile_id),
            lambda latest: pagoda_state.mark_pagoda_request_running(
                latest,
                execution_owner=execution_owner,
                phase=phase,
            ),
        )

    flow_task = asyncio.create_task(
        pagoda_miniapp.run_pagoda_public_production_flow(
            client,
            discovery_storage=storage,
            progress_callback=mark_running,
        )
    )
    while True:
        try:
            result = await asyncio.wait_for(
                asyncio.shield(flow_task),
                timeout=PAGODA_LEASE_RENEW_INTERVAL_SECONDS,
            )
            break
        except asyncio.TimeoutError:
            try:
                current_payload = _update_external_payload(
                    storage,
                    int(profile_id),
                    lambda latest: pagoda_state.renew_pagoda_request_lease(
                        latest,
                        execution_owner=execution_owner,
                    ),
                )
            except Exception as exc:
                logger.exception(
                    "Pagoda request lease renewal failed for profile=%s: %s",
                    profile_id,
                    exc,
                )
    if not result.get("ok"):
        logger.warning(
            "Pagoda public MiniApp flow failed: %s",
            pagoda_miniapp._safe_text(result.get("error")),
        )
    _update_external_payload(
        storage,
        int(profile_id),
        lambda latest: pagoda_state.finish_pagoda_request(
            latest,
            result,
            execution_owner=execution_owner,
        ),
    )
    return True


def _save_tianji_trial_daily_payload(
    storage: Storage,
    profile_id: int,
    payload: dict,
) -> None:
    external_account = storage.get_external_account(int(profile_id), ASC_PROVIDER) or {}
    storage.upsert_external_account(
        int(profile_id),
        ASC_PROVIDER,
        str(external_account.get("telegram_user_id") or ""),
        str(external_account.get("telegram_username") or ""),
        str(external_account.get("status") or "connected"),
        str(external_account.get("cookie_text") or ""),
        payload,
        str(external_account.get("api_token") or ""),
    )


def _save_xinggong_starboard_profile_payload(
    storage: Storage,
    profile_id: int,
    payload: dict,
) -> None:
    external_account = storage.get_external_account(int(profile_id), ASC_PROVIDER) or {}
    profile = storage.get_profile(int(profile_id))
    storage.upsert_external_account(
        int(profile_id),
        ASC_PROVIDER,
        str(
            external_account.get("telegram_user_id")
            or (profile.telegram_user_id if profile else "")
            or ""
        ),
        str(
            external_account.get("telegram_username")
            or (profile.telegram_username if profile else "")
            or ""
        ),
        str(external_account.get("status") or "connected"),
        str(external_account.get("cookie_text") or ""),
        payload,
        str(external_account.get("api_token") or ""),
    )


async def _run_pending_xinggong_public_starboard(
    client: object,
    storage: Storage,
    profile_id: int,
    payload: Optional[dict] = None,
) -> bool:
    profile = storage.get_profile(int(profile_id))
    if not profile or str(profile.sect_name or "").strip() != "星宫":
        return False
    current_payload = (
        payload
        if isinstance(payload, dict)
        else read_cached_external_payload(storage, int(profile_id))
    )
    request = xinggong_miniapp.get_pending_xinggong_starboard_request(
        current_payload
    )
    if not request:
        return False
    chat_id = int(request.get("chat_id") or 0)
    thread_id = request.get("thread_id")
    if chat_id:
        storage.cancel_pending_outgoing_commands(
            int(profile_id),
            chat_id,
            text=xinggong_miniapp.XINGGONG_STARBOARD_COMMAND,
            thread_id=int(thread_id) if thread_id else None,
            require_exact_thread=True,
        )
    snapshot_only = str(request.get("run_mode") or "auto") == "snapshot"
    result = await xinggong_miniapp.run_xinggong_starboard_public_miniapp_production_flow(
        client,
        discovery_storage=storage,
        target_star=request.get("target_star"),
        snapshot_only=snapshot_only,
    )
    if not result.get("ok"):
        logger.warning(
            "Xinggong public MiniApp flow failed: %s",
            xinggong_miniapp.sanitize_xinggong_starboard_secret_text(
                result.get("error")
            ),
        )
    updated_payload = xinggong_miniapp.merge_xinggong_starboard_payload(
        current_payload,
        entry=result.get("entry") if isinstance(result.get("entry"), dict) else None,
        star_platform=(
            result.get("star_platform")
            if isinstance(result.get("star_platform"), dict)
            else None
        ),
        run=result.get("run") if isinstance(result.get("run"), dict) else None,
        clear_request=True,
    )
    _save_xinggong_starboard_profile_payload(
        storage,
        int(profile_id),
        updated_payload,
    )
    if not snapshot_only and chat_id:
        task = storage.get_companion_auto_task(
            int(profile_id),
            chat_id,
            XINGGONG_STARBOARD_FEATURE_KEY,
        )
        if task:
            now = time.time()
            next_run_at = now + XINGGONG_STARBOARD_RECHECK_SECONDS
            if result.get("ok"):
                next_run_at = build_starboard_next_check_time(updated_payload, now)
            storage.update_companion_auto_task(
                int(task["id"]),
                last_run_at=now,
                next_run_at=next_run_at,
                last_error=(
                    ""
                    if result.get("ok")
                    else xinggong_miniapp.sanitize_xinggong_starboard_secret_text(
                        result.get("error") or "星宫 MiniApp 自动采集失败。"
                    )
                ),
            )
    return True


def _save_luoyun_spirit_tree_profile_payload(
    storage: Storage,
    profile_id: int,
    payload: dict,
) -> None:
    external_account = storage.get_external_account(int(profile_id), ASC_PROVIDER) or {}
    profile = storage.get_profile(int(profile_id))
    storage.upsert_external_account(
        int(profile_id),
        ASC_PROVIDER,
        str(
            external_account.get("telegram_user_id")
            or (profile.telegram_user_id if profile else "")
            or ""
        ),
        str(
            external_account.get("telegram_username")
            or (profile.telegram_username if profile else "")
            or ""
        ),
        str(external_account.get("status") or "connected"),
        str(external_account.get("cookie_text") or ""),
        payload,
        str(external_account.get("api_token") or ""),
    )


async def _run_pending_luoyun_spirit_tree(
    client: object,
    storage: Storage,
    profile_id: int,
    payload: Optional[dict] = None,
) -> bool:
    current_payload = (
        payload
        if isinstance(payload, dict)
        else read_cached_external_payload(storage, int(profile_id))
    )
    request = luoyun_spirit_tree_miniapp.get_pending_luoyun_spirit_tree_request(
        current_payload
    )
    if not request:
        return False
    profile = storage.get_profile(int(profile_id))
    if not biz_luoyun_spirit_tree_daily_auto.is_allowed_profile(profile):
        updated_payload = luoyun_spirit_tree_miniapp.cancel_luoyun_spirit_tree_request(
            current_payload,
            reason="当前角色已不是落云宗，已取消云梦山灵眼赛请求。",
        )
        _save_luoyun_spirit_tree_profile_payload(
            storage,
            int(profile_id),
            updated_payload,
        )
        chat_id = int(request.get("chat_id") or 0)
        if chat_id:
            storage.disable_companion_auto_task(
                int(profile_id),
                chat_id,
                biz_luoyun_spirit_tree_daily_auto.FEATURE_KEY,
                last_error="当前角色已不是落云宗，已关闭每日云梦山灵眼赛。",
            )
        return True

    result = await luoyun_spirit_tree_miniapp.run_luoyun_spirit_tree_public_production_flow(
        client,
        discovery_storage=storage,
        run_mode=request.get("run_mode"),
        pending_submission=(
            luoyun_spirit_tree_miniapp.get_pending_luoyun_spirit_tree_submission(
                current_payload
            )
        ),
    )
    now = time.time()
    chat_id = int(request.get("chat_id") or 0)
    task = (
        storage.get_companion_auto_task(
            int(profile_id),
            chat_id,
            biz_luoyun_spirit_tree_daily_auto.FEATURE_KEY,
        )
        if chat_id
        else None
    )
    retry_request = None
    if str(result.get("status") or "") == "retry_pending":
        retry_count = max(int(request.get("retry_count") or 0) + 1, 1)
        retry_delay = (
            luoyun_spirit_tree_miniapp.resolve_luoyun_spirit_tree_retry_delay(
                retry_count
            )
        )
        retry_request = luoyun_spirit_tree_miniapp.build_luoyun_spirit_tree_request(
            chat_id=request.get("chat_id"),
            thread_id=request.get("thread_id"),
            chat_type=str(request.get("chat_type") or "group"),
            bot_username=str(request.get("bot_username") or "fanrenxiuxian_bot"),
            run_mode=str(request.get("run_mode") or "daily"),
            not_before=now + retry_delay,
            retry_count=retry_count,
            day_key=str(request.get("day_key") or ""),
        )
    updated_payload = luoyun_spirit_tree_miniapp.merge_luoyun_spirit_tree_payload(
        current_payload,
        result,
        request=retry_request,
        clear_request=retry_request is None,
    )
    _save_luoyun_spirit_tree_profile_payload(
        storage,
        int(profile_id),
        updated_payload,
    )

    if task and str(result.get("failure_kind") or "") == "proof_rejected":
        storage.update_companion_auto_task(
            int(task["id"]),
            enabled=0,
            next_run_at=0,
            workflow_state="proof_rejected",
            last_error="服务端拒绝灵眼赛 proof，已关闭每日调度并保留最后机会。",
        )
    elif task and retry_request is not None:
        safe_error = (
            luoyun_spirit_tree_miniapp.sanitize_luoyun_spirit_tree_secret_text(
                result.get("error") or "云梦山灵眼赛执行失败。"
            )
        )
        retry_count = int(retry_request.get("retry_count") or 1)
        retry_delay = int(
            float(retry_request.get("not_before") or 0) - now
        )
        storage.update_companion_auto_task(
            int(task["id"]),
            next_run_at=float(retry_request.get("not_before") or 0),
            last_run_at=now,
            workflow_state="retry_wait",
            retry_count=retry_count,
            last_error=(
                f"{safe_error}；第 {retry_count} 次补跑将在 {max(retry_delay, 0)} 秒后继续。"
            ),
        )
    elif (
        task
        and str(request.get("run_mode") or "daily") == "daily"
        and luoyun_spirit_tree_miniapp.is_luoyun_spirit_tree_daily_target_reached(
            updated_payload,
            now=now,
        )
    ):
        run_time = biz_luoyun_spirit_tree_daily_auto.normalize_run_time(
            task.get("strategy")
        )
        tomorrow_run_at = biz_luoyun_spirit_tree_daily_auto.resolve_next_run_at(
            run_time,
            now=now,
            force_tomorrow=True,
        )
        storage.update_companion_auto_task(
            int(task["id"]),
            last_run_at=now,
            next_run_at=tomorrow_run_at,
            workflow_state="completed_today",
            retry_count=0,
            last_error=biz_luoyun_spirit_tree_daily_auto.COMPLETED_TODAY_ERROR,
        )
    elif task and result.get("ok"):
        storage.update_companion_auto_task(
            int(task["id"]),
            retry_count=0,
            last_error="",
        )
    elif task and not result.get("ok"):
        safe_error = (
            luoyun_spirit_tree_miniapp.sanitize_luoyun_spirit_tree_secret_text(
                result.get("error") or "云梦山灵眼赛执行失败。"
            )
        )
        fields = {"last_error": safe_error, "retry_count": 0}
        if str(request.get("run_mode") or "daily") == "daily":
            run_time = biz_luoyun_spirit_tree_daily_auto.normalize_run_time(
                task.get("strategy")
            )
            fields.update(
                {
                    "last_run_at": now,
                    "next_run_at": biz_luoyun_spirit_tree_daily_auto.resolve_next_run_at(
                        run_time,
                        now=now,
                        force_tomorrow=True,
                    ),
                    "workflow_state": "failed_today",
                }
            )
        storage.update_companion_auto_task(int(task["id"]), **fields)
    return True


def _build_tianji_trial_batch_state(
    result: dict,
    *,
    target_runs: int,
    captures: Optional[list] = None,
    previous_rounds: Optional[list] = None,
) -> tuple[list[dict], dict]:
    raw_results = result.get("round_results") if isinstance(result.get("round_results"), list) else []
    if not raw_results:
        raw_results = [result]
    existing_rounds = tianji_trial_miniapp._normalize_tianji_trial_rounds(
        previous_rounds or []
    )
    new_rounds = [
        tianji_trial_miniapp.build_tianji_trial_round(item, round_number=index)
        for index, item in enumerate(raw_results, start=len(existing_rounds) + 1)
        if isinstance(item, dict)
    ]
    rounds = tianji_trial_miniapp._normalize_tianji_trial_rounds(
        [*existing_rounds, *new_rounds]
    )
    latest_result = raw_results[-1] if raw_results and isinstance(raw_results[-1], dict) else result
    run = tianji_trial_miniapp.build_tianji_trial_batch_run(
        latest_result,
        rounds=rounds,
        target_runs=target_runs,
        captures=captures or [],
        pending_next=False,
    )
    return rounds, run


async def _run_pending_tianji_public_trial(
    client: object,
    storage: Storage,
    profile_id: int,
    payload: Optional[dict] = None,
) -> bool:
    _ = payload
    execution_owner = secrets.token_hex(16)
    current_payload = _update_external_payload(
        storage,
        int(profile_id),
        lambda latest: tianji_trial_miniapp.claim_tianji_trial_request(
            latest,
            execution_owner,
        ),
    )
    if not tianji_trial_miniapp.is_tianji_trial_request_owned(
        current_payload,
        execution_owner,
    ):
        return False
    request = tianji_trial_miniapp.get_pending_tianji_trial_request(
        current_payload
    )

    def mark_running() -> None:
        nonlocal current_payload
        current_payload = _update_external_payload(
            storage,
            int(profile_id),
            lambda latest: tianji_trial_miniapp.mark_tianji_trial_request_status(
                latest,
                "running",
                execution_owner=execution_owner,
            ),
        )

    captures: list[dict] = []
    target_runs = tianji_trial_miniapp._miniapp_int(
        request.get("target_runs"),
        tianji_trial_miniapp.TIANJI_TRIAL_DEFAULT_BATCH_RUNS,
    )
    result = await tianji_trial_miniapp.run_tianji_trial_public_miniapp_production_flow(
        client,
        discovery_storage=storage,
        capture_sink=captures,
        capture_source=(
            f"tianji-public:{int(profile_id)}:"
            f"{int(float(request.get('queued_at') or 0))}"
        ),
        target_runs=target_runs,
        progress_callback=mark_running,
    )
    if not result.get("ok"):
        logger.warning(
            "Tianji public MiniApp trial failed: %s",
            tianji_trial_miniapp.sanitize_tianji_trial_secret_text(result.get("error")),
        )
    _rounds, run = _build_tianji_trial_batch_state(
        result,
        target_runs=target_runs,
        captures=captures,
        previous_rounds=request.get("rounds"),
    )
    _update_external_payload(
        storage,
        int(profile_id),
        lambda latest: tianji_trial_miniapp.merge_tianji_trial_payload(
            latest,
            entry=(
                result.get("entry")
                if isinstance(result.get("entry"), dict)
                else None
            ),
            run=run,
            clear_request=True,
        )
        if tianji_trial_miniapp.is_tianji_trial_request_owned(
            latest,
            execution_owner,
        )
        else latest,
    )
    return True


def _is_estate_status_command(text: object) -> bool:
    command = str(text or "").strip()
    return command in {".洞府", "洞府"} or command.startswith(".洞府 ")


def _trusted_estate_parent(context: EventContext, storage: Storage) -> Optional[dict]:
    if not (context.is_bot_sender and _is_context_sender_allowed_bot(context)):
        return None
    if (
        not context.profile
        or context.chat_id is None
        or not context.reply_to_msg_id
        or not context.message_id
    ):
        return None
    parent = storage.get_bound_message(
        context.chat_id,
        int(context.reply_to_msg_id),
        context.profile.id,
    )
    if not parent or int(parent.get("is_bot") or 0):
        return None
    expected_user_id = str(
        (
            context.chat_binding.telegram_user_id
            if context.chat_binding
            else ""
        )
        or (context.profile.telegram_user_id if context.profile else "")
    ).strip()
    parent_sender_id = str(parent.get("sender_id") or "").strip()
    if expected_user_id and parent_sender_id != expected_user_id:
        return None
    if not _is_estate_status_command(parent.get("text")):
        return None
    return parent


async def _maybe_handle_estate_miniapp_snapshot(
    context: EventContext,
    storage: Storage,
) -> bool:
    if not _trusted_estate_parent(context, storage):
        return False
    launch = estate_miniapp.extract_estate_miniapp_launch(context.event, context.text)
    if not launch:
        return False
    external_account = storage.get_external_account(context.profile.id, ASC_PROVIDER) or {}
    try:
        payload = json.loads(external_account.get("me_json") or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    hunt_request = estate_miniapp.get_pending_estate_miniapp_hunt_request(payload)
    if hunt_request:
        execution_owner = secrets.token_hex(16)
        claimed_payload = _update_external_payload(
            storage,
            context.profile.id,
            lambda latest: estate_miniapp.claim_estate_miniapp_hunt_request(
                latest,
                execution_owner,
            ),
        )
        if not estate_miniapp.is_estate_miniapp_hunt_request_owned(
            claimed_payload,
            execution_owner,
        ):
            return True
        hunt_request = estate_miniapp.get_pending_estate_miniapp_hunt_request(
            claimed_payload
        )
        _update_external_payload(
            storage,
            context.profile.id,
            lambda latest: estate_miniapp.mark_estate_miniapp_hunt_request_status(
                latest,
                "running",
                execution_owner=execution_owner,
            ),
        )
        result = await estate_miniapp.run_estate_miniapp_production_hunt_flow(
            context.client,
            token=launch.get("token"),
            webview_url=launch.get("webview_url"),
            bot_username=launch.get("bot_username"),
            capture_source=f"estate-hunt:{context.profile.id}:{int(context.message_id or 0)}",
            max_reveals=int(hunt_request.get("max_reveals") or 8),
            min_ap_to_settle=int(hunt_request.get("min_ap_to_settle") or 0),
        )
        snapshot = result.get("snapshot") if result.get("snapshot") else None
        hunt = result.get("hunt") if result.get("hunt") else None
        if not result.get("ok"):
            logger.warning(
                "Estate MiniApp hunt failed: %s",
                estate_miniapp.sanitize_estate_miniapp_secret_text(result.get("error")),
            )
        _update_external_payload(
            storage,
            context.profile.id,
            lambda latest: estate_miniapp.merge_estate_miniapp_payload(
                latest,
                entry=launch.get("entry"),
                snapshot=snapshot if isinstance(snapshot, dict) else None,
                hunt=hunt if isinstance(hunt, dict) else None,
            )
            if estate_miniapp.is_estate_miniapp_hunt_request_owned(
                latest,
                execution_owner,
            )
            else latest,
        )
        return True

    result = await estate_miniapp.run_estate_miniapp_production_snapshot_flow(
        context.client,
        token=launch.get("token"),
        webview_url=launch.get("webview_url"),
        bot_username=launch.get("bot_username"),
        capture_source=f"estate:{context.profile.id}:{int(context.message_id or 0)}",
    )
    snapshot = result.get("snapshot") if result.get("ok") else None
    hunt_limits = result.get("hunt_limits") if result.get("ok") else None
    if not result.get("ok"):
        logger.warning(
            "Estate MiniApp read-only sync failed: %s",
            estate_miniapp.sanitize_estate_miniapp_secret_text(result.get("error")),
        )
    _record_estate_miniapp_payload(
        context,
        storage,
        entry=launch.get("entry"),
        snapshot=snapshot if isinstance(snapshot, dict) else None,
        hunt_limits=hunt_limits if isinstance(hunt_limits, dict) else None,
    )
    return True


def _is_xinggong_starboard_command(text: object) -> bool:
    return str(text or "").strip() == xinggong_miniapp.XINGGONG_STARBOARD_COMMAND


def _trusted_xinggong_starboard_parent(
    context: EventContext,
    storage: Storage,
) -> Optional[dict]:
    if not (context.is_bot_sender and _is_context_sender_allowed_bot(context)):
        return None
    if (
        not context.profile
        or context.chat_id is None
        or not context.reply_to_msg_id
        or not context.message_id
    ):
        return None
    parent = storage.get_bound_message(
        context.chat_id,
        int(context.reply_to_msg_id),
        context.profile.id,
    )
    if not parent or int(parent.get("is_bot") or 0):
        return None
    expected_user_id = str(
        (
            context.chat_binding.telegram_user_id
            if context.chat_binding
            else ""
        )
        or (context.profile.telegram_user_id if context.profile else "")
    ).strip()
    parent_sender_id = str(parent.get("sender_id") or "").strip()
    if expected_user_id and parent_sender_id != expected_user_id:
        return None
    if not _is_xinggong_starboard_command(parent.get("text")):
        return None
    return parent


def _xinggong_starboard_text_targets_profile(context: EventContext) -> bool:
    username = str(
        (
            getattr(context.chat_binding, "telegram_username", "")
            if context.chat_binding
            else ""
        )
        or (context.profile.telegram_username if context.profile else "")
        or ""
    ).strip().lower()
    if not username:
        return True
    return f"@{username}" in context.text.lower()


def _trusted_xinggong_starboard_pending_thread_entry(
    context: EventContext,
    storage: Storage,
    pending_request: dict,
) -> bool:
    if not pending_request:
        return False
    if not (context.is_bot_sender and _is_context_sender_allowed_bot(context)):
        return False
    if not context.profile or context.chat_id is None or not context.message_id:
        return False
    request_chat_id = pending_request.get("chat_id")
    if request_chat_id is not None and int(request_chat_id) != int(context.chat_id):
        return False
    request_thread_id = pending_request.get("thread_id")
    if request_thread_id is not None and int(request_thread_id) != int(context.thread_id or 0):
        return False
    if not xinggong_miniapp.looks_like_xinggong_starboard_prompt(context.text):
        return False
    if not _xinggong_starboard_text_targets_profile(context):
        return False
    latest_command = storage.get_latest_outgoing_command(
        int(context.chat_id),
        profile_id=int(context.profile.id),
        text=xinggong_miniapp.XINGGONG_STARBOARD_COMMAND,
        thread_id=context.thread_id,
    )
    if not latest_command:
        return False
    requested_at = float(pending_request.get("requested_at") or 0)
    latest_created_at = float(
        latest_command.get("created_at") or latest_command.get("updated_at") or 0
    )
    if requested_at and latest_created_at and latest_created_at + 2 < requested_at:
        return False
    current_message = storage.get_bound_message(
        int(context.chat_id),
        int(context.message_id),
        int(context.profile.id),
    )
    current_created_at = float((current_message or {}).get("created_at") or 0)
    if current_created_at and latest_created_at and current_created_at + 0.001 < latest_created_at:
        return False
    return True


def _load_xinggong_starboard_payload(
    context: EventContext,
    storage: Storage,
) -> tuple[dict, dict]:
    external_account = storage.get_external_account(context.profile.id, ASC_PROVIDER) or {}
    try:
        payload = json.loads(external_account.get("me_json") or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return external_account, payload


def _save_xinggong_starboard_payload(
    context: EventContext,
    storage: Storage,
    external_account: dict,
    payload: dict,
) -> None:
    storage.upsert_external_account(
        context.profile.id,
        ASC_PROVIDER,
        str(
            external_account.get("telegram_user_id")
            or context.profile.telegram_user_id
            or ""
        ),
        str(
            external_account.get("telegram_username")
            or context.profile.telegram_username
            or ""
        ),
        str(external_account.get("status") or "connected"),
        str(external_account.get("cookie_text") or ""),
        payload,
        str(external_account.get("api_token") or ""),
    )


def _build_xinggong_starboard_missing_entry_run() -> dict:
    now = time.time()
    return {
        "status": "failed",
        "level": "error",
        "message": "MiniApp 入口按钮未捕获，未发起 HTTP。",
        "target_star": "",
        "updated_at": now,
        "time_display": datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"),
        "error": "MiniApp 入口按钮未捕获，未发起 HTTP。",
        "events": [],
    }


async def _maybe_handle_xinggong_starboard_miniapp_entry(
    context: EventContext,
    storage: Storage,
) -> bool:
    external_account, payload = _load_xinggong_starboard_payload(context, storage)
    pending_request = xinggong_miniapp.get_pending_xinggong_starboard_request(payload)
    if not _trusted_xinggong_starboard_parent(
        context,
        storage,
    ) and not _trusted_xinggong_starboard_pending_thread_entry(
        context,
        storage,
        pending_request,
    ):
        return False

    launch = xinggong_miniapp.extract_xinggong_starboard_miniapp_launch(
        context.event,
        context.text,
    )
    if not launch:
        if not pending_request or not xinggong_miniapp.looks_like_xinggong_starboard_prompt(
            context.text
        ):
            return False
        updated_payload = xinggong_miniapp.merge_xinggong_starboard_payload(
            payload,
            run=_build_xinggong_starboard_missing_entry_run(),
            clear_request=True,
        )
        _save_xinggong_starboard_payload(
            context,
            storage,
            external_account,
            updated_payload,
        )
        return True

    entry = launch.get("entry") or xinggong_miniapp.extract_xinggong_starboard_miniapp_entry(
        context.event,
        context.text,
    )
    if pending_request:
        result = await xinggong_miniapp.run_xinggong_starboard_miniapp_production_flow(
            context.client,
            token=launch.get("token"),
            webview_url=launch.get("webview_url"),
            target_star=pending_request.get("target_star"),
        )
        updated_payload = xinggong_miniapp.merge_xinggong_starboard_payload(
            payload,
            entry=entry,
            star_platform=result.get("star_platform") if result.get("star_platform") else None,
            run=result.get("run"),
            clear_request=True,
        )
        _save_xinggong_starboard_payload(
            context,
            storage,
            external_account,
            updated_payload,
        )
        task = storage.get_companion_auto_task(
            context.profile.id,
            int(pending_request.get("chat_id") or context.chat_id or 0),
            XINGGONG_STARBOARD_FEATURE_KEY,
        )
        if task:
            now = time.time()
            next_run_at = now + XINGGONG_STARBOARD_RECHECK_SECONDS
            if result.get("ok"):
                next_run_at = build_starboard_next_check_time(updated_payload, now)
            storage.update_companion_auto_task(
                int(task["id"]),
                next_run_at=next_run_at,
                last_error=(
                    ""
                    if result.get("ok")
                    else xinggong_miniapp.sanitize_xinggong_starboard_secret_text(
                        result.get("error") or "星宫 MiniApp 自动采集失败。"
                    )
                ),
            )
        return True

    result = await xinggong_miniapp.run_xinggong_starboard_snapshot_production_flow(
        context.client,
        token=launch.get("token"),
        webview_url=launch.get("webview_url"),
    )
    updated_payload = xinggong_miniapp.merge_xinggong_starboard_payload(
        payload,
        entry=entry,
        star_platform=result.get("star_platform") if result.get("star_platform") else None,
        run=result.get("run"),
    )
    _save_xinggong_starboard_payload(
        context,
        storage,
        external_account,
        updated_payload,
    )
    return True


def _is_tianji_trial_command(text: object) -> bool:
    return str(text or "").strip() == tianji_trial_miniapp.TIANJI_TRIAL_COMMAND


def _trusted_tianji_trial_parent(context: EventContext, storage: Storage) -> Optional[dict]:
    if not (context.is_bot_sender and _is_context_sender_allowed_bot(context)):
        return None
    if (
        not context.profile
        or context.chat_id is None
        or not context.reply_to_msg_id
        or not context.message_id
    ):
        return None
    parent = storage.get_bound_message(
        context.chat_id,
        int(context.reply_to_msg_id),
        context.profile.id,
    )
    if not parent or int(parent.get("is_bot") or 0):
        return None
    expected_user_id = str(
        (
            context.chat_binding.telegram_user_id
            if context.chat_binding
            else ""
        )
        or (context.profile.telegram_user_id if context.profile else "")
    ).strip()
    parent_sender_id = str(parent.get("sender_id") or "").strip()
    if expected_user_id and parent_sender_id != expected_user_id:
        return None
    if not _is_tianji_trial_command(parent.get("text")):
        return None
    return parent


def _tianji_trial_text_targets_profile(context: EventContext) -> bool:
    username = str(
        (
            getattr(context.chat_binding, "telegram_username", "")
            if context.chat_binding
            else ""
        )
        or (context.profile.telegram_username if context.profile else "")
        or ""
    ).strip().lower()
    if not username:
        return True
    return f"@{username}" in context.text.lower()


def _trusted_tianji_trial_pending_thread_entry(
    context: EventContext,
    storage: Storage,
    pending_request: dict,
) -> bool:
    if not pending_request:
        return False
    if not (context.is_bot_sender and _is_context_sender_allowed_bot(context)):
        return False
    if not context.profile or context.chat_id is None or not context.message_id:
        return False
    request_chat_id = pending_request.get("chat_id")
    if request_chat_id is not None and int(request_chat_id) != int(context.chat_id):
        return False
    request_thread_id = pending_request.get("thread_id")
    if request_thread_id is not None and int(request_thread_id) != int(context.thread_id or 0):
        return False
    if not tianji_trial_miniapp.looks_like_tianji_trial_miniapp_prompt(context.text):
        return False
    if not _tianji_trial_text_targets_profile(context):
        return False
    latest_command = storage.get_latest_outgoing_command(
        int(context.chat_id),
        profile_id=int(context.profile.id),
        text=tianji_trial_miniapp.TIANJI_TRIAL_COMMAND,
        thread_id=context.thread_id,
    )
    if not latest_command:
        return False
    queued_at = float(pending_request.get("queued_at") or 0)
    latest_created_at = float(
        latest_command.get("created_at") or latest_command.get("updated_at") or 0
    )
    if queued_at and latest_created_at and latest_created_at + 2 < queued_at:
        return False
    current_message = storage.get_bound_message(
        int(context.chat_id),
        int(context.message_id),
        int(context.profile.id),
    )
    current_created_at = float((current_message or {}).get("created_at") or 0)
    if current_created_at and latest_created_at and current_created_at + 0.001 < latest_created_at:
        return False
    return True


def _load_tianji_trial_payload(context: EventContext, storage: Storage) -> tuple[dict, dict]:
    external_account = storage.get_external_account(context.profile.id, ASC_PROVIDER) or {}
    try:
        payload = json.loads(external_account.get("me_json") or "{}")
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return external_account, payload


async def _maybe_handle_tianji_trial_miniapp_entry(
    context: EventContext,
    storage: Storage,
) -> bool:
    _external_account, payload = _load_tianji_trial_payload(context, storage)
    pending_request = tianji_trial_miniapp.get_pending_tianji_trial_request(payload)
    if not _trusted_tianji_trial_parent(
        context,
        storage,
    ) and not _trusted_tianji_trial_pending_thread_entry(
        context,
        storage,
        pending_request,
    ):
        return False
    launch = tianji_trial_miniapp.extract_tianji_trial_miniapp_launch(
        context.event,
        context.text,
    )
    if not launch:
        if not pending_request or not tianji_trial_miniapp.looks_like_tianji_trial_miniapp_prompt(
            context.text
        ):
            return False
        execution_owner = secrets.token_hex(16)
        claimed_payload = _update_external_payload(
            storage,
            context.profile.id,
            lambda latest: tianji_trial_miniapp.claim_tianji_trial_request(
                latest,
                execution_owner,
            ),
        )
        if not tianji_trial_miniapp.is_tianji_trial_request_owned(
            claimed_payload,
            execution_owner,
        ):
            return True
        run = tianji_trial_miniapp.build_tianji_trial_run(
            {"ok": False, "status": "failed", "error": "MiniApp 入口按钮未捕获"},
            captures=[],
            error="MiniApp 入口按钮未捕获，未发起 HTTP。",
        )
        _update_external_payload(
            storage,
            context.profile.id,
            lambda latest: tianji_trial_miniapp.merge_tianji_trial_payload(
                latest,
                run=run,
                clear_request=True,
            )
            if tianji_trial_miniapp.is_tianji_trial_request_owned(
                latest,
                execution_owner,
            )
            else latest,
        )
        return True

    entry = launch.get("entry") or tianji_trial_miniapp.extract_tianji_trial_miniapp_entry(
        context.event,
        context.text,
    )
    if not pending_request:
        _update_external_payload(
            storage,
            context.profile.id,
            lambda latest: tianji_trial_miniapp.merge_tianji_trial_payload(
                latest,
                entry=entry,
            ),
        )
        return False

    execution_owner = secrets.token_hex(16)
    claimed_payload = _update_external_payload(
        storage,
        context.profile.id,
        lambda latest: tianji_trial_miniapp.claim_tianji_trial_request(
            latest,
            execution_owner,
        ),
    )
    if not tianji_trial_miniapp.is_tianji_trial_request_owned(
        claimed_payload,
        execution_owner,
    ):
        return True
    pending_request = tianji_trial_miniapp.get_pending_tianji_trial_request(
        claimed_payload
    )
    _update_external_payload(
        storage,
        context.profile.id,
        lambda latest: tianji_trial_miniapp.mark_tianji_trial_request_status(
            latest,
            "running",
            execution_owner=execution_owner,
        ),
    )
    captures: list[dict] = []
    result = await tianji_trial_miniapp.run_tianji_trial_miniapp_production_flow(
        context.client,
        token=launch.get("token"),
        webview_url=launch.get("webview_url"),
        capture_sink=captures,
        capture_source=f"tianji-trial:{context.profile.id}:{int(context.message_id or 0)}",
        target_runs=tianji_trial_miniapp._miniapp_int(
            pending_request.get("target_runs"),
            tianji_trial_miniapp.TIANJI_TRIAL_DEFAULT_BATCH_RUNS,
        ),
    )
    target_runs = tianji_trial_miniapp._miniapp_int(
        pending_request.get("target_runs"),
        tianji_trial_miniapp.TIANJI_TRIAL_DEFAULT_BATCH_RUNS,
    )
    target_runs = max(1, min(tianji_trial_miniapp.TIANJI_TRIAL_DEFAULT_BATCH_RUNS, target_runs))
    _rounds, run = _build_tianji_trial_batch_state(
        result,
        target_runs=target_runs,
        captures=captures,
        previous_rounds=pending_request.get("rounds"),
    )
    _update_external_payload(
        storage,
        context.profile.id,
        lambda latest: tianji_trial_miniapp.merge_tianji_trial_payload(
            latest,
            entry=entry,
            run=run,
            clear_request=True,
        )
        if tianji_trial_miniapp.is_tianji_trial_request_owned(
            latest,
            execution_owner,
        )
        else latest,
    )
    return True


def _is_edited_event(context: EventContext) -> bool:
    if context.is_outgoing:
        return False
    if getattr(context.event, "edit_date", None):
        return True
    message = getattr(context.event, "message", None)
    if message is not None and getattr(message, "edit_date", None):
        return True
    event_type = type(context.event).__name__.lower()
    return "edited" in event_type


def _get_profile_resume_until(storage: Storage, profile_id: int) -> float:
    try:
        return float(storage.get_runtime_state(telegram_resume_until_state_key(profile_id)) or 0)
    except (TypeError, ValueError):
        return 0.0


def _get_profile_resume_gap_seconds(storage: Storage, profile_id: int) -> float:
    try:
        return float(storage.get_runtime_state(telegram_resume_gap_state_key(profile_id)) or 0)
    except (TypeError, ValueError):
        return 0.0


def _has_pending_outgoing_command(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    text: str,
    thread_id: Optional[int],
) -> bool:
    return has_blocking_outgoing_command(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        text=text,
        thread_id=thread_id,
        manual_confirm_block_seconds=AUTO_COMMAND_MANUAL_CONFIRM_BLOCK_SECONDS,
        now=time.time(),
    )


def _get_fresh_tianji_daily_remnant_state(
    storage: Storage,
    profile_id: int,
    task: dict,
    *,
    started_at: float,
    now: float,
) -> tuple[dict, float]:
    chat_id = int(task.get("chat_id") or 0)
    if not chat_id:
        return {}, 0.0
    thread_id = int(task.get("thread_id")) if task.get("thread_id") else None
    profile = storage.get_profile(int(profile_id))
    command_chat = storage.get_chat_binding(int(profile_id), chat_id, thread_id)
    if not profile or not command_chat:
        return {}, 0.0
    command_sender_text = str(
        getattr(command_chat, "telegram_user_id", "")
        or getattr(profile, "telegram_user_id", "")
        or ""
    ).strip()
    command_sender_id = (
        int(command_sender_text) if command_sender_text.isdigit() else None
    )
    reply = biz_tianji_trial_remnant_state.get_latest_tianji_remnant_reply(
        storage,
        profile,
        command_chat,
        biz_tianji_trial_daily_auto.REMNANT_COMMAND,
        sender_id=command_sender_id,
        sender_username=getattr(profile, "telegram_username", "") or "",
        predicate=lambda text: str(text or "").startswith("【天机残痕】"),
    )
    if not reply:
        return {}, 0.0
    panel_ts = float(reply.get("created_at") or reply.get("updated_at") or 0)
    if panel_ts < max(float(started_at or 0) - 2, 0):
        return {}, panel_ts
    if not biz_tianji_trial_daily_auto.is_same_local_day(panel_ts, now):
        return {}, panel_ts
    return parse_tianji_remnant_panel_text(reply.get("text") or ""), panel_ts


def _queue_tianji_trial_daily_request(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    chat_type: str,
    bot_username: str,
) -> None:
    external_account = storage.get_external_account(int(profile_id), ASC_PROVIDER)
    if not external_account:
        profile = storage.get_profile(int(profile_id))
        storage.upsert_external_account(
            int(profile_id),
            ASC_PROVIDER,
            str(getattr(profile, "telegram_user_id", "") or ""),
            str(getattr(profile, "telegram_username", "") or ""),
            "connected",
            "",
            {},
            "",
        )
    storage.update_external_account_payload(
        int(profile_id),
        ASC_PROVIDER,
        lambda latest: tianji_trial_miniapp.queue_tianji_trial_request(
            latest,
            chat_id=int(chat_id),
            thread_id=thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
        ),
    )


def _has_active_companion_voyage_command(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    text: str,
    thread_id: Optional[int],
) -> bool:
    latest_command = storage.get_latest_outgoing_command(
        chat_id,
        profile_id=profile_id,
        text=text,
        thread_id=thread_id,
    )
    if not latest_command:
        return False
    return (
        str(latest_command.get("status") or "").strip()
        in COMPANION_VOYAGE_ACTIVE_COMMAND_STATUSES
    )


def _queue_companion_command(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    text: str,
    thread_id: Optional[int],
    chat_type: str,
    bot_username: str,
    reply_to_msg_id: Optional[int] = None,
) -> None:
    storage.enqueue_outgoing_command(
        profile_id=profile_id,
        chat_id=chat_id,
        text=text,
        thread_id=thread_id,
        reply_to_msg_id=reply_to_msg_id,
        chat_type=chat_type,
        bot_username=bot_username,
    )


def _is_allowed_companion_heart_tribulation_bot_id(sender_id: object) -> bool:
    return False


def _normalize_companion_heart_tribulation_action(value: object) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized in {"稳", "狠", "骗"} else "稳"


def _normalize_companion_voyage_strategy(value: object) -> str:
    return normalize_companion_voyage_strategy(value)


def _parse_chinese_duration_seconds(text: str) -> int:
    return parse_chinese_duration_seconds(text)


def _build_companion_voyage_state_from_reply(reply: Optional[dict]) -> dict:
    return build_companion_voyage_state_from_reply(reply)


def _is_companion_panel_text(text: str) -> bool:
    return is_companion_panel_text(text)


def _is_profile_command_reply(
    storage: Storage,
    *,
    message: dict,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    command_texts: set[str],
) -> bool:
    reply_to_msg_id = int((message or {}).get("reply_to_msg_id") or 0)
    if reply_to_msg_id <= 0:
        return False
    parent = storage.get_bound_message(chat_id, reply_to_msg_id, profile_id)
    if not parent or int(parent.get("is_bot") or 0):
        return False
    if str(parent.get("direction") or "").strip() != "outgoing":
        return False
    if thread_id and int(parent.get("thread_id") or 0) not in {int(thread_id)}:
        return False
    parent_text = str(parent.get("text") or "").strip()
    if parent_text in command_texts:
        return True
    return parent_text == ".侍妾远航" or parent_text.startswith(".侍妾远航 ")


def _get_latest_companion_panel_message(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
) -> Optional[dict]:
    profile = storage.get_profile(profile_id)
    sender_text = str(getattr(profile, "telegram_user_id", "") or "").strip()
    sender_username = str(getattr(profile, "telegram_username", "") or "").strip()
    command_reply = storage.get_latest_bot_reply_for_command(
        chat_id,
        COMPANION_PANEL_COMMAND,
        profile_id=profile_id,
        thread_id=thread_id,
        sender_id=int(sender_text) if sender_text.isdigit() else None,
        sender_username=sender_username,
    )
    if command_reply and not _is_profile_command_reply(
        storage,
        message=command_reply,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        command_texts={COMPANION_PANEL_COMMAND},
    ):
        command_reply = None
    panel_message = None
    messages = storage.list_bound_messages(
        profile_id=profile_id,
        chat_id=chat_id,
        search_query="侍妾",
        limit=80,
    )
    for message in messages:
        if not int(message.get("is_bot") or 0):
            continue
        if thread_id and int(message.get("thread_id") or 0) not in {int(thread_id)}:
            continue
        if not _is_profile_command_reply(
            storage,
            message=message,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            command_texts={COMPANION_PANEL_COMMAND},
        ):
            continue
        if _is_companion_panel_text(str(message.get("text") or "")):
            panel_message = message
            break
    if command_reply and _is_companion_panel_text(str(command_reply.get("text") or "")):
        if not panel_message:
            return command_reply
        command_ts = float(command_reply.get("created_at") or 0)
        panel_ts = float(panel_message.get("created_at") or 0)
        return command_reply if command_ts > panel_ts else panel_message
    return panel_message


def _get_latest_profile_command_reply(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    command_text: str,
    since_ts: float = 0,
) -> Optional[dict]:
    profile = storage.get_profile(profile_id)
    sender_text = str(getattr(profile, "telegram_user_id", "") or "").strip()
    sender_username = str(getattr(profile, "telegram_username", "") or "").strip()
    reply = storage.get_latest_bot_reply_for_command(
        chat_id,
        command_text,
        profile_id=profile_id,
        thread_id=thread_id,
        sender_id=int(sender_text) if sender_text.isdigit() else None,
        sender_username=sender_username,
    )
    if not reply:
        return None
    if float(reply.get("created_at") or 0) < float(since_ts or 0):
        return None
    if not _is_profile_command_reply(
        storage,
        message=reply,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        command_texts={command_text},
    ):
        return None
    return reply


def _resolve_small_world_preach_cooldown_until(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
) -> float:
    reply = _get_latest_profile_command_reply(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        command_text=biz_small_world_game.SMALL_WORLD_PREACH_COMMAND,
    )
    if not reply:
        return 0.0
    cooldown_seconds = biz_small_world_game.parse_miracle_preach_cooldown_seconds(
        str(reply.get("text") or "")
    )
    if cooldown_seconds <= 0:
        return 0.0
    return float(reply.get("created_at") or 0) + cooldown_seconds


def _is_recent_companion_panel_message(panel_reply: Optional[dict], now: float) -> bool:
    if not panel_reply:
        return False
    created_at = float(panel_reply.get("created_at") or 0)
    if created_at <= 0:
        return False
    return (now - created_at) <= COMPANION_PANEL_FRESH_SECONDS


def _queue_companion_panel_refresh_if_needed(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    chat_type: str,
    bot_username: str,
    now: float,
) -> tuple[Optional[dict], bool]:
    panel_reply = _get_latest_companion_panel_message(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
    )
    if _is_recent_companion_panel_message(panel_reply, now):
        return panel_reply, False
    if not _is_recent_or_pending_outgoing_command(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        text=COMPANION_PANEL_COMMAND,
        thread_id=thread_id,
        now=now,
        recent_seconds=COMPANION_VOYAGE_RECHECK_SECONDS,
    ):
        storage.enqueue_outgoing_command(
            profile_id=profile_id,
            chat_id=chat_id,
            text=COMPANION_PANEL_COMMAND,
            thread_id=thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
        )
    return panel_reply, True


def _resolve_companion_panel_cooldown_target(
    panel_reply: Optional[dict],
    feature_key: str,
) -> Optional[float]:
    label = COMPANION_PANEL_COOLDOWN_LABELS.get(feature_key, "")
    if not label:
        return None
    text = str((panel_reply or {}).get("text") or "").strip()
    if not text:
        return None
    match = re.search(rf"{re.escape(label)}冷却\s*[:：]\s*([^\n\r]+)", text)
    if not match:
        return None
    value = match.group(1).strip()
    if "可施展" in value:
        return 0.0
    remaining_seconds = _parse_chinese_duration_seconds(value)
    created_at = float((panel_reply or {}).get("created_at") or 0)
    if remaining_seconds <= 0 or created_at <= 0:
        return None
    return created_at + remaining_seconds


def _is_companion_voyage_state_text(text: str) -> bool:
    normalized = str(text or "").strip()
    return (
        "远航状态:" in normalized
        or "预计归航还需" in normalized
        or "仍在远航中" in normalized
        or "远航途中" in normalized
        or "正在执行" in normalized and "远航" in normalized
        or "已归航" in normalized and "远航归来" in normalized
        or "尚未结算" in normalized and "远航归来" in normalized
        or "当前并未执行远航任务" in normalized
        or "并无可结算的远航任务" in normalized
        or "当前并未随行" in normalized
        or "无法探查远航状态" in normalized
    )


def _get_latest_companion_voyage_state_message(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
) -> Optional[dict]:
    messages = storage.list_bound_messages(
        profile_id=profile_id,
        chat_id=chat_id,
        search_query="远航",
        limit=120,
    )
    for message in messages:
        if not int(message.get("is_bot") or 0):
            continue
        if thread_id and int(message.get("thread_id") or 0) not in {int(thread_id)}:
            continue
        if not _is_profile_command_reply(
            storage,
            message=message,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            command_texts={
                COMPANION_PANEL_COMMAND,
                COMPANION_VOYAGE_STATUS_COMMAND,
                COMPANION_VOYAGE_RETURN_COMMAND,
            },
        ):
            continue
        if _is_companion_voyage_state_text(str(message.get("text") or "")):
            return message
    return None


def _get_latest_companion_voyage_reply(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
) -> Optional[dict]:
    profile = storage.get_profile(profile_id)
    sender_text = str(getattr(profile, "telegram_user_id", "") or "").strip()
    sender_username = str(getattr(profile, "telegram_username", "") or "").strip()
    command_reply = storage.get_latest_bot_reply_for_command(
        chat_id,
        COMPANION_VOYAGE_STATUS_COMMAND,
        profile_id=profile_id,
        thread_id=thread_id,
        sender_id=int(sender_text) if sender_text.isdigit() else None,
        sender_username=sender_username,
    )
    if command_reply and not _is_profile_command_reply(
        storage,
        message=command_reply,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        command_texts={COMPANION_VOYAGE_STATUS_COMMAND},
    ):
        command_reply = None
    state_reply = _get_latest_companion_voyage_state_message(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
    )
    if not command_reply:
        return state_reply
    if not state_reply:
        return command_reply
    command_ts = float(command_reply.get("created_at") or 0)
    state_ts = float(state_reply.get("created_at") or 0)
    return state_reply if state_ts > command_ts else command_reply


def _is_recent_or_pending_outgoing_command(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    text: str,
    thread_id: Optional[int],
    now: float,
    recent_seconds: int = COMPANION_VOYAGE_PREFLIGHT_RECENT_SEND_SECONDS,
) -> bool:
    latest_command = storage.get_latest_outgoing_command(
        chat_id,
        profile_id=profile_id,
        text=text,
        thread_id=thread_id,
    )
    if not latest_command:
        return False
    status = str(latest_command.get("status") or "").strip()
    if _has_pending_outgoing_command(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        text=text,
        thread_id=thread_id,
    ):
        return True
    updated_at = float(latest_command.get("updated_at") or 0)
    return (
        status in OUTGOING_CONFIRMED_STATUSES
        and updated_at > 0
        and (now - updated_at) < recent_seconds
    )


def _resolve_active_companion_voyage_target(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    now: float,
) -> float:
    voyage_reply = _get_latest_companion_voyage_reply(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
    )
    voyage_state = _build_companion_voyage_state_from_reply(voyage_reply)
    voyage_target = float(voyage_state.get("target_ts") or 0)
    voyage_status = str(voyage_state.get("status") or "")
    if voyage_target > now:
        return voyage_target
    if voyage_status == "voyaging":
        panel_reply = _get_latest_companion_panel_message(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
        )
        panel_state = _build_companion_voyage_state_from_reply(panel_reply)
        panel_target = float(panel_state.get("target_ts") or 0)
        if panel_target > now:
            return panel_target
        return now + COMPANION_VOYAGE_RECHECK_SECONDS
    return 0.0


def _is_companion_heart_tribulation_active(task: Optional[dict]) -> bool:
    if not task or not bool(task.get("enabled")):
        return False
    workflow_state = str(task.get("workflow_state") or "").strip()
    return workflow_state in COMPANION_HEART_TRIBULATION_ACTIVE_STATES


def _run_companion_voyage_preflight(
    storage: Storage,
    *,
    payload: dict,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    chat_type: str,
    bot_username: str,
    now: float,
) -> tuple[bool, str, Optional[float]]:
    panel_reply = _get_latest_companion_panel_message(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
    )
    for feature_key in COMPANION_VOYAGE_PREFLIGHT_SIMPLE_FEATURES:
        resolved_next_run_at = _resolve_companion_next_run_at(payload, feature_key)
        if resolved_next_run_at is None:
            resolved_next_run_at = _resolve_companion_panel_cooldown_target(
                panel_reply,
                feature_key,
            )
        if resolved_next_run_at is None:
            label = COMPANION_PANEL_COOLDOWN_LABELS.get(feature_key, feature_key)
            return (
                False,
                f"缺少{label}冷却状态，等待侍妾面板刷新。",
                now + COMPANION_VOYAGE_RECHECK_SECONDS,
            )
        if resolved_next_run_at > now:
            continue
        command_text = str(
            (COMPANION_AUTO_FEATURES.get(feature_key) or {}).get("command") or ""
        ).strip()
        if not command_text:
            continue
        if _is_recent_or_pending_outgoing_command(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            text=command_text,
            thread_id=thread_id,
            now=now,
        ):
            continue
        storage.enqueue_outgoing_command(
            profile_id=profile_id,
            chat_id=chat_id,
            text=command_text,
            thread_id=thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
        )
        label = str(
            (COMPANION_AUTO_FEATURES.get(feature_key) or {}).get("command")
            or feature_key
        )
        return (
            False,
            f"已发送远航前置：{label}，等待侍妾面板刷新。",
            now + COMPANION_VOYAGE_RECHECK_SECONDS,
        )

    heart_task = storage.get_companion_heart_tribulation_task(
        profile_id,
        chat_id,
        thread_id=thread_id,
    )
    if _is_companion_heart_tribulation_active(heart_task):
        task_next_run_at = float((heart_task or {}).get("next_run_at") or 0)
        return (
            False,
            "等待自动共历心劫完成后远航。",
            task_next_run_at
            if task_next_run_at > now
            else now + COMPANION_VOYAGE_RECHECK_SECONDS,
        )
    if not (heart_task and bool(heart_task.get("enabled"))):
        return True, "", None

    heart_next_run_at = _resolve_companion_heart_tribulation_next_run_at(payload)
    if heart_next_run_at is None:
        heart_next_run_at = _resolve_companion_panel_cooldown_target(
            panel_reply,
            "heart_tribulation",
        )
    if heart_next_run_at is None:
        return (
            False,
            "缺少共历心劫冷却状态，等待侍妾面板刷新。",
            now + COMPANION_VOYAGE_RECHECK_SECONDS,
        )
    if heart_next_run_at > now:
        return True, "", None

    if (
        heart_task
        and bool(heart_task.get("enabled"))
        and float(heart_task.get("last_run_at") or 0) > 0
    ):
        last_run_at = float(heart_task.get("last_run_at") or 0)
        if (now - last_run_at) < COMPANION_VOYAGE_PREFLIGHT_RECENT_SEND_SECONDS:
            return (
                False,
                "已触发自动共历心劫，等待刷新。",
                now + COMPANION_VOYAGE_RECHECK_SECONDS,
            )

    storage.upsert_companion_heart_tribulation_task(
        profile_id=profile_id,
        chat_id=chat_id,
        enabled=True,
        thread_id=thread_id,
        chat_type=chat_type,
        bot_username=bot_username,
        run_id="",
        workflow_state=COMPANION_HEART_TRIBULATION_IDLE_STATE,
        next_run_at=now,
        step_deadline_at=0,
        last_run_at=0,
        matched_bot_id=0,
        anchor_command_msg_id=0,
        anchor_bot_msg_id=0,
        tribulation_command_msg_id=0,
        tribulation_msg_id=0,
        panel_reply_msg_id=0,
        round1_reply=_normalize_companion_heart_tribulation_action(
            (heart_task or {}).get("round1_reply")
        ),
        round2_reply=_normalize_companion_heart_tribulation_action(
            (heart_task or {}).get("round2_reply")
        ),
        round3_reply=_normalize_companion_heart_tribulation_action(
            (heart_task or {}).get("round3_reply")
        ),
        last_action_round_sent=0,
        last_tribulation_command_at=0,
        last_progress_at=0,
        last_progress_fingerprint="",
        last_stable_sent_at=0,
        last_error="",
        retry_count=0,
    )
    return (
        False,
        "已启动远航前置：自动共历心劫。",
        now + COMPANION_VOYAGE_RECHECK_SECONDS,
    )


def _resolve_companion_heart_tribulation_next_run_at(payload: dict) -> Optional[float]:
    companion_payload = payload.get("companion") or {}
    if not isinstance(companion_payload, dict):
        companion_payload = {}
    dongfu = payload.get("dongfu") or {}
    if isinstance(dongfu, str):
        try:
            dongfu = json.loads(dongfu)
        except Exception:
            dongfu = {}
    companion_residence = {}
    if isinstance(dongfu, dict):
        companion_residence = dongfu.get("companion_residence") or {}
        if isinstance(companion_residence, str):
            try:
                companion_residence = json.loads(companion_residence)
            except Exception:
                companion_residence = {}
    if not isinstance(companion_residence, dict):
        companion_residence = {}
    raw_value = companion_payload.get("last_companion_heart_tribulation_time")
    if raw_value is None:
        raw_value = companion_residence.get("last_companion_heart_tribulation_time")
    last_ts = _parse_iso_to_ts(raw_value)
    if last_ts <= 0:
        return None
    return last_ts + 10 * 3600


def _build_companion_heart_tribulation_action_command(task: dict, round_number: int) -> str:
    normalized_round = max(int(round_number or 1), 1)
    if normalized_round <= 1:
        action = _normalize_companion_heart_tribulation_action(task.get("round1_reply"))
    elif normalized_round == 2:
        action = _normalize_companion_heart_tribulation_action(task.get("round2_reply"))
    else:
        action = _normalize_companion_heart_tribulation_action(task.get("round3_reply"))
    return f".{action}"


def _build_companion_heart_tribulation_event_fingerprint(
    *,
    message_id: int,
    text: str,
    event_kind: str,
) -> str:
    return f"{event_kind}:{int(message_id or 0)}:{str(text or '').strip()[:900]}"


def _append_companion_heart_tribulation_log(
    storage: Storage,
    task: dict,
    *,
    step: str,
    event_type: str,
    message_id: int = 0,
    reply_to_msg_id: int = 0,
    sender_id: int = 0,
    sender_username: str = "",
    text: str = "",
    detail: Optional[dict] = None,
) -> None:
    storage.append_companion_heart_tribulation_log(
        profile_id=int(task.get("profile_id") or 0),
        chat_id=int(task.get("chat_id") or 0),
        thread_id=int(task.get("thread_id")) if task.get("thread_id") else None,
        task_id=int(task.get("id") or 0),
        run_id=str(task.get("run_id") or ""),
        step=step,
        event_type=event_type,
        message_id=int(message_id or 0),
        reply_to_msg_id=int(reply_to_msg_id or 0),
        sender_id=int(sender_id or 0),
        sender_username=sender_username,
        text=text,
        detail=detail or {},
    )


def _stop_companion_heart_tribulation_task(
    storage: Storage,
    task: dict,
    *,
    last_error: str,
    step: str,
    detail: Optional[dict] = None,
) -> Optional[dict]:
    _append_companion_heart_tribulation_log(
        storage,
        task,
        step=step,
        event_type="failed_stop",
        text=last_error,
        detail=detail or {},
    )
    profile_id = int(task.get("profile_id") or 0)
    chat_id = int(task.get("chat_id") or 0)
    if profile_id and chat_id:
        task_thread_id = int(task.get("thread_id")) if task.get("thread_id") else None
        for command_text in [
            COMPANION_PANEL_COMMAND,
            COMPANION_HEART_TRIBULATION_COMMAND,
            ".稳",
            ".狠",
            ".骗",
        ]:
            storage.cancel_pending_outgoing_commands(
                profile_id,
                chat_id,
                text=command_text,
                thread_id=task_thread_id,
                require_exact_thread=True,
            )
    updated_task = storage.disable_companion_heart_tribulation_task(
        profile_id,
        chat_id,
        thread_id=int(task.get("thread_id")) if task.get("thread_id") else None,
        last_error=last_error,
    )
    if updated_task:
        storage.update_companion_heart_tribulation_task(
            int(updated_task.get("id") or 0),
            workflow_state=COMPANION_HEART_TRIBULATION_FAILED_STATE,
        )
        return storage.get_companion_heart_tribulation_task(
            profile_id,
            chat_id,
            thread_id=int(task.get("thread_id")) if task.get("thread_id") else None,
        )
    return updated_task


def _defer_companion_heart_tribulation_if_voyaging(
    storage: Storage,
    task: dict,
    *,
    text: str,
    now: float,
    step: str,
) -> bool:
    profile_id = int(task.get("profile_id") or 0)
    chat_id = int(task.get("chat_id") or 0)
    thread_id = int(task.get("thread_id")) if task.get("thread_id") else None
    if not profile_id or not chat_id:
        return False
    state = _build_companion_voyage_state_from_reply(
        {"text": text, "created_at": now}
    )
    voyage_status = str(state.get("status") or "")
    voyage_target = float(state.get("target_ts") or 0)
    if voyage_target <= now and voyage_status == "voyaging":
        voyage_target = _resolve_active_companion_voyage_target(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            now=now,
        )
    if voyage_target <= now and voyage_status == "voyaging":
        voyage_target = now + COMPANION_VOYAGE_RECHECK_SECONDS
    if voyage_target <= now:
        return False

    updated_task = storage.update_companion_heart_tribulation_task(
        int(task.get("id") or 0),
        workflow_state=COMPANION_HEART_TRIBULATION_IDLE_STATE,
        next_run_at=voyage_target + 10,
        step_deadline_at=0,
        matched_bot_id=0,
        anchor_command_msg_id=0,
        anchor_bot_msg_id=0,
        tribulation_command_msg_id=0,
        tribulation_msg_id=0,
        panel_reply_msg_id=0,
        last_action_round_sent=0,
        last_tribulation_command_at=0,
        last_progress_at=0,
        last_progress_fingerprint="",
        last_stable_sent_at=0,
        last_error="侍妾远航中，归航后再执行自动共历心劫。",
    )
    _append_companion_heart_tribulation_log(
        storage,
        updated_task or task,
        step=step,
        event_type="defer_for_voyage",
        text=text,
        detail={"voyage_target": voyage_target},
    )
    return True


async def _send_companion_heart_tribulation_command(
    client: object,
    storage: Storage,
    task: dict,
    *,
    text: str,
    reply_to_msg_id: Optional[int] = None,
) -> object:
    chat_id = int(task.get("chat_id") or 0)
    if not chat_id:
        raise RuntimeError("Heart tribulation chat_id missing")
    return await send_message_with_thread_fallback(
        client,
        chat_id,
        text,
        thread_id=(
            int(reply_to_msg_id)
            if reply_to_msg_id is not None
            else int(task.get("thread_id"))
            if task.get("thread_id")
            else None
        ),
        storage=storage,
        profile_id=int(task.get("profile_id") or 0),
        bot_username=str(task.get("bot_username") or ""),
        log_prefix="Heart tribulation",
        guard_network_pause=True,
    )


async def _poll_companion_heart_tribulation_message(
    client: object,
    storage: Storage,
    task: dict,
) -> bool:
    workflow_state = str(task.get("workflow_state") or "").strip()
    if workflow_state not in {
        COMPANION_HEART_TRIBULATION_AWAIT_ROUND1_EDIT_STATE,
        COMPANION_HEART_TRIBULATION_AWAIT_ROUND2_EDIT_STATE,
        COMPANION_HEART_TRIBULATION_AWAIT_SETTLEMENT_STATE,
    }:
        return False
    task_id = int(task.get("id") or 0)
    profile_id = int(task.get("profile_id") or 0)
    chat_id = int(task.get("chat_id") or 0)
    thread_id = int(task.get("thread_id")) if task.get("thread_id") else None
    tribulation_msg_id = int(task.get("tribulation_msg_id") or 0)
    if not task_id or not profile_id or not chat_id or tribulation_msg_id <= 0:
        return False

    try:
        message = await client.get_messages(chat_id, ids=tribulation_msg_id)
    except Exception as exc:
        _append_companion_heart_tribulation_log(
            storage,
            task,
            step=workflow_state,
            event_type="poll_message_failed",
            message_id=tribulation_msg_id,
            detail={"error": str(exc)},
        )
        return False
    if not message:
        return False
    current_text = (
        getattr(message, "raw_text", "") or getattr(message, "text", "") or ""
    ).strip()
    if not current_text:
        return False

    last_fingerprint = str(task.get("last_progress_fingerprint") or "")
    if any(
        _build_companion_heart_tribulation_event_fingerprint(
            message_id=tribulation_msg_id,
            text=current_text,
            event_kind=kind,
        )
        == last_fingerprint
        for kind in {"tribulation_reply", "edited", "polled_edit"}
    ):
        return False

    sender_id = int(getattr(message, "sender_id", None) or task.get("matched_bot_id") or 0)
    if sender_id:
        allowed_bot_ids = storage.get_chat_binding_bot_ids(
            profile_id, chat_id, thread_id=thread_id
        )
        if sender_id not in allowed_bot_ids:
            return False
    sender_username = ""
    try:
        sender = await message.get_sender()
        sender_username = (getattr(sender, "username", "") or "").strip()
    except Exception:
        existing_message = storage.get_bound_message(
            chat_id, tribulation_msg_id, profile_id=profile_id
        )
        sender_username = str((existing_message or {}).get("sender_username") or "")

    current_fingerprint = _build_companion_heart_tribulation_event_fingerprint(
        message_id=tribulation_msg_id,
        text=current_text,
        event_kind="polled_edit",
    )
    storage.upsert_bound_message(
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        message_id=tribulation_msg_id,
        reply_to_msg_id=int(task.get("tribulation_command_msg_id") or 0),
        sender_id=sender_id,
        sender_username=sender_username,
        direction="incoming",
        is_bot=True,
        text=current_text,
    )
    _append_companion_heart_tribulation_log(
        storage,
        task,
        step=workflow_state,
        event_type="message_polled_edited",
        message_id=tribulation_msg_id,
        reply_to_msg_id=int(task.get("tribulation_command_msg_id") or 0),
        sender_id=sender_id,
        sender_username=sender_username,
        text=current_text,
    )
    storage.update_companion_heart_tribulation_task(
        task_id,
        step_deadline_at=time.time() + COMPANION_HEART_TRIBULATION_EDIT_STALL_SECONDS,
        last_progress_at=time.time(),
        last_progress_fingerprint=current_fingerprint,
    )
    task = storage.get_companion_heart_tribulation_task(
        profile_id,
        chat_id,
        thread_id=thread_id,
    ) or task

    if COMPANION_HEART_TRIBULATION_SETTLEMENT_KEYWORD in current_text:
        previous_settlement_text = str(task.get("last_settlement_text") or "")
        previous_settlement_at = float(task.get("last_settlement_at") or 0)
        updated_task = storage.update_companion_heart_tribulation_task(
            task_id,
            workflow_state=COMPANION_HEART_TRIBULATION_IDLE_STATE,
            step_deadline_at=0,
            matched_bot_id=0,
            anchor_command_msg_id=0,
            anchor_bot_msg_id=0,
            tribulation_command_msg_id=0,
            tribulation_msg_id=0,
            panel_reply_msg_id=0,
            last_action_round_sent=0,
            last_tribulation_command_at=0,
            last_progress_at=time.time(),
            last_progress_fingerprint=current_fingerprint,
            last_stable_sent_at=0,
            last_settlement_text=current_text,
            last_settlement_at=time.time(),
            previous_settlement_text=previous_settlement_text,
            previous_settlement_at=previous_settlement_at,
            last_error="",
        )
        _append_companion_heart_tribulation_log(
            storage,
            updated_task or task,
            step="completed",
            event_type="settlement_recorded",
            message_id=tribulation_msg_id,
            sender_id=sender_id,
            sender_username=sender_username,
            text=current_text,
            detail={"source": "poll"},
        )
        return True

    if workflow_state == COMPANION_HEART_TRIBULATION_AWAIT_ROUND1_EDIT_STATE:
        if COMPANION_HEART_TRIBULATION_ROUND1_LOCK_KEYWORD not in current_text:
            return True
        next_state = COMPANION_HEART_TRIBULATION_AWAIT_ROUND2_EDIT_STATE
        next_round = 2
    elif workflow_state == COMPANION_HEART_TRIBULATION_AWAIT_ROUND2_EDIT_STATE:
        if COMPANION_HEART_TRIBULATION_ROUND2_LOCK_KEYWORD not in current_text:
            return True
        next_state = COMPANION_HEART_TRIBULATION_AWAIT_SETTLEMENT_STATE
        next_round = 3
    else:
        return True

    command = _build_companion_heart_tribulation_action_command(task, next_round)
    try:
        action_message = await _send_companion_heart_tribulation_command(
            client,
            storage,
            task,
            text=command,
            reply_to_msg_id=tribulation_msg_id,
        )
    except Exception as exc:
        _stop_companion_heart_tribulation_task(
            storage,
            task,
            last_error=f"发送第{next_round}轮心劫策略失败，已停止自动共历心劫。",
            step=f"send_round{next_round}",
            detail={"error": str(exc), "command": command, "source": "poll"},
        )
        return True

    storage.update_companion_heart_tribulation_task(
        task_id,
        workflow_state=next_state,
        step_deadline_at=time.time() + COMPANION_HEART_TRIBULATION_EDIT_STALL_SECONDS,
        last_action_round_sent=next_round,
        last_progress_at=time.time(),
        last_progress_fingerprint=current_fingerprint,
        last_stable_sent_at=time.time(),
        round_retry_count=0,
        round_retry_deadline_at=time.time() + COMPANION_HEART_TRIBULATION_ROUND_RETRY_SECONDS,
        last_error="",
    )
    updated_task = storage.get_companion_heart_tribulation_task(
        profile_id,
        chat_id,
        thread_id=thread_id,
    ) or task
    _append_companion_heart_tribulation_log(
        storage,
        updated_task,
        step=next_state,
        event_type=f"send_round{next_round}",
        message_id=int(getattr(action_message, "id", 0) or 0),
        reply_to_msg_id=tribulation_msg_id,
        text=command,
        detail={"source": "poll"},
    )
    return True


async def _run_companion_heart_tribulation_scheduler(
    client: object, storage: Storage
) -> None:
    profile_id = getattr(client, "_tg_game_profile_id", None)
    if not profile_id:
        return

    while True:
        try:
            if profile_rebirth.is_profile_rebirth_locked(storage, int(profile_id)):
                await asyncio.sleep(COMPANION_HEART_TRIBULATION_EMPTY_SLEEP_SECONDS)
                continue
            tasks = storage.list_active_companion_heart_tribulation_tasks(int(profile_id))
            now = time.time()
            if not tasks:
                await asyncio.sleep(COMPANION_HEART_TRIBULATION_EMPTY_SLEEP_SECONDS)
                continue

            has_active_workflow = False
            earliest_idle_next_run_at: Optional[float] = None

            for task in tasks:
                task_id = int(task.get("id") or 0)
                if not task_id:
                    continue
                workflow_state = str(task.get("workflow_state") or "").strip()
                next_run_at = float(task.get("next_run_at") or 0)
                step_deadline_at = float(task.get("step_deadline_at") or 0)

                if workflow_state == COMPANION_HEART_TRIBULATION_FAILED_STATE:
                    continue

                if workflow_state in COMPANION_HEART_TRIBULATION_ACTIVE_STATES:
                    has_active_workflow = True

                if workflow_state in {
                    COMPANION_HEART_TRIBULATION_SENDING_PANEL_STATE,
                    COMPANION_HEART_TRIBULATION_AWAIT_PANEL_STATE,
                    COMPANION_HEART_TRIBULATION_AWAIT_TRIBULATION_STATE,
                }:
                    if step_deadline_at > 0 and now >= step_deadline_at:
                        _stop_companion_heart_tribulation_task(
                            storage,
                            task,
                            last_error="自动共历心劫等待超时，已停止自动。",
                            step=workflow_state,
                            detail={
                                "step_deadline_at": step_deadline_at,
                                "now": now,
                            },
                        )
                    continue

                if workflow_state in {
                    COMPANION_HEART_TRIBULATION_AWAIT_ROUND1_EDIT_STATE,
                    COMPANION_HEART_TRIBULATION_AWAIT_ROUND2_EDIT_STATE,
                    COMPANION_HEART_TRIBULATION_AWAIT_SETTLEMENT_STATE,
                }:
                    if await _poll_companion_heart_tribulation_message(client, storage, task):
                        continue
                    round_retry_deadline_at = float(task.get("round_retry_deadline_at") or 0)
                    round_retry_count = int(task.get("round_retry_count") or 0)
                    if round_retry_deadline_at > 0 and now >= round_retry_deadline_at:
                        if round_retry_count < COMPANION_HEART_TRIBULATION_ROUND_RETRY_MAX:
                            round_map = {
                                COMPANION_HEART_TRIBULATION_AWAIT_ROUND1_EDIT_STATE: 1,
                                COMPANION_HEART_TRIBULATION_AWAIT_ROUND2_EDIT_STATE: 2,
                                COMPANION_HEART_TRIBULATION_AWAIT_SETTLEMENT_STATE: 3,
                            }
                            round_num = round_map.get(workflow_state, 0)
                            if round_num <= 0:
                                _stop_companion_heart_tribulation_task(
                                    storage,
                                    task,
                                    last_error="自动共历心劫重试时无法确定轮次，已停止自动。",
                                    step=workflow_state,
                                )
                                continue
                            command = _build_companion_heart_tribulation_action_command(task, round_num)
                            tribulation_msg_id = int(task.get("tribulation_msg_id") or 0)
                            if tribulation_msg_id <= 0:
                                _stop_companion_heart_tribulation_task(
                                    storage,
                                    task,
                                    last_error="自动共历心劫重试时缺少心劫消息锚点，已停止自动。",
                                    step=workflow_state,
                                )
                                continue
                            try:
                                await _send_companion_heart_tribulation_command(
                                    client,
                                    storage,
                                    task,
                                    text=command,
                                    reply_to_msg_id=tribulation_msg_id,
                                )
                            except Exception as exc:
                                _stop_companion_heart_tribulation_task(
                                    storage,
                                    task,
                                    last_error=f"自动共历心劫重试发送第{round_num}轮策略失败，已停止自动。",
                                    step=workflow_state,
                                    detail={"error": str(exc), "round": round_num},
                                )
                                continue
                            new_retry_count = round_retry_count + 1
                            storage.update_companion_heart_tribulation_task(
                                task_id,
                                round_retry_count=new_retry_count,
                                round_retry_deadline_at=now + COMPANION_HEART_TRIBULATION_ROUND_RETRY_SECONDS,
                                step_deadline_at=now + COMPANION_HEART_TRIBULATION_EDIT_STALL_SECONDS,
                                last_error="",
                            )
                            _append_companion_heart_tribulation_log(
                                storage,
                                task,
                                step=workflow_state,
                                event_type="round_retry_sent",
                                text=command,
                                detail={
                                    "round": round_num,
                                    "retry_count": new_retry_count,
                                    "tribulation_msg_id": tribulation_msg_id,
                                },
                            )
                        else:
                            tribulation_msg_id = int(task.get("tribulation_msg_id") or 0)
                            matched_bot_id = int(task.get("matched_bot_id") or 0)
                            _stop_companion_heart_tribulation_task(
                                storage,
                                task,
                                last_error="自动共历心劫轮次编辑重试耗尽，已停止自动。",
                                step=workflow_state,
                                detail={
                                    "step_deadline_at": step_deadline_at,
                                    "now": now,
                                    "tribulation_msg_id": tribulation_msg_id,
                                    "matched_bot_id": matched_bot_id,
                                    "round_retry_count": round_retry_count,
                                    "workflow_state": workflow_state,
                                },
                            )
                        continue
                    if step_deadline_at > 0 and now >= step_deadline_at:
                        tribulation_msg_id = int(task.get("tribulation_msg_id") or 0)
                        matched_bot_id = int(task.get("matched_bot_id") or 0)
                        _stop_companion_heart_tribulation_task(
                            storage,
                            task,
                            last_error="自动共历心劫等待超时，已停止自动。",
                            step=workflow_state,
                            detail={
                                "step_deadline_at": step_deadline_at,
                                "now": now,
                                "tribulation_msg_id": tribulation_msg_id,
                                "matched_bot_id": matched_bot_id,
                                "round_retry_count": round_retry_count,
                                "workflow_state": workflow_state,
                            },
                        )
                    continue

                if workflow_state not in {"", COMPANION_HEART_TRIBULATION_IDLE_STATE}:
                    continue

                if next_run_at > now:
                    if earliest_idle_next_run_at is None or next_run_at < earliest_idle_next_run_at:
                        earliest_idle_next_run_at = next_run_at
                    continue

                has_active_workflow = True
                fresh_payload = await asyncio.to_thread(
                    _refresh_companion_payload, storage, int(profile_id)
                )
                if not fresh_payload or not isinstance(fresh_payload, dict):
                    _stop_companion_heart_tribulation_task(
                        storage,
                        task,
                        last_error="刷新侍妾冷却失败，已停止自动共历心劫。",
                        step="refresh_payload",
                    )
                    continue

                resolved_next_run_at = _resolve_companion_heart_tribulation_next_run_at(
                    fresh_payload
                )
                if resolved_next_run_at is None:
                    panel_reply = _get_latest_companion_panel_message(
                        storage,
                        profile_id=int(profile_id),
                        chat_id=int(task.get("chat_id") or 0),
                        thread_id=int(task.get("thread_id")) if task.get("thread_id") else None,
                    )
                    resolved_next_run_at = _resolve_companion_panel_cooldown_target(
                        panel_reply,
                        "heart_tribulation",
                    )
                    if resolved_next_run_at is None:
                        _stop_companion_heart_tribulation_task(
                            storage,
                            task,
                            last_error="最新侍妾信息缺少共历心劫冷却字段，已停止自动。",
                            step="resolve_cooldown",
                        )
                        continue
                if resolved_next_run_at > now:
                    storage.update_companion_heart_tribulation_task(
                        task_id,
                        workflow_state=COMPANION_HEART_TRIBULATION_IDLE_STATE,
                        next_run_at=resolved_next_run_at,
                        step_deadline_at=0,
                        last_error="",
                    )
                    if earliest_idle_next_run_at is None or resolved_next_run_at < earliest_idle_next_run_at:
                        earliest_idle_next_run_at = resolved_next_run_at
                    continue

                voyage_target = _resolve_active_companion_voyage_target(
                    storage,
                    profile_id=int(profile_id),
                    chat_id=int(task.get("chat_id") or 0),
                    thread_id=int(task.get("thread_id")) if task.get("thread_id") else None,
                    now=now,
                )
                if voyage_target > now:
                    storage.update_companion_heart_tribulation_task(
                        task_id,
                        workflow_state=COMPANION_HEART_TRIBULATION_IDLE_STATE,
                        next_run_at=voyage_target + 10,
                        step_deadline_at=0,
                        last_error="侍妾远航中，归航后再执行。",
                    )
                    continue

                run_id = secrets.token_hex(8)
                updated_task = storage.update_companion_heart_tribulation_task(
                    task_id,
                    enabled=1,
                    run_id=run_id,
                    workflow_state=COMPANION_HEART_TRIBULATION_SENDING_PANEL_STATE,
                    next_run_at=0,
                    step_deadline_at=now + COMPANION_HEART_TRIBULATION_STEP_TIMEOUT_SECONDS,
                    last_run_at=now,
                    matched_bot_id=0,
                    anchor_command_msg_id=0,
                    anchor_bot_msg_id=0,
                    tribulation_command_msg_id=0,
                    tribulation_msg_id=0,
                    panel_reply_msg_id=0,
                    last_action_round_sent=0,
                    last_tribulation_command_at=0,
                    last_progress_at=0,
                    last_progress_fingerprint="",
                    last_stable_sent_at=0,
                    last_error="",
                    retry_count=0,
                )
                if not updated_task:
                    continue
                task = updated_task
                _append_companion_heart_tribulation_log(
                    storage,
                    task,
                    step="launch",
                    event_type="cooldown_ready",
                    detail={"resolved_next_run_at": resolved_next_run_at},
                )
                try:
                    command_message = await _send_companion_heart_tribulation_command(
                        client,
                        storage,
                        task,
                        text=COMPANION_PANEL_COMMAND,
                    )
                except Exception as exc:
                    _stop_companion_heart_tribulation_task(
                        storage,
                        task,
                        last_error=f"发送{COMPANION_PANEL_COMMAND}失败，已停止自动共历心劫。",
                        step="send_panel_command",
                        detail={"error": str(exc)},
                    )
                    continue
                storage.update_companion_heart_tribulation_task(
                    task_id,
                    workflow_state=COMPANION_HEART_TRIBULATION_AWAIT_PANEL_STATE,
                    anchor_command_msg_id=int(getattr(command_message, "id", 0) or 0),
                    step_deadline_at=time.time() + COMPANION_HEART_TRIBULATION_STEP_TIMEOUT_SECONDS,
                    last_run_at=time.time(),
                )
                task = storage.get_companion_heart_tribulation_task(
                    int(profile_id),
                    int(task.get("chat_id") or 0),
                    thread_id=int(task.get("thread_id")) if task.get("thread_id") else None,
                ) or task
                _append_companion_heart_tribulation_log(
                    storage,
                    task,
                    step=COMPANION_HEART_TRIBULATION_AWAIT_PANEL_STATE,
                    event_type="send_panel_command",
                    message_id=int(getattr(command_message, "id", 0) or 0),
                    text=COMPANION_PANEL_COMMAND,
                    detail={"run_id": run_id},
                )
            if has_active_workflow:
                sleep_seconds = COMPANION_HEART_TRIBULATION_ACTIVE_POLL_SECONDS
            elif earliest_idle_next_run_at is not None:
                sleep_seconds = min(
                    COMPANION_HEART_TRIBULATION_IDLE_SLEEP_MAX_SECONDS,
                    max(1.0, earliest_idle_next_run_at - time.time()),
                )
            else:
                sleep_seconds = COMPANION_HEART_TRIBULATION_EMPTY_SLEEP_SECONDS
            await asyncio.sleep(sleep_seconds)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Companion heart tribulation scheduler error for profile=%s: %s",
                profile_id,
                exc,
            )
            await asyncio.sleep(10)


def _register_client_background_task(
    client: object, task: asyncio.Task
) -> asyncio.Task:
    tasks = getattr(client, "_tg_game_background_tasks", None)
    if tasks is None:
        tasks = set()
        setattr(client, "_tg_game_background_tasks", tasks)

    tasks.add(task)

    def _discard_done(done_task: asyncio.Task) -> None:
        current_tasks = getattr(client, "_tg_game_background_tasks", None)
        if current_tasks is not None:
            current_tasks.discard(done_task)

    task.add_done_callback(_discard_done)
    return task


def _get_divination_today_count_from_payload(payload: dict) -> int:
    last_divination_text = str(payload.get("last_divination_date") or "").strip()
    last_divination_ts = biz_sect_game._parse_iso_timestamp(last_divination_text)
    last_divination_day = ""
    if last_divination_ts:
        last_divination_day = time.strftime(
            "%Y-%m-%d", time.localtime(last_divination_ts)
        )
    elif last_divination_text:
        last_divination_day = last_divination_text[:10]
    today_text = time.strftime("%Y-%m-%d", time.localtime(time.time()))
    raw_today_count = max(int(payload.get("divination_count_today") or 0), 0)
    return raw_today_count if last_divination_day == today_text else 0


def _get_cached_divination_today_count(storage: Storage, profile_id: int) -> int:
    payload = read_cached_external_payload(storage, profile_id)
    return _get_divination_today_count_from_payload(payload)


def _parse_iso_to_ts(raw_value: object) -> float:
    text = str(raw_value or "").strip()
    if not text:
        return 0.0
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).timestamp()


def _parse_wanling_roam_ts(raw_value: object) -> float:
    return parse_wanling_roam_timestamp(raw_value)


def _coerce_list_value(value: object) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _resolve_wanling_roam_next_finish_at(payload: dict) -> Optional[float]:
    return resolve_wanling_roam_next_finish_at(payload, now=time.time())


def _resolve_companion_next_run_at(payload: dict, feature_key: str) -> Optional[float]:
    return resolve_simple_cooldown_next_run_at(payload, feature_key)


def _normalize_wild_experience_strategy(value: object) -> str:
    return normalize_wild_experience_strategy(value)


def _normalize_artifact_touch_command(value: object) -> str:
    return normalize_artifact_touch_command(value)


def _normalize_artifact_touch_interval(value: object) -> int:
    return normalize_artifact_touch_interval(value)


def _unpack_artifact_touch_strategy(value: object) -> tuple[str, int]:
    return unpack_artifact_touch_strategy(value)


def _normalize_artifact_trial_artifact_name(value: object) -> str:
    return normalize_artifact_trial_artifact_name(value)


def _normalize_artifact_trial_route(value: object) -> str:
    return normalize_artifact_trial_route(value)


def _unpack_artifact_trial_strategy(value: object) -> tuple[str, str]:
    return unpack_artifact_trial_strategy(value)


def _build_artifact_trial_command(artifact_name: object, route: object) -> str:
    return build_artifact_trial_command(artifact_name, route)


def _normalize_artifact_nurture_target_name(value: object) -> str:
    return normalize_artifact_nurture_target_name(value)


def _unpack_artifact_nurture_strategy(value: object) -> str:
    return unpack_artifact_nurture_strategy(value)


def _build_artifact_nurture_command(target_name: object) -> str:
    return build_artifact_nurture_command(target_name)


def _artifact_touch_parent_matches_profile(
    parent: Optional[dict], profile: object, command_text: str
) -> bool:
    if not parent or bool(parent.get("is_bot")):
        return False
    if str(parent.get("text") or "").strip() != command_text:
        return False
    if str(parent.get("direction") or "") == "outgoing":
        return True
    expected_user_id = str(getattr(profile, "telegram_user_id", "") or "").strip()
    return bool(expected_user_id) and str(parent.get("sender_id") or "") == expected_user_id


def _artifact_trial_parent_matches_profile(
    parent: Optional[dict], profile: object, command_text: str
) -> bool:
    if not parent or bool(parent.get("is_bot")):
        return False
    if str(parent.get("text") or "").strip() != command_text:
        return False
    if str(parent.get("direction") or "") == "outgoing":
        return True
    expected_user_id = str(getattr(profile, "telegram_user_id", "") or "").strip()
    return bool(expected_user_id) and str(parent.get("sender_id") or "") == expected_user_id


def _artifact_nurture_parent_matches_profile(
    parent: Optional[dict], profile: object, command_text: str
) -> bool:
    if not parent or bool(parent.get("is_bot")):
        return False
    if str(parent.get("text") or "").strip() != command_text:
        return False
    if str(parent.get("direction") or "") == "outgoing":
        return True
    expected_user_id = str(getattr(profile, "telegram_user_id", "") or "").strip()
    return bool(expected_user_id) and str(parent.get("sender_id") or "") == expected_user_id


def _enqueue_artifact_touch_cooldown_probe(
    storage: Storage, task: dict, command_text: str, current_ts: float
) -> bool:
    chat_id = int(task.get("chat_id") or 0)
    if not chat_id:
        return False
    thread_id = int(task.get("thread_id")) if task.get("thread_id") else None
    if not _has_pending_outgoing_command(
        storage,
        profile_id=int(task.get("profile_id") or 0),
        chat_id=chat_id,
        text=command_text,
        thread_id=thread_id,
    ):
        storage.enqueue_outgoing_command(
            profile_id=int(task.get("profile_id") or 0),
            chat_id=chat_id,
            text=command_text,
            thread_id=thread_id,
            chat_type=str(task.get("chat_type") or "group"),
            bot_username=str(task.get("bot_username") or ""),
            delay_seconds=ARTIFACT_TOUCH_PROBE_DELAY_SECONDS,
        )
    storage.update_companion_auto_task(
        int(task["id"]),
        next_run_at=(
            current_ts
            + ARTIFACT_TOUCH_PROBE_DELAY_SECONDS
            + ARTIFACT_TOUCH_REPLY_WAIT_SECONDS
        ),
        workflow_state=ARTIFACT_TOUCH_PROBE_PENDING_STATE,
        last_error="bot回包未提供冷却，已安排10秒后补发一次获取冷却。",
    )
    return True


def _reschedule_artifact_touch_task_from_reply(
    storage: Storage,
    task: dict,
    *,
    profile: object,
    parent: dict,
    reply_text: str,
    reply_created_at: float = 0,
    now: Optional[float] = None,
) -> bool:
    command_text, _interval_seconds = _unpack_artifact_touch_strategy(
        task.get("strategy") or ""
    )
    if not _artifact_touch_parent_matches_profile(parent, profile, command_text):
        return False
    parsed = biz_artifact_game.parse_message(reply_text)
    if not parsed or parsed.get("event") != "artifact_touch":
        return False
    current_ts = float(now if now is not None else time.time())
    cooldown_seconds = int(parsed.get("cooldown_seconds") or 0)
    if cooldown_seconds <= 0:
        workflow_state = str(task.get("workflow_state") or "").strip()
        last_error = str(task.get("last_error") or "").strip()
        if workflow_state == ARTIFACT_TOUCH_AWAIT_REPLY_STATE or (
            workflow_state == ARTIFACT_TOUCH_INTERNAL_WAIT_STATE
            and "bot回包未提供冷却" in last_error
        ):
            return _enqueue_artifact_touch_cooldown_probe(
                storage,
                task,
                command_text,
                current_ts,
            )
        return False
    base_ts = float(reply_created_at or current_ts)
    target_ts = base_ts + cooldown_seconds + ARTIFACT_TOUCH_COOLDOWN_BUFFER_SECONDS
    if target_ts <= current_ts:
        return False
    storage.update_companion_auto_task(
        int(task["id"]),
        next_run_at=target_ts,
        workflow_state=ARTIFACT_TOUCH_BOT_COOLDOWN_STATE,
        last_error="",
    )
    return True


def reschedule_artifact_touch_auto_on_reply(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    reply_to_msg_id: int,
    reply_text: str,
    reply_created_at: float = 0,
    now: Optional[float] = None,
) -> bool:
    if not reply_to_msg_id:
        return False
    profile = storage.get_profile(int(profile_id))
    if not profile:
        return False
    task = storage.get_companion_auto_task(
        int(profile_id),
        int(chat_id),
        ARTIFACT_TOUCH_FEATURE_KEY,
    )
    if not task or not bool(task.get("enabled")):
        return False
    parent = storage.get_bound_message(int(chat_id), int(reply_to_msg_id), int(profile_id))
    if not parent:
        return False
    task_thread_id = task.get("thread_id")
    if task_thread_id:
        parent_thread_id = parent.get("thread_id")
        if parent_thread_id is not None and int(parent_thread_id) != int(task_thread_id):
            return False
    return _reschedule_artifact_touch_task_from_reply(
        storage,
        task,
        profile=profile,
        parent=parent,
        reply_text=reply_text,
        reply_created_at=reply_created_at,
        now=now,
    )


def sync_artifact_touch_auto_from_latest_reply(
    storage: Storage, profile_id: int, task: dict, *, now: Optional[float] = None
) -> bool:
    profile = storage.get_profile(int(profile_id))
    if not profile:
        return False
    command_text, _interval_seconds = _unpack_artifact_touch_strategy(
        task.get("strategy") or ""
    )
    chat_id = int(task.get("chat_id") or 0)
    if not chat_id:
        return False
    sender_id = None
    try:
        sender_id = int(str(profile.telegram_user_id or "").strip())
    except (TypeError, ValueError):
        sender_id = None
    reply = storage.get_latest_bot_reply_for_command(
        chat_id,
        command_text,
        profile_id=int(profile_id),
        thread_id=int(task.get("thread_id")) if task.get("thread_id") else None,
        sender_id=sender_id,
        sender_username=str(profile.telegram_username or ""),
    )
    if not reply:
        return False
    return reschedule_artifact_touch_auto_on_reply(
        storage,
        profile_id=int(profile_id),
        chat_id=chat_id,
        reply_to_msg_id=int(reply.get("reply_to_msg_id") or 0),
        reply_text=str(reply.get("text") or ""),
        reply_created_at=float(reply.get("created_at") or 0),
        now=now,
    )


def _reschedule_artifact_trial_task_from_reply(
    storage: Storage,
    task: dict,
    *,
    profile: object,
    parent: dict,
    reply_text: str,
    reply_created_at: float = 0,
    now: Optional[float] = None,
) -> bool:
    artifact_name, route = _unpack_artifact_trial_strategy(task.get("strategy") or "")
    command_text = _build_artifact_trial_command(artifact_name, route)
    if not _artifact_trial_parent_matches_profile(parent, profile, command_text):
        return False
    parsed = biz_artifact_game.parse_message(reply_text)
    if not parsed or parsed.get("event") != "artifact_trial":
        return False
    if parsed.get("insufficient_resources"):
        storage.update_companion_auto_task(
            int(task["id"]),
            enabled=0,
            next_run_at=0,
            workflow_state=ARTIFACT_TRIAL_STOPPED_RESOURCES_STATE,
            last_error="bot提示器灵试炼资源不足，已停止自动试炼。",
        )
        return True
    current_ts = float(now if now is not None else time.time())
    cooldown_seconds = int(parsed.get("cooldown_seconds") or 0)
    if cooldown_seconds <= 0:
        cooldown_seconds = ARTIFACT_TRIAL_DEFAULT_COOLDOWN_SECONDS
    base_ts = float(reply_created_at or current_ts)
    target_ts = base_ts + cooldown_seconds + ARTIFACT_TRIAL_COOLDOWN_BUFFER_SECONDS
    if target_ts <= current_ts:
        return False
    storage.update_companion_auto_task(
        int(task["id"]),
        next_run_at=target_ts,
        workflow_state=ARTIFACT_TRIAL_BOT_COOLDOWN_STATE,
        last_error="",
    )
    return True


def reschedule_artifact_trial_auto_on_reply(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    reply_to_msg_id: int,
    reply_text: str,
    reply_created_at: float = 0,
    now: Optional[float] = None,
) -> bool:
    if not reply_to_msg_id:
        return False
    profile = storage.get_profile(int(profile_id))
    if not profile:
        return False
    task = storage.get_companion_auto_task(
        int(profile_id),
        int(chat_id),
        ARTIFACT_TRIAL_FEATURE_KEY,
    )
    if not task or not bool(task.get("enabled")):
        return False
    parent = storage.get_bound_message(int(chat_id), int(reply_to_msg_id), int(profile_id))
    if not parent:
        return False
    task_thread_id = task.get("thread_id")
    if task_thread_id:
        parent_thread_id = parent.get("thread_id")
        if parent_thread_id is not None and int(parent_thread_id) != int(task_thread_id):
            return False
    return _reschedule_artifact_trial_task_from_reply(
        storage,
        task,
        profile=profile,
        parent=parent,
        reply_text=reply_text,
        reply_created_at=reply_created_at,
        now=now,
    )


def sync_artifact_trial_auto_from_latest_reply(
    storage: Storage, profile_id: int, task: dict, *, now: Optional[float] = None
) -> bool:
    profile = storage.get_profile(int(profile_id))
    if not profile:
        return False
    artifact_name, route = _unpack_artifact_trial_strategy(task.get("strategy") or "")
    command_text = _build_artifact_trial_command(artifact_name, route)
    chat_id = int(task.get("chat_id") or 0)
    if not chat_id:
        return False
    sender_id = None
    try:
        sender_id = int(str(profile.telegram_user_id or "").strip())
    except (TypeError, ValueError):
        sender_id = None
    reply = storage.get_latest_bot_reply_for_command(
        chat_id,
        command_text,
        profile_id=int(profile_id),
        thread_id=int(task.get("thread_id")) if task.get("thread_id") else None,
        sender_id=sender_id,
        sender_username=str(profile.telegram_username or ""),
    )
    if not reply:
        return False
    return reschedule_artifact_trial_auto_on_reply(
        storage,
        profile_id=int(profile_id),
        chat_id=chat_id,
        reply_to_msg_id=int(reply.get("reply_to_msg_id") or 0),
        reply_text=str(reply.get("text") or ""),
        reply_created_at=float(reply.get("created_at") or 0),
        now=now,
    )


def _reschedule_artifact_nurture_task_from_reply(
    storage: Storage,
    task: dict,
    *,
    profile: object,
    parent: dict,
    reply_text: str,
    reply_created_at: float = 0,
    now: Optional[float] = None,
) -> bool:
    target_name = _unpack_artifact_nurture_strategy(task.get("strategy") or "")
    command_text = _build_artifact_nurture_command(target_name)
    if not _artifact_nurture_parent_matches_profile(parent, profile, command_text):
        return False
    parsed = biz_artifact_game.parse_message(reply_text)
    if not parsed or parsed.get("event") != "artifact_nurture":
        return False
    if parsed.get("insufficient_resources"):
        storage.update_companion_auto_task(
            int(task["id"]),
            enabled=0,
            next_run_at=0,
            workflow_state=ARTIFACT_NURTURE_STOPPED_RESOURCES_STATE,
            last_error="bot提示温养器灵资源不足，已停止自动温养。",
        )
        return True
    current_ts = float(now if now is not None else time.time())
    cooldown_seconds = int(parsed.get("cooldown_seconds") or 0)
    if cooldown_seconds <= 0:
        cooldown_seconds = ARTIFACT_NURTURE_DEFAULT_COOLDOWN_SECONDS
    base_ts = float(reply_created_at or current_ts)
    target_ts = base_ts + cooldown_seconds + ARTIFACT_NURTURE_COOLDOWN_BUFFER_SECONDS
    if target_ts <= current_ts:
        return False
    storage.update_companion_auto_task(
        int(task["id"]),
        next_run_at=target_ts,
        workflow_state=ARTIFACT_NURTURE_BOT_COOLDOWN_STATE,
        last_error="",
    )
    return True


def reschedule_artifact_nurture_auto_on_reply(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    reply_to_msg_id: int,
    reply_text: str,
    reply_created_at: float = 0,
    now: Optional[float] = None,
) -> bool:
    if not reply_to_msg_id:
        return False
    profile = storage.get_profile(int(profile_id))
    if not profile:
        return False
    task = storage.get_companion_auto_task(
        int(profile_id),
        int(chat_id),
        ARTIFACT_NURTURE_FEATURE_KEY,
    )
    if not task or not bool(task.get("enabled")):
        return False
    parent = storage.get_bound_message(int(chat_id), int(reply_to_msg_id), int(profile_id))
    if not parent:
        return False
    task_thread_id = task.get("thread_id")
    if task_thread_id:
        parent_thread_id = parent.get("thread_id")
        if parent_thread_id is not None and int(parent_thread_id) != int(task_thread_id):
            return False
    return _reschedule_artifact_nurture_task_from_reply(
        storage,
        task,
        profile=profile,
        parent=parent,
        reply_text=reply_text,
        reply_created_at=reply_created_at,
        now=now,
    )


def sync_artifact_nurture_auto_from_latest_reply(
    storage: Storage, profile_id: int, task: dict, *, now: Optional[float] = None
) -> bool:
    profile = storage.get_profile(int(profile_id))
    if not profile:
        return False
    target_name = _unpack_artifact_nurture_strategy(task.get("strategy") or "")
    command_text = _build_artifact_nurture_command(target_name)
    chat_id = int(task.get("chat_id") or 0)
    if not chat_id:
        return False
    sender_id = None
    try:
        sender_id = int(str(profile.telegram_user_id or "").strip())
    except (TypeError, ValueError):
        sender_id = None
    reply = storage.get_latest_bot_reply_for_command(
        chat_id,
        command_text,
        profile_id=int(profile_id),
        thread_id=int(task.get("thread_id")) if task.get("thread_id") else None,
        sender_id=sender_id,
        sender_username=str(profile.telegram_username or ""),
    )
    if not reply:
        return False
    return reschedule_artifact_nurture_auto_on_reply(
        storage,
        profile_id=int(profile_id),
        chat_id=chat_id,
        reply_to_msg_id=int(reply.get("reply_to_msg_id") or 0),
        reply_text=str(reply.get("text") or ""),
        reply_created_at=float(reply.get("created_at") or 0),
        now=now,
    )


def _normalize_xinggong_starboard_target(value: object) -> str:
    return normalize_starboard_target(value)


def _get_xinggong_starboard_plots(payload: dict) -> dict:
    return get_starboard_plots(payload)


def _build_xinggong_starboard_commands(
    payload: dict, target_star: str, now: float
) -> tuple[list[str], Optional[float]]:
    return build_starboard_commands(payload, target_star, now)


def _build_xinggong_starboard_pending_candidates(
    payload: dict, target_star: str, commands: list[str]
) -> list[str]:
    return build_starboard_pending_candidates(payload, target_star, commands)


def _has_pending_xinggong_starboard_command(
    storage: Storage,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    commands: list[str],
) -> bool:
    for command_text in commands:
        if _has_pending_outgoing_command(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            text=command_text,
            thread_id=thread_id,
        ):
            return True
    return False


def _resolve_mulan_next_daily_run_at(now: float) -> float:
    current = datetime.fromtimestamp(float(now or time.time()))
    target = current.replace(
        hour=0,
        minute=MULAN_DAILY_RUN_MINUTE,
        second=0,
        microsecond=0,
    )
    if target.timestamp() <= float(now or 0):
        target += timedelta(days=1)
    return float(target.timestamp())


def _mulan_task_thread_id(task: dict) -> Optional[int]:
    return int(task.get("thread_id")) if task.get("thread_id") else None


def _mulan_workflow_parts(workflow_state: object) -> list[str]:
    return [
        part.strip()
        for part in str(workflow_state or "").split("|")
        if part.strip()
    ]


def _mulan_saved_support_command(task: dict) -> str:
    command = str(task.get("strategy") or "").strip()
    return command if command in mulan_feature.MULAN_VALID_SUPPORT_COMMANDS else ""


def _mulan_support_command_from_panel(panel_state: dict, task: dict) -> str:
    recommendation = mulan_feature.build_mulan_recommendation(panel_state)
    command = str(recommendation.get("command") or "").strip()
    if command in mulan_feature.MULAN_VALID_SUPPORT_COMMANDS:
        return command
    return _mulan_saved_support_command(task) or ".支援慕兰 护阵"


def _mulan_wait_for_command_reply(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    command_text: str,
    last_run_at: float,
) -> Optional[dict]:
    # Critical safety boundary: only follow the bot reply to this profile's own command.
    return _get_latest_profile_command_reply(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        command_text=command_text,
        since_ts=max(float(last_run_at or 0) - 2, 0),
    )


def _mulan_today_window(now: float) -> tuple[float, float]:
    current = datetime.fromtimestamp(float(now or time.time()))
    start = current.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    try:
        return float(start.timestamp()), float(end.timestamp())
    except OSError:
        return 0.0, 86400.0


def _find_current_profile_mulan_completion(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    now: float,
) -> Optional[str]:
    day_start, day_end = _mulan_today_window(now)
    messages = storage.list_bound_messages(
        profile_id=profile_id,
        chat_id=chat_id,
        search_query="慕兰烽烟",
        limit=160,
    )
    for message in messages:
        if not int(message.get("is_bot") or 0):
            continue
        created_at = float(message.get("created_at") or 0)
        if created_at < day_start or created_at >= day_end:
            continue
        if thread_id and int(message.get("thread_id") or 0) not in {int(thread_id)}:
            continue
        text = str(message.get("text") or "").strip()
        if not text:
            continue
        if (
            mulan_feature.parse_mulan_support_result_text(text)
            and _is_profile_command_reply(
                storage,
                message=message,
                profile_id=profile_id,
                chat_id=chat_id,
                thread_id=thread_id,
                command_texts=mulan_feature.MULAN_VALID_SUPPORT_COMMANDS,
            )
        ):
            return "已收到当前 profile 的慕兰支援回包，明日再执行。"
        panel_state = mulan_feature.parse_mulan_panel_text(text)
        if (
            "已支援" in str(panel_state.get("status") or "")
            and _is_profile_command_reply(
                storage,
                message=message,
                profile_id=profile_id,
                chat_id=chat_id,
                thread_id=thread_id,
                command_texts={mulan_feature.MULAN_PANEL_COMMAND_TEXT},
            )
        ):
            return "当前 profile 面板显示今日已支援，明日再执行。"
    return None


def _expire_stale_mulan_sending_commands(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    workflow_parts: list[str],
    now: float,
) -> int:
    command_texts = {
        mulan_feature.MULAN_PANEL_COMMAND_TEXT,
        mulan_feature.MULAN_SPY_COMMAND_TEXT,
        mulan_feature.MULAN_COLLECT_REPORT_COMMAND_TEXT,
        *mulan_feature.MULAN_VALID_SUPPORT_COMMANDS,
    }
    for part in workflow_parts:
        if part.startswith(".辨报 ") or part.startswith(".公开军报 "):
            command_texts.add(part)

    expired = 0
    stale_before = float(now or time.time()) - OUTGOING_CONFIRM_TIMEOUT_SECONDS
    for command_text in command_texts:
        latest_command = storage.get_latest_outgoing_command(
            chat_id,
            profile_id=profile_id,
            text=command_text,
            thread_id=thread_id,
        )
        if not latest_command:
            continue
        if str(latest_command.get("status") or "").strip() != "sending":
            continue
        updated_at = float(
            latest_command.get("updated_at") or latest_command.get("created_at") or 0
        )
        if updated_at > stale_before:
            continue
        storage.mark_outgoing_command_failed(
            int(latest_command["id"]),
            "Stale Mulan outgoing send state expired; scheduler will re-check.",
        )
        expired += 1
    return expired


def _run_mulan_auto_task_step(
    storage: Storage,
    *,
    profile_id: int,
    task: dict,
    now: float,
) -> None:
    task_id = int(task.get("id") or 0)
    chat_id = int(task.get("chat_id") or 0)
    if not task_id:
        return
    if not chat_id:
        storage.update_companion_auto_task(
            task_id,
            enabled=0,
            last_error="Chat ID missing",
        )
        return

    next_run_at = float(task.get("next_run_at") or 0)
    if next_run_at > now:
        return

    thread_id = _mulan_task_thread_id(task)
    chat_type = str(task.get("chat_type") or "group")
    bot_username = str(task.get("bot_username") or "")
    workflow_parts = _mulan_workflow_parts(task.get("workflow_state"))
    workflow_state = workflow_parts[0] if workflow_parts else ""
    last_run_at = float(task.get("last_run_at") or 0)

    _expire_stale_mulan_sending_commands(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        workflow_parts=workflow_parts,
        now=now,
    )

    completion_message = _find_current_profile_mulan_completion(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        now=now,
    )
    if completion_message:
        storage.update_companion_auto_task(
            task_id,
            last_run_at=now,
            next_run_at=_resolve_mulan_next_daily_run_at(now),
            workflow_state="",
            last_error=completion_message,
        )
        return

    def has_pending(command_text: str) -> bool:
        return _has_pending_outgoing_command(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            text=command_text,
            thread_id=thread_id,
        )

    def enqueue(command_text: str) -> None:
        storage.enqueue_outgoing_command(
            profile_id=profile_id,
            chat_id=chat_id,
            text=command_text,
            thread_id=thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
        )

    def enqueue_verify_report(true_report: dict, support_command: str) -> bool:
        number = str(true_report.get("number") or "").strip()
        verify_command = mulan_feature.build_mulan_verify_report_command(number)
        public_command = mulan_feature.build_mulan_public_report_command(number)
        if not verify_command or not public_command:
            return False
        if has_pending(verify_command):
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                last_error="已有辨报命令待发送，稍后复查。",
            )
            return True
        enqueue(verify_command)
        storage.update_companion_auto_task(
            task_id,
            last_run_at=now,
            next_run_at=now + MULAN_STEP_RETRY_SECONDS,
            workflow_state=f"await_verify_report|{verify_command}|{public_command}|{support_command}",
            last_error=f"已发送辨报 {number}，等待可信度回包。",
        )
        return True

    if workflow_state == "await_panel":
        command_text = mulan_feature.MULAN_PANEL_COMMAND_TEXT
        if has_pending(command_text):
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                last_error="等待边境军功命令发送或确认。",
            )
            return
        panel_reply = _mulan_wait_for_command_reply(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            command_text=command_text,
            last_run_at=last_run_at,
        )
        if not panel_reply:
            if last_run_at and now - last_run_at < MULAN_PANEL_WAIT_SECONDS:
                storage.update_companion_auto_task(
                    task_id,
                    next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                    last_error="等待边境军功回包。",
                )
                return
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now + 300,
                workflow_state="",
                last_error="未收到当前 profile 的边境军功回包，稍后重新刷新。",
            )
            return

        panel_text = str(panel_reply.get("text") or "")
        panel_state = mulan_feature.parse_mulan_panel_text(panel_text)
        if not panel_state.get("daily_council") and not panel_state.get("records"):
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now + 300,
                workflow_state="",
                last_error="边境军功回包未识别，稍后重新刷新。",
            )
            return
        if "已支援" in str(panel_state.get("status") or ""):
            storage.update_companion_auto_task(
                task_id,
                last_run_at=now,
                next_run_at=_resolve_mulan_next_daily_run_at(now),
                workflow_state="",
                last_error="面板显示今日已支援，明日再执行。",
            )
            return

        support_command = _mulan_support_command_from_panel(panel_state, task)
        spy_command = mulan_feature.MULAN_SPY_COMMAND_TEXT
        if has_pending(spy_command):
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                last_error="已有慕兰谍影命令待发送，稍后复查。",
            )
            return
        enqueue(spy_command)
        storage.update_companion_auto_task(
            task_id,
            last_run_at=now,
            next_run_at=now + MULAN_STEP_RETRY_SECONDS,
            workflow_state=f"await_spy|{support_command}",
            last_error="已发送慕兰谍影，等待军报匣回包。",
        )
        return

    if workflow_state == "await_spy":
        support_command = (
            workflow_parts[1]
            if len(workflow_parts) > 1
            and workflow_parts[1] in mulan_feature.MULAN_VALID_SUPPORT_COMMANDS
            else _mulan_saved_support_command(task) or ".支援慕兰 护阵"
        )
        spy_command = mulan_feature.MULAN_SPY_COMMAND_TEXT
        if has_pending(spy_command):
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                last_error="等待慕兰谍影命令发送或确认。",
            )
            return
        spy_reply = _mulan_wait_for_command_reply(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            command_text=spy_command,
            last_run_at=last_run_at,
        )
        if not spy_reply:
            if last_run_at and now - last_run_at < MULAN_SPY_REPLY_WAIT_SECONDS:
                storage.update_companion_auto_task(
                    task_id,
                    next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                    last_error="等待慕兰谍影回包。",
                )
                return
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now + 300,
                workflow_state="",
                last_error="未收到当前 profile 的慕兰谍影回包，稍后重新刷新。",
            )
            return

        spy_text = str(spy_reply.get("text") or "")
        if (
            "搜集军报" in spy_text
            and not mulan_feature.parse_mulan_report_options(spy_text)
        ):
            collect_command = mulan_feature.MULAN_COLLECT_REPORT_COMMAND_TEXT
            if has_pending(collect_command):
                storage.update_companion_auto_task(
                    task_id,
                    next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                    last_error="已有搜集军报命令待发送，稍后复查。",
                )
                return
            enqueue(collect_command)
            storage.update_companion_auto_task(
                task_id,
                last_run_at=now,
                next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                workflow_state=f"await_collect_reports|{support_command}",
                last_error="已发送搜集军报，等待军报匣回包。",
            )
            return

        true_report = mulan_feature.select_known_true_report(spy_text)
        if true_report.get("number"):
            enqueue_verify_report(true_report, support_command)
            return

        if has_pending(support_command):
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                last_error="已有慕兰支援命令待发送，稍后复查。",
            )
            return
        enqueue(support_command)
        storage.update_companion_auto_task(
            task_id,
            last_run_at=now,
            next_run_at=now + MULAN_STEP_RETRY_SECONDS,
            workflow_state=f"await_support|{support_command}",
            last_error="未识别到已知真军报，已按今日军议发送支援。",
        )
        return

    if workflow_state == "await_collect_reports":
        support_command = (
            workflow_parts[1]
            if len(workflow_parts) > 1
            and workflow_parts[1] in mulan_feature.MULAN_VALID_SUPPORT_COMMANDS
            else _mulan_saved_support_command(task) or ".支援慕兰 护阵"
        )
        collect_command = mulan_feature.MULAN_COLLECT_REPORT_COMMAND_TEXT
        if has_pending(collect_command):
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                last_error="等待搜集军报命令发送或确认。",
            )
            return
        collect_reply = _mulan_wait_for_command_reply(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            command_text=collect_command,
            last_run_at=last_run_at,
        )
        if not collect_reply:
            if last_run_at and now - last_run_at < MULAN_COLLECT_REPORT_REPLY_WAIT_SECONDS:
                storage.update_companion_auto_task(
                    task_id,
                    next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                    last_error="等待搜集军报回包。",
                )
                return
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now + 300,
                workflow_state="",
                last_error="未收到当前 profile 的搜集军报回包，稍后重新刷新。",
            )
            return

        true_report = mulan_feature.select_known_true_report(
            str(collect_reply.get("text") or "")
        )
        if true_report.get("number"):
            enqueue_verify_report(true_report, support_command)
            return

        if has_pending(support_command):
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                last_error="已有慕兰支援命令待发送，稍后复查。",
            )
            return
        enqueue(support_command)
        storage.update_companion_auto_task(
            task_id,
            last_run_at=now,
            next_run_at=now + MULAN_STEP_RETRY_SECONDS,
            workflow_state=f"await_support|{support_command}",
            last_error="搜集军报后未识别到已知真军报，已按今日军议发送支援。",
        )
        return

    if workflow_state == "await_verify_report":
        verify_command = workflow_parts[1] if len(workflow_parts) > 1 else ""
        public_command = (
            workflow_parts[2]
            if len(workflow_parts) > 2
            and workflow_parts[2].startswith(".公开军报 ")
            else ""
        )
        support_command = (
            workflow_parts[3]
            if len(workflow_parts) > 3
            and workflow_parts[3] in mulan_feature.MULAN_VALID_SUPPORT_COMMANDS
            else _mulan_saved_support_command(task) or ".支援慕兰 护阵"
        )
        if not verify_command.startswith(".辨报 ") or not public_command:
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now,
                workflow_state="",
                last_error="辨报流程状态异常，重新刷新边境军功。",
            )
            return
        if has_pending(verify_command):
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                last_error="等待辨报命令发送或确认。",
            )
            return
        verify_reply = _mulan_wait_for_command_reply(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            command_text=verify_command,
            last_run_at=last_run_at,
        )
        if not verify_reply:
            if last_run_at and now - last_run_at < MULAN_VERIFY_REPORT_REPLY_WAIT_SECONDS:
                storage.update_companion_auto_task(
                    task_id,
                    next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                    last_error="等待辨报回包。",
                )
                return
            if has_pending(support_command):
                storage.update_companion_auto_task(
                    task_id,
                    next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                    last_error="辨报未回包，等待慕兰支援命令发送或确认。",
                )
                return
            enqueue(support_command)
            storage.update_companion_auto_task(
                task_id,
                last_run_at=now,
                next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                workflow_state=f"await_support|{support_command}",
                last_error="未收到当前 profile 的辨报回包，跳过公开军报并按今日军议发送支援。",
            )
            return

        judgement = mulan_feature.parse_mulan_report_judgement(
            str(verify_reply.get("text") or "")
        )
        if judgement.get("credible") or judgement.get("limited"):
            candidate_public_command = str(judgement.get("public_command") or "").strip()
            if (
                candidate_public_command
                and candidate_public_command != public_command
            ):
                public_command = candidate_public_command
            if has_pending(public_command):
                storage.update_companion_auto_task(
                    task_id,
                    next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                    last_error="已有公开军报命令待发送，稍后复查。",
                )
                return
            enqueue(public_command)
            storage.update_companion_auto_task(
                task_id,
                last_run_at=now,
                next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                workflow_state=f"await_public_report|{public_command}|{support_command}",
                last_error="辨报通过，已公开军报，等待回包。",
            )
            return

        if has_pending(support_command):
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                last_error="已有慕兰支援命令待发送，稍后复查。",
            )
            return
        enqueue(support_command)
        storage.update_companion_auto_task(
            task_id,
            last_run_at=now,
            next_run_at=now + MULAN_STEP_RETRY_SECONDS,
            workflow_state=f"await_support|{support_command}",
            last_error="辨报未通过，跳过公开军报并按今日军议发送支援。",
        )
        return

    if workflow_state == "await_public_report":
        public_command = workflow_parts[1] if len(workflow_parts) > 1 else ""
        support_command = (
            workflow_parts[2]
            if len(workflow_parts) > 2
            and workflow_parts[2] in mulan_feature.MULAN_VALID_SUPPORT_COMMANDS
            else _mulan_saved_support_command(task) or ".支援慕兰 护阵"
        )
        if not public_command.startswith(".公开军报 "):
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now,
                workflow_state="",
                last_error="公开军报流程状态异常，重新刷新边境军功。",
            )
            return
        if has_pending(public_command):
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                last_error="等待公开军报命令发送或确认。",
            )
            return
        public_reply = _mulan_wait_for_command_reply(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            command_text=public_command,
            last_run_at=last_run_at,
        )
        if not public_reply:
            if last_run_at and now - last_run_at < MULAN_PUBLIC_REPORT_REPLY_WAIT_SECONDS:
                storage.update_companion_auto_task(
                    task_id,
                    next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                    last_error="等待公开军报回包。",
                )
                return
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now + 300,
                workflow_state="",
                last_error="未收到当前 profile 的公开军报回包，稍后重新刷新。",
            )
            return

        if has_pending(support_command):
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                last_error="已有慕兰支援命令待发送，稍后复查。",
            )
            return
        enqueue(support_command)
        storage.update_companion_auto_task(
            task_id,
            last_run_at=now,
            next_run_at=now + MULAN_STEP_RETRY_SECONDS,
            workflow_state=f"await_support|{support_command}",
            last_error="已收到公开军报回包，继续发送慕兰支援。",
        )
        return

    if workflow_state == "await_support":
        support_command = (
            workflow_parts[1]
            if len(workflow_parts) > 1
            and workflow_parts[1] in mulan_feature.MULAN_VALID_SUPPORT_COMMANDS
            else _mulan_saved_support_command(task) or ".支援慕兰 护阵"
        )
        if has_pending(support_command):
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                last_error="等待慕兰支援命令发送或确认。",
            )
            return
        support_reply = _mulan_wait_for_command_reply(
            storage,
            profile_id=profile_id,
            chat_id=chat_id,
            thread_id=thread_id,
            command_text=support_command,
            last_run_at=last_run_at,
        )
        if support_reply:
            storage.update_companion_auto_task(
                task_id,
                last_run_at=now,
                next_run_at=_resolve_mulan_next_daily_run_at(now),
                workflow_state="",
                last_error="已收到慕兰支援回包，明日再执行。",
            )
            return
        if last_run_at and now - last_run_at < MULAN_SUPPORT_REPLY_WAIT_SECONDS:
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                last_error="等待慕兰支援回包。",
            )
            return
        storage.update_companion_auto_task(
            task_id,
            last_run_at=now,
            next_run_at=_resolve_mulan_next_daily_run_at(now),
            workflow_state="",
            last_error="未确认慕兰支援回包，为避免重复支援，明日再执行。",
        )
        return

    mulan_commands = [
        mulan_feature.MULAN_PANEL_COMMAND_TEXT,
        mulan_feature.MULAN_SPY_COMMAND_TEXT,
        mulan_feature.MULAN_COLLECT_REPORT_COMMAND_TEXT,
        *mulan_feature.MULAN_VALID_SUPPORT_COMMANDS,
    ]
    for part in workflow_parts:
        if part.startswith(".辨报 ") or part.startswith(".公开军报 "):
            mulan_commands.append(part)
    for command_text in mulan_commands:
        if has_pending(command_text):
            storage.update_companion_auto_task(
                task_id,
                next_run_at=now + MULAN_STEP_RETRY_SECONDS,
                last_error="已有慕兰命令待发送，稍后复查。",
            )
            return
    enqueue(mulan_feature.MULAN_PANEL_COMMAND_TEXT)
    storage.update_companion_auto_task(
        task_id,
        last_run_at=now,
        next_run_at=now + MULAN_STEP_RETRY_SECONDS,
        workflow_state="await_panel",
        last_error="已发送边境军功，等待当前 profile 的面板回包。",
    )


async def _run_companion_auto_scheduler(
    client: object,
    storage: Storage,
    *,
    run_once: bool = False,
    task_ids: Optional[set[int]] = None,
    include_tianxing: bool = True,
) -> None:
    profile_id = getattr(client, "_tg_game_profile_id", None)
    if not profile_id:
        return
    resume_last_task_at = 0.0

    while True:
        try:
            _disable_legacy_wild_experience(storage, int(profile_id))
            tasks = storage.list_active_companion_auto_tasks(int(profile_id))
            if task_ids is not None:
                tasks = [
                    task for task in tasks if int(task.get("id") or 0) in task_ids
                ]
            now = time.time()
            _cancel_legacy_pagoda_outgoing(storage, int(profile_id))
            if profile_rebirth.is_profile_rebirth_locked(storage, int(profile_id)):
                if run_once:
                    return
                await asyncio.sleep(COMPANION_AUTO_POLL_SECONDS)
                continue
            if is_network_paused(storage, int(profile_id), now=now):
                if run_once:
                    return
                await asyncio.sleep(COMPANION_AUTO_POLL_SECONDS)
                continue
            if include_tianxing:
                tick_tianxing_timeline(storage, int(profile_id), now=now)
                tick_craft_loop(storage, int(profile_id), now=now)
            payload = read_cached_external_payload(storage, int(profile_id))
            if task_ids is None and await _run_pending_wild_experience(
                client,
                storage,
                int(profile_id),
                payload,
            ):
                payload = read_cached_external_payload(storage, int(profile_id))
            if task_ids is None and await _run_pending_estate_public_hunt(
                client,
                storage,
                int(profile_id),
                payload,
            ):
                payload = read_cached_external_payload(storage, int(profile_id))
            if task_ids is None and await _run_pending_beast_merge_public(
                client,
                storage,
                int(profile_id),
                payload,
            ):
                payload = read_cached_external_payload(storage, int(profile_id))
            if task_ids is None and await _run_pending_tianji_public_trial(
                client,
                storage,
                int(profile_id),
                payload,
            ):
                payload = read_cached_external_payload(storage, int(profile_id))
            if task_ids is None and await _run_pending_pagoda_public(
                client,
                storage,
                int(profile_id),
                payload,
            ):
                payload = read_cached_external_payload(storage, int(profile_id))
            if task_ids is None and await _run_pending_xinggong_public_starboard(
                client,
                storage,
                int(profile_id),
                payload,
            ):
                payload = read_cached_external_payload(storage, int(profile_id))
                tasks = storage.list_active_companion_auto_tasks(int(profile_id))
            if task_ids is None and await _run_pending_luoyun_spirit_tree(
                client,
                storage,
                int(profile_id),
                payload,
            ):
                payload = read_cached_external_payload(storage, int(profile_id))
                tasks = storage.list_active_companion_auto_tasks(int(profile_id))
            if not tasks:
                if run_once:
                    return
                await asyncio.sleep(COMPANION_AUTO_POLL_SECONDS)
                continue
            resume_until = _get_profile_resume_until(storage, int(profile_id))
            resume_gap_seconds = _get_profile_resume_gap_seconds(
                storage,
                int(profile_id),
            )
            resume_active = resume_until > now
            for task in tasks:
                task_id = int(task.get("id") or 0)
                feature_key = str(task.get("feature_key") or "").strip()
                feature = COMPANION_AUTO_FEATURES.get(feature_key)
                if not feature or not task_id:
                    continue
                task_next_run_at = float(task.get("next_run_at") or 0)
                if resume_active and task_next_run_at <= now:
                    if (
                        resume_gap_seconds > COMPANION_AUTO_LONG_RESUME_SECONDS
                        and feature_key in COMPANION_AUTO_RESUME_HIGH_RISK_FEATURES
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now
                            + COMPANION_AUTO_LONG_RESUME_DEFER_SECONDS,
                            last_error="恢复保护：离线超过4小时，高风险自动任务延后重新检查。",
                        )
                        continue
                    if (
                        resume_last_task_at
                        and now - resume_last_task_at
                        < COMPANION_AUTO_RESUME_TASK_SPACING_SECONDS
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now
                            + COMPANION_AUTO_RESUME_TASK_SPACING_SECONDS,
                            last_error="恢复保护错峰：稍后按当前状态重新判断。",
                        )
                        continue
                    resume_last_task_at = now

                if feature_key == pagoda_auto.FEATURE_KEY:
                    chat_id = int(task.get("chat_id") or 0)
                    if not chat_id:
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            last_error="Chat ID missing",
                        )
                        continue
                    run_time = pagoda_auto.normalize_run_time(task.get("strategy"))
                    thread_id = (
                        int(task.get("thread_id")) if task.get("thread_id") else None
                    )
                    next_run_at = float(task.get("next_run_at") or 0)
                    staggered_next_run_at = pagoda_auto.stagger_existing_next_run_at(
                        next_run_at,
                        int(profile_id),
                    )
                    if staggered_next_run_at != next_run_at:
                        next_run_at = staggered_next_run_at
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=next_run_at,
                        )
                    if next_run_at > now:
                        continue
                    tomorrow_run_at = pagoda_auto.resolve_next_run_at(
                        run_time,
                        now=now,
                        force_tomorrow=True,
                        profile_id=int(profile_id),
                    )
                    last_run_at = float(task.get("last_run_at") or 0)
                    if pagoda_auto.is_same_local_day(last_run_at, now):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=tomorrow_run_at,
                            workflow_state="requested_today",
                            last_error=pagoda_auto.SENT_TODAY_ERROR,
                        )
                        continue
                    if pagoda_auto.attempted_today_from_payload(
                        payload, now=now
                    ) or pagoda_state.was_pagoda_completed_today(payload, now=now):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=tomorrow_run_at,
                            workflow_state="attempted_today",
                            last_error=pagoda_auto.ATTEMPTED_TODAY_ERROR,
                        )
                        continue
                    if pagoda_state.has_active_pagoda_request(payload, now=now):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + 60,
                            last_error="已有 MiniApp 闯塔任务，稍后复查。",
                        )
                        continue
                    queued_payload = _update_external_payload(
                        storage,
                        int(profile_id),
                        lambda latest: pagoda_state.queue_pagoda_request(
                            latest,
                            chat_id=chat_id,
                            thread_id=thread_id,
                            chat_type=str(task.get("chat_type") or "group"),
                            bot_username=str(task.get("bot_username") or ""),
                        ),
                    )
                    if not pagoda_state.get_pagoda_request(queued_payload):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + 60,
                            last_error="天机阁账号未连接，无法排队 MiniApp 闯塔。",
                        )
                        continue
                    storage.update_companion_auto_task(
                        task_id,
                        last_run_at=now,
                        next_run_at=tomorrow_run_at,
                        workflow_state="requested_today",
                        last_error=pagoda_auto.SENT_TODAY_ERROR,
                    )
                    continue

                if feature_key == biz_tianji_trial_daily_auto.FEATURE_KEY:
                    chat_id = int(task.get("chat_id") or 0)
                    if not chat_id:
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            last_error="Chat ID missing",
                        )
                        continue
                    run_time = biz_tianji_trial_daily_auto.normalize_run_time(
                        task.get("strategy")
                    )
                    next_run_at = float(task.get("next_run_at") or 0)
                    if next_run_at > now:
                        continue
                    thread_id = (
                        int(task.get("thread_id")) if task.get("thread_id") else None
                    )
                    tomorrow_run_at = biz_tianji_trial_daily_auto.resolve_next_run_at(
                        run_time,
                        now=now,
                        force_tomorrow=True,
                    )
                    last_run_at = float(task.get("last_run_at") or 0)
                    if biz_tianji_trial_daily_auto.is_same_local_day(last_run_at, now):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=tomorrow_run_at,
                            workflow_state="sent_today",
                            last_error=biz_tianji_trial_daily_auto.SENT_TODAY_ERROR,
                        )
                        continue
                    if tianji_trial_miniapp.get_pending_tianji_trial_request(
                        read_cached_external_payload(storage, int(profile_id))
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            last_run_at=now,
                            next_run_at=tomorrow_run_at,
                            workflow_state="sent_today",
                            last_error="已有天机试炼自动请求在运行，等待明日固定时间。",
                        )
                        continue
                    _queue_tianji_trial_daily_request(
                        storage,
                        profile_id=int(profile_id),
                        chat_id=chat_id,
                        thread_id=thread_id,
                        chat_type=str(task.get("chat_type") or "group"),
                        bot_username=str(task.get("bot_username") or ""),
                    )
                    storage.update_companion_auto_task(
                        task_id,
                        last_run_at=now,
                        next_run_at=tomorrow_run_at,
                        workflow_state="sent_today",
                        last_error=biz_tianji_trial_daily_auto.SENT_TODAY_ERROR,
                    )
                    continue

                if feature_key == biz_estate_hunt_daily_auto.FEATURE_KEY:
                    chat_id = int(task.get("chat_id") or 0)
                    if not chat_id:
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            last_error="Chat ID missing",
                        )
                        continue
                    thread_id = (
                        int(task.get("thread_id")) if task.get("thread_id") else None
                    )
                    run_time = biz_estate_hunt_daily_auto.normalize_run_time(
                        task.get("strategy")
                    )
                    next_run_at = float(task.get("next_run_at") or 0)
                    if next_run_at > now:
                        continue
                    tomorrow_run_at = biz_estate_hunt_daily_auto.resolve_next_run_at(
                        run_time,
                        now=now,
                        force_tomorrow=True,
                    )
                    last_run_at = float(task.get("last_run_at") or 0)
                    if biz_estate_hunt_daily_auto.is_same_local_day(last_run_at, now):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=tomorrow_run_at,
                            workflow_state="sent_today",
                            last_error=biz_estate_hunt_daily_auto.SENT_TODAY_ERROR,
                        )
                        continue
                    limit_reached = False

                    def queue_estate_request(latest: dict) -> dict:
                        nonlocal limit_reached
                        if estate_miniapp.is_estate_miniapp_hunt_limit_reached(
                            latest
                        ):
                            limit_reached = True
                            return estate_miniapp.mark_estate_miniapp_hunt_limit_reached(
                                latest
                            )
                        return estate_miniapp.queue_estate_miniapp_hunt_request(
                            latest,
                            chat_id=chat_id,
                            thread_id=thread_id,
                            chat_type=str(task.get("chat_type") or "group"),
                            bot_username=str(task.get("bot_username") or ""),
                        )

                    _update_external_payload(
                        storage,
                        int(profile_id),
                        queue_estate_request,
                    )
                    if limit_reached:
                        storage.update_companion_auto_task(
                            task_id,
                            last_run_at=now,
                            next_run_at=tomorrow_run_at,
                            workflow_state="limit_reached",
                            last_error=biz_estate_hunt_daily_auto.LIMIT_REACHED_ERROR,
                        )
                        continue
                    storage.update_companion_auto_task(
                        task_id,
                        last_run_at=now,
                        next_run_at=tomorrow_run_at,
                        workflow_state="sent_today",
                        last_error=biz_estate_hunt_daily_auto.SENT_TODAY_ERROR,
                    )
                    continue

                if feature_key == biz_beast_merge_daily_auto.FEATURE_KEY:
                    chat_id = int(task.get("chat_id") or 0)
                    if not chat_id:
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            last_error="Chat ID missing",
                        )
                        continue
                    next_run_at = float(task.get("next_run_at") or 0)
                    if next_run_at > now:
                        continue
                    run_time = biz_beast_merge_daily_auto.normalize_run_time(
                        task.get("strategy")
                    )
                    tomorrow_run_at = biz_beast_merge_daily_auto.resolve_next_run_at(
                        run_time,
                        now=now,
                        force_tomorrow=True,
                    )
                    latest_payload = read_cached_external_payload(storage, int(profile_id))
                    last_run_at = float(task.get("last_run_at") or 0)
                    if (
                        biz_beast_merge_daily_auto.is_same_local_day(last_run_at, now)
                        or biz_beast_merge_state.was_beast_merge_requested_today(
                            latest_payload,
                            now=now,
                        )
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            last_run_at=now,
                            next_run_at=tomorrow_run_at,
                            workflow_state="sent_today",
                            last_error=biz_beast_merge_daily_auto.SENT_TODAY_ERROR,
                        )
                        continue
                    if biz_beast_merge_state.get_pending_beast_merge_request(latest_payload):
                        storage.update_companion_auto_task(
                            task_id,
                            last_run_at=now,
                            next_run_at=tomorrow_run_at,
                            workflow_state="sent_today",
                            last_error="已有噬金虫自动请求在运行，等待明日固定时间。",
                        )
                        continue
                    if biz_beast_merge_state.is_beast_merge_daily_limit_reached(latest_payload):
                        storage.update_companion_auto_task(
                            task_id,
                            last_run_at=now,
                            next_run_at=tomorrow_run_at,
                            workflow_state="limit_reached",
                            last_error=biz_beast_merge_daily_auto.LIMIT_REACHED_ERROR,
                        )
                        continue
                    thread_id = (
                        int(task.get("thread_id")) if task.get("thread_id") else None
                    )
                    _update_external_payload(
                        storage,
                        int(profile_id),
                        lambda latest: biz_beast_merge_state.queue_beast_merge_request(
                            latest,
                            chat_id=chat_id,
                            thread_id=thread_id,
                            chat_type=str(task.get("chat_type") or "group"),
                            bot_username=str(task.get("bot_username") or ""),
                        ),
                    )
                    storage.update_companion_auto_task(
                        task_id,
                        last_run_at=now,
                        next_run_at=tomorrow_run_at,
                        workflow_state="sent_today",
                        last_error=biz_beast_merge_daily_auto.SENT_TODAY_ERROR,
                    )
                    continue

                if feature_key == biz_luoyun_spirit_tree_daily_auto.FEATURE_KEY:
                    chat_id = int(task.get("chat_id") or 0)
                    if not chat_id:
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            last_error="Chat ID missing",
                        )
                        continue
                    profile = storage.get_profile(int(profile_id))
                    if not biz_luoyun_spirit_tree_daily_auto.is_allowed_profile(profile):
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            next_run_at=0,
                            last_error="当前角色已不是落云宗，已关闭每日云梦山灵眼赛。",
                        )
                        continue
                    next_run_at = float(task.get("next_run_at") or 0)
                    if next_run_at > now:
                        continue
                    run_time = biz_luoyun_spirit_tree_daily_auto.normalize_run_time(
                        task.get("strategy")
                    )
                    tomorrow_run_at = biz_luoyun_spirit_tree_daily_auto.resolve_next_run_at(
                        run_time,
                        now=now,
                        force_tomorrow=True,
                    )
                    latest_payload = read_cached_external_payload(
                        storage,
                        int(profile_id),
                    )
                    if luoyun_spirit_tree_miniapp.is_luoyun_spirit_tree_daily_target_reached(
                        latest_payload,
                        now=now,
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            last_run_at=now,
                            next_run_at=tomorrow_run_at,
                            workflow_state="completed_today",
                            retry_count=0,
                            last_error=(
                                biz_luoyun_spirit_tree_daily_auto.COMPLETED_TODAY_ERROR
                            ),
                        )
                        continue
                    if luoyun_spirit_tree_miniapp.get_pending_luoyun_spirit_tree_request(
                        latest_payload
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now
                            + luoyun_spirit_tree_miniapp.LUOYUN_SPIRIT_TREE_PENDING_RETRY_SECONDS,
                            workflow_state=(
                                str(task.get("workflow_state") or "") or "running"
                            ),
                        )
                        continue
                    updated_payload = luoyun_spirit_tree_miniapp.queue_luoyun_spirit_tree_request(
                        latest_payload,
                        chat_id=chat_id,
                        thread_id=(
                            int(task.get("thread_id"))
                            if task.get("thread_id")
                            else None
                        ),
                        chat_type=str(task.get("chat_type") or "group"),
                        bot_username=str(task.get("bot_username") or "fanrenxiuxian_bot"),
                        run_mode="daily",
                    )
                    _save_luoyun_spirit_tree_profile_payload(
                        storage,
                        int(profile_id),
                        updated_payload,
                    )
                    storage.update_companion_auto_task(
                        task_id,
                        last_run_at=now,
                        next_run_at=now
                        + luoyun_spirit_tree_miniapp.LUOYUN_SPIRIT_TREE_PENDING_RETRY_SECONDS,
                        workflow_state="running",
                        retry_count=0,
                        last_error="云梦山灵眼赛已排队，等待公共洞府入口。",
                    )
                    continue

                if feature_key == biz_fishing_daily_auto.FEATURE_KEY:
                    chat_id = int(task.get("chat_id") or 0)
                    if not chat_id:
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            last_error="Chat ID missing",
                        )
                        continue
                    next_run_at = float(task.get("next_run_at") or 0)
                    if next_run_at > now:
                        continue
                    run_time = biz_fishing_daily_auto.normalize_run_time(
                        task.get("strategy")
                    )
                    tomorrow_run_at = biz_fishing_daily_auto.resolve_next_run_at(
                        run_time,
                        now=now,
                        force_tomorrow=True,
                    )
                    last_run_at = float(task.get("last_run_at") or 0)
                    if biz_fishing_daily_auto.is_same_local_day(last_run_at, now):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=tomorrow_run_at,
                            workflow_state="sent_today",
                            last_error=biz_fishing_daily_auto.SENT_TODAY_ERROR,
                        )
                        continue
                    session = storage.get_fishing_session(int(profile_id), chat_id)
                    if (
                        session
                        and biz_fishing_daily_auto.is_same_local_day(
                            float(session.get("last_action_at") or 0),
                            now,
                        )
                        and _miniapp_int(session.get("daily_limit"), 0) > 0
                        and _miniapp_int(session.get("daily_count"), 0)
                        >= _miniapp_int(session.get("daily_limit"), 0)
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            last_run_at=now,
                            next_run_at=tomorrow_run_at,
                            workflow_state="completed_today",
                            last_error=biz_fishing_daily_auto.COMPLETED_TODAY_ERROR,
                        )
                        continue
                    if session and str(session.get("state") or "") in {
                        "miniapp_canary",
                        "miniapp_batch",
                        "miniapp_canary_running",
                        "miniapp_batch_running",
                    }:
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + 300,
                            last_error="已有灵溪垂钓任务在运行，稍后复查。",
                        )
                        continue
                    session_fields = {
                        "thread_id": (
                            int(task.get("thread_id")) if task.get("thread_id") else None
                        ),
                        "chat_type": str(task.get("chat_type") or "group"),
                        "bot_username": str(task.get("bot_username") or "fanrenxiuxian_bot"),
                        "enabled": True,
                        "state": "miniapp_batch",
                        "next_action_at": now,
                        "last_error": "每日灵溪垂钓已登记，等待公共洞府入口执行。",
                    }
                    if session and not biz_fishing_daily_auto.is_same_local_day(
                        float(session.get("last_action_at") or 0),
                        now,
                    ):
                        session_fields["daily_count"] = 0
                    if session:
                        storage.update_fishing_session(int(session["id"]), **session_fields)
                    else:
                        storage.upsert_fishing_session(
                            profile_id=int(profile_id),
                            chat_id=chat_id,
                            pond=biz_fishing_game.FISHING_DEFAULT_POND,
                            bait=biz_fishing_game.FISHING_DEFAULT_BAIT,
                            daily_limit=fishing_miniapp.FISHING_MINIAPP_DAILY_LIMIT_FALLBACK,
                            **session_fields,
                        )
                    storage.update_companion_auto_task(
                        task_id,
                        last_run_at=now,
                        next_run_at=tomorrow_run_at,
                        workflow_state="sent_today",
                        last_error=biz_fishing_daily_auto.SENT_TODAY_ERROR,
                    )
                    continue

                if feature_key == ARTIFACT_TOUCH_FEATURE_KEY:
                    chat_id = int(task.get("chat_id") or 0)
                    if not chat_id:
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            last_error="Chat ID missing",
                        )
                        continue
                    command_text, interval_seconds = _unpack_artifact_touch_strategy(
                        task.get("strategy") or ""
                    )
                    next_run_at = float(task.get("next_run_at") or 0)
                    workflow_state = str(task.get("workflow_state") or "").strip()
                    if workflow_state != ARTIFACT_TOUCH_BOT_COOLDOWN_STATE and (
                        sync_artifact_touch_auto_from_latest_reply(
                            storage, int(profile_id), task, now=now
                        )
                    ):
                        continue
                    if (
                        workflow_state == ARTIFACT_TOUCH_PROBE_PENDING_STATE
                        and next_run_at <= now
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + interval_seconds,
                            workflow_state=ARTIFACT_TOUCH_INTERNAL_WAIT_STATE,
                            last_error="补发抚摸仍未提供冷却，按设置间隔等待下次尝试。",
                        )
                        continue
                    if (
                        workflow_state == ARTIFACT_TOUCH_AWAIT_REPLY_STATE
                        and next_run_at <= now
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + interval_seconds,
                            workflow_state=ARTIFACT_TOUCH_INTERNAL_WAIT_STATE,
                            last_error="未解析到bot回包冷却，按设置间隔等待下次尝试。",
                        )
                        continue
                    if next_run_at > now:
                        continue
                    thread_id = (
                        int(task.get("thread_id")) if task.get("thread_id") else None
                    )
                    if _has_pending_outgoing_command(
                        storage,
                        profile_id=int(profile_id),
                        chat_id=chat_id,
                        text=command_text,
                        thread_id=thread_id,
                    ):
                        continue
                    storage.enqueue_outgoing_command(
                        profile_id=int(profile_id),
                        chat_id=chat_id,
                        text=command_text,
                        thread_id=thread_id,
                        chat_type=str(task.get("chat_type") or "group"),
                        bot_username=str(task.get("bot_username") or ""),
                    )
                    storage.update_companion_auto_task(
                        task_id,
                        last_run_at=now,
                        next_run_at=now + ARTIFACT_TOUCH_REPLY_WAIT_SECONDS,
                        workflow_state=ARTIFACT_TOUCH_AWAIT_REPLY_STATE,
                        last_error="已发送抚摸法宝，等待bot回包。",
                    )
                    continue

                if feature_key == ARTIFACT_TRIAL_FEATURE_KEY:
                    chat_id = int(task.get("chat_id") or 0)
                    if not chat_id:
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            last_error="Chat ID missing",
                        )
                        continue
                    artifact_name, route = _unpack_artifact_trial_strategy(
                        task.get("strategy") or ""
                    )
                    command_text = _build_artifact_trial_command(artifact_name, route)
                    next_run_at = float(task.get("next_run_at") or 0)
                    workflow_state = str(task.get("workflow_state") or "").strip()
                    if workflow_state != ARTIFACT_TRIAL_BOT_COOLDOWN_STATE and (
                        sync_artifact_trial_auto_from_latest_reply(
                            storage, int(profile_id), task, now=now
                        )
                    ):
                        continue
                    if (
                        workflow_state == ARTIFACT_TRIAL_AWAIT_REPLY_STATE
                        and next_run_at <= now
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + ARTIFACT_TRIAL_DEFAULT_COOLDOWN_SECONDS,
                            workflow_state=ARTIFACT_TRIAL_INTERNAL_WAIT_STATE,
                            last_error="未解析到bot回包冷却，按8小时默认冷却等待下次尝试。",
                        )
                        continue
                    if next_run_at > now:
                        continue
                    thread_id = (
                        int(task.get("thread_id")) if task.get("thread_id") else None
                    )
                    fresh_payload = await asyncio.to_thread(
                        _refresh_companion_payload, storage, int(profile_id)
                    )
                    if fresh_payload and isinstance(fresh_payload, dict):
                        payload = fresh_payload
                    resources = build_artifact_trial_resource_state(
                        payload,
                        storage.get_game_items(),
                    )
                    if not resources.get("ok"):
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            next_run_at=0,
                            workflow_state=ARTIFACT_TRIAL_STOPPED_RESOURCES_STATE,
                            last_error=str(resources.get("error_text") or "资源不足。"),
                        )
                        continue
                    if _has_pending_outgoing_command(
                        storage,
                        profile_id=int(profile_id),
                        chat_id=chat_id,
                        text=command_text,
                        thread_id=thread_id,
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + 60,
                            last_error="已有器灵试炼命令待发送，稍后复查。",
                        )
                        continue
                    storage.enqueue_outgoing_command(
                        profile_id=int(profile_id),
                        chat_id=chat_id,
                        text=command_text,
                        thread_id=thread_id,
                        chat_type=str(task.get("chat_type") or "group"),
                        bot_username=str(task.get("bot_username") or ""),
                    )
                    storage.update_companion_auto_task(
                        task_id,
                        last_run_at=now,
                        next_run_at=now + ARTIFACT_TRIAL_REPLY_WAIT_SECONDS,
                        workflow_state=ARTIFACT_TRIAL_AWAIT_REPLY_STATE,
                        last_error="已发送器灵试炼，等待bot回包。",
                    )
                    continue

                if feature_key == ARTIFACT_NURTURE_FEATURE_KEY:
                    chat_id = int(task.get("chat_id") or 0)
                    if not chat_id:
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            last_error="Chat ID missing",
                        )
                        continue
                    target_name = _unpack_artifact_nurture_strategy(
                        task.get("strategy") or ""
                    )
                    command_text = _build_artifact_nurture_command(target_name)
                    next_run_at = float(task.get("next_run_at") or 0)
                    workflow_state = str(task.get("workflow_state") or "").strip()
                    if workflow_state != ARTIFACT_NURTURE_BOT_COOLDOWN_STATE and (
                        sync_artifact_nurture_auto_from_latest_reply(
                            storage, int(profile_id), task, now=now
                        )
                    ):
                        continue
                    if (
                        workflow_state == ARTIFACT_NURTURE_AWAIT_REPLY_STATE
                        and next_run_at <= now
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + ARTIFACT_NURTURE_DEFAULT_COOLDOWN_SECONDS,
                            workflow_state=ARTIFACT_NURTURE_INTERNAL_WAIT_STATE,
                            last_error="未解析到bot回包冷却，按6小时默认冷却等待下次尝试。",
                        )
                        continue
                    if next_run_at > now:
                        continue
                    thread_id = (
                        int(task.get("thread_id")) if task.get("thread_id") else None
                    )
                    fresh_payload = await asyncio.to_thread(
                        _refresh_companion_payload, storage, int(profile_id)
                    )
                    if fresh_payload and isinstance(fresh_payload, dict):
                        payload = fresh_payload
                    resources = build_artifact_nurture_resource_state(
                        payload,
                        storage.get_game_items(),
                    )
                    if not resources.get("ok"):
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            next_run_at=0,
                            workflow_state=ARTIFACT_NURTURE_STOPPED_RESOURCES_STATE,
                            last_error=str(resources.get("error_text") or "资源不足。"),
                        )
                        continue
                    if _has_pending_outgoing_command(
                        storage,
                        profile_id=int(profile_id),
                        chat_id=chat_id,
                        text=command_text,
                        thread_id=thread_id,
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + 60,
                            last_error="已有温养器灵命令待发送，稍后复查。",
                        )
                        continue
                    storage.enqueue_outgoing_command(
                        profile_id=int(profile_id),
                        chat_id=chat_id,
                        text=command_text,
                        thread_id=thread_id,
                        chat_type=str(task.get("chat_type") or "group"),
                        bot_username=str(task.get("bot_username") or ""),
                    )
                    storage.update_companion_auto_task(
                        task_id,
                        last_run_at=now,
                        next_run_at=now + ARTIFACT_NURTURE_REPLY_WAIT_SECONDS,
                        workflow_state=ARTIFACT_NURTURE_AWAIT_REPLY_STATE,
                        last_error="已发送温养器灵，等待bot回包。",
                    )
                    continue

                if feature_key == WANLING_ROAM_FEATURE_KEY:
                    chat_id = int(task.get("chat_id") or 0)
                    if not chat_id:
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            last_error="Chat ID missing",
                        )
                        continue
                    profile = storage.get_profile(int(profile_id))
                    if not profile or not is_wanling_profile(profile):
                        thread_id = (
                            int(task.get("thread_id")) if task.get("thread_id") else None
                        )
                        for command_text in build_wanling_roam_cancel_commands(
                            task.get("strategy")
                        ):
                            storage.cancel_pending_outgoing_commands(
                                int(profile_id),
                                chat_id,
                                command_text,
                                thread_id=thread_id,
                                require_exact_thread=thread_id is not None,
                            )
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            next_run_at=0,
                            workflow_state="stopped_non_wanling",
                            last_error="当前角色不是万灵宗，已停止自动一键放养。",
                        )
                        continue
                    next_run_at = float(task.get("next_run_at") or 0)
                    if next_run_at > now:
                        resolved_next_finish_at = _resolve_wanling_roam_next_finish_at(
                            payload
                        )
                        if (
                            resolved_next_finish_at is not None
                            and resolved_next_finish_at > now
                            and next_run_at < resolved_next_finish_at
                        ):
                            storage.update_companion_auto_task(
                                task_id,
                                next_run_at=(
                                    resolved_next_finish_at
                                    + WANLING_ROAM_AUTO_AFTER_RETURN_SECONDS
                                ),
                                last_error="",
                            )
                        continue

                    fresh_payload = await asyncio.to_thread(
                        _refresh_companion_payload, storage, int(profile_id)
                    )
                    if fresh_payload and isinstance(fresh_payload, dict):
                        payload = fresh_payload
                    resolved_next_finish_at = _resolve_wanling_roam_next_finish_at(
                        payload
                    )
                    if resolved_next_finish_at is None:
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + WANLING_ROAM_RECHECK_SECONDS,
                            last_error="刷新灵兽放养数据失败，5分钟后重试。",
                        )
                        continue
                    if resolved_next_finish_at > now:
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=(
                                resolved_next_finish_at
                                + WANLING_ROAM_AUTO_AFTER_RETURN_SECONDS
                            ),
                            last_error="",
                        )
                        continue

                    thread_id = (
                        int(task.get("thread_id")) if task.get("thread_id") else None
                    )
                    command_sequence = build_wanling_roam_command_sequence(
                        task.get("strategy"), payload
                    )
                    has_pending_command = False
                    for command_text in build_wanling_roam_cancel_commands(
                        task.get("strategy")
                    ):
                        if _has_pending_outgoing_command(
                            storage,
                            profile_id=int(profile_id),
                            chat_id=chat_id,
                            text=command_text,
                            thread_id=thread_id,
                        ):
                            has_pending_command = True
                            break
                    if has_pending_command:
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + 60,
                            last_error="已有灵兽放养命令待发送，稍后复查。",
                        )
                        continue

                    last_run_at = float(task.get("last_run_at") or 0)
                    if (
                        last_run_at
                        and (now - last_run_at) < WANLING_ROAM_POST_SEND_GRACE_SECONDS
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + WANLING_ROAM_RECHECK_SECONDS,
                            last_error="已发送灵兽放养序列，等待天机阁刷新。",
                        )
                        continue

                    for index, command_text in enumerate(command_sequence):
                        storage.enqueue_outgoing_command(
                            profile_id=int(profile_id),
                            chat_id=chat_id,
                            text=command_text,
                            thread_id=thread_id,
                            chat_type=str(task.get("chat_type") or "group"),
                            bot_username=str(task.get("bot_username") or ""),
                            delay_seconds=index * WANLING_ROAM_COMMAND_DELAY_SECONDS,
                        )
                    storage.update_companion_auto_task(
                        task_id,
                        last_run_at=now,
                        next_run_at=now + WANLING_ROAM_RECHECK_SECONDS,
                        last_error=(
                            "已发送灵兽巡游、安抚和一键放养，等待天机阁刷新。"
                            if len(command_sequence) > 1
                            else "已发送一键放养，等待天机阁刷新。"
                        ),
                    )
                    continue

                if feature_key == XINGGONG_STARBOARD_FEATURE_KEY:
                    chat_id = int(task.get("chat_id") or 0)
                    if not chat_id:
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            last_error="Chat ID missing",
                        )
                        continue
                    profile = storage.get_profile(int(profile_id))
                    if not profile or str(profile.sect_name or "").strip() != "星宫":
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            last_error="当前角色已不是星宫，已关闭自动星辰采集。",
                        )
                        continue
                    next_run_at = float(task.get("next_run_at") or 0)
                    if next_run_at > now:
                        continue

                    thread_id = (
                        int(task.get("thread_id")) if task.get("thread_id") else None
                    )
                    latest_payload = read_cached_external_payload(
                        storage,
                        int(profile_id),
                    )
                    cached_next_run_at = build_starboard_next_check_time(
                        latest_payload,
                        now,
                    )
                    if (
                        get_starboard_plots(latest_payload)
                        and cached_next_run_at
                        > now + XINGGONG_STARBOARD_READY_CHECK_SECONDS
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=cached_next_run_at,
                            last_error="星盘冷却中，按冷却或30分钟健康检查复查 MiniApp 状态。",
                        )
                        continue
                    if xinggong_miniapp.get_pending_xinggong_starboard_request(
                        latest_payload
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + XINGGONG_STARBOARD_PENDING_CHECK_SECONDS,
                            last_error="已有星宫 MiniApp 自动采集请求在运行，稍后复查。",
                        )
                        continue
                    updated_payload = xinggong_miniapp.queue_xinggong_starboard_request(
                        latest_payload,
                        chat_id=chat_id,
                        thread_id=thread_id,
                        chat_type=str(task.get("chat_type") or "group"),
                        bot_username=str(task.get("bot_username") or ""),
                        target_star=_normalize_xinggong_starboard_target(
                            task.get("strategy")
                        ),
                    )
                    external_account = storage.get_external_account(
                        int(profile_id),
                        ASC_PROVIDER,
                    ) or {}
                    storage.upsert_external_account(
                        int(profile_id),
                        ASC_PROVIDER,
                        str(
                            external_account.get("telegram_user_id")
                            or (profile.telegram_user_id if profile else "")
                            or ""
                        ),
                        str(
                            external_account.get("telegram_username")
                            or (profile.telegram_username if profile else "")
                            or ""
                        ),
                        str(external_account.get("status") or "connected"),
                        str(external_account.get("cookie_text") or ""),
                        updated_payload,
                        str(external_account.get("api_token") or ""),
                    )
                    storage.cancel_pending_outgoing_commands(
                        int(profile_id),
                        chat_id,
                        text=xinggong_miniapp.XINGGONG_STARBOARD_COMMAND,
                        thread_id=thread_id,
                        require_exact_thread=True,
                    )
                    storage.update_companion_auto_task(
                        task_id,
                        next_run_at=now + XINGGONG_STARBOARD_PENDING_CHECK_SECONDS,
                        last_error="已登记公共洞府星宫入口请求，等待执行。",
                    )
                    continue

                if feature_key == mulan_feature.MULAN_AUTO_SUPPORT_FEATURE_KEY:
                    _run_mulan_auto_task_step(
                        storage,
                        profile_id=int(profile_id),
                        task=task,
                        now=now,
                    )
                    continue

                if feature_key == biz_small_world_game.SMALL_WORLD_PREACH_AUTO_FEATURE_KEY:
                    chat_id = int(task.get("chat_id") or 0)
                    if not chat_id:
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            last_error="Chat ID missing",
                        )
                        continue
                    thread_id = (
                        int(task.get("thread_id")) if task.get("thread_id") else None
                    )
                    full_auto_task = storage.get_companion_auto_task(
                        int(profile_id),
                        chat_id,
                        biz_small_world_game.SMALL_WORLD_AUTO_FEATURE_KEY,
                    )
                    if full_auto_task and bool(full_auto_task.get("enabled")):
                        storage.cancel_pending_outgoing_commands(
                            int(profile_id),
                            chat_id,
                            text=biz_small_world_game.SMALL_WORLD_PREACH_COMMAND,
                            thread_id=thread_id,
                            require_exact_thread=True,
                        )
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            next_run_at=0,
                            last_error="自动小世界运行中，已关闭自动神迹布道。",
                        )
                        continue
                    next_run_at = float(task.get("next_run_at") or 0)
                    if next_run_at > now:
                        continue
                    preach_cooldown_until = _resolve_small_world_preach_cooldown_until(
                        storage,
                        profile_id=int(profile_id),
                        chat_id=chat_id,
                        thread_id=thread_id,
                    )
                    if preach_cooldown_until > now:
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=preach_cooldown_until,
                            last_error="",
                        )
                        continue
                    if _has_pending_outgoing_command(
                        storage,
                        profile_id=int(profile_id),
                        chat_id=chat_id,
                        text=biz_small_world_game.SMALL_WORLD_PREACH_COMMAND,
                        thread_id=thread_id,
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + SMALL_WORLD_PANEL_RETRY_SECONDS,
                            last_error="等待神迹布道发送或确认。",
                        )
                        continue
                    last_run_at = float(task.get("last_run_at") or 0)
                    if (
                        last_run_at
                        and (now - last_run_at) < COMPANION_AUTO_POST_SEND_GRACE_SECONDS
                    ):
                        continue
                    storage.enqueue_outgoing_command(
                        profile_id=int(profile_id),
                        chat_id=chat_id,
                        text=biz_small_world_game.SMALL_WORLD_PREACH_COMMAND,
                        thread_id=thread_id,
                        chat_type=str(task.get("chat_type") or "group"),
                        bot_username=str(task.get("bot_username") or ""),
                    )
                    storage.update_companion_auto_task(
                        task_id,
                        last_run_at=now,
                        next_run_at=now + COMPANION_AUTO_POST_SEND_GRACE_SECONDS,
                        last_error="已发送神迹布道，等待回包更新冷却。",
                    )
                    continue

                if feature_key == biz_small_world_game.SMALL_WORLD_AUTO_FEATURE_KEY:
                    chat_id = int(task.get("chat_id") or 0)
                    if not chat_id:
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            last_error="Chat ID missing",
                        )
                        continue
                    next_run_at = float(task.get("next_run_at") or 0)
                    thread_id = (
                        int(task.get("thread_id")) if task.get("thread_id") else None
                    )
                    strategy = biz_small_world_game.unpack_auto_strategy(
                        task.get("strategy") or ""
                    )
                    small_world_commands = [
                        biz_small_world_game.SMALL_WORLD_PANEL_COMMAND,
                        *SMALL_WORLD_ACTION_COMMANDS,
                    ]
                    workflow_state = str(task.get("workflow_state") or "").strip()
                    awaited_action_command = resolve_awaited_action_command(workflow_state)

                    if next_run_at > now:
                        last_run_at = float(task.get("last_run_at") or 0)
                        if workflow_state or not last_run_at:
                            continue
                        panel_reply = _get_latest_profile_command_reply(
                            storage,
                            profile_id=int(profile_id),
                            chat_id=chat_id,
                            thread_id=thread_id,
                            command_text=biz_small_world_game.SMALL_WORLD_PANEL_COMMAND,
                            since_ts=last_run_at + 0.001,
                        )
                        if not panel_reply:
                            continue
                        panel_state = biz_small_world_game.parse_small_world_reply(
                            str(panel_reply.get("text") or ""),
                            created_at=float(panel_reply.get("created_at") or 0),
                        )
                        if not panel_state.get("opened"):
                            continue
                        preach_cooldown_until = _resolve_small_world_preach_cooldown_until(
                            storage,
                            profile_id=int(profile_id),
                            chat_id=chat_id,
                            thread_id=thread_id,
                        )
                        command_texts = build_auto_action_commands(
                            panel_state,
                            strategy,
                            now=now,
                            preach_cooldown_until=preach_cooldown_until,
                        )
                        pending_action_commands = {
                            command_text
                            for command_text in SMALL_WORLD_ACTION_COMMANDS
                            if _has_pending_outgoing_command(
                                    storage,
                                    profile_id=int(profile_id),
                                    chat_id=chat_id,
                                    text=command_text,
                                    thread_id=thread_id,
                                )
                        }
                        command_text = select_next_action_command(
                            command_texts,
                            pending_action_commands,
                        )
                        if not command_text:
                            continue
                        storage.enqueue_outgoing_command(
                            profile_id=int(profile_id),
                            chat_id=chat_id,
                            text=command_text,
                            thread_id=thread_id,
                            chat_type=str(task.get("chat_type") or "group"),
                            bot_username=str(task.get("bot_username") or ""),
                        )
                        storage.update_companion_auto_task(
                            task_id,
                            last_run_at=now,
                            next_run_at=now + SMALL_WORLD_PANEL_RETRY_SECONDS,
                            workflow_state=SMALL_WORLD_ACTION_STATES_BY_COMMAND[
                                command_text
                            ],
                            last_error=f"已根据最新小世界回包发送{command_text}，等待回包。",
                        )
                        continue

                    if awaited_action_command:
                        last_run_at = float(task.get("last_run_at") or 0)
                        if _has_pending_outgoing_command(
                            storage,
                            profile_id=int(profile_id),
                            chat_id=chat_id,
                            text=awaited_action_command,
                            thread_id=thread_id,
                        ):
                            storage.update_companion_auto_task(
                                task_id,
                                next_run_at=now + SMALL_WORLD_PANEL_RETRY_SECONDS,
                                last_error=f"等待{awaited_action_command}发送或确认。",
                            )
                            continue
                        action_reply = _get_latest_profile_command_reply(
                            storage,
                            profile_id=int(profile_id),
                            chat_id=chat_id,
                            thread_id=thread_id,
                            command_text=awaited_action_command,
                            since_ts=max(last_run_at - 2, 0),
                        )
                        if action_reply:
                            if (
                                awaited_action_command
                                == biz_small_world_game.SMALL_WORLD_COLLECT_COMMAND
                                and strategy["quench_after_collect_enabled"]
                            ):
                                quench_command = build_quench_command_from_collect_reply(
                                    str(action_reply.get("text") or "")
                                )
                                if quench_command:
                                    storage.enqueue_outgoing_command(
                                        profile_id=int(profile_id),
                                        chat_id=chat_id,
                                        text=quench_command,
                                        thread_id=thread_id,
                                        chat_type=str(task.get("chat_type") or "group"),
                                        bot_username=str(task.get("bot_username") or ""),
                                    )
                                    storage.update_companion_auto_task(
                                        task_id,
                                        last_run_at=now,
                                        next_run_at=now + SMALL_WORLD_PANEL_RETRY_SECONDS,
                                        workflow_state=build_quench_reply_state(
                                            quench_command
                                        ),
                                        last_error=(
                                            f"已收到{awaited_action_command}回包，"
                                            f"已发送{quench_command}，等待回包。"
                                        ),
                                    )
                                    continue
                            storage.update_companion_auto_task(
                                task_id,
                                last_run_at=now,
                                next_run_at=now
                                + int(strategy["refresh_interval_seconds"]),
                                workflow_state="",
                                last_error=f"已收到{awaited_action_command}回包，下轮重新刷新判断。",
                            )
                            continue
                        if (
                            last_run_at
                            and now - last_run_at
                            < SMALL_WORLD_ACTION_REPLY_WAIT_SECONDS
                        ):
                            storage.update_companion_auto_task(
                                task_id,
                                next_run_at=now + SMALL_WORLD_PANEL_RETRY_SECONDS,
                                last_error=f"等待{awaited_action_command}回包。",
                            )
                            continue
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + int(strategy["refresh_interval_seconds"]),
                            workflow_state="",
                            last_error=f"未收到{awaited_action_command}回包，下轮重新刷新。",
                        )
                        continue

                    if workflow_state != "await_panel_reply":
                        if any(
                            _has_pending_outgoing_command(
                                storage,
                                profile_id=int(profile_id),
                                chat_id=chat_id,
                                text=command_text,
                                thread_id=thread_id,
                            )
                            for command_text in small_world_commands
                        ):
                            storage.update_companion_auto_task(
                                task_id,
                                next_run_at=now + SMALL_WORLD_PANEL_WAIT_SECONDS,
                                last_error="已有小世界命令待发送，稍后复查。",
                            )
                            continue
                        storage.enqueue_outgoing_command(
                            profile_id=int(profile_id),
                            chat_id=chat_id,
                            text=biz_small_world_game.SMALL_WORLD_PANEL_COMMAND,
                            thread_id=thread_id,
                            chat_type=str(task.get("chat_type") or "group"),
                            bot_username=str(task.get("bot_username") or ""),
                        )
                        storage.update_companion_auto_task(
                            task_id,
                            last_run_at=now,
                            next_run_at=now + SMALL_WORLD_PANEL_WAIT_SECONDS,
                            workflow_state="await_panel_reply",
                            last_error="已发送小世界，等待状态回包。",
                        )
                        continue

                    last_run_at = float(task.get("last_run_at") or 0)
                    if _has_pending_outgoing_command(
                        storage,
                        profile_id=int(profile_id),
                        chat_id=chat_id,
                        text=biz_small_world_game.SMALL_WORLD_PANEL_COMMAND,
                        thread_id=thread_id,
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + SMALL_WORLD_PANEL_RETRY_SECONDS,
                            last_error="等待小世界发送或确认。",
                        )
                        continue
                    panel_reply = _get_latest_profile_command_reply(
                        storage,
                        profile_id=int(profile_id),
                        chat_id=chat_id,
                        thread_id=thread_id,
                        command_text=biz_small_world_game.SMALL_WORLD_PANEL_COMMAND,
                        since_ts=max(last_run_at - 2, 0),
                    )
                    if not panel_reply:
                        if last_run_at and now - last_run_at < SMALL_WORLD_PANEL_WAIT_SECONDS:
                            storage.update_companion_auto_task(
                                task_id,
                                next_run_at=now + SMALL_WORLD_PANEL_RETRY_SECONDS,
                                last_error="等待小世界状态回包。",
                            )
                            continue
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + int(strategy["refresh_interval_seconds"]),
                            workflow_state="",
                            last_error="未收到小世界回包，下轮重新刷新。",
                        )
                        continue

                    panel_state = biz_small_world_game.parse_small_world_reply(
                        str(panel_reply.get("text") or ""),
                        created_at=float(panel_reply.get("created_at") or 0),
                    )
                    if not panel_state.get("opened"):
                        storage.update_companion_auto_task(
                            task_id,
                            last_run_at=now,
                            next_run_at=now + int(strategy["refresh_interval_seconds"]),
                            workflow_state="",
                            last_error="小世界未开辟或状态不可识别。",
                        )
                        continue

                    preach_cooldown_until = _resolve_small_world_preach_cooldown_until(
                        storage,
                        profile_id=int(profile_id),
                        chat_id=chat_id,
                        thread_id=thread_id,
                    )
                    command_texts = build_auto_action_commands(
                        panel_state,
                        strategy,
                        now=now,
                        preach_cooldown_until=preach_cooldown_until,
                    )
                    pending_action_commands = {
                        command_text
                        for command_text in SMALL_WORLD_ACTION_COMMANDS
                        if _has_pending_outgoing_command(
                                storage,
                                profile_id=int(profile_id),
                                chat_id=chat_id,
                                text=command_text,
                                thread_id=thread_id,
                            )
                    }
                    pending_action_command = next(
                        (
                            command_text
                            for command_text in SMALL_WORLD_ACTION_COMMANDS
                            if command_text in pending_action_commands
                        ),
                        "",
                    )
                    if pending_action_command:
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + int(strategy["refresh_interval_seconds"]),
                            workflow_state="",
                            last_error=(
                                f"已有{pending_action_command}待发送，"
                                "下轮重新刷新判断。"
                            ),
                        )
                        continue
                    command_text = select_next_action_command(
                        command_texts,
                        pending_action_commands,
                    )
                    if command_text:
                        storage.enqueue_outgoing_command(
                            profile_id=int(profile_id),
                            chat_id=chat_id,
                            text=command_text,
                            thread_id=thread_id,
                            chat_type=str(task.get("chat_type") or "group"),
                            bot_username=str(task.get("bot_username") or ""),
                        )
                        storage.update_companion_auto_task(
                            task_id,
                            last_run_at=now,
                            next_run_at=now + SMALL_WORLD_PANEL_RETRY_SECONDS,
                            workflow_state=SMALL_WORLD_ACTION_STATES_BY_COMMAND[
                                command_text
                            ],
                            last_error=f"已发送{command_text}，等待回包。",
                        )
                        continue
                    storage.update_companion_auto_task(
                        task_id,
                        last_run_at=now,
                        next_run_at=now + int(strategy["refresh_interval_seconds"]),
                        workflow_state="",
                        last_error="已刷新小世界，无需操作。",
                    )
                    continue

                if feature_key == COMPANION_VOYAGE_FEATURE_KEY:
                    chat_id = int(task.get("chat_id") or 0)
                    if not chat_id:
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            last_error="Chat ID missing",
                        )
                        continue
                    next_run_at = float(task.get("next_run_at") or 0)
                    if next_run_at > now:
                        continue
                    thread_id = (
                        int(task.get("thread_id")) if task.get("thread_id") else None
                    )
                    strategy = _normalize_companion_voyage_strategy(
                        task.get("strategy")
                    )
                    start_command = f".侍妾远航 {strategy}"
                    command_texts = [
                        COMPANION_VOYAGE_STATUS_COMMAND,
                        COMPANION_VOYAGE_RETURN_COMMAND,
                        start_command,
                    ]
                    if any(
                        _has_active_companion_voyage_command(
                            storage,
                            profile_id=int(profile_id),
                            chat_id=chat_id,
                            text=command_text,
                            thread_id=thread_id,
                        )
                        for command_text in command_texts
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + COMPANION_VOYAGE_RECHECK_SECONDS,
                            last_error="已有远航命令待发送，稍后复查。",
                        )
                        continue

                    panel_reply, panel_queued = _queue_companion_panel_refresh_if_needed(
                        storage,
                        profile_id=int(profile_id),
                        chat_id=chat_id,
                        thread_id=thread_id,
                        chat_type=str(task.get("chat_type") or "group"),
                        bot_username=str(task.get("bot_username") or ""),
                        now=now,
                    )
                    if panel_queued:
                        storage.update_companion_auto_task(
                            task_id,
                            last_run_at=now,
                            next_run_at=now + COMPANION_VOYAGE_RECHECK_SECONDS,
                            last_error="已发送我的侍妾，等待远航状态面板。",
                        )
                        continue

                    panel_state = _build_companion_voyage_state_from_reply(panel_reply)
                    panel_status = str(panel_state.get("status") or "")
                    if panel_status != "unknown":
                        voyage_state = panel_state
                    else:
                        voyage_reply = _get_latest_companion_voyage_reply(
                            storage,
                            profile_id=int(profile_id),
                            chat_id=chat_id,
                            thread_id=thread_id,
                        )
                        voyage_state = _build_companion_voyage_state_from_reply(
                            voyage_reply
                        )
                    voyage_target = float(voyage_state.get("target_ts") or 0)
                    voyage_status = str(voyage_state.get("status") or "")
                    if voyage_target > now:
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=voyage_target + 10,
                            last_error="",
                        )
                        continue
                    if voyage_status == "unknown":
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + COMPANION_VOYAGE_RECHECK_SECONDS,
                            last_error="侍妾面板缺少远航状态，稍后刷新再判断。",
                        )
                        continue
                    if voyage_status == "not_following":
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + 3600,
                            last_error="侍妾未随行，暂不能自动远航。",
                        )
                        continue

                    if voyage_status == "returned_waiting":
                        if not _is_recent_or_pending_outgoing_command(
                            storage,
                            profile_id=int(profile_id),
                            chat_id=chat_id,
                            text=COMPANION_VOYAGE_RETURN_COMMAND,
                            thread_id=thread_id,
                            now=now,
                            recent_seconds=COMPANION_VOYAGE_RECHECK_SECONDS,
                        ):
                            storage.enqueue_outgoing_command(
                                profile_id=int(profile_id),
                                chat_id=chat_id,
                                text=COMPANION_VOYAGE_RETURN_COMMAND,
                                thread_id=thread_id,
                                chat_type=str(task.get("chat_type") or "group"),
                                bot_username=str(task.get("bot_username") or ""),
                            )
                            last_run_at = now
                            last_error = "已发送远航归来，等待结算后刷新面板。"
                        else:
                            last_run_at = float(task.get("last_run_at") or 0)
                            last_error = "已发送远航归来，等待结算后刷新面板。"
                        storage.update_companion_auto_task(
                            task_id,
                            last_run_at=last_run_at,
                            next_run_at=now + COMPANION_VOYAGE_RECHECK_SECONDS,
                            last_error=last_error,
                        )
                        continue

                    fresh_payload = await asyncio.to_thread(
                        _refresh_companion_payload, storage, int(profile_id)
                    )
                    if fresh_payload and isinstance(fresh_payload, dict):
                        payload = fresh_payload
                    (
                        preflight_ready,
                        preflight_message,
                        preflight_next_run_at,
                    ) = _run_companion_voyage_preflight(
                        storage,
                        payload=payload if isinstance(payload, dict) else {},
                        profile_id=int(profile_id),
                        chat_id=chat_id,
                        thread_id=thread_id,
                        chat_type=str(task.get("chat_type") or "group"),
                        bot_username=str(task.get("bot_username") or ""),
                        now=now,
                    )
                    if not preflight_ready:
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=(
                                preflight_next_run_at
                                if preflight_next_run_at
                                and preflight_next_run_at > now
                                else now
                                + COMPANION_VOYAGE_PREFLIGHT_RECHECK_SECONDS
                            ),
                            last_error=preflight_message,
                        )
                        continue

                    if _is_recent_or_pending_outgoing_command(
                        storage,
                        profile_id=int(profile_id),
                        chat_id=chat_id,
                        text=start_command,
                        thread_id=thread_id,
                        now=now,
                        recent_seconds=COMPANION_VOYAGE_RECHECK_SECONDS,
                    ):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + COMPANION_VOYAGE_RECHECK_SECONDS,
                            last_error="已发送侍妾远航，等待状态确认。",
                        )
                        continue

                    commands_to_send = [
                        start_command,
                        COMPANION_VOYAGE_STATUS_COMMAND,
                    ]
                    for index, command_text in enumerate(commands_to_send):
                        storage.enqueue_outgoing_command(
                            profile_id=int(profile_id),
                            chat_id=chat_id,
                            text=command_text,
                            thread_id=thread_id,
                            chat_type=str(task.get("chat_type") or "group"),
                            bot_username=str(task.get("bot_username") or ""),
                            delay_seconds=index
                            * COMPANION_VOYAGE_RETURN_DELAY_SECONDS,
                        )
                    storage.update_companion_auto_task(
                        task_id,
                        last_run_at=now,
                        next_run_at=now + COMPANION_VOYAGE_RECHECK_SECONDS,
                        last_error="已发送侍妾远航，等待状态确认。",
                    )
                    continue

                resolved_next_run_at = _resolve_companion_next_run_at(
                    payload, feature_key
                )
                if feature_key in COMPANION_VOYAGE_PREFLIGHT_SIMPLE_FEATURES:
                    chat_id = int(task.get("chat_id") or 0)
                    if not chat_id:
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            last_error="Chat ID missing",
                        )
                        continue
                    thread_id = (
                        int(task.get("thread_id")) if task.get("thread_id") else None
                    )
                    if resolved_next_run_at is None or resolved_next_run_at <= now:
                        panel_reply, panel_queued = _queue_companion_panel_refresh_if_needed(
                            storage,
                            profile_id=int(profile_id),
                            chat_id=chat_id,
                            thread_id=thread_id,
                            chat_type=str(task.get("chat_type") or "group"),
                            bot_username=str(task.get("bot_username") or ""),
                            now=now,
                        )
                        if panel_queued:
                            storage.update_companion_auto_task(
                                task_id,
                                last_run_at=now,
                                next_run_at=now + COMPANION_VOYAGE_RECHECK_SECONDS,
                                last_error="已发送我的侍妾，等待面板冷却确认。",
                            )
                            continue
                        panel_target = _resolve_companion_panel_cooldown_target(
                            panel_reply,
                            feature_key,
                        )
                        if panel_target is None:
                            label = COMPANION_PANEL_COOLDOWN_LABELS.get(
                                feature_key,
                                feature_key,
                            )
                            storage.update_companion_auto_task(
                                task_id,
                                next_run_at=now + COMPANION_VOYAGE_RECHECK_SECONDS,
                                last_error=f"侍妾面板缺少{label}冷却，稍后刷新再判断。",
                            )
                            continue
                        if panel_target > now:
                            storage.update_companion_auto_task(
                                task_id,
                                next_run_at=panel_target,
                                last_error="",
                            )
                            continue
                        resolved_next_run_at = panel_target
                if resolved_next_run_at is None:
                    cancel_text = str(feature.get("command") or "")
                    if feature_key == "wild_experience":
                        cancel_text = f".野外历练 {_normalize_wild_experience_strategy(task.get('strategy'))}"
                    storage.cancel_pending_outgoing_commands(
                        int(profile_id),
                        int(task.get("chat_id") or 0),
                        text=cancel_text,
                    )
                    storage.update_companion_auto_task(
                        task_id,
                        enabled=0,
                        next_run_at=0,
                        last_error=f"最新 payload 缺少{feature.get('command') or feature_key}冷却字段，已停止自动。",
                    )
                    continue
                if feature_key == "wild_experience" and resolved_next_run_at <= now:
                    fresh_payload = await asyncio.to_thread(
                        _refresh_companion_payload, storage, int(profile_id)
                    )
                    if not fresh_payload or not isinstance(fresh_payload, dict):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=now + 300,
                            last_error="刷新野外历练冷却失败，5分钟后重试。",
                        )
                        continue
                    payload = fresh_payload
                    resolved_next_run_at = _resolve_companion_next_run_at(
                        fresh_payload, feature_key
                    )
                    if resolved_next_run_at is None:
                        cancel_text = f".野外历练 {_normalize_wild_experience_strategy(task.get('strategy'))}"
                        storage.cancel_pending_outgoing_commands(
                            int(profile_id),
                            int(task.get("chat_id") or 0),
                            text=cancel_text,
                        )
                        storage.update_companion_auto_task(
                            task_id,
                            enabled=0,
                            next_run_at=0,
                            last_error="最新 payload 缺少野外历练冷却字段，已停止自动。",
                        )
                        continue
                if resolved_next_run_at > now:
                    storage.update_companion_auto_task(
                        task_id,
                        next_run_at=resolved_next_run_at,
                        last_error="",
                    )
                    continue

                chat_id = int(task.get("chat_id") or 0)
                if not chat_id:
                    storage.update_companion_auto_task(
                        task_id,
                        enabled=0,
                        last_error="Chat ID missing",
                    )
                    continue

                thread_id = (
                    int(task.get("thread_id")) if task.get("thread_id") else None
                )
                command_text = str(feature.get("command") or "").strip()
                if feature_key == "wild_experience":
                    wild_strategy = _normalize_wild_experience_strategy(task.get("strategy"))
                    command_text = f".野外历练 {wild_strategy}"
                    gate = build_exploration_route_gate(
                        storage,
                        profile_id=int(profile_id),
                        chat_id=chat_id,
                        thread_id=thread_id,
                        chat_type=str(task.get("chat_type") or "group"),
                        bot_username=str(task.get("bot_username") or ""),
                        high_risk=wild_strategy == "深入",
                        now=now,
                    )
                    if not gate.get("allowed"):
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=float(gate.get("next_time") or now + 300),
                            last_error=(
                                f"天星宗探索 gate 阻断：{gate.get('reason') or '等待改命 探索确认'}"
                            ),
                        )
                        continue
                if feature_key in COMPANION_VOYAGE_PREFLIGHT_SIMPLE_FEATURES:
                    voyage_target = _resolve_active_companion_voyage_target(
                        storage,
                        profile_id=int(profile_id),
                        chat_id=chat_id,
                        thread_id=thread_id,
                        now=now,
                    )
                    if voyage_target > now:
                        storage.update_companion_auto_task(
                            task_id,
                            next_run_at=voyage_target + 10,
                            last_error="侍妾远航中，归航后再执行。",
                        )
                        continue

                if _has_pending_outgoing_command(
                    storage,
                    profile_id=int(profile_id),
                    chat_id=chat_id,
                    text=command_text,
                    thread_id=thread_id,
                ):
                    continue

                last_run_at = float(task.get("last_run_at") or 0)
                if (
                    last_run_at
                    and (now - last_run_at) < COMPANION_AUTO_POST_SEND_GRACE_SECONDS
                ):
                    continue

                storage.enqueue_outgoing_command(
                    profile_id=int(profile_id),
                    chat_id=chat_id,
                    text=command_text,
                    thread_id=thread_id,
                    chat_type=str(task.get("chat_type") or "group"),
                    bot_username=str(task.get("bot_username") or ""),
                )
                storage.update_companion_auto_task(
                    task_id,
                    last_run_at=now,
                    next_run_at=now + COMPANION_AUTO_POST_SEND_GRACE_SECONDS,
                    last_error="",
                )
            if run_once:
                return
            await asyncio.sleep(COMPANION_AUTO_POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Companion auto scheduler error for profile=%s: %s", profile_id, exc
            )
            if run_once:
                raise
            await asyncio.sleep(10)


async def _run_divination_batch_scheduler(
    client: object, storage: Storage, *, run_once: bool = False
) -> None:
    profile_id = getattr(client, "_tg_game_profile_id", None)
    if not profile_id:
        return

    while True:
        try:
            if profile_rebirth.is_profile_rebirth_locked(storage, int(profile_id)):
                if run_once:
                    return
                await asyncio.sleep(DIVINATION_BATCH_POLL_SECONDS)
                continue
            batch = storage.get_active_divination_batch(int(profile_id))
            if not batch:
                if run_once:
                    return
                await asyncio.sleep(DIVINATION_BATCH_POLL_SECONDS)
                continue

            batch_id = int(batch["id"])
            chat_id = int(batch.get("chat_id") or 0)
            thread_id = int(batch.get("thread_id")) if batch.get("thread_id") else None
            target_count = max(int(batch.get("target_count") or 0), 0)
            initial_count = max(int(batch.get("initial_count") or 0), 0)
            planned_rounds = max(target_count - initial_count, 0)
            sent_count = max(int(batch.get("sent_count") or 0), 0)
            last_dispatch_at = float(batch.get("last_dispatch_at") or 0)

            current_count = _get_cached_divination_today_count(storage, int(profile_id))
            completed_count = max(current_count - initial_count, 0)
            stored_completed = max(int(batch.get("completed_count") or 0), 0)
            if completed_count != stored_completed:
                batch = (
                    storage.update_divination_batch(
                        batch_id,
                        completed_count=completed_count,
                        pending_command_msg_id=0,
                        last_error="",
                    )
                    or batch
                )

            if current_count >= target_count:
                storage.cancel_pending_outgoing_commands(
                    int(profile_id), chat_id, text=DIVINATION_COMMAND
                )
                storage.finish_divination_batch(batch_id, status="completed")
                if run_once:
                    return
                await asyncio.sleep(DIVINATION_BATCH_POLL_SECONDS)
                continue

            latest_command = storage.get_latest_outgoing_command(
                chat_id,
                profile_id=int(profile_id),
                text=DIVINATION_COMMAND,
                thread_id=thread_id,
            )
            if _has_pending_outgoing_command(
                storage,
                profile_id=int(profile_id),
                chat_id=chat_id,
                text=DIVINATION_COMMAND,
                thread_id=thread_id,
            ):
                if run_once:
                    return
                await asyncio.sleep(DIVINATION_BATCH_POLL_SECONDS)
                continue

            now = time.time()
            effective_last_dispatch_at = last_dispatch_at
            if not effective_last_dispatch_at and latest_command:
                effective_last_dispatch_at = float(
                    latest_command.get("created_at") or 0
                )

            if effective_last_dispatch_at and (
                now - effective_last_dispatch_at
                < DIVINATION_BATCH_COMMAND_INTERVAL_SECONDS
            ):
                if run_once:
                    return
                await asyncio.sleep(DIVINATION_BATCH_POLL_SECONDS)
                continue

            # 计划次数已发完后，主动刷新天机阁缓存再决定补发与否
            needs_makeup = current_count < target_count
            if sent_count >= planned_rounds and needs_makeup:
                try:
                    fresh_payload = await asyncio.to_thread(
                        _refresh_divination_payload, storage, int(profile_id)
                    )
                    if fresh_payload and isinstance(fresh_payload, dict):
                        fresh_count = _get_divination_today_count_from_payload(
                            fresh_payload
                        )
                        fresh_completed = max(fresh_count - initial_count, 0)
                        storage.update_divination_batch(
                            batch_id,
                            completed_count=fresh_completed,
                            last_error="",
                        )
                        if fresh_count >= target_count:
                            storage.cancel_pending_outgoing_commands(
                                int(profile_id), chat_id, text=DIVINATION_COMMAND
                            )
                            storage.finish_divination_batch(
                                batch_id, status="completed"
                            )
                            if run_once:
                                return
                            await asyncio.sleep(DIVINATION_BATCH_POLL_SECONDS)
                            continue
                        current_count = fresh_count
                        completed_count = fresh_completed
                        needs_makeup = current_count < target_count
                    else:
                        # 接口返回None或非dict，终止补发
                        storage.cancel_pending_outgoing_commands(
                            int(profile_id), chat_id, text=DIVINATION_COMMAND
                        )
                        storage.finish_divination_batch(
                            batch_id,
                            status="failed",
                            last_error="天机阁接口刷新失败，终止补发",
                        )
                        if run_once:
                            return
                        await asyncio.sleep(DIVINATION_BATCH_POLL_SECONDS)
                        continue
                except Exception:
                    storage.cancel_pending_outgoing_commands(
                        int(profile_id), chat_id, text=DIVINATION_COMMAND
                    )
                    storage.finish_divination_batch(
                        batch_id,
                        status="failed",
                        last_error="天机阁接口刷新异常，终止补发",
                    )
                    if run_once:
                        return
                    await asyncio.sleep(DIVINATION_BATCH_POLL_SECONDS)
                    continue
            if sent_count >= planned_rounds and not needs_makeup:
                if run_once:
                    return
                await asyncio.sleep(DIVINATION_BATCH_POLL_SECONDS)
                continue

            storage.enqueue_outgoing_command(
                profile_id=int(profile_id),
                chat_id=chat_id,
                text=DIVINATION_COMMAND,
                thread_id=thread_id,
                chat_type=str(batch.get("chat_type") or "group"),
                bot_username=str(batch.get("bot_username") or ""),
            )
            storage.update_divination_batch(
                batch_id,
                pending_command_msg_id=0,
                last_dispatch_at=now,
                last_error="",
            )
            if run_once:
                return
            await asyncio.sleep(DIVINATION_BATCH_POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "Divination batch scheduler error for profile=%s: %s", profile_id, exc
            )
            if run_once:
                raise
            await asyncio.sleep(10)


def _build_fishing_session_updates_from_reply(
    session: dict,
    parsed: dict,
    *,
    parent_command: str,
    parent_message_id: int,
    bot_message_id: int,
    now: float,
) -> dict:
    return build_session_updates_from_reply(
        session,
        parsed,
        parent_command=parent_command,
        parent_message_id=parent_message_id,
        bot_message_id=bot_message_id,
        now=now,
    )


def _build_fishing_enqueue_session_updates(
    command_info: dict,
    command_text: str,
    *,
    now: float,
) -> dict:
    reason = str((command_info or {}).get("reason") or "").strip()
    update_fields = {
        "last_command_text": command_text,
        "last_action_at": now,
        "next_action_at": now + 60,
        "last_error": "",
    }
    if reason in {"start", "start_without_nest_bait"}:
        update_fields["state"] = "waiting_bite"
        update_fields["next_action_at"] = now + biz_fishing_game.FISHING_POLL_SECONDS
    elif reason == "check_bite":
        update_fields["next_action_at"] = now + biz_fishing_game.FISHING_POLL_SECONDS
    elif reason in {"probe_bite", "hook_without_probe", "hook"}:
        update_fields["state"] = "hook_ready"
        update_fields["next_action_at"] = now + biz_fishing_game.FISHING_POLL_SECONDS
    return update_fields


def _upsert_fishing_session_from_chat(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    chat_type: str,
    bot_username: str,
) -> dict:
    existing = storage.get_fishing_session(profile_id, chat_id)
    if existing:
        return existing
    return storage.upsert_fishing_session(
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        chat_type=chat_type,
        bot_username=bot_username,
    )


def _trusted_fishing_parent(context: EventContext, storage: Storage) -> Optional[dict]:
    if not (context.is_bot_sender and _is_context_sender_allowed_bot(context)):
        return None
    if (
        not context.profile
        or context.chat_id is None
        or not context.reply_to_msg_id
        or not context.message_id
    ):
        return None
    parent = storage.get_bound_message(
        context.chat_id,
        int(context.reply_to_msg_id),
        context.profile.id,
    )
    if not parent or int(parent.get("is_bot") or 0):
        return None
    expected_user_id = str(
        (
            context.chat_binding.telegram_user_id
            if context.chat_binding
            else ""
        )
        or (context.profile.telegram_user_id if context.profile else "")
    ).strip()
    parent_sender_id = str(parent.get("sender_id") or "").strip()
    if expected_user_id and parent_sender_id != expected_user_id:
        return None
    parent_command = str(parent.get("text") or "").strip()
    if not biz_fishing_game.is_fishing_command(parent_command):
        return None
    return parent


def observe_fishing_reply(context: EventContext, storage: Storage) -> bool:
    parent = _trusted_fishing_parent(context, storage)
    if not parent:
        return False
    parent_command = str(parent.get("text") or "").strip()
    parsed = biz_fishing_game.parse_fishing_reply(context.text)
    miniapp_entry = extract_fishing_miniapp_entry(context.event, context.text)
    if not parsed and not miniapp_entry:
        return False
    session = _upsert_fishing_session_from_chat(
        storage,
        profile_id=context.profile.id,
        chat_id=context.chat_id,
        thread_id=context.thread_id,
        chat_type=context.chat_binding.chat_type if context.chat_binding else "group",
        bot_username=context.chat_binding.bot_username if context.chat_binding else "",
    )
    now = time.time()
    if parsed:
        updates = _build_fishing_session_updates_from_reply(
            session,
            parsed,
            parent_command=parent_command,
            parent_message_id=int(parent.get("message_id") or context.reply_to_msg_id or 0),
            bot_message_id=int(context.message_id or 0),
            now=now,
        )
    else:
        updates = {
            "last_command_text": parent_command,
            "last_command_msg_id": int(parent.get("message_id") or context.reply_to_msg_id or 0),
            "last_bot_msg_id": int(context.message_id or 0),
            "last_result_text": str(context.text or "")[:4000],
            "last_action_at": now,
            "last_error": "",
        }
    if miniapp_entry:
        updates["last_result_text"] = append_miniapp_entry_block(
            updates.get("last_result_text") or str((parsed or {}).get("raw_text") or ""),
            miniapp_entry,
        )
    storage.update_fishing_session(int(session["id"]), **updates)
    return True


def _miniapp_int(value: object, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _iter_miniapp_progress_maps(value: object, depth: int = 0):
    if depth > 4:
        return
    if isinstance(value, dict):
        lowered = {str(key).lower() for key in value}
        if any(
            hint in key
            for key in lowered
            for hint in ("daily", "used", "remaining", "limit", "count")
        ):
            yield value
        for child in value.values():
            yield from _iter_miniapp_progress_maps(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_miniapp_progress_maps(child, depth + 1)


def _miniapp_progress_value(data: object, keys: tuple[str, ...]) -> int:
    for candidate in _iter_miniapp_progress_maps(data):
        lower_map = {str(key).lower(): value for key, value in candidate.items()}
        for key in keys:
            if key.lower() not in lower_map:
                continue
            parsed = _miniapp_int(lower_map.get(key.lower()), -1)
            if parsed >= 0:
                return parsed
    return -1


def _format_fishing_miniapp_catches(catches: list[dict]) -> str:
    names = []
    for item in catches:
        if not isinstance(item, dict):
            continue
        name = str(item.get("fish") or "").strip()
        if name:
            names.append(name)
    return "、".join(names[:6]) if names else "无明细"


def _format_fishing_miniapp_capture_report(captures: list[dict], *, note: str = "") -> str:
    lines = ["【MiniApp试钓报告】"]
    clean_note = str(note or "").strip()
    if clean_note:
        lines.append(clean_note[:500])
    if not captures:
        lines.append("HTTP：未发起或未捕获")
        return "\n".join(lines)
    for item in captures[:8]:
        if not isinstance(item, dict):
            continue
        request = item.get("request") if isinstance(item.get("request"), dict) else {}
        response = item.get("response") if isinstance(item.get("response"), dict) else {}
        endpoint = str(request.get("endpoint") or "-").strip() or "-"
        step = str(item.get("step") or endpoint).strip() or endpoint
        status_code = _miniapp_int(response.get("status_code"))
        ok_text = "OK" if response.get("ok") else "FAIL"
        payload_keys = request.get("payload_keys")
        if isinstance(payload_keys, list):
            payload_text = ",".join(str(key) for key in payload_keys)
        else:
            payload_text = "-"
        data_shape = response.get("data_shape")
        try:
            shape_text = json.dumps(data_shape or {}, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            shape_text = "{}"
        line = (
            f"{step} {endpoint} HTTP {status_code} {ok_text} "
            f"payload={payload_text} shape={shape_text}"
        )
        proof = request.get("proof") if isinstance(request.get("proof"), dict) else {}
        if proof:
            proof_parts = []
            for key in (
                "mode",
                "challenge_suffix",
                "durationMs",
                "events",
                "progress",
                "score",
                "stability",
                "samples",
                "actions",
                "dangerMs",
                "slackMs",
            ):
                if key in proof:
                    proof_parts.append(f"{key}:{proof.get(key)}")
            if proof_parts:
                line = f"{line} proof={','.join(proof_parts)}"
        summary = response.get("summary") if isinstance(response.get("summary"), dict) else {}
        if summary:
            summary_parts = []
            for key in ("status", "reason", "ready", "caught", "fish", "rarity", "grade", "score", "duration_ms"):
                if key in summary:
                    summary_parts.append(f"{key}:{summary.get(key)}")
            if summary_parts:
                line = f"{line} result={','.join(summary_parts)}"
        error_text = str(response.get("error") or "").strip()
        if error_text:
            line = f"{line} error={fishing_miniapp.sanitize_miniapp_secret_text(error_text, limit=120)}"
        lines.append(line[:500])
    return "\n".join(lines)


def _remaining_fishing_miniapp_rounds(session: dict) -> int:
    daily_count = max(_miniapp_int(session.get("daily_count")), 0)
    daily_limit = max(_miniapp_int(session.get("daily_limit"), biz_fishing_game.FISHING_DAILY_LIMIT), 1)
    return max(1, daily_limit - daily_count)


def _build_fishing_miniapp_result_updates(session: dict, result: dict, *, now: float, bot_message_id: int) -> dict:
    result = dict(result or {})
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    status = str(result.get("status") or "unknown").strip() or "unknown"
    ok = bool(result.get("ok"))
    daily_limit = max(_miniapp_int(session.get("daily_limit"), biz_fishing_game.FISHING_DAILY_LIMIT), 1)
    daily_count = max(_miniapp_int(session.get("daily_count")), 0)
    limit_value = _miniapp_progress_value(
        data,
        ("dailyLimit", "daily_limit", "dailyRodsLimit", "rodLimit", "limit", "total"),
    )
    used_value = _miniapp_progress_value(
        data,
        ("dailyUsed", "daily_used", "dailyCount", "daily_count", "rodCount", "used", "count"),
    )
    remaining_value = _miniapp_progress_value(
        data,
        ("dailyRemaining", "daily_remaining", "remainingRods", "remaining", "left"),
    )
    if limit_value > 0:
        daily_limit = limit_value
    if used_value >= 0:
        daily_count = min(daily_limit, used_value)
    elif remaining_value >= 0:
        daily_count = min(daily_limit, max(0, daily_limit - remaining_value))
    elif ok:
        settled_count = max(_miniapp_int(result.get("settled_count") or data.get("settled_count"), 1), 1)
        daily_count = min(daily_limit, daily_count + settled_count)

    catches = fishing_miniapp.extract_fishing_miniapp_catches(data)
    catch_text = _format_fishing_miniapp_catches(catches)
    finished = ok and (daily_count >= daily_limit or status == "daily_limit")
    failed = not ok or status in {"next_failed", "next_unavailable"}
    summary = f"MiniApp {status}｜{daily_count}/{daily_limit}｜渔获:{catch_text}"
    if failed and result.get("error"):
        summary = f"{summary}｜{fishing_miniapp.sanitize_miniapp_secret_text(result.get('error'))}"
    updates = {
        "state": "finished" if finished else ("catch_success" if ok else "miniapp_failed"),
        "daily_count": daily_count,
        "daily_limit": daily_limit,
        "last_bot_msg_id": int(bot_message_id or 0),
        "last_result_text": summary[:4000],
        "last_error": summary[:1000] if failed else "",
        "next_action_at": 0 if finished else (now + 1800 if failed else now + biz_fishing_game.FISHING_RESULT_RECOVERY_SECONDS),
        "last_action_at": now,
    }
    if finished:
        updates["enabled"] = False
    if catches:
        merged = dict(session.get("catches") or {})
        for item in catches:
            fish = str(item.get("fish") or "").strip()
            if fish:
                merged[fish] = _miniapp_int(merged.get(fish), 0) + 1
        updates["catches"] = merged
        updates["last_fish_name"] = str(catches[-1].get("fish") or "")[:255]
    return updates


async def _maybe_handle_fishing_miniapp_entry(context: EventContext, storage: Storage) -> bool:
    parent = _trusted_fishing_parent(context, storage)
    if not parent:
        return False
    launch = fishing_miniapp.extract_fishing_miniapp_launch(context.event, context.text)
    if not launch:
        if not fishing_miniapp.looks_like_fishing_miniapp_prompt(context.text):
            return False
        session = _upsert_fishing_session_from_chat(
            storage,
            profile_id=context.profile.id,
            chat_id=context.chat_id,
            thread_id=context.thread_id,
            chat_type=context.chat_binding.chat_type if context.chat_binding else "group",
            bot_username=context.chat_binding.bot_username if context.chat_binding else "",
        )
        if str(session.get("state") or "") in {
            "miniapp_canary",
            "miniapp_batch",
            "miniapp_canary_running",
            "miniapp_batch_running",
        }:
            return False
        if not _miniapp_int(session.get("enabled")):
            return False
        now = time.time()
        button_debug = fishing_miniapp.describe_miniapp_button_debug(context.event)
        prompt_note = "入口：bot 提示进入 MiniApp，但 runtime 未捕获按钮 URL。"
        if "已有一竿尚未收起" in str(context.text or ""):
            prompt_note = (
                "入口：bot 返回已有未收起鱼竿；这条回包通常不是原始开竿入口，"
                "runtime 未捕获可接管按钮 URL。"
            )
        report_text = _format_fishing_miniapp_capture_report(
            [],
            note=f"{prompt_note}\n按钮诊断：{button_debug}",
        )
        storage.update_fishing_session(
            int(session["id"]),
            enabled=False,
            state="miniapp_failed",
            last_result_text=report_text[:4000],
            last_command_text=str(parent.get("text") or "").strip(),
            last_command_msg_id=int(parent.get("message_id") or context.reply_to_msg_id or 0),
            last_bot_msg_id=int(context.message_id or 0),
            last_action_at=now,
            next_action_at=0,
            last_error="MiniApp 入口按钮未捕获，未发起 HTTP。",
        )
        return True
    session = _upsert_fishing_session_from_chat(
        storage,
        profile_id=context.profile.id,
        chat_id=context.chat_id,
        thread_id=context.thread_id,
        chat_type=context.chat_binding.chat_type if context.chat_binding else "group",
        bot_username=context.chat_binding.bot_username if context.chat_binding else "",
    )
    if str(session.get("state") or "") in {
        "miniapp_canary",
        "miniapp_batch",
        "miniapp_canary_running",
        "miniapp_batch_running",
    }:
        return False
    if not _miniapp_int(session.get("enabled")):
        return False
    now = time.time()
    entry = launch.get("entry") or extract_fishing_miniapp_entry(context.event, context.text)
    storage.update_fishing_session(
        int(session["id"]),
        state="miniapp",
        last_result_text=append_miniapp_entry_block("MiniApp 钓鱼接管中", entry),
        last_command_text=str(parent.get("text") or "").strip(),
        last_command_msg_id=int(parent.get("message_id") or context.reply_to_msg_id or 0),
        last_bot_msg_id=int(context.message_id or 0),
        last_action_at=now,
        next_action_at=now + 90 * _remaining_fishing_miniapp_rounds(session),
        last_error="",
    )
    captures: list[dict] = []
    result = await fishing_miniapp.run_fishing_miniapp_production_flow(
        context.client,
        token=launch.get("token"),
        webview_url=launch.get("webview_url"),
        max_rounds=_remaining_fishing_miniapp_rounds(session),
        capture_sink=captures,
        capture_source=f"fishing:{context.profile.id}:{int(context.message_id or 0)}",
    )
    fresh_session = storage.get_fishing_session(context.profile.id, context.chat_id) or session
    updates = _build_fishing_miniapp_result_updates(
        fresh_session,
        result,
        now=time.time(),
        bot_message_id=int(context.message_id or 0),
    )
    report_text = _format_fishing_miniapp_capture_report(captures)
    updates["last_result_text"] = (
        f"{updates.get('last_result_text') or ''}\n\n{report_text}"
    )[:4000]
    storage.update_fishing_session(int(fresh_session["id"]), **updates)
    return True


async def _run_fishing_auto_scheduler(
    client: object,
    storage: Storage,
    *,
    run_once: bool = False,
    session_ids: Optional[set[int]] = None,
) -> None:
    profile_id = getattr(client, "_tg_game_profile_id", None)
    if not profile_id:
        return

    while True:
        try:
            if profile_rebirth.is_profile_rebirth_locked(storage, int(profile_id)):
                if run_once:
                    return
                await asyncio.sleep(FISHING_AUTO_POLL_SECONDS)
                continue
            sessions = storage.list_active_fishing_sessions(int(profile_id))
            if session_ids is not None:
                sessions = [
                    session
                    for session in sessions
                    if int(session.get("id") or 0) in session_ids
                ]
            for session in sessions:
                chat_id = int(session.get("chat_id") or 0)
                if not chat_id:
                    continue
                thread_id = (
                    int(session.get("thread_id"))
                    if session.get("thread_id") is not None
                    else None
                )
                state = str(session.get("state") or "")
                if state in {
                    "miniapp_canary",
                    "miniapp_batch",
                    "miniapp_canary_running",
                    "miniapp_batch_running",
                }:
                    now = time.time()
                    if float(session.get("next_action_at") or 0) > now:
                        continue
                    batch_mode = state in {"miniapp_batch", "miniapp_batch_running"}
                    storage.update_fishing_session(
                        int(session["id"]),
                        state=(
                            "miniapp_batch_running"
                            if batch_mode
                            else "miniapp_canary_running"
                        ),
                        next_action_at=now + 15 * 60,
                        last_action_at=now,
                        last_error="",
                    )
                    captures: list[dict] = []
                    result = await fishing_miniapp.run_fishing_miniapp_public_production_flow(
                        client,
                        discovery_storage=storage,
                        pond=str(session.get("pond") or biz_fishing_game.FISHING_DEFAULT_POND),
                        bait=str(session.get("bait") or biz_fishing_game.FISHING_DEFAULT_BAIT),
                        max_rounds=(
                            fishing_miniapp.FISHING_MINIAPP_MAX_DAILY_ROUNDS
                            if batch_mode
                            else 1
                        ),
                        auto_buy_bait=True,
                        capture_sink=captures,
                        capture_source=f"fishing-public:{profile_id}:{int(session['id'])}",
                    )
                    fresh_session = (
                        storage.get_fishing_session(int(profile_id), chat_id) or session
                    )
                    updates = _build_fishing_miniapp_result_updates(
                        fresh_session,
                        result,
                        now=time.time(),
                        bot_message_id=0,
                    )
                    updates["enabled"] = False
                    updates["next_action_at"] = 0
                    report_text = _format_fishing_miniapp_capture_report(captures)
                    updates["last_result_text"] = (
                        f"{updates.get('last_result_text') or ''}\n\n{report_text}"
                    )[:4000]
                    storage.update_fishing_session(int(fresh_session["id"]), **updates)
                    daily_task = storage.get_companion_auto_task(
                        int(profile_id),
                        chat_id,
                        biz_fishing_daily_auto.FEATURE_KEY,
                    )
                    if daily_task:
                        task_error = str(updates.get("last_error") or "")
                        if updates.get("state") == "finished":
                            task_error = biz_fishing_daily_auto.COMPLETED_TODAY_ERROR
                        storage.update_companion_auto_task(
                            int(daily_task["id"]),
                            workflow_state=str(updates.get("state") or ""),
                            last_error=task_error,
                        )
                    continue
                command_info = biz_fishing_game.build_next_auto_command(session)
                if not command_info:
                    continue
                command_text = str(command_info.get("command") or "").strip()
                if not command_text:
                    continue
                if _has_pending_outgoing_command(
                    storage,
                    profile_id=int(profile_id),
                    chat_id=chat_id,
                    text=command_text,
                    thread_id=thread_id,
                ):
                    continue
                now = time.time()
                session_updates = command_info.get("session_updates")
                if not isinstance(session_updates, dict):
                    session_updates = {}
                storage.enqueue_outgoing_command(
                    profile_id=int(profile_id),
                    chat_id=chat_id,
                    text=command_text,
                    thread_id=thread_id,
                    chat_type=str(session.get("chat_type") or "group"),
                    bot_username=str(session.get("bot_username") or ""),
                )
                update_fields = _build_fishing_enqueue_session_updates(
                    command_info,
                    command_text,
                    now=now,
                )
                update_fields.update(session_updates)
                storage.update_fishing_session(int(session["id"]), **update_fields)
            if run_once:
                return
            await asyncio.sleep(FISHING_AUTO_POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Fishing auto scheduler failed: %s", exc)
            if run_once:
                raise
            await asyncio.sleep(FISHING_AUTO_POLL_SECONDS)


async def run_queue_backed_schedules_once(
    storage: Storage,
    profile_id: int,
    *,
    companion_task_ids: Iterable[int] = (),
    fishing_session_ids: Iterable[int] = (),
    include_divination_batch: bool = False,
) -> None:
    client = SimpleNamespace(_tg_game_profile_id=int(profile_id))
    companion_ids = {int(task_id) for task_id in companion_task_ids}
    fishing_ids = {int(session_id) for session_id in fishing_session_ids}
    if companion_ids:
        await _run_companion_auto_scheduler(
            client,
            storage,
            run_once=True,
            task_ids=companion_ids,
            include_tianxing=False,
        )
    if fishing_ids:
        await _run_fishing_auto_scheduler(
            client,
            storage,
            run_once=True,
            session_ids=fishing_ids,
        )
    if include_divination_batch:
        await _run_divination_batch_scheduler(client, storage, run_once=True)


SECT_FEATURE_REPLY_WHITELISTS = {
    "huangfeng": {
        ".小药园",
        ".播种",
        ".采药",
        ".除草",
        ".除虫",
        ".浇水",
        ".扩建药园",
    },
    "xingong": {
        ".启阵",
        ".助阵",
        ".观星台",
        ".牵引星辰",
        ".收集精华",
        ".安抚星辰",
        ".观星",
        ".改换星移",
        ".我的侍妾",
        ".每日问安",
    },
    "lingxiao": {
        ".凌霄宫",
        ".天阶状态",
        ".问心台",
        ".登天阶",
        ".引九天罡风",
        ".借天门势",
    },
    "taiyi": {".引道", ".神识冲击"},
    "wanling": {
        ".寻觅灵兽",
        ".我的灵兽",
        ".喂养",
        ".灵兽出战",
        ".灵兽休息",
        ".一键放养",
        ".灵兽偷菜",
        ".探渊",
    },
    "luoyun": {".灵树状态", ".灵树灌溉", ".协同守山", ".采摘灵果"},
    "yinluo": {
        ".我的阴罗幡",
        ".升级阴罗幡",
        ".每日献祭",
        ".化功为煞",
        ".血洗山林",
        ".召唤魔影",
        ".囚禁魂魄",
        ".安抚幡灵",
        ".收取精华",
        ".下咒",
        ".收割",
    },
    "yuanying": {
        ".元婴状态",
        ".元婴出窍",
        ".元婴闭关",
        ".元婴归窍",
        ".问道",
        ".参悟功法",
    },
    "hehuan": {
        ".闭关双修",
        ".缔结同参",
        ".双修 温养",
        ".种下心印",
        ".双修 采补",
        ".挣脱心印",
        ".结印",
    },
}


class BaseExecutor(ABC):
    key = "base"

    async def startup(self, client: object, storage: Storage) -> None:
        return None

    def _expected_profile_user_id(self, context: EventContext) -> str:
        binding_user_id = (
            context.chat_binding.telegram_user_id if context.chat_binding else ""
        )
        return binding_user_id or (
            context.profile.telegram_user_id if context.profile else ""
        )

    async def _bot_message_targets_profile(
                        self, context: EventContext, storage: Storage
    ) -> bool:
        if await context.bot_message_targets_profile():
            return True
        return False

    def _get_stored_reply_message(
        self, context: EventContext, storage: Storage
    ) -> Optional[dict]:
        return None

    async def _get_reply_message_text(
        self, context: EventContext, storage: Storage
    ) -> str:
        reply_text = await context.get_reply_message_text()
        if reply_text:
            return reply_text.strip()
        return ""

    @abstractmethod
    async def handle(self, context: EventContext, storage: Storage) -> bool:
        raise NotImplementedError


class FanrenExecutor(BaseExecutor):
    key = "fanren"

    def __init__(self) -> None:
        self._runner_started = False

    def _is_yuanying_settlement_for_profile(self, context: EventContext) -> bool:
        if not context.profile:
            return False
        return biz_fanren_game._is_yuanying_settlement_text(
            context.text
        ) and biz_fanren_game._message_mentions_profile(context.profile, context.text)

    async def startup(self, client: object, storage: Storage) -> None:
        if self._runner_started:
            return
        self._runner_started = True
        db = SQLiteCompatDb(storage)
        biz_fanren_game.ensure_tables(db)
        db.close()
        _register_client_background_task(
            client,
            asyncio.create_task(
                biz_fanren_game.runner(
                    client,
                    storage,
                    profile_id=getattr(client, "_tg_game_profile_id", None),
                )
            ),
        )
        logger.info("Fanren executor runner started")

    async def _bot_message_targets_profile(
        self, context: EventContext, storage: Storage
    ) -> bool:
        if await super()._bot_message_targets_profile(context, storage):
            return True
        if not context.profile or context.chat_id is None:
            return False
        db = SQLiteCompatDb(storage)
        try:
            session = biz_fanren_game.get_session(
                db, context.chat_id, profile_id=context.profile.id
            )
        finally:
            db.close()
        if not session:
            return False
        if session.get("thread_id") and context.thread_id:
            if int(session.get("thread_id") or 0) != int(context.thread_id or 0):
                return False
        if session.get("auto_yuanying_enabled") and self._is_yuanying_settlement_for_profile(
            context
        ):
            return True
        parent_command = ""
        if context.reply_to_msg_id:
            parent = storage.get_bound_message(
                context.chat_id,
                int(context.reply_to_msg_id),
                context.profile.id,
            )
            if (
                str((parent or {}).get("direction") or "") == "outgoing"
                and not int((parent or {}).get("is_bot") or 0)
            ):
                parent_command = str((parent or {}).get("text") or "").strip()
        if parent_command in {
            biz_fanren_game.YUANYING_OUTING_COMMAND,
            biz_fanren_game.YUANYING_STATUS_COMMAND,
        }:
            raw_text = context.text
            if (
                parent_command == biz_fanren_game.YUANYING_STATUS_COMMAND
                or "你的本命元婴" in raw_text
            ):
                yy_status, _yy_cd = biz_fanren_game.parse_yuanying_status_reply(
                    raw_text
                )
                return yy_status != "unknown"
            yy_success, yy_cd = biz_fanren_game.parse_yuanying_reply(raw_text)
            return yy_success or yy_cd is not None
        if profile_rebirth.is_rebirth_command(parent_command):
            return profile_rebirth.is_profile_rebirth_locked(
                storage, context.profile.id
            )
        last_action = str(session.get("last_action") or "").strip()
        if not last_action:
            return False
        if last_action not in {
            biz_fanren_game.YUANYING_OUTING_COMMAND,
            biz_fanren_game.YUANYING_STATUS_COMMAND,
        }:
            return False
        last_action_time = float(session.get("last_action_time") or 0)
        if not last_action_time:
            return False
        if (time.time() - last_action_time) > FANREN_RECENT_REPLY_WINDOW_SECONDS:
            return False
        raw_text = context.text
        has_yuanying_anchor = any(
            keyword in raw_text
            for keyword in ("元婴", "本命元婴", "元神归窍", "窍中温养")
        )
        if not has_yuanying_anchor:
            return False
        if last_action == biz_fanren_game.YUANYING_STATUS_COMMAND:
            yy_status, _yy_cd = biz_fanren_game.parse_yuanying_status_reply(raw_text)
            return yy_status != "unknown"
        yy_success, yy_cd = biz_fanren_game.parse_yuanying_reply(raw_text)
        return yy_success or yy_cd is not None

    async def handle(self, context: EventContext, storage: Storage) -> bool:
        if not context.chat_binding:
            return False

        db = SQLiteCompatDb(storage)
        try:
            if context.text.startswith(".fanren") and context.is_profile_owner():
                if context.profile:
                    if context.thread_id is not None:
                        storage.set_chat_binding_thread_id(
                            context.profile.id, context.chat_id, context.thread_id
                        )
                        biz_fanren_game.update_session(
                            db,
                            context.chat_id,
                            profile_id=context.profile.id if context.profile else None,
                            thread_id=context.thread_id,
                        )
                return await self._handle_command(context, db)

            if (
                context.is_bot_sender
                and _is_context_sender_allowed_bot(context)
                and await self._bot_message_targets_profile(context, storage)
            ):
                session = biz_fanren_game.get_session(
                    db,
                    context.chat_id,
                    profile_id=context.profile.id if context.profile else None,
                )
                is_yuanying_settlement = self._is_yuanying_settlement_for_profile(
                    context
                )
                reply_text = await self._get_reply_message_text(context, storage)
                allowed_reply_commands = {
                    biz_fanren_game.FANREN_CHECK_COMMAND,
                    biz_fanren_game.FANREN_NORMAL_COMMAND,
                    biz_fanren_game.FANREN_DEEP_COMMAND,
                    ".强行出关",
                    biz_fanren_game.RIFT_EXPLORE_COMMAND,
                    biz_fanren_game.YUANYING_OUTING_COMMAND,
                    biz_fanren_game.YUANYING_STATUS_COMMAND,
                }
                if session:
                    allowed_reply_commands.add(biz_fanren_game.build_check_command(session))
                if (
                    reply_text
                    and reply_text not in allowed_reply_commands
                    and not profile_rebirth.is_rebirth_command(reply_text)
                    and not is_yuanying_settlement
                ):
                    return False
                stored_reply_message = self._get_stored_reply_message(context, storage)
                reply_message_id = context.reply_to_msg_id or int(
                    (stored_reply_message or {}).get("message_id") or 0
                )
                parsed = await biz_fanren_game.handle_bot_message(
                    context.event,
                    db,
                    client=context.client,
                    profile_id=context.profile.id if context.profile else None,
                )
                if parsed is not None:
                    session = biz_fanren_game.get_session(
                        db,
                        context.chat_id,
                        profile_id=context.profile.id if context.profile else None,
                    )
                    await biz_fanren_game.maybe_delete_normal_command_message(
                        context.event,
                        session,
                        context.client,
                        reply_text,
                        reply_message_id=reply_message_id or None,
                    )
                    if context.profile and context.chat_id is not None:
                        try:
                            sync_cultivation_session(
                                storage, context.profile.id, context.chat_id, db
                            )
                        except Exception as exc:
                            logger.warning(
                                "Cultivation API sync failed in chat %s: %s",
                                context.chat_id,
                                exc,
                            )
                    self._record_result(context, storage, parsed.event)
                return parsed is not None
            if (
                context.is_bot_sender
                and _is_context_sender_allowed_bot(context)
                and await context.bot_message_targets_profile()
            ):
                is_yuanying_settlement = self._is_yuanying_settlement_for_profile(
                    context
                )
                reply_text = await self._get_reply_message_text(context, storage)
                fallback_allowed_reply_commands = {
                    biz_fanren_game.FANREN_CHECK_COMMAND,
                    biz_fanren_game.FANREN_NORMAL_COMMAND,
                    biz_fanren_game.FANREN_DEEP_COMMAND,
                    ".强行出关",
                    biz_fanren_game.RIFT_EXPLORE_COMMAND,
                    biz_fanren_game.YUANYING_OUTING_COMMAND,
                    biz_fanren_game.YUANYING_STATUS_COMMAND,
                }
                if (
                    reply_text
                    and reply_text not in fallback_allowed_reply_commands
                    and not profile_rebirth.is_rebirth_command(reply_text)
                    and not is_yuanying_settlement
                ):
                    return False
                parsed = await biz_fanren_game.handle_bot_message(
                    context.event,
                    db,
                    client=context.client,
                    profile_id=context.profile.id if context.profile else None,
                )
                if parsed is not None:
                    if context.profile and context.chat_id is not None:
                        try:
                            sync_cultivation_session(
                                storage, context.profile.id, context.chat_id, db
                            )
                        except Exception as exc:
                            logger.warning(
                                "Cultivation API sync failed in chat %s: %s",
                                context.chat_id,
                                exc,
                            )
                    return True
            return False
        finally:
            db.close()

    def _record_result(
        self, context: EventContext, storage: Storage, event_name: str
    ) -> None:
        if not event_name:
            return
        # 记录所有闭关/元婴/裂缝相关事件，不只是里程碑
        if event_name in {"empty", "ignored", "blocked", "resource_blocked", "unknown"}:
            return
        if event_name.endswith("_edited"):
            pass  # 编辑事件总是记录
        elif not any(
            event_name.startswith(prefix)
            for prefix in (
                "retreat_",
                "deep_",
                "cultivat",
                "cooldown",
                "rift_",
                "yuanying_",
                "soul_",
                "meditation",
            )
        ) and event_name not in {
            "cultivation_full",
            "soul_returning",
            "jie_dan",
            "jie_dan_complete",
        }:
            return
        session_setting = context.get_setting("cultivation") or context.get_setting(
            "basic"
        )
        gain_value = biz_fanren_game.parse_gain_value(context.text)
        stage_name, progress_text = biz_fanren_game.extract_stage_progress(context.text)
        mode = "normal"
        if context.chat_id is not None:
            db = SQLiteCompatDb(storage)
            try:
                session = biz_fanren_game.get_session(
                    db,
                    context.chat_id,
                    profile_id=context.profile.id if context.profile else None,
                )
                mode = (
                    (session.get("retreat_mode") or "normal") if session else "normal"
                )
            finally:
                db.close()
        elif (
            session_setting
            and session_setting.command_template == biz_fanren_game.FANREN_CHECK_COMMAND
        ):
            mode = "deep"
        storage.record_cultivation_result(
            profile_id=context.profile.id if context.profile else None,
            chat_id=context.chat_id or 0,
            mode=mode,
            event=event_name,
            gain_value=gain_value,
            stage_name=stage_name,
            progress_text=progress_text,
            summary=biz_fanren_game.parse_message(context.text).summary,
            raw_text=context.text,
        )

    async def _handle_command(self, context: EventContext, db: SQLiteCompatDb) -> bool:
        parts = context.text.split(maxsplit=2)
        action = parts[1].lower() if len(parts) > 1 else "status"
        payload = parts[2].strip() if len(parts) > 2 else ""
        chat_id = context.chat_id
        if chat_id is None:
            return False

        setting = context.get_setting("cultivation") or context.get_setting("basic")
        if setting:
            biz_fanren_game.set_interval(
                db,
                chat_id,
                setting.check_interval_seconds,
                profile_id=context.profile.id if context.profile else None,
            )
            if setting.command_template:
                biz_fanren_game.set_check_command(
                    db,
                    chat_id,
                    setting.command_template,
                    profile_id=context.profile.id if context.profile else None,
                )

        if action == "on":
            if payload in {"normal", "deep"}:
                biz_fanren_game.set_mode(
                    db,
                    chat_id,
                    payload,
                    profile_id=context.profile.id if context.profile else None,
                )
            if context.profile:
                sync_cultivation_session(storage, context.profile.id, chat_id, db)
            biz_fanren_game.set_enabled(
                db,
                chat_id,
                True,
                reset_failure=True,
                profile_id=context.profile.id if context.profile else None,
            )
            session = biz_fanren_game.get_session(
                db,
                chat_id,
                profile_id=context.profile.id if context.profile else None,
            )
            await context.reply(
                f"凡人修仙自动化已开启，当前模式为 {'深度闭关' if session.get('retreat_mode') == 'deep' else '普通闭关'}，将按接口冷却时间自动调度。"
            )
            return True
        if action == "off":
            biz_fanren_game.set_enabled(
                db,
                chat_id,
                False,
                profile_id=context.profile.id if context.profile else None,
            )
            await context.reply("凡人修仙自动化已关闭。")
            return True
        if action == "status":
            session = biz_fanren_game.get_session(
                db,
                chat_id,
                profile_id=context.profile.id if context.profile else None,
            )
            await context.reply(biz_fanren_game.build_status_text(session))
            return True
        if action == "dry-run":
            enabled = payload.lower() == "on"
            biz_fanren_game.set_dry_run(
                db,
                chat_id,
                enabled,
                profile_id=context.profile.id if context.profile else None,
            )
            await context.reply(f"凡人修仙 dry-run 已{'开启' if enabled else '关闭'}。")
            return True
        if action == "interval":
            try:
                interval_seconds = biz_fanren_game.parse_interval_input(payload)
            except ValueError as exc:
                await context.reply(f"设置失败: {exc}")
                return True
            biz_fanren_game.set_interval(
                db,
                chat_id,
                interval_seconds,
                profile_id=context.profile.id if context.profile else None,
            )
            await context.reply(
                f"凡人修仙检查间隔已设置为 {biz_fanren_game.format_duration(interval_seconds)}。"
            )
            return True
        if action == "check":
            try:
                check_command = biz_fanren_game.set_check_command(
                    db,
                    chat_id,
                    payload,
                    profile_id=context.profile.id if context.profile else None,
                )
            except ValueError as exc:
                await context.reply(f"设置失败: {exc}")
                return True
            await context.reply(f"凡人修仙检查指令已设置为: {check_command}")
            return True
        if action == "mode":
            try:
                retreat_mode = biz_fanren_game.set_mode(
                    db,
                    chat_id,
                    payload,
                    profile_id=context.profile.id if context.profile else None,
                )
            except ValueError as exc:
                await context.reply(f"设置失败: {exc}")
                return True
            if context.profile:
                sync_cultivation_session(storage, context.profile.id, chat_id, db)
            await context.reply(
                f"凡人修仙模式已设置为 {'深度闭关' if retreat_mode == 'deep' else '普通闭关'}，将按接口冷却时间自动调度。"
            )
            return True
        if action == "run":
            if context.profile:
                sync_cultivation_session(storage, context.profile.id, chat_id, db)
            _ok, status = await biz_fanren_game.maybe_send_check(
                context.client,
                db,
                chat_id,
                force=False,
                profile_id=context.profile.id if context.profile else None,
            )
            await context.reply(f"执行结果: {status}")
            return True
        if action == "reset":
            biz_fanren_game.reset_failures(
                db,
                chat_id,
                profile_id=context.profile.id if context.profile else None,
            )
            await context.reply("凡人修仙失败计数已重置。")
            return True
        if action == "rift":
            rift_action = payload.lower() if payload else "status"
            rift_session = biz_fanren_game.get_session(
                db,
                chat_id,
                profile_id=context.profile.id if context.profile else None,
            )
            if rift_action == "on":
                biz_fanren_game.set_auto_rift(
                    db,
                    chat_id,
                    True,
                    profile_id=context.profile.id if context.profile else None,
                )
                cooldown_label = biz_fanren_game.get_rift_cooldown_label(
                    storage, context.profile.id if context.profile else None
                )
                await context.reply(
                    f"自动探寻裂缝已开启，当前基础 CD {cooldown_label}，bot 回包倒计时优先。"
                )
                return True
            if rift_action == "off":
                biz_fanren_game.set_auto_rift(
                    db,
                    chat_id,
                    False,
                    profile_id=context.profile.id if context.profile else None,
                )
                await context.reply("自动探寻裂缝已关闭。")
                return True
            if rift_action == "status":
                await context.reply(
                    "\n".join(
                        [
                            "自动探寻裂缝状态",
                            f"开关: {'开启' if rift_session.get('auto_rift_enabled') else '关闭'}",
                            f"状态: {rift_session.get('rift_state') or '-'}",
                            f"下次: {biz_fanren_game.format_timestamp(rift_session.get('rift_next_check_time') or 0)}",
                            f"重试: {rift_session.get('rift_retry_count') or 0}/{biz_fanren_game.RIFT_RETRY_MAX}",
                        ]
                    )
                )
                return True
            if rift_action == "log":
                if not context.profile:
                    await context.reply("当前未绑定角色，无法查看裂缝日志。")
                    return True
                logs = biz_fanren_game.get_rift_execution_logs(
                    storage,
                    profile_id=context.profile.id,
                    chat_id=chat_id,
                    limit=12,
                )
                if not logs:
                    await context.reply("最近没有自动探寻裂缝执行日志。")
                    return True
                lines = ["自动探寻裂缝日志（最近12条）"]
                for entry in reversed(logs):
                    lines.append(
                        f"[{biz_fanren_game.format_timestamp(entry.get('created_at') or 0)}] "
                        f"{entry.get('step') or '-'} / {entry.get('event_type') or '-'} / "
                        f"{entry.get('rift_state') or '-'}"
                    )
                await context.reply("\n".join(lines))
                return True
        if action == "yuanying":
            yy_action = payload.lower() if payload else "status"
            yy_session = biz_fanren_game.get_session(
                db,
                chat_id,
                profile_id=context.profile.id if context.profile else None,
            )
            if yy_action == "on":
                biz_fanren_game.set_auto_yuanying(
                    db,
                    chat_id,
                    True,
                    profile_id=context.profile.id if context.profile else None,
                )
                await context.reply("自动元婴出窍已开启，CD 8 小时。")
                return True
            if yy_action == "off":
                biz_fanren_game.set_auto_yuanying(
                    db,
                    chat_id,
                    False,
                    profile_id=context.profile.id if context.profile else None,
                )
                await context.reply("自动元婴出窍已关闭。")
                return True
            if yy_action == "status":
                await context.reply(
                    "\n".join(
                        [
                            "自动元婴出窍状态",
                            f"开关: {'开启' if yy_session.get('auto_yuanying_enabled') else '关闭'}",
                            f"状态: {yy_session.get('yuanying_state') or '-'}",
                            f"下次: {biz_fanren_game.format_timestamp(yy_session.get('yuanying_next_check_time') or 0)}",
                        ]
                    )
                )
                return True

        await context.reply(
            "用法: .fanren status|on [normal|deep]|off|mode normal|deep|dry-run on|off|interval 5m|check 指令|run|reset|rift on|off|status|yuanying on|off|status"
        )
        return True


class SectExecutor(BaseExecutor):
    key = "sect"

    def __init__(self) -> None:
        self._runner_started = False

    def _reply_matches_whitelist(self, reply_text: str, feature_key: str) -> bool:
        reply_text = (reply_text or "").strip()
        if not reply_text:
            return False
        for command in SECT_FEATURE_REPLY_WHITELISTS.get(feature_key, set()):
            if reply_text == command or reply_text.startswith(f"{command} "):
                return True
        return False

    async def startup(self, client: object, storage: Storage) -> None:
        if self._runner_started:
            return
        self._runner_started = True
        db = SQLiteCompatDb(storage)
        biz_sect_game.ensure_tables(db)
        db.close()
        _register_client_background_task(
            client,
            asyncio.create_task(
                biz_sect_game.runner(
                    client,
                    storage,
                    profile_id=getattr(client, "_tg_game_profile_id", None),
                )
            ),
        )
        logger.info("Sect executor runner started")

    async def handle(self, context: EventContext, storage: Storage) -> bool:
        if not context.chat_binding:
            return False

        db = SQLiteCompatDb(storage)
        try:
            if context.text.startswith(".sect") and context.is_profile_owner():
                if context.profile:
                    if context.thread_id is not None:
                        storage.set_chat_binding_thread_id(
                            context.profile.id, context.chat_id, context.thread_id
                        )
                        biz_sect_game.update_session(
                            db,
                            context.chat_id,
                            profile_id=context.profile.id if context.profile else None,
                            thread_id=context.thread_id,
                        )
                return await self._handle_command(context, db)

            if context.is_bot_sender and _is_context_sender_allowed_bot(context):
                preview_parsed = biz_sect_game.parse_message(context.text)
                bot_targets_profile = await self._bot_message_targets_profile(
                    context, storage
                )
                allow_companion_assist_observation = False
                if (
                    not bot_targets_profile
                    and preview_parsed.get("event")
                    in {"xinggong_star_array_open", "xinggong_star_array_complete"}
                    and context.profile
                    and context.chat_id is not None
                ):
                    session = biz_sect_game.get_session(
                        db,
                        context.chat_id,
                        profile_id=context.profile.id,
                    )
                    allow_companion_assist_observation = bool(
                        session
                        and session.get("enabled")
                        and session.get("auto_companion_assist_enabled")
                    )
                if not bot_targets_profile and not allow_companion_assist_observation:
                    return False
                reply_text = await self._get_reply_message_text(context, storage)
                if reply_text:
                    if (
                        preview_parsed.get("event")
                        in {
                            "sect_panel",
                            "sect_panel_pending",
                            "sect_info",
                        }
                        and reply_text != ".我的宗门"
                    ):
                        return False
                    if (
                        preview_parsed.get("event") == "lingxiao_step"
                        and reply_text != ".登天阶"
                    ):
                        return False
                parsed = await biz_sect_game.handle_bot_message(
                    context.event,
                    db,
                    client=context.client,
                    profile_id=context.profile.id if context.profile else None,
                    profile=context.profile,
                )
                if parsed is not None:
                    return True
                return parsed is not None
            return False
        finally:
            db.close()

    async def _handle_command(self, context: EventContext, db: SQLiteCompatDb) -> bool:
        parts = context.text.split(maxsplit=2)
        action = parts[1].lower() if len(parts) > 1 else "status"
        payload = parts[2].strip() if len(parts) > 2 else ""
        chat_id = context.chat_id
        if chat_id is None:
            return False

        setting = context.get_setting("sect") or context.get_setting("basic")
        if setting:
            biz_sect_game.set_interval(
                db,
                chat_id,
                setting.check_interval_seconds,
                profile_id=context.profile.id if context.profile else None,
            )
            if setting.command_template:
                biz_sect_game.set_check_command(
                    db,
                    chat_id,
                    setting.command_template,
                    profile_id=context.profile.id if context.profile else None,
                )

        if action == "on":
            biz_sect_game.set_enabled(
                db,
                chat_id,
                True,
                profile_id=context.profile.id if context.profile else None,
            )
            await context.reply("宗门模块已开启。")
            return True
        if action == "off":
            biz_sect_game.set_enabled(
                db,
                chat_id,
                False,
                profile_id=context.profile.id if context.profile else None,
            )
            await context.reply("宗门模块已关闭。")
            return True
        if action == "status":
            session = biz_sect_game.get_session(
                db,
                chat_id,
                profile_id=context.profile.id if context.profile else None,
            )
            await context.reply(biz_sect_game.build_status_text(session))
            return True
        if action == "dry-run":
            enabled = payload.lower() == "on"
            biz_sect_game.set_dry_run(
                db,
                chat_id,
                enabled,
                profile_id=context.profile.id if context.profile else None,
            )
            await context.reply(f"宗门 dry-run 已{'开启' if enabled else '关闭'}。")
            return True
        if action == "interval":
            try:
                interval_seconds = biz_fanren_game.parse_interval_input(payload)
            except ValueError as exc:
                await context.reply(f"设置失败: {exc}")
                return True
            biz_sect_game.set_interval(
                db,
                chat_id,
                interval_seconds,
                profile_id=context.profile.id if context.profile else None,
            )
            await context.reply(
                f"宗门检查间隔已设置为 {biz_fanren_game.format_duration(interval_seconds)}。"
            )
            return True
        if action == "check":
            try:
                check_command = biz_sect_game.set_check_command(
                    db,
                    chat_id,
                    payload,
                    profile_id=context.profile.id if context.profile else None,
                )
            except ValueError as exc:
                await context.reply(f"设置失败: {exc}")
                return True
            await context.reply(f"宗门查询指令已设置为: {check_command}")
            return True
        if action == "panel":
            _ok, status, _msg_id = await biz_sect_game.maybe_send_check(
                context.client,
                db,
                chat_id,
                force=True,
                command_text=".我的宗门",
                profile_id=context.profile.id if context.profile else None,
            )
            await context.reply(f"执行结果: {status}")
            return True
        if action == "sign":
            _ok, status, _msg_id = await biz_sect_game.maybe_send_check(
                context.client,
                db,
                chat_id,
                force=True,
                command_text=".宗门点卯",
                profile_id=context.profile.id if context.profile else None,
            )
            await context.reply(f"执行结果: {status}")
            return True
        if action == "teach":
            _ok, status, _msg_id = await biz_sect_game.maybe_send_check(
                context.client,
                db,
                chat_id,
                force=True,
                command_text=".宗门传功",
                profile_id=context.profile.id if context.profile else None,
            )
            await context.reply(f"执行结果: {status}")
            return True
        if action == "bounty":
            _ok, status, _msg_id = await biz_sect_game.maybe_send_check(
                context.client,
                db,
                chat_id,
                force=True,
                command_text=".宗门悬赏",
                profile_id=context.profile.id if context.profile else None,
            )
            await context.reply(f"执行结果: {status}")
            return True
        if action == "submit":
            if not payload:
                await context.reply("用法: .sect submit 问候")
                return True
            _ok, status, _msg_id = await biz_sect_game.maybe_send_check(
                context.client,
                db,
                chat_id,
                force=True,
                command_text=f".提交任务 {payload}",
                profile_id=context.profile.id if context.profile else None,
            )
            await context.reply(f"执行结果: {status}")
            return True
        if action == "hf":
            return await self._handle_huangfeng_command(context, db, payload)
        if action == "xg":
            return await self._handle_xingong_command(context, db, payload)
        if action == "lx":
            return await self._handle_lingxiao_command(context, db, payload)
        if action == "ty":
            return await self._handle_taiyi_command(context, db, payload)
        if action == "wl":
            return await self._handle_wanling_command(context, db, payload)
        if action == "ly":
            return await self._handle_simple_feature_command(
                context,
                db,
                payload,
                {
                    "status": ".灵树状态",
                    "water": ".灵树灌溉",
                    "guard": ".协同守山",
                    "harvest": ".采摘灵果",
                },
                "用法: .sect ly status|water|guard|harvest",
            )
        if action == "yl":
            return await self._handle_simple_feature_command(
                context,
                db,
                payload,
                {
                    "banner": ".我的阴罗幡",
                    "upgrade": ".升级阴罗幡",
                    "daily": ".每日献祭",
                    "convert": ".化功为煞",
                    "hunt": ".血洗山林",
                    "summon": ".召唤魔影",
                    "prison": ".囚禁魂魄",
                    "soothe": ".安抚幡灵",
                    "collect": ".收取精华",
                    "curse": ".下咒",
                    "reap": ".收割",
                },
                "用法: .sect yl banner|upgrade|daily|convert|hunt|summon|prison|soothe|collect|curse|reap",
            )
        if action == "yy":
            yy_action = (payload or "").strip().lower()
            if yy_action in {"seek", "retreat"} and (
                not context.profile
                or not biz_sect_game._is_same_sect_name(
                    context.profile.sect_name, biz_sect_game.YUANYING_SECT_NAME
                )
            ):
                await context.reply("当前角色不是元婴宗，已阻止元婴宗专属命令。")
                return True
            return await self._handle_simple_feature_command(
                context,
                db,
                payload,
                {
                    "status": ".元婴状态",
                    "trip": ".元婴出窍",
                    "retreat": ".元婴闭关",
                    "return": ".元婴归窍",
                    "seek": ".问道",
                    "skill": ".参悟功法",
                },
                "用法: .sect yy status|trip|retreat|return|seek|skill",
            )
        if action == "hh":
            return await self._handle_simple_feature_command(
                context,
                db,
                payload,
                {
                    "dual": ".闭关双修",
                    "contract": ".缔结同参",
                    "warm": ".双修 温养",
                    "mark": ".种下心印",
                    "harvest": ".双修 采补",
                    "break": ".挣脱心印",
                    "seal": ".结印",
                },
                "用法: .sect hh dual|contract|warm|mark|harvest|break|seal",
            )
        if action == "run":
            _ok, status, _msg_id = await biz_sect_game.maybe_send_check(
                context.client,
                db,
                chat_id,
                force=True,
                profile_id=context.profile.id if context.profile else None,
            )
            await context.reply(f"执行结果: {status}")
            return True

        await context.reply(
            "用法: .sect status|on|off|dry-run on|off|interval 30m|check 指令|panel|sign|teach|bounty|submit 内容|hf/xg/lx/ty/wl/ly/yl/yy/hh 子命令|run"
        )
        return True

    async def _handle_simple_feature_command(
        self,
        context: EventContext,
        db: SQLiteCompatDb,
        payload: str,
        action_map: dict,
        usage: str,
    ) -> bool:
        chat_id = context.chat_id
        if chat_id is None:
            return False
        action = (payload or "").strip().lower()
        command_text = action_map.get(action)
        if not command_text:
            await context.reply(usage)
            return True
        _ok, status, _msg_id = await biz_sect_game.maybe_send_check(
            context.client,
            db,
            chat_id,
            force=True,
            command_text=command_text,
            profile_id=context.profile.id if context.profile else None,
        )
        await context.reply(f"执行结果: {status}")
        return True


class GeneralGameExecutor(BaseExecutor):
    key = "game"

    def __init__(self) -> None:
        self._runner_started = False
        self._parsers = [
            ("basic", biz_basic_game.parse_message),
            ("breakthrough", biz_breakthrough_game.parse_message),
            ("battle", biz_battle_game.parse_message),
            ("inventory", biz_inventory_game.parse_message),
            ("artifact", biz_artifact_game.parse_message),
            ("estate", biz_estate_game.parse_message),
            ("companion", biz_companion_game.parse_message),
            ("dungeon", biz_dungeon_game.parse_message),
            ("market", biz_market_game.parse_message),
            ("stock", biz_stock_game.parse_message),
            ("diplomacy", biz_diplomacy_game.parse_message),
            ("shop", biz_shop_game.parse_message),
        ]

    async def startup(self, client: object, storage: Storage) -> None:
        if self._runner_started:
            return
        self._runner_started = True
        _register_client_background_task(
            client,
            asyncio.create_task(_run_divination_batch_scheduler(client, storage)),
        )
        _register_client_background_task(
            client,
            asyncio.create_task(_run_companion_auto_scheduler(client, storage)),
        )
        _register_client_background_task(
            client,
            asyncio.create_task(_run_fishing_auto_scheduler(client, storage)),
        )
        _register_client_background_task(
            client,
            asyncio.create_task(_run_companion_heart_tribulation_scheduler(client, storage)),
        )
        return

    async def handle(self, context: EventContext, storage: Storage) -> bool:
        if context.text.strip() == ".chatid" and context.is_profile_owner():
            binding_ref = (
                f"{context.chat_id}_{context.thread_id}"
                if context.thread_id
                else f"{context.chat_id}"
            )
            await context.reply(
                "\n".join(
                    [
                        "当前聊天信息",
                        f"绑定 ID: {binding_ref}",
                        f"Chat ID: {context.chat_id}",
                        f"Thread ID: {context.thread_id or '无'}",
                        f"类型: {'私聊' if context.is_private else '群组/频道'}",
                        f"发送者 ID: {context.sender_id}",
                        f"线程状态: {'话题线程' if context.thread_id else '主会话'}",
                    ]
                )
            )
            return True
        if not context.chat_binding:
            return False

        await self._maybe_advance_divination_batch(context, storage)

        if context.is_bot_sender and await _maybe_handle_fishing_miniapp_entry(
            context, storage
        ):
            return True

        if context.is_bot_sender and await _maybe_handle_estate_miniapp_snapshot(
            context, storage
        ):
            return True

        if context.is_bot_sender and await _maybe_handle_xinggong_starboard_miniapp_entry(
            context, storage
        ):
            return True

        if context.is_bot_sender and await _maybe_handle_tianji_trial_miniapp_entry(
            context, storage
        ):
            return True

        if (
            context.is_bot_sender
            and observe_fishing_reply(context, storage)
        ):
            return True

        if context.is_bot_sender and await self._bot_message_targets_profile(
            context, storage
        ):
            reply_text = await self._get_reply_message_text(context, storage)
            if (
                context.profile
                and context.chat_id is not None
                and reply_text
                in {
                    ".我的持仓",
                    ".股市任务",
                }
                and context.text
            ):
                # 校验回包内容确实是股票相关，过滤误匹配
                stock_keywords = (
                    "持仓",
                    "股票",
                    "浮盈",
                    "市值",
                    "仓位",
                    "股息",
                    "融资",
                )
                is_stock_reply = any(
                    kw in (context.text or "") for kw in stock_keywords
                )
                if reply_text == ".我的持仓":
                    is_stock_reply = is_stock_reply or "我的股票账户" in (
                        context.text or ""
                    )
                elif reply_text == ".股市任务":
                    is_stock_reply = is_stock_reply or "股市任务" in (
                        context.text or ""
                    )
                if is_stock_reply:
                    storage.upsert_stock_player_reply(
                        context.profile.id,
                        context.chat_id,
                        reply_text,
                        context.text,
                        thread_id=context.thread_id,
                        source_message_id=int(context.message_id or 0),
                        reply_to_msg_id=int(context.reply_to_msg_id or 0),
                    )
            for module_key, parser in self._parsers:
                parsed = parser(context.text)
                if parsed is not None:
                    if module_key == "basic" and parsed.get("event") in {
                        "basic_profile",
                        "basic_profile_pending",
                    }:
                        continue
                    if (
                        module_key == "battle"
                        and parsed.get("event") == "battle_profile"
                    ):
                        continue
                    if (
                        module_key == "artifact"
                        and parsed.get("event") == "artifact_status_profile"
                    ):
                        continue
                    if (
                        module_key == "artifact"
                        and parsed.get("event") == "artifact_touch"
                    ):
                        self._maybe_reschedule_artifact_touch(context, storage, parsed)
                    if (
                        module_key == "artifact"
                        and parsed.get("event") == "artifact_trial"
                    ):
                        self._maybe_reschedule_artifact_trial(context, storage, parsed)
                    if (
                        module_key == "artifact"
                        and parsed.get("event") == "artifact_nurture"
                    ):
                        self._maybe_reschedule_artifact_nurture(context, storage, parsed)
                    if module_key == "estate":
                        _record_estate_miniapp_payload(context, storage)
                    return True
        return False


    def _maybe_reschedule_artifact_touch(
        self, context: EventContext, storage: Storage, parsed: dict
    ) -> None:
        if not context.profile or context.chat_id is None:
            return
        task = storage.get_companion_auto_task(
            context.profile.id,
            context.chat_id,
            ARTIFACT_TOUCH_FEATURE_KEY,
        )
        if not task or not bool(task.get("enabled")):
            return
        task_thread_id = task.get("thread_id")
        if task_thread_id and (
            not context.thread_id or int(task_thread_id) != int(context.thread_id)
        ):
            return
        reschedule_artifact_touch_auto_on_reply(
            storage,
            profile_id=context.profile.id,
            chat_id=context.chat_id,
            reply_to_msg_id=int(context.reply_to_msg_id or 0),
            reply_text=context.text,
            now=time.time(),
        )


    def _maybe_reschedule_artifact_trial(
        self, context: EventContext, storage: Storage, parsed: dict
    ) -> None:
        if not context.profile or context.chat_id is None:
            return
        task = storage.get_companion_auto_task(
            context.profile.id,
            context.chat_id,
            ARTIFACT_TRIAL_FEATURE_KEY,
        )
        if not task or not bool(task.get("enabled")):
            return
        task_thread_id = task.get("thread_id")
        if task_thread_id and (
            not context.thread_id or int(task_thread_id) != int(context.thread_id)
        ):
            return
        reschedule_artifact_trial_auto_on_reply(
            storage,
            profile_id=context.profile.id,
            chat_id=context.chat_id,
            reply_to_msg_id=int(context.reply_to_msg_id or 0),
            reply_text=context.text,
            now=time.time(),
        )


    def _maybe_reschedule_artifact_nurture(
        self, context: EventContext, storage: Storage, parsed: dict
    ) -> None:
        if not context.profile or context.chat_id is None:
            return
        task = storage.get_companion_auto_task(
            context.profile.id,
            context.chat_id,
            ARTIFACT_NURTURE_FEATURE_KEY,
        )
        if not task or not bool(task.get("enabled")):
            return
        task_thread_id = task.get("thread_id")
        if task_thread_id and (
            not context.thread_id or int(task_thread_id) != int(context.thread_id)
        ):
            return
        reschedule_artifact_nurture_auto_on_reply(
            storage,
            profile_id=context.profile.id,
            chat_id=context.chat_id,
            reply_to_msg_id=int(context.reply_to_msg_id or 0),
            reply_text=context.text,
            now=time.time(),
        )


    async def _maybe_advance_companion_heart_tribulation(
        self, context: EventContext, storage: Storage
    ) -> bool:
        if not context.profile or context.chat_id is None:
            return False
        task = storage.get_companion_heart_tribulation_task(
            context.profile.id,
            context.chat_id,
            thread_id=context.thread_id,
        )
        if not task or not bool(task.get("enabled")):
            return False

        task_id = int(task.get("id") or 0)
        if not task_id:
            return False

        workflow_state = str(task.get("workflow_state") or "").strip()
        if workflow_state in {
            "",
            COMPANION_HEART_TRIBULATION_IDLE_STATE,
            COMPANION_HEART_TRIBULATION_SENDING_PANEL_STATE,
            COMPANION_HEART_TRIBULATION_FAILED_STATE,
        }:
            return False

        task_thread_id = int(task.get("thread_id")) if task.get("thread_id") else None
        if (
            task_thread_id is not None
            and context.thread_id is not None
            and context.thread_id != task_thread_id
        ):
            return False

        if not _is_context_sender_allowed_bot(context):
            return False

        sender = getattr(context.event, "sender", None)
        sender_username = (getattr(sender, "username", "") or "").strip()
        current_message_id = int(context.message_id or 0)
        current_reply_to_msg_id = int(context.reply_to_msg_id or 0)
        current_sender_id = int(context.sender_id or 0)
        current_text = context.text or ""
        is_edited_event = _is_edited_event(context)

        if workflow_state == COMPANION_HEART_TRIBULATION_AWAIT_PANEL_STATE:
            expected_reply_to = int(task.get("anchor_command_msg_id") or 0)
            if expected_reply_to <= 0:
                _stop_companion_heart_tribulation_task(
                    storage,
                    task,
                    last_error="自动共历心劫缺少侍妾命令锚点，已停止自动。",
                    step=workflow_state,
                )
                return True
            if current_reply_to_msg_id != expected_reply_to:
                return False
            if not current_message_id:
                return False
            _append_companion_heart_tribulation_log(
                storage,
                task,
                step=workflow_state,
                event_type="panel_reply_received",
                message_id=current_message_id,
                reply_to_msg_id=current_reply_to_msg_id,
                sender_id=current_sender_id,
                sender_username=sender_username,
                text=current_text,
            )
            if _defer_companion_heart_tribulation_if_voyaging(
                storage,
                task,
                text=current_text,
                now=time.time(),
                step=workflow_state,
            ):
                return True
            panel_cooldown_target = _resolve_companion_panel_cooldown_target(
                {"text": current_text, "created_at": time.time()},
                "heart_tribulation",
            )
            if panel_cooldown_target is None:
                storage.update_companion_heart_tribulation_task(
                    task_id,
                    workflow_state=COMPANION_HEART_TRIBULATION_IDLE_STATE,
                    next_run_at=time.time() + COMPANION_VOYAGE_RECHECK_SECONDS,
                    step_deadline_at=0,
                    last_error="侍妾面板缺少共历心劫冷却，稍后刷新再判断。",
                )
                return True
            if panel_cooldown_target > time.time():
                storage.update_companion_heart_tribulation_task(
                    task_id,
                    workflow_state=COMPANION_HEART_TRIBULATION_IDLE_STATE,
                    next_run_at=panel_cooldown_target,
                    step_deadline_at=0,
                    last_error="",
                )
                return True
            try:
                command_message = await _send_companion_heart_tribulation_command(
                    context.client,
                    storage,
                    task,
                    text=COMPANION_HEART_TRIBULATION_COMMAND,
                    reply_to_msg_id=current_message_id,
                )
            except Exception as exc:
                _stop_companion_heart_tribulation_task(
                    storage,
                    task,
                    last_error=f"发送{COMPANION_HEART_TRIBULATION_COMMAND}失败，已停止自动共历心劫。",
                    step="send_tribulation_command",
                    detail={"error": str(exc)},
                )
                return True
            storage.update_companion_heart_tribulation_task(
                task_id,
                workflow_state=COMPANION_HEART_TRIBULATION_AWAIT_TRIBULATION_STATE,
                step_deadline_at=time.time() + COMPANION_HEART_TRIBULATION_STEP_TIMEOUT_SECONDS,
                last_run_at=time.time(),
                matched_bot_id=current_sender_id,
                anchor_bot_msg_id=current_message_id,
                panel_reply_msg_id=current_message_id,
                tribulation_command_msg_id=int(getattr(command_message, "id", 0) or 0),
                last_tribulation_command_at=time.time(),
                last_error="",
            )
            task = storage.get_companion_heart_tribulation_task(
                context.profile.id,
                context.chat_id,
                thread_id=context.thread_id,
            ) or task
            _append_companion_heart_tribulation_log(
                storage,
                task,
                step=COMPANION_HEART_TRIBULATION_AWAIT_TRIBULATION_STATE,
                event_type="send_tribulation_command",
                message_id=int(getattr(command_message, "id", 0) or 0),
                reply_to_msg_id=current_message_id,
                text=COMPANION_HEART_TRIBULATION_COMMAND,
            )
            return True

        if workflow_state == COMPANION_HEART_TRIBULATION_AWAIT_TRIBULATION_STATE:
            expected_reply_to = int(task.get("tribulation_command_msg_id") or 0)
            if expected_reply_to <= 0:
                _stop_companion_heart_tribulation_task(
                    storage,
                    task,
                    last_error="自动共历心劫缺少心劫命令锚点，已停止自动。",
                    step=workflow_state,
                )
                return True
            if current_reply_to_msg_id != expected_reply_to:
                return False
            if not current_message_id:
                return False
            round1_command = _build_companion_heart_tribulation_action_command(task, 1)
            _append_companion_heart_tribulation_log(
                storage,
                task,
                step=workflow_state,
                event_type="tribulation_reply_received",
                message_id=current_message_id,
                reply_to_msg_id=current_reply_to_msg_id,
                sender_id=current_sender_id,
                sender_username=sender_username,
                text=current_text,
            )
            if _defer_companion_heart_tribulation_if_voyaging(
                storage,
                task,
                text=current_text,
                now=time.time(),
                step=workflow_state,
            ):
                return True
            try:
                action_message = await _send_companion_heart_tribulation_command(
                    context.client,
                    storage,
                    task,
                    text=round1_command,
                    reply_to_msg_id=current_message_id,
                )
            except Exception as exc:
                _stop_companion_heart_tribulation_task(
                    storage,
                    task,
                    last_error="发送第一轮心劫策略失败，已停止自动共历心劫。",
                    step="send_round1",
                    detail={"error": str(exc), "command": round1_command},
                )
                return True
            fingerprint = _build_companion_heart_tribulation_event_fingerprint(
                message_id=current_message_id,
                text=current_text,
                event_kind="tribulation_reply",
            )
            storage.update_companion_heart_tribulation_task(
                task_id,
                workflow_state=COMPANION_HEART_TRIBULATION_AWAIT_ROUND1_EDIT_STATE,
                step_deadline_at=time.time() + COMPANION_HEART_TRIBULATION_EDIT_STALL_SECONDS,
                last_run_at=time.time(),
                matched_bot_id=current_sender_id,
                tribulation_msg_id=current_message_id,
                anchor_bot_msg_id=current_message_id,
                last_action_round_sent=1,
                last_progress_at=time.time(),
                last_progress_fingerprint=fingerprint,
                last_stable_sent_at=time.time(),
                round_retry_count=0,
                round_retry_deadline_at=time.time() + COMPANION_HEART_TRIBULATION_ROUND_RETRY_SECONDS,
                last_error="",
            )
            task = storage.get_companion_heart_tribulation_task(
                context.profile.id,
                context.chat_id,
                thread_id=context.thread_id,
            ) or task
            _append_companion_heart_tribulation_log(
                storage,
                task,
                step=COMPANION_HEART_TRIBULATION_AWAIT_ROUND1_EDIT_STATE,
                event_type="send_round1",
                message_id=int(getattr(action_message, "id", 0) or 0),
                reply_to_msg_id=current_message_id,
                text=round1_command,
            )
            return True

        tribulation_msg_id = int(task.get("tribulation_msg_id") or 0)
        if workflow_state == COMPANION_HEART_TRIBULATION_AWAIT_SETTLEMENT_STATE and not is_edited_event:
            if COMPANION_HEART_TRIBULATION_SETTLEMENT_KEYWORD in current_text and current_sender_id in _binding_bot_ids(context):
                _append_companion_heart_tribulation_log(
                    storage,
                    task,
                    step=workflow_state,
                    event_type="settlement_received",
                    message_id=current_message_id,
                    reply_to_msg_id=current_reply_to_msg_id,
                    sender_id=current_sender_id,
                    sender_username=sender_username,
                    text=current_text,
                )
                previous_settlement_text = str(task.get("last_settlement_text") or "")
                previous_settlement_at = float(task.get("last_settlement_at") or 0)
                updated_task = storage.update_companion_heart_tribulation_task(
                    task_id,
                    workflow_state=COMPANION_HEART_TRIBULATION_IDLE_STATE,
                    step_deadline_at=0,
                    matched_bot_id=0,
                    anchor_command_msg_id=0,
                    anchor_bot_msg_id=0,
                    tribulation_command_msg_id=0,
                    tribulation_msg_id=0,
                    panel_reply_msg_id=0,
                    last_action_round_sent=0,
                    last_tribulation_command_at=0,
                    last_progress_at=time.time(),
                    last_progress_fingerprint="",
                    last_stable_sent_at=0,
                    last_settlement_text=current_text,
                    last_settlement_at=time.time(),
                    previous_settlement_text=previous_settlement_text,
                    previous_settlement_at=previous_settlement_at,
                    last_error="",
                )
                task = updated_task or task
                _append_companion_heart_tribulation_log(
                    storage,
                    task,
                    step="completed",
                    event_type="settlement_recorded",
                    message_id=current_message_id,
                    sender_id=current_sender_id,
                    sender_username=sender_username,
                    text=current_text,
                )
                return True
            return False
        if tribulation_msg_id <= 0 or current_message_id != tribulation_msg_id or not is_edited_event:
            return False
        if matched_bot_id > 0 and current_sender_id != matched_bot_id:
            # 星宫/心劫链路里不同阶段的回包可能由不同的允许 bot 发出，
            # 编辑阶段只要求仍然是允许的星宫 bot，避免把真实的成功编辑误过滤。
            if current_sender_id not in _binding_bot_ids(context):
                return False

        current_fingerprint = _build_companion_heart_tribulation_event_fingerprint(
            message_id=current_message_id,
            text=current_text,
            event_kind="edited",
        )
        if current_fingerprint == str(task.get("last_progress_fingerprint") or ""):
            return True

        _append_companion_heart_tribulation_log(
            storage,
            task,
            step=workflow_state,
            event_type="message_edited",
            message_id=current_message_id,
            reply_to_msg_id=current_reply_to_msg_id,
            sender_id=current_sender_id,
            sender_username=sender_username,
            text=current_text,
        )

        storage.update_companion_heart_tribulation_task(
            task_id,
            step_deadline_at=time.time() + COMPANION_HEART_TRIBULATION_EDIT_STALL_SECONDS,
            last_progress_at=time.time(),
            last_progress_fingerprint=current_fingerprint,
        )
        task = storage.update_companion_heart_tribulation_task(task_id) or task

        if COMPANION_HEART_TRIBULATION_SETTLEMENT_KEYWORD in current_text:
            previous_settlement_text = str(task.get("last_settlement_text") or "")
            previous_settlement_at = float(task.get("last_settlement_at") or 0)
            completed_run_id = str(task.get("run_id") or "")
            updated_task = storage.update_companion_heart_tribulation_task(
                task_id,
                workflow_state=COMPANION_HEART_TRIBULATION_IDLE_STATE,
                step_deadline_at=0,
                matched_bot_id=0,
                anchor_command_msg_id=0,
                anchor_bot_msg_id=0,
                tribulation_command_msg_id=0,
                tribulation_msg_id=0,
                panel_reply_msg_id=0,
                last_action_round_sent=0,
                last_tribulation_command_at=0,
                last_progress_at=time.time(),
                last_progress_fingerprint=current_fingerprint,
                last_stable_sent_at=0,
                last_settlement_text=current_text,
                last_settlement_at=time.time(),
                previous_settlement_text=previous_settlement_text,
                previous_settlement_at=previous_settlement_at,
                last_error="",
            )
            task = updated_task or task
            _append_companion_heart_tribulation_log(
                storage,
                task,
                step="completed",
                event_type="settlement_recorded",
                message_id=current_message_id,
                sender_id=current_sender_id,
                sender_username=sender_username,
                text=current_text,
            )
            fresh_payload = await asyncio.to_thread(
                _refresh_companion_payload, storage, context.profile.id
            )
            if not fresh_payload or not isinstance(fresh_payload, dict):
                _stop_companion_heart_tribulation_task(
                    storage,
                    task,
                    last_error="结算后刷新侍妾冷却失败，已停止自动共历心劫。",
                    step="post_settlement_refresh",
                )
                return True
            next_run_at = _resolve_companion_heart_tribulation_next_run_at(fresh_payload)
            if next_run_at is None:
                _stop_companion_heart_tribulation_task(
                    storage,
                    task,
                    last_error="结算后无法解析最新共历心劫冷却，已停止自动。",
                    step="post_settlement_cooldown",
                )
                return True
            storage.update_companion_heart_tribulation_task(
                task_id,
                enabled=1,
                run_id="",
                workflow_state=COMPANION_HEART_TRIBULATION_IDLE_STATE,
                next_run_at=next_run_at,
                step_deadline_at=0,
            )
            return True

        if workflow_state == COMPANION_HEART_TRIBULATION_AWAIT_ROUND1_EDIT_STATE:
            if COMPANION_HEART_TRIBULATION_ROUND1_LOCK_KEYWORD not in current_text:
                return True
            round2_command = _build_companion_heart_tribulation_action_command(task, 2)
            try:
                action_message = await _send_companion_heart_tribulation_command(
                    context.client,
                    storage,
                    task,
                    text=round2_command,
                    reply_to_msg_id=current_message_id,
                )
            except Exception as exc:
                _stop_companion_heart_tribulation_task(
                    storage,
                    task,
                    last_error="发送第二轮心劫策略失败，已停止自动共历心劫。",
                    step="send_round2",
                    detail={"error": str(exc), "command": round2_command},
                )
                return True
            storage.update_companion_heart_tribulation_task(
                task_id,
                workflow_state=COMPANION_HEART_TRIBULATION_AWAIT_ROUND2_EDIT_STATE,
                step_deadline_at=time.time() + COMPANION_HEART_TRIBULATION_EDIT_STALL_SECONDS,
                last_action_round_sent=2,
                last_progress_at=time.time(),
                last_progress_fingerprint=current_fingerprint,
                last_stable_sent_at=time.time(),
                round_retry_count=0,
                round_retry_deadline_at=time.time() + COMPANION_HEART_TRIBULATION_ROUND_RETRY_SECONDS,
                last_error="",
            )
            task = storage.get_companion_heart_tribulation_task(
                context.profile.id,
                context.chat_id,
                thread_id=context.thread_id,
            ) or task
            _append_companion_heart_tribulation_log(
                storage,
                task,
                step=COMPANION_HEART_TRIBULATION_AWAIT_ROUND2_EDIT_STATE,
                event_type="send_round2",
                message_id=int(getattr(action_message, "id", 0) or 0),
                reply_to_msg_id=current_message_id,
                text=round2_command,
            )
            return True

        if workflow_state == COMPANION_HEART_TRIBULATION_AWAIT_ROUND2_EDIT_STATE:
            if COMPANION_HEART_TRIBULATION_ROUND2_LOCK_KEYWORD not in current_text:
                return True
            round3_command = _build_companion_heart_tribulation_action_command(task, 3)
            try:
                action_message = await _send_companion_heart_tribulation_command(
                    context.client,
                    storage,
                    task,
                    text=round3_command,
                    reply_to_msg_id=current_message_id,
                )
            except Exception as exc:
                _stop_companion_heart_tribulation_task(
                    storage,
                    task,
                    last_error="发送第三轮心劫策略失败，已停止自动共历心劫。",
                    step="send_round3",
                    detail={"error": str(exc), "command": round3_command},
                )
                return True
            storage.update_companion_heart_tribulation_task(
                task_id,
                workflow_state=COMPANION_HEART_TRIBULATION_AWAIT_SETTLEMENT_STATE,
                step_deadline_at=time.time() + COMPANION_HEART_TRIBULATION_EDIT_STALL_SECONDS,
                last_action_round_sent=3,
                last_progress_at=time.time(),
                last_progress_fingerprint=current_fingerprint,
                last_stable_sent_at=time.time(),
                round_retry_count=0,
                round_retry_deadline_at=time.time() + COMPANION_HEART_TRIBULATION_ROUND_RETRY_SECONDS,
                last_error="",
            )
            task = storage.get_companion_heart_tribulation_task(
                context.profile.id,
                context.chat_id,
                thread_id=context.thread_id,
            ) or task
            _append_companion_heart_tribulation_log(
                storage,
                task,
                step=COMPANION_HEART_TRIBULATION_AWAIT_SETTLEMENT_STATE,
                event_type="send_round3",
                message_id=int(getattr(action_message, "id", 0) or 0),
                reply_to_msg_id=current_message_id,
                text=round3_command,
            )
            return True

        if workflow_state == COMPANION_HEART_TRIBULATION_AWAIT_SETTLEMENT_STATE:
            return True

        return False

    async def _maybe_advance_divination_batch(
        self, context: EventContext, storage: Storage
    ) -> None:
        if not context.profile or context.chat_id is None:
            return
        batch = storage.get_active_divination_batch(context.profile.id, context.chat_id)
        if not batch:
            return

        if context.is_outgoing:
            if context.text.strip() != DIVINATION_COMMAND or not context.message_id:
                return
            storage.update_divination_batch(
                int(batch["id"]),
                thread_id=context.thread_id or batch.get("thread_id"),
                sent_count=max(int(batch.get("sent_count") or 0), 0) + 1,
                pending_command_msg_id=0,
            )
        return

    async def _maybe_resume_idle_divination_batch(
        self,
        context: EventContext,
        storage: Storage,
        batch: dict,
        planned_rounds: int,
    ) -> bool:
        if planned_rounds <= 0:
            storage.finish_divination_batch(int(batch["id"]), status="completed")
            return True

        pending_command_msg_id = int(batch.get("pending_command_msg_id") or 0)
        if pending_command_msg_id:
            return False

        completed_count = max(int(batch.get("completed_count") or 0), 0)
        if completed_count >= planned_rounds:
            storage.finish_divination_batch(int(batch["id"]), status="completed")
            return True

        thread_id = int(batch.get("thread_id")) if batch.get("thread_id") else None
        latest_command = storage.get_latest_outgoing_command(
            int(batch.get("chat_id") or context.chat_id),
            profile_id=context.profile.id,
            text=DIVINATION_COMMAND,
            thread_id=thread_id,
        )
        if latest_command:
            latest_status = str(latest_command.get("status") or "").strip()
            latest_updated_at = float(latest_command.get("updated_at") or 0)
            batch_updated_at = float(batch.get("updated_at") or 0)
            if _has_pending_outgoing_command(
                storage,
                profile_id=context.profile.id,
                chat_id=int(batch.get("chat_id") or context.chat_id),
                text=DIVINATION_COMMAND,
                thread_id=thread_id,
            ):
                return True
            if (
                latest_status in OUTGOING_CONFIRMED_STATUSES
                and latest_updated_at >= batch_updated_at
            ):
                return True

        storage.enqueue_outgoing_command(
            profile_id=context.profile.id,
            chat_id=int(batch.get("chat_id") or context.chat_id),
            text=DIVINATION_COMMAND,
            thread_id=thread_id,
            chat_type=str(batch.get("chat_type") or "group"),
            bot_username=str(batch.get("bot_username") or ""),
        )
        return True

    async def _send(self, context: EventContext, command_text: str) -> bool:
        await send_message_with_thread_fallback(
            context.client,
            context.chat_id,
            command_text,
            thread_id=context.thread_id,
            storage=None,
            profile_id=context.profile.id if context.profile else None,
            bot_username=(
                context.chat_binding.bot_username if context.chat_binding else ""
            ),
            log_prefix="Runtime executor",
        )
        await context.reply(f"执行结果: sent `{command_text}`")
        return True

    async def _handle_huangfeng_command(
        self, context: EventContext, db: SQLiteCompatDb, payload: str
    ) -> bool:
        chat_id = context.chat_id
        if chat_id is None:
            return False
        session = biz_sect_game.get_session(
            db,
            chat_id,
            profile_id=context.profile.id if context.profile else None,
        )
        parts = (payload or "").split(maxsplit=2)
        action = parts[0].lower() if parts else ""
        command_texts = []
        if action == "garden":
            command_texts = [".小药园"]
        elif action == "sow":
            if len(parts) >= 3:
                command_texts = [f".播种 {parts[1]} {parts[2]}"]
            elif len(parts) >= 2:
                command_texts = [f".播种 {parts[1]}"]
        elif action == "harvest":
            if len(parts) >= 2:
                command_texts = [f".采药 {parts[1]}"]
            else:
                command_texts = [".采药"]
        elif action == "weed":
            if len(parts) >= 2:
                command_texts = [f".除草 {parts[1]}"]
            else:
                command_texts = [".除草"]
        elif action == "bug":
            if len(parts) >= 2:
                command_texts = [f".除虫 {parts[1]}"]
            else:
                command_texts = [".除虫"]
        elif action == "water":
            if len(parts) >= 2:
                command_texts = [f".浇水 {parts[1]}"]
            else:
                command_texts = [".浇水"]
        elif action == "expand":
            command_texts = [".扩建药园"]
        elif action == "auto":
            auto_body = parts[1] if len(parts) >= 2 else ""
            if len(parts) >= 3:
                auto_body = f"{parts[1]} {parts[2]}".strip()
            auto_parts = auto_body.split(maxsplit=1)
            auto_action = auto_parts[0].lower() if auto_parts else "status"
            auto_payload = auto_parts[1].strip() if len(auto_parts) > 1 else ""
            if auto_action == "on":
                seed_name = (
                    auto_payload
                    or str((session or {}).get("huangfeng_seed_name") or "").strip()
                )
                if not seed_name:
                    await context.reply("用法: .sect hf auto on 种子名")
                    return True
                biz_sect_game.configure_huangfeng_auto(
                    db,
                    chat_id,
                    True,
                    seed_name=seed_name,
                    profile_id=context.profile.id if context.profile else None,
                )
                await context.reply(f"黄枫谷自动化已开启，播种种子为 {seed_name}。")
                return True
            if auto_action == "off":
                biz_sect_game.configure_huangfeng_auto(
                    db,
                    chat_id,
                    False,
                    profile_id=context.profile.id if context.profile else None,
                )
                await context.reply("黄枫谷自动化已关闭。")
                return True
            if auto_action == "seed":
                if not auto_payload:
                    await context.reply("用法: .sect hf auto seed 种子名")
                    return True
                biz_sect_game.set_huangfeng_seed(
                    db,
                    chat_id,
                    auto_payload,
                    profile_id=context.profile.id if context.profile else None,
                )
                await context.reply(f"黄枫谷自动播种种子已设置为 {auto_payload}。")
                return True
            if auto_action == "exchange":
                enabled = auto_payload.lower() == "on"
                biz_sect_game.set_huangfeng_exchange_auto(
                    db,
                    chat_id,
                    enabled,
                    profile_id=context.profile.id if context.profile else None,
                )
                await context.reply(
                    f"黄枫谷自动兑换种子已{'开启' if enabled else '关闭'}。"
                )
                return True
            if auto_action == "status":
                refreshed_session = biz_sect_game.get_session(
                    db,
                    chat_id,
                    profile_id=context.profile.id if context.profile else None,
                )
                await context.reply(
                    "\n".join(
                        [
                            "黄枫谷自动化状态",
                            f"开关: {'开启' if refreshed_session.get('auto_huangfeng_enabled') else '关闭'}",
                            f"播种种子: {refreshed_session.get('huangfeng_seed_name') or '-'}",
                            f"自动兑换: {'开启' if refreshed_session.get('auto_huangfeng_exchange_enabled') else '关闭'}",
                            f"下次检查: {biz_sect_game.format_timestamp(refreshed_session.get('huangfeng_next_check_time') or 0)}",
                            f"状态来源: {refreshed_session.get('huangfeng_next_check_source') or '-'}",
                        ]
                    )
                )
                return True
        if not command_texts:
            await context.reply(
                "用法: .sect hf garden|sow [地块] 种子|harvest [地块]|weed [地块]|bug [地块]|water [地块]|expand|auto on 种子|off|seed 种子|exchange on|off|status"
            )
            return True
        if len(command_texts) > 1 and not session:
            await context.reply(
                "黄枫谷会话未初始化，请先执行 .sect on 或 .sect hf garden。"
            )
            return True
        if len(command_texts) > 1 and not biz_sect_game._get_huangfeng_known_plots(session):
            await context.reply(
                "缺少最近药园状态，请先执行 .sect hf garden 后再省略地块。"
            )
            return True
        command_text = command_texts[0]
        _ok, status, _msg_id = await biz_sect_game.maybe_send_check(
            context.client,
            db,
            chat_id,
            force=True,
            command_text=command_text,
            profile_id=context.profile.id if context.profile else None,
        )
        if status == "sent" and len(command_texts) > 1:
            storage = getattr(context.client, "_tg_game_storage", None)
            if storage and context.profile:
                for index, extra_command in enumerate(command_texts[1:], start=1):
                    storage.enqueue_outgoing_command(
                        profile_id=context.profile.id,
                        chat_id=chat_id,
                        text=extra_command,
                        thread_id=session.get("thread_id")
                        if session
                        else context.thread_id,
                        chat_type="group",
                        bot_username=(
                            context.chat_binding.bot_username
                            if context.chat_binding
                            else ""
                        ),
                        delay_seconds=index * 3,
                    )
                await context.reply(
                    f"执行结果: {status}，已按最近药园状态为全部地块排队 {len(command_texts)} 条命令。"
                )
                return True
        await context.reply(f"执行结果: {status}")
        return True
    async def _handle_taiyi_command(
        self, context: EventContext, db: SQLiteCompatDb, payload: str
    ) -> bool:
        chat_id = context.chat_id
        if chat_id is None:
            return False
        parts = (payload or "").split(maxsplit=1)
        action = parts[0].lower() if parts else ""
        argument = parts[1] if len(parts) > 1 else ""
        command_text = None
        if action == "guide":
            if argument not in {"金", "木", "水", "火", "土"}:
                await context.reply("用法: .sect ty guide 金|木|水|火|土")
                return True
            command_text = f".引道 {argument}"
        elif action == "shock":
            command_text = ".神识冲击"
        if not command_text:
            await context.reply("用法: .sect ty guide 金|木|水|火|土|shock")
            return True
        _ok, status, _msg_id = await biz_sect_game.maybe_send_check(
            context.client,
            db,
            chat_id,
            force=True,
            command_text=command_text,
            profile_id=context.profile.id if context.profile else None,
        )
        await context.reply(f"执行结果: {status}")
        return True
    async def _handle_wanling_command(
        self, context: EventContext, db: SQLiteCompatDb, payload: str
    ) -> bool:
        chat_id = context.chat_id
        if chat_id is None:
            return False
        parts = (payload or "").split(maxsplit=2)
        action = parts[0].lower() if parts else ""
        command_text = None
        if action == "search":
            command_text = ".寻觅灵兽"
        elif action == "status":
            command_text = ".我的灵兽"
        elif action == "feed" and len(parts) >= 3:
            command_text = f".喂养 {parts[1]} {parts[2]}"
        elif action == "battle" and len(parts) >= 2:
            command_text = f".灵兽出战 {parts[1]}"
        elif action == "rest":
            command_text = ".灵兽休息"
        elif action == "farm":
            command_text = ".一键放养"
        elif action == "steal":
            command_text = ".灵兽偷菜"
        elif action == "abyss":
            command_text = ".探渊"
        if not command_text:
            await context.reply(
                "用法: .sect wl search|status|feed 灵兽 物品*数量|battle 灵兽|rest|farm|steal|abyss"
            )
            return True
        _ok, status, _msg_id = await biz_sect_game.maybe_send_check(
            context.client,
            db,
            chat_id,
            force=True,
            command_text=command_text,
            profile_id=context.profile.id if context.profile else None,
        )
        await context.reply(f"执行结果: {status}")
        return True
    async def _handle_lingxiao_command(
        self, context: EventContext, db: SQLiteCompatDb, payload: str
    ) -> bool:
        chat_id = context.chat_id
        if chat_id is None:
            return False
        action = (payload or "").strip().lower()
        command_text = None
        if action == "status":
            command_text = ".天阶状态"
        elif action == "mind":
            command_text = ".问心台"
        elif action == "step":
            command_text = ".登天阶"
        elif action == "wind":
            command_text = ".引九天罡风"
        elif action == "gate":
            command_text = ".借天门势"
        elif action == "overview":
            command_text = ".凌霄宫"
        if not command_text:
            await context.reply("用法: .sect lx overview|status|mind|step|wind|gate")
            return True
        _ok, status, _msg_id = await biz_sect_game.maybe_send_check(
            context.client,
            db,
            chat_id,
            force=True,
            command_text=command_text,
            profile_id=context.profile.id if context.profile else None,
        )
        await context.reply(f"执行结果: {status}")
        return True
    async def _handle_xingong_command(
        self, context: EventContext, db: SQLiteCompatDb, payload: str
    ) -> bool:
        chat_id = context.chat_id
        if chat_id is None:
            return False
        parts = payload.split(maxsplit=2)
        if not parts:
            await context.reply(
                "用法: .sect xg matrix|assist|starboard|divine|shift @目标|companion"
            )
            return True
        action = parts[0].lower()
        command_text = None
        if action == "matrix":
            command_text = ".启阵"
        elif action == "assist":
            command_text = ".助阵"
        elif action == "starboard":
            await context.reply(
                "观星台入口已改由 Web 页面通过公共洞府获取，不再发送 .观星台。"
            )
            return True
        elif action in {"pull", "collect", "soothe"}:
            await context.reply(
                "观星台已迁移 MiniApp；请在 Web 页面使用公共洞府入口，后续安抚、收集、牵星由 MiniApp API 接管。"
            )
            return True
        elif action == "divine":
            command_text = ".观星"
        elif action == "shift" and len(parts) >= 2:
            command_text = f".改换星移 {parts[1]}"
        elif action == "companion":
            command_text = ".我的侍妾"
        if not command_text:
            await context.reply(
                "用法: .sect xg matrix|assist|starboard|divine|shift @目标|companion"
            )
            return True
        _ok, status, _msg_id = await biz_sect_game.maybe_send_check(
            context.client,
            db,
            chat_id,
            force=True,
            command_text=command_text,
            profile_id=context.profile.id if context.profile else None,
        )
        await context.reply(f"执行结果: {status}")
        return True


async def observe_companion_heart_tribulation_event(
    context: EventContext, storage: Storage
) -> bool:
    observer = GeneralGameExecutor()
    return await observer._maybe_advance_companion_heart_tribulation(context, storage)
