from tg_game.services.external_sync import ASC_PROVIDER, read_cached_external_payload
from tg_game.storage import CompatDb, Storage
from tg_game.features.wanling.biz_wanling_roam import (
    WANLING_ROAM_AUTO_AFTER_RETURN_SECONDS,
    WANLING_ROAM_FEATURE_KEY,
    build_wanling_roam_command_sequence,
)
from tg_game.features.xinggong.biz_xinggong_star_board import XINGGONG_STARBOARD_FEATURE_KEY
import biz_fanren_game
import biz_sect_game
from tg_game.web.app_helpers import (
    _build_rift_failure_profile_state,
    _build_wanling_roam_auto_view,
    _build_wanling_roam_config_view,
    _build_wanling_roam_state,
    _build_xinggong_starboard_pull_result,
    _normalize_xinggong_starboard_target,
)


def load_profile_card_state(
    storage: Storage,
    active_profile,
    *,
    refresh_external: bool = True,
    should_refresh_cultivator_payload,
    refresh_cultivator_payload,
    get_primary_command_chat,
    resolve_current_sect_feature,
    build_xinggong_state,
) -> dict:
    if not active_profile:
        return {
            "active_profile": None,
            "external_account": None,
            "payload": {},
            "cultivation_session": None,
            "rift_failure_state": None,
            "current_sect_feature": None,
            "sect_chat": None,
            "sect_session": None,
            "lingxiao_state": None,
            "yinluo_state": None,
            "huangfeng_state": None,
            "wanling_state": None,
            "luoyun_state": None,
            "xinggong_state": None,
            "yuanying_sect_state": None,
        }

    profile = storage.get_profile(active_profile.id) or active_profile
    external_account = storage.get_external_account(profile.id, ASC_PROVIDER)
    should_refresh = refresh_external and shouldrefresh_cultivator_payload(
        profile, external_account
    )
    payload = (
        refresh_cultivator_payload(profile.id)
        if should_refresh
        else read_cached_external_payload(storage, profile.id, ASC_PROVIDER)
    )
    profile = storage.get_profile(profile.id) or profile
    external_account = storage.get_external_account(profile.id, ASC_PROVIDER)
    cultivation_chat = get_primary_command_chat(
        profile.id, biz_fanren_game.FANREN_BOT_USERNAME
    )
    cultivation_session = (
        storage.get_cultivation_session(
            cultivation_chat.chat_id, profile_id=profile.id
        )
        if cultivation_chat
        else None
    )
    rift_failure_state = _build_rift_failure_profile_state(
        payload, cultivation_session
    )
    current_sect_feature = resolve_current_sect_feature(profile)
    sect_chat = storage.get_primary_chat_binding(
        profile.id, bot_username=biz_sect_game.SECT_BOT_USERNAME
    ) or storage.get_primary_chat_binding(profile.id)
    sect_session = (
        storage.get_sect_session(sect_chat.chat_id, profile_id=profile.id)
        if sect_chat
        else None
    )
    lingxiao_state = None
    yinluo_state = None
    huangfeng_state = None
    wanling_state = None
    luoyun_state = None
    xinggong_state = None
    yuanying_sect_state = None
    if current_sect_feature and current_sect_feature["name"] == "凌霄宫":
        if sect_chat:
            db = CompatDb(storage)
            try:
                biz_sect_game.ensure_tables(db)
                sect_session, _ = biz_sect_game.sync_lingxiao_trial_state(
                    storage,
                    db,
                    profile.id,
                    sect_chat.chat_id,
                    payload=payload,
                )
            finally:
                db.close()
        lingxiao_state = biz_sect_game.build_lingxiao_view(
            payload,
            session=sect_session,
            sect_position=profile.sect_position,
        )
    if current_sect_feature and current_sect_feature["name"] == "阴罗宗":
        banner_reply = None
        summon_shadow_reply = None
        if sect_chat:
            db = CompatDb(storage)
            try:
                biz_sect_game.ensure_tables(db)
                sect_session, yinluo_state = biz_sect_game.sync_yinluo_state(
                    storage,
                    db,
                    profile.id,
                    sect_chat.chat_id,
                    payload=payload,
                )
            finally:
                db.close()
        if yinluo_state is None:
            yinluo_state = biz_sect_game.build_yinluo_view(
                payload,
                session=sect_session,
                banner_text=(banner_reply or {}).get("text") or "",
                summon_shadow_reply=summon_shadow_reply,
            )
        else:
            yinluo_state = biz_sect_game.build_yinluo_view(
                payload,
                session=sect_session,
                banner_text=(banner_reply or {}).get("text") or "",
                summon_shadow_reply=summon_shadow_reply,
            )
    if current_sect_feature and current_sect_feature["name"] == "黄枫谷":
        if sect_chat:
            db = CompatDb(storage)
            try:
                biz_sect_game.ensure_tables(db)
                sect_session, huangfeng_state = biz_sect_game.sync_huangfeng_state(
                    storage,
                    db,
                    profile.id,
                    sect_chat.chat_id,
                    payload=payload,
                )
            finally:
                db.close()
        if huangfeng_state is None:
            huangfeng_state = biz_sect_game.build_huangfeng_view(
                payload,
                session=sect_session,
            )
    if current_sect_feature and current_sect_feature["name"] == "万灵宗":
        wanling_auto_task = (
            storage.get_companion_auto_task(
                profile.id,
                sect_chat.chat_id if sect_chat else 0,
                WANLING_ROAM_FEATURE_KEY,
            )
            if sect_chat
            else None
        )
        wanling_state = _build_wanling_roam_state(payload)
        wanling_state["roam_config"] = _build_wanling_roam_config_view(
            payload, wanling_auto_task
        )
        wanling_state["roam_auto_state"] = _build_wanling_roam_auto_view(
            wanling_auto_task,
            min_next_run_at=(
                float(wanling_state.get("next_finish_ts") or 0)
                + WANLING_ROAM_AUTO_AFTER_RETURN_SECONDS
            ),
        )
        wanling_state["roam_command_sequence"] = list(
            build_wanling_roam_command_sequence(
                (wanling_auto_task or {}).get("strategy"), payload
            )
        )
    if current_sect_feature and current_sect_feature["name"] == "落云宗":
        if sect_chat:
            db = CompatDb(storage)
            try:
                biz_sect_game.ensure_tables(db)
                sect_session, luoyun_state = biz_sect_game.sync_luoyun_state(
                    storage,
                    db,
                    profile.id,
                    sect_chat.chat_id,
                    payload=payload,
                )
            finally:
                db.close()
        if luoyun_state is None:
            luoyun_state = biz_sect_game.build_luoyun_view(
                payload,
                session=sect_session,
            )
    if current_sect_feature and current_sect_feature["name"] == "星宫":
        starboard_auto_task = (
            storage.get_companion_auto_task(
                profile.id,
                sect_chat.chat_id if sect_chat else 0,
                XINGGONG_STARBOARD_FEATURE_KEY,
            )
            if sect_chat
            else None
        )
        starboard_target = _normalize_xinggong_starboard_target(
            (starboard_auto_task or {}).get("strategy")
        )
        starboard_pull_result = _build_xinggong_starboard_pull_result(
            storage,
            profile,
            sect_chat,
            starboard_target,
            payload,
        )
        xinggong_state = build_xinggong_state(
            payload,
            profile,
            sect_session,
            starboard_auto_task,
            starboard_pull_result,
        )
    if current_sect_feature and current_sect_feature["name"] == "元婴宗":
        yuanying_sect_state = biz_sect_game.build_yuanying_sect_view(sect_session)

    return {
        "active_profile": profile,
        "external_account": external_account,
        "payload": payload,
        "cultivation_session": cultivation_session,
        "rift_failure_state": rift_failure_state,
        "current_sect_feature": current_sect_feature,
        "sect_chat": sect_chat,
        "sect_session": sect_session,
        "lingxiao_state": lingxiao_state,
        "yinluo_state": yinluo_state,
        "huangfeng_state": huangfeng_state,
        "wanling_state": wanling_state,
        "luoyun_state": luoyun_state,
        "xinggong_state": xinggong_state,
        "yuanying_sect_state": yuanying_sect_state,
    }
