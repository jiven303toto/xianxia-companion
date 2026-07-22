import asyncio
import json
import time
import logging
import subprocess
import re
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
from tg_game.features.artifact.biz_artifact_nurture import (
    ARTIFACT_NURTURE_AWAIT_REPLY_STATE,
    ARTIFACT_NURTURE_BOT_COOLDOWN_STATE,
    ARTIFACT_NURTURE_DEFAULT_COOLDOWN_SECONDS,
    ARTIFACT_NURTURE_DEFAULT_TARGET_NAME,
    ARTIFACT_NURTURE_FEATURE_KEY,
    ARTIFACT_NURTURE_REPLY_WAIT_SECONDS,
    ARTIFACT_NURTURE_STOPPED_RESOURCES_STATE,
    build_artifact_nurture_resource_state,
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
    build_profile_rebirth_countdown_items as _countdown_build_profile_rebirth_countdown_items,
    build_sect_countdown_items as _countdown_build_sect_countdown_items,
    build_small_world_countdown_items as _countdown_build_small_world_countdown_items,
    build_tianxing_countdown_items as _countdown_build_tianxing_countdown_items,
    build_wanling_roam_countdown_items as _countdown_build_wanling_roam_countdown_items,
    build_xinggong_slot_countdown_items as _countdown_build_xinggong_slot_countdown_items,
    format_countdown_display_for_now as _countdown_format_display_for_now,
    sort_countdown_items,
)
from tg_game.features.fishing.biz_fishing_view_model import build_fishing_view
from tg_game.features.small_world.biz_small_world_view_model import (
    build_small_world_auto_view as _small_world_build_small_world_auto_view,
    build_small_world_preach_auto_view as _small_world_build_small_world_preach_auto_view,
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
from tg_game.features.tianji_trial.biz_tianji_trial_encounter_state import (
    build_tianji_encounter_state as _tianji_build_tianji_encounter_state,
)
from tg_game.features.tianji_trial.biz_tianji_trial_remnant_state import (
    TIANJI_EXCHANGE_COMMAND_TEXT as _tianji_exchange_command_text,
    TIANJI_EXCHANGE_FALLBACK_ITEMS as _tianji_exchange_fallback_items,
    TIANJI_REMNANT_COMMANDS as _tianji_remnant_commands,
    TIANJI_REMNANT_COMMAND_TEXT as _tianji_remnant_command_text,
    TIANJI_TRIAL_COMMAND_TEXT as _tianji_trial_command_text,
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
from tg_game.web.biz_artifact_view_model import (
    build_artifact_nurture_auto_view as _artifact_build_artifact_nurture_auto_view,
    build_artifact_nurture_command as _artifact_build_artifact_nurture_command,
    build_artifact_touch_auto_view as _artifact_build_artifact_touch_auto_view,
    build_artifact_trial_auto_view as _artifact_build_artifact_trial_auto_view,
    build_artifact_trial_command as _artifact_build_artifact_trial_command,
    normalize_artifact_nurture_target_name as _artifact_normalize_artifact_nurture_target_name,
    normalize_artifact_touch_command as _artifact_normalize_artifact_touch_command,
    normalize_artifact_touch_interval as _artifact_normalize_artifact_touch_interval,
    normalize_artifact_trial_artifact_name as _artifact_normalize_artifact_trial_artifact_name,
    normalize_artifact_trial_route as _artifact_normalize_artifact_trial_route,
    pack_artifact_nurture_strategy as _artifact_pack_artifact_nurture_strategy,
    pack_artifact_touch_strategy as _artifact_pack_artifact_touch_strategy,
    pack_artifact_trial_strategy as _artifact_pack_artifact_trial_strategy,
    unpack_artifact_nurture_strategy as _artifact_unpack_artifact_nurture_strategy,
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
    build_inventory_bulk_sell_command as _build_inventory_bulk_sell_command,
    build_inventory_items_from_payload as _build_inventory_items_from_payload,
    build_profile_inventory_search as _inventory_build_profile_inventory_search,
    format_market_price as _format_market_price,
    inventory_item_matches_query as _inventory_item_matches_query,
    item_type_label as _item_type_label,
    market_price_preview as _market_price_preview,
    market_price_sort_key as _market_price_sort_key,
    profile_display_label as _inventory_profile_display_label,
    build_profile_telegram_name_map as _inventory_build_profile_telegram_name_map,
    read_telegram_session_display_name as _inventory_read_telegram_session_display_name,
    resolve_profile_telegram_name as _inventory_resolve_profile_telegram_name,
    reverse_market_price_sort_key as _reverse_market_price_sort_key,
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


__all__ = [
    'APP_DIR',
    'REPO_ROOT_DIR',
    'ASSETS_DIR',
    'TEMPLATES_DIR',
    'STATIC_DIR',
    'WILD_DEEP_LOG_DIR',
    'WILD_DEEP_COMMAND_PREFIX',
    'templates',
    'APP_SESSION_COOKIE',
    'TG_LOGIN_CHALLENGE_COOKIE',
    'EXTERNAL_PROFILE_REFRESH_TTL_SECONDS',
    'EXTERNAL_REFRESH_LOOP_SECONDS',
    'logger',
    'COMPANION_AUTO_MANUAL_DELAY_SECONDS',
    'ARTIFACT_TOUCH_REPLY_WAIT_SECONDS',
    'ARTIFACT_TRIAL_REPLY_WAIT_SECONDS',
    'ARTIFACT_NURTURE_REPLY_WAIT_SECONDS',
    'SMALL_WORLD_AUTO_DEFAULT_REFRESH_MINUTES',
    '_get_profile_cultivation_binding',
    '_set_all_profile_cultivation',
    '_build_all_profile_cultivation_state',
    '_resolve_active_companion_payload_and_status',
    '_resolve_latest_companion_payload',
    '_resolve_latest_companion_cooldown_target',
    '_format_companion_cooldown_display',
    '_build_companion_voyage_state',
    '_build_companion_view',
    '_build_companion_heart_tribulation_view',
    '_build_companion_auto_view',
    '_build_pagoda_auto_view',
    '_build_tianji_trial_daily_auto_view',
    '_build_estate_hunt_daily_auto_view',
    '_normalize_companion_voyage_strategy',
    '_normalize_wild_experience_strategy',
    '_normalize_artifact_touch_command',
    '_normalize_artifact_touch_interval',
    '_pack_artifact_touch_strategy',
    '_unpack_artifact_touch_strategy',
    '_normalize_artifact_trial_artifact_name',
    '_normalize_artifact_trial_route',
    '_pack_artifact_trial_strategy',
    '_unpack_artifact_trial_strategy',
    '_build_artifact_trial_command',
    '_build_artifact_touch_auto_view',
    '_build_artifact_trial_auto_view',
    '_normalize_artifact_nurture_target_name',
    '_pack_artifact_nurture_strategy',
    '_unpack_artifact_nurture_strategy',
    '_build_artifact_nurture_command',
    '_build_artifact_nurture_auto_view',
    '_normalize_xinggong_starboard_target',
    '_is_xinggong_starboard_insufficient_reply',
    '_is_xinggong_starboard_success_reply',
    '_is_xinggong_starboard_pull_command_for_target',
    '_build_xinggong_starboard_pull_result',
    '_build_xinggong_starboard_auto_view',
    '_build_wanling_roam_auto_view',
    '_format_countdown_display',
    '_build_small_world_auto_view',
    '_build_small_world_preach_auto_view',
    '_build_countdown_item',
    '_build_cultivation_countdown_items',
    '_build_companion_voyage_countdown_items',
    '_build_profile_rebirth_countdown_items',
    '_build_auto_task_countdown_items',
    '_build_xinggong_slot_countdown_items',
    '_build_wanling_roam_state',
    '_build_wanling_roam_config_view',
    '_build_wanling_roam_countdown_items',
    '_build_sect_countdown_items',
    '_build_tianxing_countdown_items',
    '_build_small_world_countdown_items',
    '_resolve_auto_feature_next_run_at',
    '_build_wild_experience_view',
    '_resolve_companion_auto_next_run_at',
    'OTHER_PLAY_DEFINITIONS',
    'MULAN_AUTO_SUPPORT_FEATURE_KEY',
    'MULAN_PANEL_COMMAND',
    'MULAN_MERIT_COMMANDS',
    'MULAN_MERIT_EXCHANGE_FALLBACK_ITEMS',
    'MULAN_SUPPORT_COMMANDS',
    'MULAN_UTILITY_COMMANDS',
    'MULAN_WANLING_COMMANDS',
    'MULAN_WANLING_PATROL_ROUTES',
    'MULAN_MANUAL_COMMANDS',
    'MULAN_ROUTE_ACTIONS',
    'MULAN_VALID_SUPPORT_COMMANDS',
    'TIANJI_REMNANT_COMMAND_TEXT',
    'TIANJI_TRIAL_COMMAND_TEXT',
    'TIANJI_EXCHANGE_COMMAND_TEXT',
    'TIANJI_REMNANT_COMMANDS',
    'TIANJI_EXCHANGE_FALLBACK_ITEMS',
    '_get_dungeon_definition',
    '_build_pagoda_view',
    '_build_estate_miniapp_hunt_button',
    '_build_dongfu_view',
    '_build_dongfu_pavilion_slots_view',
    '_build_estate_reply_messages',
    '_build_dice_state',
    '_build_ghost_gambling_view',
    '_build_divination_view',
    '_build_character_view',
    '_build_taiyi_view',
    '_build_tianji_encounter_state',
    '_extract_mulan_section_lines',
    '_extract_mulan_labeled_value',
    '_parse_mulan_panel_text',
    '_mulan_line_value',
    '_mulan_action_from_route_text',
    '_build_mulan_recommendation',
    '_build_mulan_auto_support_view',
    '_mulan_message_matches_thread',
    '_mulan_message_has_current_profile_parent',
    '_find_latest_mulan_message',
    '_mulan_preview_lines',
    '_is_mulan_support_ack_text',
    '_build_mulan_state',
    '_get_latest_tianji_remnant_reply',
    '_build_tianji_remnant_state',
    '_build_other_play_view',
    '_build_divination_batch_view',
    '_build_fishing_view',
    '_list_dungeon_feed_source_messages',
    '_build_dungeon_messages',
    '_extract_dungeon_command_buttons',
    '_extract_dungeon_cleanup_targets',
    '_clean_stock_name',
    '_parse_stock_market_batch',
    '_build_stock_trend_points',
    '_decorate_stock_history',
    '_latest_stock_player_reply_view',
    '_build_stock_view',
    '_resolve_stock_history_range',
    '_build_stock_history_response',
    '_build_recent_player_options',
    '_build_sect_recent_reply_text',
    '_is_sect_related_message',
    '_wild_deep_time_bucket',
    '_build_wild_deep_log_rows',
    '_render_wild_deep_log_markdown',
    '_export_wild_deep_log_file',
    '_build_wild_deep_log_export_result',
    '_build_sect_daily_view',
    '_merge_sect_daily_view_with_session',
    '_normalize_sect_name_text',
    'NO_SECT_NAMES',
    '_has_joined_sect',
    '_is_tianxing_sect_profile',
    '_sect_matches_current',
    '_profile_display_label',
    '_telegram_session_file_path',
    '_read_telegram_session_display_name',
    '_resolve_profile_telegram_name',
    '_build_profile_telegram_name_map',
    '_build_profile_inventory_search',
    'CULTIVATION_STAGE_CAPS',
    '_major_stage_rank',
    '_is_small_world_module_available',
    '_is_yuanying_stage',
    '_payload_has_artifact_spirit',
    'SECT_METADATA',
    '_format_cultivation_progress',
    '_extract_item_delta_lines',
    '_extract_adventure_lines',
    '_build_cultivation_result_view',
    '_sync_all_items_if_needed',
    '_sync_bootstrap_if_needed',
    '_sync_shop_items_if_needed',
    '_sync_marketplace_listings_if_needed',
    '_sync_profile_from_cultivator',
    '_build_rift_failure_profile_state',
]

APP_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT_DIR = APP_DIR.parent
ASSETS_DIR = APP_DIR / "assets"
TEMPLATES_DIR = ASSETS_DIR / "templates"
STATIC_DIR = ASSETS_DIR / "static"
WILD_DEEP_LOG_DIR = REPO_ROOT_DIR / "logs" / "wild_experience_deep"
WILD_DEEP_COMMAND_PREFIX = _wild_deep_WILD_DEEP_COMMAND_PREFIX

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
APP_SESSION_COOKIE = "tg_game_app_session"
TG_LOGIN_CHALLENGE_COOKIE = "tg_game_login_challenge"
EXTERNAL_PROFILE_REFRESH_TTL_SECONDS = get_settings().external_keepalive_seconds
EXTERNAL_REFRESH_LOOP_SECONDS = get_external_keepalive_poll_seconds()


logger = logging.getLogger("tg_game.web.app")
COMPANION_AUTO_MANUAL_DELAY_SECONDS = 1800
ARTIFACT_TOUCH_REPLY_WAIT_SECONDS = 180
ARTIFACT_TRIAL_REPLY_WAIT_SECONDS = 180
SMALL_WORLD_AUTO_DEFAULT_REFRESH_MINUTES = (
    biz_small_world_game.SMALL_WORLD_DEFAULT_REFRESH_INTERVAL_SECONDS // 60
)


def _get_profile_cultivation_binding(storage: Storage, profile):
    return _cultivation_get_profile_cultivation_binding(storage, profile)


def _set_all_profile_cultivation(
    storage: Storage, mode: str, protected_profile_id: int = DEFAULT_BULK_CULTIVATION_PROTECTED_PROFILE_ID
) -> dict:
    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in {"normal", "deep"}:
        raise ValueError("Cultivation mode must be normal or deep")
    protected_profile_id = int(protected_profile_id or 0)
    db = CompatDb(storage)
    updated = 0
    skipped = 0
    protected = 0
    try:
        biz_fanren_game.ensure_tables(db)
        for profile in storage.list_profiles():
            if protected_profile_id and profile.id == protected_profile_id:
                protected += 1
                continue
            binding = _get_profile_cultivation_binding(storage, profile)
            if not binding:
                skipped += 1
                continue
            biz_fanren_game.ensure_session(db, binding.chat_id, profile_id=profile.id)
            biz_fanren_game.set_mode(
                db,
                binding.chat_id,
                normalized_mode,
                profile_id=profile.id,
            )
            biz_fanren_game.update_session(
                db,
                binding.chat_id,
                profile_id=profile.id,
                thread_id=binding.thread_id,
            )
            biz_fanren_game.set_enabled(
                db,
                binding.chat_id,
                True,
                reset_failure=True,
                profile_id=profile.id,
            )
            updated += 1
    finally:
        db.close()
    return {"updated": updated, "skipped": skipped, "protected": protected}


def _build_all_profile_cultivation_state(
    storage: Storage,
    profiles: list,
    protected_profile_id: int = DEFAULT_BULK_CULTIVATION_PROTECTED_PROFILE_ID,
) -> dict:
    return _cultivation_build_all_profile_cultivation_state(
        storage,
        profiles,
        protected_profile_id=protected_profile_id,
    )


def _resolve_active_companion_payload_and_status(payload: dict) -> tuple[dict, str]:
    return _companion_resolve_active_companion_payload_and_status(payload)


def _resolve_latest_companion_payload(payload: dict) -> dict:
    return _companion_resolve_latest_companion_payload(payload)


def _resolve_latest_companion_cooldown_target(
    companion_payload: dict,
    field_name: str,
    cooldown_hours: int,
) -> Optional[float]:
    return _companion_resolve_latest_companion_cooldown_target(
        companion_payload,
        field_name,
        cooldown_hours,
    )


def _format_companion_cooldown_display(target: Optional[float]) -> str:
    return _companion_format_companion_cooldown_display(
        target,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_companion_voyage_state(voyage_reply: Optional[dict]) -> dict:
    return _companion_build_companion_voyage_state(
        voyage_reply,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_companion_view(
    payload: dict,
    companion_reply_text: str = "",
    voyage_reply: Optional[dict] = None,
) -> dict:
    return _companion_build_companion_view(
        payload,
        companion_reply_text,
        voyage_reply,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_companion_heart_tribulation_view(raw_task: Optional[dict]) -> dict:
    return _companion_build_companion_heart_tribulation_view(
        raw_task,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_companion_auto_view(raw_task: Optional[dict], feature_key: str) -> dict:
    return _companion_build_companion_auto_view(
        raw_task,
        feature_key,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_pagoda_auto_view(raw_task: Optional[dict]) -> dict:
    return _companion_build_pagoda_auto_view(
        raw_task,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_tianji_trial_daily_auto_view(raw_task: Optional[dict]) -> dict:
    return _companion_build_tianji_trial_daily_auto_view(
        raw_task,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_estate_hunt_daily_auto_view(raw_task: Optional[dict]) -> dict:
    return _companion_build_estate_hunt_daily_auto_view(
        raw_task,
        now_ts=biz_fanren_game.time.time(),
    )


def _normalize_companion_voyage_strategy(value: object) -> str:
    return normalize_companion_voyage_strategy(value)


def _normalize_wild_experience_strategy(value: object) -> str:
    return normalize_wild_experience_strategy(value)


def _normalize_artifact_touch_command(value: object) -> str:
    return _artifact_normalize_artifact_touch_command(value)


def _normalize_artifact_touch_interval(value: object) -> int:
    return _artifact_normalize_artifact_touch_interval(value)


def _pack_artifact_touch_strategy(command_text: str, interval_seconds: int) -> str:
    return _artifact_pack_artifact_touch_strategy(command_text, interval_seconds)


def _unpack_artifact_touch_strategy(value: object) -> tuple[str, int]:
    return _artifact_unpack_artifact_touch_strategy(value)


def _normalize_artifact_trial_artifact_name(value: object) -> str:
    return _artifact_normalize_artifact_trial_artifact_name(value)


def _normalize_artifact_trial_route(value: object) -> str:
    return _artifact_normalize_artifact_trial_route(value)


def _pack_artifact_trial_strategy(artifact_name: str, route: str) -> str:
    return _artifact_pack_artifact_trial_strategy(artifact_name, route)


def _unpack_artifact_trial_strategy(value: object) -> tuple[str, str]:
    return _artifact_unpack_artifact_trial_strategy(value)


def _build_artifact_trial_command(artifact_name: object, route: object) -> str:
    return _artifact_build_artifact_trial_command(artifact_name, route)


def _build_artifact_touch_auto_view(raw_task: Optional[dict]) -> dict:
    return _artifact_build_artifact_touch_auto_view(raw_task)


def _build_artifact_trial_auto_view(
    raw_task: Optional[dict],
    payload: Optional[dict] = None,
    game_items_dict: Optional[dict] = None,
) -> dict:
    return _artifact_build_artifact_trial_auto_view(
        raw_task,
        payload,
        game_items_dict,
    )


def _normalize_artifact_nurture_target_name(value: object) -> str:
    return _artifact_normalize_artifact_nurture_target_name(value)


def _pack_artifact_nurture_strategy(target_name: object) -> str:
    return _artifact_pack_artifact_nurture_strategy(target_name)


def _unpack_artifact_nurture_strategy(value: object) -> str:
    return _artifact_unpack_artifact_nurture_strategy(value)


def _build_artifact_nurture_command(target_name: object) -> str:
    return _artifact_build_artifact_nurture_command(target_name)


def _build_artifact_nurture_auto_view(
    raw_task: Optional[dict],
    payload: Optional[dict] = None,
    game_items_dict: Optional[dict] = None,
) -> dict:
    return _artifact_build_artifact_nurture_auto_view(
        raw_task,
        payload,
        game_items_dict,
    )


def _normalize_xinggong_starboard_target(value: object) -> str:
    return normalize_starboard_target(value)


def _is_xinggong_starboard_insufficient_reply(text: str) -> bool:
    return is_starboard_insufficient_reply(text)


def _is_xinggong_starboard_success_reply(text: str) -> bool:
    return is_starboard_success_reply(text)


def _is_xinggong_starboard_pull_command_for_target(
    command_text: str, target_star: str
) -> bool:
    return is_starboard_pull_command_for_target(command_text, target_star)


def _build_xinggong_starboard_pull_result(
    storage: Storage,
    profile,
    command_chat,
    target_star: str,
    payload: Optional[dict] = None,
) -> dict:
    miniapp_result = xinggong_miniapp.build_xinggong_starboard_payload_result(
        payload or {}
    )
    if miniapp_result:
        return miniapp_result
    if not profile or not command_chat:
        return {}
    normalized_target = _normalize_xinggong_starboard_target(target_star)
    messages = storage.list_bound_messages(
        profile_id=profile.id,
        chat_id=command_chat.chat_id,
        search_query=XINGGONG_STARBOARD_PULL_PREFIX,
        limit=120,
    )
    for message in messages:
        if int(message.get("is_bot") or 0):
            continue
        if command_chat.thread_id and int(message.get("thread_id") or 0) not in {
            int(command_chat.thread_id),
        }:
            continue
        command_text = str(message.get("text") or "").strip()
        if not _is_xinggong_starboard_pull_command_for_target(
            command_text, normalized_target
        ):
            continue
        reply = storage.get_latest_bot_reply_message(
            command_chat.chat_id,
            int(message.get("message_id") or 0),
            profile.id,
        )
        reply_text = str((reply or {}).get("text") or "").strip()
        if not reply_text:
            continue
        observed_at = float(
            (reply or {}).get("updated_at") or (reply or {}).get("created_at") or 0
        )
        observed_display = biz_fanren_game.format_timestamp(observed_at) if observed_at else ""
        if _is_xinggong_starboard_insufficient_reply(reply_text):
            return {
                "level": "error",
                "message": "修为不足，已停止自动引星盘，避免重复牵引。",
                "time_display": observed_display,
            }
        if _is_xinggong_starboard_success_reply(reply_text):
            return {
                "level": "success",
                "message": f"牵引成功：{normalized_target}",
                "time_display": observed_display,
            }
    return {}


def _build_xinggong_starboard_auto_view(raw_task: Optional[dict]) -> dict:
    return _xinggong_build_xinggong_starboard_auto_view(
        raw_task,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_wanling_roam_auto_view(
    raw_task: Optional[dict], *, min_next_run_at: float = 0.0
) -> dict:
    return _wanling_build_wanling_roam_auto_view(
        raw_task,
        min_next_run_at=min_next_run_at,
        now_ts=biz_fanren_game.time.time(),
    )


def _format_countdown_display(target_ts: float, *, ready_text: str = "已到期") -> str:
    return _countdown_format_display_for_now(
        target_ts,
        ready_text=ready_text,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_small_world_auto_view(
    raw_task: Optional[dict],
    panel_state: Optional[dict] = None,
    preach_reply: Optional[dict] = None,
) -> dict:
    return _small_world_build_small_world_auto_view(
        raw_task,
        panel_state,
        preach_reply,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_small_world_preach_auto_view(
    raw_task: Optional[dict],
    *,
    full_auto_active: bool = False,
) -> dict:
    return _small_world_build_small_world_preach_auto_view(
        raw_task,
        full_auto_active=full_auto_active,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_countdown_item(
    *,
    title: str,
    module_name: str,
    href: str,
    status: str,
    target_ts: float = 0,
    detail: str = "",
    badge: str = "",
    tone: str = "default",
    ready_text: Optional[str] = None,
) -> dict:
    return _countdown_build_item_for_now(
        title=title,
        module_name=module_name,
        href=href,
        status=status,
        target_ts=target_ts,
        detail=detail,
        badge=badge,
        tone=tone,
        ready_text=ready_text,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_cultivation_countdown_items(cultivation_session: Optional[dict]) -> list[dict]:
    return _countdown_build_cultivation_countdown_items(
        cultivation_session,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_companion_voyage_countdown_items(voyage_state: Optional[dict]) -> list[dict]:
    return _countdown_build_companion_voyage_countdown_items(
        voyage_state,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_profile_rebirth_countdown_items(rebirth_state: Optional[dict]) -> list[dict]:
    return _countdown_build_profile_rebirth_countdown_items(
        rebirth_state,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_auto_task_countdown_items(
    tasks: list[dict], *, current_sect_name: str = ""
) -> list[dict]:
    return _countdown_build_auto_task_countdown_items(
        tasks,
        current_sect_name=current_sect_name,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_xinggong_slot_countdown_items(payload: dict, starboard_task: Optional[dict]) -> list[dict]:
    return _countdown_build_xinggong_slot_countdown_items(
        payload,
        starboard_task,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_wanling_roam_state(payload: dict) -> dict:
    return _wanling_build_wanling_roam_state(
        payload,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_wanling_roam_config_view(payload: dict, raw_task: Optional[dict]) -> dict:
    return _wanling_build_wanling_roam_config_view(payload, raw_task)


def _build_wanling_roam_countdown_items(wanling_state: Optional[dict]) -> list[dict]:
    return _countdown_build_wanling_roam_countdown_items(
        wanling_state,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_sect_countdown_items(
    sect_session: Optional[dict], *, current_sect_name: str = ""
) -> list[dict]:
    return _countdown_build_sect_countdown_items(
        sect_session,
        current_sect_name=current_sect_name,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_tianxing_countdown_items(snapshot: Optional[dict]) -> list[dict]:
    return _countdown_build_tianxing_countdown_items(
        snapshot,
        now_ts=biz_fanren_game.time.time(),
    )


def _build_small_world_countdown_items(
    raw_task: Optional[dict],
    panel_state: Optional[dict] = None,
    preach_reply: Optional[dict] = None,
) -> list[dict]:
    return _countdown_build_small_world_countdown_items(
        raw_task,
        panel_state,
        preach_reply,
        now_ts=biz_fanren_game.time.time(),
    )


def _resolve_auto_feature_next_run_at(payload: dict, feature_key: str) -> Optional[float]:
    feature = COMPANION_AUTO_FEATURES.get(feature_key) or {}
    cooldown_hours = int(feature.get("cooldown_hours") or 0)
    payload_field = str(feature.get("payload_field") or "").strip()
    payload_scope = str(feature.get("payload_scope") or "companion").strip()
    if not payload_field or cooldown_hours <= 0:
        return None
    if payload_scope == "root":
        if payload_field not in payload:
            return None
        return _cooldown_target_timestamp(
            payload.get(payload_field), cooldown_hours
        ) or biz_fanren_game.time.time()
    companion_payload = _resolve_latest_companion_payload(payload)
    return _resolve_latest_companion_cooldown_target(
        companion_payload,
        payload_field,
        cooldown_hours,
    )


def _build_wild_experience_view(payload: dict, raw_task: Optional[dict]) -> dict:
    return _companion_build_wild_experience_view(
        payload,
        raw_task,
        now_ts=biz_fanren_game.time.time(),
    )


def _resolve_companion_auto_next_run_at(
    payload: dict, feature_key: str
) -> Optional[float]:
    return _resolve_auto_feature_next_run_at(payload, feature_key)


OTHER_PLAY_DEFINITIONS = [
    {
        "key": "divination",
        "title": "卜筮问天",
        "command": ".卜筮问天",
        "description": "直接占一次气运与吉凶，适合日常顺手点。",
        "type": "button",
    },
    {
        "key": "wheel",
        "title": "六道轮回盘",
        "command": ".六道轮回盘",
        "description": "先用 `.六道轮回盘` 查看下注情况，再用 `.卜卦` 按机选或自选下注。",
        "type": "button",
    },
    {
        "key": "stone",
        "title": "赌石坊",
        "command": ".赌石",
        "description": "赌石入口，历史消息里已有真实 `.赌石` 指令样例。",
        "type": "button",
    },
    {
        "key": "tianji_dice",
        "title": "天机骰",
        "template": ".押 {bet_type} {amount}",
        "description": "鬼赌坊的三骰玩法，使用 `.押 <类型> <金额>` 押大小单双、点数或豹子。",
        "type": "form",
        "fields": [
            {
                "name": "bet_type",
                "label": "押注类型",
                "type": "text",
                "placeholder": "大 / 小 / 点数7 / 豹子 / 豹子1",
            },
            {
                "name": "amount",
                "label": "灵石",
                "type": "number",
                "placeholder": "例如 100",
            },
        ],
    },
    {
        "key": "linglong_dice",
        "title": "玲珑骰",
        "template": ".对赌 {amount}",
        "description": "一对一掷骰子。历史消息样例为 `.对赌 500`，对方再用 `.应战` 接局。",
        "type": "form",
        "fields": [
            {
                "name": "amount",
                "label": "赌注灵石",
                "type": "number",
                "placeholder": "例如 500",
            }
        ],
        "extra_commands": [".应战"],
    },
    {
        "key": "mind_duel",
        "title": "神识对决",
        "template": ".神识对决 {amount}",
        "description": "21 点玩法。常见过程指令包含 `.应战`、`.凝神`、`.固元`。",
        "type": "form",
        "fields": [
            {
                "name": "amount",
                "label": "赌注灵石",
                "type": "number",
                "placeholder": "例如 500",
            }
        ],
        "extra_commands": [".应战", ".凝神", ".固元"],
    },
]

MULAN_AUTO_SUPPORT_FEATURE_KEY = mulan_feature.MULAN_AUTO_SUPPORT_FEATURE_KEY
MULAN_PANEL_COMMAND = mulan_feature.MULAN_PANEL_COMMAND
MULAN_MERIT_COMMANDS = mulan_feature.MULAN_MERIT_COMMANDS
MULAN_MERIT_EXCHANGE_FALLBACK_ITEMS = mulan_feature.MULAN_MERIT_EXCHANGE_FALLBACK_ITEMS
MULAN_SUPPORT_COMMANDS = mulan_feature.MULAN_SUPPORT_COMMANDS
MULAN_UTILITY_COMMANDS = mulan_feature.MULAN_UTILITY_COMMANDS
MULAN_WANLING_COMMANDS = mulan_feature.MULAN_WANLING_COMMANDS
MULAN_WANLING_PATROL_ROUTES = mulan_feature.MULAN_WANLING_PATROL_ROUTES
MULAN_MANUAL_COMMANDS = mulan_feature.MULAN_MANUAL_COMMANDS
MULAN_ROUTE_ACTIONS = mulan_feature.MULAN_ROUTE_ACTIONS
MULAN_VALID_SUPPORT_COMMANDS = mulan_feature.MULAN_VALID_SUPPORT_COMMANDS

TIANJI_REMNANT_COMMAND_TEXT = _tianji_remnant_command_text
TIANJI_TRIAL_COMMAND_TEXT = _tianji_trial_command_text
TIANJI_EXCHANGE_COMMAND_TEXT = _tianji_exchange_command_text
TIANJI_REMNANT_COMMANDS = _tianji_remnant_commands
TIANJI_EXCHANGE_FALLBACK_ITEMS = _tianji_exchange_fallback_items


def _get_dungeon_definition(dungeon_key: str) -> dict:
    return _dungeon_get_dungeon_definition(dungeon_key)


def _build_pagoda_view(payload: dict) -> dict:
    today_text = biz_fanren_game.time.strftime(
        "%Y-%m-%d", biz_fanren_game.time.localtime(biz_fanren_game.time.time())
    )
    return _other_build_pagoda_view(payload, today_text=today_text)


def _build_estate_miniapp_hunt_button(hunt: dict) -> dict:
    return _estate_build_estate_miniapp_hunt_button(hunt)


def _build_dongfu_view(payload: dict, game_items_dict: Optional[dict] = None) -> dict:
    return _estate_build_dongfu_view(payload, game_items_dict)


def _build_dongfu_pavilion_slots_view(
    raw_value, game_items_dict: Optional[dict] = None
) -> dict[str, str]:
    return _estate_build_dongfu_pavilion_slots_view(raw_value, game_items_dict)


def _build_estate_reply_messages(
    storage: Storage,
    profile_id: int,
    chat_id: Optional[int],
    thread_id: Optional[int] = None,
    sender_id: Optional[int] = None,
    sender_username: str = "",
    fallback_messages: Optional[list] = None,
) -> list[dict]:
    fallback = []
    for message in fallback_messages or []:
        text = str(
            message if not isinstance(message, dict) else message.get("text") or ""
        ).strip()
        if text:
            fallback.append(
                {
                    "command_text": "洞府缓存",
                    "text": text,
                    "created_at": 0,
                    "created_at_display": "-",
                }
            )
    return fallback[:3]


def _build_dice_state(
    raw_value, default_summary_keys: Optional[list[str]] = None
) -> dict:
    return _other_build_dice_state(raw_value, default_summary_keys)


def _build_ghost_gambling_view(payload: dict) -> dict:
    return _other_build_ghost_gambling_view(
        payload,
        parse_timestamp=biz_sect_game._parse_iso_timestamp,
        format_timestamp=biz_fanren_game.format_timestamp,
    )


def _build_divination_view(payload: dict) -> dict:
    today_text = biz_fanren_game.time.strftime(
        "%Y-%m-%d", biz_fanren_game.time.localtime(biz_fanren_game.time.time())
    )
    return _other_build_divination_view(
        payload,
        parse_timestamp=biz_sect_game._parse_iso_timestamp,
        format_day_from_timestamp=lambda value: biz_fanren_game.time.strftime(
            "%Y-%m-%d", biz_fanren_game.time.localtime(value)
        ),
        today_text=today_text,
    )


def _build_character_view(payload: dict) -> dict:
    return _other_build_character_view(payload)


def _build_taiyi_view(payload: dict) -> dict:
    return _other_build_taiyi_view(payload)


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


def _extract_mulan_section_lines(text: str, section_title: str) -> list[str]:
    return mulan_feature.extract_mulan_section_lines(text, section_title)


def _extract_mulan_labeled_value(lines: list[str], label: str) -> str:
    return mulan_feature.extract_mulan_labeled_value(lines, label)


def _parse_mulan_panel_text(text: str) -> dict:
    return mulan_feature.parse_mulan_panel_text(text)


def _mulan_line_value(lines: list[str], label: str) -> str:
    return mulan_feature.mulan_line_value(lines, label)


def _mulan_action_from_route_text(text: str) -> dict:
    return mulan_feature.mulan_action_from_route_text(text)


def _build_mulan_recommendation(panel_state: dict) -> dict:
    return mulan_feature.build_mulan_recommendation(panel_state)


def _build_mulan_auto_support_view(raw_task: Optional[dict], recommendation: dict) -> dict:
    return mulan_feature.build_mulan_auto_support_view(raw_task, recommendation)


def _mulan_message_matches_thread(message: dict, thread_id: Optional[int]) -> bool:
    return _mulan_message_matches_thread_impl(message, thread_id)


def _mulan_message_has_current_profile_parent(
    storage: Storage,
    *,
    message: dict,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    command_texts: set[str],
) -> bool:
    return _mulan_message_has_current_profile_parent_impl(
        storage,
        message=message,
        profile_id=profile_id,
        chat_id=chat_id,
        thread_id=thread_id,
        command_texts=command_texts,
    )


def _find_latest_mulan_message(
    storage: Storage,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    search_queries: list[str],
    command_texts: set[str],
    predicate,
) -> Optional[dict]:
    return _mulan_find_latest_mulan_message(
        storage,
        profile_id,
        chat_id,
        thread_id,
        search_queries,
        command_texts,
        predicate,
    )


def _mulan_preview_lines(text: str, limit: int = 8) -> list[str]:
    return _mulan_preview_lines_impl(text, limit)


def _is_mulan_support_ack_text(text: str) -> bool:
    return _mulan_is_mulan_support_ack_text(text)


def _build_mulan_state(
    storage: Optional[Storage] = None,
    profile=None,
    command_chat=None,
    auto_support_task: Optional[dict] = None,
) -> dict:
    return _mulan_build_mulan_state(
        storage,
        profile,
        command_chat,
        auto_support_task,
        format_timestamp=biz_fanren_game.format_timestamp,
    )


def _get_latest_tianji_remnant_reply(
    storage: Storage,
    profile,
    command_chat,
    command_text: str,
    *,
    sender_id: Optional[int],
    sender_username: str,
    predicate,
) -> Optional[dict]:
    return _tianji_get_latest_tianji_remnant_reply(
        storage,
        profile,
        command_chat,
        command_text,
        sender_id=sender_id,
        sender_username=sender_username,
        predicate=predicate,
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


def _build_other_play_view(payload: dict) -> dict:
    today_text = biz_fanren_game.time.strftime(
        "%Y-%m-%d", biz_fanren_game.time.localtime(biz_fanren_game.time.time())
    )
    return _other_build_other_play_view(
        payload,
        today_text=today_text,
        parse_timestamp=biz_sect_game._parse_iso_timestamp,
        format_timestamp=biz_fanren_game.format_timestamp,
        format_day_from_timestamp=lambda value: biz_fanren_game.time.strftime(
            "%Y-%m-%d", biz_fanren_game.time.localtime(value)
        ),
    )


def _build_divination_batch_view(raw_batch: Optional[dict]) -> dict:
    return _other_build_divination_batch_view(raw_batch)


def _build_fishing_view(
    raw_session: Optional[dict], daily_task: Optional[dict] = None
) -> dict:
    return build_fishing_view(raw_session, daily_task)


def _list_dungeon_feed_source_messages(
    storage: Storage, chat_id: int, dungeon_key: str, profile_id: Optional[int] = None
) -> list[dict]:
    return _dungeon_list_dungeon_feed_source_messages(
        storage, chat_id, dungeon_key, profile_id=profile_id
    )


def _build_dungeon_messages(
    storage: Storage,
    chat_id: int,
    dungeon_key: str,
    profile_id: Optional[int] = None,
) -> list[dict]:
    return _dungeon_build_dungeon_messages(
        storage,
        chat_id,
        dungeon_key,
        profile_id=profile_id,
        format_timestamp=biz_fanren_game.format_timestamp,
    )


def _extract_dungeon_command_buttons(dungeon_def: dict) -> list[str]:
    return _dungeon_extract_dungeon_command_buttons(dungeon_def)


def _extract_dungeon_cleanup_targets(dungeon_messages: list[dict]) -> list[dict]:
    return _dungeon_extract_dungeon_cleanup_targets(dungeon_messages)


def _clean_stock_name(raw: str) -> str:
    return _stock_clean_stock_name(raw)


def _parse_stock_market_batch(text: str, observed_at: float) -> list[dict]:
    return _stock_parse_stock_market_batch(text, observed_at)


def _build_stock_trend_points(
    history_rows: list[dict], width: int = 220, height: int = 72
) -> str:
    return _stock_build_stock_trend_points(history_rows, width=width, height=height)


def _decorate_stock_history(
    history_rows: list[dict], max_points: Optional[int] = 16
) -> dict:
    return _stock_decorate_stock_history(history_rows, max_points=max_points)


def _latest_stock_player_reply_view(
    storage: Storage, profile_id: int, command_text: str
) -> dict:
    return _stock_latest_stock_player_reply_view(
        storage,
        profile_id,
        command_text,
        format_timestamp=biz_fanren_game.format_timestamp,
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


def _resolve_stock_history_range(range_key: str) -> tuple[str, dict]:
    return _stock_resolve_stock_history_range(range_key)


def _build_stock_history_response(
    storage: Storage, stock_code: str, range_key: str
) -> dict:
    return _stock_build_stock_history_response(
        storage, stock_code, range_key, now_ts=biz_fanren_game.time.time()
    )


def _build_recent_player_options(
    storage: Storage,
    chat_id: Optional[int],
    profile_id: Optional[int] = None,
    exclude_usernames: Optional[list[str]] = None,
    limit: int = 12,
) -> list[dict]:
    return []


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


def _is_sect_related_message(text: str, current_sect_feature: Optional[dict]) -> bool:
    return _sect_is_sect_related_message(text, current_sect_feature)


def _wild_deep_time_bucket(timestamp: float) -> str:
    return _wild_deep_time_bucket_impl(timestamp)


def _build_wild_deep_log_rows(
    storage: Storage,
    profile_id: int,
    day_key: str,
    chat_id: Optional[int] = None,
) -> list[dict]:
    return _wild_deep_build_wild_deep_log_rows(
        storage,
        profile_id=profile_id,
        day_key=day_key,
        chat_id=chat_id,
    )


def _render_wild_deep_log_markdown(
    *, day_key: str, rows: list[dict], chat_id: Optional[int]
) -> str:
    return _wild_deep_render_wild_deep_log_markdown(
        day_key=day_key,
        rows=rows,
        chat_id=chat_id,
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


def _build_wild_deep_log_export_result(request: Request) -> Optional[dict]:
    return _wild_deep_build_wild_deep_log_export_result(request.query_params)


def _build_sect_daily_view(payload: dict, now=None) -> dict:
    return _sect_build_sect_daily_view(
        payload,
        now_ts=now or biz_fanren_game.time.time(),
    )


def _merge_sect_daily_view_with_session(
    daily_view: dict, sect_session: Optional[dict], now=None
) -> dict:
    return _sect_merge_sect_daily_view_with_session(
        daily_view,
        sect_session,
        now_ts=now or biz_fanren_game.time.time(),
    )


def _normalize_sect_name_text(value: str) -> str:
    return _sect_normalize_sect_name_text(value)


NO_SECT_NAMES = _sect_NO_SECT_NAMES


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


def _profile_display_label(profile) -> str:
    return _inventory_profile_display_label(profile)


def _telegram_session_file_path(storage: Storage, session_name: str) -> Optional[Path]:
    return _inventory_telegram_session_file_path(storage, session_name)


def _read_telegram_session_display_name(
    storage: Storage, profile
) -> str:
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


def _build_profile_telegram_name_map(storage: Storage, profiles: list) -> dict:
    return _inventory_build_profile_telegram_name_map(
        storage,
        profiles,
        external_account_reader=lambda profile: storage.get_external_account(
            profile.id, ASC_PROVIDER
        ),
    )


def _build_profile_inventory_search(
    storage: Storage, profiles: list, query: str
) -> dict:
    return _inventory_build_profile_inventory_search(
        profiles,
        query,
        game_items_dict=storage.get_game_items(),
        payload_reader=lambda profile: read_cached_external_payload(
            storage, profile.id, ASC_PROVIDER
        ),
    )


CULTIVATION_STAGE_CAPS = _cultivation_CULTIVATION_STAGE_CAPS

def _major_stage_rank(stage_name: str) -> int:
    return _module_major_stage_rank(stage_name)


def _is_small_world_module_available(active_profile) -> bool:
    return _module_is_small_world_module_available(active_profile)


def _is_yuanying_stage(active_profile) -> bool:
    return _module_is_yuanying_stage(active_profile)


def _payload_has_artifact_spirit(payload: Optional[dict]) -> bool:
    return _module_payload_has_artifact_spirit(payload)


SECT_METADATA = _sect_SECT_METADATA


def _format_cultivation_progress(
    stage_name: str, cultivation_points, stage_caps: Optional[dict] = None
) -> str:
    return _cultivation_format_cultivation_progress(
        stage_name,
        cultivation_points,
        stage_caps,
    )


def _extract_item_delta_lines(raw_text: str) -> list[str]:
    return _cultivation_extract_item_delta_lines(raw_text)


def _extract_adventure_lines(raw_text: str) -> list[str]:
    return _cultivation_extract_adventure_lines(raw_text)


def _build_cultivation_result_view(result: dict) -> dict:
    return _cultivation_build_cultivation_result_view(
        result,
        extract_item_delta=_extract_item_delta_lines,
        extract_adventure=_extract_adventure_lines,
    )


def _sync_all_items_if_needed(storage: Storage, cookie_text: str):
    last_sync = float(storage.get_runtime_state("last_all_items_sync") or 0)
    now = biz_fanren_game.time.time()
    if now - last_sync > 86400:
        from tg_game.clients.asc_client import get_all_items
        try:
            payload, _status = get_all_items(cookie_text)
            items = (
                payload
                if isinstance(payload, list)
                else (
                    payload.get("items")
                    or payload.get("data")
                    or list(payload.values())
                    if isinstance(payload, dict)
                    else []
                )
            )
            if items:
                storage.upsert_game_items(items)
                storage.set_runtime_state("last_all_items_sync", str(now))
        except Exception as exc:
            pass


def _sync_bootstrap_if_needed(storage: Storage, cookie_text: str):
    last_sync = float(storage.get_runtime_state("last_bootstrap_sync") or 0)
    now = biz_fanren_game.time.time()
    if now - last_sync <= 86400:
        return
    from tg_game.clients.asc_client import get_bootstrap
    try:
        payload, _status = get_bootstrap(cookie_text)
        if not isinstance(payload, dict):
            return

        wrote_items = False
        wrote_thresholds = False

        game_items_payload = payload.get("game_items") or {}
        if isinstance(game_items_payload, dict):
            items = []
            for item_id, meta in game_items_payload.items():
                if not isinstance(meta, dict):
                    continue
                items.append({"id": item_id, **meta})
            if items:
                storage.upsert_game_items_partial(items)
                wrote_items = True

        level_thresholds = payload.get("level_thresholds") or {}
        if isinstance(level_thresholds, dict) and level_thresholds:
            storage.replace_level_thresholds(level_thresholds)
            wrote_thresholds = True

        if wrote_thresholds and (wrote_items or isinstance(game_items_payload, dict)):
            storage.set_runtime_state("last_bootstrap_sync", str(now))
    except Exception:
        pass


def _sync_shop_items_if_needed(storage: Storage, cookie_text: str):
    last_sync = float(storage.get_runtime_state("last_shop_items_sync") or 0)
    now = biz_fanren_game.time.time()
    if now - last_sync <= 86400:
        return
    from tg_game.clients.asc_client import get_shop_items
    try:
        payload, _status = get_shop_items(cookie_text)
        items = (
            payload
            if isinstance(payload, list)
            else (
                payload.get("items") or payload.get("data") or list(payload.values())
                if isinstance(payload, dict)
                else []
            )
        )
        if items:
            storage.replace_shop_items(items)
            storage.set_runtime_state("last_shop_items_sync", str(now))
    except Exception:
        pass


def _sync_marketplace_listings_if_needed(storage: Storage, cookie_text: str):
    last_sync = float(storage.get_runtime_state("last_marketplace_listings_sync") or 0)
    now = biz_fanren_game.time.time()
    if now - last_sync <= 300:
        return
    from tg_game.clients.asc_client import get_all_marketplace_listings
    try:
        game_items_dict = storage.get_game_items()
        items = []
        for item in get_all_marketplace_listings(cookie_text):
            item_id = str(item.get("item_id") or "").strip()
            meta = game_items_dict.get(item_id) or {}
            items.append(
                {
                    **item,
                    "item_type": str(meta.get("type") or "").strip()
                    or ("material" if item.get("is_material") else ""),
                }
            )
        storage.replace_marketplace_listings(items)
        storage.set_runtime_state("last_marketplace_listings_sync", str(now))
    except Exception:
        pass


def _sync_profile_from_cultivator(
    storage: Storage, profile_id: int, cultivator_payload: dict
) -> None:
    profile = storage.get_profile(profile_id)
    if not profile:
        return
    game_username = (
        cultivator_payload.get("username") or profile.telegram_username or ""
    ).strip()
    sect_name = (cultivator_payload.get("sect_name") or "").strip()
    sect_position = _format_sect_position(cultivator_payload)
    sect_meta = SECT_METADATA.get(sect_name, {})
    stage_caps = {**CULTIVATION_STAGE_CAPS, **(storage.get_level_thresholds() or {})}
    storage.update_profile_game_info(
        profile_id=profile_id,
        display_name=(cultivator_payload.get("dao_name") or "").strip(),
        artifact_text=_format_external_artifacts(cultivator_payload),
        spirit_root=(cultivator_payload.get("spirit_root") or "").strip(),
        stage_name=(cultivator_payload.get("cultivation_level") or "").strip(),
        cultivation_text=_format_cultivation_progress(
            (cultivator_payload.get("cultivation_level") or "").strip(),
            cultivator_payload.get("cultivation_points"),
            stage_caps,
        ),
        poison_text=str(cultivator_payload.get("drug_poison_points") or "").strip(),
        kill_count_text=str(cultivator_payload.get("kill_count") or "").strip(),
        game_name=(cultivator_payload.get("dao_name") or "").strip(),
        account_name=(f"@{game_username.lstrip('@')}" if game_username else ""),
    )
    storage.update_profile_sect_info(
        profile_id=profile_id,
        sect_name=sect_name,
        sect_leader="",
        sect_position=sect_position,
        sect_description=sect_meta.get("description", ""),
        sect_bonus_text=sect_meta.get("bonus", ""),
        sect_contribution_text=str(
            cultivator_payload.get("sect_contribution") or ""
        ).strip(),
    )
    if game_username:
        storage.bind_profile_telegram_account(
            profile_id,
            telegram_user_id=profile.telegram_user_id,
            telegram_username=game_username,
            telegram_phone=profile.telegram_phone,
            telegram_session_name=profile.telegram_session_name,
        )


def _build_rift_failure_profile_state(
    payload: dict, cultivation_session: Optional[dict]
) -> Optional[dict]:
    status = str((payload or {}).get("status") or "").strip().upper()
    if status != "ESCAPED_SOUL":
        return None
    reason = str((cultivation_session or {}).get("rift_state") or "").strip()
    return {
        "title": "元婴遁逃·虚弱",
        "summary": reason or "当前为残魂状态，普通调度已冻结，系统正在自动夺舍重生。",
        "status": status,
        "dao_name": str((payload or {}).get("dao_name") or "").strip(),
        "stage_name": str((payload or {}).get("cultivation_level") or "").strip(),
    }
