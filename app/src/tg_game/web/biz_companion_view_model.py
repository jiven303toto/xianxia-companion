import re
from datetime import datetime, timedelta, timezone
from typing import Optional
import biz_small_world_game
from tg_game import pagoda_auto
from tg_game.features.estate import biz_estate_hunt_daily_auto
from tg_game.features.tianji_trial import biz_tianji_trial_daily_auto
from tg_game.features.companion.biz_companion_cooldown import (
    SIMPLE_COOLDOWN_AUTO_FEATURES,
    WILD_EXPERIENCE_FEATURE_KEY,
    WILD_EXPERIENCE_STRATEGY_OPTIONS,
    normalize_wild_experience_strategy,
)
from tg_game.features.companion.biz_companion_voyage import COMPANION_VOYAGE_FEATURE_KEY
from tg_game.features.countdowns.biz_countdowns_view_model import (
    SHANGHAI_TZ,
    format_countdown_display,
    format_datetime_display_seconds,
    format_remaining_delta,
)
from tg_game.web.biz_web_display_formatting import (
    coerce_json_dict,
    cooldown_target_timestamp,
    extract_reply_field,
    format_datetime_display,
    parse_chinese_duration_seconds,
    parse_iso_datetime,
)


COMPANION_AUTO_FEATURES = {
    pagoda_auto.FEATURE_KEY: {
        "label": "自动闯塔",
        "command": pagoda_auto.COMMAND,
    },
    **SIMPLE_COOLDOWN_AUTO_FEATURES,
    COMPANION_VOYAGE_FEATURE_KEY: {
        "label": "侍妾远航",
        "command": ".侍妾远航",
    },
    biz_small_world_game.SMALL_WORLD_AUTO_FEATURE_KEY: {
        "label": "小世界",
        "command": biz_small_world_game.SMALL_WORLD_PANEL_COMMAND,
    },
}
COMPANION_HEART_TRIBULATION_ACTIONS = ("稳", "狠", "骗")
COMPANION_PANEL_COMMAND = ".我的侍妾"
COMPANION_VOYAGE_STATUS_COMMAND = ".远航状态"
COMPANION_VOYAGE_RETURN_COMMAND = ".远航归来"
COMPANION_HEART_TRIBULATION_COMMAND = ".共历心劫"


def _now_ts(now_ts: Optional[float] = None) -> float:
    if now_ts is None:
        return datetime.now(timezone.utc).timestamp()
    return float(now_ts or 0)


def resolve_active_companion_payload_and_status(payload: dict) -> tuple[dict, str]:
    companion = coerce_json_dict((payload or {}).get("companion"))
    dongfu = coerce_json_dict((payload or {}).get("dongfu"))
    companion_residence = coerce_json_dict(dongfu.get("companion_residence"))
    if companion and not companion_residence:
        return companion, "随行"
    if companion_residence and not companion:
        return companion_residence, "洞府"
    return {}, "-"


def resolve_latest_companion_payload(payload: dict) -> dict:
    companion_payload, _status = resolve_active_companion_payload_and_status(payload)
    return companion_payload


def resolve_latest_companion_cooldown_target(
    companion_payload: dict,
    field_name: str,
    cooldown_hours: int,
) -> Optional[float]:
    normalized_field_name = str(field_name or "").strip()
    if not normalized_field_name or normalized_field_name not in companion_payload:
        return None
    raw_value = companion_payload.get(normalized_field_name)
    parsed = parse_iso_datetime(raw_value)
    if not parsed:
        return None
    end_time = parsed + timedelta(hours=max(int(cooldown_hours or 0), 0))
    return end_time.astimezone(timezone.utc).timestamp()


def format_companion_cooldown_display(
    target: Optional[float],
    *,
    now_ts: Optional[float] = None,
) -> str:
    if target is None:
        return "接口未提供"
    now = _now_ts(now_ts)
    if target <= now:
        return "可施展"
    return format_remaining_delta(target, now_ts=now)


def build_companion_voyage_state(
    voyage_reply: Optional[dict],
    *,
    now_ts: Optional[float] = None,
) -> dict:
    reply = voyage_reply or {}
    text = str(reply.get("text") or "").strip()
    created_at = float(reply.get("created_at") or 0)
    remaining_match = re.search(r"预计归航还需\s*([^\n。]+)", text)
    remaining_seconds = (
        parse_chinese_duration_seconds(remaining_match.group(1))
        if remaining_match
        else 0
    )
    target_ts = created_at + remaining_seconds if created_at and remaining_seconds else 0
    task_match = re.search(r"正在执行【([^】]+)】远航", text)
    companion_match = re.search(r"侍妾【([^】]+)】", text)
    status_text = "未查询"
    now = _now_ts(now_ts)
    if target_ts > now:
        status_text = "远航中"
    elif text:
        status_text = "可查询"
    return {
        "command": COMPANION_VOYAGE_STATUS_COMMAND,
        "status": status_text,
        "companion_name": companion_match.group(1).strip() if companion_match else "",
        "task": task_match.group(1).strip() if task_match else "",
        "target_ts": target_ts,
        "target_display": format_datetime_display_seconds(target_ts),
        "countdown_target": target_ts if target_ts > now else 0,
        "countdown_display": format_countdown_display(
            target_ts,
            ready_text=status_text,
            now_ts=now,
        ),
        "raw_text": text,
    }


def build_companion_view(
    payload: dict,
    companion_reply_text: str = "",
    voyage_reply: Optional[dict] = None,
    *,
    now_ts: Optional[float] = None,
) -> dict:
    companion_payload, status_text = resolve_active_companion_payload_and_status(payload)
    behavior_metrics = coerce_json_dict((payload or {}).get("behavior_metrics"))
    heart_vow = coerce_json_dict(companion_payload.get("heart_vow"))
    fragment_bag = coerce_json_dict(companion_payload.get("xutian_fragment_bag"))

    fragment_entries = [
        ("xutian_chart_east", "东"),
        ("xutian_chart_south", "南"),
        ("xutian_chart_west", "西"),
        ("xutian_chart_north", "北"),
    ]
    fragment_detail = " / ".join(
        f"{label}{int(fragment_bag.get(key) or 0)}" for key, label in fragment_entries
    )

    cangkun_bag = coerce_json_dict(companion_payload.get("cangkun_fragment_bag"))
    cangkun_entries = [
        ("cangkun_chart_gate", "门"),
        ("cangkun_chart_jade", "玉"),
        ("cangkun_chart_mulan", "木"),
        ("cangkun_chart_taimiao", "太"),
    ]
    cangkun_detail = " / ".join(
        f"{label}{int(cangkun_bag.get(key) or 0)}" for key, label in cangkun_entries
    )

    reply_divination_chain = extract_reply_field(companion_reply_text, "天机代卜链")
    reply_abyss_guard = extract_reply_field(companion_reply_text, "坠魔谷护持")

    divination_chain_text = str(companion_payload.get("divination_chain") or "").strip()
    abyss_guard_text = str(companion_payload.get("abyss_guard") or "").strip()

    if not divination_chain_text:
        divination_chain_text = reply_divination_chain or "接口未提供"
    if not abyss_guard_text:
        abyss_guard_text = reply_abyss_guard or "接口未提供"

    current_vow_text = str(heart_vow.get("type") or "").strip() or "无"
    companion_name = str(companion_payload.get("name") or "-").strip() or "-"
    affection_value = int(companion_payload.get("affection") or 0)
    heart_demon_value = companion_payload.get("companion_heart_demon_value")
    if heart_demon_value is None:
        heart_demon_value = companion_payload.get("heart_demon_value")
    if heart_demon_value is None:
        heart_demon_value = behavior_metrics.get("companion_heart_demon_value")
    dream_seek_target = resolve_latest_companion_cooldown_target(
        companion_payload,
        "last_dream_map_seek_time",
        8,
    )
    heart_tribulation_target = resolve_latest_companion_cooldown_target(
        companion_payload,
        "last_companion_heart_tribulation_time",
        10,
    )
    divination_chain_target = resolve_latest_companion_cooldown_target(
        companion_payload,
        "last_divination_chain_time",
        12,
    )
    now = _now_ts(now_ts)

    return {
        "available": bool(companion_payload),
        "relation_title": "侍妾同行",
        "name": companion_name,
        "status": status_text,
        "affection": affection_value,
        "heart_demon_value": (
            "-" if heart_demon_value is None else str(heart_demon_value).strip() or "-"
        ),
        "current_vow": current_vow_text,
        "sworn_at_display": format_datetime_display(heart_vow.get("sworn_at")),
        "divination_chain": divination_chain_text,
        "abyss_guard": abyss_guard_text,
        "dream_seek_display": format_companion_cooldown_display(
            dream_seek_target,
            now_ts=now,
        ),
        "dream_seek_cooldown_target": float(dream_seek_target or 0),
        "heart_tribulation_display": format_companion_cooldown_display(
            heart_tribulation_target,
            now_ts=now,
        ),
        "heart_tribulation_cooldown_target": float(heart_tribulation_target or 0),
        "divination_chain_display": format_companion_cooldown_display(
            divination_chain_target,
            now_ts=now,
        ),
        "divination_chain_cooldown_target": float(divination_chain_target or 0),
        "fragment_detail": fragment_detail,
        "cangkun_fragment_detail": cangkun_detail,
        "heart_tribulation_command": COMPANION_HEART_TRIBULATION_COMMAND,
        "voyage": build_companion_voyage_state(voyage_reply, now_ts=now),
    }


def build_companion_heart_tribulation_view(
    raw_task: Optional[dict],
    *,
    now_ts: Optional[float] = None,
) -> dict:
    task = raw_task or {}
    next_run_at = float(task.get("next_run_at") or 0)
    round1_reply = str(task.get("round1_reply") or "稳").strip() or "稳"
    round2_reply = str(task.get("round2_reply") or "稳").strip() or "稳"
    round3_reply = str(task.get("round3_reply") or "稳").strip() or "稳"
    is_active = bool(task) and bool(task.get("enabled"))
    has_error = bool(str(task.get("last_error") or "").strip())
    workflow_state = str(task.get("workflow_state") or "").strip()
    now = _now_ts(now_ts)

    def _build_settlement_entry(text: str, ts: float) -> Optional[dict]:
        normalized_text = str(text or "").strip()
        if not normalized_text:
            return None
        display_time = "-"
        if float(ts or 0) > 0:
            display_time = datetime.fromtimestamp(
                float(ts), tz=timezone.utc
            ).astimezone(SHANGHAI_TZ).strftime("%m-%d %H:%M")
        return {"text": normalized_text, "time": display_time}

    records = []
    latest_entry = _build_settlement_entry(
        task.get("last_settlement_text"), float(task.get("last_settlement_at") or 0)
    )
    previous_entry = _build_settlement_entry(
        task.get("previous_settlement_text"),
        float(task.get("previous_settlement_at") or 0),
    )
    if latest_entry:
        records.append(latest_entry)
    if previous_entry:
        records.append(previous_entry)

    next_run_display = (
        format_remaining_delta(next_run_at, now_ts=now)
        if next_run_at > 0
        else "待命"
    )
    return {
        "enabled": is_active,
        "active": is_active,
        "next_run_at": next_run_at,
        "next_run_display": next_run_display,
        "status_display": (
            format_remaining_delta(next_run_at, now_ts=now)
            if next_run_at > 0 and is_active and workflow_state in {"", "idle"}
            else (
                "进行中"
                if is_active and workflow_state and workflow_state != "idle"
                else ("已停止" if has_error else ("待命" if is_active else "未启用"))
            )
        ),
        "round1_reply": round1_reply,
        "round2_reply": round2_reply,
        "round3_reply": round3_reply,
        "round_choices_summary": f"第1轮{round1_reply} · 第2轮{round2_reply} · 第3轮{round3_reply}",
        "strategy_locked": is_active,
        "automation_state_display": (
            "运行中"
            if is_active
            else ("已停止" if has_error else "未启用")
        ),
        "action_options": list(COMPANION_HEART_TRIBULATION_ACTIONS),
        "workflow_state": workflow_state,
        "last_error": str(task.get("last_error") or "").strip(),
        "records": records,
    }


def build_companion_auto_view(
    raw_task: Optional[dict],
    feature_key: str,
    *,
    now_ts: Optional[float] = None,
) -> dict:
    feature = COMPANION_AUTO_FEATURES.get(feature_key) or {}
    task = raw_task or {}
    next_run_at = float(task.get("next_run_at") or 0)
    strategy = str(task.get("strategy") or "").strip()
    enabled = bool(task) and bool(task.get("enabled"))
    last_error = str(task.get("last_error") or "").strip()
    next_run_display = (
        format_remaining_delta(next_run_at, now_ts=_now_ts(now_ts))
        if next_run_at > 0
        else "待命"
    )
    return {
        "feature_key": feature_key,
        "label": str(feature.get("label") or feature_key),
        "command": str(feature.get("command") or "").strip(),
        "enabled": enabled,
        "active": enabled,
        "next_run_at": next_run_at,
        "next_run_display": next_run_display,
        "status_display": (
            next_run_display if next_run_at > 0 and enabled else ("已停止" if last_error else "未开启")
        ),
        "automation_state_display": (
            "运行中" if enabled else ("已停止" if last_error else "未开启")
        ),
        "strategy": strategy,
        "last_error": last_error,
    }


def build_wild_experience_view(
    payload: dict,
    raw_task: Optional[dict],
    *,
    now_ts: Optional[float] = None,
) -> dict:
    task = raw_task or {}
    feature = COMPANION_AUTO_FEATURES.get(WILD_EXPERIENCE_FEATURE_KEY) or {}
    cooldown_hours = int(feature.get("cooldown_hours") or 0)
    payload_field = str(
        feature.get("payload_field") or "last_wild_experience_time"
    ).strip()
    has_cooldown_field = payload_field in (payload or {})
    last_raw_value = (payload or {}).get(payload_field)
    cooldown_target = cooldown_target_timestamp(last_raw_value, cooldown_hours)
    next_run_at = float(task.get("next_run_at") or 0)
    active = bool(task) and bool(task.get("enabled"))
    strategy = normalize_wild_experience_strategy(task.get("strategy"))
    last_display = "-"
    last_dt = parse_iso_datetime(last_raw_value)
    if last_dt:
        last_display = last_dt.astimezone(SHANGHAI_TZ).strftime("%m-%d %H:%M")
    now = _now_ts(now_ts)
    cooldown_ready = bool(cooldown_target) and cooldown_target <= now
    if not cooldown_target and not has_cooldown_field:
        status_display = "接口未提供"
        status_prefix = "接口未提供"
    elif cooldown_target <= now:
        status_display = "可历练"
        status_prefix = "可历练"
    else:
        status_display = (
            f"冷却中，剩余{format_remaining_delta(cooldown_target, now_ts=now)}"
        )
        status_prefix = "冷却中，剩余"
    return {
        "active": active,
        "enabled": active,
        "feature_key": WILD_EXPERIENCE_FEATURE_KEY,
        "title": str(feature.get("label") or "野外历练"),
        "strategy": strategy,
        "strategy_options": list(WILD_EXPERIENCE_STRATEGY_OPTIONS),
        "command_preview": f".野外历练 {strategy}",
        "cooldown_target": float(cooldown_target or 0),
        "cooldown_ready": cooldown_ready,
        "status_display": status_display,
        "status_prefix": status_prefix,
        "last_experience_display": last_display,
        "next_run_at": next_run_at,
        "next_run_display": (
            format_remaining_delta(next_run_at, now_ts=now)
            if next_run_at > 0
            else "待命"
        ),
        "last_error": str(task.get("last_error") or "").strip(),
    }


def build_pagoda_auto_view(
    raw_task: Optional[dict],
    *,
    now_ts: Optional[float] = None,
) -> dict:
    task = raw_task or {}
    active = bool(task) and bool(task.get("enabled"))
    next_run_at = float(task.get("next_run_at") or 0)
    run_time = pagoda_auto.normalize_run_time(task.get("strategy"))
    last_error = str(task.get("last_error") or "").strip()
    next_run_display = (
        format_remaining_delta(next_run_at, now_ts=_now_ts(now_ts))
        if next_run_at > 0
        else "待命"
    )
    return {
        "feature_key": pagoda_auto.FEATURE_KEY,
        "command": pagoda_auto.COMMAND,
        "active": active,
        "enabled": active,
        "run_time": run_time,
        "next_run_at": next_run_at,
        "next_run_display": next_run_display,
        "status_display": (
            next_run_display if active and next_run_at > 0 else ("已停止" if last_error else "未开启")
        ),
        "last_error": last_error,
    }


def build_tianji_trial_daily_auto_view(
    raw_task: Optional[dict],
    *,
    now_ts: Optional[float] = None,
) -> dict:
    task = raw_task or {}
    active = bool(task) and bool(task.get("enabled"))
    next_run_at = float(task.get("next_run_at") or 0)
    run_time = biz_tianji_trial_daily_auto.normalize_run_time(task.get("strategy"))
    last_error = str(task.get("last_error") or "").strip()
    workflow_state = str(task.get("workflow_state") or "").strip()
    next_run_display = (
        format_remaining_delta(next_run_at, now_ts=_now_ts(now_ts))
        if next_run_at > 0
        else "待命"
    )
    return {
        "feature_key": biz_tianji_trial_daily_auto.FEATURE_KEY,
        "command": biz_tianji_trial_daily_auto.TRIAL_COMMAND,
        "active": active,
        "enabled": active,
        "run_time": run_time,
        "next_run_at": next_run_at,
        "next_run_display": next_run_display,
        "status_display": (
            "等待残痕刷新"
            if active and biz_tianji_trial_daily_auto.is_awaiting_remnant(workflow_state)
            else (
                next_run_display
                if active and next_run_at > 0
                else ("已停止" if last_error else "未开启")
            )
        ),
        "last_error": last_error,
    }


def build_estate_hunt_daily_auto_view(
    raw_task: Optional[dict],
    *,
    now_ts: Optional[float] = None,
) -> dict:
    task = raw_task or {}
    active = bool(task) and bool(task.get("enabled"))
    next_run_at = float(task.get("next_run_at") or 0)
    run_time = biz_estate_hunt_daily_auto.normalize_run_time(task.get("strategy"))
    last_error = str(task.get("last_error") or "").strip()
    next_run_display = (
        format_remaining_delta(next_run_at, now_ts=_now_ts(now_ts))
        if next_run_at > 0
        else "待命"
    )
    return {
        "feature_key": biz_estate_hunt_daily_auto.FEATURE_KEY,
        "command": biz_estate_hunt_daily_auto.COMMAND_LABEL,
        "active": active,
        "enabled": active,
        "run_time": run_time,
        "next_run_at": next_run_at,
        "next_run_display": next_run_display,
        "status_display": (
            next_run_display
            if active and next_run_at > 0
            else ("已停止" if last_error else "未开启")
        ),
        "last_error": last_error,
    }
