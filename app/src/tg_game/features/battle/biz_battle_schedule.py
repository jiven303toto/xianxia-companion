import json
import re
import time
from datetime import datetime, timedelta

from tg_game.storage import OUTGOING_CONFIRM_TIMEOUT_SECONDS, Storage


STATE_KEY = "admin_battle_schedule"
COMMAND_PREFIX = ".斗法 "
DEFAULT_RUN_TIME = "22:10"
DEFAULT_DAILY_ATTEMPTS = 10
MAX_DAILY_ATTEMPTS = 10
POLL_SECONDS = 5
TARGET_COOLDOWN_SECONDS = 5 * 60 + 15
ATTACKER_COOLDOWN_SECONDS = 10 * 60 + 15
LOSER_COOLDOWN_SECONDS = 15 * 60 + 15
BUSY_RETRY_SECONDS = 60
RESULT_TIMEOUT_SECONDS = 15 * 60
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{5,32}$")
ATTACKER_PATTERN = re.compile(r"攻方[:：]\s*(?P<value>@?[A-Za-z0-9_]+)")
DEFENDER_PATTERN = re.compile(r"守方[:：]\s*(?P<value>@?[A-Za-z0-9_]+)")
WINNER_PATTERN = re.compile(r"胜者[:：]\s*(?P<value>@?[A-Za-z0-9_]+)")
LOSER_PATTERN = re.compile(r"败者[:：]\s*(?P<value>@?[A-Za-z0-9_]+)")
GAIN_PATTERN = re.compile(r"净得修为\s*(?P<value>[+\-]?[0-9.]+(?:万|亿)?)")
LOSS_PATTERN = re.compile(r"损失修为\s*(?P<value>[+\-]?[0-9.]+(?:万|亿)?)")
SPIRIT_PATTERN = re.compile(r"今日神念[:：]\s*(?P<value>\d+)\s*/\s*10")
WIN_CAP_PATTERN = re.compile(r"对此人剩余胜场[:：]\s*(?P<value>\d+)")
WEAR_PATTERN = re.compile(r"法宝磨损\s*(?P<value>[+\-]?\d+)")


class BattleScheduleBusyError(RuntimeError):
    pass


def normalize_username(value: str) -> str:
    username = str(value or "").strip().lstrip("@")
    if not username:
        return ""
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError("目标账号必须是有效的 Telegram username")
    return f"@{username}"


def normalize_run_time(value: str) -> str:
    raw = str(value or "").strip()
    try:
        hour_text, minute_text = raw.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except (TypeError, ValueError):
        raise ValueError("执行时间必须使用 HH:MM 格式") from None
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("执行时间必须使用 HH:MM 格式")
    return f"{hour:02d}:{minute:02d}"


def normalize_daily_attempts(value: int | str) -> int:
    try:
        attempts = int(value)
    except (TypeError, ValueError):
        raise ValueError("每日斗法次数必须是 1 到 10") from None
    if not 1 <= attempts <= MAX_DAILY_ATTEMPTS:
        raise ValueError("每日斗法次数必须是 1 到 10")
    return attempts


def normalize_selected_profile_ids(values) -> list[int]:
    if values is None:
        return []
    if isinstance(values, (str, int)):
        values = [values]
    selected_ids = []
    for value in values:
        try:
            profile_id = int(value)
        except (TypeError, ValueError):
            raise ValueError("出战 Profile 选择无效") from None
        if profile_id <= 0:
            raise ValueError("出战 Profile 选择无效")
        if profile_id not in selected_ids:
            selected_ids.append(profile_id)
    return selected_ids


def _empty_batch() -> dict:
    return {
        "status": "idle",
        "source": "",
        "started_at": 0.0,
        "completed_at": 0.0,
        "target_username": "",
        "selection_mode": "",
        "selected_profile_ids": [],
        "target_ready_at": 0.0,
        "cursor": 0,
        "items": [],
        "events": [],
        "last_error": "",
    }


def default_state() -> dict:
    return {
        "config": {
            "enabled": False,
            "run_time": DEFAULT_RUN_TIME,
            "target_username": "",
            "daily_attempts": DEFAULT_DAILY_ATTEMPTS,
            "selected_profile_ids": [],
            "next_run_at": 0.0,
            "last_run_at": 0.0,
        },
        "batch": _empty_batch(),
    }


def load_state(storage: Storage) -> dict:
    state = default_state()
    raw = storage.get_runtime_state(STATE_KEY)
    if not raw:
        return state
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return state
    if not isinstance(parsed, dict):
        return state
    config = parsed.get("config") if isinstance(parsed.get("config"), dict) else {}
    batch = parsed.get("batch") if isinstance(parsed.get("batch"), dict) else {}
    state["config"].update(config)
    state["batch"].update(batch)
    try:
        state["config"]["selected_profile_ids"] = normalize_selected_profile_ids(
            state["config"].get("selected_profile_ids")
        )
    except ValueError:
        state["config"]["selected_profile_ids"] = []
    try:
        state["batch"]["selected_profile_ids"] = normalize_selected_profile_ids(
            state["batch"].get("selected_profile_ids")
        )
    except ValueError:
        state["batch"]["selected_profile_ids"] = []
    if not isinstance(state["batch"].get("items"), list):
        state["batch"]["items"] = []
    if not isinstance(state["batch"].get("events"), list):
        state["batch"]["events"] = []
    return state


def save_state(storage: Storage, state: dict) -> dict:
    storage.set_runtime_state(
        STATE_KEY,
        json.dumps(state, ensure_ascii=False, separators=(",", ":")),
    )
    return state


def build_command(target_username: str) -> str:
    target = normalize_username(target_username)
    if not target:
        raise ValueError("请先配置斗法目标")
    return f"{COMMAND_PREFIX}{target}"


def _username_key(value: str) -> str:
    return str(value or "").strip().lower().lstrip("@")


def _profile_name(profile) -> str:
    return profile.display_name or profile.game_name or profile.name


def _profile_username(profile) -> str:
    return normalize_username(profile.account_name or profile.telegram_username)


def _profile_unavailable_reason(storage: Storage, profile) -> str:
    try:
        account_name = _profile_username(profile)
    except ValueError:
        return "Telegram username 无效"
    if not account_name:
        return "没有可用 Telegram username"
    if not storage.get_primary_chat_binding(profile.id):
        return "没有可用群绑定"
    if not str(profile.telegram_session_name or "").strip():
        return "没有可用 Telegram session"
    return ""


def _resolve_selected_profiles(
    storage: Storage,
    profiles,
    selected_profile_ids,
    *,
    require_selection: bool,
) -> tuple[list[int], list]:
    selected_ids = normalize_selected_profile_ids(selected_profile_ids)
    if require_selection and not selected_ids:
        raise ValueError("请至少选择一个出战 Profile")
    profile_map = {int(profile.id): profile for profile in profiles}
    missing_ids = [profile_id for profile_id in selected_ids if profile_id not in profile_map]
    if missing_ids:
        raise ValueError(f"找不到出战 Profile：{', '.join(str(value) for value in missing_ids)}")
    selected_profiles = [profile_map[profile_id] for profile_id in selected_ids]
    for profile in selected_profiles:
        reason = _profile_unavailable_reason(storage, profile)
        if reason:
            raise ValueError(f"{_profile_name(profile)} 不可出战：{reason}")
    return selected_ids, selected_profiles


def validate_target(
    target_username: str,
    selected_profiles,
) -> str:
    target = normalize_username(target_username)
    if not target:
        raise ValueError("请先配置斗法目标")
    target_key = _username_key(target)
    for profile in selected_profiles:
        attacker_usernames = {
            _username_key(value)
            for value in (profile.account_name, profile.telegram_username)
            if _username_key(value)
        }
        if target_key in attacker_usernames:
            raise ValueError(f"斗法目标不能与已选出战 Profile（{_profile_name(profile)}）相同")
    return target


def _next_schedule_at(now: float, run_time: str) -> float:
    normalized = normalize_run_time(run_time)
    hour, minute = (int(part) for part in normalized.split(":"))
    current = datetime.fromtimestamp(now)
    target = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= current:
        target += timedelta(days=1)
    return target.timestamp()


def set_config(
    storage: Storage,
    profiles,
    *,
    admin_profile_id: int,
    enabled: bool,
    target_username: str,
    run_time: str,
    daily_attempts: int | str,
    selected_profile_ids=None,
    now: float | None = None,
) -> dict:
    current_time = float(now if now is not None else time.time())
    selected_ids, selected_profiles = _resolve_selected_profiles(
        storage,
        profiles,
        selected_profile_ids,
        require_selection=False,
    )
    target = normalize_username(target_username)
    if target:
        target = validate_target(target, selected_profiles)
    if enabled and not target:
        raise ValueError("开启每日争锋前必须配置斗法目标")
    if enabled and not selected_ids:
        raise ValueError("开启每日争锋前请至少选择一个出战 Profile")
    normalized_time = normalize_run_time(run_time)
    attempts = normalize_daily_attempts(daily_attempts)
    state = load_state(storage)
    state["config"].update(
        {
            "enabled": bool(enabled),
            "run_time": normalized_time,
            "target_username": target,
            "daily_attempts": attempts,
            "selected_profile_ids": selected_ids,
            "next_run_at": (
                _next_schedule_at(current_time, normalized_time) if enabled else 0.0
            ),
        }
    )
    return save_state(storage, state)


def _build_item(storage: Storage, profile, daily_attempts: int) -> dict:
    chat = storage.get_primary_chat_binding(profile.id)
    account_name = _profile_username(profile)
    item = {
        "profile_id": int(profile.id),
        "profile_name": _profile_name(profile),
        "account_name": account_name,
        "chat_id": int(chat.chat_id) if chat else 0,
        "thread_id": int(chat.thread_id) if chat and chat.thread_id else None,
        "chat_type": chat.chat_type if chat else "group",
        "bot_username": chat.bot_username if chat else "",
        "status": "waiting",
        "attempts": 0,
        "daily_attempts": daily_attempts,
        "remaining_spirit": None,
        "cultivation_transferred": 0,
        "next_action_at": 0.0,
        "pending_outgoing_id": 0,
        "queued_at": 0.0,
        "last_result": "",
        "last_error": "",
    }
    if not account_name:
        item["status"] = "failed"
        item["last_error"] = "当前 Profile 没有可用 Telegram username"
    elif not chat:
        item["status"] = "failed"
        item["last_error"] = "当前 Profile 没有可用群绑定"
    elif not profile.telegram_session_name:
        item["status"] = "failed"
        item["last_error"] = "当前 Profile 没有可用 Telegram session"
    return item


def _append_event(batch: dict, *, now: float, item: dict | None, result: str, detail: str) -> None:
    events = batch.setdefault("events", [])
    events.append(
        {
            "at": float(now),
            "profile_id": int(item.get("profile_id") or 0) if item else 0,
            "profile_name": str(item.get("profile_name") or "") if item else "",
            "result": str(result or ""),
            "detail": str(detail or "")[:1000],
        }
    )
    del events[:-100]


def start_batch(
    storage: Storage,
    profiles,
    *,
    admin_profile_id: int,
    source: str = "manual",
    now: float | None = None,
) -> dict:
    current_time = float(now if now is not None else time.time())
    state = load_state(storage)
    if state["batch"].get("status") == "running":
        raise BattleScheduleBusyError("当前已有诸元神争锋任务正在执行")
    selected_ids, selected_profiles = _resolve_selected_profiles(
        storage,
        profiles,
        state["config"].get("selected_profile_ids"),
        require_selection=True,
    )
    target = validate_target(
        state["config"].get("target_username") or "",
        selected_profiles,
    )
    attempts = normalize_daily_attempts(
        state["config"].get("daily_attempts") or DEFAULT_DAILY_ATTEMPTS
    )
    items = [
        _build_item(storage, profile, attempts)
        for profile in selected_profiles
    ]
    batch = _empty_batch()
    batch.update(
        {
            "status": "running",
            "source": source,
            "started_at": current_time,
            "target_username": target,
            "selection_mode": "explicit",
            "selected_profile_ids": selected_ids,
            "items": items,
        }
    )
    _append_event(
        batch,
        now=current_time,
        item=None,
        result="started",
        detail=f"开始调度 {len(items)} 个执行 Profile，目标 {target}",
    )
    state["batch"] = batch
    return save_state(storage, state)


def stop_batch(
    storage: Storage,
    *,
    now: float | None = None,
    reason: str = "管理员已停止任务",
) -> dict:
    current_time = float(now if now is not None else time.time())
    state = load_state(storage)
    batch = state["batch"]
    if batch.get("status") != "running":
        return state
    target = batch.get("target_username") or ""
    try:
        command = build_command(target)
    except ValueError:
        command = ""
    for item in batch.get("items") or []:
        if command and item.get("status") == "awaiting_reply":
            storage.cancel_pending_outgoing_commands(
                int(item.get("profile_id") or 0),
                int(item.get("chat_id") or 0),
                command,
                thread_id=item.get("thread_id"),
                require_exact_thread=True,
            )
        if item.get("status") in {"waiting", "awaiting_reply"}:
            item["status"] = "stopped"
            item["last_error"] = reason
    batch["status"] = "stopped"
    batch["completed_at"] = current_time
    batch["last_error"] = reason
    _append_event(
        batch,
        now=current_time,
        item=None,
        result="stopped",
        detail=reason,
    )
    return save_state(storage, state)


def _amount_to_int(value: str) -> int:
    raw = str(value or "").strip().replace("+", "")
    sign = -1 if raw.startswith("-") else 1
    raw = raw.lstrip("-")
    multiplier = 1
    if raw.endswith("万"):
        multiplier = 10_000
        raw = raw[:-1]
    elif raw.endswith("亿"):
        multiplier = 100_000_000
        raw = raw[:-1]
    try:
        return sign * int(float(raw) * multiplier)
    except ValueError:
        return 0


def _match_username(pattern: re.Pattern, text: str) -> str:
    match = pattern.search(text or "")
    return normalize_username(match.group("value")) if match else ""


def parse_reply(text: str, *, attacker_username: str, target_username: str) -> dict:
    raw = str(text or "").strip()
    attacker = normalize_username(attacker_username)
    target = normalize_username(target_username)
    if not raw:
        return {"type": "pending"}
    if "法宝齐出" in raw or "正在整理天道战报" in raw or "正在推演战局" in raw:
        return {"type": "pending"}
    if "今日神念消耗过剧" in raw or "每日可主动斗法 10 次" in raw:
        return {"type": "daily_limit", "remaining_spirit": 0}
    if "元神尚未平复" in raw and "无法再次斗法" in raw:
        return {"type": "target_cooldown"}
    if "正在进行另一场因果纠缠" in raw:
        return {"type": "busy"}
    if "出手次数过多" in raw and "法则限制" in raw:
        return {"type": "target_win_limit"}
    if any(
        marker in raw
        for marker in (
            "尚未踏入仙途",
            "已遁入山林",
            "与自己斗法",
            "神识无法锁定",
        )
    ):
        return {"type": "fatal", "error": raw.splitlines()[0][:500]}
    if "侥幸逃脱" in raw:
        escaped = re.search(r"(@?[A-Za-z0-9_]+)\s*凭借神通侥幸逃脱", raw)
        if escaped and _username_key(escaped.group(1)) != _username_key(attacker):
            return {"type": "mismatch", "error": "逃脱回包中的攻击方与当前 Profile 不一致"}
        return {"type": "escape"}
    if "天道战报" not in raw:
        return {"type": "pending"}

    report_attacker = _match_username(ATTACKER_PATTERN, raw)
    report_defender = _match_username(DEFENDER_PATTERN, raw)
    winner = _match_username(WINNER_PATTERN, raw)
    loser = _match_username(LOSER_PATTERN, raw)
    if _username_key(report_attacker) != _username_key(attacker):
        return {"type": "mismatch", "error": "战报攻击方与当前 Profile 不一致"}
    if _username_key(report_defender) != _username_key(target):
        return {"type": "mismatch", "error": "战报守方与配置目标不一致"}

    gain_match = GAIN_PATTERN.search(raw)
    loss_match = LOSS_PATTERN.search(raw)
    spirit_match = SPIRIT_PATTERN.search(raw)
    win_cap_match = WIN_CAP_PATTERN.search(raw)
    wear_values = [int(match.group("value")) for match in WEAR_PATTERN.finditer(raw)]
    winner_wear = wear_values[0] if wear_values else 0
    loser_wear = wear_values[1] if len(wear_values) > 1 else 0
    gain_text = gain_match.group("value") if gain_match else ""
    loss_text = loss_match.group("value") if loss_match else ""
    attacker_lost = _username_key(loser) == _username_key(attacker)
    attacker_won = _username_key(winner) == _username_key(attacker)
    target_won = _username_key(winner) == _username_key(target)
    if not ((attacker_lost and target_won) or attacker_won):
        return {"type": "mismatch", "error": "战报胜负方与当前任务不一致"}
    return {
        "type": "report",
        "outcome": "lost" if attacker_lost else "won",
        "gain_text": gain_text,
        "gain_value": _amount_to_int(gain_text),
        "loss_text": loss_text,
        "loss_value": abs(_amount_to_int(loss_text)),
        "remaining_spirit": int(spirit_match.group("value")) if spirit_match else None,
        "remaining_target_wins": (
            int(win_cap_match.group("value")) if win_cap_match else None
        ),
        "winner_wear": winner_wear,
        "loser_wear": loser_wear,
    }


def _has_blocking_outgoing(
    storage: Storage,
    profile_id: int,
    chat_id: int,
    *,
    now: float,
) -> bool:
    with storage.connect() as conn:
        rows = conn.execute(
            """
            SELECT status, created_at, updated_at
            FROM outgoing_commands
            WHERE profile_id=? AND chat_id=?
              AND status IN ('pending', 'sending', 'awaiting_confirm', 'needs_manual_confirm')
            """,
            (int(profile_id), int(chat_id)),
        ).fetchall()
    for row in rows:
        if str(row["status"] or "") != "needs_manual_confirm":
            return True
        updated_at = float(row["updated_at"] or row["created_at"] or 0)
        if updated_at <= 0 or now - updated_at < OUTGOING_CONFIRM_TIMEOUT_SECONDS:
            return True
    return False


def _find_pending_item(batch: dict) -> dict | None:
    for item in batch.get("items") or []:
        if item.get("status") == "awaiting_reply":
            return item
    return None


def _finish_item_after_attempt(
    item: dict,
    *,
    now: float,
    result_text: str,
    cooldown_seconds: int = ATTACKER_COOLDOWN_SECONDS,
) -> None:
    item["last_result"] = result_text
    item["pending_outgoing_id"] = 0
    item["queued_at"] = 0.0
    remaining = item.get("remaining_spirit")
    if int(item.get("attempts") or 0) >= int(item.get("daily_attempts") or 0):
        item["status"] = "completed"
    elif remaining is not None and int(remaining) <= 0:
        item["status"] = "completed"
    else:
        item["status"] = "waiting"
        item["next_action_at"] = now + cooldown_seconds


def _fail_batch_for_target(batch: dict, *, now: float, error: str) -> None:
    batch["status"] = "failed"
    batch["completed_at"] = now
    batch["last_error"] = error
    for item in batch.get("items") or []:
        if item.get("status") in {"waiting", "awaiting_reply"}:
            item["status"] = "failed"
            item["last_error"] = error
    _append_event(batch, now=now, item=None, result="failed", detail=error)


def _settle_pending_item(storage: Storage, batch: dict, item: dict, *, now: float) -> None:
    outgoing_id = int(item.get("pending_outgoing_id") or 0)
    outgoing = storage.get_outgoing_command(outgoing_id) if outgoing_id else None
    if outgoing and str(outgoing.get("status") or "") == "failed":
        item["status"] = "failed"
        item["last_error"] = str(outgoing.get("error_text") or "斗法命令发送失败")
        _append_event(
            batch,
            now=now,
            item=item,
            result="failed",
            detail=item["last_error"],
        )
        return

    command = build_command(batch.get("target_username") or "")
    reply = storage.get_latest_bot_reply_for_command(
        int(item.get("chat_id") or 0),
        command,
        profile_id=int(item.get("profile_id") or 0),
        thread_id=item.get("thread_id"),
    )
    queued_at = float(item.get("queued_at") or 0)
    if reply and float(reply.get("created_at") or 0) >= queued_at:
        parsed = parse_reply(
            str(reply.get("text") or ""),
            attacker_username=item.get("account_name") or "",
            target_username=batch.get("target_username") or "",
        )
        result_type = parsed.get("type")
        if result_type == "report":
            item["attempts"] = int(item.get("attempts") or 0) + 1
            item["remaining_spirit"] = parsed.get("remaining_spirit")
            batch["target_ready_at"] = now + TARGET_COOLDOWN_SECONDS
            if parsed.get("outcome") == "lost":
                transferred = max(int(parsed.get("gain_value") or 0), 0)
                item["cultivation_transferred"] = (
                    int(item.get("cultivation_transferred") or 0) + transferred
                )
                result_text = (
                    f"战败，向目标转移 {parsed.get('gain_text') or '0'} 修为；"
                    f"双方磨损 {parsed.get('loser_wear') or 0}/{parsed.get('winner_wear') or 0}"
                )
                _finish_item_after_attempt(
                    item,
                    now=now,
                    result_text=result_text,
                    cooldown_seconds=LOSER_COOLDOWN_SECONDS,
                )
                _append_event(
                    batch,
                    now=now,
                    item=item,
                    result="lost",
                    detail=result_text,
                )
                return
            item["status"] = "failed"
            item["pending_outgoing_id"] = 0
            item["queued_at"] = 0.0
            batch["target_ready_at"] = now + LOSER_COOLDOWN_SECONDS
            item["last_result"] = "攻击方意外获胜"
            item["last_error"] = "为避免从目标大号反向夺取修为，已停止当前 Profile"
            _append_event(
                batch,
                now=now,
                item=item,
                result="unexpected_win",
                detail=item["last_error"],
            )
            return
        if result_type == "escape":
            item["attempts"] = int(item.get("attempts") or 0) + 1
            batch["target_ready_at"] = now + TARGET_COOLDOWN_SECONDS
            _finish_item_after_attempt(item, now=now, result_text="侥幸逃脱，神念已消耗，未转移修为")
            _append_event(
                batch,
                now=now,
                item=item,
                result="escape",
                detail=item["last_result"],
            )
            return
        if result_type in {"daily_limit", "target_win_limit"}:
            item["status"] = "completed"
            item["remaining_spirit"] = parsed.get("remaining_spirit")
            item["pending_outgoing_id"] = 0
            item["queued_at"] = 0.0
            item["last_result"] = (
                "今日主动斗法次数已用完"
                if result_type == "daily_limit"
                else "今日对目标出手已被法则限制"
            )
            _append_event(
                batch,
                now=now,
                item=item,
                result=result_type,
                detail=item["last_result"],
            )
            return
        if result_type == "target_cooldown":
            item["status"] = "waiting"
            item["next_action_at"] = now + TARGET_COOLDOWN_SECONDS
            item["pending_outgoing_id"] = 0
            item["queued_at"] = 0.0
            batch["target_ready_at"] = now + TARGET_COOLDOWN_SECONDS
            item["last_result"] = "目标元神尚未平复，稍后重试"
            return
        if result_type == "busy":
            item["status"] = "waiting"
            item["next_action_at"] = now + BUSY_RETRY_SECONDS
            item["pending_outgoing_id"] = 0
            item["queued_at"] = 0.0
            item["last_result"] = "目标正在进行其他战斗，稍后重试"
            return
        if result_type in {"fatal", "mismatch"}:
            _fail_batch_for_target(
                batch,
                now=now,
                error=str(parsed.get("error") or "斗法目标或战报归属异常"),
            )
            return

    if queued_at and now - queued_at >= RESULT_TIMEOUT_SECONDS:
        item["status"] = "failed"
        item["pending_outgoing_id"] = 0
        item["queued_at"] = 0.0
        item["last_error"] = "超过 15 分钟仍未确认最终战报；为避免重复扣除神念，已停止"
        _append_event(
            batch,
            now=now,
            item=item,
            result="timeout",
            detail=item["last_error"],
        )


def _all_items_finished(batch: dict) -> bool:
    final_statuses = {"completed", "failed", "stopped", "skipped"}
    return bool(batch.get("items")) and all(
        item.get("status") in final_statuses for item in batch.get("items") or []
    )


def _queue_next_item(storage: Storage, batch: dict, *, now: float) -> None:
    if float(batch.get("target_ready_at") or 0) > now:
        return
    items = batch.get("items") or []
    if not items:
        return
    start_index = int(batch.get("cursor") or 0) % len(items)
    for offset in range(len(items)):
        index = (start_index + offset) % len(items)
        item = items[index]
        if item.get("status") != "waiting":
            continue
        if float(item.get("next_action_at") or 0) > now:
            continue
        if int(item.get("attempts") or 0) >= int(item.get("daily_attempts") or 0):
            item["status"] = "completed"
            continue
        profile_id = int(item.get("profile_id") or 0)
        chat_id = int(item.get("chat_id") or 0)
        if _has_blocking_outgoing(storage, profile_id, chat_id, now=now):
            item["next_action_at"] = now + BUSY_RETRY_SECONDS
            item["last_result"] = "当前 Profile 仍有其他群命令待处理"
            continue
        command = build_command(batch.get("target_username") or "")
        outgoing_id = storage.enqueue_outgoing_command(
            profile_id=profile_id,
            chat_id=chat_id,
            text=command,
            thread_id=item.get("thread_id"),
            chat_type=item.get("chat_type") or "group",
            bot_username=item.get("bot_username") or "",
        )
        item["status"] = "awaiting_reply"
        item["pending_outgoing_id"] = int(outgoing_id)
        item["queued_at"] = now
        item["last_result"] = "斗法命令已入队，等待最终战报"
        item["last_error"] = ""
        batch["cursor"] = (index + 1) % len(items)
        _append_event(
            batch,
            now=now,
            item=item,
            result="queued",
            detail=f"已向 {batch.get('target_username')} 登记斗法命令",
        )
        return


def tick(
    storage: Storage,
    profiles,
    *,
    admin_profile_id: int,
    now: float | None = None,
) -> dict:
    current_time = float(now if now is not None else time.time())
    state = load_state(storage)
    config = state["config"]
    batch = state["batch"]

    if batch.get("status") == "running" and batch.get("selection_mode") != "explicit":
        return stop_batch(
            storage,
            now=current_time,
            reason="旧批次缺少出战元神选择，请重新配置",
        )

    if batch.get("status") != "running":
        next_run_at = float(config.get("next_run_at") or 0)
        if not config.get("enabled") or not next_run_at or current_time < next_run_at:
            return state
        state = start_batch(
            storage,
            profiles,
            admin_profile_id=admin_profile_id,
            source="scheduled",
            now=current_time,
        )
        state["config"]["next_run_at"] = _next_schedule_at(
            current_time + 60,
            state["config"].get("run_time") or DEFAULT_RUN_TIME,
        )
        save_state(storage, state)
        batch = state["batch"]

    pending = _find_pending_item(batch)
    if pending:
        _settle_pending_item(storage, batch, pending, now=current_time)
    if batch.get("status") == "running" and not _find_pending_item(batch):
        _queue_next_item(storage, batch, now=current_time)
    if batch.get("status") == "running" and _all_items_finished(batch):
        batch["status"] = "completed"
        batch["completed_at"] = current_time
        state["config"]["last_run_at"] = current_time
        _append_event(
            batch,
            now=current_time,
            item=None,
            result="completed",
            detail="全部执行 Profile 已结束今日争锋",
        )
    return save_state(storage, state)
