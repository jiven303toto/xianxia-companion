from __future__ import annotations

import biz_fanren_game
import biz_sect_game
from tg_game.features.fishing import biz_fishing_daily_auto
from tg_game.web.biz_other_play_view_model import build_pagoda_today_view

from tg_game.web.biz_inventory_view_model import (
    build_inventory_bulk_sell_command,
    build_inventory_items_from_payload,
    format_market_price,
    inventory_item_matches_query,
    item_type_label,
    market_price_preview,
    market_price_sort_key,
    reverse_market_price_sort_key,
)
from tg_game.web.pagination import build_pagination_numbers


def build_module_detail_payload_view_state(
    payload: dict,
    game_items_dict: dict,
    *,
    build_character_view,
    build_taiyi_view,
    build_other_play_view,
    build_dongfu_view,
) -> dict:
    current_payload = payload or {}
    return {
        "character_state": build_character_view(current_payload),
        "taiyi_state": build_taiyi_view(current_payload),
        "other_play_state": build_other_play_view(current_payload),
        "dongfu_state": build_dongfu_view(current_payload, game_items_dict),
    }


def build_cultivation_module_state(
    storage,
    *,
    profile_id,
    enabled: bool,
    page: int = 1,
    page_size: int = 4,
    since_seconds: int = 86400,
    build_cultivation_result_view,
    build_pagination_numbers,
) -> dict:
    cultivation_page = max(int(page or 1), 1)
    state = {
        "cultivation_results": [],
        "cultivation_page": cultivation_page,
        "cultivation_page_size": page_size,
        "cultivation_total": 0,
        "cultivation_total_pages": 1,
        "cultivation_page_numbers": [1],
    }
    if not enabled or not profile_id:
        return state

    cultivation_total = storage.count_cultivation_results(
        profile_id, since_seconds=since_seconds
    )
    cultivation_total_pages = max(
        (cultivation_total + page_size - 1) // page_size,
        1,
    )
    cultivation_page = min(cultivation_page, cultivation_total_pages)
    state.update(
        {
            "cultivation_results": [
                build_cultivation_result_view(result)
                for result in storage.list_cultivation_results(
                    profile_id,
                    limit=page_size,
                    offset=(cultivation_page - 1) * page_size,
                    since_seconds=since_seconds,
                )
            ],
            "cultivation_page": cultivation_page,
            "cultivation_total": cultivation_total,
            "cultivation_total_pages": cultivation_total_pages,
            "cultivation_page_numbers": build_pagination_numbers(
                cultivation_page, cultivation_total_pages
            ),
        }
    )
    return state


def build_small_world_module_state(
    storage,
    *,
    enabled: bool,
    active_profile,
    command_chat,
    panel_command: str,
    preach_command: str,
    auto_feature_key: str,
    parse_small_world_reply,
    get_latest_command_reply_for_profile,
    build_small_world_auto_view,
    preach_auto_feature_key: str = "",
    build_small_world_preach_auto_view=None,
) -> dict:
    if not enabled:
        return {}

    reply = get_latest_command_reply_for_profile(
        active_profile,
        command_chat,
        panel_command,
    )
    small_world_state = parse_small_world_reply(
        str((reply or {}).get("text") or "").strip(),
        float((reply or {}).get("created_at") or 0),
    )
    preach_reply = get_latest_command_reply_for_profile(
        active_profile,
        command_chat,
        preach_command,
    )
    auto_task = storage.get_companion_auto_task(
        active_profile.id,
        command_chat.chat_id if command_chat else 0,
        auto_feature_key,
    )
    state = {
        "small_world_state": small_world_state,
        "small_world_auto_state": build_small_world_auto_view(
            auto_task,
            small_world_state,
            preach_reply,
        ),
    }
    if preach_auto_feature_key and build_small_world_preach_auto_view:
        state["small_world_preach_auto_state"] = build_small_world_preach_auto_view(
            storage.get_companion_auto_task(
                active_profile.id,
                command_chat.chat_id if command_chat else 0,
                preach_auto_feature_key,
            ),
            full_auto_active=bool(auto_task and auto_task.get("enabled")),
        )
    return state


def build_fishing_module_state(
    storage,
    *,
    enabled: bool,
    active_profile,
    command_chat,
    build_fishing_view,
) -> dict:
    if not enabled:
        return {}

    chat_id = command_chat.chat_id if command_chat else 0
    return {
        "fishing_state": build_fishing_view(
            storage.get_fishing_session(active_profile.id, chat_id),
            storage.get_companion_auto_task(
                active_profile.id,
                chat_id,
                biz_fishing_daily_auto.FEATURE_KEY,
            ),
        ),
    }


def build_dungeon_module_state(
    storage,
    *,
    enabled: bool,
    active_profile,
    command_chat,
    selected_dungeon: dict,
    build_dungeon_messages,
    extract_dungeon_cleanup_targets,
) -> dict:
    if not enabled or not command_chat:
        return {}

    dungeon_messages = build_dungeon_messages(
        storage,
        command_chat.chat_id,
        selected_dungeon["key"],
        profile_id=active_profile.id,
    )
    return {
        "dungeon_messages": dungeon_messages,
        "dungeon_cleanup_targets": extract_dungeon_cleanup_targets(
            dungeon_messages
        ),
    }


def build_stock_module_state(
    storage,
    *,
    enabled: bool,
    active_profile,
    command_chat,
    build_stock_view,
) -> dict:
    if not enabled:
        return {}

    command_sender_text = str(
        getattr(command_chat, "telegram_user_id", "")
        or getattr(active_profile, "telegram_user_id", "")
        or ""
    ).strip()
    return {
        "stock_state": build_stock_view(
            storage,
            active_profile.id,
            command_chat.chat_id if command_chat else None,
            command_chat.thread_id if command_chat else None,
            command_sender_id=(
                int(command_sender_text) if command_sender_text.isdigit() else None
            ),
            command_sender_username=(
                getattr(active_profile, "telegram_username", "") or ""
            ),
        ),
    }


def build_estate_module_state(
    storage,
    *,
    enabled: bool,
    active_profile,
    command_chat,
    dongfu_state: dict,
    estate_hunt_daily_auto_feature_key: str,
    build_estate_hunt_daily_auto_view,
    build_estate_reply_messages,
) -> dict:
    if not enabled:
        return {}

    profile_id = active_profile.id
    chat_id = command_chat.chat_id if command_chat else None
    thread_id = command_chat.thread_id if command_chat else None
    command_sender_text = str(
        getattr(command_chat, "telegram_user_id", "")
        or getattr(active_profile, "telegram_user_id", "")
        or ""
    ).strip()
    current_dongfu_state = dongfu_state or {}
    current_dongfu_state["messages"] = build_estate_reply_messages(
        storage,
        profile_id,
        chat_id,
        thread_id=thread_id,
        sender_id=(int(command_sender_text) if command_sender_text.isdigit() else None),
        sender_username=(getattr(active_profile, "telegram_username", "") or ""),
        fallback_messages=current_dongfu_state.get("messages") or [],
    )
    return {
        "estate_hunt_daily_auto_state": build_estate_hunt_daily_auto_view(
            storage.get_companion_auto_task(
                profile_id,
                command_chat.chat_id if command_chat else 0,
                estate_hunt_daily_auto_feature_key,
            )
        ),
        "dongfu_state": current_dongfu_state,
    }


def build_artifact_module_state(
    storage,
    payload: dict,
    game_items_dict: dict,
    *,
    enabled: bool,
    active_profile,
    command_chat,
    artifact_touch_feature_key: str,
    artifact_trial_feature_key: str,
    build_artifact_touch_auto_view,
    build_artifact_trial_auto_view,
) -> dict:
    if not enabled:
        return {}

    profile_id = active_profile.id
    chat_id = command_chat.chat_id if command_chat else 0
    return {
        "artifact_touch_auto_state": build_artifact_touch_auto_view(
            storage.get_companion_auto_task(
                profile_id,
                chat_id,
                artifact_touch_feature_key,
            )
        ),
        "artifact_trial_auto_state": build_artifact_trial_auto_view(
            storage.get_companion_auto_task(
                profile_id,
                chat_id,
                artifact_trial_feature_key,
            ),
            payload or {},
            game_items_dict,
        ),
    }


def build_sect_module_state(
    storage,
    *,
    enabled: bool,
    active_profile,
    sect_chat,
    current_sect_feature,
    sect_session,
    explore_day: str,
    build_sect_recent_reply_text,
    is_tianxing_sect_profile,
    get_tianxing_status_snapshot,
    build_tianxing_today_exploration_rewards,
) -> dict:
    if not enabled:
        return {}

    state = {
        "sect_recent_reply_text": build_sect_recent_reply_text(
            storage,
            active_profile.id,
            sect_chat,
            current_sect_feature,
            active_profile,
            fallback_text=(sect_session or {}).get("last_summary") or "",
        )
    }
    if is_tianxing_sect_profile(active_profile):
        state.update(
            {
                "tianxing_state": get_tianxing_status_snapshot(
                    storage, active_profile.id
                ),
                "tianxing_daily_rewards": build_tianxing_today_exploration_rewards(
                    storage, active_profile.id, day_key=explore_day
                ),
            }
        )
    return state


def build_other_module_state(
    storage,
    payload: dict,
    game_items_dict: dict,
    *,
    enabled: bool,
    active_profile,
    command_chat,
    companion_auto_features,
    excluded_companion_auto_feature_keys,
    artifact_touch_feature_key: str,
    artifact_trial_feature_key: str,
    mulan_auto_support_feature_key: str,
    companion_panel_command: str,
    companion_voyage_status_command: str,
    pagoda_feature_key: str,
    tianji_trial_daily_feature_key: str,
    build_divination_batch_view,
    build_recent_player_options,
    build_tianji_encounter_state,
    build_tianji_remnant_state,
    build_mulan_state,
    get_latest_command_reply_for_profile,
    build_companion_view,
    build_companion_auto_view,
    build_pagoda_auto_view,
    build_tianji_trial_daily_auto_view,
    build_wild_experience_view,
    build_companion_heart_tribulation_view,
    build_artifact_touch_auto_view,
    build_artifact_trial_auto_view,
) -> dict:
    if not enabled:
        return {}

    profile_id = active_profile.id
    chat_id = command_chat.chat_id if command_chat else None
    thread_id = command_chat.thread_id if command_chat else None
    current_payload = payload or {}
    state = {}
    if command_chat:
        state.update(
            {
                "cultivation_session": storage.get_cultivation_session(
                    command_chat.chat_id, profile_id=profile_id
                ),
                "artifact_touch_auto_state": build_artifact_touch_auto_view(
                    storage.get_companion_auto_task(
                        profile_id,
                        command_chat.chat_id,
                        artifact_touch_feature_key,
                    )
                ),
                "artifact_trial_auto_state": build_artifact_trial_auto_view(
                    storage.get_companion_auto_task(
                        profile_id,
                        command_chat.chat_id,
                        artifact_trial_feature_key,
                    ),
                    current_payload,
                    game_items_dict,
                ),
            }
        )

    divination_batch = storage.get_active_divination_batch(
        profile_id,
        chat_id=chat_id,
    ) or storage.get_latest_divination_batch(
        profile_id,
        chat_id=chat_id,
    )
    companion_reply = get_latest_command_reply_for_profile(
        active_profile, command_chat, companion_panel_command
    )
    voyage_reply = get_latest_command_reply_for_profile(
        active_profile, command_chat, companion_voyage_status_command
    )
    state.update(
        {
            "divination_batch_state": build_divination_batch_view(
                divination_batch
            ),
            "other_opponent_options": build_recent_player_options(
                storage,
                chat_id,
                profile_id=profile_id,
                exclude_usernames=[
                    getattr(active_profile, "telegram_username", "")
                ],
            ),
            "tianji_encounter_state": build_tianji_encounter_state(
                storage, profile_id, chat_id
            ),
            "tianji_remnant_state": build_tianji_remnant_state(
                storage,
                active_profile,
                command_chat,
                current_payload,
            ),
            "mulan_state": build_mulan_state(
                storage,
                active_profile,
                command_chat,
                storage.get_companion_auto_task(
                    profile_id,
                    command_chat.chat_id,
                    mulan_auto_support_feature_key,
                ),
            ),
            "companion_state": build_companion_view(
                current_payload,
                str((companion_reply or {}).get("text") or "").strip(),
                voyage_reply,
            ),
            "companion_auto_state": {
                feature_key: build_companion_auto_view(
                    storage.get_companion_auto_task(
                        profile_id,
                        command_chat.chat_id if command_chat else 0,
                        feature_key,
                    ),
                    feature_key,
                )
                for feature_key in companion_auto_features
                if feature_key not in excluded_companion_auto_feature_keys
            },
            "pagoda_auto_state": build_pagoda_auto_view(
                storage.get_companion_auto_task(
                    profile_id,
                    command_chat.chat_id if command_chat else 0,
                    pagoda_feature_key,
                )
            ),
            "pagoda_today_state": build_pagoda_today_view(
                storage,
                profile_id,
                command_chat.chat_id if command_chat else None,
            ),
            "tianji_trial_daily_auto_state": build_tianji_trial_daily_auto_view(
                storage.get_companion_auto_task(
                    profile_id,
                    command_chat.chat_id if command_chat else 0,
                    tianji_trial_daily_feature_key,
                )
            ),
            "wild_experience_state": build_wild_experience_view(
                current_payload,
                storage.get_companion_auto_task(
                    profile_id,
                    command_chat.chat_id if command_chat else 0,
                    "wild_experience",
                ),
            ),
            "companion_heart_tribulation_state": (
                build_companion_heart_tribulation_view(
                    storage.get_companion_heart_tribulation_task(
                        profile_id,
                        command_chat.chat_id if command_chat else 0,
                        thread_id=thread_id,
                    )
                )
            ),
        }
    )
    return state


def build_module_detail_default_state(
    *,
    build_tianji_remnant_state,
    build_mulan_state,
    build_companion_voyage_state,
    build_companion_auto_view,
    build_pagoda_auto_view,
    build_tianji_trial_daily_auto_view,
    build_estate_hunt_daily_auto_view,
    build_artifact_touch_auto_view,
    build_artifact_trial_auto_view,
    build_wild_experience_view,
    build_companion_heart_tribulation_view,
) -> dict:
    return {
        "stock_state": {
            "rows": [],
            "count": 0,
            "top_gainer": None,
            "top_loser": None,
            "latest_updated_at": 0,
            "latest_updated_display": "-",
            "latest_account_text": "",
            "latest_account_time_display": "-",
            "latest_task_text": "",
            "latest_task_time_display": "-",
            "tracked_stocks": [],
            "tracked_codes": [],
        },
        "tianji_encounter_state": {
            "strategy": "未知",
            "today_count": "0/2",
            "last_encounter": "暂无",
            "records": [],
        },
        "tianji_remnant_state": build_tianji_remnant_state(),
        "mulan_state": build_mulan_state(),
        "companion_state": {
            "available": False,
            "relation_title": "侍妾同行",
            "name": "-",
            "status": "-",
            "affection": 0,
            "heart_demon_value": "-",
            "current_vow": "无",
            "sworn_at_display": "-",
            "divination_chain": "-",
            "abyss_guard": "-",
            "dream_seek_display": "接口未提供",
            "dream_seek_cooldown_target": 0.0,
            "heart_tribulation_display": "接口未提供",
            "heart_tribulation_cooldown_target": 0.0,
            "divination_chain_display": "接口未提供",
            "divination_chain_cooldown_target": 0.0,
            "fragment_detail": "东0 / 南0 / 西0 / 北0",
            "cangkun_fragment_detail": "",
            "heart_tribulation_command": ".共历心劫",
            "voyage": build_companion_voyage_state(None),
        },
        "companion_auto_state": {
            "dream_seek": build_companion_auto_view(None, "dream_seek"),
            "divination_chain": build_companion_auto_view(
                None, "divination_chain"
            ),
            "companion_voyage": build_companion_auto_view(
                None, "companion_voyage"
            ),
        },
        "pagoda_auto_state": build_pagoda_auto_view(None),
        "pagoda_today_state": build_pagoda_today_view(None, 0, None),
        "tianji_trial_daily_auto_state": build_tianji_trial_daily_auto_view(None),
        "estate_hunt_daily_auto_state": build_estate_hunt_daily_auto_view(None),
        "artifact_touch_auto_state": build_artifact_touch_auto_view(None),
        "artifact_trial_auto_state": build_artifact_trial_auto_view(None),
        "wild_experience_state": build_wild_experience_view({}, None),
        "companion_heart_tribulation_state": build_companion_heart_tribulation_view(
            None
        ),
        "tianxing_state": None,
        "tianxing_daily_rewards": {"summary": {}, "entries": [], "day_key": ""},
    }


def build_sect_artifact_inventory_summary_state(
    payload: dict,
    game_items_dict: dict,
    *,
    enabled: bool,
    sect_session,
    build_sect_daily_view,
    merge_sect_daily_view_with_session,
    payload_name_summary,
    equipped_artifact_names_text,
    payload_named_entries,
    recipe_craft_name,
    build_equipped_artifact_details,
) -> dict:
    state = {
        "sect_daily_state": {
            "last_check_in_time": 0,
            "checked_in_today": False,
            "consecutive_check_in_days": 0,
            "teach_count": 0,
            "teach_progress_text": f"0/{biz_sect_game.SECT_DAILY_TEACH_LIMIT}",
        },
        "active_badge_text": "-",
        "recipes_known_text": "-",
        "formations_known_text": "-",
        "learned_techniques_text": "-",
        "equipped_artifact_name": "",
        "recipes_known_entries": [],
        "equipped_artifact_details": "未装备法宝",
    }
    if not enabled:
        return state

    current_payload = payload or {}
    recipes_known_entries = [
        {
            **entry,
            "craft_name": recipe_craft_name(entry["name"]),
        }
        for entry in payload_named_entries(
            current_payload.get("recipes_known"), game_items_dict
        )
    ]
    state.update(
        {
            "sect_daily_state": merge_sect_daily_view_with_session(
                build_sect_daily_view(current_payload), sect_session
            ),
            "active_badge_text": payload_name_summary(
                current_payload.get("active_badge"), game_items_dict
            ),
            "equipped_artifact_name": equipped_artifact_names_text(current_payload),
            "recipes_known_entries": recipes_known_entries,
            "recipes_known_text": (
                "、".join(entry["name"] for entry in recipes_known_entries)
                if recipes_known_entries
                else "-"
            ),
            "formations_known_text": payload_name_summary(
                current_payload.get("formations_known"), game_items_dict
            ),
            "learned_techniques_text": payload_name_summary(
                current_payload.get("learned_techniques"), game_items_dict
            ),
            "equipped_artifact_details": build_equipped_artifact_details(
                current_payload
            ),
        }
    )
    return state


def build_inventory_module_state(
    payload: dict,
    game_items_dict: dict,
    *,
    enabled: bool,
    query: str = "",
    page: int = 1,
    page_size: int = 60,
) -> dict:
    inventory_page = max(int(page or 1), 1)
    state = {
        "inventory_materials": {},
        "inventory_items": [],
        "inventory_trade_options": [],
        "inventory_bulk_sell_command": "",
        "inventory_page": inventory_page,
        "inventory_page_size": page_size,
        "inventory_total": 0,
        "inventory_total_pages": 1,
        "inventory_page_numbers": [1],
        "inventory_query": "",
        "equipped_id": "",
        "spirit_stones": 0,
    }
    if not enabled:
        return state

    inventory_query = str(query or "").strip()
    inventory_data = (payload or {}).get("inventory") or {}
    raw_materials = inventory_data.get("materials") or {}
    equipped_id_list = (payload or {}).get("equipped_treasure_id")
    equipped_id = (
        equipped_id_list[0]
        if equipped_id_list and isinstance(equipped_id_list, list)
        else ""
    )
    inventory_items = build_inventory_items_from_payload(payload, game_items_dict)
    inventory_all_items = list(inventory_items)
    if inventory_query:
        inventory_all_items = [
            item
            for item in inventory_all_items
            if inventory_item_matches_query(item, inventory_query)
        ]
    inventory_total = len(inventory_all_items)
    inventory_total_pages = max((inventory_total + page_size - 1) // page_size, 1)
    inventory_page = min(inventory_page, inventory_total_pages)
    inventory_start = (inventory_page - 1) * page_size

    state.update(
        {
            "inventory_items": inventory_all_items[
                inventory_start : inventory_start + page_size
            ],
            "inventory_trade_options": sorted(
                {
                    name.strip()
                    for name in [
                        *(meta.get("name", "") for meta in game_items_dict.values()),
                        "灵石",
                    ]
                    if name and name.strip()
                }
            ),
            "inventory_bulk_sell_command": build_inventory_bulk_sell_command(
                inventory_items
            ),
            "inventory_page": inventory_page,
            "inventory_total": inventory_total,
            "inventory_total_pages": inventory_total_pages,
            "inventory_page_numbers": build_pagination_numbers(
                inventory_page, inventory_total_pages
            ),
            "inventory_query": inventory_query,
            "equipped_id": equipped_id,
            "spirit_stones": raw_materials.get("mat_001", 0),
        }
    )
    return state


def build_market_module_state(
    listings: list[dict],
    game_items_dict: dict,
    *,
    enabled: bool,
    query: str = "",
    exchange_query: str = "",
    sort_key: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict:
    market_query = str(query or "").strip()
    market_exchange_query = str(exchange_query or "").strip()
    market_sort = str(sort_key or "").strip().lower()
    market_page = max(int(page or 1), 1)
    state = {
        "market_listings": [],
        "market_query": market_query,
        "market_exchange_query": market_exchange_query,
        "market_sort": market_sort,
        "market_page": market_page,
        "market_page_size": page_size,
        "market_total": 0,
        "market_total_pages": 1,
        "market_page_numbers": [1],
    }
    if not enabled:
        return state

    market_listings = []
    for item in listings:
        item_id = str(item.get("item_id") or "")
        meta = game_items_dict.get(item_id) or {}
        display_name = str(meta.get("name") or item.get("item_name") or item_id).strip()
        price_preview = market_price_preview(item.get("price_json"), game_items_dict)
        listing_time_ts = biz_sect_game._parse_iso_timestamp(item.get("listing_time"))
        market_listings.append(
            {
                **item,
                "display_name": display_name or item_id,
                "display_type": item_type_label(
                    item.get("item_type") or meta.get("type") or "",
                    is_material=bool(item.get("is_material")),
                ),
                "display_raw_type": str(item.get("item_type") or "").strip(),
                "price_text": format_market_price(
                    item.get("price_json"), game_items_dict
                ),
                "price_sort_key": market_price_sort_key(
                    item.get("price_json"), game_items_dict
                ),
                "price_preview_text": price_preview["preview_text"],
                "price_full_text": price_preview["full_text"],
                "price_item_count": price_preview["item_count"],
                "seller_display": str(item.get("seller_username") or "-").strip()
                or "-",
                "listing_time_ts": listing_time_ts,
                "listing_time_display": biz_fanren_game.format_timestamp(
                    listing_time_ts
                ),
                "is_bundle_text": "是" if item.get("is_bundle") else "否",
                "quantity_selectable": not bool(item.get("is_bundle"))
                and int(item.get("quantity") or 0) > 1,
            }
        )

    normalized_market_query = market_query.lower()
    if normalized_market_query:
        market_listings = [
            item
            for item in market_listings
            if normalized_market_query
            in " ".join(
                [
                    str(item.get("id") or ""),
                    str(item.get("display_name") or ""),
                    str(item.get("display_type") or ""),
                    str(item.get("seller_display") or ""),
                ]
            ).lower()
        ]
    normalized_exchange_query = market_exchange_query.lower()
    if normalized_exchange_query:
        market_listings = [
            item
            for item in market_listings
            if normalized_exchange_query
            in str(item.get("price_full_text") or item.get("price_text") or "").lower()
        ]
    if market_sort == "price_desc":
        market_listings.sort(
            key=lambda item: reverse_market_price_sort_key(
                item.get("price_sort_key") or ()
            )
        )
    elif market_sort == "price_asc":
        market_listings.sort(key=lambda item: item.get("price_sort_key") or ())

    market_total = len(market_listings)
    market_total_pages = max((market_total + page_size - 1) // page_size, 1)
    market_page = min(market_page, market_total_pages)
    start_index = (market_page - 1) * page_size
    end_index = start_index + page_size

    state.update(
        {
            "market_listings": market_listings[start_index:end_index],
            "market_page": market_page,
            "market_total": market_total,
            "market_total_pages": market_total_pages,
            "market_page_numbers": build_pagination_numbers(
                market_page, market_total_pages
            ),
        }
    )
    return state
