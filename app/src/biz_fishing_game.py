import json
import re
import time
from typing import Optional

FISHING_DEFAULT_POND = "青溪浅滩"
FISHING_DEFAULT_BAIT = "凡饵"
FISHING_POND_OPTIONS = [
    {"name": "青溪浅滩", "description": "门槛无，推荐凡饵"},
    {"name": "灵眼寒潭", "description": "钓术熟练度 800，推荐灵虫饵"},
    {"name": "乱星海礁", "description": "钓术熟练度 2400，推荐妖血饵"},
]
FISHING_BAIT_OPTIONS = [
    {"name": "凡饵", "description": "灵石 x12，入门鱼饵"},
    {"name": "灵米饵", "description": "灵石 x35，标准鱼饵"},
    {"name": "灵虫饵", "description": "灵石 x90，凝血草 x2"},
    {"name": "妖血饵", "description": "灵石 x220，一阶妖丹 x1"},
    {"name": "月华饵", "description": "灵石 x650，二级妖丹 x1"},
]
FISHING_BIG_FISH_PRESET = {
    "name": "大鱼优先",
    "pond": "青溪浅滩",
    "bait": "灵米饵",
    "auto_probe": True,
}
FISHING_DEFAULT_NEST = "米糠小窝"
FISHING_NEST_OPTIONS = [
    {
        "name": "米糠小窝",
        "bait_requirements": {"凡饵": 2},
        "casts": 4,
        "daily_limit": 2,
    },
    {
        "name": "灵草窝",
        "bait_requirements": {"灵米饵": 3},
        "casts": 5,
        "daily_limit": 2,
    },
    {
        "name": "妖腥窝",
        "bait_requirements": {"妖血饵": 2},
        "casts": 6,
        "daily_limit": 1,
    },
]
FISHING_DAILY_LIMIT = 20
FISHING_POLL_SECONDS = 5
FISHING_RESULT_RECOVERY_SECONDS = 3
FISHING_DAILY_REFRESH_BUFFER_SECONDS = 5 * 60
FISHING_STATUS_COMMAND = ".钓鱼状态"
FISHING_BASKET_COMMAND = ".鱼篓"
FISHING_PROBE_COMMAND = ".试探咬饵"
FISHING_HOOK_COMMAND = ".提竿"
FISHING_STOP_COMMAND = ".收竿"

FISHING_COMMAND_PREFIXES = (
    ".渔具铺",
    ".买鱼饵",
    ".钓鱼",
    ".垂钓",
    ".钓鱼状态",
    ".试探咬饵",
    ".提竿",
    ".收竿",
    ".打窝",
    ".鱼篓",
    ".我的鱼篓",
    ".鱼谱",
    ".钓鱼图鉴",
    ".钓鱼榜",
    ".开鱼",
)

def _normalize_text(text: str) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def _first_match(pattern: str, text: str) -> str:
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _first_int(pattern: str, text: str, default: int = 0) -> int:
    value = _first_match(pattern, text)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _parse_item_section(text: str, title: str) -> dict[str, int]:
    match = re.search(
        rf"{re.escape(title)}\n(?P<body>.*?)(?:\n\n|可用|$)",
        text,
        re.DOTALL,
    )
    if not match:
        return {}
    body = match.group("body")
    result: dict[str, int] = {}
    for name, count in re.findall(r"-\s*([^\nx]+?)\s*x\s*(\d+)", body):
        clean_name = name.strip()
        if clean_name:
            result[clean_name] = int(count)
    return result


def _parse_status_reply(text: str) -> dict:
    fish_signal = _first_match(r"鱼讯：([^\n]+)", text)
    daily_count = _first_int(r"今日竿数：\s*(\d+)\s*/\s*\d+", text, -1)
    daily_limit = _first_int(r"今日竿数：\s*\d+\s*/\s*(\d+)", text, 0)
    limit_reached = (
        daily_count >= 0
        and daily_limit > 0
        and daily_count >= daily_limit
    ) or ("今日竿数" in text and ("已满" in text or "上限" in text))
    countdown = _first_int(r"鱼讯倒计时：\s*(\d+)\s*秒", text)
    if not countdown:
        countdown = _first_int(r"预计\s*(\d+)\s*秒\s*内会有鱼讯", text)
    hook_remaining = _first_int(r"提竿剩余：\s*(\d+)\s*秒", text)
    if not hook_remaining:
        hook_remaining = _first_int(r"请在\s*(\d+)\s*秒\s*内\s*\.提竿", text)

    state = "idle"
    next_command = ""
    delay_seconds = 0
    if countdown:
        state = "waiting_bite"
        next_command = FISHING_STATUS_COMMAND
        delay_seconds = countdown
    elif "正口黑漂" in fish_signal or "黑漂" in text:
        state = "hook_ready"
        next_command = FISHING_HOOK_COMMAND
        delay_seconds = 0
    elif hook_remaining or "鱼在试口" in fish_signal:
        state = "probe_ready"
        next_command = FISHING_PROBE_COMMAND
        delay_seconds = 0

    return {
        "event": "status",
        "state": state,
        "fisher": _first_match(r"钓者：@?([^\n]+)", text),
        "pond": _first_match(r"鱼塘：([^\n]+)", text),
        "weather": _first_match(r"天象：([^\n]+)", text),
        "fish_signal": fish_signal,
        "progress": _first_match(r"进度：([^\n]+)", text),
        "daily_count": daily_count if daily_count >= 0 else None,
        "daily_limit": daily_limit if daily_limit > 0 else None,
        "limit_reached": limit_reached,
        "bite_countdown_seconds": countdown,
        "hook_remaining_seconds": hook_remaining,
        "next_command": next_command,
        "delay_seconds": delay_seconds,
        "raw_text": text,
    }


def _parse_basket_reply(text: str) -> dict:
    daily_count = _first_int(r"今日竿数：\s*(\d+)\s*/\s*\d+", text)
    daily_limit = _first_int(r"今日竿数：\s*\d+\s*/\s*(\d+)", text, FISHING_DAILY_LIMIT)
    current_nest = _first_match(r"当前窝料：([^\n]+)", text) or "无"
    return {
        "event": "basket",
        "rod": _first_match(r"^([^：\n]*钓竿)：([^\n]+)", text)
        or _first_match(r"^(青竹钓竿)：", text),
        "rod_status": _first_match(r"钓竿：([^\n]+)", text),
        "skill": _first_match(r"钓术：([^\n]+)", text),
        "daily_count": daily_count,
        "daily_limit": daily_limit or FISHING_DAILY_LIMIT,
        "current_nest": current_nest,
        "nest_remaining": parse_nest_remaining(current_nest),
        "baits": _parse_item_section(text, "鱼饵"),
        "nest_baits": _parse_item_section(text, "窝料"),
        "catches": _parse_item_section(text, "鱼获"),
        "raw_text": text,
    }


def parse_fishing_reply(text: str) -> Optional[dict]:
    normalized = _normalize_text(text)
    if not normalized:
        return None
    if normalized.startswith("【灵溪垂钓】"):
        return _parse_status_reply(normalized)
    if normalized.startswith("【鱼篓】"):
        return _parse_basket_reply(normalized)
    if normalized.startswith("【提竿成功】"):
        return {
            "event": "catch_success",
            "fish_name": _first_match(r"竟是一尾\s*【([^】]+)】", normalized),
            "quality": _first_match(r"品阶：([^\n]+)", normalized),
            "weight": _first_match(r"重量：([^\n]+)", normalized),
            "skill": _first_match(r"钓术：([^\n]+)", normalized),
            "raw_text": normalized,
        }
    if normalized.startswith("【空竿】"):
        return {
            "event": "empty_hook",
            "skill": _first_match(r"钓术：([^\n]+)", normalized),
            "raw_text": normalized,
        }
    if normalized.startswith("【打窝已成】"):
        return {
            "event": "nest_ready",
            "nest": _first_match(r"撒下\s*【([^】]+)】", normalized),
            "nest_uses": _first_int(r"接下来\s*(\d+)\s*竿", normalized),
            "raw_text": normalized,
        }
    active_nest = re.search(
        r"你已打下【([^】]+)】，还可影响\s*(\d+)\s*竿，不可重复叠加",
        normalized,
    )
    if active_nest:
        return {
            "event": "nest_active",
            "nest": active_nest.group(1).strip(),
            "nest_remaining": int(active_nest.group(2)),
            "raw_text": normalized,
        }
    nest_failed = re.search(r"打窝失败，资源不足：([^。\n]+)", normalized)
    if nest_failed:
        return {
            "event": "nest_failed",
            "missing": nest_failed.group(1).strip(),
            "raw_text": normalized,
        }
    if normalized.startswith("打窝失败"):
        return {
            "event": "nest_failed",
            "missing": _first_match(r"打窝失败[，,:：]?\s*([^\n。]+)", normalized),
            "raw_text": normalized,
        }
    if "窝料" in normalized and "用尽" in normalized:
        return {
            "event": "nest_daily_limit",
            "raw_text": normalized,
        }
    missing_bait = re.search(r"你的鱼篓中没有【([^】]+)】。可用\s*\.买鱼饵", normalized)
    if missing_bait:
        return {
            "event": "missing_bait",
            "bait": missing_bait.group(1).strip(),
            "raw_text": normalized,
        }
    if "今日竿数" in normalized and ("上限" in normalized or "20/20" in normalized):
        return {"event": "daily_limit", "raw_text": normalized}
    if "需要" in normalized and "钓竿" in normalized:
        return {"event": "missing_rod", "raw_text": normalized}
    return None


def is_fishing_command(text: str) -> bool:
    normalized = str(text or "").strip()
    return any(
        normalized == prefix or normalized.startswith(f"{prefix} ")
        for prefix in FISHING_COMMAND_PREFIXES
    )


def build_start_command(pond: str, bait: str) -> str:
    clean_pond = str(pond or "").strip() or FISHING_DEFAULT_POND
    clean_bait = str(bait or "").strip() or FISHING_DEFAULT_BAIT
    return f".钓鱼 {clean_pond} {clean_bait}"


def get_fishing_nest_option(name: str) -> dict:
    clean_name = str(name or "").strip() or FISHING_DEFAULT_NEST
    for option in FISHING_NEST_OPTIONS:
        if option["name"] == clean_name:
            return option
    return FISHING_NEST_OPTIONS[0]


def build_nest_command(nest: str) -> str:
    return f".打窝 {get_fishing_nest_option(nest)['name']}"


def parse_nest_remaining(current_nest: str) -> int:
    return _first_int(r"剩余\s*(\d+)\s*竿", str(current_nest or ""))


def nest_name_from_text(current_nest: str) -> str:
    text = str(current_nest or "").strip()
    if not text or text == "无":
        return ""
    return re.sub(r"（剩余\s*\d+\s*竿）$", "", text).strip()


def format_current_nest(nest: str, remaining: int) -> str:
    clean_nest = str(nest or "").strip()
    clean_remaining = max(int(remaining or 0), 0)
    if not clean_nest or clean_nest == "无" or clean_remaining <= 0:
        return "无"
    return f"{clean_nest}（剩余 {clean_remaining} 竿）"


def build_next_auto_command(session: Optional[dict], now: Optional[float] = None) -> Optional[dict]:
    from tg_game.features.fishing.biz_fishing_auto import build_next_auto_command as _build_next
    return _build_next(session, now=now)


def next_daily_refresh_at(now: Optional[float] = None) -> float:
    current_time = time.time() if now is None else float(now)
    local_time = time.localtime(current_time)
    next_day_tuple = (
        local_time.tm_year,
        local_time.tm_mon,
        local_time.tm_mday + 1,
        0,
        0,
        FISHING_DAILY_REFRESH_BUFFER_SECONDS,
        local_time.tm_wday,
        local_time.tm_yday,
        local_time.tm_isdst,
    )
    return time.mktime(next_day_tuple)


def dumps_map(value: Optional[dict]) -> str:
    return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))


def loads_map(value: object) -> dict[str, int]:
    if isinstance(value, dict):
        return {str(k): int(v or 0) for k, v in value.items()}
    text = str(value or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    result: dict[str, int] = {}
    for key, raw_count in parsed.items():
        try:
            result[str(key)] = int(raw_count or 0)
        except (TypeError, ValueError):
            result[str(key)] = 0
    return result
