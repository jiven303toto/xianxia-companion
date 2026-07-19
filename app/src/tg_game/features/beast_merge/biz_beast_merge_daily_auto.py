from tg_game import pagoda_auto


FEATURE_KEY = "beast_merge_daily"
COMMAND_LABEL = "MiniApp 噬金虫进化"
DEFAULT_RUN_TIME = pagoda_auto.DEFAULT_RUN_TIME
SENT_TODAY_ERROR = "已启动今日噬金虫进化，使用公共洞府入口执行。"
LIMIT_REACHED_ERROR = "今日噬金虫进化已达上限，等待明日固定时间。"


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
