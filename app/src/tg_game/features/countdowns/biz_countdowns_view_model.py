import math
import time
from datetime import datetime, timezone, timedelta
from typing import Optional
import biz_small_world_game
from tg_game import pagoda_auto
from tg_game.features import biz_mulan_feature as mulan_feature
from tg_game.features.artifact.biz_artifact_touch_auto import (
    ARTIFACT_TOUCH_BOT_COOLDOWN_STATE,
    ARTIFACT_TOUCH_FEATURE_KEY,
    unpack_artifact_touch_strategy,
)
from tg_game.features.artifact.biz_artifact_trial import (
    ARTIFACT_TRIAL_BOT_COOLDOWN_STATE,
    ARTIFACT_TRIAL_FEATURE_KEY,
    unpack_artifact_trial_strategy,
)
from tg_game.features.companion.biz_companion_cooldown import (
    DIVINATION_CHAIN_FEATURE_KEY,
    DREAM_SEEK_FEATURE_KEY,
    WILD_EXPERIENCE_FEATURE_KEY,
)
from tg_game.features.companion.biz_companion_voyage import (
    COMPANION_VOYAGE_FEATURE_KEY,
    normalize_companion_voyage_strategy,
)
from tg_game.features.cultivation.biz_cultivation_countdown import build_cultivation_countdown_entries
from tg_game.features.estate import biz_estate_hunt_daily_auto
from tg_game.features.luoyun_spirit_tree import biz_luoyun_spirit_tree_daily_auto
from tg_game.features.tianji_trial import biz_tianji_trial_daily_auto
from tg_game.features.tianxing.biz_tianxing_parser import get_day_key as get_tianxing_day_key
from tg_game.features.wanling.biz_wanling_roam import WANLING_ROAM_FEATURE_KEY
from tg_game.features.xinggong.biz_xinggong_star_board import (
    XINGGONG_STARBOARD_FEATURE_KEY,
    get_starboard_plots,
    iter_starboard_plot_states,
    normalize_starboard_target,
)


SHANGHAI_TZ = timezone(timedelta(hours=8))


def format_datetime_display_seconds(raw_value) -> str:
    if raw_value is None:
        return "-"
    try:
        target = float(raw_value)
    except (TypeError, ValueError):
        return "-"
    if target <= 0:
        return "-"
    return (
        datetime.fromtimestamp(target, tz=timezone.utc)
        .astimezone(SHANGHAI_TZ)
        .strftime("%Y-%m-%d %H:%M:%S")
    )


def format_remaining_delta(target_ts: float, *, now_ts: Optional[float] = None) -> str:
    now = float(now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp())
    remaining_seconds = int(float(target_ts or 0) - now)
    if remaining_seconds <= 0:
        return "可施展"
    total_minutes = math.ceil(remaining_seconds / 60)
    hours, minutes = divmod(total_minutes, 60)
    if hours <= 0:
        return f"{minutes}分钟"
    if minutes == 0:
        return f"{hours}小时"
    return f"{hours}小时{minutes}分钟"


def format_countdown_display(
    target_ts: float,
    *,
    ready_text: str = "已到期",
    now_ts: Optional[float] = None,
) -> str:
    target = float(target_ts or 0)
    now = float(now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp())
    if target <= 0:
        return ready_text
    if target <= now:
        return ready_text
    return format_remaining_delta(target, now_ts=now)


def build_countdown_item(
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
    now_ts: Optional[float] = None,
) -> dict:
    target = float(target_ts or 0)
    now = float(now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp())
    return {
        "title": title,
        "module_name": module_name,
        "href": href,
        "status": status,
        "detail": detail,
        "badge": badge,
        "tone": tone,
        "target_ts": target,
        "target_display": format_datetime_display_seconds(target),
        "countdown_target": target if target > now else 0,
        "countdown_display": format_countdown_display(
            target, ready_text=ready_text or status, now_ts=now
        ),
    }


def sort_countdown_items(items: list[dict], *, now_ts: Optional[float] = None) -> list[dict]:
    now = float(now_ts if now_ts is not None else datetime.now(timezone.utc).timestamp())
    return sorted(
        items or [],
        key=lambda item: (
            1 if float(item.get("target_ts") or 0) <= now else 0,
            float(item.get("target_ts") or 0) or 9999999999,
            str(item.get("title") or ""),
        ),
    )


def _now_ts(now_ts: Optional[float] = None) -> float:
    return float(now_ts if now_ts is not None else time.time())


def format_countdown_display_for_now(
    target_ts: float, *, ready_text: str = "已到期", now_ts: Optional[float] = None
) -> str:
    return format_countdown_display(
        target_ts,
        ready_text=ready_text,
        now_ts=_now_ts(now_ts),
    )


def build_countdown_item_for_now(
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
    now_ts: Optional[float] = None,
) -> dict:
    return build_countdown_item(
        title=title,
        module_name=module_name,
        href=href,
        status=status,
        target_ts=target_ts,
        detail=detail,
        badge=badge,
        tone=tone,
        ready_text=ready_text,
        now_ts=_now_ts(now_ts),
    )


def build_cultivation_countdown_items(
    cultivation_session: Optional[dict], *, now_ts: Optional[float] = None
) -> list[dict]:
    now = _now_ts(now_ts)
    return [
        build_countdown_item_for_now(**entry, now_ts=now)
        for entry in build_cultivation_countdown_entries(cultivation_session)
    ]


def build_companion_voyage_countdown_items(
    voyage_state: Optional[dict], *, now_ts: Optional[float] = None
) -> list[dict]:
    now = _now_ts(now_ts)
    state = voyage_state or {}
    target_ts = float(state.get("target_ts") or 0)
    if target_ts <= now:
        return []
    detail_parts = []
    companion_name = str(state.get("companion_name") or "").strip()
    task_name = str(state.get("task") or "").strip()
    if companion_name:
        detail_parts.append(companion_name)
    if task_name:
        detail_parts.append(task_name)
    return [
        build_countdown_item_for_now(
            title="侍妾远航",
            module_name="三界游历",
            href="/modules/other",
            status="归航倒计时",
            target_ts=target_ts,
            detail=" · ".join(detail_parts),
            badge="侍妾",
            tone="voyage",
            ready_text="可查询",
            now_ts=now,
        )
    ]


def build_auto_task_countdown_items(
    tasks: list[dict],
    *,
    current_sect_name: str = "",
    now_ts: Optional[float] = None,
) -> list[dict]:
    now = _now_ts(now_ts)
    items = []
    feature_meta = {
        pagoda_auto.FEATURE_KEY: ("自动闯塔", "三界游历", "/modules/other", "pagoda"),
        biz_tianji_trial_daily_auto.FEATURE_KEY: (
            "每日天机试炼",
            "三界游历",
            "/modules/other",
            "tianji-trial",
        ),
        biz_estate_hunt_daily_auto.FEATURE_KEY: (
            "每日洞府寻宝",
            "私人仙府",
            "/modules/estate",
            "estate-hunt",
        ),
        biz_luoyun_spirit_tree_daily_auto.FEATURE_KEY: (
            "每日云梦山灵眼赛",
            "宗门大殿",
            "/modules/sect",
            "luoyun-spirit-tree",
        ),
        DREAM_SEEK_FEATURE_KEY: ("自动入梦寻图", "三界游历", "/modules/other", "dream"),
        DIVINATION_CHAIN_FEATURE_KEY: ("自动天机代卜", "三界游历", "/modules/other", "divination"),
        WILD_EXPERIENCE_FEATURE_KEY: ("自动野外历练", "三界游历", "/modules/other", "wild"),
        COMPANION_VOYAGE_FEATURE_KEY: ("自动侍妾远航", "三界游历", "/modules/other", "voyage"),
        mulan_feature.MULAN_AUTO_SUPPORT_FEATURE_KEY: (
            "自动慕兰",
            "三界游历",
            "/modules/other",
            "mulan",
        ),
        ARTIFACT_TOUCH_FEATURE_KEY: (
            "自动抚摸法宝",
            "本命法宝",
            "/modules/artifact",
            "artifact",
        ),
        ARTIFACT_TRIAL_FEATURE_KEY: (
            "自动器灵试炼",
            "三界游历",
            "/modules/other",
            "artifact-trial",
        ),
        XINGGONG_STARBOARD_FEATURE_KEY: (
            "自动星辰采集",
            "宗门大殿",
            "/modules/sect",
            "starboard-auto",
        ),
        WANLING_ROAM_FEATURE_KEY: ("自动一键放养", "宗门大殿", "/modules/sect", "wanling"),
    }
    for task in tasks or []:
        if not bool(task.get("enabled")):
            continue
        feature_key = str(task.get("feature_key") or "").strip()
        if feature_key not in feature_meta:
            continue
        if (
            feature_key == ARTIFACT_TOUCH_FEATURE_KEY
            and str(task.get("workflow_state") or "").strip()
            != ARTIFACT_TOUCH_BOT_COOLDOWN_STATE
        ):
            continue
        if (
            feature_key == ARTIFACT_TRIAL_FEATURE_KEY
            and str(task.get("workflow_state") or "").strip()
            != ARTIFACT_TRIAL_BOT_COOLDOWN_STATE
        ):
            continue
        if (
            feature_key == WANLING_ROAM_FEATURE_KEY
            and str(current_sect_name or "").strip() != "万灵宗"
        ):
            continue
        if (
            feature_key == biz_luoyun_spirit_tree_daily_auto.FEATURE_KEY
            and str(current_sect_name or "").strip() != "落云宗"
        ):
            continue
        title, module_name, href, tone = feature_meta[feature_key]
        strategy = str(task.get("strategy") or "").strip()
        detail = ""
        if feature_key == pagoda_auto.FEATURE_KEY:
            detail = f"固定 {pagoda_auto.normalize_run_time(strategy)}"
        elif feature_key == biz_tianji_trial_daily_auto.FEATURE_KEY:
            detail = f"固定 {biz_tianji_trial_daily_auto.normalize_run_time(strategy)}"
        elif feature_key == biz_estate_hunt_daily_auto.FEATURE_KEY:
            detail = f"固定 {biz_estate_hunt_daily_auto.normalize_run_time(strategy)}"
        elif feature_key == biz_luoyun_spirit_tree_daily_auto.FEATURE_KEY:
            detail = (
                f"固定 {biz_luoyun_spirit_tree_daily_auto.normalize_run_time(strategy)}"
            )
        elif feature_key == WILD_EXPERIENCE_FEATURE_KEY:
            detail = f"策略 {strategy or '均衡'}"
        elif feature_key == COMPANION_VOYAGE_FEATURE_KEY:
            detail = f"航线 {normalize_companion_voyage_strategy(strategy)}"
        elif feature_key == mulan_feature.MULAN_AUTO_SUPPORT_FEATURE_KEY:
            detail = str(task.get("last_error") or "").strip() or "每日边境军功"
        elif feature_key == ARTIFACT_TOUCH_FEATURE_KEY:
            command_text, _interval_seconds = unpack_artifact_touch_strategy(strategy)
            detail = command_text
        elif feature_key == ARTIFACT_TRIAL_FEATURE_KEY:
            artifact_name, route = unpack_artifact_trial_strategy(strategy)
            detail = f"{artifact_name} · {route}"
        elif feature_key == XINGGONG_STARBOARD_FEATURE_KEY:
            detail = f"目标 {normalize_starboard_target(strategy)}"
        elif feature_key == WANLING_ROAM_FEATURE_KEY:
            detail = "巡游安抚后放养"
        items.append(
            build_countdown_item_for_now(
                title=title,
                module_name=module_name,
                href=href,
                status=(
                    "下次执行"
                    if feature_key == mulan_feature.MULAN_AUTO_SUPPORT_FEATURE_KEY
                    else "已到期"
                ),
                target_ts=float(task.get("next_run_at") or 0),
                detail=detail,
                badge="自动任务",
                tone=tone,
                ready_text=(
                    "待执行"
                    if feature_key == mulan_feature.MULAN_AUTO_SUPPORT_FEATURE_KEY
                    else None
                ),
                now_ts=now,
            )
        )
    return items


def build_xinggong_slot_countdown_items(
    payload: dict,
    starboard_task: Optional[dict],
    *,
    now_ts: Optional[float] = None,
) -> list[dict]:
    if not starboard_task or not bool(starboard_task.get("enabled")):
        return []
    if not get_starboard_plots(payload):
        return []
    now = _now_ts(now_ts)
    items = []
    for plot in iter_starboard_plot_states(payload, now=now):
        slot = str(plot.get("slot") or "").strip()
        if plot.get("empty_slot"):
            items.append(
                build_countdown_item_for_now(
                    title=f"引星盘 #{slot}",
                    module_name="宗门大殿",
                    href="/modules/sect",
                    status="可牵引",
                    detail=f"目标 {normalize_starboard_target(starboard_task.get('strategy'))}",
                    badge="星宫",
                    tone="starboard",
                    now_ts=now,
                )
            )
            continue
        star_name = str(plot.get("star_name") or "未牵引").strip() or "未牵引"
        status = str(plot.get("status") or "").strip()
        target_ts = 0.0
        cooldown_total = int(plot.get("cooldown_total") or 0)
        start_ts = float(plot.get("start_ts") or 0)
        if start_ts > 0 and cooldown_total > 0:
            target_ts = start_ts + cooldown_total
        if plot.get("needs_comfort"):
            status_text = "需安抚"
        elif plot.get("collectable"):
            status_text = "待收集"
        elif target_ts > now:
            status_text = "冷却中"
        else:
            status_text = "可牵引"
        items.append(
            build_countdown_item_for_now(
                title=f"引星盘 #{slot}",
                module_name="宗门大殿",
                href="/modules/sect",
                status=status_text,
                target_ts=target_ts,
                detail=f"{star_name} · {status or status_text}",
                badge="星宫",
                tone="starboard",
                now_ts=now,
            )
        )
    return items


def build_wanling_roam_countdown_items(
    wanling_state: Optional[dict], *, now_ts: Optional[float] = None
) -> list[dict]:
    now = _now_ts(now_ts)
    state = wanling_state or {}
    target_ts = float(state.get("next_finish_ts") or 0)
    if target_ts <= now:
        return []
    detail = f"{int(state.get('active_count') or 0)} 只灵兽放养中"
    return [
        build_countdown_item_for_now(
            title="一键放养",
            module_name="宗门大殿",
            href="/modules/sect",
            status="灵兽归来",
            target_ts=target_ts,
            detail=detail,
            badge="万灵宗",
            tone="wanling",
            ready_text="可放养",
            now_ts=now,
        )
    ]


def build_sect_countdown_items(
    sect_session: Optional[dict],
    *,
    current_sect_name: str = "",
    now_ts: Optional[float] = None,
) -> list[dict]:
    now = _now_ts(now_ts)
    sect_name = str(current_sect_name or "")
    session = sect_session or {}
    items = []
    if "阴罗宗" in sect_name:
        for spec in [
            (
                "auto_yinluo_sacrifice_enabled",
                "yinluo_sacrifice_next_check_time",
                "yinluo_sacrifice_next_check_source",
                "自动献祭",
                "下次献祭",
                "可献祭",
                "yinluo-sacrifice",
                "阴罗宗自动献祭",
            ),
            (
                "auto_yinluo_blood_wash_enabled",
                "yinluo_blood_wash_next_check_time",
                "yinluo_blood_wash_next_check_source",
                "自动血洗",
                "下次血洗",
                "可血洗",
                "yinluo-blood-wash",
                "阴罗宗自动血洗",
            ),
            (
                "auto_yinluo_shadow_enabled",
                "yinluo_shadow_next_check_time",
                "yinluo_shadow_next_check_source",
                "自动魔影",
                "下次魔影",
                "可召唤",
                "yinluo-shadow",
                "阴罗宗自动魔影",
            ),
            (
                "auto_yinluo_refine_enabled",
                "yinluo_refine_next_check_time",
                "yinluo_refine_next_check_source",
                "自动炼魂",
                "下次炼魂",
                "可炼魂",
                "yinluo-refine",
                "阴罗宗自动炼魂",
            ),
        ]:
            (
                enabled_field,
                next_field,
                source_field,
                title,
                status,
                ready_text,
                tone,
                fallback_detail,
            ) = spec
            if not session.get(enabled_field):
                continue
            detail = str(session.get(source_field) or "").strip() or fallback_detail
            items.append(
                build_countdown_item_for_now(
                    title=title,
                    module_name="宗门大殿",
                    href="/modules/sect",
                    status=status,
                    target_ts=float(session.get(next_field) or 0),
                    detail=detail,
                    badge="自动任务",
                    tone=tone,
                    ready_text=ready_text,
                    now_ts=now,
                )
            )
        return items
    if "元婴宗" not in sect_name:
        return []
    if session.get("auto_yuanying_wendao_enabled"):
        detail = (
            str(session.get("yuanying_wendao_next_check_source") or "").strip()
            or "元婴宗自动问道"
        )
        items.append(
            build_countdown_item_for_now(
                title="自动问道",
                module_name="宗门大殿",
                href="/modules/sect",
                status="下次问道",
                target_ts=float(session.get("yuanying_wendao_next_check_time") or 0),
                detail=detail,
                badge="自动任务",
                tone="yuanying-wendao",
                ready_text="可问道",
                now_ts=now,
            )
        )
    if session.get("auto_yuanying_retreat_enabled"):
        detail = (
            str(session.get("yuanying_retreat_next_check_source") or "").strip()
            or str(session.get("yuanying_retreat_state") or "").strip()
            or "元婴宗自动闭关"
        )
        items.append(
            build_countdown_item_for_now(
                title="自动元婴闭关",
                module_name="三界游历",
                href="/modules/other",
                status="下次执行",
                target_ts=float(session.get("yuanying_retreat_next_check_time") or 0),
                detail=detail,
                badge="自动任务",
                tone="yuanying-retreat",
                ready_text="立即执行",
                now_ts=now,
            )
        )
    return items


def build_tianxing_countdown_items(
    snapshot: Optional[dict], *, now_ts: Optional[float] = None
) -> list[dict]:
    data = snapshot or {}
    if not data:
        return []
    state = data.get("state") or {}
    config = data.get("config") or {}
    items = []
    now = _now_ts(now_ts)
    if (
        config.get("timeline_enabled")
        or config.get("auto_observe_enabled")
        or config.get("auto_set_star_enabled")
    ):
        today_key = get_tianxing_day_key(now)
        has_today_observe = (
            str(state.get("observed_stars_day") or "") == today_key
            and (
                bool(state.get("observed_stars") or [])
                or float(state.get("observed_stars_at") or 0) > 0
            )
        )
        next_day = datetime.fromtimestamp(now, tz=SHANGHAI_TZ).date() + timedelta(
            days=1
        )
        next_midnight = datetime(
            next_day.year,
            next_day.month,
            next_day.day,
            tzinfo=SHANGHAI_TZ,
        ).timestamp()
        items.append(
            build_countdown_item_for_now(
                title="每日观命",
                module_name="宗门大殿",
                href="/modules/sect",
                status="刷新时间",
                target_ts=next_midnight if has_today_observe else 0,
                detail=(
                    "今日观命已完成，零点后需重新观命"
                    if has_today_observe
                    else "今日还没有观命结果"
                ),
                badge="天星宗",
                tone="tianxing-observe",
                ready_text="需重新观命",
                now_ts=now,
            )
        )
    if not (config.get("timeline_enabled") or config.get("auto_predict_enabled")):
        return items
    current_prediction = str(state.get("current_prediction") or "").strip()
    prediction_source = str(state.get("current_prediction_until_source") or "").strip()
    prediction_until = (
        float(state.get("current_prediction_until") or 0)
        if current_prediction == "探索" and prediction_source == "panel"
        else 0
    )
    if current_prediction == "探索":
        detail = "当前推命: 探索，来自天机盘"
        predict_ready_text = "需重新推命"
        if prediction_source != "panel":
            detail = "当前推命: 探索，需天机盘校准倒计时"
            predict_ready_text = "需天机盘校准"
        elif prediction_until <= now:
            detail = "当前推命: 探索，已到期后需重新推命"
    elif current_prediction:
        detail = f"当前推命: {current_prediction}，探索需重新推命"
        predict_ready_text = "需重新推命"
    else:
        detail = "当前没有有效推命 探索"
        predict_ready_text = "需重新推命"
    items.append(
        build_countdown_item_for_now(
            title="推命探索",
            module_name="宗门大殿",
            href="/modules/sect",
            status="到期时间",
            target_ts=prediction_until,
            detail=detail,
            badge="天星宗",
            tone="tianxing-predict",
            ready_text=predict_ready_text,
            now_ts=now,
        )
    )
    current_change = str(state.get("current_change") or "").strip()
    change_source = str(state.get("current_change_until_source") or "").strip()
    change_until = (
        float(state.get("current_change_until") or 0)
        if current_change == "探索" and change_source == "panel"
        else 0
    )
    if current_change == "探索":
        change_detail = "当前改命: 探索，来自天机盘"
        change_ready_text = "需重新改命"
        if change_source != "panel":
            change_detail = "当前改命: 探索，需天机盘校准倒计时"
            change_ready_text = "需天机盘校准"
        elif change_until <= now:
            change_detail = "当前改命: 探索，已到期后需重新改命"
    elif current_change:
        change_detail = f"当前改命: {current_change}，探索需重新改命"
        change_ready_text = "需重新改命"
    else:
        change_detail = "当前没有有效改命 探索"
        change_ready_text = "需重新改命"
    items.append(
        build_countdown_item_for_now(
            title="改命探索",
            module_name="宗门大殿",
            href="/modules/sect",
            status="到期时间",
            target_ts=change_until,
            detail=change_detail,
            badge="天星宗",
            tone="tianxing-change",
            ready_text=change_ready_text,
            now_ts=now,
        )
    )
    return items


def build_small_world_countdown_items(
    raw_task: Optional[dict],
    panel_state: Optional[dict] = None,
    preach_reply: Optional[dict] = None,
    *,
    now_ts: Optional[float] = None,
) -> list[dict]:
    now = _now_ts(now_ts)
    task = raw_task or {}
    panel = panel_state or {}
    items = []
    if task and bool(task.get("enabled")):
        items.append(
            build_countdown_item_for_now(
                title="自动小世界",
                module_name="小世界",
                href="/modules/small_world",
                status="下次检查",
                target_ts=float(task.get("next_run_at") or 0),
                detail=str(task.get("last_error") or "").strip(),
                badge="自动任务",
                tone="small-world-auto",
                ready_text="待执行",
                now_ts=now,
            )
        )

    panel_created_at = float(panel.get("created_at") or 0)
    prayer_cooldown_seconds = int(panel.get("prayer_cooldown_seconds") or 0)
    prayer_target = (
        panel_created_at + prayer_cooldown_seconds
        if panel_created_at and prayer_cooldown_seconds
        else 0
    )
    if prayer_target > now:
        prayer_title = str(panel.get("prayer_title") or "").strip()
        items.append(
            build_countdown_item_for_now(
                title="祈愿感应",
                module_name="小世界",
                href="/modules/small_world",
                status="祈愿倒计时",
                target_ts=prayer_target,
                detail=prayer_title,
                badge="小世界",
                tone="small-world-prayer",
                ready_text="可显灵",
                now_ts=now,
            )
        )

    preach_text = str((preach_reply or {}).get("text") or "").strip()
    preach_created_at = float((preach_reply or {}).get("created_at") or 0)
    preach_cooldown_seconds = biz_small_world_game.parse_miracle_preach_cooldown_seconds(
        preach_text
    )
    preach_target = (
        preach_created_at + preach_cooldown_seconds
        if preach_created_at and preach_cooldown_seconds
        else 0
    )
    if preach_target > now:
        items.append(
            build_countdown_item_for_now(
                title="神迹布道",
                module_name="小世界",
                href="/modules/small_world",
                status="布道冷却",
                target_ts=preach_target,
                detail="来自 .神迹 布道 回包",
                badge="小世界",
                tone="small-world-preach",
                ready_text="可布道",
                now_ts=now,
            )
        )
    return items
