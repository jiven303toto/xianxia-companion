import asyncio
import time
from typing import Optional

from tg_game.storage import Storage


TELEGRAM_NETWORK_PAUSE_SECONDS = 15 * 60
TELEGRAM_NETWORK_PAUSE_UNTIL_PREFIX = "telegram_network_pause_until:"
TELEGRAM_NETWORK_PAUSE_STARTED_PREFIX = "telegram_network_pause_started:"
TELEGRAM_NETWORK_LAST_ERROR_PREFIX = "telegram_network_last_error:"


class TelegramNetworkPaused(RuntimeError):
    pass


def telegram_network_pause_until_state_key(profile_id: int) -> str:
    return f"{TELEGRAM_NETWORK_PAUSE_UNTIL_PREFIX}{int(profile_id)}"


def telegram_network_pause_started_state_key(profile_id: int) -> str:
    return f"{TELEGRAM_NETWORK_PAUSE_STARTED_PREFIX}{int(profile_id)}"


def telegram_network_last_error_state_key(profile_id: int) -> str:
    return f"{TELEGRAM_NETWORK_LAST_ERROR_PREFIX}{int(profile_id)}"


def _read_float_state(storage: Optional[Storage], key: str) -> float:
    if not storage:
        return 0.0
    try:
        return float(storage.get_runtime_state(key) or 0)
    except (TypeError, ValueError):
        return 0.0


def get_network_pause_until(storage: Optional[Storage], profile_id: Optional[int]) -> float:
    if not storage or not profile_id:
        return 0.0
    return _read_float_state(
        storage, telegram_network_pause_until_state_key(int(profile_id))
    )


def get_network_pause_started_at(
    storage: Optional[Storage], profile_id: Optional[int]
) -> float:
    if not storage or not profile_id:
        return 0.0
    return _read_float_state(
        storage, telegram_network_pause_started_state_key(int(profile_id))
    )


def is_network_paused(
    storage: Optional[Storage],
    profile_id: Optional[int],
    *,
    now: Optional[float] = None,
) -> bool:
    pause_until = get_network_pause_until(storage, profile_id)
    return pause_until > float(now if now is not None else time.time())


def raise_if_network_paused(
    storage: Optional[Storage],
    profile_id: Optional[int],
    *,
    now: Optional[float] = None,
) -> None:
    pause_until = get_network_pause_until(storage, profile_id)
    current_time = float(now if now is not None else time.time())
    if pause_until <= current_time:
        return
    remaining = max(int(pause_until - current_time), 1)
    raise TelegramNetworkPaused(
        f"Telegram 网络发送熔断中，{remaining} 秒后再检查。"
    )


def clear_network_pause(storage: Optional[Storage], profile_id: Optional[int]) -> None:
    if not storage or not profile_id:
        return
    storage.set_runtime_state(telegram_network_pause_until_state_key(int(profile_id)), "0")
    storage.set_runtime_state(telegram_network_pause_started_state_key(int(profile_id)), "0")
    storage.set_runtime_state(telegram_network_last_error_state_key(int(profile_id)), "")


def finish_network_pause_window(
    storage: Optional[Storage], profile_id: Optional[int]
) -> None:
    if not storage or not profile_id:
        return
    storage.set_runtime_state(telegram_network_pause_until_state_key(int(profile_id)), "0")


def mark_network_send_failure(
    storage: Optional[Storage],
    profile_id: Optional[int],
    exc: BaseException,
    *,
    now: Optional[float] = None,
    pause_seconds: int = TELEGRAM_NETWORK_PAUSE_SECONDS,
) -> float:
    if not storage or not profile_id:
        return 0.0
    current_time = float(now if now is not None else time.time())
    pause_until = current_time + max(int(pause_seconds or 0), 1)
    started_at = get_network_pause_started_at(storage, int(profile_id))
    if started_at <= 0:
        storage.set_runtime_state(
            telegram_network_pause_started_state_key(int(profile_id)),
            str(current_time),
        )
    storage.set_runtime_state(
        telegram_network_pause_until_state_key(int(profile_id)),
        str(pause_until),
    )
    storage.set_runtime_state(
        telegram_network_last_error_state_key(int(profile_id)),
        str(exc)[:1000],
    )
    return pause_until


def is_network_send_error(exc: BaseException) -> bool:
    text = str(exc or "")
    if "TOPIC_CLOSED" in text:
        return False
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError, OSError)):
        return True
    class_name = type(exc).__name__.lower()
    if any(token in class_name for token in ("timeout", "connection", "network")):
        return True
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            "connection",
            "disconnected",
            "timed out",
            "timeout",
            "network",
            "connect call failed",
            "server closed the connection",
            "server disconnected",
            "getaddrinfo failed",
            "temporary failure in name resolution",
            "name or service not known",
            "winerror 100",
            "winerror 11001",
        )
    )
