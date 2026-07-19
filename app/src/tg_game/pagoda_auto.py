from datetime import datetime, timedelta, timezone
import json
import re


SHANGHAI_TZ = timezone(timedelta(hours=8))
FEATURE_KEY = "pagoda_tower"
# 仅用于识别和取消迁移前遗留的待发送命令；新自动化不再入队该指令。
COMMAND = ".闯塔"
DEFAULT_RUN_TIME = "00:05"
PROFILE_STAGGER_SECONDS = 15
FAILED_TODAY_ERROR = "今日闯塔失败，已等待明日固定时间。"
SENT_TODAY_ERROR = "今日 MiniApp 闯塔已排队，等待明日固定时间。"
ATTEMPTED_TODAY_ERROR = "今日已闯塔，等待明日固定时间。"


def normalize_run_time(value: object) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if not match:
        return DEFAULT_RUN_TIME
    hour = int(match.group(1))
    minute = int(match.group(2))
    if hour > 23 or minute > 59:
        return DEFAULT_RUN_TIME
    return f"{hour:02d}:{minute:02d}"


def is_same_local_day(left_ts: float, right_ts: float) -> bool:
    if not left_ts or not right_ts:
        return False
    left_date = datetime.fromtimestamp(left_ts, tz=timezone.utc).astimezone(
        SHANGHAI_TZ
    ).date()
    right_date = datetime.fromtimestamp(right_ts, tz=timezone.utc).astimezone(
        SHANGHAI_TZ
    ).date()
    return left_date == right_date


def stagger_existing_next_run_at(next_run_at: float, profile_id: int) -> float:
    value = float(next_run_at or 0)
    if not value or datetime.fromtimestamp(value, tz=timezone.utc).second:
        return value
    return value + max(int(profile_id or 0) - 1, 0) * PROFILE_STAGGER_SECONDS


def resolve_next_run_at(
    run_time: object,
    *,
    now: float,
    force_tomorrow: bool = False,
    attempted_today: bool = False,
    profile_id: int = 0,
) -> float:
    normalized_time = normalize_run_time(run_time)
    hour, minute = [int(part) for part in normalized_time.split(":", 1)]
    now_local = datetime.fromtimestamp(float(now), tz=timezone.utc).astimezone(
        SHANGHAI_TZ
    )
    target_local = now_local.replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )
    if force_tomorrow or attempted_today or target_local.timestamp() <= float(now):
        target_local = target_local + timedelta(days=1)
    stagger_seconds = max(int(profile_id or 0) - 1, 0) * PROFILE_STAGGER_SECONDS
    return target_local.timestamp() + stagger_seconds


def attempted_today_from_payload(payload: dict, *, now: float) -> bool:
    progress = payload.get("pagoda_progress") if isinstance(payload, dict) else {}
    if isinstance(progress, str):
        try:
            progress = json.loads(progress)
        except json.JSONDecodeError:
            return False
    if not isinstance(progress, dict):
        return False
    last_attempt_date = str(progress.get("last_attempt_date") or "").strip()
    if not last_attempt_date:
        return False
    today_text = datetime.fromtimestamp(float(now), tz=timezone.utc).astimezone(
        SHANGHAI_TZ
    ).strftime("%Y-%m-%d")
    return last_attempt_date[:10] == today_text


def is_failed_today_reply(text: str) -> bool:
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return False
    if "今日已挑战失败" in normalized or "今天闯塔失败" in normalized:
        return True
    return "挑战失败" in normalized and "重置古塔" in normalized
