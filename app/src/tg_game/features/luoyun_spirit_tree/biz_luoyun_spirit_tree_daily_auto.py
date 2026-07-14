import re

from tg_game import pagoda_auto


FEATURE_KEY = "luoyun_spirit_tree_daily"
SECT_NAME = "落云宗"
DEFAULT_RUN_TIME = "05:30"
SENT_TODAY_ERROR = "已启动今日云梦山灵眼赛，使用公共洞府入口执行。"
COMPLETED_TODAY_ERROR = "今日云梦山灵眼赛已达目标，等待明日固定时间。"


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


def resolve_next_run_at(
    run_time: object,
    *,
    now: float,
    force_tomorrow: bool = False,
    attempted_today: bool = False,
) -> float:
    return pagoda_auto.resolve_next_run_at(
        normalize_run_time(run_time),
        now=now,
        force_tomorrow=force_tomorrow,
        attempted_today=attempted_today,
    )


def is_same_local_day(left_ts: float, right_ts: float) -> bool:
    return pagoda_auto.is_same_local_day(left_ts, right_ts)


def is_allowed_profile(profile: object) -> bool:
    sect_name = re.sub(r"[\s【】\[\]]+", "", str(getattr(profile, "sect_name", "") or ""))
    return sect_name == SECT_NAME
