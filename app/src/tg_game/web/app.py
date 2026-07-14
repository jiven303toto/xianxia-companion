import asyncio
import json
import time
import logging
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus
import biz_fanren_game
import biz_fishing_game
import biz_small_world_game
from tg_game import pagoda_auto
import biz_sect_game
from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from tg_game.clients.asc_client import AscAuthError
from tg_game.config import get_settings
from tg_game.module_commands import MODULE_COMMANDS
from tg_game.features.artifact.biz_artifact_touch_auto import (
    ARTIFACT_TOUCH_AWAIT_REPLY_STATE,
    ARTIFACT_TOUCH_BOT_COOLDOWN_STATE,
    ARTIFACT_TOUCH_DEFAULT_INTERVAL_SECONDS,
    ARTIFACT_TOUCH_FEATURE_KEY,
    ARTIFACT_TOUCH_MIN_INTERVAL_SECONDS,
)
from tg_game.features.artifact.biz_artifact_trial import (
    ARTIFACT_TRIAL_AWAIT_REPLY_STATE,
    ARTIFACT_TRIAL_BOT_COOLDOWN_STATE,
    ARTIFACT_TRIAL_DEFAULT_ARTIFACT_NAME,
    ARTIFACT_TRIAL_FEATURE_KEY,
    ARTIFACT_TRIAL_STOPPED_RESOURCES_STATE,
    build_artifact_trial_resource_state,
)
from tg_game.features.companion.biz_companion_cooldown import normalize_wild_experience_strategy
from tg_game.features.companion.biz_companion_voyage import (
    COMPANION_VOYAGE_STRATEGY_OPTIONS,
    normalize_companion_voyage_strategy,
)
from tg_game.features.countdowns.biz_countdowns_view_model import (
    build_auto_task_countdown_items as _countdown_build_auto_task_countdown_items,
    build_companion_voyage_countdown_items as _countdown_build_companion_voyage_countdown_items,
    build_countdown_item_for_now as _countdown_build_item_for_now,
    build_cultivation_countdown_items as _countdown_build_cultivation_countdown_items,
    build_sect_countdown_items as _countdown_build_sect_countdown_items,
    build_small_world_countdown_items as _countdown_build_small_world_countdown_items,
    build_tianxing_countdown_items as _countdown_build_tianxing_countdown_items,
    build_wanling_roam_countdown_items as _countdown_build_wanling_roam_countdown_items,
    build_xinggong_slot_countdown_items as _countdown_build_xinggong_slot_countdown_items,
    format_countdown_display_for_now as _countdown_format_display_for_now,
    sort_countdown_items,
)
from tg_game.features.fishing.biz_fishing_view_model import build_fishing_view
from tg_game.features.fishing import biz_fishing_daily_auto
from tg_game.features.fishing import biz_fishing_miniapp as fishing_miniapp
from tg_game.features.small_world.biz_small_world_view_model import (
    build_small_world_auto_view as _small_world_build_small_world_auto_view,
)
from tg_game.features.small_world.biz_small_world_auto import (
    resolve_awaited_action_command as _resolve_small_world_awaited_action_command,
)
from tg_game.features.sect.biz_sect_metadata import SECT_METADATA as _sect_SECT_METADATA
from tg_game.features.sect.biz_sect_view_model import (
    NO_SECT_NAMES as _sect_NO_SECT_NAMES,
    build_sect_daily_view as _sect_build_sect_daily_view,
    build_sect_recent_reply_text as _sect_build_sect_recent_reply_text,
    build_sect_treasury_items as _sect_build_sect_treasury_items,
    has_joined_sect as _sect_has_joined_sect,
    is_sect_related_message as _sect_is_sect_related_message,
    is_tianxing_sect_profile as _sect_is_tianxing_sect_profile,
    merge_sect_daily_view_with_session as _sect_merge_sect_daily_view_with_session,
    normalize_sect_name_text as _sect_normalize_sect_name_text,
    sect_matches_current as _sect_viewmodel_sect_matches_current,
)
from tg_game.features import biz_mulan_feature as mulan_feature
from tg_game.features.stock.biz_stock_view_model import (
    STOCK_HISTORY_RANGE_OPTIONS,
    build_stock_history_response as _stock_build_stock_history_response,
    build_stock_trend_points as _stock_build_stock_trend_points,
    clean_stock_name as _stock_clean_stock_name,
    decorate_stock_history as _stock_decorate_stock_history,
    parse_stock_market_batch as _stock_parse_stock_market_batch,
    resolve_stock_history_range as _stock_resolve_stock_history_range,
)
from tg_game.features.stock.biz_stock_page_state import (
    build_stock_view as _stock_build_stock_view,
    latest_stock_player_reply_view as _stock_latest_stock_player_reply_view,
)
from tg_game.features.tianxing import (
    get_status_snapshot as get_tianxing_status_snapshot,
    send_command as send_tianxing_command,
    set_profile_config as set_tianxing_profile_config,
    start_craft_loop as start_tianxing_craft_loop,
    start_or_advance_timeline as start_tianxing_timeline,
    stop_craft_loop as stop_tianxing_craft_loop,
)
from tg_game.features.tianxing.biz_tianxing_reward_summary import (
    build_tianxing_reward_marker_days as _build_tianxing_reward_marker_days,
    build_tianxing_today_exploration_rewards as _build_tianxing_today_exploration_rewards,
    escape_sql_like as _escape_sql_like,
    normalize_tianxing_day_key as _normalize_tianxing_day_key,
    shift_tianxing_day_key as _shift_tianxing_day_key,
    tianxing_day_key_from_timestamp as _tianxing_day_key_from_timestamp,
)
from tg_game.features.xinggong.biz_xinggong_star_board import (
    XINGGONG_STARBOARD_DEFAULT_STAR,
    XINGGONG_STARBOARD_FEATURE_KEY,
    XINGGONG_STARBOARD_PULL_PREFIX,
    is_starboard_insufficient_reply,
    is_starboard_pull_command_for_target,
    is_starboard_success_reply,
    normalize_starboard_target,
)
from tg_game.features.xinggong import biz_xinggong_miniapp as xinggong_miniapp
from tg_game.features.wanling.biz_wanling_roam import (
    WANLING_ROAM_AUTO_AFTER_RETURN_SECONDS,
    WANLING_ROAM_COMMAND,
    WANLING_ROAM_COMMAND_SEQUENCE,
    WANLING_ROAM_FEATURE_KEY,
    build_wanling_roam_cancel_commands,
    build_wanling_roam_command_sequence,
    list_spirit_beast_names,
    normalize_wanling_roam_beast_names,
    pack_wanling_roam_strategy,
)
from tg_game.features.wanling.biz_wanling_view_model import (
    build_wanling_roam_auto_view as _wanling_build_wanling_roam_auto_view,
    build_wanling_roam_config_view as _wanling_build_wanling_roam_config_view,
    build_wanling_roam_state as _wanling_build_wanling_roam_state,
)
from tg_game.runtime_status import (
    build_runtime_status,
    compute_runtime_code_fingerprint,
    load_runtime_status,
)
from tg_game.sect_command_guard import SectCommandScopeError
from tg_game.sect_features import SECT_FEATURES
from tg_game.features.estate.biz_estate_miniapp import (
    is_estate_miniapp_hunt_limit_reached,
    mark_estate_miniapp_hunt_limit_reached,
    queue_estate_miniapp_hunt_request,
)
from tg_game.features.estate import biz_estate_hunt_daily_auto
from tg_game.features.tianji_trial import queue_tianji_trial_request
from tg_game.features.tianji_trial import biz_tianji_trial_daily_auto
from tg_game.features.luoyun_spirit_tree import biz_luoyun_spirit_tree_daily_auto
from tg_game.features.luoyun_spirit_tree import (
    biz_luoyun_spirit_tree_miniapp as luoyun_spirit_tree_miniapp,
)
from tg_game.features.tianji_trial.biz_tianji_trial_encounter_state import (
    build_tianji_encounter_state as _tianji_build_tianji_encounter_state,
)
from tg_game.features.tianji_trial.biz_tianji_trial_remnant_state import (
    TIANJI_EXCHANGE_COMMAND_TEXT as _tianji_exchange_command_text,
    TIANJI_EXCHANGE_FALLBACK_ITEMS as _tianji_exchange_fallback_items,
    TIANJI_REMNANT_COMMANDS as _tianji_remnant_commands,
    TIANJI_REMNANT_COMMAND_TEXT as _tianji_remnant_command_text,
    build_tianji_remnant_state as _tianji_build_tianji_remnant_state,
    get_latest_tianji_remnant_reply as _tianji_get_latest_tianji_remnant_reply,
)
from tg_game.services import module_registry
from tg_game.services.cultivation_sync import sync_cultivation_session
from tg_game.services.external_sync import (
    ASC_PROVIDER,
    get_cultivator_lookup_candidates,
    get_effective_external_cookie,
    get_external_keepalive_poll_seconds,
    is_authorized_profile,
    is_external_account_expired,
    mark_external_account_failure,
    read_cached_external_payload,
    should_keep_external_session_fresh,
    sync_external_account,
)
from tg_game.services.profile_schedules import (
    stop_current_profile_schedules as _stop_current_profile_schedules,
)
from tg_game.storage import CompatDb, Storage
from tg_game.telegram.account import (
    get_authorized_account_info,
    has_authorized_session,
    logout_account,
    send_login_code,
    verify_login_code,
    verify_login_password,
)
from tg_game.web.biz_web_display_formatting import (
    FISHING_REQUIRED_ROD_NAME,
    SCENERY_CODE_NAME_MAP,
    SHANGHAI_TZ,
    build_equipped_artifact_details as _build_equipped_artifact_details,
    build_payload_stat_items as _build_payload_stat_items,
    coerce_json_dict as _coerce_json_dict,
    coerce_json_list as _coerce_json_list,
    cooldown_target_timestamp as _cooldown_target_timestamp,
    equipped_artifact_names_text as _equipped_artifact_names_text,
    extract_reply_field as _extract_reply_field,
    first_equipped_artifact_name as _first_equipped_artifact_name,
    format_cooldown_from_last as _format_cooldown_from_last,
    format_datetime_display as _format_datetime_display,
    format_datetime_display_seconds as _format_datetime_display_seconds,
    format_external_artifacts as _format_external_artifacts,
    format_market_effects as _format_market_effects,
    format_payload_display_text as _format_payload_display_text,
    format_remaining_delta as _format_remaining_delta,
    format_sect_position as _format_sect_position,
    parse_chinese_duration_seconds as _parse_chinese_duration_seconds,
    payload_name_list as _payload_name_list,
    payload_name_summary as _payload_name_summary,
    payload_named_entries as _payload_named_entries,
    payload_stat_label as _payload_stat_label,
    parse_optional_int as _parse_optional_int,
    profile_has_fishing_rod as _profile_has_fishing_rod,
    recipe_craft_name as _recipe_craft_name,
    resolve_scenery_display_name as _resolve_scenery_display_name,
    stringify_payload_stat_value as _stringify_payload_stat_value,
)
from tg_game.web import admin_global_execution
from tg_game.web.biz_artifact_view_model import (
    build_artifact_touch_auto_view as _artifact_build_artifact_touch_auto_view,
    build_artifact_trial_auto_view as _artifact_build_artifact_trial_auto_view,
    build_artifact_trial_command as _artifact_build_artifact_trial_command,
    normalize_artifact_touch_command as _artifact_normalize_artifact_touch_command,
    normalize_artifact_touch_interval as _artifact_normalize_artifact_touch_interval,
    normalize_artifact_trial_artifact_name as _artifact_normalize_artifact_trial_artifact_name,
    normalize_artifact_trial_route as _artifact_normalize_artifact_trial_route,
    pack_artifact_touch_strategy as _artifact_pack_artifact_touch_strategy,
    pack_artifact_trial_strategy as _artifact_pack_artifact_trial_strategy,
    unpack_artifact_touch_strategy as _artifact_unpack_artifact_touch_strategy,
    unpack_artifact_trial_strategy as _artifact_unpack_artifact_trial_strategy,
)
from tg_game.web.biz_companion_view_model import (
    COMPANION_AUTO_FEATURES,
    COMPANION_HEART_TRIBULATION_ACTIONS,
    COMPANION_HEART_TRIBULATION_COMMAND,
    COMPANION_PANEL_COMMAND,
    COMPANION_VOYAGE_RETURN_COMMAND,
    COMPANION_VOYAGE_STATUS_COMMAND,
    build_companion_auto_view as _companion_build_companion_auto_view,
    build_companion_heart_tribulation_view as _companion_build_companion_heart_tribulation_view,
    build_companion_view as _companion_build_companion_view,
    build_companion_voyage_state as _companion_build_companion_voyage_state,
    build_estate_hunt_daily_auto_view as _companion_build_estate_hunt_daily_auto_view,
    build_pagoda_auto_view as _companion_build_pagoda_auto_view,
    build_tianji_trial_daily_auto_view as _companion_build_tianji_trial_daily_auto_view,
    build_wild_experience_view as _companion_build_wild_experience_view,
    format_companion_cooldown_display as _companion_format_companion_cooldown_display,
    resolve_active_companion_payload_and_status as _companion_resolve_active_companion_payload_and_status,
    resolve_latest_companion_cooldown_target as _companion_resolve_latest_companion_cooldown_target,
    resolve_latest_companion_payload as _companion_resolve_latest_companion_payload,
)
from tg_game.web.biz_cultivation_view_model import (
    CULTIVATION_STAGE_CAPS as _cultivation_CULTIVATION_STAGE_CAPS,
    DEFAULT_BULK_CULTIVATION_PROTECTED_PROFILE_ID,
    build_all_profile_cultivation_state as _cultivation_build_all_profile_cultivation_state,
    build_cultivation_result_view as _cultivation_build_cultivation_result_view,
    extract_adventure_lines as _cultivation_extract_adventure_lines,
    extract_item_delta_lines as _cultivation_extract_item_delta_lines,
    format_cultivation_progress as _cultivation_format_cultivation_progress,
    get_profile_cultivation_binding as _cultivation_get_profile_cultivation_binding,
)
from tg_game.web.biz_dungeon_view_model import (
    DUNGEON_DEFINITIONS,
    build_dungeon_messages as _dungeon_build_dungeon_messages,
    extract_dungeon_cleanup_targets as _dungeon_extract_dungeon_cleanup_targets,
    extract_dungeon_command_buttons as _dungeon_extract_dungeon_command_buttons,
    get_dungeon_definition as _dungeon_get_dungeon_definition,
    list_dungeon_feed_source_messages as _dungeon_list_dungeon_feed_source_messages,
)
from tg_game.web.biz_estate_view_model import (
    build_dongfu_pavilion_slots_view as _estate_build_dongfu_pavilion_slots_view,
    build_dongfu_view as _estate_build_dongfu_view,
    build_estate_miniapp_hunt_button as _estate_build_estate_miniapp_hunt_button,
)
from tg_game.web.biz_inventory_view_model import (
    build_profile_inventory_search as _inventory_build_profile_inventory_search,
    inventory_item_matches_query as _inventory_item_matches_query,
    item_type_label as _item_type_label,
    profile_display_label as _inventory_profile_display_label,
    build_profile_telegram_name_map as _inventory_build_profile_telegram_name_map,
    read_telegram_session_display_name as _inventory_read_telegram_session_display_name,
    resolve_profile_telegram_name as _inventory_resolve_profile_telegram_name,
    telegram_session_file_path as _inventory_telegram_session_file_path,
)
from tg_game.web.module_availability import (
    MAJOR_STAGE_ORDER,
    SMALL_WORLD_MIN_MAJOR_STAGE,
    is_small_world_module_available as _module_is_small_world_module_available,
    is_yuanying_stage as _module_is_yuanying_stage,
    major_stage_rank as _module_major_stage_rank,
    payload_has_artifact_spirit as _module_payload_has_artifact_spirit,
)
from tg_game.web.module_detail_state import (
    build_artifact_module_state as _module_detail_build_artifact_module_state,
    build_cultivation_module_state as _module_detail_build_cultivation_module_state,
    build_dungeon_module_state as _module_detail_build_dungeon_module_state,
    build_estate_module_state as _module_detail_build_estate_module_state,
    build_fishing_module_state as _module_detail_build_fishing_module_state,
    build_module_detail_default_state as _module_detail_build_default_state,
    build_other_module_state as _module_detail_build_other_module_state,
    build_small_world_module_state as _module_detail_build_small_world_module_state,
    build_stock_module_state as _module_detail_build_stock_module_state,
    build_module_detail_payload_view_state as _module_detail_build_payload_view_state,
    build_sect_artifact_inventory_summary_state as _module_detail_build_sect_artifact_inventory_summary_state,
    build_inventory_module_state as _module_detail_build_inventory_module_state,
    build_market_module_state as _module_detail_build_market_module_state,
    build_sect_module_state as _module_detail_build_sect_module_state,
)
from tg_game.web.biz_mulan_view_model import (
    build_mulan_state as _mulan_build_mulan_state,
    find_latest_mulan_message as _mulan_find_latest_mulan_message,
    is_mulan_support_ack_text as _mulan_is_mulan_support_ack_text,
    mulan_message_has_current_profile_parent as _mulan_message_has_current_profile_parent_impl,
    mulan_message_matches_thread as _mulan_message_matches_thread_impl,
    mulan_preview_lines as _mulan_preview_lines_impl,
)
from tg_game.web.biz_other_play_view_model import (
    build_character_view as _other_build_character_view,
    build_divination_batch_view as _other_build_divination_batch_view,
    build_divination_view as _other_build_divination_view,
    build_dice_state as _other_build_dice_state,
    build_ghost_gambling_view as _other_build_ghost_gambling_view,
    build_other_play_view as _other_build_other_play_view,
    build_pagoda_view as _other_build_pagoda_view,
    build_taiyi_view as _other_build_taiyi_view,
)
from tg_game.web.pagination import build_pagination_numbers as _build_pagination_numbers
from tg_game.web.biz_tianxing_wild_deep_log import (
    WILD_DEEP_COMMAND_PREFIX as _wild_deep_WILD_DEEP_COMMAND_PREFIX,
    build_wild_deep_log_export_result as _wild_deep_build_wild_deep_log_export_result,
    build_wild_deep_log_rows as _wild_deep_build_wild_deep_log_rows,
    export_wild_deep_log_file as _wild_deep_export_wild_deep_log_file,
    render_wild_deep_log_markdown as _wild_deep_render_wild_deep_log_markdown,
    wild_deep_time_bucket as _wild_deep_time_bucket_impl,
)
from tg_game.web.biz_xinggong_view_model import (
    build_companion_gift_items as _xinggong_build_companion_gift_items,
    build_xinggong_starboard_auto_view as _xinggong_build_xinggong_starboard_auto_view,
    build_xinggong_state as _xinggong_build_xinggong_state,
)
from tg_game.web.request_results import (
    build_external_session_notice as _request_build_external_session_notice,
    build_profile_bulk_result as _request_build_profile_bulk_result,
    build_refresh_all_result as _request_build_refresh_all_result,
    build_stop_current_result as _request_build_stop_current_result,
)
from tg_game.web.bot_sync import (
    RESULT_FILE_NAME as _BOT_SYNC_RESULT_FILE_NAME,
    build_busy_result as _build_bot_sync_busy_result,
    load_bot_sync_result as _load_bot_sync_result,
    run_bot_sync_command as _run_bot_sync_command,
    write_bot_sync_result as _write_bot_sync_result,
)
from tg_game.web.bot_schedule import (
    build_schedule_action_result as _build_bot_schedule_action_result,
    load_bot_schedule_state as _load_bot_schedule_state,
    set_bot_schedule_enabled as _set_bot_schedule_enabled,
    update_bot_schedule as _update_bot_schedule,
)
from tg_game.web.session_helpers import (
    build_tianji_login_redirect as _session_build_tianji_login_redirect,
    get_authenticated_profile as _session_get_authenticated_profile,
    is_public_path as _session_is_public_path,
    is_telegram_runtime_active as _session_is_telegram_runtime_active,
    list_session_profiles as _session_list_session_profiles,
    login_session_name as _session_login_session_name,
    login_session_name_for_phone as _session_login_session_name_for_phone,
    profile_belongs_to_session as _session_profile_belongs_to_session,
    sign_in_profile as _session_sign_in_profile,
)
from tg_game.web.shared_context import (
    build_chat_binding_bot_ids_view as _shared_build_chat_binding_bot_ids_view,
    build_command_target_context as _shared_build_command_target_context,
    build_sect_command_target_context as _shared_build_sect_command_target_context,
    build_shared_template_context as _shared_build_shared_template_context,
    ensure_chat_binding_bot_ids as _shared_ensure_chat_binding_bot_ids,
    normalize_chat_binding_bot_ids as _shared_normalize_chat_binding_bot_ids,
)


from tg_game.web.app_helpers import *  # noqa: F403
from tg_game.web.profile_card_state import load_profile_card_state


def _build_tianji_encounter_state(
    storage: Storage,
    profile_id: int,
    chat_id: Optional[int],
) -> dict:
    return _tianji_build_tianji_encounter_state(
        storage,
        profile_id,
        chat_id,
        format_timestamp=biz_fanren_game.format_timestamp,
    )


def _build_tianji_remnant_state(
    storage: Optional[Storage] = None,
    profile=None,
    command_chat=None,
    payload: Optional[dict] = None,
) -> dict:
    return _tianji_build_tianji_remnant_state(
        storage,
        profile,
        command_chat,
        payload,
        get_latest_reply=_get_latest_tianji_remnant_reply,
        format_timestamp=biz_fanren_game.format_timestamp,
    )


def _build_sect_recent_reply_text(
    storage: Storage,
    profile_id: int,
    sect_chat,
    current_sect_feature: Optional[dict],
    active_profile,
    fallback_text: str = "",
) -> str:
    if not sect_chat or not profile_id:
        return str(fallback_text or "").strip()
    messages = storage.list_bound_messages(
        profile_id=profile_id,
        chat_id=int(sect_chat.chat_id) if sect_chat else None,
        limit=60,
    )
    return _sect_build_sect_recent_reply_text(
        messages,
        current_sect_feature,
        fallback_text=fallback_text,
        is_related_message=_is_sect_related_message,
    )


def _has_joined_sect(active_profile) -> bool:
    return _sect_has_joined_sect(
        active_profile,
        normalize_name=_normalize_sect_name_text,
    )


def _is_tianxing_sect_profile(active_profile) -> bool:
    return _sect_is_tianxing_sect_profile(
        active_profile,
        normalize_name=_normalize_sect_name_text,
    )


def _sect_matches_current(item_sect_name: str, current_sect_name: str) -> bool:
    return _sect_viewmodel_sect_matches_current(
        item_sect_name,
        current_sect_name,
        normalize_name=_normalize_sect_name_text,
    )


def _build_cultivation_result_view(result: dict) -> dict:
    return _cultivation_build_cultivation_result_view(
        result,
        extract_item_delta=_extract_item_delta_lines,
        extract_adventure=_extract_adventure_lines,
    )


def _build_stock_view(
    storage: Storage,
    profile_id: int,
    chat_id: Optional[int],
    thread_id: Optional[int] = None,
    command_sender_id: Optional[int] = None,
    command_sender_username: str = "",
) -> dict:
    settings = get_settings()
    return _stock_build_stock_view(
        storage,
        profile_id,
        chat_id,
        thread_id=thread_id,
        command_sender_id=command_sender_id,
        command_sender_username=command_sender_username,
        authorized_user_id=str(settings.authorized_user_id or "").strip(),
        format_timestamp=biz_fanren_game.format_timestamp,
    )


def _export_wild_deep_log_file(
    storage: Storage,
    *,
    profile_id: int,
    day_key: str,
    chat_id: Optional[int],
) -> dict:
    return _wild_deep_export_wild_deep_log_file(
        storage,
        profile_id=profile_id,
        day_key=day_key,
        chat_id=chat_id,
        log_dir=WILD_DEEP_LOG_DIR,
    )


def _read_telegram_session_display_name(storage: Storage, profile) -> str:
    return _inventory_read_telegram_session_display_name(storage, profile)


def _resolve_profile_telegram_name(
    storage: Storage, profile, external_account: Optional[dict]
) -> str:
    return _inventory_resolve_profile_telegram_name(
        storage,
        profile,
        external_account,
        session_display_name_reader=_read_telegram_session_display_name,
    )


def create_app() -> FastAPI:
    settings = get_settings()
    storage = Storage(settings.database_path)
    application = FastAPI(title=settings.app_name, version=settings.app_version)
    bot_sync_lock = asyncio.Lock()
    application.state.bot_sync_lock = bot_sync_lock
    admin_global_execution_lock = asyncio.Lock()
    application.state.admin_global_execution_lock = admin_global_execution_lock
    web_started_at = time.time()
    application.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @application.exception_handler(SectCommandScopeError)
    async def sect_command_scope_error_handler(
        request: Request, exc: SectCommandScopeError
    ) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    visible_module_keys = {
        "cultivation",
        "sect",
        "artifact",
        "inventory",
        "fishing",
        "small_world",
        "other",
        "estate",
        "market",
        "stock",
        "dungeon",
    }

    def _sync_env_binding(profile_id: int, telegram_user_id: str = "") -> None:
        storage.sync_env_chat_binding(
            profile_id=profile_id,
            chat_id=settings.bound_chat_id,
            thread_id=settings.bound_thread_id,
            chat_type=settings.bound_chat_type,
            bot_username="",
            bot_id=settings.bound_bot_id,
            telegram_user_id=telegram_user_id,
        )

    def _get_authorized_user_id_text() -> str:
        return str(settings.authorized_user_id or "").strip()

    def _get_admin_profile():
        authorized_user_id = _get_authorized_user_id_text()
        if not authorized_user_id:
            return None
        return storage.get_profile_by_telegram_user_id(authorized_user_id)

    def _is_admin_profile(profile) -> bool:
        return is_authorized_profile(storage, profile)

    def _get_global_market_cookie() -> str:
        admin_profile = _get_admin_profile()
        if not admin_profile:
            return ""
        return get_effective_external_cookie(storage)

    def _sync_global_reference_data_if_needed() -> None:
        cookie_text = _get_global_market_cookie()
        if not cookie_text:
            return
        _sync_bootstrap_if_needed(storage, cookie_text)
        _sync_all_items_if_needed(storage, cookie_text)
        _sync_shop_items_if_needed(storage, cookie_text)
        _sync_marketplace_listings_if_needed(storage, cookie_text)

    def _build_command_target_context(active_profile) -> dict:
        return _shared_build_command_target_context(
            settings,
            active_profile,
            get_primary_command_chat=_get_primary_command_chat,
            bot_username=biz_fanren_game.FANREN_BOT_USERNAME,
        )

    def _build_sect_command_target_context(active_profile, sect_chat=None) -> dict:
        return _shared_build_sect_command_target_context(
            settings,
            active_profile,
            get_primary_command_chat=_get_primary_command_chat,
            default_bot_username=biz_fanren_game.FANREN_BOT_USERNAME,
            sect_bot_username=biz_sect_game.SECT_BOT_USERNAME,
            sect_chat=sect_chat,
        )

    def _build_xinggong_state(
        payload: dict,
        active_profile,
        sect_session=None,
        starboard_auto_task: Optional[dict] = None,
        starboard_pull_result: Optional[dict] = None,
    ) -> dict:
        return _xinggong_build_xinggong_state(
            payload,
            sect_position=getattr(active_profile, "sect_position", "") or "",
            sect_session=sect_session,
            starboard_auto_task=starboard_auto_task,
            starboard_pull_result=starboard_pull_result,
            game_items_dict=storage.get_game_items(),
            now_ts=biz_fanren_game.time.time(),
        )

    def _build_companion_gift_items(payload: dict) -> list[dict]:
        return _xinggong_build_companion_gift_items(
            payload,
            storage.get_game_items(),
        )

    def _build_sect_treasury_items(active_profile) -> list[dict]:
        return _sect_build_sect_treasury_items(
            active_profile,
            storage.get_shop_items(),
            storage.get_game_items(),
            format_display_text=_format_payload_display_text,
            item_type_label=_item_type_label,
            matches_current=_sect_matches_current,
        )

    def _is_fishing_module_available(active_profile, payload: Optional[dict] = None) -> bool:
        if not active_profile:
            return False
        profile_payload = (
            payload
            if isinstance(payload, dict)
            else read_cached_external_payload(storage, active_profile.id, ASC_PROVIDER)
        )
        return _profile_has_fishing_rod(profile_payload, storage.get_game_items())

    def _is_artifact_module_available(active_profile, payload: Optional[dict] = None) -> bool:
        if not active_profile:
            return False
        profile_payload = (
            payload
            if isinstance(payload, dict)
            else read_cached_external_payload(storage, active_profile.id, ASC_PROVIDER)
        )
        return _payload_has_artifact_spirit(profile_payload)

    def _build_shared_template_context(active_profile) -> dict:
        context = _shared_build_shared_template_context(
            storage,
            settings,
            active_profile,
            build_command_target_context=_build_command_target_context,
            build_sect_treasury_items=_build_sect_treasury_items,
            build_chat_binding_bot_ids_view=_build_chat_binding_bot_ids_view,
            ensure_chat_binding_bot_ids=_ensure_chat_binding_bot_ids,
            is_admin_profile=_is_admin_profile,
            get_authorized_user_id_text=_get_authorized_user_id_text,
            is_fishing_module_available=_is_fishing_module_available,
            is_artifact_module_available=_is_artifact_module_available,
            is_yuanying_stage=_is_yuanying_stage,
            is_small_world_module_available=_is_small_world_module_available,
            has_joined_sect=_has_joined_sect,
            asc_provider=ASC_PROVIDER,
        )
        context["global_execution_managed"] = admin_global_execution.managed_state(
            storage
        )
        return context

    def _get_current_binding(active_profile, chat_id: int):
        if not active_profile:
            return None
        return storage.get_chat_binding(active_profile.id, chat_id)

    def _build_chat_binding_bot_ids_view(
        binding,
        *,
        active_bot_ids: set[int] | None = None,
        manual_live_bot_ids: set[int] | None = None,
    ) -> list[dict]:
        return _shared_build_chat_binding_bot_ids_view(
            storage,
            binding,
            active_bot_ids=active_bot_ids,
            manual_live_bot_ids=manual_live_bot_ids,
        )

    def _ensure_chat_binding_bot_ids(profile_id: int, chat_id: int, thread_id=None) -> None:
        return _shared_ensure_chat_binding_bot_ids(
            storage, profile_id, chat_id, thread_id=thread_id
        )

    def _is_public_path(path: str) -> bool:
        return _session_is_public_path(path)

    def _sign_in_profile(
        request: Request, profile_id: int, redirect_url: str = "/"
    ) -> RedirectResponse:
        return _session_sign_in_profile(
            storage,
            request,
            profile_id,
            app_session_cookie=APP_SESSION_COOKIE,
            redirect_url=redirect_url,
        )

    def _login_session_name() -> str:
        return _session_login_session_name(settings)

    def _login_session_name_for_phone(phone: str = "") -> str:
        return _session_login_session_name_for_phone(_login_session_name(), phone)

    def _is_telegram_runtime_active() -> bool:
        return _session_is_telegram_runtime_active()

    def _build_tianji_login_redirect(message: str = "") -> RedirectResponse:
        return _session_build_tianji_login_redirect(message)

    def _get_external_account_for_profile(profile_id: int) -> Optional[dict]:
        if not profile_id:
            return None
        return storage.get_external_account(profile_id, ASC_PROVIDER)

    def _is_external_session_expired_for_profile(profile_id: int) -> bool:
        return is_external_account_expired(
            _get_external_account_for_profile(profile_id)
        )

    def _ensure_external_session_active(profile) -> Optional[RedirectResponse]:
        if not profile:
            return None
        if not _is_external_session_expired_for_profile(profile.id):
            return None
        return _build_tianji_login_redirect()

    def _connect_external_cookie(profile_id: int, cookie_text: str) -> None:
        profile = storage.get_profile(profile_id)
        if not profile:
            raise RuntimeError("Profile not found")
        is_admin = _is_admin_profile(profile)
        normalized_cookie_text = (cookie_text or "").strip()
        global_cookie_text = _get_global_market_cookie()
        if (
            normalized_cookie_text
            and not is_admin
            and normalized_cookie_text != global_cookie_text
        ):
            raise RuntimeError("只有管理员可以替换天机阁 Cookie")
        cultivator_payload = sync_external_account(
            storage,
            profile_id,
            cookie_text=(
                normalized_cookie_text
                if is_admin
                else (global_cookie_text or normalized_cookie_text)
            ),
        )
        telegram_user_id = str(profile.telegram_user_id or "").strip()
        telegram_username = (profile.telegram_username or "").strip().lstrip("@")
        telegram_session_name = (
            profile.telegram_session_name
            or _login_session_name()
            or settings.telegram_session_name
        ).strip()
        storage.bind_profile_telegram_account(
            profile_id,
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            telegram_phone=profile.telegram_phone,
            telegram_session_name=telegram_session_name,
        )
        storage.activate_profile(profile_id)
        if is_admin:
            _sync_global_reference_data_if_needed()
        _sync_profile_from_cultivator(storage, profile_id, cultivator_payload)
        _sync_env_binding(profile_id, telegram_user_id)
        for binding in storage.list_chat_bindings(profile_id):
            if not binding.is_active:
                continue
            try:
                sync_cultivation_session(storage, profile_id, binding.chat_id)
            except Exception as exc:
                logger.warning(
                    "Cultivation session resync failed after external login profile=%s chat=%s: %s",
                    profile_id,
                    binding.chat_id,
                    exc,
                )
        storage.request_sect_refresh(profile_id, cooldown_seconds=0)

    def _get_profile_refresh_cookie(profile_id: int) -> str:
        external_account = storage.get_external_account(profile_id, ASC_PROVIDER) or {}
        return (
            str(external_account.get("cookie_text") or "").strip()
            or get_effective_external_cookie(storage)
        )

    def _can_refresh_profile_info(profile) -> bool:
        return bool(
            profile
            and getattr(profile, "telegram_verified_at", 0)
            and _get_profile_refresh_cookie(profile.id)
        )

    def _refresh_profile_external_info(profile) -> tuple[bool, str]:
        if not profile:
            return False, "missing_profile"
        if not getattr(profile, "telegram_verified_at", 0):
            return False, "telegram_unverified"
        cookie_text = _get_profile_refresh_cookie(profile.id)
        if not cookie_text:
            return False, "missing_cookie"
        try:
            _connect_external_cookie(profile.id, cookie_text)
            return True, ""
        except Exception as exc:
            mark_external_account_failure(
                storage, profile.id, exc, cookie_text=cookie_text
            )
            return False, str(exc)

    def _build_refresh_all_result(request: Request) -> Optional[dict]:
        return _request_build_refresh_all_result(
            request.query_params,
            parse_int=biz_sect_game._parse_int,
        )

    def _build_profile_bulk_result(request: Request) -> Optional[dict]:
        return _request_build_profile_bulk_result(
            request.query_params,
            parse_int=biz_sect_game._parse_int,
        )

    def _build_stop_current_result(request: Request) -> Optional[dict]:
        return _request_build_stop_current_result(
            request.query_params,
            parse_int=biz_sect_game._parse_int,
        )

    def _build_external_session_notice(
        external_account: Optional[dict],
    ) -> Optional[dict]:
        return _request_build_external_session_notice(external_account)

    def _should_refresh_cultivator_payload(
        profile, external_account: Optional[dict]
    ) -> bool:
        return should_keep_external_session_fresh(profile, external_account)

    def _get_request_profile(request: Request):
        return getattr(request.state, "auth_profile", None)

    def _get_primary_command_chat(profile_id: int, bot_username: str = ""):
        return storage.get_primary_chat_binding(
            profile_id, bot_username=bot_username
        ) or storage.get_primary_chat_binding(profile_id)

    def _get_latest_command_reply_for_profile(profile, command_chat, command_text: str):
        if not profile or not command_chat:
            return None
        command_sender_text = str(
            getattr(command_chat, "telegram_user_id", "")
            or getattr(profile, "telegram_user_id", "")
            or ""
        ).strip()
        return storage.get_latest_bot_reply_for_command(
            command_chat.chat_id,
            command_text,
            profile_id=profile.id,
            thread_id=command_chat.thread_id,
            sender_id=(
                int(command_sender_text) if command_sender_text.isdigit() else None
            ),
            sender_username=(getattr(profile, "telegram_username", "") or ""),
        )

    def _normalize_chat_binding_bot_ids(binding) -> list[int]:
        return _shared_normalize_chat_binding_bot_ids(binding)

    def _load_cached_page_state(
        request: Request,
        *,
        include_chats: bool = False,
        include_profile_state: bool = True,
    ) -> dict:
        active_profile = _get_request_profile(request)
        chats = []
        external_account = None
        profile_state = {
            "active_profile": None,
            "external_account": None,
            "payload": {},
            "current_sect_feature": None,
            "sect_chat": None,
            "sect_session": None,
            "lingxiao_state": None,
            "yinluo_state": None,
            "huangfeng_state": None,
            "wanling_state": None,
        }
        if active_profile:
            _sync_env_binding(active_profile.id, active_profile.telegram_user_id)
            if include_profile_state:
                profile_state = _load_profile_card_state(
                    active_profile, refresh_external=False
                )
                active_profile = profile_state["active_profile"]
                external_account = profile_state["external_account"]
            else:
                external_account = storage.get_external_account(
                    active_profile.id, ASC_PROVIDER
                )
                profile_state["active_profile"] = active_profile
                profile_state["external_account"] = external_account
            if include_chats:
                chats = storage.list_chat_bindings(active_profile.id)
                for chat in chats:
                    _ensure_chat_binding_bot_ids(active_profile.id, chat.chat_id, chat.thread_id)
                chats = storage.list_chat_bindings(active_profile.id)
        return {
            "active_profile": active_profile,
            "external_account": external_account,
            "chats": chats,
            "profile_state": profile_state,
        }

    async def _background_refresh_external_profiles() -> None:
        while True:
            try:
                await asyncio.to_thread(_sync_global_reference_data_if_needed)
                profiles = storage.list_profiles()
                for profile in profiles:
                    if not profile.telegram_verified_at:
                        continue
                    external_account = storage.get_external_account(
                        profile.id, ASC_PROVIDER
                    )
                    if is_external_account_expired(external_account):
                        continue
                    if not _should_refresh_cultivator_payload(
                        profile, external_account
                    ):
                        continue
                    await asyncio.to_thread(_refresh_cultivator_payload, profile.id)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Background external profile refresh failed")
            await asyncio.sleep(EXTERNAL_REFRESH_LOOP_SECONDS)

    async def _background_run_admin_global_schedules() -> None:
        while True:
            try:
                async with admin_global_execution_lock:
                    await asyncio.to_thread(
                        admin_global_execution.run_due_schedule,
                        storage,
                        storage.list_profiles(),
                        fallback_chat_id=settings.bound_chat_id,
                        fallback_thread_id=settings.bound_thread_id,
                        fallback_chat_type=settings.bound_chat_type,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Background admin global schedule failed")
            await asyncio.sleep(admin_global_execution.SCHEDULE_POLL_SECONDS)

    def _refresh_cultivator_payload(profile_id: int) -> dict:
        profile = storage.get_profile(profile_id)
        if not profile:
            return {}
        external_account = storage.get_external_account(profile_id, ASC_PROVIDER) or {}
        cookie_text = (
            external_account.get("cookie_text")
            or get_effective_external_cookie(storage)
        ).strip()
        identifiers = get_cultivator_lookup_candidates(profile)
        if not cookie_text or not identifiers:
            return read_cached_external_payload(storage, profile_id, ASC_PROVIDER)
        try:
            payload = sync_external_account(
                storage, profile_id, cookie_text=cookie_text
            )
            if _is_admin_profile(profile):
                _sync_global_reference_data_if_needed()
            _sync_profile_from_cultivator(storage, profile_id, payload)
            for binding in storage.list_chat_bindings(profile_id):
                if not binding.is_active:
                    continue
                try:
                    sync_cultivation_session(
                        storage,
                        profile_id,
                        binding.chat_id,
                        cultivator_payload=payload,
                    )
                except Exception as exc:
                    logger.warning(
                        "Cultivation session sync failed after payload refresh profile=%s chat=%s: %s",
                        profile_id,
                        binding.chat_id,
                        exc,
                    )
            return payload if isinstance(payload, dict) else {}
        except Exception as exc:
            mark_external_account_failure(
                storage, profile_id, exc, cookie_text=cookie_text
            )
            return read_cached_external_payload(storage, profile_id, ASC_PROVIDER)

    def _get_sect_feature_by_name(sect_name: str) -> Optional[dict]:
        normalized = _normalize_sect_name_text(sect_name)
        if not normalized:
            return None
        for feature in SECT_FEATURES:
            if feature["name"] in normalized:
                return feature
        return None

    def _resolve_current_sect_feature(profile) -> Optional[dict]:
        if not profile or not profile.sect_name:
            return None
        return _get_sect_feature_by_name(profile.sect_name)

    def _build_sect_action_command(action: dict, form_data) -> str:
        command_text = str(action.get("command") or "").strip()
        if command_text:
            return command_text
        template = str(action.get("template") or "").strip()
        if not template:
            raise HTTPException(status_code=400, detail="Sect action template missing")
        values = {}
        for field in action.get("fields") or []:
            field_name = str(field.get("name") or "").strip()
            if not field_name:
                continue
            raw_value = str(form_data.get(field_name) or "").strip()
            if field.get("required", True) and not raw_value:
                raise HTTPException(
                    status_code=400,
                    detail=f"{field.get('label') or field_name} is required",
                )
            if field.get("type") == "select":
                allowed_values = {
                    str(option.get("value") or "").strip()
                    for option in field.get("options") or []
                }
                if raw_value and allowed_values and raw_value not in allowed_values:
                    raise HTTPException(
                        status_code=400, detail="Invalid sect action option"
                    )
            values[field_name] = raw_value
        if str(action.get("key") or "").strip() == "gift" and not values.get("count", "").strip():
            values["count"] = "1"
        return template.format(**values).strip()

    def _load_profile_card_state(active_profile, refresh_external: bool = True) -> dict:
        return load_profile_card_state(
            storage,
            active_profile,
            refresh_external=refresh_external,
            should_refresh_cultivator_payload=_should_refresh_cultivator_payload,
            refresh_cultivator_payload=_refresh_cultivator_payload,
            get_primary_command_chat=_get_primary_command_chat,
            resolve_current_sect_feature=_resolve_current_sect_feature,
            build_xinggong_state=_build_xinggong_state,
        )

    def _get_or_create_profile_for_telegram(
        telegram_user_id: str, telegram_username: str, telegram_first_name: str
    ):
        profile = storage.get_profile_by_telegram_user_id(telegram_user_id)
        if profile:
            return profile
        base_name = telegram_username or telegram_first_name or "tg"
        profile_name = f"{base_name}-{telegram_user_id[-6:]}"
        profile = storage.create_profile(name=profile_name, activate=False)
        storage.ensure_module_settings(profile.id, module_registry.list_modules())
        return profile

    def _get_authenticated_profile(request: Request):
        return _session_get_authenticated_profile(
            storage,
            request,
            app_session_cookie=APP_SESSION_COOKIE,
        )

    def _list_session_profiles(request: Request) -> list:
        return _session_list_session_profiles(
            storage,
            request,
            app_session_cookie=APP_SESSION_COOKIE,
        )

    def _profile_belongs_to_session(request: Request, profile_id: int) -> bool:
        return _session_profile_belongs_to_session(
            _list_session_profiles(request), profile_id
        )

    async def _discover_authorized_account(request: Request) -> Optional[dict]:
        session_names = []
        seen = set()
        runtime_active = _is_telegram_runtime_active()

        def _push_session_name(value: str) -> None:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                return
            seen.add(normalized)
            session_names.append(normalized)

        _push_session_name(_login_session_name())
        if not runtime_active:
            for profile in _list_session_profiles(request):
                _push_session_name(profile.telegram_session_name)
            for profile in storage.list_profiles():
                _push_session_name(profile.telegram_session_name)
            _push_session_name(settings.telegram_session_name)

        for session_name in session_names:
            if await has_authorized_session(session_name, allow_fallback=False):
                return await get_authorized_account_info(
                    session_name, allow_fallback=False
                )
        return None

    def _finalize_telegram_login(request: Request, account: dict):
        telegram_user_id = str(account.get("id") or "").strip()
        telegram_username = (account.get("username") or "").strip()
        telegram_first_name = (account.get("first_name") or "").strip()
        telegram_phone = (account.get("phone") or "").strip()
        telegram_session_name = (
            account.get("session_name") or _login_session_name()
        ).strip()
        profile = _get_or_create_profile_for_telegram(
            telegram_user_id, telegram_username, telegram_first_name
        )
        storage.bind_profile_telegram_account(
            profile.id,
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            telegram_phone=telegram_phone,
            telegram_session_name=telegram_session_name,
        )
        storage.activate_profile(profile.id)
        _sync_env_binding(profile.id, telegram_user_id)
        default_cookie = get_effective_external_cookie(storage)
        if default_cookie:
            try:
                _connect_external_cookie(profile.id, default_cookie)
            except Exception as exc:
                mark_external_account_failure(
                    storage, profile.id, exc, cookie_text=default_cookie
                )
                return _sign_in_profile(
                    request,
                    profile.id,
                    redirect_url="/login?error="
                    + quote_plus("默认天机阁会话已失效，请重新获取 session 粘贴导入"),
                )
        return _sign_in_profile(
            request,
            profile.id,
            redirect_url="/login?success="
            + quote_plus("TG 登录成功，已自动绑定当前账号"),
        )

    def _switch_session_profile(
        request: Request, profile_id: int, redirect_url: str = "/profile"
    ) -> RedirectResponse:
        session_token = request.cookies.get(APP_SESSION_COOKIE, "")
        storage.attach_profile_to_session_token(session_token, profile_id)
        profile = storage.set_current_profile_by_session_token(
            session_token, profile_id
        )
        if not profile:
            raise HTTPException(
                status_code=404, detail="Profile not available in session"
            )
        storage.activate_profile(profile.id)
        _sync_env_binding(profile.id, profile.telegram_user_id)
        storage.request_sect_refresh(profile.id, cooldown_seconds=0)
        return RedirectResponse(url=redirect_url or "/profile", status_code=303)

    @application.middleware("http")
    async def require_app_session(request: Request, call_next):
        profile = _get_authenticated_profile(request)
        request.state.auth_profile = profile
        if not profile and not _is_public_path(request.url.path):
            return RedirectResponse(url="/login", status_code=303)
        if (
            profile
            and not _is_public_path(request.url.path)
            and _is_external_session_expired_for_profile(profile.id)
        ):
            return _build_tianji_login_redirect()
        return await call_next(request)

    @application.on_event("startup")
    async def on_startup() -> None:
        storage.init_schema()
        storage.maybe_cleanup_bound_messages(min_interval_seconds=0)
        active_profile = storage.get_active_profile()
        if active_profile:
            _sync_env_binding(active_profile.id, active_profile.telegram_user_id)
        db = CompatDb(storage)
        try:
            biz_fanren_game.ensure_tables(db)
            biz_sect_game.ensure_tables(db)
        finally:
            db.close()
        application.state.external_refresh_task = asyncio.create_task(
            _background_refresh_external_profiles()
        )
        application.state.admin_global_schedule_task = asyncio.create_task(
            _background_run_admin_global_schedules()
        )

    @application.on_event("shutdown")
    async def on_shutdown() -> None:
        task = getattr(application.state, "external_refresh_task", None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        schedule_task = getattr(
            application.state, "admin_global_schedule_task", None
        )
        if schedule_task:
            schedule_task.cancel()
            try:
                await schedule_task
            except asyncio.CancelledError:
                pass

    @application.get("/login", response_class=HTMLResponse)
    async def login_page(
        request: Request, error: str = "", success: str = ""
    ) -> HTMLResponse:
        auth_profile = getattr(request.state, "auth_profile", None)
        login_challenge = None
        raw_challenge_id = request.cookies.get(TG_LOGIN_CHALLENGE_COOKIE, "")
        if raw_challenge_id.isdigit():
            login_challenge = storage.get_telegram_login_challenge(
                int(raw_challenge_id)
            )
        if (
            not error
            and not success
            and not login_challenge
            and (not auth_profile or not auth_profile.telegram_verified_at)
        ):
            try:
                account = await _discover_authorized_account(request)
                if account:
                    return _finalize_telegram_login(request, account)
            except Exception:
                logger.exception("Auto Telegram login bind failed")
        active_profile = auth_profile
        session_profiles = _list_session_profiles(request)
        session_token = request.cookies.get(APP_SESSION_COOKIE, "")
        if session_token:
            session_profile_ids = {int(profile.id) for profile in session_profiles}
            for profile in storage.list_profiles():
                if not getattr(profile, "telegram_verified_at", 0):
                    continue
                if int(profile.id) in session_profile_ids:
                    continue
                storage.attach_profile_to_session_token(session_token, profile.id)
            session_profiles = _list_session_profiles(request)
        session_profile_map = {int(profile.id): profile for profile in session_profiles}
        for profile in storage.list_profiles():
            if not getattr(profile, "telegram_verified_at", 0):
                continue
            session_profile_map.setdefault(int(profile.id), profile)
        session_profiles = sorted(
            session_profile_map.values(),
            key=lambda profile: (
                0 if active_profile and profile.id == active_profile.id else 1,
                -float(getattr(profile, "telegram_verified_at", 0) or 0),
                -int(profile.id),
            ),
        )
        if not active_profile:
            active_profile = next(
                (
                    profile
                    for profile in session_profiles
                    if getattr(profile, "telegram_verified_at", 0)
                ),
                session_profiles[0] if session_profiles else None,
            )
        available_telegram_profiles = sorted(
            [
                profile
                for profile in storage.list_profiles()
                if getattr(profile, "telegram_verified_at", 0)
            ],
            key=lambda profile: (
                0 if active_profile and profile.id == active_profile.id else 1,
                -float(getattr(profile, "telegram_verified_at", 0) or 0),
                -int(profile.id),
            ),
        )
        if (
            not error
            and not success
            and not login_challenge
            and (not active_profile or not active_profile.telegram_verified_at)
        ):
            verified_session_profile = next(
                (
                    profile
                    for profile in session_profiles
                    if getattr(profile, "telegram_verified_at", 0)
                ),
                None,
            )
            if verified_session_profile and (
                not active_profile or active_profile.id != verified_session_profile.id
            ):
                return _switch_session_profile(
                    request,
                    verified_session_profile.id,
                    redirect_url="/login",
                )
            if verified_session_profile:
                active_profile = verified_session_profile
        if not auth_profile and active_profile and active_profile.telegram_verified_at:
            return _sign_in_profile(
                request,
                active_profile.id,
                redirect_url="/login?success="
                + quote_plus("会话已续期，请继续使用"),
            )
        external_account = None
        if active_profile:
            external_account = storage.get_external_account(
                active_profile.id, ASC_PROVIDER
            )
        telegram_account = None
        has_telegram_session = False
        if active_profile and active_profile.telegram_verified_at:
            telegram_account = {
                "id": active_profile.telegram_user_id,
                "username": active_profile.telegram_username,
                "first_name": active_profile.name,
                "phone": active_profile.telegram_phone,
                "session_name": active_profile.telegram_session_name,
            }
            has_telegram_session = True
        me_payload = {}
        if external_account and external_account.get("me_json"):
            try:
                me_payload = json.loads(external_account.get("me_json") or "{}")
            except json.JSONDecodeError:
                me_payload = {}
        external_session_notice = _build_external_session_notice(external_account)
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "app_name": settings.app_name,
                "active_profile": active_profile,
                "external_account": external_account,
                "external_character_count": len(me_payload.get("characters") or []),
                "login_error": error,
                "login_success": success,
                "has_telegram_session": has_telegram_session,
                "login_challenge": login_challenge,
                "telegram_account": telegram_account,
                "session_profiles": session_profiles,
                "available_telegram_profiles": available_telegram_profiles,
                "is_admin_profile": _is_admin_profile(active_profile),
                "has_global_external_cookie": bool(_get_global_market_cookie()),
                "external_session_notice": external_session_notice,
                "format_timestamp": biz_fanren_game.format_timestamp,
            },
        )

    @application.post("/auth/telegram/local-login")
    async def local_telegram_login(request: Request) -> RedirectResponse:
        active_profile = getattr(request.state, "auth_profile", None)
        if active_profile and active_profile.telegram_verified_at:
            return _finalize_telegram_login(
                request,
                {
                    "id": active_profile.telegram_user_id,
                    "username": active_profile.telegram_username,
                    "first_name": active_profile.name,
                    "phone": active_profile.telegram_phone,
                    "session_name": active_profile.telegram_session_name
                    or _login_session_name(),
                },
            )
        try:
            account = await _discover_authorized_account(request)
            if not account:
                raise RuntimeError(
                    "当前没有可直接复用的 Telegram 会话，请先走手机号验证码登录"
                )
        except Exception as exc:
            return RedirectResponse(
                url=f"/login?error={quote_plus(str(exc))}", status_code=303
            )
        return _finalize_telegram_login(request, account)

    @application.post("/auth/telegram/start")
    async def start_telegram_login(phone: str = Form(...)) -> RedirectResponse:
        try:
            session_name = _login_session_name_for_phone(phone)
            result = await send_login_code(phone, session_name)
            challenge_id = storage.create_telegram_login_challenge(
                phone=result.get("phone") or "",
                phone_code_hash=result.get("phone_code_hash") or "",
                session_name=result.get("session_name") or session_name,
            )
            response = RedirectResponse(
                url="/login?success="
                + quote_plus("验证码已发送，请输入验证码完成登录"),
                status_code=303,
            )
            response.set_cookie(
                TG_LOGIN_CHALLENGE_COOKIE,
                str(challenge_id),
                httponly=True,
                samesite="lax",
                secure=False,
                max_age=600,
            )
            return response
        except Exception as exc:
            return RedirectResponse(
                url=f"/login?error={quote_plus(str(exc))}", status_code=303
            )

    @application.post("/auth/telegram/verify")
    async def verify_telegram_login(
        request: Request, code: str = Form(...)
    ) -> RedirectResponse:
        raw_challenge_id = request.cookies.get(TG_LOGIN_CHALLENGE_COOKIE, "")
        if not raw_challenge_id.isdigit():
            return RedirectResponse(
                url="/login?error=" + quote_plus("请先发送 Telegram 验证码"),
                status_code=303,
            )
        challenge = storage.get_telegram_login_challenge(int(raw_challenge_id))
        if not challenge:
            return RedirectResponse(
                url="/login?error=" + quote_plus("登录挑战已失效，请重新发送验证码"),
                status_code=303,
            )
        try:
            result = await verify_login_code(
                challenge.get("phone") or "",
                code,
                challenge.get("phone_code_hash") or "",
                challenge.get("session_name") or _login_session_name(),
            )
            if result.get("requires_password"):
                storage.update_telegram_login_challenge_status(
                    challenge["id"], "password_required"
                )
                return RedirectResponse(
                    url="/login?success="
                    + quote_plus("检测到二步验证，请输入 Telegram 密码"),
                    status_code=303,
                )
            storage.delete_telegram_login_challenge(challenge["id"])
            response = _finalize_telegram_login(request, result.get("account") or {})
            response.delete_cookie(TG_LOGIN_CHALLENGE_COOKIE)
            return response
        except Exception as exc:
            return RedirectResponse(
                url=f"/login?error={quote_plus(str(exc))}", status_code=303
            )

    @application.post("/auth/telegram/password")
    async def verify_telegram_password(
        request: Request, password: str = Form(...)
    ) -> RedirectResponse:
        raw_challenge_id = request.cookies.get(TG_LOGIN_CHALLENGE_COOKIE, "")
        if not raw_challenge_id.isdigit():
            return RedirectResponse(
                url="/login?error=" + quote_plus("请先发送 Telegram 验证码"),
                status_code=303,
            )
        challenge = storage.get_telegram_login_challenge(int(raw_challenge_id))
        if not challenge:
            return RedirectResponse(
                url="/login?error=" + quote_plus("登录挑战已失效，请重新发送验证码"),
                status_code=303,
            )
        try:
            account = await verify_login_password(
                password,
                challenge.get("session_name") or _login_session_name(),
            )
            storage.delete_telegram_login_challenge(challenge["id"])
            response = _finalize_telegram_login(request, account)
            response.delete_cookie(TG_LOGIN_CHALLENGE_COOKIE)
            return response
        except Exception as exc:
            return RedirectResponse(
                url=f"/login?error={quote_plus(str(exc))}", status_code=303
            )

    @application.post("/auth/telegram/logout")
    async def telegram_logout(request: Request) -> RedirectResponse:
        profile = getattr(request.state, "auth_profile", None)
        session_token = request.cookies.get(APP_SESSION_COOKIE, "")
        session_name = (
            profile.telegram_session_name if profile else ""
        ) or _login_session_name()
        try:
            await logout_account(session_name)
        except Exception:
            pass
        if profile:
            storage.clear_profile_telegram_account(profile.id)
        has_remaining_profiles = (
            storage.remove_profile_from_session_token(session_token, profile.id)
            if profile and session_token
            else False
        )
        if has_remaining_profiles:
            next_profile = storage.get_profile_by_session_token(session_token)
            if next_profile:
                storage.activate_profile(next_profile.id)
                _sync_env_binding(next_profile.id, next_profile.telegram_user_id)
            response = RedirectResponse(
                url="/login?success="
                + quote_plus("当前 TG 账号已退出，已切换到浏览器会话中的其他档案"),
                status_code=303,
            )
        else:
            storage.revoke_app_session(session_token)
            response = RedirectResponse(
                url="/login?success="
                + quote_plus("TG 账号已退出，请重新走标准登录流程"),
                status_code=303,
            )
            response.delete_cookie(APP_SESSION_COOKIE)
        response.delete_cookie(TG_LOGIN_CHALLENGE_COOKIE)
        return response

    @application.post("/auth/external/connect")
    async def connect_external(
        request: Request, cookie_text: str = Form("")
    ) -> RedirectResponse:
        try:
            profile = _get_request_profile(request)
            if not profile:
                raise RuntimeError("请先完成 Telegram Web 登录")
            normalized_cookie_text = (cookie_text or "").strip()
            if _is_admin_profile(profile):
                if not normalized_cookie_text:
                    raise RuntimeError("管理员提交的 Cookie 不能为空")
                _connect_external_cookie(profile.id, normalized_cookie_text)
            else:
                if not _get_global_market_cookie():
                    raise RuntimeError("管理员尚未配置可用的天机阁 Cookie")
                _connect_external_cookie(profile.id, "")
        except AscAuthError as exc:
            profile = _get_request_profile(request)
            if profile:
                mark_external_account_failure(
                    storage, profile.id, exc, cookie_text=cookie_text
                )
            return RedirectResponse(
                url=f"/login?error={quote_plus(str(exc))}", status_code=303
            )
        except Exception as exc:
            return RedirectResponse(
                url=f"/login?error={quote_plus(str(exc))}", status_code=303
            )
        return _sign_in_profile(
            request,
            profile.id,
            redirect_url="/login?success="
            + quote_plus("天机阁登录成功，已同步人物卡并恢复自动调度"),
        )

    @application.post("/auth/external/logout")
    async def external_logout(request: Request) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            return RedirectResponse(url="/login", status_code=303)
        storage.clear_external_account(profile.id, ASC_PROVIDER)
        if _is_admin_profile(profile):
            storage.clear_external_cookie_override()
        return RedirectResponse(
            url="/login?success=" + quote_plus("天机阁登录已退出"),
            status_code=303,
        )

    @application.post("/logout")
    async def logout(request: Request) -> RedirectResponse:
        storage.revoke_app_session(request.cookies.get(APP_SESSION_COOKIE, ""))
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie(APP_SESSION_COOKIE)
        return response

    @application.post("/auth/external/refresh")
    async def refresh_external_session(request: Request) -> RedirectResponse:
        profile = getattr(request.state, "auth_profile", None)
        if not profile:
            return RedirectResponse(url="/login", status_code=303)
        external_account = storage.get_external_account(profile.id, ASC_PROVIDER)
        cookie_text = get_effective_external_cookie(storage)
        if not cookie_text:
            return RedirectResponse(url="/login", status_code=303)
        try:
            _connect_external_cookie(profile.id, cookie_text)
            return RedirectResponse(
                url=f"/login?success={quote_plus('天机阁会话验证成功，已恢复自动调度并同步人物卡')}",
                status_code=303,
            )
        except Exception as exc:
            mark_external_account_failure(
                storage, profile.id, exc, cookie_text=cookie_text
            )
            return RedirectResponse(
                url=f"/login?error={quote_plus(str(exc))}", status_code=303
            )

    @application.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        page_state = _load_cached_page_state(request, include_chats=True)
        active_profile = page_state["active_profile"]
        modules = [
            module
            for module in module_registry.list_modules()
            if module.key in visible_module_keys
            and module.key != "market"
            and (
                module.key != "small_world"
                or _is_small_world_module_available(active_profile)
            )
            and (
                module.key != "artifact"
                or _is_artifact_module_available(active_profile)
            )
        ]
        chats = page_state["chats"]
        profile_state = page_state["profile_state"]
        payload = profile_state.get("payload") or {}
        character_state = _build_character_view(payload)
        sect_session = profile_state["sect_session"]
        current_sect_feature = profile_state["current_sect_feature"]
        lingxiao_state = profile_state["lingxiao_state"]
        yinluo_state = profile_state["yinluo_state"]
        huangfeng_state = profile_state.get("huangfeng_state")
        sect_chat = profile_state["sect_chat"]
        external_account = page_state["external_account"]
        if active_profile:
            storage.ensure_module_settings(active_profile.id, modules)
        external_session_notice = _build_external_session_notice(external_account)
        shared_template_context = _build_shared_template_context(active_profile)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "app_name": settings.app_name,
                "modules": modules,
                "active_profile": active_profile,
                "chats": chats,
                "character_state": character_state,
                "sect_session": sect_session,
                "sect_features": SECT_FEATURES,
                "current_sect_feature": current_sect_feature,
                "lingxiao_state": lingxiao_state,
                "format_timestamp": biz_fanren_game.format_timestamp,
                "now_ts": biz_fanren_game.time.time(),
                "external_account": external_account,
                "external_session_notice": external_session_notice,
                **shared_template_context,
            },
        )

    @application.get("/profile", response_class=HTMLResponse)
    async def profile_page(request: Request) -> HTMLResponse:
        page_state = _load_cached_page_state(request, include_chats=True)
        active_profile = page_state["active_profile"]
        profiles = sorted(
            storage.list_profiles_by_session_token(
                request.cookies.get(APP_SESSION_COOKIE, "")
            ),
            key=lambda profile: (
                str(getattr(profile, "name", "") or "").lower(),
                int(getattr(profile, "id", 0) or 0),
            ),
        )
        chats = page_state["chats"]
        external_account = page_state["external_account"]
        profile_state = page_state["profile_state"]
        payload = profile_state.get("payload") or {}
        character_state = _build_character_view(payload)
        companion_state = _build_companion_view(payload)
        inventory_payload = _coerce_json_dict(payload.get("inventory"))
        inventory_materials = _coerce_json_dict(inventory_payload.get("materials"))
        profile_spirit_stones = inventory_materials.get("mat_001", 0)
        rift_failure_state = profile_state.get("rift_failure_state")
        cultivation_session = profile_state.get("cultivation_session")
        external_session_notice = _build_external_session_notice(external_account)
        refresh_all_result = _build_refresh_all_result(request)
        profile_bulk_result = _build_profile_bulk_result(request)
        stop_current_result = _build_stop_current_result(request)
        profile_inventory_query = str(
            request.query_params.get("profile_inventory_q") or ""
        ).strip()
        profile_inventory_search = _build_profile_inventory_search(
            storage,
            profiles,
            profile_inventory_query,
        )
        bulk_cultivation_protected_profile_id = DEFAULT_BULK_CULTIVATION_PROTECTED_PROFILE_ID
        all_profile_cultivation_state = _build_all_profile_cultivation_state(
            storage,
            profiles,
            protected_profile_id=bulk_cultivation_protected_profile_id,
        )
        profile_telegram_names = _build_profile_telegram_name_map(storage, profiles)
        bot_sync_result = None
        bot_schedule_state = None
        if _is_admin_profile(active_profile):
            bot_sync_result = _load_bot_sync_result(
                Path(settings.database_path).with_name(_BOT_SYNC_RESULT_FILE_NAME),
                request.query_params.get("bot_sync_result") or "",
            )
            bot_schedule_state = await asyncio.to_thread(_load_bot_schedule_state)
        shared_template_context = _build_shared_template_context(active_profile)
        return templates.TemplateResponse(
            request,
            "profile.html",
            {
                "app_name": settings.app_name,
                "profiles": profiles,
                "active_profile": active_profile,
                "chats": chats,
                "format_timestamp": biz_fanren_game.format_timestamp,
                "now_ts": biz_fanren_game.time.time(),
                "external_account": external_account,
                "character_state": character_state,
                "companion_state": companion_state,
                "profile_spirit_stones": profile_spirit_stones,
                "rift_failure_state": rift_failure_state,
                "cultivation_session": cultivation_session,
                "refresh_all_result": refresh_all_result,
                "profile_bulk_result": profile_bulk_result,
                "stop_current_result": stop_current_result,
                "profile_inventory_search": profile_inventory_search,
                "all_profile_cultivation_state": all_profile_cultivation_state,
                "bulk_cultivation_protected_profile_id": bulk_cultivation_protected_profile_id,
                "profile_telegram_names": profile_telegram_names,
                "bot_schedule_state": bot_schedule_state,
                "global_result": bot_sync_result,
                "can_refresh_all_profiles": any(
                    _can_refresh_profile_info(profile) for profile in profiles
                ),
                "external_session_notice": external_session_notice,
                **shared_template_context,
            },
        )

    @application.get("/admin/global-execution", response_class=HTMLResponse)
    async def admin_global_execution_page(request: Request) -> HTMLResponse:
        active_profile = _get_request_profile(request)
        if not _is_admin_profile(active_profile):
            raise HTTPException(status_code=403, detail="Only admin can run global tasks")
        dashboard = admin_global_execution.build_dashboard(storage)
        return templates.TemplateResponse(
            request,
            "admin_global_execution.html",
            {
                "app_name": settings.app_name,
                "active_profile": active_profile,
                "admin_execution": dashboard,
                **_build_shared_template_context(active_profile),
            },
        )

    @application.get("/admin/global-execution/status")
    async def admin_global_execution_status(request: Request) -> JSONResponse:
        active_profile = _get_request_profile(request)
        if not _is_admin_profile(active_profile):
            raise HTTPException(status_code=403, detail="Only admin can run global tasks")
        return JSONResponse(admin_global_execution.build_dashboard(storage))

    @application.post("/admin/global-execution/{kind}")
    async def admin_global_execution_start(
        request: Request,
        kind: str,
    ) -> JSONResponse:
        active_profile = _get_request_profile(request)
        if not _is_admin_profile(active_profile):
            raise HTTPException(status_code=403, detail="Only admin can run global tasks")
        async with admin_global_execution_lock:
            try:
                admin_global_execution.start_batch(
                    storage,
                    kind,
                    storage.list_profiles(),
                    fallback_chat_id=settings.bound_chat_id,
                    fallback_thread_id=settings.bound_thread_id,
                    fallback_chat_type=settings.bound_chat_type,
                )
            except admin_global_execution.BatchBusyError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        return JSONResponse(admin_global_execution.build_dashboard(storage))

    @application.post("/admin/global-execution/{kind}/schedule")
    async def admin_global_execution_schedule(
        request: Request,
        kind: str,
        enabled: str = Form("0"),
        run_time: str = Form("00:05"),
    ) -> RedirectResponse:
        active_profile = _get_request_profile(request)
        if not _is_admin_profile(active_profile):
            raise HTTPException(status_code=403, detail="Only admin can schedule global tasks")
        async with admin_global_execution_lock:
            try:
                admin_global_execution.set_schedule(
                    storage,
                    kind,
                    enabled=enabled == "1",
                    run_time=run_time,
                    profiles=storage.list_profiles(),
                )
            except ValueError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
        return RedirectResponse(url="/admin/global-execution", status_code=303)

    @application.post("/runtime/telegram-bots/sync")
    async def runtime_sync_telegram_bots(request: Request) -> RedirectResponse:
        active_profile = _get_authenticated_profile(request)
        if not _is_admin_profile(active_profile):
            raise HTTPException(
                status_code=403,
                detail="Only admin can synchronize Telegram bots",
            )
        if bot_sync_lock.locked():
            result = _build_bot_sync_busy_result()
        else:
            async with bot_sync_lock:
                try:
                    result = await _run_bot_sync_command()
                except Exception as exc:
                    result = {
                        "ok": False,
                        "status": "failed",
                        "title": "Bot 同步失败",
                        "message": f"启动同步脚本失败：{exc}",
                        "elapsed_seconds": 0,
                        "raw_output": str(exc),
                    }
        result_id = _write_bot_sync_result(
            Path(settings.database_path).with_name(_BOT_SYNC_RESULT_FILE_NAME),
            result,
        )
        return RedirectResponse(
            url=f"/profile?bot_sync_result={quote_plus(result_id)}#chats",
            status_code=303,
        )

    @application.post("/runtime/telegram-bots/schedule/toggle")
    async def runtime_toggle_telegram_bot_schedule(
        request: Request,
        enabled: str = Form("0"),
    ) -> RedirectResponse:
        active_profile = _get_authenticated_profile(request)
        if not _is_admin_profile(active_profile):
            raise HTTPException(
                status_code=403,
                detail="Only admin can manage Telegram Bot automation",
            )
        current_state = await asyncio.to_thread(_load_bot_schedule_state)
        should_enable = str(enabled or "").strip() == "1"
        try:
            raw_output = await asyncio.to_thread(
                _set_bot_schedule_enabled,
                should_enable,
                current_state,
            )
            updated_state = await asyncio.to_thread(_load_bot_schedule_state)
            result = _build_bot_schedule_action_result(
                "自动同步已开启" if should_enable else "自动同步已关闭",
                (
                    "计划任务已按服务器当前时间加执行周期重新计算首次执行。"
                    if should_enable
                    else "已停止后续定时执行；正在运行的扫描不会被中断。"
                ),
                updated_state,
                raw_output=raw_output,
            )
        except Exception as exc:
            result = _build_bot_schedule_action_result(
                "自动同步操作失败",
                str(exc),
                current_state,
                ok=False,
                raw_output=str(exc),
            )
        result_id = _write_bot_sync_result(
            Path(settings.database_path).with_name(_BOT_SYNC_RESULT_FILE_NAME),
            result,
        )
        return RedirectResponse(
            url=f"/profile?bot_sync_result={quote_plus(result_id)}#chats",
            status_code=303,
        )

    @application.post("/runtime/telegram-bots/schedule/update")
    async def runtime_update_telegram_bot_schedule(
        request: Request,
        interval_hours: str = Form("1"),
    ) -> RedirectResponse:
        active_profile = _get_authenticated_profile(request)
        if not _is_admin_profile(active_profile):
            raise HTTPException(
                status_code=403,
                detail="Only admin can manage Telegram Bot automation",
            )
        current_state = await asyncio.to_thread(_load_bot_schedule_state)
        try:
            raw_output = await asyncio.to_thread(
                _update_bot_schedule,
                interval_hours,
                keep_disabled=bool(current_state.get("exists"))
                and not bool(current_state.get("enabled")),
            )
            updated_state = await asyncio.to_thread(_load_bot_schedule_state)
            result = _build_bot_schedule_action_result(
                "自动同步时间已更新",
                "新的执行周期已写入 Windows 计划任务；首次执行按服务器当前时间加周期计算。",
                updated_state,
                raw_output=raw_output,
            )
        except Exception as exc:
            result = _build_bot_schedule_action_result(
                "自动同步时间更新失败",
                str(exc),
                current_state,
                ok=False,
                raw_output=str(exc),
            )
        result_id = _write_bot_sync_result(
            Path(settings.database_path).with_name(_BOT_SYNC_RESULT_FILE_NAME),
            result,
        )
        return RedirectResponse(
            url=f"/profile?bot_sync_result={quote_plus(result_id)}#chats",
            status_code=303,
        )

    @application.post("/profiles/{profile_id}/switch")
    async def switch_profile(
        request: Request,
        profile_id: int,
        redirect_to: str = Form("/profile"),
    ) -> RedirectResponse:
        return _switch_session_profile(request, profile_id, redirect_to)

    @application.get("/messages", response_class=HTMLResponse)
    async def messages_page(
        request: Request,
        chat_id: str = "",
        limit: int = 200,
        q: str = "",
        focus_msg_id: str = "",
    ) -> HTMLResponse:
        page_state = _load_cached_page_state(request, include_chats=True)
        active_profile = page_state["active_profile"]
        if not _is_admin_profile(active_profile):
            raise HTTPException(
                status_code=403, detail="Only admin can access messages"
            )
        chats = page_state["chats"]
        external_account = page_state["external_account"]
        safe_limit = max(20, min(int(limit or 200), 500))
        normalized_chat_id_text = str(chat_id or "").strip()
        selected_chat_id = (
            int(normalized_chat_id_text)
            if normalized_chat_id_text.lstrip("-").isdigit()
            else None
        )
        search_query = str(q or "").strip()
        normalized_focus_msg_id = str(focus_msg_id or "").strip()
        focused_message_id = (
            int(normalized_focus_msg_id) if normalized_focus_msg_id.isdigit() else None
        )
        profile_id = active_profile.id if active_profile else None
        if selected_chat_id is not None and focused_message_id is not None:
            messages = storage.get_bound_message_context(
                chat_id=selected_chat_id,
                message_id=focused_message_id,
                profile_id=profile_id,
            )
        else:
            messages = storage.list_bound_messages(
                profile_id=profile_id,
                chat_id=selected_chat_id,
                search_query=search_query,
                limit=safe_limit,
            )
        for message in messages:
            reply_preview = ""
            if message.get("reply_to_msg_id"):
                reply_message = storage.get_bound_message(
                    message.get("chat_id") or 0,
                    int(message["reply_to_msg_id"]),
                    profile_id=profile_id,
                )
                reply_preview = ((reply_message or {}).get("text") or "").strip()[:160]
            message["reply_preview"] = reply_preview
            message["is_focused"] = bool(
                focused_message_id is not None
                and int(message.get("message_id") or 0) == focused_message_id
                and int(message.get("chat_id") or 0) == int(selected_chat_id or 0)
            )
        shared_template_context = _build_shared_template_context(active_profile)
        return templates.TemplateResponse(
            request,
            "messages.html",
            {
                "app_name": settings.app_name,
                "active_profile": active_profile,
                "chats": chats,
                "messages": messages,
                "selected_chat_id": selected_chat_id,
                "limit": safe_limit,
                "search_query": search_query,
                "search_query_qs": quote_plus(search_query) if search_query else "",
                "focused_message_id": focused_message_id,
                "format_timestamp": biz_fanren_game.format_timestamp,
                "external_session_notice": _build_external_session_notice(
                    external_account
                ),
                **shared_template_context,
            },
        )

    @application.get("/countdowns", response_class=HTMLResponse)
    async def countdowns(request: Request) -> HTMLResponse:
        page_state = _load_cached_page_state(request)
        active_profile = page_state["active_profile"]
        profile_state = page_state["profile_state"]
        payload = profile_state.get("payload") or {}
        cultivation_session = profile_state.get("cultivation_session")
        external_account = page_state["external_account"]
        active_tasks = (
            storage.list_active_companion_auto_tasks(active_profile.id)
            if active_profile
            else []
        )
        starboard_task = None
        small_world_countdowns = []
        sect_countdowns = []
        tianxing_countdowns = []
        companion_voyage_state = _build_companion_voyage_state(None)
        if active_profile:
            sect_chat = profile_state.get("sect_chat")
            starboard_task = storage.get_companion_auto_task(
                active_profile.id,
                sect_chat.chat_id if sect_chat else 0,
                XINGGONG_STARBOARD_FEATURE_KEY,
            )
            command_chat = _get_primary_command_chat(
                active_profile.id, biz_fanren_game.FANREN_BOT_USERNAME
            )
            voyage_reply = _get_latest_command_reply_for_profile(
                active_profile, command_chat, COMPANION_VOYAGE_STATUS_COMMAND
            )
            companion_voyage_state = _build_companion_voyage_state(voyage_reply)
            if _is_small_world_module_available(active_profile):
                small_world_reply = _get_latest_command_reply_for_profile(
                    active_profile,
                    command_chat,
                    biz_small_world_game.SMALL_WORLD_PANEL_COMMAND,
                )
                small_world_state = biz_small_world_game.parse_small_world_reply(
                    str((small_world_reply or {}).get("text") or "").strip(),
                    float((small_world_reply or {}).get("created_at") or 0),
                )
                small_world_preach_reply = _get_latest_command_reply_for_profile(
                    active_profile,
                    command_chat,
                    biz_small_world_game.SMALL_WORLD_PREACH_COMMAND,
                )
                small_world_countdowns = _build_small_world_countdown_items(
                    storage.get_companion_auto_task(
                        active_profile.id,
                        command_chat.chat_id if command_chat else 0,
                        biz_small_world_game.SMALL_WORLD_AUTO_FEATURE_KEY,
                    ),
                    small_world_state,
                    small_world_preach_reply,
                )
            sect_countdowns = _build_sect_countdown_items(
                profile_state.get("sect_session"),
                current_sect_name=str(getattr(active_profile, "sect_name", "") or ""),
            )
            if _is_tianxing_sect_profile(active_profile):
                tianxing_countdowns = _build_tianxing_countdown_items(
                    get_tianxing_status_snapshot(storage, active_profile.id)
                )
        auto_task_countdowns = _build_auto_task_countdown_items(
            active_tasks,
            current_sect_name=str(getattr(active_profile, "sect_name", "") or ""),
        )
        cultivation_countdowns = _build_cultivation_countdown_items(
            cultivation_session
        )
        companion_voyage_countdowns = _build_companion_voyage_countdown_items(
            companion_voyage_state
        )
        xinggong_slot_countdowns = _build_xinggong_slot_countdown_items(
            payload, starboard_task
        )
        wanling_roam_countdowns = _build_wanling_roam_countdown_items(
            profile_state.get("wanling_state")
        )
        all_countdowns = [
            *cultivation_countdowns,
            *companion_voyage_countdowns,
            *auto_task_countdowns,
            *sect_countdowns,
            *tianxing_countdowns,
            *xinggong_slot_countdowns,
            *wanling_roam_countdowns,
            *small_world_countdowns,
        ]
        all_countdowns = sort_countdown_items(
            all_countdowns,
            now_ts=biz_fanren_game.time.time(),
        )
        shared_template_context = _build_shared_template_context(active_profile)
        return templates.TemplateResponse(
            request,
            "countdowns.html",
            {
                "app_name": settings.app_name,
                "active_profile": active_profile,
                "countdown_items": all_countdowns,
                "cultivation_countdowns": cultivation_countdowns,
                "companion_voyage_countdowns": companion_voyage_countdowns,
                "auto_task_countdowns": auto_task_countdowns,
                "sect_countdowns": sect_countdowns,
                "xinggong_slot_countdowns": xinggong_slot_countdowns,
                "wanling_roam_countdowns": wanling_roam_countdowns,
                "small_world_countdowns": small_world_countdowns,
                "external_session_notice": _build_external_session_notice(
                    external_account
                ),
                **shared_template_context,
            },
        )

    @application.get("/modules/{module_key}", response_class=HTMLResponse)
    async def module_detail(
        request: Request,
        module_key: str,
        page: int = 1,
        dungeon_key: str = "",
        q: str = "",
        q_exchange: str = "",
        sort: str = "",
        inv_page: int = 1,
        inv_q: str = "",
        explore_day: str = "",
    ) -> HTMLResponse:
        if module_key not in visible_module_keys:
            raise HTTPException(status_code=404, detail="Module not available")
        module = module_registry.get_module(module_key)
        if not module:
            raise HTTPException(status_code=404, detail="Module not found")
        page_state = _load_cached_page_state(request)
        active_profile = page_state["active_profile"]
        active_profile_id = active_profile.id if active_profile else None
        if module_key == "small_world" and not _is_small_world_module_available(
            active_profile
        ):
            return RedirectResponse(url="/profile", status_code=303)
        if module_key == "artifact" and not _is_artifact_module_available(active_profile):
            return RedirectResponse(url="/profile", status_code=303)
        module_setting = None
        cultivation_session = None
        command_chat = None
        profile_state = page_state["profile_state"]
        sect_session = profile_state["sect_session"]
        current_sect_feature = profile_state["current_sect_feature"]
        lingxiao_state = profile_state["lingxiao_state"]
        yinluo_state = profile_state["yinluo_state"]
        huangfeng_state = profile_state.get("huangfeng_state")
        wanling_state = profile_state.get("wanling_state")
        luoyun_state = profile_state.get("luoyun_state")
        xinggong_state = profile_state.get("xinggong_state")
        yuanying_sect_state = profile_state.get("yuanying_sect_state")
        sect_chat = profile_state["sect_chat"]
        external_account = page_state["external_account"]
        cultivation_state = _module_detail_build_cultivation_module_state(
            storage,
            profile_id=active_profile_id,
            enabled=False,
            page=page,
            page_size=4,
            build_cultivation_result_view=_build_cultivation_result_view,
            build_pagination_numbers=_build_pagination_numbers,
        )
        payload = {}
        game_items_dict = storage.get_game_items()
        payload_view_state = _module_detail_build_payload_view_state(
            payload,
            game_items_dict,
            build_character_view=_build_character_view,
            build_taiyi_view=_build_taiyi_view,
            build_other_play_view=_build_other_play_view,
            build_dongfu_view=_build_dongfu_view,
        )
        dongfu_state = payload_view_state["dongfu_state"]
        divination_batch_state = _build_divination_batch_view(None)
        fishing_state = _build_fishing_view(None)
        small_world_state = biz_small_world_game.parse_small_world_reply("")
        small_world_auto_state = _build_small_world_auto_view(None)
        small_world_preach_auto_state = _build_small_world_preach_auto_view(None)
        selected_dungeon = _get_dungeon_definition(dungeon_key)
        dungeon_command_buttons = _extract_dungeon_command_buttons(selected_dungeon)
        dungeon_cleanup_targets = []
        dungeon_messages = []
        sect_recent_reply_text = ""
        other_opponent_options = []
        other_module_state = {}
        default_state = _module_detail_build_default_state(
            build_tianji_remnant_state=_build_tianji_remnant_state,
            build_mulan_state=_build_mulan_state,
            build_companion_voyage_state=_build_companion_voyage_state,
            build_companion_auto_view=_build_companion_auto_view,
            build_pagoda_auto_view=_build_pagoda_auto_view,
            build_tianji_trial_daily_auto_view=_build_tianji_trial_daily_auto_view,
            build_estate_hunt_daily_auto_view=_build_estate_hunt_daily_auto_view,
            build_artifact_touch_auto_view=_build_artifact_touch_auto_view,
            build_artifact_trial_auto_view=_build_artifact_trial_auto_view,
            build_wild_experience_view=_build_wild_experience_view,
            build_companion_heart_tribulation_view=(
                _build_companion_heart_tribulation_view
            ),
        )
        stock_state = default_state["stock_state"]
        tianji_encounter_state = default_state["tianji_encounter_state"]
        tianji_remnant_state = default_state["tianji_remnant_state"]
        mulan_state = default_state["mulan_state"]
        companion_state = default_state["companion_state"]
        companion_auto_state = default_state["companion_auto_state"]
        pagoda_auto_state = default_state["pagoda_auto_state"]
        tianji_trial_daily_auto_state = default_state["tianji_trial_daily_auto_state"]
        estate_hunt_daily_auto_state = default_state["estate_hunt_daily_auto_state"]
        artifact_touch_auto_state = default_state["artifact_touch_auto_state"]
        artifact_trial_auto_state = default_state["artifact_trial_auto_state"]
        wild_experience_state = default_state["wild_experience_state"]
        companion_heart_tribulation_state = default_state[
            "companion_heart_tribulation_state"
        ]
        tianxing_state = default_state["tianxing_state"]
        tianxing_daily_rewards = default_state["tianxing_daily_rewards"]
        wild_deep_log_export_result = _build_wild_deep_log_export_result(request)
        if active_profile:
            storage.ensure_module_settings(
                active_profile.id, module_registry.list_modules()
            )
            module_setting = storage.get_module_setting(active_profile.id, module_key)
            payload = profile_state.get("payload") or {}
            if module_key == "fishing" and not _profile_has_fishing_rod(
                payload, game_items_dict
            ):
                return RedirectResponse(url="/profile", status_code=303)
            payload_view_state = _module_detail_build_payload_view_state(
                payload,
                game_items_dict,
                build_character_view=_build_character_view,
                build_taiyi_view=_build_taiyi_view,
                build_other_play_view=_build_other_play_view,
                build_dongfu_view=_build_dongfu_view,
            )
            dongfu_state = payload_view_state["dongfu_state"]
            if module_key == "sect":
                sect_module_state = _module_detail_build_sect_module_state(
                    storage,
                    enabled=True,
                    active_profile=active_profile,
                    sect_chat=sect_chat,
                    current_sect_feature=current_sect_feature,
                    sect_session=sect_session,
                    explore_day=explore_day,
                    build_sect_recent_reply_text=_build_sect_recent_reply_text,
                    is_tianxing_sect_profile=_is_tianxing_sect_profile,
                    get_tianxing_status_snapshot=get_tianxing_status_snapshot,
                    build_tianxing_today_exploration_rewards=(
                        _build_tianxing_today_exploration_rewards
                    ),
                )
                sect_recent_reply_text = sect_module_state["sect_recent_reply_text"]
                tianxing_state = sect_module_state.get(
                    "tianxing_state", tianxing_state
                )
                tianxing_daily_rewards = sect_module_state.get(
                    "tianxing_daily_rewards", tianxing_daily_rewards
                )
            if module_key == "cultivation":
                cultivation_state = _module_detail_build_cultivation_module_state(
                    storage,
                    profile_id=active_profile.id,
                    enabled=True,
                    page=page,
                    page_size=4,
                    build_cultivation_result_view=_build_cultivation_result_view,
                    build_pagination_numbers=_build_pagination_numbers,
                )
                command_chat = _get_primary_command_chat(
                    active_profile.id, biz_fanren_game.FANREN_BOT_USERNAME
                )
                if command_chat:
                    cultivation_session = storage.get_cultivation_session(
                        command_chat.chat_id, profile_id=active_profile.id
                    )
            elif module_key == "artifact":
                command_chat = _get_primary_command_chat(
                    active_profile.id, biz_fanren_game.FANREN_BOT_USERNAME
                )
                artifact_module_state = _module_detail_build_artifact_module_state(
                    storage,
                    payload,
                    game_items_dict,
                    enabled=True,
                    active_profile=active_profile,
                    command_chat=command_chat,
                    artifact_touch_feature_key=ARTIFACT_TOUCH_FEATURE_KEY,
                    artifact_trial_feature_key=ARTIFACT_TRIAL_FEATURE_KEY,
                    build_artifact_touch_auto_view=_build_artifact_touch_auto_view,
                    build_artifact_trial_auto_view=_build_artifact_trial_auto_view,
                )
                artifact_touch_auto_state = artifact_module_state[
                    "artifact_touch_auto_state"
                ]
                artifact_trial_auto_state = artifact_module_state[
                    "artifact_trial_auto_state"
                ]
            elif module_key in {"other", "estate", "dungeon", "stock", "fishing", "small_world"}:
                command_chat = _get_primary_command_chat(
                    active_profile.id, biz_fanren_game.FANREN_BOT_USERNAME
                )
                if module_key == "fishing":
                    fishing_module_state = _module_detail_build_fishing_module_state(
                        storage,
                        enabled=True,
                        active_profile=active_profile,
                        command_chat=command_chat,
                        build_fishing_view=_build_fishing_view,
                    )
                    fishing_state = fishing_module_state["fishing_state"]
                if module_key == "small_world":
                    small_world_module_state = _module_detail_build_small_world_module_state(
                        storage,
                        enabled=True,
                        active_profile=active_profile,
                        command_chat=command_chat,
                        panel_command=biz_small_world_game.SMALL_WORLD_PANEL_COMMAND,
                        preach_command=biz_small_world_game.SMALL_WORLD_PREACH_COMMAND,
                        auto_feature_key=biz_small_world_game.SMALL_WORLD_AUTO_FEATURE_KEY,
                        parse_small_world_reply=biz_small_world_game.parse_small_world_reply,
                        get_latest_command_reply_for_profile=(
                            _get_latest_command_reply_for_profile
                        ),
                        build_small_world_auto_view=_build_small_world_auto_view,
                        preach_auto_feature_key=(
                            biz_small_world_game.SMALL_WORLD_PREACH_AUTO_FEATURE_KEY
                        ),
                        build_small_world_preach_auto_view=(
                            _build_small_world_preach_auto_view
                        ),
                    )
                    small_world_state = small_world_module_state["small_world_state"]
                    small_world_auto_state = small_world_module_state[
                        "small_world_auto_state"
                    ]
                    small_world_preach_auto_state = small_world_module_state[
                        "small_world_preach_auto_state"
                    ]
                if module_key == "other":
                    other_module_state = _module_detail_build_other_module_state(
                        storage,
                        payload,
                        game_items_dict,
                        enabled=True,
                        active_profile=active_profile,
                        command_chat=command_chat,
                        companion_auto_features=COMPANION_AUTO_FEATURES,
                        excluded_companion_auto_feature_keys={
                            "heart_tribulation",
                            "wild_experience",
                            pagoda_auto.FEATURE_KEY,
                        },
                        artifact_touch_feature_key=ARTIFACT_TOUCH_FEATURE_KEY,
                        artifact_trial_feature_key=ARTIFACT_TRIAL_FEATURE_KEY,
                        mulan_auto_support_feature_key=MULAN_AUTO_SUPPORT_FEATURE_KEY,
                        companion_panel_command=COMPANION_PANEL_COMMAND,
                        companion_voyage_status_command=COMPANION_VOYAGE_STATUS_COMMAND,
                        pagoda_feature_key=pagoda_auto.FEATURE_KEY,
                        tianji_trial_daily_feature_key=biz_tianji_trial_daily_auto.FEATURE_KEY,
                        build_divination_batch_view=_build_divination_batch_view,
                        build_recent_player_options=_build_recent_player_options,
                        build_tianji_encounter_state=_build_tianji_encounter_state,
                        build_tianji_remnant_state=_build_tianji_remnant_state,
                        build_mulan_state=_build_mulan_state,
                        get_latest_command_reply_for_profile=(
                            _get_latest_command_reply_for_profile
                        ),
                        build_companion_view=_build_companion_view,
                        build_companion_auto_view=_build_companion_auto_view,
                        build_pagoda_auto_view=_build_pagoda_auto_view,
                        build_tianji_trial_daily_auto_view=(
                            _build_tianji_trial_daily_auto_view
                        ),
                        build_wild_experience_view=_build_wild_experience_view,
                        build_companion_heart_tribulation_view=(
                            _build_companion_heart_tribulation_view
                        ),
                        build_artifact_touch_auto_view=_build_artifact_touch_auto_view,
                        build_artifact_trial_auto_view=_build_artifact_trial_auto_view,
                    )
                if module_key == "estate":
                    estate_module_state = _module_detail_build_estate_module_state(
                        storage,
                        enabled=True,
                        active_profile=active_profile,
                        command_chat=command_chat,
                        dongfu_state=dongfu_state,
                        estate_hunt_daily_auto_feature_key=(
                            biz_estate_hunt_daily_auto.FEATURE_KEY
                        ),
                        build_estate_hunt_daily_auto_view=(
                            _build_estate_hunt_daily_auto_view
                        ),
                        build_estate_reply_messages=_build_estate_reply_messages,
                    )
                    estate_hunt_daily_auto_state = estate_module_state[
                        "estate_hunt_daily_auto_state"
                    ]
                    dongfu_state = estate_module_state["dongfu_state"]
                if module_key == "dungeon":
                    dungeon_module_state = _module_detail_build_dungeon_module_state(
                        storage,
                        enabled=True,
                        active_profile=active_profile,
                        command_chat=command_chat,
                        selected_dungeon=selected_dungeon,
                        build_dungeon_messages=_build_dungeon_messages,
                        extract_dungeon_cleanup_targets=(
                            _extract_dungeon_cleanup_targets
                        ),
                    )
                    dungeon_messages = dungeon_module_state.get(
                        "dungeon_messages", dungeon_messages
                    )
                    dungeon_cleanup_targets = dungeon_module_state.get(
                        "dungeon_cleanup_targets", dungeon_cleanup_targets
                    )
                if module_key == "stock":
                    stock_module_state = _module_detail_build_stock_module_state(
                        storage,
                        enabled=True,
                        active_profile=active_profile,
                        command_chat=command_chat,
                        build_stock_view=_build_stock_view,
                    )
                    stock_state = stock_module_state["stock_state"]
        summary_state = _module_detail_build_sect_artifact_inventory_summary_state(
            payload,
            game_items_dict,
            enabled=module_key in {"sect", "artifact", "inventory"}
            and bool(active_profile),
            sect_session=sect_session,
            build_sect_daily_view=_build_sect_daily_view,
            merge_sect_daily_view_with_session=_merge_sect_daily_view_with_session,
            payload_name_summary=_payload_name_summary,
            equipped_artifact_names_text=_equipped_artifact_names_text,
            payload_named_entries=_payload_named_entries,
            recipe_craft_name=_recipe_craft_name,
            build_equipped_artifact_details=_build_equipped_artifact_details,
        )
        inventory_state = _module_detail_build_inventory_module_state(
            payload,
            game_items_dict,
            enabled=module_key == "inventory" and bool(active_profile),
            query=inv_q,
            page=inv_page,
        )
        market_state = _module_detail_build_market_module_state(
            storage.get_marketplace_listings() if module_key == "market" else [],
            game_items_dict,
            enabled=module_key == "market",
            query=q,
            exchange_query=q_exchange,
            sort_key=sort,
            page=page,
        )

        shared_template_context = _build_shared_template_context(active_profile)
        sect_command_context = _build_sect_command_target_context(active_profile, sect_chat)

        return templates.TemplateResponse(
            request,
            "module.html",
            {
                "app_name": settings.app_name,
                "module": module,
                "active_profile": active_profile,
                "module_setting": module_setting,
                **cultivation_state,
                "cultivation_session": cultivation_session,
                "sect_session": sect_session,
                "module_commands": MODULE_COMMANDS.get(module_key, []),
                "sect_features": SECT_FEATURES,
                "current_sect_feature": current_sect_feature,
                **summary_state,
                "lingxiao_state": lingxiao_state,
                "yinluo_state": yinluo_state,
                "huangfeng_state": huangfeng_state,
                "wanling_state": wanling_state,
                "luoyun_state": luoyun_state,
                "xinggong_state": xinggong_state,
                "yuanying_sect_state": yuanying_sect_state,
                **payload_view_state,
                "other_play_definitions": OTHER_PLAY_DEFINITIONS,
                "other_opponent_options": other_opponent_options,
                "divination_batch_state": divination_batch_state,
                "fishing_state": fishing_state,
                "small_world_state": small_world_state,
                "small_world_auto_state": small_world_auto_state,
                "small_world_preach_auto_state": small_world_preach_auto_state,
                "small_world_manual_commands": biz_small_world_game.SMALL_WORLD_MANUAL_COMMANDS,
                "tianji_encounter_state": tianji_encounter_state,
                "tianji_remnant_state": tianji_remnant_state,
                "mulan_state": mulan_state,
                "tianxing_state": tianxing_state,
                "tianxing_daily_rewards": tianxing_daily_rewards,
                "wild_deep_log_export_result": wild_deep_log_export_result,
            "companion_state": companion_state,
            "companion_auto_state": companion_auto_state,
            "pagoda_auto_state": pagoda_auto_state,
            "tianji_trial_daily_auto_state": tianji_trial_daily_auto_state,
            "estate_hunt_daily_auto_state": estate_hunt_daily_auto_state,
            "artifact_touch_auto_state": artifact_touch_auto_state,
            "artifact_trial_auto_state": artifact_trial_auto_state,
            "wild_experience_state": wild_experience_state,
            "companion_heart_tribulation_state": companion_heart_tribulation_state,
                **other_module_state,
                "stock_state": stock_state,
                "dungeon_definitions": DUNGEON_DEFINITIONS,
                "selected_dungeon": selected_dungeon,
                "dungeon_command_buttons": dungeon_command_buttons,
                "dungeon_cleanup_targets": dungeon_cleanup_targets,
                "dungeon_messages": dungeon_messages,
                **inventory_state,
                "inventory_query_qs": quote_plus(inventory_state["inventory_query"])
                if inventory_state["inventory_query"]
                else "",
                **market_state,
                "market_query_qs": quote_plus(market_state["market_query"])
                if market_state["market_query"]
                else "",
                "market_exchange_query_qs": quote_plus(market_state["market_exchange_query"])
                if market_state["market_exchange_query"]
                else "",
                "sect_recent_reply_text": sect_recent_reply_text,
                "format_timestamp": biz_fanren_game.format_timestamp,
                "now_ts": biz_fanren_game.time.time(),
                "external_session_notice": _build_external_session_notice(
                    external_account
                ),
                **sect_command_context,
                **shared_template_context,
            },
        )

    @application.get("/api/dungeon-feed")
    async def dungeon_feed(
        request: Request, dungeon_key: str = "", chat_id: str = ""
    ) -> dict:
        active_profile = _get_request_profile(request)
        selected_dungeon = _get_dungeon_definition(dungeon_key)
        normalized_chat_id = str(chat_id or "").strip()
        resolved_chat_id = (
            int(normalized_chat_id)
            if normalized_chat_id.lstrip("-").isdigit()
            else None
        )
        if resolved_chat_id is None and active_profile:
            command_chat = _get_primary_command_chat(
                active_profile.id, biz_fanren_game.FANREN_BOT_USERNAME
            )
            if command_chat:
                resolved_chat_id = int(command_chat.chat_id)
        return {
            "chat_ready": bool(resolved_chat_id),
            "chat_id": resolved_chat_id,
            "dungeon": {
                "key": selected_dungeon["key"],
                "title": selected_dungeon["title"],
            },
            "messages": _build_dungeon_messages(
                storage,
                resolved_chat_id or 0,
                selected_dungeon["key"],
                profile_id=active_profile.id if active_profile else None,
            ),
        }

    @application.get("/api/stock-history")
    async def stock_history(
        request: Request, stock_code: str = "", range_key: str = "7d"
    ) -> dict:
        if not _get_request_profile(request):
            raise HTTPException(status_code=401, detail="Profile not active")
        normalized_code = str(stock_code or "").strip().upper()
        if not normalized_code:
            raise HTTPException(status_code=400, detail="stock_code is required")
        return _build_stock_history_response(storage, normalized_code, range_key)

    @application.post("/runtime/dungeon/clear-messages")
    async def runtime_clear_dungeon_messages(
        request: Request,
        dungeon_key: str = Form(...),
        chat_id: str = Form(...),
        redirect_to: str = Form("/modules/dungeon"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(
                status_code=400, detail="Dungeon chat is not configured"
            )
        resolved_chat_id = int(normalized_chat_id)
        message_ids = [
            int(message.get("message_id") or 0)
            for message in _list_dungeon_feed_source_messages(
                storage,
                resolved_chat_id,
                dungeon_key,
                profile_id=profile.id,
            )
            if int(message.get("message_id") or 0)
        ]
        storage.delete_bound_messages(resolved_chat_id, message_ids)
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/profiles")
    async def create_profile(
        name: str = Form(...),
    ) -> RedirectResponse:
        profile = storage.create_profile(
            name=name,
            activate=True,
        )
        _sync_env_binding(profile.id, profile.telegram_user_id)
        storage.ensure_module_settings(profile.id, module_registry.list_modules())
        return RedirectResponse(url="/", status_code=303)

    @application.post("/profiles/bulk-cultivation")
    async def bulk_profile_cultivation(
        request: Request,
        mode: str = Form(...),
        protected_profile_id: str = Form(
            str(DEFAULT_BULK_CULTIVATION_PROTECTED_PROFILE_ID)
        ),
    ) -> RedirectResponse:
        if not _get_request_profile(request):
            raise HTTPException(status_code=401, detail="Profile not active")
        normalized_protected_profile_id = max(
            biz_sect_game._parse_int(protected_profile_id, 0),
            0,
        )
        try:
            result = _set_all_profile_cultivation(
                storage,
                mode,
                protected_profile_id=normalized_protected_profile_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        normalized_mode = str(mode or "").strip().lower()
        return RedirectResponse(
            url=(
                "/profile?bulk_cultivation=1"
                f"&mode={normalized_mode}"
                f"&updated={result['updated']}"
                f"&skipped={result['skipped']}"
                f"&protected={result['protected']}"
            ),
            status_code=303,
        )

    @application.post("/profiles/stop-current-schedules")
    async def stop_current_profile_schedules(
        request: Request,
        confirm_1: str = Form(""),
        confirm_2: str = Form(""),
        confirm_3: str = Form(""),
    ) -> RedirectResponse:
        active_profile = _get_request_profile(request)
        if not active_profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        if [confirm_1, confirm_2, confirm_3] != ["1", "1", "1"]:
            raise HTTPException(
                status_code=400,
                detail="Stop current profile schedules requires three confirmations",
            )
        result = _stop_current_profile_schedules(storage, active_profile.id)
        return RedirectResponse(
            url=(
                "/profile?stop_current_schedules=1"
                f"&profiles={result['profiles']}"
                f"&outgoing_cancelled={result['outgoing_cancelled']}"
            ),
            status_code=303,
        )

    @application.post("/profiles/{profile_id}/bind-current-telegram")
    async def bind_current_telegram_account(
        request: Request, profile_id: int
    ) -> RedirectResponse:
        profile = storage.get_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        if not _profile_belongs_to_session(request, profile_id):
            raise HTTPException(
                status_code=403, detail="Profile not available in current session"
            )
        profile_session_name = (profile.telegram_session_name or "").strip()
        if profile_session_name:
            account = await get_authorized_account_info(
                profile_session_name, allow_fallback=False
            )
        else:
            account = await _discover_authorized_account(request)
            if not account:
                raise HTTPException(
                    status_code=400,
                    detail="No authorized Telegram session available for binding",
                )
        telegram_user_id = str(account.get("id") or "").strip()
        if not telegram_user_id:
            raise HTTPException(status_code=400, detail="Telegram account unavailable")
        telegram_username = (account.get("username") or "").strip()
        telegram_phone = (account.get("phone") or "").strip()
        telegram_session_name = (account.get("session_name") or "").strip()
        storage.bind_profile_telegram_account(
            profile_id,
            telegram_user_id=telegram_user_id,
            telegram_username=telegram_username,
            telegram_phone=telegram_phone,
            telegram_session_name=telegram_session_name,
        )
        _sync_env_binding(profile_id, telegram_user_id)
        storage.request_sect_refresh(profile_id, cooldown_seconds=0)
        return RedirectResponse(url="/profile", status_code=303)

    @application.post("/profiles/{profile_id}/refresh-info")
    async def refresh_profile_info(profile_id: int) -> RedirectResponse:
        profile = storage.get_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        if not profile.telegram_verified_at:
            return RedirectResponse(url="/profile", status_code=303)
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect
        if not _get_profile_refresh_cookie(profile_id):
            return RedirectResponse(url="/profile", status_code=303)
        _refresh_profile_external_info(profile)
        return RedirectResponse(url="/profile", status_code=303)

    @application.post("/profiles/refresh-all-info")
    async def refresh_all_profile_info(request: Request) -> RedirectResponse:
        original_profile = _get_request_profile(request)
        profiles = _list_session_profiles(request)
        if not profiles:
            return RedirectResponse(url="/profile", status_code=303)
        refreshed = 0
        failed = 0
        skipped = 0
        for profile in profiles:
            ok, message = _refresh_profile_external_info(profile)
            if ok:
                refreshed += 1
            elif message in {"missing_profile", "telegram_unverified", "missing_cookie"}:
                skipped += 1
            else:
                failed += 1
        if original_profile:
            storage.activate_profile(original_profile.id)
            _sync_env_binding(original_profile.id, original_profile.telegram_user_id)
        return RedirectResponse(
            url=(
                "/profile?refresh_all=1"
                f"&ok={refreshed}&failed={failed}&skipped={skipped}"
            ),
            status_code=303,
        )

    @application.post("/profiles/{profile_id}/chat-bindings/{chat_id}/bot-ids/add")
    async def add_chat_binding_bot_id(
        request: Request,
        profile_id: int,
        chat_id: int,
        bot_identity: str = Form(...),
        thread_id: str = Form(""),
        redirect_to: str = Form("/profile"),
    ) -> RedirectResponse:
        if not _profile_belongs_to_session(request, profile_id):
            raise HTTPException(status_code=403, detail="Profile not available in current session")
        profile = storage.get_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        identity = str(bot_identity or "").strip()
        if not identity:
            return RedirectResponse(url=redirect_to or "/profile", status_code=303)
        normalized_thread_id = _parse_optional_int(thread_id)
        binding = storage.get_chat_binding(profile_id, chat_id, thread_id=normalized_thread_id)
        if not binding:
            raise HTTPException(status_code=404, detail="Chat binding not found")
        bot_id = int(identity) if identity.lstrip("-").isdigit() else None
        bot_username = ""
        if bot_id is None:
            bot_username = identity.lstrip("@").strip()
            bot_id = storage.resolve_bot_id_from_username(identity)
            if bot_id is None:
                try:
                    resolved_account = await get_authorized_account_info(identity, allow_fallback=True)
                    bot_id = int(resolved_account.get("id") or 0) or None
                    bot_username = str(resolved_account.get("username") or bot_username).strip().lstrip("@")
                except Exception:
                    bot_id = None
            if bot_id is None:
                raise HTTPException(status_code=400, detail="无法解析该 bot 用户名对应的 bot id")
        storage.add_chat_binding_bot_id(profile_id, chat_id, bot_id, bot_username=bot_username, thread_id=binding.thread_id)
        return RedirectResponse(url=redirect_to or "/profile", status_code=303)

    @application.post("/profiles/{profile_id}/chat-bindings/{chat_id}/bot-ids/remove")
    async def remove_chat_binding_bot_id(
        request: Request,
        profile_id: int,
        chat_id: int,
        bot_id: int = Form(...),
        thread_id: str = Form(""),
        redirect_to: str = Form("/profile"),
    ) -> RedirectResponse:
        if not _profile_belongs_to_session(request, profile_id):
            raise HTTPException(status_code=403, detail="Profile not available in current session")
        profile = storage.get_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        normalized_thread_id = _parse_optional_int(thread_id)
        binding = storage.get_chat_binding(profile_id, chat_id, thread_id=normalized_thread_id)
        if not binding:
            raise HTTPException(status_code=404, detail="Chat binding not found")
        storage.remove_chat_binding_bot_id(profile_id, chat_id, bot_id, thread_id=binding.thread_id)
        return RedirectResponse(url=redirect_to or "/profile", status_code=303)

    @application.post("/profiles/{profile_id}/chat-bindings/{chat_id}/bot-candidates/{sender_id}/decision")
    async def decide_chat_binding_bot_candidate(
        request: Request,
        profile_id: int,
        chat_id: int,
        sender_id: int,
        action: str = Form(...),
        redirect_to: str = Form("/profile#chats"),
    ) -> RedirectResponse:
        if not _profile_belongs_to_session(request, profile_id):
            raise HTTPException(status_code=403, detail="Profile not available in current session")
        if int(chat_id) != int(settings.bound_chat_id):
            raise HTTPException(status_code=409, detail="Candidate is not in the current bound chat")
        if action not in {"trust", "reject"}:
            raise HTTPException(status_code=400, detail="Invalid candidate action")
        binding = storage.get_chat_binding(profile_id, chat_id)
        if not binding:
            raise HTTPException(status_code=404, detail="Chat binding not found")
        result = await bot_sync_web.run_bot_candidate_action(
            sender_id,
            trust=action == "trust",
        )
        if not result.get("ok"):
            raise HTTPException(status_code=409, detail=result.get("message") or "Candidate action failed")
        return RedirectResponse(url=redirect_to or "/profile#chats", status_code=303)

    @application.post("/modules/{module_key}/settings")
    async def save_module_setting(
        module_key: str,
        profile_id: int = Form(...),
        enabled: str = Form("0"),
        cooldown_seconds: int = Form(30),
        check_interval_seconds: int = Form(300),
        command_template: str = Form(""),
        notes: str = Form(""),
    ) -> RedirectResponse:
        if module_key in ("sect", "inventory"):
            return RedirectResponse(url=f"/modules/{module_key}", status_code=303)
        if not module_registry.get_module(module_key):
            raise HTTPException(status_code=404, detail="Module not found")
        if not storage.get_profile(profile_id):
            raise HTTPException(status_code=404, detail="Profile not found")
        storage.save_module_setting(
            profile_id=profile_id,
            module_key=module_key,
            enabled=enabled == "1",
            cooldown_seconds=cooldown_seconds,
            check_interval_seconds=check_interval_seconds,
            command_template=command_template,
            notes=notes,
        )
        return RedirectResponse(url=f"/modules/{module_key}", status_code=303)

    @application.post("/modules/{module_key}/toggle")
    async def toggle_module_setting(
        module_key: str,
        profile_id: int = Form(...),
        enabled: str = Form(...),
    ) -> RedirectResponse:
        if module_key in ("sect", "inventory"):
            return RedirectResponse(url=f"/modules/{module_key}", status_code=303)
        if not storage.get_profile(profile_id):
            raise HTTPException(status_code=404, detail="Profile not found")
        storage.ensure_module_settings(profile_id, module_registry.list_modules())
        storage.set_module_enabled(profile_id, module_key, enabled == "1")
        return RedirectResponse(url=f"/modules/{module_key}", status_code=303)

    @application.post("/modules/tianxing/config")
    async def save_tianxing_config(
        request: Request,
        profile_id: int = Form(...),
        scope: str = Form("safe"),
        auto_panel_enabled: str = Form("0"),
        auto_observe_enabled: str = Form("0"),
        auto_clear_calamity_enabled: str = Form("0"),
        timeline_enabled: str = Form("0"),
        timeline_dry_run_enabled: str = Form("0"),
        strategy_dry_run_enabled: str = Form("0"),
        auto_set_star_enabled: str = Form("0"),
        set_star_name: str = Form(""),
        auto_predict_enabled: str = Form("0"),
        auto_change_fate_enabled: str = Form("0"),
        craft_farm_enabled: str = Form("0"),
        craft_farm_dry_run_enabled: str = Form("0"),
        craft_farm_item: str = Form("玄铁剑"),
        craft_farm_quantity: int = Form(1),
        retreat_farm_enabled: str = Form("0"),
        retreat_farm_dry_run_enabled: str = Form("0"),
        deep_retreat_consume_enabled: str = Form("0"),
        redirect_to: str = Form("/modules/sect"),
    ) -> RedirectResponse:
        if not _profile_belongs_to_session(request, profile_id):
            raise HTTPException(
                status_code=403, detail="Profile not available in current session"
            )
        form = await request.form()
        normalized_scope = str(scope or "safe").strip().lower()
        if normalized_scope == "risk":
            updates = {
                "auto_set_star_enabled": auto_set_star_enabled == "1",
                "set_star_name": set_star_name,
                "auto_predict_enabled": auto_predict_enabled == "1",
                "auto_change_fate_enabled": auto_change_fate_enabled == "1",
            }
            if "route_priority" in form:
                updates["route_priority"] = list(form.getlist("route_priority"))
            if "change_route_priority" in form:
                updates["change_route_priority"] = list(
                    form.getlist("change_route_priority")
                )
            if any(
                field in form
                for field in (
                    "craft_farm_enabled",
                    "craft_farm_item",
                    "craft_farm_quantity",
                )
            ):
                updates["craft_farm_enabled"] = craft_farm_enabled == "1"
                updates["craft_farm_item"] = craft_farm_item
                updates["craft_farm_quantity"] = craft_farm_quantity
            if any(
                field in form
                for field in (
                    "retreat_farm_enabled",
                    "deep_retreat_consume_enabled",
                )
            ):
                updates["retreat_farm_enabled"] = retreat_farm_enabled == "1"
                updates["deep_retreat_consume_enabled"] = (
                    deep_retreat_consume_enabled == "1"
                )
            if "craft_farm_dry_run_enabled" in form:
                updates["craft_farm_dry_run_enabled"] = (
                    craft_farm_dry_run_enabled == "1"
                )
            if "retreat_farm_dry_run_enabled" in form:
                updates["retreat_farm_dry_run_enabled"] = (
                    retreat_farm_dry_run_enabled == "1"
                )
        else:
            updates = {
                "auto_panel_enabled": auto_panel_enabled == "1",
                "auto_observe_enabled": auto_observe_enabled == "1",
                "auto_clear_calamity_enabled": auto_clear_calamity_enabled == "1",
                "timeline_enabled": timeline_enabled == "1",
            }
            if "timeline_dry_run_enabled" in form:
                updates["timeline_dry_run_enabled"] = (
                    timeline_dry_run_enabled == "1"
                )
            if "strategy_dry_run_enabled" in form:
                updates["strategy_dry_run_enabled"] = (
                    strategy_dry_run_enabled == "1"
                )
        set_tianxing_profile_config(storage, profile_id, updates)
        normalized_redirect = str(redirect_to or "/modules/sect").strip()
        if not normalized_redirect.startswith("/"):
            normalized_redirect = "/modules/sect"
        return RedirectResponse(url=normalized_redirect, status_code=303)

    @application.post("/modules/tianxing/command")
    async def send_tianxing_manual_command(
        request: Request,
        profile_id: int = Form(...),
        action: str = Form(...),
        chat_id: str = Form(""),
        thread_id: str = Form(""),
        chat_type: str = Form("group"),
        bot_username: str = Form(""),
        redirect_to: str = Form("/modules/sect"),
    ) -> RedirectResponse:
        if not _profile_belongs_to_session(request, profile_id):
            raise HTTPException(
                status_code=403, detail="Profile not available in current session"
            )
        profile = storage.get_profile(profile_id)
        if not profile or not _is_tianxing_sect_profile(profile):
            raise HTTPException(status_code=404, detail="Tianxing sect profile not found")
        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")
        command_by_action = {
            "panel": ".天机盘",
            "observe": ".观命",
            "clear_calamity": ".消劫",
        }
        command = command_by_action.get(str(action or "").strip())
        if not command:
            raise HTTPException(status_code=400, detail="Unsupported Tianxing command")
        send_tianxing_command(
            storage,
            profile_id=profile_id,
            chat_id=int(normalized_chat_id),
            thread_id=int(thread_id) if thread_id and thread_id.isdigit() else None,
            chat_type=chat_type,
            bot_username=bot_username or biz_sect_game.SECT_BOT_USERNAME,
            command=command,
            family="tianxing_manual",
            dry_run=False,
        )
        normalized_redirect = str(redirect_to or "/modules/sect").strip()
        if not normalized_redirect.startswith("/"):
            normalized_redirect = "/modules/sect"
        return RedirectResponse(url=normalized_redirect, status_code=303)

    @application.post("/modules/tianxing/timeline")
    async def toggle_tianxing_timeline(
        request: Request,
        profile_id: int = Form(...),
        enabled: str = Form("1"),
        chat_id: str = Form(""),
        thread_id: str = Form(""),
        chat_type: str = Form("group"),
        bot_username: str = Form(""),
        redirect_to: str = Form("/modules/sect"),
    ) -> RedirectResponse:
        if not _profile_belongs_to_session(request, profile_id):
            raise HTTPException(
                status_code=403, detail="Profile not available in current session"
            )
        profile = storage.get_profile(profile_id)
        if not profile or not _is_tianxing_sect_profile(profile):
            raise HTTPException(status_code=404, detail="Tianxing sect profile not found")
        should_enable = str(enabled or "").strip() == "1"
        normalized_chat_id = str(chat_id or "").strip()
        if should_enable and not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")
        updates = {"timeline_enabled": should_enable}
        if should_enable:
            updates["timeline_dry_run_enabled"] = False
            stop_tianxing_craft_loop(
                storage,
                profile_id=profile_id,
                reason="exploration_timeline_started",
            )
        set_tianxing_profile_config(
            storage,
            profile_id,
            updates,
        )
        if should_enable:
            start_tianxing_timeline(
                storage,
                profile_id=profile_id,
                chat_id=int(normalized_chat_id),
                route="探索",
                thread_id=int(thread_id) if thread_id and thread_id.isdigit() else None,
                chat_type=chat_type,
                bot_username=bot_username or biz_sect_game.SECT_BOT_USERNAME,
            )
        normalized_redirect = str(redirect_to or "/modules/sect").strip()
        if not normalized_redirect.startswith("/"):
            normalized_redirect = "/modules/sect"
        return RedirectResponse(url=normalized_redirect, status_code=303)

    @application.post("/modules/tianxing/craft-loop")
    async def toggle_tianxing_craft_loop(
        request: Request,
        profile_id: int = Form(...),
        enabled: str = Form("1"),
        item: str = Form("玄铁剑"),
        target_count: int = Form(30),
        chat_id: str = Form(""),
        thread_id: str = Form(""),
        chat_type: str = Form("group"),
        bot_username: str = Form(""),
        redirect_to: str = Form("/modules/sect"),
    ) -> RedirectResponse:
        if not _profile_belongs_to_session(request, profile_id):
            raise HTTPException(
                status_code=403, detail="Profile not available in current session"
            )
        profile = storage.get_profile(profile_id)
        if not profile or not _is_tianxing_sect_profile(profile):
            raise HTTPException(status_code=404, detail="Tianxing sect profile not found")
        should_enable = str(enabled or "").strip() == "1"
        normalized_chat_id = str(chat_id or "").strip()
        if should_enable and not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")
        if should_enable:
            start_tianxing_craft_loop(
                storage,
                profile_id=profile_id,
                chat_id=int(normalized_chat_id),
                thread_id=int(thread_id) if thread_id and thread_id.isdigit() else None,
                chat_type=chat_type,
                bot_username=bot_username or biz_sect_game.SECT_BOT_USERNAME,
                item=item or "玄铁剑",
                target_count=target_count,
            )
        else:
            stop_tianxing_craft_loop(storage, profile_id=profile_id)
        normalized_redirect = str(redirect_to or "/modules/sect").strip()
        if not normalized_redirect.startswith("/"):
            normalized_redirect = "/modules/sect"
        return RedirectResponse(url=normalized_redirect, status_code=303)

    @application.post("/modules/sect/wild-deep-log/export")
    async def export_wild_deep_log(
        request: Request,
        day: str = Form(""),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        selected_day_key = _normalize_tianxing_day_key(day)
        sect_chat = _get_primary_command_chat(
            profile.id,
            biz_sect_game.SECT_BOT_USERNAME,
        )
        result = _export_wild_deep_log_file(
            storage,
            profile_id=profile.id,
            day_key=selected_day_key,
            chat_id=int(sect_chat.chat_id) if sect_chat else None,
        )
        redirect_url = (
            f"/modules/sect?explore_day={quote_plus(result['day_key'])}"
            "&wild_deep_export=1"
            f"&wild_deep_rows={int(result['rows'])}"
            f"&wild_deep_path={quote_plus(result['path'])}"
        )
        return RedirectResponse(url=redirect_url, status_code=303)

    @application.post("/runtime/commands/send-raw")
    async def runtime_send_raw_command(
        request: Request,
        chat_id: str = Form(...),
        text: str = Form(...),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/"),
    ) -> RedirectResponse:
        profile = getattr(request.state, "auth_profile", None)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect

        normalized_text = (text or "").strip()
        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")
        if not normalized_text:
            raise HTTPException(status_code=400, detail="Command text is required")

        storage.enqueue_outgoing_command(
            profile_id=profile.id,
            chat_id=int(normalized_chat_id),
            text=normalized_text,
            thread_id=int(thread_id) if thread_id and thread_id.isdigit() else None,
            chat_type=chat_type,
            bot_username=bot_username,
        )
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/tianji-trial/miniapp-auto")
    async def runtime_start_tianji_trial_miniapp_auto(
        request: Request,
        chat_id: str = Form(...),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/modules/other"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect

        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")
        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None

        external_account = storage.get_external_account(profile.id, ASC_PROVIDER) or {}
        try:
            payload = json.loads(external_account.get("me_json") or "{}")
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload = queue_tianji_trial_request(
            payload,
            chat_id=resolved_chat_id,
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
        )
        storage.upsert_external_account(
            profile.id,
            ASC_PROVIDER,
            str(
                external_account.get("telegram_user_id")
                or profile.telegram_user_id
                or ""
            ),
            str(
                external_account.get("telegram_username")
                or profile.telegram_username
                or ""
            ),
            str(external_account.get("status") or "connected"),
            str(external_account.get("cookie_text") or ""),
            payload,
            str(external_account.get("api_token") or ""),
        )
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/tianji-trial/daily-auto")
    async def runtime_toggle_tianji_trial_daily_auto(
        request: Request,
        chat_id: str = Form(...),
        run_time: str = Form(biz_tianji_trial_daily_auto.DEFAULT_RUN_TIME),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/modules/other"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        if admin_global_execution.is_schedule_enabled(storage, "tianji"):
            raise HTTPException(
                status_code=409,
                detail="已由“诸元神巡令”统一托管",
            )
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect

        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")
        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None
        normalized_run_time = biz_tianji_trial_daily_auto.normalize_run_time(run_time)
        feature_key = biz_tianji_trial_daily_auto.FEATURE_KEY
        existing_task = storage.get_companion_auto_task(
            profile.id,
            resolved_chat_id,
            feature_key,
        )
        if existing_task and bool(existing_task.get("enabled")):
            storage.disable_companion_auto_task(
                profile.id,
                resolved_chat_id,
                feature_key,
                last_error="用户手动关闭每日自动天机试炼。",
            )
            for command_text in (
                biz_tianji_trial_daily_auto.REMNANT_COMMAND,
                biz_tianji_trial_daily_auto.TRIAL_COMMAND,
            ):
                storage.cancel_pending_outgoing_commands(
                    profile.id,
                    resolved_chat_id,
                    text=command_text,
                    thread_id=resolved_thread_id,
                    require_exact_thread=True,
                )
            return RedirectResponse(url=redirect_to, status_code=303)

        storage.cancel_pending_outgoing_commands(
            profile.id,
            resolved_chat_id,
            text=xinggong_miniapp.XINGGONG_STARBOARD_COMMAND,
            thread_id=resolved_thread_id,
            require_exact_thread=True,
        )
        now_ts = biz_fanren_game.time.time()
        sent_today = biz_tianji_trial_daily_auto.is_same_local_day(
            float((existing_task or {}).get("last_run_at") or 0),
            now_ts,
        )
        next_run_at = biz_tianji_trial_daily_auto.resolve_next_run_at(
            normalized_run_time,
            now=now_ts,
            attempted_today=sent_today,
        )
        task = storage.upsert_companion_auto_task(
            profile_id=profile.id,
            chat_id=resolved_chat_id,
            feature_key=feature_key,
            enabled=True,
            strategy=normalized_run_time,
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            next_run_at=next_run_at,
            last_run_at=float((existing_task or {}).get("last_run_at") or 0),
            last_error=(biz_tianji_trial_daily_auto.SENT_TODAY_ERROR if sent_today else ""),
        )
        storage.update_companion_auto_task(
            int(task["id"]),
            workflow_state="",
        )
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/estate/miniapp-hunt-daily-auto")
    async def runtime_toggle_estate_miniapp_hunt_daily_auto(
        request: Request,
        chat_id: str = Form(...),
        run_time: str = Form(biz_estate_hunt_daily_auto.DEFAULT_RUN_TIME),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/modules/estate"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        if admin_global_execution.is_schedule_enabled(storage, "estate"):
            raise HTTPException(
                status_code=409,
                detail="已由“诸元神巡令”统一托管",
            )
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect

        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")
        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None
        normalized_run_time = biz_estate_hunt_daily_auto.normalize_run_time(run_time)
        feature_key = biz_estate_hunt_daily_auto.FEATURE_KEY
        existing_task = storage.get_companion_auto_task(
            profile.id,
            resolved_chat_id,
            feature_key,
        )
        if existing_task and bool(existing_task.get("enabled")):
            storage.disable_companion_auto_task(
                profile.id,
                resolved_chat_id,
                feature_key,
                last_error="用户手动关闭每日自动洞府寻宝。",
            )
            return RedirectResponse(url=redirect_to, status_code=303)

        now_ts = biz_fanren_game.time.time()
        sent_today = biz_estate_hunt_daily_auto.is_same_local_day(
            float((existing_task or {}).get("last_run_at") or 0),
            now_ts,
        )
        next_run_at = biz_estate_hunt_daily_auto.resolve_next_run_at(
            normalized_run_time,
            now=now_ts,
            attempted_today=sent_today,
        )
        task = storage.upsert_companion_auto_task(
            profile_id=profile.id,
            chat_id=resolved_chat_id,
            feature_key=feature_key,
            enabled=True,
            strategy=normalized_run_time,
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            next_run_at=next_run_at,
            last_run_at=float((existing_task or {}).get("last_run_at") or 0),
            last_error=(biz_estate_hunt_daily_auto.SENT_TODAY_ERROR if sent_today else ""),
        )
        storage.update_companion_auto_task(
            int(task["id"]),
            workflow_state="",
        )
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/estate/miniapp-hunt-canary")
    async def runtime_start_estate_miniapp_hunt_canary(
        request: Request,
        chat_id: str = Form(...),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/modules/estate"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect

        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")
        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None

        external_account = storage.get_external_account(profile.id, ASC_PROVIDER) or {}
        try:
            payload = json.loads(external_account.get("me_json") or "{}")
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if is_estate_miniapp_hunt_limit_reached(payload):
            payload = mark_estate_miniapp_hunt_limit_reached(payload)
            storage.upsert_external_account(
                profile.id,
                ASC_PROVIDER,
                str(
                    external_account.get("telegram_user_id")
                    or profile.telegram_user_id
                    or ""
                ),
                str(
                    external_account.get("telegram_username")
                    or profile.telegram_username
                    or ""
                ),
                str(external_account.get("status") or "connected"),
                str(external_account.get("cookie_text") or ""),
                payload,
                str(external_account.get("api_token") or ""),
            )
            return RedirectResponse(url=redirect_to, status_code=303)

        payload = queue_estate_miniapp_hunt_request(
            payload,
            chat_id=resolved_chat_id,
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
        )
        storage.upsert_external_account(
            profile.id,
            ASC_PROVIDER,
            str(
                external_account.get("telegram_user_id")
                or profile.telegram_user_id
                or ""
            ),
            str(
                external_account.get("telegram_username")
                or profile.telegram_username
                or ""
            ),
            str(external_account.get("status") or "connected"),
            str(external_account.get("cookie_text") or ""),
            payload,
            str(external_account.get("api_token") or ""),
        )
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/sect/luoyun-spirit-tree-canary")
    async def runtime_start_luoyun_spirit_tree_canary(
        request: Request,
        chat_id: str = Form(...),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/modules/sect"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect
        if not biz_luoyun_spirit_tree_daily_auto.is_allowed_profile(profile):
            raise HTTPException(
                status_code=400,
                detail="仅当前宗门为落云宗时可用",
            )
        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Sect chat is not configured")
        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None
        payload = read_cached_external_payload(storage, profile.id)
        if luoyun_spirit_tree_miniapp.get_pending_luoyun_spirit_tree_request(payload):
            raise HTTPException(status_code=409, detail="已有云梦山灵眼赛请求在运行")
        updated_payload = luoyun_spirit_tree_miniapp.queue_luoyun_spirit_tree_request(
            payload,
            chat_id=resolved_chat_id,
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            run_mode="canary",
        )
        external_account = storage.get_external_account(profile.id, ASC_PROVIDER) or {}
        storage.upsert_external_account(
            profile.id,
            ASC_PROVIDER,
            str(external_account.get("telegram_user_id") or profile.telegram_user_id or ""),
            str(external_account.get("telegram_username") or profile.telegram_username or ""),
            str(external_account.get("status") or "connected"),
            str(external_account.get("cookie_text") or ""),
            updated_payload,
            str(external_account.get("api_token") or ""),
        )
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/sect/luoyun-spirit-tree-daily-auto")
    async def runtime_toggle_luoyun_spirit_tree_daily_auto(
        request: Request,
        chat_id: str = Form(...),
        run_time: str = Form(
            biz_luoyun_spirit_tree_daily_auto.DEFAULT_RUN_TIME
        ),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/modules/sect"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect
        if not biz_luoyun_spirit_tree_daily_auto.is_allowed_profile(profile):
            raise HTTPException(
                status_code=400,
                detail="仅当前宗门为落云宗时可用",
            )
        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Sect chat is not configured")
        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None
        feature_key = biz_luoyun_spirit_tree_daily_auto.FEATURE_KEY
        existing_task = storage.get_companion_auto_task(
            profile.id,
            resolved_chat_id,
            feature_key,
        )
        payload = read_cached_external_payload(storage, profile.id)
        if existing_task and bool(existing_task.get("enabled")):
            storage.disable_companion_auto_task(
                profile.id,
                resolved_chat_id,
                feature_key,
                last_error="用户手动关闭每日云梦山灵眼赛。",
            )
            if not luoyun_spirit_tree_miniapp.get_pending_luoyun_spirit_tree_submission(
                payload
            ):
                updated_payload = luoyun_spirit_tree_miniapp.cancel_luoyun_spirit_tree_request(
                    payload,
                    reason="用户手动关闭每日云梦山灵眼赛。",
                )
                external_account = storage.get_external_account(
                    profile.id,
                    ASC_PROVIDER,
                ) or {}
                storage.upsert_external_account(
                    profile.id,
                    ASC_PROVIDER,
                    str(external_account.get("telegram_user_id") or profile.telegram_user_id or ""),
                    str(external_account.get("telegram_username") or profile.telegram_username or ""),
                    str(external_account.get("status") or "connected"),
                    str(external_account.get("cookie_text") or ""),
                    updated_payload,
                    str(external_account.get("api_token") or ""),
                )
            return RedirectResponse(url=redirect_to, status_code=303)

        board = (
            payload.get("luoyun_spirit_tree")
            if isinstance(payload.get("luoyun_spirit_tree"), dict)
            else {}
        )
        canary = board.get("canary") if isinstance(board.get("canary"), dict) else {}
        if not bool(canary.get("passed")):
            raise HTTPException(
                status_code=409,
                detail="请先执行并通过跃、飞各一次真实 Canary",
            )
        normalized_run_time = biz_luoyun_spirit_tree_daily_auto.normalize_run_time(
            run_time
        )
        now_ts = biz_fanren_game.time.time()
        attempted_today = (
            biz_luoyun_spirit_tree_daily_auto.is_same_local_day(
                float((existing_task or {}).get("last_run_at") or 0),
                now_ts,
            )
            or luoyun_spirit_tree_miniapp.is_luoyun_spirit_tree_daily_target_reached(
                payload,
                now=now_ts,
            )
        )
        next_run_at = biz_luoyun_spirit_tree_daily_auto.resolve_next_run_at(
            normalized_run_time,
            now=now_ts,
            attempted_today=attempted_today,
        )
        task = storage.upsert_companion_auto_task(
            profile_id=profile.id,
            chat_id=resolved_chat_id,
            feature_key=feature_key,
            enabled=True,
            strategy=normalized_run_time,
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            next_run_at=next_run_at,
            last_run_at=float((existing_task or {}).get("last_run_at") or 0),
            last_error=(
                biz_luoyun_spirit_tree_daily_auto.COMPLETED_TODAY_ERROR
                if attempted_today
                else ""
            ),
        )
        storage.update_companion_auto_task(int(task["id"]), workflow_state="")
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/mulan/auto-support-plan")
    async def runtime_save_mulan_auto_support_plan(
        request: Request,
        chat_id: str = Form(...),
        support_command: str = Form("auto"),
        enabled: int = Form(1),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/modules/other"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")

        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")
        normalized_command = str(support_command or "").strip()
        if normalized_command not in MULAN_VALID_SUPPORT_COMMANDS:
            normalized_command = "auto"

        should_enable = bool(int(enabled or 0))
        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None
        existing_task = storage.get_companion_auto_task(
            profile.id,
            resolved_chat_id,
            MULAN_AUTO_SUPPORT_FEATURE_KEY,
        )

        task = storage.upsert_companion_auto_task(
            profile_id=profile.id,
            chat_id=resolved_chat_id,
            feature_key=MULAN_AUTO_SUPPORT_FEATURE_KEY,
            enabled=should_enable,
            strategy=normalized_command,
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            next_run_at=time.time() if should_enable else 0,
            last_run_at=0,
            last_error=(
                "自动慕兰已开启，等待后台刷新边境军功。"
                if should_enable
                else "自动慕兰已停止。"
            ),
        )
        if task:
            storage.update_companion_auto_task(
                int(task["id"]),
                workflow_state="",
                anchor_command_msg_id=0,
                anchor_bot_msg_id=0,
            )
        if not should_enable:
            cancel_commands = [
                mulan_feature.MULAN_PANEL_COMMAND_TEXT,
                mulan_feature.MULAN_SPY_COMMAND_TEXT,
                mulan_feature.MULAN_COLLECT_REPORT_COMMAND_TEXT,
                *MULAN_VALID_SUPPORT_COMMANDS,
            ]
            existing_workflow = str(
                (existing_task or {}).get("workflow_state") or ""
            ).strip()
            for part in existing_workflow.split("|"):
                command_part = part.strip()
                if command_part.startswith(".辨报 ") or command_part.startswith(".公开军报 "):
                    cancel_commands.append(command_part)
            for command_text in cancel_commands:
                storage.cancel_pending_outgoing_commands(
                    profile.id,
                    resolved_chat_id,
                    command_text,
                    thread_id=resolved_thread_id,
                    require_exact_thread=resolved_thread_id is not None,
                )
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/commands/divination-batch")
    async def runtime_start_divination_batch(
        request: Request,
        chat_id: str = Form(...),
        target_count: int = Form(...),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/modules/other"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect

        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")

        normalized_target_count = max(int(target_count or 0), 0)
        if normalized_target_count <= 0:
            raise HTTPException(status_code=400, detail="Target count is required")

        resolved_chat_id = int(normalized_chat_id)
        payload = read_cached_external_payload(storage, profile.id)
        current_count = _build_divination_view(payload)["today_count"]
        remaining_rounds = max(normalized_target_count - current_count, 0)
        if remaining_rounds <= 0:
            return RedirectResponse(url=redirect_to, status_code=303)

        active_batch = storage.get_active_divination_batch(profile.id, resolved_chat_id)
        if active_batch:
            return RedirectResponse(url=redirect_to, status_code=303)

        batch_id = storage.start_divination_batch(
            profile_id=profile.id,
            chat_id=resolved_chat_id,
            target_count=normalized_target_count,
            initial_count=current_count,
            thread_id=int(thread_id) if thread_id and thread_id.isdigit() else None,
            chat_type=chat_type,
            bot_username=bot_username,
        )
        try:
            storage.enqueue_outgoing_command(
                profile_id=profile.id,
                chat_id=resolved_chat_id,
                text=".卜筮问天",
                thread_id=int(thread_id) if thread_id and thread_id.isdigit() else None,
                chat_type=chat_type,
                bot_username=bot_username,
                delay_seconds=0,
            )
            storage.update_divination_batch(
                batch_id,
                last_dispatch_at=biz_fanren_game.time.time(),
            )
        except Exception as exc:
            storage.finish_divination_batch(
                batch_id, status="failed", last_error=str(exc)
            )
            raise

        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/commands/divination-batch/cancel")
    async def runtime_cancel_divination_batch(
        request: Request,
        chat_id: str = Form(...),
        redirect_to: str = Form("/modules/other"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")
        resolved_chat_id = int(normalized_chat_id)
        active_batch = storage.get_active_divination_batch(profile.id, resolved_chat_id)
        if active_batch:
            storage.finish_divination_batch(
                int(active_batch["id"]),
                status="cancelled",
                last_error="Cancelled by user",
            )
        storage.cancel_pending_outgoing_commands(
            profile.id,
            resolved_chat_id,
            text=".卜筮问天",
        )
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/fishing/auto")
    async def runtime_toggle_fishing_auto(
        request: Request,
        chat_id: str = Form(...),
        enabled: str = Form(...),
        pond: str = Form(biz_fishing_game.FISHING_DEFAULT_POND),
        bait: str = Form(biz_fishing_game.FISHING_DEFAULT_BAIT),
        auto_probe: str = Form("1"),
        auto_nest: str = Form("0"),
        nest: str = Form(biz_fishing_game.FISHING_DEFAULT_NEST),
        nest_limit: str = Form("0"),
        auto_until_limit: str = Form("1"),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/modules/fishing"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect
        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")
        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None
        existing = storage.get_fishing_session(profile.id, resolved_chat_id)
        should_enable = enabled == "1"
        clean_pond = str(pond or "").strip() or biz_fishing_game.FISHING_DEFAULT_POND
        clean_bait = str(bait or "").strip() or biz_fishing_game.FISHING_DEFAULT_BAIT
        clean_nest = biz_fishing_game.get_fishing_nest_option(str(nest or ""))["name"]
        try:
            clean_nest_limit = max(int(str(nest_limit or "0").strip() or 0), 0)
        except ValueError:
            clean_nest_limit = 0
        if should_enable and auto_nest == "1" and clean_nest_limit <= 0:
            clean_nest_limit = int(
                biz_fishing_game.get_fishing_nest_option(clean_nest).get("daily_limit")
                or 1
            )
        clean_auto_nest = should_enable and auto_nest == "1"
        if existing:
            storage.update_fishing_session(
                int(existing["id"]),
                thread_id=resolved_thread_id,
                chat_type=chat_type,
                bot_username=bot_username,
                enabled=should_enable,
                pond=clean_pond,
                bait=clean_bait,
                auto_probe=auto_probe == "1",
                auto_nest=clean_auto_nest,
                nest=clean_nest,
                nest_limit=clean_nest_limit,
                nest_used_count=0 if should_enable else int(existing.get("nest_used_count") or 0),
                nest_remaining=(
                    int(existing.get("nest_remaining") or 0) if should_enable else 0
                ),
                auto_until_limit=auto_until_limit == "1",
                state="needs_basket" if should_enable else "stopped",
                next_action_at=biz_fanren_game.time.time() if should_enable else 0,
                last_error="",
            )
        else:
            storage.upsert_fishing_session(
                profile_id=profile.id,
                chat_id=resolved_chat_id,
                thread_id=resolved_thread_id,
                chat_type=chat_type,
                bot_username=bot_username,
                enabled=should_enable,
                pond=clean_pond,
                bait=clean_bait,
                auto_probe=auto_probe == "1",
                auto_nest=clean_auto_nest,
                nest=clean_nest,
                nest_limit=clean_nest_limit,
                auto_until_limit=auto_until_limit == "1",
                state="needs_basket" if should_enable else "stopped",
                next_action_at=biz_fanren_game.time.time() if should_enable else 0,
            )
        if not should_enable:
            for command_text in {
                biz_fishing_game.FISHING_STATUS_COMMAND,
                biz_fishing_game.FISHING_BASKET_COMMAND,
                biz_fishing_game.FISHING_PROBE_COMMAND,
                biz_fishing_game.FISHING_HOOK_COMMAND,
                biz_fishing_game.FISHING_STOP_COMMAND,
                biz_fishing_game.build_nest_command(clean_nest),
                biz_fishing_game.build_start_command(clean_pond, clean_bait),
            }:
                storage.cancel_pending_outgoing_commands(
                    profile.id,
                    resolved_chat_id,
                    text=command_text,
                    thread_id=resolved_thread_id,
                )
        return RedirectResponse(url=redirect_to, status_code=303)

    def _queue_fishing_miniapp_start(
        request: Request,
        *,
        chat_id: str,
        pond: str,
        bait: str,
        thread_id: Optional[str],
        chat_type: str,
        bot_username: str,
        redirect_to: str,
        one_cast: bool,
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect
        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")

        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None
        existing = storage.get_fishing_session(profile.id, resolved_chat_id)
        clean_pond = str(
            pond or (existing or {}).get("pond") or biz_fishing_game.FISHING_DEFAULT_POND
        ).strip() or biz_fishing_game.FISHING_DEFAULT_POND
        clean_bait = str(
            bait or (existing or {}).get("bait") or biz_fishing_game.FISHING_DEFAULT_BAIT
        ).strip() or biz_fishing_game.FISHING_DEFAULT_BAIT
        now = biz_fanren_game.time.time()
        daily_count = 0
        daily_limit = fishing_miniapp.FISHING_MINIAPP_DAILY_LIMIT_FALLBACK
        if existing:
            try:
                daily_count = max(int(existing.get("daily_count") or 0), 0)
            except (TypeError, ValueError):
                daily_count = 0
            try:
                daily_limit = max(int(existing.get("daily_limit") or daily_limit), 1)
            except (TypeError, ValueError):
                daily_limit = fishing_miniapp.FISHING_MINIAPP_DAILY_LIMIT_FALLBACK
            if not biz_fishing_daily_auto.is_same_local_day(
                float(existing.get("last_action_at") or 0),
                now,
            ):
                daily_count = 0
        state = "miniapp_canary" if one_cast else "miniapp_batch"
        last_error = (
            "MiniApp 试钓已登记，等待 Telegram runtime 使用公共洞府入口执行。"
            if one_cast
            else "MiniApp 钓满今日已登记，等待 Telegram runtime 使用公共洞府入口执行。"
        )
        limit_reached = daily_limit > 0 and daily_count >= daily_limit
        if limit_reached:
            state = "finished"
            last_error = "今日竿数已满，未排队 MiniApp 钓鱼。"
        if existing:
            storage.update_fishing_session(
                int(existing["id"]),
                thread_id=resolved_thread_id,
                chat_type=chat_type,
                bot_username=bot_username,
                enabled=not limit_reached,
                pond=clean_pond,
                bait=clean_bait,
                auto_probe=True,
                auto_nest=False,
                auto_until_limit=True,
                state=state,
                daily_count=daily_count,
                daily_limit=daily_limit,
                last_command_text="MiniApp 公共洞府直连",
                next_action_at=now if not limit_reached else 0,
                last_action_at=now,
                last_error=last_error,
            )
        else:
            storage.upsert_fishing_session(
                profile_id=profile.id,
                chat_id=resolved_chat_id,
                thread_id=resolved_thread_id,
                chat_type=chat_type,
                bot_username=bot_username,
                enabled=not limit_reached,
                pond=clean_pond,
                bait=clean_bait,
                auto_probe=True,
                auto_nest=False,
                auto_until_limit=True,
                state=state,
                daily_count=0,
                daily_limit=daily_limit,
                last_command_text="MiniApp 公共洞府直连",
                next_action_at=now if not limit_reached else 0,
                last_action_at=now,
                last_error=last_error,
            )
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/fishing/miniapp-canary")
    async def runtime_start_fishing_miniapp_canary(
        request: Request,
        chat_id: str = Form(...),
        pond: str = Form(biz_fishing_game.FISHING_DEFAULT_POND),
        bait: str = Form(biz_fishing_game.FISHING_DEFAULT_BAIT),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/modules/fishing"),
    ) -> RedirectResponse:
        return _queue_fishing_miniapp_start(
            request,
            chat_id=chat_id,
            pond=pond,
            bait=bait,
            thread_id=thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            redirect_to=redirect_to,
            one_cast=True,
        )

    @application.post("/runtime/fishing/miniapp-full")
    async def runtime_start_fishing_miniapp_full(
        request: Request,
        chat_id: str = Form(...),
        pond: str = Form(biz_fishing_game.FISHING_DEFAULT_POND),
        bait: str = Form(biz_fishing_game.FISHING_DEFAULT_BAIT),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/modules/fishing"),
    ) -> RedirectResponse:
        return _queue_fishing_miniapp_start(
            request,
            chat_id=chat_id,
            pond=pond,
            bait=bait,
            thread_id=thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            redirect_to=redirect_to,
            one_cast=False,
        )

    @application.post("/runtime/fishing/miniapp-daily-auto")
    async def runtime_toggle_fishing_miniapp_daily_auto(
        request: Request,
        chat_id: str = Form(...),
        pond: str = Form(biz_fishing_game.FISHING_DEFAULT_POND),
        bait: str = Form(biz_fishing_game.FISHING_DEFAULT_BAIT),
        run_time: str = Form(biz_fishing_daily_auto.DEFAULT_RUN_TIME),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/modules/fishing"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect
        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")
        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None
        feature_key = biz_fishing_daily_auto.FEATURE_KEY
        existing_task = storage.get_companion_auto_task(
            profile.id,
            resolved_chat_id,
            feature_key,
        )
        existing_session = storage.get_fishing_session(profile.id, resolved_chat_id)
        if existing_task and bool(existing_task.get("enabled")):
            storage.disable_companion_auto_task(
                profile.id,
                resolved_chat_id,
                feature_key,
                last_error="用户手动关闭每日灵溪垂钓。",
            )
            if existing_session and str(existing_session.get("state") or "") == "miniapp_batch":
                storage.update_fishing_session(
                    int(existing_session["id"]),
                    enabled=False,
                    state="stopped",
                    next_action_at=0,
                    last_error="用户手动关闭每日灵溪垂钓。",
                )
            return RedirectResponse(url=redirect_to, status_code=303)

        session_view = _build_fishing_view(existing_session)
        if not session_view.get("canary_passed"):
            raise HTTPException(status_code=409, detail="请先完成一次真实 MiniApp 试钓")
        clean_pond = str(pond or session_view.get("pond") or biz_fishing_game.FISHING_DEFAULT_POND).strip()
        clean_bait = str(bait or session_view.get("bait") or biz_fishing_game.FISHING_DEFAULT_BAIT).strip()
        if existing_session:
            storage.update_fishing_session(
                int(existing_session["id"]),
                pond=clean_pond,
                bait=clean_bait,
                enabled=False,
            )
        else:
            storage.upsert_fishing_session(
                profile_id=profile.id,
                chat_id=resolved_chat_id,
                thread_id=resolved_thread_id,
                chat_type=chat_type,
                bot_username=bot_username,
                enabled=False,
                pond=clean_pond,
                bait=clean_bait,
                daily_limit=fishing_miniapp.FISHING_MINIAPP_DAILY_LIMIT_FALLBACK,
            )
        normalized_run_time = biz_fishing_daily_auto.normalize_run_time(run_time)
        now_ts = biz_fanren_game.time.time()
        attempted_today = biz_fishing_daily_auto.is_same_local_day(
            float((existing_task or {}).get("last_run_at") or 0),
            now_ts,
        )
        next_run_at = biz_fishing_daily_auto.resolve_next_run_at(
            normalized_run_time,
            now=now_ts,
            attempted_today=attempted_today,
        )
        task = storage.upsert_companion_auto_task(
            profile_id=profile.id,
            chat_id=resolved_chat_id,
            feature_key=feature_key,
            enabled=True,
            strategy=normalized_run_time,
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            next_run_at=next_run_at,
            last_run_at=float((existing_task or {}).get("last_run_at") or 0),
            last_error=(
                biz_fishing_daily_auto.COMPLETED_TODAY_ERROR if attempted_today else ""
            ),
        )
        storage.update_companion_auto_task(int(task["id"]), workflow_state="")
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/commands/pagoda-auto")
    async def runtime_toggle_pagoda_auto(
        request: Request,
        chat_id: str = Form(...),
        run_time: str = Form(pagoda_auto.DEFAULT_RUN_TIME),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/modules/other"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        if admin_global_execution.is_schedule_enabled(storage, "pagoda"):
            raise HTTPException(
                status_code=409,
                detail="已由“诸元神巡令”统一托管",
            )
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect

        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")
        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None
        normalized_run_time = pagoda_auto.normalize_run_time(run_time)
        existing_task = storage.get_companion_auto_task(
            profile.id,
            resolved_chat_id,
            pagoda_auto.FEATURE_KEY,
        )
        if existing_task and bool(existing_task.get("enabled")):
            storage.disable_companion_auto_task(
                profile.id,
                resolved_chat_id,
                pagoda_auto.FEATURE_KEY,
                last_error="用户手动关闭自动闯塔。",
            )
            storage.cancel_pending_outgoing_commands(
                profile.id,
                resolved_chat_id,
                text=pagoda_auto.COMMAND,
                thread_id=resolved_thread_id,
                require_exact_thread=True,
            )
            return RedirectResponse(url=redirect_to, status_code=303)

        payload = read_cached_external_payload(storage, profile.id)
        now_ts = biz_fanren_game.time.time()
        sent_today = pagoda_auto.is_same_local_day(
            float((existing_task or {}).get("last_run_at") or 0),
            now_ts,
        )
        attempted_today = pagoda_auto.attempted_today_from_payload(
            payload if isinstance(payload, dict) else {},
            now=now_ts,
        )
        next_run_at = pagoda_auto.resolve_next_run_at(
            normalized_run_time,
            now=now_ts,
            attempted_today=attempted_today or sent_today,
            profile_id=profile.id,
        )
        storage.upsert_companion_auto_task(
            profile_id=profile.id,
            chat_id=resolved_chat_id,
            feature_key=pagoda_auto.FEATURE_KEY,
            enabled=True,
            strategy=normalized_run_time,
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            next_run_at=next_run_at,
            last_run_at=float((existing_task or {}).get("last_run_at") or 0),
            last_error=(
                pagoda_auto.ATTEMPTED_TODAY_ERROR
                if attempted_today or sent_today
                else ""
            ),
        )
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/small-world/auto")
    async def runtime_toggle_small_world_auto(
        request: Request,
        chat_id: str = Form(...),
        enabled: str = Form("1"),
        collect_enabled: str = Form("0"),
        collect_threshold: str = Form(
            str(biz_small_world_game.SMALL_WORLD_DEFAULT_COLLECT_THRESHOLD)
        ),
        quench_after_collect_enabled: str = Form("1"),
        manifest_enabled: str = Form("0"),
        preach_enabled: str = Form("0"),
        refresh_interval_minutes: int = Form(SMALL_WORLD_AUTO_DEFAULT_REFRESH_MINUTES),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/modules/small_world"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        if not _is_small_world_module_available(profile):
            raise HTTPException(status_code=400, detail="仅化神及以上角色可用")
        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")
        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None
        feature_key = biz_small_world_game.SMALL_WORLD_AUTO_FEATURE_KEY

        if enabled != "1":
            existing_task = storage.get_companion_auto_task(
                profile.id,
                resolved_chat_id,
                feature_key,
            )
            awaited_command = _resolve_small_world_awaited_action_command(
                str((existing_task or {}).get("workflow_state") or "")
            )
            storage.disable_companion_auto_task(
                profile.id,
                resolved_chat_id,
                feature_key,
                last_error="用户手动关闭自动小世界。",
            )
            for command_text in (
                biz_small_world_game.SMALL_WORLD_PANEL_COMMAND,
                biz_small_world_game.SMALL_WORLD_COLLECT_COMMAND,
                biz_small_world_game.SMALL_WORLD_MANIFEST_COMMAND,
                biz_small_world_game.SMALL_WORLD_PREACH_COMMAND,
                awaited_command,
            ):
                if not command_text:
                    continue
                storage.cancel_pending_outgoing_commands(
                    profile.id,
                    resolved_chat_id,
                    text=command_text,
                    thread_id=resolved_thread_id,
                    require_exact_thread=True,
                )
            return RedirectResponse(url=redirect_to, status_code=303)

        try:
            threshold = float(str(collect_threshold or "0").strip() or 0)
        except (TypeError, ValueError):
            threshold = biz_small_world_game.SMALL_WORLD_DEFAULT_COLLECT_THRESHOLD
        strategy = biz_small_world_game.pack_auto_strategy(
            collect_enabled=collect_enabled == "1",
            collect_threshold=threshold,
            quench_after_collect_enabled=quench_after_collect_enabled == "1",
            manifest_enabled=manifest_enabled == "1",
            preach_enabled=preach_enabled == "1",
            refresh_interval_seconds=max(int(refresh_interval_minutes or 0), 5) * 60,
        )
        storage.disable_companion_auto_task(
            profile.id,
            resolved_chat_id,
            biz_small_world_game.SMALL_WORLD_PREACH_AUTO_FEATURE_KEY,
            last_error="自动小世界已开启，自动神迹布道已关闭。",
        )
        storage.cancel_pending_outgoing_commands(
            profile.id,
            resolved_chat_id,
            text=biz_small_world_game.SMALL_WORLD_PREACH_COMMAND,
            thread_id=resolved_thread_id,
            require_exact_thread=True,
        )
        storage.upsert_companion_auto_task(
            profile_id=profile.id,
            chat_id=resolved_chat_id,
            feature_key=feature_key,
            enabled=True,
            strategy=strategy,
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            next_run_at=biz_fanren_game.time.time(),
            last_error="",
        )
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/small-world/preach-auto")
    async def runtime_toggle_small_world_preach_auto(
        request: Request,
        chat_id: str = Form(...),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/modules/small_world"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        if not _is_small_world_module_available(profile):
            raise HTTPException(status_code=400, detail="仅化神及以上角色可用")
        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")
        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None
        feature_key = biz_small_world_game.SMALL_WORLD_PREACH_AUTO_FEATURE_KEY

        full_auto_task = storage.get_companion_auto_task(
            profile.id,
            resolved_chat_id,
            biz_small_world_game.SMALL_WORLD_AUTO_FEATURE_KEY,
        )
        existing_task = storage.get_companion_auto_task(
            profile.id,
            resolved_chat_id,
            feature_key,
        )
        if full_auto_task and bool(full_auto_task.get("enabled")):
            storage.disable_companion_auto_task(
                profile.id,
                resolved_chat_id,
                feature_key,
                last_error="自动小世界运行中，自动神迹布道已关闭。",
            )
            storage.cancel_pending_outgoing_commands(
                profile.id,
                resolved_chat_id,
                text=biz_small_world_game.SMALL_WORLD_PREACH_COMMAND,
                thread_id=resolved_thread_id,
                require_exact_thread=True,
            )
            return RedirectResponse(url=redirect_to, status_code=303)

        if existing_task and bool(existing_task.get("enabled")):
            storage.disable_companion_auto_task(
                profile.id,
                resolved_chat_id,
                feature_key,
                last_error="用户手动关闭自动神迹布道。",
            )
            storage.cancel_pending_outgoing_commands(
                profile.id,
                resolved_chat_id,
                text=biz_small_world_game.SMALL_WORLD_PREACH_COMMAND,
                thread_id=resolved_thread_id,
                require_exact_thread=True,
            )
            return RedirectResponse(url=redirect_to, status_code=303)

        now_ts = biz_fanren_game.time.time()
        latest_command = storage.get_latest_outgoing_command(
            resolved_chat_id,
            profile_id=profile.id,
            text=biz_small_world_game.SMALL_WORLD_PREACH_COMMAND,
            thread_id=resolved_thread_id,
        )
        latest_status = str((latest_command or {}).get("status") or "").strip()
        command_waiting = latest_status in {
            "pending",
            "sending",
            "awaiting_confirm",
            "needs_manual_confirm",
        }
        if not command_waiting:
            storage.enqueue_outgoing_command(
                profile_id=profile.id,
                chat_id=resolved_chat_id,
                text=biz_small_world_game.SMALL_WORLD_PREACH_COMMAND,
                thread_id=resolved_thread_id,
                chat_type=chat_type,
                bot_username=bot_username,
            )
        storage.upsert_companion_auto_task(
            profile_id=profile.id,
            chat_id=resolved_chat_id,
            feature_key=feature_key,
            enabled=True,
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            next_run_at=now_ts + 10,
            last_run_at=now_ts,
            last_error=(
                "等待最新神迹布道回包更新冷却。"
                if not command_waiting
                else "已有神迹布道待确认，等待回包更新冷却。"
            ),
        )
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/commands/companion-auto")
    async def runtime_toggle_companion_auto(
        request: Request,
        chat_id: str = Form(...),
        feature_key: str = Form(...),
        thread_id: Optional[str] = Form(None),
        heart_round1: str = Form("稳"),
        heart_round2: str = Form("稳"),
        heart_round3: str = Form("稳"),
        voyage_strategy: str = Form("均衡"),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/modules/other"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect

        normalized_chat_id = str(chat_id or "").strip()
        normalized_feature_key = str(feature_key or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")

        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None
        if normalized_feature_key == "heart_tribulation":
            normalized_rounds = [
                str(heart_round1 or "稳").strip() or "稳",
                str(heart_round2 or "稳").strip() or "稳",
                str(heart_round3 or "稳").strip() or "稳",
            ]
            if any(
                value not in COMPANION_HEART_TRIBULATION_ACTIONS
                for value in normalized_rounds
            ):
                raise HTTPException(status_code=400, detail="Invalid heart tribulation action")
            existing_heart_task = storage.get_companion_heart_tribulation_task(
                profile.id,
                resolved_chat_id,
                thread_id=resolved_thread_id,
            )
            if existing_heart_task and bool(existing_heart_task.get("enabled")):
                stopped_task = storage.disable_companion_heart_tribulation_task(
                    profile.id,
                    resolved_chat_id,
                    thread_id=resolved_thread_id,
                    last_error="用户手动关闭自动共历心劫。",
                )
                storage.append_companion_heart_tribulation_log(
                    profile_id=profile.id,
                    chat_id=resolved_chat_id,
                    thread_id=resolved_thread_id,
                    task_id=int((stopped_task or existing_heart_task or {}).get("id") or 0),
                    run_id=str((existing_heart_task or {}).get("run_id") or ""),
                    step="stopped",
                    event_type="manual_stop",
                    text="用户关闭自动共历心劫",
                    detail={
                        "thread_id": resolved_thread_id,
                        "chat_type": chat_type,
                        "bot_username": bot_username,
                    },
                )
                for command_text in [
                    ".我的侍妾",
                    ".共历心劫",
                    *[f".{action}" for action in COMPANION_HEART_TRIBULATION_ACTIONS],
                ]:
                    storage.cancel_pending_outgoing_commands(
                        profile.id,
                        resolved_chat_id,
                        text=command_text,
                        thread_id=resolved_thread_id,
                        require_exact_thread=True,
                    )
                return RedirectResponse(url=redirect_to, status_code=303)

            payload = read_cached_external_payload(storage, profile.id)
            now_ts = biz_fanren_game.time.time()
            next_run_at = _cooldown_target_timestamp(
                _resolve_latest_companion_payload(payload).get(
                    "last_companion_heart_tribulation_time"
                ),
                10,
            )
            task = storage.upsert_companion_heart_tribulation_task(
                profile_id=profile.id,
                chat_id=resolved_chat_id,
                enabled=True,
                thread_id=resolved_thread_id,
                chat_type=chat_type,
                bot_username=bot_username,
                run_id="",
                workflow_state="idle",
                next_run_at=float(next_run_at or now_ts),
                step_deadline_at=0,
                last_run_at=0,
                matched_bot_id=0,
                anchor_command_msg_id=0,
                anchor_bot_msg_id=0,
                tribulation_command_msg_id=0,
                tribulation_msg_id=0,
                panel_reply_msg_id=0,
                round1_reply=normalized_rounds[0],
                round2_reply=normalized_rounds[1],
                round3_reply=normalized_rounds[2],
                last_action_round_sent=0,
                last_tribulation_command_at=0,
                last_progress_at=0,
                last_progress_fingerprint="",
                last_stable_sent_at=0,
                last_error="",
                retry_count=0,
            )
            storage.append_companion_heart_tribulation_log(
                profile_id=profile.id,
                chat_id=resolved_chat_id,
                thread_id=resolved_thread_id,
                task_id=int(task.get("id") or 0),
                run_id="",
                step="configured",
                event_type="manual_start",
                text="用户开启自动共历心劫",
                detail={
                    "next_run_at": float(next_run_at or now_ts),
                    "round1": normalized_rounds[0],
                    "round2": normalized_rounds[1],
                    "round3": normalized_rounds[2],
                    "chat_type": chat_type,
                    "bot_username": bot_username,
                },
            )
            return RedirectResponse(url=redirect_to, status_code=303)

        feature = COMPANION_AUTO_FEATURES.get(normalized_feature_key)
        if not feature:
            raise HTTPException(
                status_code=400, detail="Invalid companion auto feature"
            )

        existing_task = storage.get_companion_auto_task(
            profile.id, resolved_chat_id, normalized_feature_key
        )

        if existing_task and bool(existing_task.get("enabled")):
            storage.disable_companion_auto_task(
                profile.id, resolved_chat_id, normalized_feature_key
            )
            if normalized_feature_key == "companion_voyage":
                existing_strategy = _normalize_companion_voyage_strategy(
                    existing_task.get("strategy")
                )
                selected_strategy = _normalize_companion_voyage_strategy(
                    voyage_strategy
                )
                for command_text in {
                    COMPANION_VOYAGE_STATUS_COMMAND,
                    COMPANION_VOYAGE_RETURN_COMMAND,
                    f".侍妾远航 {existing_strategy}",
                    f".侍妾远航 {selected_strategy}",
                }:
                    storage.cancel_pending_outgoing_commands(
                        profile.id,
                        resolved_chat_id,
                        text=command_text,
                        thread_id=resolved_thread_id,
                        require_exact_thread=True,
                    )
            else:
                storage.cancel_pending_outgoing_commands(
                    profile.id,
                    resolved_chat_id,
                    text=str(feature.get("command") or ""),
                )
            return RedirectResponse(url=redirect_to, status_code=303)

        if normalized_feature_key == "companion_voyage":
            normalized_strategy = _normalize_companion_voyage_strategy(voyage_strategy)
            voyage_reply = _get_latest_command_reply_for_profile(
                profile,
                storage.get_primary_chat_binding(profile.id)
                if not resolved_chat_id
                else type("ChatRef", (), {
                    "chat_id": resolved_chat_id,
                    "thread_id": resolved_thread_id,
                    "telegram_user_id": profile.telegram_user_id,
                })(),
                COMPANION_VOYAGE_STATUS_COMMAND,
            )
            voyage_state = _build_companion_voyage_state(voyage_reply)
            target_ts = float(voyage_state.get("target_ts") or 0)
            next_run_at = target_ts + 10 if target_ts > biz_fanren_game.time.time() else biz_fanren_game.time.time() + 10
            storage.upsert_companion_auto_task(
                profile_id=profile.id,
                chat_id=resolved_chat_id,
                feature_key=normalized_feature_key,
                enabled=True,
                strategy=normalized_strategy,
                thread_id=resolved_thread_id,
                chat_type=chat_type,
                bot_username=bot_username,
                next_run_at=next_run_at,
                last_error="",
            )
            return RedirectResponse(url=redirect_to, status_code=303)

        payload = read_cached_external_payload(storage, profile.id)
        next_run_at = _resolve_companion_auto_next_run_at(
            payload, normalized_feature_key
        )
        if next_run_at is None:
            storage.upsert_companion_auto_task(
                profile_id=profile.id,
                chat_id=resolved_chat_id,
                feature_key=normalized_feature_key,
                enabled=False,
                thread_id=resolved_thread_id,
                chat_type=chat_type,
                bot_username=bot_username,
                next_run_at=0,
                last_error=f"最新 payload 缺少{feature.get('label') or normalized_feature_key}冷却字段，已停止自动。",
            )
            storage.cancel_pending_outgoing_commands(
                profile.id,
                resolved_chat_id,
                text=str(feature.get("command") or ""),
            )
            return RedirectResponse(url=redirect_to, status_code=303)
        storage.upsert_companion_auto_task(
            profile_id=profile.id,
            chat_id=resolved_chat_id,
            feature_key=normalized_feature_key,
            enabled=True,
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            next_run_at=next_run_at,
            last_error="",
        )
        if next_run_at <= biz_fanren_game.time.time():
            now_ts = biz_fanren_game.time.time()
            storage.enqueue_outgoing_command(
                profile_id=profile.id,
                chat_id=resolved_chat_id,
                text=str(feature.get("command") or "").strip(),
                thread_id=resolved_thread_id,
                chat_type=chat_type,
                bot_username=bot_username,
                delay_seconds=0,
            )
            storage.upsert_companion_auto_task(
                profile_id=profile.id,
                chat_id=resolved_chat_id,
                feature_key=normalized_feature_key,
                enabled=True,
                thread_id=resolved_thread_id,
                chat_type=chat_type,
                bot_username=bot_username,
                next_run_at=now_ts + COMPANION_AUTO_MANUAL_DELAY_SECONDS,
                last_run_at=now_ts,
                last_error="",
            )
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/artifact/touch-auto")
    async def runtime_toggle_artifact_touch_auto(
        request: Request,
        chat_id: str = Form(...),
        command_text: str = Form(".抚摸法宝"),
        interval_minutes: int = Form(360),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/modules/artifact"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect

        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")
        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None
        normalized_command = _normalize_artifact_touch_command(command_text)
        interval_seconds = _normalize_artifact_touch_interval(
            int(interval_minutes or 0) * 60
        )

        existing_task = storage.get_companion_auto_task(
            profile.id, resolved_chat_id, ARTIFACT_TOUCH_FEATURE_KEY
        )
        if existing_task and bool(existing_task.get("enabled")):
            existing_command, _existing_interval = _unpack_artifact_touch_strategy(
                existing_task.get("strategy") or ""
            )
            storage.disable_companion_auto_task(
                profile.id,
                resolved_chat_id,
                ARTIFACT_TOUCH_FEATURE_KEY,
                last_error="用户手动关闭自动抚摸法宝。",
            )
            storage.cancel_pending_outgoing_commands(
                profile.id,
                resolved_chat_id,
                text=existing_command,
                thread_id=resolved_thread_id,
                require_exact_thread=True,
            )
            return RedirectResponse(url=redirect_to, status_code=303)

        now_ts = biz_fanren_game.time.time()
        task = storage.upsert_companion_auto_task(
            profile_id=profile.id,
            chat_id=resolved_chat_id,
            feature_key=ARTIFACT_TOUCH_FEATURE_KEY,
            enabled=True,
            strategy=_pack_artifact_touch_strategy(
                normalized_command, interval_seconds
            ),
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            next_run_at=now_ts + ARTIFACT_TOUCH_REPLY_WAIT_SECONDS,
            last_run_at=now_ts,
            last_error="已发送抚摸法宝，等待bot回包。",
        )
        storage.enqueue_outgoing_command(
            profile_id=profile.id,
            chat_id=resolved_chat_id,
            text=normalized_command,
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
        )
        if task.get("id"):
            storage.update_companion_auto_task(
                int(task["id"]),
                workflow_state=ARTIFACT_TOUCH_AWAIT_REPLY_STATE,
                last_error="已发送抚摸法宝，等待bot回包。",
            )
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/artifact/trial-auto")
    async def runtime_toggle_artifact_trial_auto(
        request: Request,
        chat_id: str = Form(...),
        artifact_name: str = Form(ARTIFACT_TRIAL_DEFAULT_ARTIFACT_NAME),
        trial_route: str = Form("静修"),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/modules/other"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect

        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")
        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None
        normalized_artifact_name = _normalize_artifact_trial_artifact_name(artifact_name)
        normalized_route = _normalize_artifact_trial_route(trial_route)
        command_text = _build_artifact_trial_command(
            normalized_artifact_name,
            normalized_route,
        )

        existing_task = storage.get_companion_auto_task(
            profile.id, resolved_chat_id, ARTIFACT_TRIAL_FEATURE_KEY
        )
        if existing_task and bool(existing_task.get("enabled")):
            existing_artifact_name, existing_route = _unpack_artifact_trial_strategy(
                existing_task.get("strategy") or ""
            )
            storage.disable_companion_auto_task(
                profile.id,
                resolved_chat_id,
                ARTIFACT_TRIAL_FEATURE_KEY,
                last_error="用户手动关闭自动器灵试炼。",
            )
            storage.cancel_pending_outgoing_commands(
                profile.id,
                resolved_chat_id,
                text=_build_artifact_trial_command(existing_artifact_name, existing_route),
                thread_id=resolved_thread_id,
                require_exact_thread=True,
            )
            return RedirectResponse(url=redirect_to, status_code=303)

        payload = _refresh_cultivator_payload(profile.id)
        resources = build_artifact_trial_resource_state(
            payload if isinstance(payload, dict) else {},
            storage.get_game_items(),
        )
        strategy = _pack_artifact_trial_strategy(
            normalized_artifact_name,
            normalized_route,
        )
        if not resources.get("ok"):
            task = storage.upsert_companion_auto_task(
                profile_id=profile.id,
                chat_id=resolved_chat_id,
                feature_key=ARTIFACT_TRIAL_FEATURE_KEY,
                enabled=False,
                strategy=strategy,
                thread_id=resolved_thread_id,
                chat_type=chat_type,
                bot_username=bot_username,
                next_run_at=0,
                last_error=str(resources.get("error_text") or "资源不足。"),
            )
            if task.get("id"):
                storage.update_companion_auto_task(
                    int(task["id"]),
                    workflow_state=ARTIFACT_TRIAL_STOPPED_RESOURCES_STATE,
                )
            return RedirectResponse(url=redirect_to, status_code=303)

        now_ts = biz_fanren_game.time.time()
        task = storage.upsert_companion_auto_task(
            profile_id=profile.id,
            chat_id=resolved_chat_id,
            feature_key=ARTIFACT_TRIAL_FEATURE_KEY,
            enabled=True,
            strategy=strategy,
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            next_run_at=now_ts + ARTIFACT_TRIAL_REPLY_WAIT_SECONDS,
            last_run_at=now_ts,
            last_error="已发送器灵试炼，等待bot回包。",
        )
        storage.enqueue_outgoing_command(
            profile_id=profile.id,
            chat_id=resolved_chat_id,
            text=command_text,
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
        )
        if task.get("id"):
            storage.update_companion_auto_task(
                int(task["id"]),
                workflow_state=ARTIFACT_TRIAL_AWAIT_REPLY_STATE,
                last_error="已发送器灵试炼，等待bot回包。",
            )
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/commands/wild-experience-auto")
    async def runtime_toggle_wild_experience_auto(
        request: Request,
        chat_id: str = Form(...),
        strategy: str = Form("均衡"),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("fanrenxiuxian_bot"),
        redirect_to: str = Form("/modules/other"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect

        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Chat ID not configured")
        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None
        normalized_strategy = _normalize_wild_experience_strategy(strategy)
        existing_task = storage.get_companion_auto_task(
            profile.id, resolved_chat_id, "wild_experience"
        )
        if existing_task and bool(existing_task.get("enabled")):
            storage.disable_companion_auto_task(
                profile.id, resolved_chat_id, "wild_experience"
            )
            storage.cancel_pending_outgoing_commands(
                profile.id,
                resolved_chat_id,
                text=f".野外历练 {str(existing_task.get('strategy') or normalized_strategy).strip() or normalized_strategy}",
            )
            return RedirectResponse(url=redirect_to, status_code=303)

        payload = read_cached_external_payload(storage, profile.id)
        next_run_at = _resolve_auto_feature_next_run_at(
            payload if isinstance(payload, dict) else {}, "wild_experience"
        )
        if next_run_at is None:
            storage.upsert_companion_auto_task(
                profile_id=profile.id,
                chat_id=resolved_chat_id,
                feature_key="wild_experience",
                enabled=False,
                strategy=normalized_strategy,
                thread_id=resolved_thread_id,
                chat_type=chat_type,
                bot_username=bot_username,
                next_run_at=0,
                last_error="最新 payload 缺少野外历练冷却字段，已停止自动。",
            )
            return RedirectResponse(url=redirect_to, status_code=303)

        storage.upsert_companion_auto_task(
            profile_id=profile.id,
            chat_id=resolved_chat_id,
            feature_key="wild_experience",
            enabled=True,
            strategy=normalized_strategy,
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            next_run_at=next_run_at,
            last_error="",
        )
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/sect/xinggong-starboard-auto")
    async def runtime_toggle_xinggong_starboard_auto(
        request: Request,
        chat_id: str = Form(...),
        target_star: str = Form(XINGGONG_STARBOARD_DEFAULT_STAR),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("luoxueyao_bot"),
        redirect_to: str = Form("/modules/sect"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect
        if str(profile.sect_name or "").strip() != "星宫":
            raise HTTPException(status_code=400, detail="仅星宫角色可用")

        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Sect chat is not configured")
        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None
        normalized_target = _normalize_xinggong_starboard_target(target_star)

        existing_task = storage.get_companion_auto_task(
            profile.id, resolved_chat_id, XINGGONG_STARBOARD_FEATURE_KEY
        )
        if existing_task and bool(existing_task.get("enabled")):
            existing_target = _normalize_xinggong_starboard_target(
                existing_task.get("strategy")
            )
            storage.disable_companion_auto_task(
                profile.id,
                resolved_chat_id,
                XINGGONG_STARBOARD_FEATURE_KEY,
                last_error="用户手动关闭自动星辰采集。",
            )
            payload = read_cached_external_payload(storage, profile.id)
            external_account = storage.get_external_account(
                profile.id,
                ASC_PROVIDER,
            ) or {}
            updated_payload = xinggong_miniapp.cancel_xinggong_starboard_request(
                payload,
                reason="用户手动关闭自动星辰采集。",
            )
            storage.upsert_external_account(
                profile.id,
                ASC_PROVIDER,
                str(
                    external_account.get("telegram_user_id")
                    or profile.telegram_user_id
                    or ""
                ),
                str(
                    external_account.get("telegram_username")
                    or profile.telegram_username
                    or ""
                ),
                str(external_account.get("status") or "connected"),
                str(external_account.get("cookie_text") or ""),
                updated_payload,
                str(external_account.get("api_token") or ""),
            )
            star_platform = _coerce_json_dict((payload or {}).get("star_platform"))
            slot_count = max(int(star_platform.get("size") or 0), 8)
            storage.cancel_pending_outgoing_commands(
                profile.id,
                resolved_chat_id,
                text=xinggong_miniapp.XINGGONG_STARBOARD_COMMAND,
                thread_id=resolved_thread_id,
                require_exact_thread=True,
            )
            storage.cancel_pending_outgoing_commands(
                profile.id,
                resolved_chat_id,
                text=".安抚星辰",
                thread_id=resolved_thread_id,
                require_exact_thread=True,
            )
            for command_text in {
                ".收集精华",
                f".牵引星辰 {existing_target}",
                f".牵引星辰 {normalized_target}",
            }:
                storage.cancel_pending_outgoing_commands(
                    profile.id,
                    resolved_chat_id,
                    text=command_text,
                    thread_id=resolved_thread_id,
                    require_exact_thread=True,
                )
            for slot in range(1, slot_count + 1):
                for command_text in {
                    f".安抚星辰 {slot}",
                    f".收集精华 {slot}",
                    f".牵引星辰 {slot} {existing_target}",
                    f".牵引星辰 {slot} {normalized_target}",
                }:
                    storage.cancel_pending_outgoing_commands(
                        profile.id,
                        resolved_chat_id,
                        text=command_text,
                        thread_id=resolved_thread_id,
                        require_exact_thread=True,
                    )
            return RedirectResponse(url=redirect_to, status_code=303)

        now_ts = biz_fanren_game.time.time()
        storage.upsert_companion_auto_task(
            profile_id=profile.id,
            chat_id=resolved_chat_id,
            feature_key=XINGGONG_STARBOARD_FEATURE_KEY,
            enabled=True,
            strategy=normalized_target,
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            next_run_at=now_ts + 10,
            last_run_at=0,
            last_error="自动星辰采集已开启，等待公共洞府入口检查。",
        )
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/sect/wanling-roam-auto")
    async def runtime_toggle_wanling_roam_auto(
        request: Request,
        chat_id: str = Form(...),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("luoxueyao_bot"),
        redirect_to: str = Form("/modules/sect"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect
        if str(profile.sect_name or "").strip() != "万灵宗":
            raise HTTPException(status_code=400, detail="仅万灵宗角色可用")

        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Sect chat is not configured")
        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None

        existing_task = storage.get_companion_auto_task(
            profile.id, resolved_chat_id, WANLING_ROAM_FEATURE_KEY
        )
        if existing_task and bool(existing_task.get("enabled")):
            storage.disable_companion_auto_task(
                profile.id,
                resolved_chat_id,
                WANLING_ROAM_FEATURE_KEY,
                last_error="用户手动关闭自动一键放养。",
            )
            for command_text in build_wanling_roam_cancel_commands(
                existing_task.get("strategy")
            ):
                storage.cancel_pending_outgoing_commands(
                    profile.id,
                    resolved_chat_id,
                    text=command_text,
                    thread_id=resolved_thread_id,
                    require_exact_thread=True,
                )
            return RedirectResponse(url=redirect_to, status_code=303)

        payload = read_cached_external_payload(storage, profile.id)
        wanling_state = _build_wanling_roam_state(payload if isinstance(payload, dict) else {})
        existing_strategy = str((existing_task or {}).get("strategy") or "")
        if not wanling_state.get("available"):
            storage.upsert_companion_auto_task(
                profile_id=profile.id,
                chat_id=resolved_chat_id,
                feature_key=WANLING_ROAM_FEATURE_KEY,
                enabled=False,
                strategy=existing_strategy,
                thread_id=resolved_thread_id,
                chat_type=chat_type,
                bot_username=bot_username,
                next_run_at=0,
                last_error="最新 payload 缺少灵兽放养数据，已停止自动。",
            )
            return RedirectResponse(url=redirect_to, status_code=303)

        now_ts = biz_fanren_game.time.time()
        next_finish_ts = float(wanling_state.get("next_finish_ts") or 0)
        next_run_at = next_finish_ts + 10 if next_finish_ts > now_ts else now_ts + 10
        storage.upsert_companion_auto_task(
            profile_id=profile.id,
            chat_id=resolved_chat_id,
            feature_key=WANLING_ROAM_FEATURE_KEY,
            enabled=True,
            strategy=existing_strategy,
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
            next_run_at=next_run_at,
            last_run_at=0,
            last_error="",
        )
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/sect/wanling-roam-config")
    async def runtime_save_wanling_roam_config(
        request: Request,
        chat_id: str = Form(...),
        thread_id: Optional[str] = Form(None),
        chat_type: str = Form("group"),
        bot_username: str = Form("luoxueyao_bot"),
        redirect_to: str = Form("/modules/sect"),
    ) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect
        if str(profile.sect_name or "").strip() != "万灵宗":
            raise HTTPException(status_code=400, detail="仅万灵宗角色可用")

        normalized_chat_id = str(chat_id or "").strip()
        if not normalized_chat_id:
            raise HTTPException(status_code=400, detail="Sect chat is not configured")
        resolved_chat_id = int(normalized_chat_id)
        resolved_thread_id = int(thread_id) if thread_id and thread_id.isdigit() else None
        form_data = await request.form()
        payload = read_cached_external_payload(storage, profile.id)
        available_names = list_spirit_beast_names(payload if isinstance(payload, dict) else {})
        available_set = set(available_names)
        requested_names = normalize_wanling_roam_beast_names(
            form_data.getlist("beast_names")
        )
        selected_names = [name for name in requested_names if name in available_set]
        dropped_count = len(requested_names) - len(selected_names)
        strategy = pack_wanling_roam_strategy(selected_names)
        save_message = (
            f"已忽略 {dropped_count} 个不在当前灵兽列表中的名字，请先同步 .我的灵兽。"
            if dropped_count
            else ""
        )
        existing_task = storage.get_companion_auto_task(
            profile.id, resolved_chat_id, WANLING_ROAM_FEATURE_KEY
        )
        if existing_task:
            storage.update_companion_auto_task(
                int(existing_task["id"]),
                strategy=strategy,
                last_error=save_message,
            )
        else:
            storage.upsert_companion_auto_task(
                profile_id=profile.id,
                chat_id=resolved_chat_id,
                feature_key=WANLING_ROAM_FEATURE_KEY,
                enabled=False,
                strategy=strategy,
                thread_id=resolved_thread_id,
                chat_type=chat_type,
                bot_username=bot_username,
                next_run_at=0,
                last_run_at=0,
                last_error=save_message,
            )
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/sect/action")
    async def runtime_send_sect_action(request: Request) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect
        form_data = await request.form()
        sect_name = str(form_data.get("sect_name") or "").strip()
        action_key = str(form_data.get("action_key") or "").strip()
        redirect_to = str(form_data.get("redirect_to") or "/modules/sect").strip()
        chat_id_text = str(form_data.get("chat_id") or "").strip()
        if not sect_name or not action_key:
            raise HTTPException(status_code=400, detail="Sect action is required")
        if not chat_id_text:
            raise HTTPException(status_code=400, detail="Sect chat is not configured")

        feature = _get_sect_feature_by_name(sect_name)
        if not feature:
            raise HTTPException(status_code=404, detail="Sect feature not found")
        current_feature = _resolve_current_sect_feature(profile)
        if not current_feature or current_feature["name"] != feature["name"]:
            raise HTTPException(status_code=400, detail="当前角色不是该宗门")
        action = next(
            (
                item
                for item in feature.get("actions") or []
                if str(item.get("key") or "").strip() == action_key
            ),
            None,
        )
        if not action:
            raise HTTPException(status_code=404, detail="Sect action not found")

        if feature["name"] == "万灵宗" and any(
            str(field.get("name") or "").strip() == "beast"
            for field in action.get("fields") or []
        ):
            payload = read_cached_external_payload(storage, profile.id)
            available_names = list_spirit_beast_names(
                payload if isinstance(payload, dict) else {}
            )
            selected_names = normalize_wanling_roam_beast_names(
                [str(form_data.get("beast") or "").strip()]
            )
            if not selected_names or selected_names[0] not in set(available_names):
                raise HTTPException(
                    status_code=400,
                    detail="灵兽名不在当前“我的灵兽”列表中，请先同步后再选择。",
                )

        thread_id_text = str(form_data.get("thread_id") or "").strip()
        chat_type = str(form_data.get("chat_type") or "group").strip() or "group"
        bot_username = (
            str(form_data.get("bot_username") or "").strip()
            or biz_sect_game.SECT_BOT_USERNAME
        )
        resolved_chat_id = int(chat_id_text)
        resolved_thread_id = int(thread_id_text) if thread_id_text.isdigit() else None
        if feature["name"] == "星宫" and action_key == "starboard":
            payload = read_cached_external_payload(storage, profile.id)
            external_account = storage.get_external_account(
                profile.id,
                ASC_PROVIDER,
            ) or {}
            updated_payload = xinggong_miniapp.queue_xinggong_starboard_request(
                payload,
                chat_id=resolved_chat_id,
                thread_id=resolved_thread_id,
                chat_type=chat_type,
                bot_username=bot_username,
                run_mode="snapshot",
            )
            storage.upsert_external_account(
                profile.id,
                ASC_PROVIDER,
                str(
                    external_account.get("telegram_user_id")
                    or profile.telegram_user_id
                    or ""
                ),
                str(
                    external_account.get("telegram_username")
                    or profile.telegram_username
                    or ""
                ),
                str(external_account.get("status") or "connected"),
                str(external_account.get("cookie_text") or ""),
                updated_payload,
                str(external_account.get("api_token") or ""),
            )
            storage.cancel_pending_outgoing_commands(
                profile.id,
                resolved_chat_id,
                text=xinggong_miniapp.XINGGONG_STARBOARD_COMMAND,
                thread_id=resolved_thread_id,
                require_exact_thread=True,
            )
            return RedirectResponse(
                url=redirect_to or "/modules/sect",
                status_code=303,
            )

        command_text = _build_sect_action_command(action, form_data)
        storage.enqueue_outgoing_command(
            profile_id=profile.id,
            chat_id=resolved_chat_id,
            text=command_text,
            thread_id=resolved_thread_id,
            chat_type=chat_type,
            bot_username=bot_username,
        )
        return RedirectResponse(url=redirect_to or "/modules/sect", status_code=303)

    @application.post("/runtime/sect/yinluo-batch")
    async def runtime_start_yinluo_batch(request: Request) -> RedirectResponse:
        profile = _get_request_profile(request)
        if not profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        expired_redirect = _ensure_external_session_active(profile)
        if expired_redirect:
            return expired_redirect
        form_data = await request.form()
        batch_mode = str(form_data.get("batch_mode") or "").strip().lower()
        redirect_to = str(form_data.get("redirect_to") or "/modules/sect").strip()
        chat_id_text = str(form_data.get("chat_id") or "").strip()
        if not chat_id_text:
            raise HTTPException(status_code=400, detail="Sect chat is not configured")
        thread_id_text = str(form_data.get("thread_id") or "").strip()
        chat_type = str(form_data.get("chat_type") or "group").strip() or "group"
        bot_username = (
            str(form_data.get("bot_username") or "").strip()
            or biz_sect_game.SECT_BOT_USERNAME
        )

        if batch_mode in {"soothe", "collect"}:
            command_text = (
                ".一键安抚幡灵" if batch_mode == "soothe" else ".一键收取精华"
            )
            storage.enqueue_outgoing_command(
                profile_id=profile.id,
                chat_id=int(chat_id_text),
                text=command_text,
                thread_id=int(thread_id_text) if thread_id_text.isdigit() else None,
                chat_type=chat_type,
                bot_username=bot_username,
            )
            return RedirectResponse(url=redirect_to or "/modules/sect", status_code=303)

        if batch_mode != "imprison":
            raise HTTPException(status_code=400, detail="Invalid yinluo batch mode")

        commands = []
        for key in sorted(form_data.keys()):
            if not key.startswith("slot_soul_"):
                continue
            slot_index_text = key.split("slot_soul_", 1)[1].strip()
            if not slot_index_text.isdigit():
                continue
            slot_state = str(
                form_data.get(f"slot_state_{slot_index_text}") or ""
            ).strip()
            soul_name = str(form_data.get(key) or "").strip()
            if slot_state != "空闲" or not soul_name:
                continue
            commands.append(f".囚禁魂魄 {int(slot_index_text)} {soul_name}")
        if not commands:
            raise HTTPException(
                status_code=400, detail="No available yinluo imprison commands"
            )

        db = CompatDb(storage)
        try:
            biz_sect_game.ensure_tables(db)
            biz_sect_game.set_enabled(
                db,
                int(chat_id_text),
                True,
                profile_id=profile.id,
            )
            biz_sect_game.start_yinluo_batch(
                db,
                int(chat_id_text),
                "imprison",
                commands,
                profile_id=profile.id,
            )
        finally:
            db.close()
        return RedirectResponse(url=redirect_to or "/modules/sect", status_code=303)

    @application.post("/runtime/cultivation/toggle")
    async def toggle_cultivation_runtime(
        request: Request, chat_id: int = Form(...), enabled: str = Form(...)
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_fanren_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            binding = (
                storage.get_chat_binding(active_profile.id, chat_id)
                if active_profile
                else None
            )
            if enabled == "1":
                if active_profile:
                    sync_cultivation_session(storage, active_profile.id, chat_id, db)
                biz_fanren_game.update_session(
                    db,
                    chat_id,
                    profile_id=active_profile.id if active_profile else None,
                    thread_id=getattr(binding, "thread_id", None),
                )
                biz_fanren_game.set_enabled(
                    db,
                    chat_id,
                    True,
                    reset_failure=True,
                    profile_id=active_profile.id if active_profile else None,
                )
            else:
                biz_fanren_game.set_enabled(
                    db,
                    chat_id,
                    False,
                    profile_id=active_profile.id if active_profile else None,
                )
            session = biz_fanren_game.get_session(
                db, chat_id, profile_id=active_profile.id if active_profile else None
            )
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Cultivation session not found")
        return RedirectResponse(url="/modules/cultivation", status_code=303)

    @application.post("/runtime/cultivation/mode")
    async def set_cultivation_mode(
        request: Request, chat_id: int = Form(...), mode: str = Form(...)
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_fanren_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            current_session = biz_fanren_game.get_session(
                db, chat_id, profile_id=active_profile.id if active_profile else None
            )
            preserve_next_check_time = 0
            if (
                (mode or "").strip().lower() == "deep"
                and current_session
                and float(current_session.get("next_check_time") or 0)
                > biz_fanren_game.time.time()
                and (
                    str(current_session.get("next_check_source") or "").strip()
                    == "deep_seclusion_end_time"
                    or (current_session.get("last_event") or "")
                    in biz_fanren_game.FANREN_DEEP_PENDING_EVENTS
                )
            ):
                preserve_next_check_time = float(
                    current_session.get("next_check_time") or 0
                )
            biz_fanren_game.set_mode(
                db,
                chat_id,
                mode,
                preserve_next_check_time=preserve_next_check_time,
                profile_id=active_profile.id if active_profile else None,
            )
            if active_profile:
                sync_cultivation_session(storage, active_profile.id, chat_id, db)
            biz_fanren_game.update_session(
                db,
                chat_id,
                profile_id=active_profile.id if active_profile else None,
                last_summary=f"已切换为{'深度闭关' if mode == 'deep' else '普通闭关'}，将按接口冷却时间自动调度。",
            )
            session = biz_fanren_game.get_session(
                db, chat_id, profile_id=active_profile.id if active_profile else None
            )
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Cultivation session not found")
        return RedirectResponse(url="/modules/cultivation", status_code=303)

    @application.post("/runtime/cultivation/delete-command-toggle")
    async def toggle_cultivation_delete_command(
        request: Request, chat_id: int = Form(...), enabled: str = Form(...)
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_fanren_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            biz_fanren_game.set_delete_normal_command_message(
                db,
                chat_id,
                enabled == "1",
                profile_id=active_profile.id if active_profile else None,
            )
            session = biz_fanren_game.get_session(
                db, chat_id, profile_id=active_profile.id if active_profile else None
            )
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Cultivation session not found")
        return RedirectResponse(url="/modules/cultivation", status_code=303)

    @application.post("/runtime/cultivation/jiyin-toggle")
    async def toggle_cultivation_jiyin_auto(
        request: Request,
        chat_id: int = Form(...),
        enabled: str = Form(...),
        choice: str = Form(""),
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_fanren_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            if not active_profile:
                raise HTTPException(status_code=401, detail="Profile not active")
            biz_fanren_game.set_auto_jiyin(
                db,
                chat_id,
                enabled == "1",
                choice,
                profile_id=active_profile.id,
            )
            session = biz_fanren_game.get_session(db, chat_id, profile_id=active_profile.id)
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Cultivation session not found")
        return RedirectResponse(url="/modules/cultivation", status_code=303)

    @application.post("/runtime/cultivation/nanlong-toggle")
    async def toggle_cultivation_nanlong_auto(
        request: Request,
        chat_id: int = Form(...),
        enabled: str = Form(...),
        choice: str = Form(""),
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_fanren_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            if not active_profile:
                raise HTTPException(status_code=401, detail="Profile not active")
            biz_fanren_game.set_auto_nanlong(
                db,
                chat_id,
                enabled == "1",
                choice,
                profile_id=active_profile.id,
            )
            session = biz_fanren_game.get_session(db, chat_id, profile_id=active_profile.id)
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Cultivation session not found")
        return RedirectResponse(url="/modules/cultivation", status_code=303)

    @application.post("/runtime/cultivation/rift-toggle")
    async def toggle_cultivation_rift_auto(
        request: Request,
        chat_id: int = Form(...),
        enabled: str = Form(...),
        redirect_to: str = Form("/modules/cultivation"),
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_fanren_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            if not active_profile:
                raise HTTPException(status_code=401, detail="Profile not active")
            if enabled == "1" and not _is_yuanying_stage(active_profile):
                raise HTTPException(status_code=400, detail="仅元婴及以上境界角色可用")
            biz_fanren_game.set_auto_rift(
                db,
                chat_id,
                enabled == "1",
                profile_id=active_profile.id,
            )
            session = biz_fanren_game.get_session(db, chat_id, profile_id=active_profile.id)
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Cultivation session not found")
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/cultivation/yuanying-toggle")
    async def toggle_cultivation_yuanying_auto(
        request: Request,
        chat_id: int = Form(...),
        enabled: str = Form(...),
        redirect_to: str = Form("/modules/cultivation"),
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_fanren_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            if not active_profile:
                raise HTTPException(status_code=401, detail="Profile not active")
            if enabled == "1" and not _is_yuanying_stage(active_profile):
                raise HTTPException(status_code=400, detail="仅元婴及以上境界角色可用")
            biz_fanren_game.set_auto_yuanying(
                db,
                chat_id,
                enabled == "1",
                profile_id=active_profile.id,
            )
            if enabled == "1":
                sect_chat = _get_primary_command_chat(
                    active_profile.id,
                    biz_sect_game.SECT_BOT_USERNAME,
                )
                if sect_chat:
                    biz_sect_game.ensure_tables(db)
                    biz_sect_game.configure_yuanying_retreat_auto(
                        db,
                        sect_chat.chat_id,
                        False,
                        profile_id=active_profile.id,
                    )
            session = biz_fanren_game.get_session(db, chat_id, profile_id=active_profile.id)
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Cultivation session not found")
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/sect/lingxiao-toggle")
    async def toggle_lingxiao_auto(
        request: Request, chat_id: int = Form(...), enabled: str = Form(...)
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_sect_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            biz_sect_game.configure_lingxiao_auto(
                db,
                chat_id,
                enabled == "1",
                profile_id=active_profile.id if active_profile else None,
            )
            if enabled == "1":
                biz_sect_game.set_enabled(
                    db,
                    chat_id,
                    True,
                    profile_id=active_profile.id if active_profile else None,
                )
                if active_profile:
                    biz_sect_game.sync_lingxiao_trial_state(
                        storage, db, active_profile.id, chat_id
                    )
            session = biz_sect_game.get_session(
                db, chat_id, profile_id=active_profile.id if active_profile else None
            )
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Sect session not found")
        return RedirectResponse(url="/modules/sect", status_code=303)

    @application.post("/runtime/sect/yuanying-wendao-toggle")
    async def toggle_yuanying_wendao_auto(
        request: Request, chat_id: int = Form(...), enabled: str = Form(...)
    ) -> RedirectResponse:
        active_profile = _get_request_profile(request)
        if not active_profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        if not biz_sect_game._is_same_sect_name(active_profile.sect_name, biz_sect_game.YUANYING_SECT_NAME):
            raise HTTPException(status_code=400, detail="仅元婴宗角色可用")
        db = CompatDb(storage)
        try:
            biz_sect_game.ensure_tables(db)
            biz_sect_game.configure_yuanying_wendao_auto(
                db,
                chat_id,
                enabled == "1",
                profile_id=active_profile.id,
            )
            if enabled == "1":
                biz_sect_game.set_enabled(db, chat_id, True, profile_id=active_profile.id)
            session = biz_sect_game.get_session(db, chat_id, profile_id=active_profile.id)
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Sect session not found")
        return RedirectResponse(url="/modules/sect", status_code=303)

    @application.post("/runtime/sect/yuanying-retreat-toggle")
    async def toggle_yuanying_retreat_auto(
        request: Request,
        chat_id: int = Form(...),
        enabled: str = Form(...),
        redirect_to: str = Form("/modules/sect"),
    ) -> RedirectResponse:
        active_profile = _get_request_profile(request)
        if not active_profile:
            raise HTTPException(status_code=401, detail="Profile not active")
        if not biz_sect_game._is_same_sect_name(active_profile.sect_name, biz_sect_game.YUANYING_SECT_NAME):
            raise HTTPException(status_code=400, detail="仅元婴宗角色可用")
        db = CompatDb(storage)
        try:
            biz_sect_game.ensure_tables(db)
            biz_sect_game.configure_yuanying_retreat_auto(
                db,
                chat_id,
                enabled == "1",
                profile_id=active_profile.id,
            )
            if enabled == "1":
                cultivation_chat = _get_primary_command_chat(
                    active_profile.id,
                    biz_fanren_game.FANREN_BOT_USERNAME,
                )
                if cultivation_chat:
                    biz_fanren_game.ensure_tables(db)
                    biz_fanren_game.set_auto_yuanying(
                        db,
                        cultivation_chat.chat_id,
                        False,
                        profile_id=active_profile.id,
                    )
            if enabled == "1":
                biz_sect_game.set_enabled(db, chat_id, True, profile_id=active_profile.id)
            session = biz_sect_game.get_session(db, chat_id, profile_id=active_profile.id)
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Sect session not found")
        return RedirectResponse(url=redirect_to, status_code=303)

    @application.post("/runtime/sect/checkin-toggle")
    async def toggle_sect_checkin_auto(
        request: Request, chat_id: int = Form(...), enabled: str = Form(...)
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_sect_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            biz_sect_game.configure_sect_checkin_auto(
                db,
                chat_id,
                enabled == "1",
                profile_id=active_profile.id if active_profile else None,
            )
            if enabled == "1":
                biz_sect_game.set_enabled(
                    db,
                    chat_id,
                    True,
                    profile_id=active_profile.id if active_profile else None,
                )
                if active_profile:
                    biz_sect_game.sync_common_sect_state(
                        storage, db, active_profile.id, chat_id
                    )
            session = biz_sect_game.get_session(
                db, chat_id, profile_id=active_profile.id if active_profile else None
            )
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Sect session not found")
        return RedirectResponse(url="/modules/sect", status_code=303)

    @application.post("/runtime/sect/teach-toggle")
    async def toggle_sect_teach_auto(
        request: Request, chat_id: int = Form(...), enabled: str = Form(...)
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_sect_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            biz_sect_game.configure_sect_teach_auto(
                db,
                chat_id,
                enabled == "1",
                profile_id=active_profile.id if active_profile else None,
            )
            if enabled == "1":
                biz_sect_game.set_enabled(
                    db,
                    chat_id,
                    True,
                    profile_id=active_profile.id if active_profile else None,
                )
                if active_profile:
                    biz_sect_game.sync_common_sect_state(
                        storage, db, active_profile.id, chat_id
                    )
            session = biz_sect_game.get_session(
                db, chat_id, profile_id=active_profile.id if active_profile else None
            )
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Sect session not found")
        return RedirectResponse(url="/modules/sect", status_code=303)

    @application.post("/runtime/sect/companion-greet-toggle")
    async def toggle_companion_greet_auto(
        request: Request, chat_id: int = Form(...), enabled: str = Form(...)
    ) -> RedirectResponse:
        active_profile = _get_request_profile(request)
        if not active_profile:
            return RedirectResponse(url="/login", status_code=303)
        if str(active_profile.sect_name or "").strip() != "星宫":
            raise HTTPException(status_code=400, detail="仅星宫角色可用")
        db = CompatDb(storage)
        try:
            biz_sect_game.ensure_tables(db)
            biz_sect_game.configure_companion_greet_auto(
                db,
                chat_id,
                enabled == "1",
                profile_id=active_profile.id,
            )
            if enabled == "1":
                biz_sect_game.set_enabled(db, chat_id, True, profile_id=active_profile.id)
                biz_sect_game.sync_common_sect_state(storage, db, active_profile.id, chat_id)
            session = biz_sect_game.get_session(db, chat_id, profile_id=active_profile.id)
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Sect session not found")
        return RedirectResponse(url="/modules/sect", status_code=303)

    @application.post("/runtime/sect/companion-assist-toggle")
    async def toggle_companion_assist_auto(
        request: Request, chat_id: int = Form(...), enabled: str = Form(...)
    ) -> RedirectResponse:
        active_profile = _get_request_profile(request)
        if not active_profile:
            return RedirectResponse(url="/login", status_code=303)
        if str(active_profile.sect_name or "").strip() != "星宫":
            raise HTTPException(status_code=400, detail="仅星宫角色可用")
        db = CompatDb(storage)
        try:
            biz_sect_game.ensure_tables(db)
            biz_sect_game.configure_companion_assist_auto(
                db,
                chat_id,
                enabled == "1",
                profile_id=active_profile.id,
            )
            if enabled == "1":
                biz_sect_game.set_enabled(db, chat_id, True, profile_id=active_profile.id)
                biz_sect_game.sync_common_sect_state(storage, db, active_profile.id, chat_id)
            session = biz_sect_game.get_session(db, chat_id, profile_id=active_profile.id)
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Sect session not found")
        return RedirectResponse(url="/modules/sect", status_code=303)

    @application.post("/runtime/sect/yinluo-sacrifice-toggle")
    async def toggle_yinluo_sacrifice_auto(
        request: Request, chat_id: int = Form(...), enabled: str = Form(...)
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_sect_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            biz_sect_game.configure_yinluo_sacrifice_auto(
                db,
                chat_id,
                enabled == "1",
                profile_id=active_profile.id if active_profile else None,
            )
            if enabled == "1":
                biz_sect_game.set_enabled(
                    db,
                    chat_id,
                    True,
                    profile_id=active_profile.id if active_profile else None,
                )
                if active_profile:
                    biz_sect_game.sync_yinluo_state(storage, db, active_profile.id, chat_id)
            session = biz_sect_game.get_session(
                db, chat_id, profile_id=active_profile.id if active_profile else None
            )
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Sect session not found")
        return RedirectResponse(url="/modules/sect", status_code=303)

    @application.post("/runtime/sect/yinluo-all-toggle")
    async def toggle_yinluo_all_auto(
        request: Request, chat_id: int = Form(...), enabled: str = Form(...)
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_sect_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            if enabled == "1" and active_profile and not biz_sect_game._is_same_sect_name(
                getattr(active_profile, "sect_name", "") or "",
                biz_sect_game.YINLUO_SECT_NAME,
            ):
                raise HTTPException(status_code=400, detail="Yinluo sect only")
            biz_sect_game.configure_yinluo_all_auto(
                db,
                chat_id,
                enabled == "1",
                profile_id=active_profile.id if active_profile else None,
            )
            if enabled == "1":
                biz_sect_game.set_enabled(
                    db,
                    chat_id,
                    True,
                    profile_id=active_profile.id if active_profile else None,
                )
                if active_profile:
                    biz_sect_game.sync_yinluo_state(storage, db, active_profile.id, chat_id)
            session = biz_sect_game.get_session(
                db, chat_id, profile_id=active_profile.id if active_profile else None
            )
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Sect session not found")
        return RedirectResponse(url="/modules/sect", status_code=303)

    @application.post("/runtime/sect/yinluo-blood-wash-toggle")
    async def toggle_yinluo_blood_wash_auto(
        request: Request, chat_id: int = Form(...), enabled: str = Form(...)
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_sect_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            biz_sect_game.configure_yinluo_blood_wash_auto(
                db,
                chat_id,
                enabled == "1",
                profile_id=active_profile.id if active_profile else None,
            )
            if enabled == "1":
                biz_sect_game.set_enabled(
                    db,
                    chat_id,
                    True,
                    profile_id=active_profile.id if active_profile else None,
                )
                if active_profile:
                    biz_sect_game.sync_yinluo_state(storage, db, active_profile.id, chat_id)
            session = biz_sect_game.get_session(
                db, chat_id, profile_id=active_profile.id if active_profile else None
            )
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Sect session not found")
        return RedirectResponse(url="/modules/sect", status_code=303)

    @application.post("/runtime/sect/yinluo-refine-toggle")
    async def toggle_yinluo_refine_auto(
        request: Request, chat_id: int = Form(...), enabled: str = Form(...)
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_sect_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            biz_sect_game.configure_yinluo_refine_auto(
                db,
                chat_id,
                enabled == "1",
                profile_id=active_profile.id if active_profile else None,
            )
            if enabled == "1":
                biz_sect_game.set_enabled(
                    db,
                    chat_id,
                    True,
                    profile_id=active_profile.id if active_profile else None,
                )
                if active_profile:
                    biz_sect_game.sync_yinluo_state(storage, db, active_profile.id, chat_id)
            session = biz_sect_game.get_session(
                db, chat_id, profile_id=active_profile.id if active_profile else None
            )
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Sect session not found")
        return RedirectResponse(url="/modules/sect", status_code=303)

    @application.post("/runtime/sect/yinluo-shadow-toggle")
    async def toggle_yinluo_shadow_auto(
        request: Request, chat_id: int = Form(...), enabled: str = Form(...)
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_sect_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            biz_sect_game.configure_yinluo_shadow_auto(
                db,
                chat_id,
                enabled == "1",
                profile_id=active_profile.id if active_profile else None,
            )
            if enabled == "1":
                biz_sect_game.set_enabled(
                    db,
                    chat_id,
                    True,
                    profile_id=active_profile.id if active_profile else None,
                )
                if active_profile:
                    biz_sect_game.sync_yinluo_state(storage, db, active_profile.id, chat_id)
            session = biz_sect_game.get_session(
                db, chat_id, profile_id=active_profile.id if active_profile else None
            )
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Sect session not found")
        return RedirectResponse(url="/modules/sect", status_code=303)

    @application.post("/runtime/sect/huangfeng-auto")
    async def configure_huangfeng_auto(
        request: Request,
        chat_id: int = Form(...),
        enabled: str = Form(...),
        seed_name: str = Form(""),
        exchange_enabled: str = Form("0"),
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_sect_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            if not active_profile:
                raise HTTPException(status_code=401, detail="Profile not active")
            session = biz_sect_game.get_session(db, chat_id, profile_id=active_profile.id)
            normalized_seed_name = (
                str(seed_name or "").strip()
                or str((session or {}).get("huangfeng_seed_name") or "").strip()
            )
            exchange_flag = exchange_enabled == "1"
            if enabled == "1" and not normalized_seed_name:
                raise HTTPException(status_code=400, detail="Seed name required")
            biz_sect_game.configure_huangfeng_auto(
                db,
                chat_id,
                enabled == "1",
                seed_name=normalized_seed_name if enabled == "1" else None,
                exchange_enabled=exchange_flag,
                profile_id=active_profile.id,
            )
            if enabled == "1":
                biz_sect_game.set_enabled(
                    db,
                    chat_id,
                    True,
                    profile_id=active_profile.id,
                )
            session = biz_sect_game.get_session(db, chat_id, profile_id=active_profile.id)
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Sect session not found")
        return RedirectResponse(url="/modules/sect", status_code=303)

    @application.post("/runtime/sect/luoyun-toggle")
    async def toggle_luoyun_auto(
        request: Request, chat_id: int = Form(...), enabled: str = Form(...)
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_sect_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            if not active_profile:
                raise HTTPException(status_code=401, detail="Profile not active")
            biz_sect_game.configure_luoyun_auto(
                db,
                chat_id,
                enabled == "1",
                profile_id=active_profile.id,
            )
            if enabled == "1":
                biz_sect_game.set_enabled(
                    db,
                    chat_id,
                    True,
                    profile_id=active_profile.id,
                )
                biz_sect_game.sync_luoyun_state(storage, db, active_profile.id, chat_id)
            session = biz_sect_game.get_session(db, chat_id, profile_id=active_profile.id)
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Sect session not found")
        return RedirectResponse(url="/modules/sect", status_code=303)

    @application.post("/runtime/sect/lingxiao-gangfeng-toggle")
    async def toggle_lingxiao_gangfeng_auto(
        request: Request, chat_id: int = Form(...), enabled: str = Form(...)
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_sect_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            biz_sect_game.configure_lingxiao_gangfeng_auto(
                db,
                chat_id,
                enabled == "1",
                profile_id=active_profile.id if active_profile else None,
            )
            if enabled == "1":
                biz_sect_game.set_enabled(
                    db,
                    chat_id,
                    True,
                    profile_id=active_profile.id if active_profile else None,
                )
                if active_profile:
                    biz_sect_game.sync_lingxiao_trial_state(
                        storage, db, active_profile.id, chat_id
                    )
            session = biz_sect_game.get_session(
                db, chat_id, profile_id=active_profile.id if active_profile else None
            )
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Sect session not found")
        return RedirectResponse(url="/modules/sect", status_code=303)

    @application.post("/runtime/sect/lingxiao-borrow-toggle")
    async def toggle_lingxiao_borrow_auto(
        request: Request, chat_id: int = Form(...), enabled: str = Form(...)
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_sect_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            biz_sect_game.configure_lingxiao_borrow_auto(
                db,
                chat_id,
                enabled == "1",
                profile_id=active_profile.id if active_profile else None,
            )
            if enabled == "1":
                biz_sect_game.set_enabled(
                    db,
                    chat_id,
                    True,
                    profile_id=active_profile.id if active_profile else None,
                )
                if active_profile:
                    biz_sect_game.sync_lingxiao_trial_state(
                        storage, db, active_profile.id, chat_id
                    )
            session = biz_sect_game.get_session(
                db, chat_id, profile_id=active_profile.id if active_profile else None
            )
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Sect session not found")
        return RedirectResponse(url="/modules/sect", status_code=303)

    @application.post("/runtime/sect/lingxiao-question-toggle")
    async def toggle_lingxiao_question_auto(
        request: Request, chat_id: int = Form(...), enabled: str = Form(...)
    ) -> RedirectResponse:
        db = CompatDb(storage)
        try:
            biz_sect_game.ensure_tables(db)
            active_profile = _get_request_profile(request)
            biz_sect_game.configure_lingxiao_question_auto(
                db,
                chat_id,
                enabled == "1",
                profile_id=active_profile.id if active_profile else None,
            )
            if enabled == "1":
                biz_sect_game.set_enabled(
                    db,
                    chat_id,
                    True,
                    profile_id=active_profile.id if active_profile else None,
                )
                if active_profile:
                    biz_sect_game.sync_lingxiao_trial_state(
                        storage, db, active_profile.id, chat_id
                    )
            session = biz_sect_game.get_session(
                db, chat_id, profile_id=active_profile.id if active_profile else None
            )
        finally:
            db.close()
        if not session:
            raise HTTPException(status_code=404, detail="Sect session not found")
        return RedirectResponse(url="/modules/sect", status_code=303)

    @application.get("/health")
    async def health() -> dict:
        active_profile = storage.get_active_profile()
        current_fingerprint = compute_runtime_code_fingerprint()
        telegram_runtime = load_runtime_status(
            storage.get_runtime_state("telegram_runtime_status") or ""
        )
        telegram_fingerprint = str(
            telegram_runtime.get("code_fingerprint") or ""
        ).strip()
        return {
            "status": "ok",
            "modules": len(module_registry.list_modules()),
            "profiles": len(storage.list_profiles()),
            "active_profile": active_profile.name if active_profile else None,
            "runtime_code": {
                "current_fingerprint": current_fingerprint,
                "web": build_runtime_status("web", started_at=web_started_at),
                "telegram": telegram_runtime,
                "telegram_code_current": bool(telegram_fingerprint)
                and telegram_fingerprint == current_fingerprint,
            },
        }

    return application


app = create_app()
