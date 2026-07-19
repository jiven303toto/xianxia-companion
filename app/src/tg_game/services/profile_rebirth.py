import json
import re
import time
from typing import Optional

from tg_game.storage import OUTGOING_BLOCKING_STATUSES, Storage


REBIRTH_QUERY_COMMAND = ".夺舍重生"
REBIRTH_CHOICE_COMMAND_PREFIX = ".重生 "
REBIRTH_STATE_KEY_PREFIX = "profile_rebirth:"
REBIRTH_COMMAND_RETRY_SECONDS = 10 * 60

REBIRTH_STAGE_QUERY_PENDING = "query_pending"
REBIRTH_STAGE_COOLDOWN = "cooldown"
REBIRTH_STAGE_CHOICE_PENDING = "choice_pending"
REBIRTH_STAGE_COMPLETED = "completed"

_CANDIDATE_HEADER_RE = re.compile(r"^\s*(\d+)\s*[.、]\s*【夺舍")
_SPIRIT_ROOT_RE = re.compile(r"灵根[:：]\s*(.+)$")
_DURATION_PATTERNS = (
    (re.compile(r"(\d+)\s*小时"), 3600),
    (re.compile(r"(\d+)\s*分钟"), 60),
    (re.compile(r"(\d+)\s*秒"), 1),
)


class ProfileRebirthLockedError(RuntimeError):
    pass


def _state_key(profile_id: int) -> str:
    return f"{REBIRTH_STATE_KEY_PREFIX}{int(profile_id)}"


def load_profile_rebirth_state(storage: Storage, profile_id: int) -> dict:
    try:
        state = json.loads(storage.get_runtime_state(_state_key(profile_id)) or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return state if isinstance(state, dict) else {}


def save_profile_rebirth_state(storage: Storage, profile_id: int, state: dict) -> dict:
    normalized = dict(state or {})
    normalized["profile_id"] = int(profile_id)
    normalized["updated_at"] = time.time()
    storage.set_runtime_state(
        _state_key(profile_id),
        json.dumps(normalized, ensure_ascii=False, sort_keys=True),
    )
    return normalized


def is_profile_rebirth_locked(storage: Optional[Storage], profile_id: Optional[int]) -> bool:
    if not storage or not profile_id:
        return False
    return bool(load_profile_rebirth_state(storage, int(profile_id)).get("active"))


def is_rebirth_command(text: str) -> bool:
    normalized = str(text or "").strip()
    return normalized == REBIRTH_QUERY_COMMAND or normalized.startswith(
        REBIRTH_CHOICE_COMMAND_PREFIX
    )


def ensure_profile_rebirth_send_allowed(
    storage: Optional[Storage], profile_id: Optional[int], text: str
) -> None:
    if is_profile_rebirth_locked(storage, profile_id) and not is_rebirth_command(text):
        raise ProfileRebirthLockedError(
            "当前 profile 正在等待夺舍重生，普通命令已保留在队列中。"
        )


def _is_active_outgoing_command(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    text: str,
    thread_id: Optional[int],
    now: float,
) -> bool:
    latest = storage.get_latest_outgoing_command(
        chat_id,
        profile_id=profile_id,
        text=text,
        thread_id=thread_id,
    )
    if not latest:
        return False
    status = str(latest.get("status") or "").strip()
    if status not in OUTGOING_BLOCKING_STATUSES:
        return False
    if status != "needs_manual_confirm":
        return True
    updated_at = float(latest.get("updated_at") or latest.get("created_at") or 0)
    return updated_at <= 0 or now - updated_at < REBIRTH_COMMAND_RETRY_SECONDS


def _enqueue_rebirth_command(
    storage: Storage,
    state: dict,
    text: str,
    *,
    reply_to_msg_id: Optional[int] = None,
    now: Optional[float] = None,
) -> int:
    current_time = float(now if now is not None else time.time())
    profile_id = int(state.get("profile_id") or 0)
    chat_id = int(state.get("chat_id") or 0)
    thread_id = int(state["thread_id"]) if state.get("thread_id") else None
    if not profile_id or not chat_id:
        return 0
    if _is_active_outgoing_command(
        storage,
        profile_id=profile_id,
        chat_id=chat_id,
        text=text,
        thread_id=thread_id,
        now=current_time,
    ):
        return 0
    return storage.enqueue_outgoing_command(
        profile_id=profile_id,
        chat_id=chat_id,
        text=text,
        thread_id=thread_id,
        reply_to_msg_id=reply_to_msg_id,
        chat_type=str(state.get("chat_type") or "group"),
        bot_username=str(state.get("bot_username") or "fanrenxiuxian_bot"),
    )


def queue_rebirth_query(
    storage: Storage, profile_id: int, *, now: Optional[float] = None
) -> int:
    current_time = float(now if now is not None else time.time())
    state = load_profile_rebirth_state(storage, profile_id)
    if not state.get("active"):
        return 0
    command_id = _enqueue_rebirth_command(
        storage,
        state,
        REBIRTH_QUERY_COMMAND,
        now=current_time,
    )
    state.update(
        {
            "stage": REBIRTH_STAGE_QUERY_PENDING,
            "retry_at": current_time + REBIRTH_COMMAND_RETRY_SECONDS,
        }
    )
    if command_id:
        state["last_command_id"] = command_id
        state["last_command"] = REBIRTH_QUERY_COMMAND
    save_profile_rebirth_state(storage, profile_id, state)
    return command_id


def start_profile_rebirth(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    thread_id: Optional[int],
    chat_type: str,
    bot_username: str,
    now: Optional[float] = None,
) -> dict:
    current_time = float(now if now is not None else time.time())
    existing = load_profile_rebirth_state(storage, profile_id)
    if existing.get("active"):
        return existing
    state = save_profile_rebirth_state(
        storage,
        profile_id,
        {
            "active": True,
            "stage": REBIRTH_STAGE_QUERY_PENDING,
            "chat_id": int(chat_id),
            "thread_id": int(thread_id) if thread_id else None,
            "chat_type": str(chat_type or "group"),
            "bot_username": str(bot_username or "fanrenxiuxian_bot"),
            "started_at": current_time,
            "retry_at": current_time + REBIRTH_COMMAND_RETRY_SECONDS,
            "selected_index": 0,
            "selected_root": "",
            "offer_message_id": 0,
        },
    )
    queue_rebirth_query(storage, profile_id, now=current_time)
    return load_profile_rebirth_state(storage, profile_id) or state


def parse_rebirth_cooldown_seconds(text: str) -> Optional[int]:
    total = 0
    matched = False
    for pattern, multiplier in _DURATION_PATTERNS:
        for match in pattern.finditer(str(text or "")):
            total += int(match.group(1)) * multiplier
            matched = True
    return total if matched else None


def parse_rebirth_candidates(text: str) -> list[dict]:
    candidates = []
    current = None
    for raw_line in str(text or "").splitlines():
        header = _CANDIDATE_HEADER_RE.search(raw_line)
        if header:
            current = {"index": int(header.group(1)), "root": ""}
            candidates.append(current)
            continue
        if current is None:
            continue
        root_match = _SPIRIT_ROOT_RE.search(raw_line)
        if root_match:
            current["root"] = root_match.group(1).strip()
    return [candidate for candidate in candidates if candidate.get("root")]


def _root_priority(root: str) -> int:
    normalized = str(root or "").replace(" ", "")
    if "异灵根" in normalized:
        return 0
    if "天灵根" in normalized:
        return 1
    if "真灵根" in normalized:
        return 2
    if "五行伪灵根" in normalized or "伪灵根" in normalized:
        return 3
    if "废灵根" in normalized:
        return 4
    return 99


def select_rebirth_candidate(text: str) -> Optional[dict]:
    candidates = parse_rebirth_candidates(text)
    if not candidates:
        return None
    return min(candidates, key=lambda item: (_root_priority(item["root"]), item["index"]))


def recheck_pending_profile_commands(storage: Storage, profile_id: int) -> dict:
    kept = 0
    invalid_ids = []
    with storage.connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM outgoing_commands
            WHERE profile_id=? AND status='pending'
            ORDER BY scheduled_at ASC, created_at ASC, id ASC
            """,
            (int(profile_id),),
        ).fetchall()
    for row in rows:
        command = dict(row)
        if is_rebirth_command(command.get("text") or ""):
            continue
        thread_id = int(command["thread_id"]) if command.get("thread_id") else None
        binding = storage.get_chat_binding(
            int(profile_id), int(command.get("chat_id") or 0), thread_id
        )
        if not binding or not bool(getattr(binding, "is_active", False)):
            invalid_ids.append(int(command["id"]))
            continue
        kept += 1
    for command_id in invalid_ids:
        storage.mark_outgoing_command_failed(
            command_id, "夺舍重生完成后重新检查：原聊天绑定已失效。"
        )
    return {
        "kept": kept,
        "duplicates_cancelled": 0,
        "invalid_cancelled": len(invalid_ids),
    }


def _cancel_pending_rebirth_commands(storage: Storage, profile_id: int) -> int:
    now = time.time()
    with storage.connect() as conn:
        cursor = conn.execute(
            """
            UPDATE outgoing_commands
            SET status='failed', error_text=?, updated_at=?
            WHERE profile_id=? AND status='pending'
              AND (text=? OR text LIKE ?)
            """,
            (
                "夺舍重生已经完成，未发送的恢复命令已取消。",
                now,
                int(profile_id),
                REBIRTH_QUERY_COMMAND,
                f"{REBIRTH_CHOICE_COMMAND_PREFIX}%",
            ),
        )
    return int(cursor.rowcount or 0)


def handle_profile_rebirth_reply(
    storage: Storage,
    *,
    profile_id: int,
    chat_id: int,
    message_id: int,
    text: str,
    reply_command: str = "",
    now: Optional[float] = None,
) -> Optional[dict]:
    current_time = float(now if now is not None else time.time())
    state = load_profile_rebirth_state(storage, profile_id)
    if not state.get("active") or int(state.get("chat_id") or 0) != int(chat_id):
        return None
    normalized_reply_command = str(reply_command or "").strip()
    if is_rebirth_command(normalized_reply_command):
        thread_id = int(state["thread_id"]) if state.get("thread_id") else None
        latest = storage.get_latest_outgoing_command(
            chat_id,
            profile_id=profile_id,
            text=normalized_reply_command,
            thread_id=thread_id,
        )
        if latest and str(latest.get("status") or "") in OUTGOING_BLOCKING_STATUSES:
            storage.mark_outgoing_command_confirmed(int(latest["id"]), "收到夺舍回包")
    normalized = str(text or "").strip()
    if "成功夺舍重生" in normalized or (
        "【天机开阖·夺舍重生】" in normalized and "全新肉身" in normalized
    ):
        recovery_cancelled = _cancel_pending_rebirth_commands(storage, profile_id)
        queue_result = recheck_pending_profile_commands(storage, profile_id)
        state.update(
            {
                "active": False,
                "stage": REBIRTH_STAGE_COMPLETED,
                "completed_at": current_time,
                "retry_at": 0,
                "queue_recheck": queue_result,
                "recovery_commands_cancelled": recovery_cancelled,
            }
        )
        save_profile_rebirth_state(storage, profile_id, state)
        return {
            "event": "rebirth_completed",
            "state": state,
            "recovery_commands_cancelled": recovery_cancelled,
            **queue_result,
        }

    selected = select_rebirth_candidate(normalized)
    if selected:
        command = f"{REBIRTH_CHOICE_COMMAND_PREFIX}{selected['index']}"
        command_id = _enqueue_rebirth_command(
            storage,
            state,
            command,
            reply_to_msg_id=int(message_id),
            now=current_time,
        )
        state.update(
            {
                "stage": REBIRTH_STAGE_CHOICE_PENDING,
                "selected_index": int(selected["index"]),
                "selected_root": str(selected["root"]),
                "offer_message_id": int(message_id),
                "retry_at": 0,
            }
        )
        if command_id:
            state["last_command_id"] = command_id
            state["last_command"] = command
        save_profile_rebirth_state(storage, profile_id, state)
        return {
            "event": "rebirth_choice_queued",
            "state": state,
            "command_id": command_id,
            "selected": selected,
        }

    cooldown = parse_rebirth_cooldown_seconds(normalized)
    if cooldown is not None and ("温养" in normalized or "神魂冲击" in normalized):
        retry_at = current_time + max(int(cooldown), 1)
        state.update(
            {
                "stage": REBIRTH_STAGE_COOLDOWN,
                "retry_at": retry_at,
                "cooldown_seconds": int(cooldown),
            }
        )
        save_profile_rebirth_state(storage, profile_id, state)
        return {
            "event": "rebirth_cooldown",
            "state": state,
            "cooldown_seconds": int(cooldown),
            "retry_at": retry_at,
        }
    return None


def tick_profile_rebirth(
    storage: Storage, profile_id: int, *, now: Optional[float] = None
) -> dict:
    current_time = float(now if now is not None else time.time())
    state = load_profile_rebirth_state(storage, profile_id)
    if not state.get("active"):
        return {"active": False, "queued": False}
    stage = str(state.get("stage") or "")
    retry_at = float(state.get("retry_at") or 0)
    if stage in {REBIRTH_STAGE_QUERY_PENDING, REBIRTH_STAGE_COOLDOWN} and (
        retry_at <= 0 or current_time >= retry_at
    ):
        command_id = queue_rebirth_query(storage, profile_id, now=current_time)
        return {"active": True, "queued": bool(command_id), "command_id": command_id}
    return {"active": True, "queued": False}
