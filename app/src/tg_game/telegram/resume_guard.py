import logging

from tg_game.storage import (
    Storage,
    telegram_resume_gap_state_key,
    telegram_resume_until_state_key,
    telegram_worker_heartbeat_state_key,
)
from tg_game.telegram.network_guard import (
    finish_network_pause_window,
    get_network_pause_started_at,
    get_network_pause_until,
)


logger = logging.getLogger(__name__)

TELEGRAM_RESUME_OFFLINE_GAP_SECONDS = 15 * 60
TELEGRAM_RESUME_MODE_SECONDS = 30 * 60
TELEGRAM_WORKER_HEARTBEAT_SECONDS = 15
TELEGRAM_RESUME_SETTLE_SECONDS = 1
TELEGRAM_LONG_RESUME_SECONDS = 4 * 3600
TELEGRAM_LONG_RESUME_DEFER_SECONDS = 15 * 60
TELEGRAM_RESUME_COUNTDOWN_SPACING_SECONDS = 60


def read_profile_worker_heartbeat(storage: Storage, profile_id: int) -> float:
    try:
        return float(
            storage.get_runtime_state(telegram_worker_heartbeat_state_key(profile_id))
            or 0
        )
    except (TypeError, ValueError):
        return 0.0


def write_profile_worker_heartbeat(
    storage: Storage,
    profile_id: int,
    *,
    now: float,
) -> None:
    storage.set_runtime_state(
        telegram_worker_heartbeat_state_key(profile_id), str(float(now))
    )


def prepare_resume_protection(
    storage: Storage,
    profile_id: int,
    *,
    now: float,
    gap_seconds: float,
) -> int:
    if float(gap_seconds or 0) < TELEGRAM_RESUME_OFFLINE_GAP_SECONDS:
        write_profile_worker_heartbeat(storage, profile_id, now=now)
        return 0
    failed_count = storage.fail_stale_outgoing_commands(
        int(profile_id),
        stale_before=float(now) - TELEGRAM_RESUME_OFFLINE_GAP_SECONDS,
        error_text="恢复保护：服务离线期间遗留的待发送命令已取消，请按当前状态重新判断。",
    )
    storage.set_runtime_state(
        telegram_resume_until_state_key(profile_id),
        str(float(now) + TELEGRAM_RESUME_MODE_SECONDS),
    )
    storage.set_runtime_state(
        telegram_resume_gap_state_key(profile_id),
        str(float(gap_seconds or 0)),
    )
    if float(gap_seconds or 0) > TELEGRAM_LONG_RESUME_SECONDS:
        deferred_count = defer_long_resume_countdowns(
            storage,
            int(profile_id),
            now=float(now),
        )
        if deferred_count:
            logger.warning(
                "Long resume deferred %s due countdown(s) for profile=%s",
                deferred_count,
                profile_id,
            )
    write_profile_worker_heartbeat(storage, profile_id, now=now)
    return failed_count


def defer_long_resume_countdowns(
    storage: Storage,
    profile_id: int,
    *,
    now: float,
) -> int:
    deferred_count = 0
    try:
        import biz_fanren_game
        import biz_sect_game

        fanren_count = biz_fanren_game.defer_resume_due_countdowns(
            storage,
            profile_id,
            now=now,
            defer_seconds=TELEGRAM_LONG_RESUME_DEFER_SECONDS,
            spacing_seconds=TELEGRAM_RESUME_COUNTDOWN_SPACING_SECONDS,
        )
        deferred_count += fanren_count
        sect_count = biz_sect_game.defer_resume_due_countdowns(
            storage,
            profile_id,
            now=now,
            defer_seconds=(
                TELEGRAM_LONG_RESUME_DEFER_SECONDS
                + fanren_count * TELEGRAM_RESUME_COUNTDOWN_SPACING_SECONDS
            ),
            spacing_seconds=TELEGRAM_RESUME_COUNTDOWN_SPACING_SECONDS,
        )
        deferred_count += sect_count
    except Exception:
        logger.exception(
            "Long resume countdown deferral failed for profile=%s",
            profile_id,
        )
    return deferred_count


def prepare_network_resume_if_ready(
    storage: Storage,
    profile_id: int,
    *,
    now: float,
) -> bool:
    pause_until = get_network_pause_until(storage, profile_id)
    if pause_until <= 0:
        return False
    if pause_until > now:
        return True
    started_at = get_network_pause_started_at(storage, profile_id)
    gap_seconds = max(float(now) - float(started_at or now), 0.0)
    failed_count = prepare_resume_protection(
        storage,
        profile_id,
        now=now,
        gap_seconds=gap_seconds,
    )
    finish_network_pause_window(storage, profile_id)
    logger.warning(
        "Network resume protection checked profile=%s gap_seconds=%.1f stale_outgoing_failed=%s",
        profile_id,
        gap_seconds,
        failed_count,
    )
    return False
