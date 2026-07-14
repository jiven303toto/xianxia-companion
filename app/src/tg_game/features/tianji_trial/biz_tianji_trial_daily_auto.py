from tg_game import pagoda_auto

from .biz_tianji_trial_miniapp import TIANJI_REMNANT_COMMAND, TIANJI_TRIAL_COMMAND
from .biz_tianji_trial_remnant_view import tianji_remnant_fraction


FEATURE_KEY = "tianji_trial_daily"
REMNANT_COMMAND = TIANJI_REMNANT_COMMAND
TRIAL_COMMAND = TIANJI_TRIAL_COMMAND
DEFAULT_RUN_TIME = pagoda_auto.DEFAULT_RUN_TIME
AWAIT_REMNANT_STATE = "await_remnant"
REMNANT_REPLY_RECHECK_SECONDS = 10
REMNANT_REPLY_TIMEOUT_SECONDS = 90
SENT_TODAY_ERROR = "已启动今日天机试炼，使用洞府公共入口执行。"
LIMIT_REACHED_ERROR = "今日天机试炼已达上限，等待明日固定时间。"
AWAIT_REMNANT_ERROR = "已发送天机残痕，等待刷新今日上限。"


def normalize_run_time(value: object) -> str:
    return pagoda_auto.normalize_run_time(value)


def resolve_next_run_at(
    run_time: object,
    *,
    now: float,
    force_tomorrow: bool = False,
    attempted_today: bool = False,
) -> float:
    return pagoda_auto.resolve_next_run_at(
        run_time,
        now=now,
        force_tomorrow=force_tomorrow,
        attempted_today=attempted_today,
    )


def is_same_local_day(left_ts: float, right_ts: float) -> bool:
    return pagoda_auto.is_same_local_day(left_ts, right_ts)


def pack_await_remnant_state(started_at: float) -> str:
    return f"{AWAIT_REMNANT_STATE}:{float(started_at or 0):.3f}"


def unpack_await_remnant_started_at(value: object) -> float:
    text = str(value or "").strip()
    if text == AWAIT_REMNANT_STATE:
        return 0.0
    prefix = f"{AWAIT_REMNANT_STATE}:"
    if not text.startswith(prefix):
        return 0.0
    try:
        return float(text[len(prefix) :])
    except ValueError:
        return 0.0


def is_awaiting_remnant(value: object) -> bool:
    return str(value or "").strip().startswith(AWAIT_REMNANT_STATE)


def is_daily_limit_reached(remnant_state: dict) -> bool:
    entry_used, entry_limit = tianji_remnant_fraction(
        (remnant_state or {}).get("entry_count")
    )
    completed_used, completed_limit = tianji_remnant_fraction(
        (remnant_state or {}).get("completed_count")
    )
    return (
        entry_limit > 0
        and entry_used >= entry_limit
        or completed_limit > 0
        and completed_used >= completed_limit
    )
