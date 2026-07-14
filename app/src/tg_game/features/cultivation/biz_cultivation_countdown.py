import re
from typing import Optional


FANREN_CHECK_COMMAND = ".查看闭关"
FANREN_NORMAL_COMMAND = ".闭关修炼"
FANREN_DEEP_COMMAND = ".深度闭关"
FANREN_DEFAULT_MODE = "normal"
FANREN_DEFAULT_INTERVAL = 300
FANREN_COMMAND_COOLDOWN = 30
FANREN_MIN_INTERVAL = 30

YUANYING_STATUS_COMMAND = ".元婴状态"
YUANYING_OUTING_COMMAND = ".元婴出窍"
YUANYING_OUTING_COOLDOWN_SECONDS = 28800
YUANYING_SUCCESS_KEYWORDS = (
    "元婴化作一道流光飞出",
    "元婴出窍",
    "云游",
)
YUANYING_RETURNED_KEYWORDS = (
    "归窍总结",
    "元神归窍",
    "已归来",
)
YUANYING_READY_KEYWORDS = (
    "窍中温养",
)
YUANYING_STILL_OUT_KEYWORDS = (
    "无法分身",
    "正在执行",
)

COOLDOWN_PATTERNS = (
    re.compile(r"(?P<value>\d+)\s*小时"),
    re.compile(r"(?P<value>\d+)\s*分钟"),
    re.compile(r"(?P<value>\d+)\s*秒"),
)

COUNTDOWN_SOURCE_LABELS = {
    "deep_seclusion_end_time": "深度闭关结束",
    "cultivation_cooldown_until": "修炼冷却结束",
}


def clamp_interval(seconds: object) -> int:
    return max(int(seconds), FANREN_MIN_INTERVAL)


def parse_cooldown_seconds(text: str) -> Optional[int]:
    total = 0
    matched = False
    for pattern in COOLDOWN_PATTERNS:
        for match in pattern.finditer(text or ""):
            value = int(match.group("value"))
            unit = match.group(0)
            matched = True
            if "小时" in unit:
                total += value * 3600
            elif "分钟" in unit:
                total += value * 60
            else:
                total += value
    return total if matched else None


def parse_yuanying_status_reply(text: str) -> tuple[str, Optional[int]]:
    normalized = (text or "").strip()
    if not normalized:
        return "unknown", None

    for keyword in YUANYING_RETURNED_KEYWORDS:
        if keyword in normalized:
            return "settled", 0

    for keyword in YUANYING_READY_KEYWORDS:
        if keyword in normalized:
            return "ready", 0

    cooldown = parse_cooldown_seconds(normalized)
    for keyword in YUANYING_STILL_OUT_KEYWORDS:
        if keyword in normalized:
            return "out", cooldown

    if cooldown:
        return "out", cooldown

    return "unknown", None


def parse_yuanying_reply(text: str) -> tuple[bool, Optional[int]]:
    normalized = (text or "").strip()
    if not normalized:
        return False, None
    status, _status_cooldown = parse_yuanying_status_reply(normalized)
    if "你的本命元婴" in normalized and status != "unknown":
        return False, None
    has_success = any(keyword in normalized for keyword in YUANYING_SUCCESS_KEYWORDS)
    has_failure = (
        ("失败" in normalized or "无法" in normalized or "不可" in normalized)
        and ("元婴" in normalized or "出窍" in normalized)
    )
    if not has_success and not has_failure:
        return False, None
    cooldown = parse_cooldown_seconds(normalized)
    for keyword in YUANYING_SUCCESS_KEYWORDS:
        if keyword in normalized:
            return True, cooldown or YUANYING_OUTING_COOLDOWN_SECONDS
    if has_failure:
        return False, cooldown
    return False, cooldown


def is_countdown_due(session: dict, field_name: str, now: float) -> bool:
    try:
        next_time = float((session or {}).get(field_name) or 0)
    except (TypeError, ValueError):
        next_time = 0.0
    return next_time <= float(now)


def compute_cycle_next_check(
    now: float, session: dict, *, is_status_check: bool = False
) -> float:
    base_interval = int((session or {}).get("interval_seconds") or FANREN_DEFAULT_INTERVAL)
    min_interval = max(base_interval, FANREN_COMMAND_COOLDOWN, FANREN_MIN_INTERVAL)
    return now + min_interval


def normal_retry_seconds(cooldown_seconds: object, fallback_seconds: object) -> int:
    base = cooldown_seconds or fallback_seconds
    return max(int(base), 0) + 60


def build_cultivation_countdown_entries(cultivation_session: Optional[dict]) -> list[dict]:
    session = cultivation_session or {}
    if not session:
        return []
    entries = []
    mode_label = (
        "深度闭关"
        if str(session.get("retreat_mode") or "").strip().lower() == "deep"
        else "普通闭关"
    )
    source_text = str(session.get("next_check_source") or "").strip()
    source_label = COUNTDOWN_SOURCE_LABELS.get(source_text, source_text)
    if bool(session.get("enabled")):
        detail_parts = [mode_label]
        if source_label:
            detail_parts.append(source_label)
        entries.append(
            {
                "title": "本命修为调度",
                "module_name": "闭关洞府",
                "href": "/modules/cultivation",
                "status": "下次调度",
                "target_ts": float(session.get("next_check_time") or 0),
                "detail": " · ".join(detail_parts),
                "badge": "自动闭关",
                "tone": "cultivation",
                "ready_text": "已到期",
            }
        )
    if bool(session.get("auto_rift_enabled")):
        rift_state = str(session.get("rift_state") or "").strip()
        entries.append(
            {
                "title": "自动探寻裂缝",
                "module_name": "闭关洞府",
                "href": "/modules/cultivation",
                "status": "下次执行",
                "target_ts": float(session.get("rift_next_check_time") or 0),
                "detail": rift_state,
                "badge": "自动任务",
                "tone": "rift",
                "ready_text": rift_state or "立即执行",
            }
        )
    if bool(session.get("auto_yuanying_enabled")):
        yuanying_state = str(session.get("yuanying_state") or "").strip()
        entries.append(
            {
                "title": "自动元婴出窍",
                "module_name": "闭关洞府",
                "href": "/modules/cultivation",
                "status": "下次执行",
                "target_ts": float(session.get("yuanying_next_check_time") or 0),
                "detail": yuanying_state,
                "badge": "自动任务",
                "tone": "yuanying",
                "ready_text": yuanying_state or "立即执行",
            }
        )
    return entries
