from typing import Optional

from tg_game.storage import (
    OUTGOING_BLOCKING_STATUSES,
    OUTGOING_NEEDS_MANUAL_CONFIRM_STATUS,
    Storage,
)


def has_blocking_outgoing_command(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    text: str,
    thread_id: Optional[int],
    manual_confirm_block_seconds: float,
    now: float,
) -> bool:
    latest_command = storage.get_latest_outgoing_command(
        chat_id,
        profile_id=profile_id,
        text=text,
        thread_id=thread_id,
    )
    if not latest_command:
        return False

    status = str(latest_command.get("status") or "").strip()
    if status not in OUTGOING_BLOCKING_STATUSES:
        return False
    if status != OUTGOING_NEEDS_MANUAL_CONFIRM_STATUS:
        return True

    updated_at = float(
        latest_command.get("updated_at") or latest_command.get("created_at") or 0
    )
    if updated_at <= 0:
        return True
    return (float(now) - updated_at) < float(manual_confirm_block_seconds)
