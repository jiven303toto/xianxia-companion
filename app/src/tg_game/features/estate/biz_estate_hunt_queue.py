from copy import deepcopy
from datetime import datetime
import re
import time
from typing import Optional
from .biz_estate_constants import (
    ESTATE_MINIAPP_DEFAULT_BOT_USERNAME,
    MINIAPP_HUNT_SAFETY_BOUNDARY,
)
from .biz_estate_safety import _safe_text
from .biz_estate_view_state import (
    _as_dict,
    _as_list,
    _build_hunt_round_summary,
    _first_text,
    _hunt_chance_text,
    _hunt_logs,
    _hunt_loot_text,
    _int_or_zero,
    _merge_hunt_loot,
    _normalize_hunt_loot,
    _normalize_hunt_rounds,
    build_estate_miniapp_hunt,
)


_DEFAULT_HUNT_REVEAL_ORDER = (
    12,
    7,
    11,
    13,
    17,
    6,
    8,
    16,
    18,
    0,
    4,
    20,
    24,
    1,
    3,
    5,
    9,
    15,
    19,
    21,
    23,
    2,
    10,
    14,
    22,
)


def _estate_miniapp_day_key(value: object = None) -> str:
    if value is None:
        return time.strftime("%Y-%m-%d", time.localtime(time.time()))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        try:
            return time.strftime("%Y-%m-%d", time.localtime(timestamp))
        except (OverflowError, OSError, ValueError):
            return ""
    text = str(value or "").strip()
    if not text or text in {"-", "0"}:
        return ""
    try:
        return _estate_miniapp_day_key(float(text))
    except (TypeError, ValueError):
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            return _estate_miniapp_day_key(parsed.timestamp())
        return parsed.strftime("%Y-%m-%d")
    except ValueError:
        pass
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    return match.group(0) if match else ""


def is_estate_miniapp_hunt_state_stale(hunt: object) -> bool:
    hunt_data = _as_dict(hunt)
    day_key = _estate_miniapp_day_key(hunt_data.get("updated_at"))
    return bool(day_key and day_key != _estate_miniapp_day_key())


def _revealed_hunt_indices(run: dict) -> set[int]:
    indices: set[int] = set()
    for cell in _as_list(run.get("cells")):
        if not isinstance(cell, dict) or not cell.get("revealed"):
            continue
        try:
            indices.add(int(cell.get("index")))
        except (TypeError, ValueError):
            continue
    return indices


def _choose_hunt_reveal_index(run: dict, tried: list[int]) -> Optional[int]:
    revealed = _revealed_hunt_indices(run)
    blocked = set(tried) | revealed
    hint = _as_dict(run.get("latestHint"))
    markers = [item for item in _as_list(hint.get("markers")) if isinstance(item, dict)]
    for preferred_kind in ("treasure", "resource"):
        for marker in markers:
            if marker.get("kind") != preferred_kind:
                continue
            try:
                index = int(marker.get("index"))
            except (TypeError, ValueError):
                continue
            if index not in blocked:
                return index
    for index in _DEFAULT_HUNT_REVEAL_ORDER:
        if index not in blocked:
            return index
    return None


def _build_hunt_state(
    *,
    status: str,
    run: object = None,
    result: object = None,
    dwelling: object = None,
    error: object = "",
    events: Optional[list] = None,
    strategy: str = "exhaust_ap",
    revealed_indices: Optional[list[int]] = None,
) -> dict:
    from .biz_estate_miniapp import sanitize_estate_miniapp_secret_text
    run_data = _as_dict(run)
    result_data = _as_dict(result)
    dwelling_data = _as_dict(dwelling)
    hunt_limits = _as_dict(dwelling_data.get("hunt"))
    loot = _normalize_hunt_loot(result_data.get("loot") or run_data.get("loot"))
    logs = _hunt_logs(result_data.get("logs") or run_data.get("logs"))
    latest_hint = _as_dict(run_data.get("latestHint"))
    return {
        "status": str(status or "unknown"),
        "updated_at": time.time(),
        "strategy": strategy,
        "grade": _first_text(result_data.get("grade")) or "-",
        "score": _int_or_zero(result_data.get("score") or run_data.get("score")),
        "contribution": _int_or_zero(result_data.get("contribution")),
        "found_main": bool(result_data.get("foundMain") or run_data.get("foundMain")),
        "ap": _int_or_zero(run_data.get("ap")),
        "max_ap": _int_or_zero(run_data.get("maxAp")),
        "revealed_count": _int_or_zero(
            result_data.get("revealedCount") or run_data.get("revealedCount")
        ),
        "remaining": _int_or_zero(hunt_limits.get("remaining")),
        "used": _int_or_zero(hunt_limits.get("used")),
        "limit": _int_or_zero(hunt_limits.get("limit")),
        "loot": loot,
        "loot_text": _hunt_loot_text(loot),
        "logs": logs,
        "latest_hint": sanitize_estate_miniapp_secret_text(
            latest_hint.get("text") or "", limit=160
        ),
        "revealed_indices": list(revealed_indices or []),
        "events": list(events or [])[-8:],
        "error": sanitize_estate_miniapp_secret_text(error),
        "safety_boundary": MINIAPP_HUNT_SAFETY_BOUNDARY,
    }


def _extract_hunt_limits_state(data: object) -> dict:
    from .biz_estate_miniapp import _extract_snapshot_source
    dwelling = _as_dict(_extract_snapshot_source(data))
    limits = _as_dict(dwelling.get("hunt"))
    used = _int_or_zero(limits.get("used"))
    limit = _int_or_zero(limits.get("limit"))
    remaining = _int_or_zero(limits.get("remaining"))
    if not (used or limit or remaining):
        return {}
    reached = bool(limit and (used >= limit or remaining <= 0))
    return {
        "status": "limit_reached" if reached else "synced",
        "updated_at": time.time(),
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "chance_text": _hunt_chance_text(used, limit, remaining),
        "automation_status": "今日次数已满" if reached else "状态已刷新",
        "error": "",
        "safety_boundary": MINIAPP_HUNT_SAFETY_BOUNDARY,
    }


def build_estate_miniapp_hunt_request(
    *,
    max_reveals: int = 8,
    min_ap_to_settle: int = 0,
    chat_id: object = "",
    thread_id: object = None,
    chat_type: str = "group",
    bot_username: str = ESTATE_MINIAPP_DEFAULT_BOT_USERNAME,
    runs_completed: int = 0,
    total_loot: object = None,
    total_contribution: int = 0,
    started_at: object = None,
    rounds: object = None,
) -> dict:
    now = time.time()
    normalized_thread_id = None
    if thread_id not in (None, ""):
        normalized_thread_id = _int_or_zero(thread_id)
    return {
        "status": "queued",
        "mode": "auto_daily",
        "requested_at": now,
        "started_at": started_at or now,
        "max_reveals": max(1, min(_int_or_zero(max_reveals), 8)),
        "min_ap_to_settle": max(0, min(_int_or_zero(min_ap_to_settle), 8)),
        "chat_id": _int_or_zero(chat_id),
        "thread_id": normalized_thread_id,
        "chat_type": _safe_text(chat_type or "group", 20) or "group",
        "bot_username": _safe_text(
            bot_username or ESTATE_MINIAPP_DEFAULT_BOT_USERNAME, 64
        )
        or ESTATE_MINIAPP_DEFAULT_BOT_USERNAME,
        "runs_completed": max(0, _int_or_zero(runs_completed)),
        "total_loot": _merge_hunt_loot(total_loot),
        "total_contribution": max(0, _int_or_zero(total_contribution)),
        "rounds": _normalize_hunt_rounds(rounds),
    }


def queue_estate_miniapp_hunt_request(
    payload: dict,
    *,
    max_reveals: int = 8,
    min_ap_to_settle: int = 0,
    chat_id: object = "",
    thread_id: object = None,
    chat_type: str = "group",
    bot_username: str = ESTATE_MINIAPP_DEFAULT_BOT_USERNAME,
) -> dict:
    result = deepcopy(payload if isinstance(payload, dict) else {})
    dongfu = result.get("dongfu")
    if not isinstance(dongfu, dict):
        dongfu = {}
    else:
        dongfu = dict(dongfu)
    dongfu.pop("miniapp_launch", None)
    request = build_estate_miniapp_hunt_request(
        max_reveals=max_reveals,
        min_ap_to_settle=min_ap_to_settle,
        chat_id=chat_id,
        thread_id=thread_id,
        chat_type=chat_type,
        bot_username=bot_username,
    )
    dongfu["miniapp_hunt_request"] = request
    dongfu["miniapp_hunt"] = {
        "status": "queued",
        "updated_at": request["requested_at"],
        "strategy": "exhaust_ap",
        "automation_mode": "auto_daily",
        "automation_runs": 0,
        "automation_total_loot": [],
        "automation_total_contribution": 0,
        "rounds": [],
        "automation_status": "等待入口",
        "error": "",
        "safety_boundary": MINIAPP_HUNT_SAFETY_BOUNDARY,
    }
    result["dongfu"] = dongfu
    return result


def get_pending_estate_miniapp_hunt_request(payload: object) -> dict:
    root = _as_dict(payload)
    dongfu = _as_dict(root.get("dongfu"))
    request = _as_dict(dongfu.get("miniapp_hunt_request"))
    return request if request.get("status") in {"queued", "resolving", "running"} else {}


def mark_estate_miniapp_hunt_request_status(payload: object, status: str) -> dict:
    if status not in {"resolving", "running"}:
        raise ValueError("Unsupported estate MiniApp request status")
    result = deepcopy(payload if isinstance(payload, dict) else {})
    dongfu = dict(result.get("dongfu") or {})
    request = dict(dongfu.get("miniapp_hunt_request") or {})
    if not request:
        return result
    now = time.time()
    request["status"] = status
    request["started_at"] = request.get("started_at") or now
    hunt = dict(dongfu.get("miniapp_hunt") or {})
    hunt.update(
        {
            "status": status,
            "updated_at": now,
            "automation_status": "正在获取入口" if status == "resolving" else "正在寻宝",
            "error": "",
        }
    )
    dongfu["miniapp_hunt_request"] = request
    dongfu["miniapp_hunt"] = hunt
    result["dongfu"] = dongfu
    return result


def is_estate_miniapp_hunt_limit_reached(payload: object) -> bool:
    root = _as_dict(payload)
    dongfu = _as_dict(root.get("dongfu"))
    hunt = _as_dict(dongfu.get("miniapp_hunt"))
    if is_estate_miniapp_hunt_state_stale(hunt):
        return False
    used = _int_or_zero(hunt.get("used"))
    limit = _int_or_zero(hunt.get("limit"))
    remaining = _int_or_zero(hunt.get("remaining"))
    return bool(limit and (used >= limit or remaining <= 0))


def mark_estate_miniapp_hunt_limit_reached(payload: object) -> dict:
    result = deepcopy(payload if isinstance(payload, dict) else {})
    dongfu = result.get("dongfu")
    if not isinstance(dongfu, dict):
        dongfu = {}
    else:
        dongfu = dict(dongfu)
    hunt = build_estate_miniapp_hunt(dongfu.get("miniapp_hunt"))
    hunt.update(
        {
            "status": "limit_reached",
            "updated_at": time.time(),
            "automation_mode": "auto_daily",
            "automation_status": "今日次数已满",
            "error": "",
            "safety_boundary": MINIAPP_HUNT_SAFETY_BOUNDARY,
        }
    )
    dongfu["miniapp_hunt"] = hunt
    dongfu.pop("miniapp_hunt_request", None)
    result["dongfu"] = dongfu
    return result


def continue_estate_miniapp_hunt_automation(
    request: object,
    hunt: object,
) -> tuple[dict, dict]:
    request_data = _as_dict(request)
    hunt_data = _as_dict(hunt)
    previous_runs = _int_or_zero(request_data.get("runs_completed"))
    was_settled = str(hunt_data.get("status") or "") == "settled"
    runs_completed = previous_runs + (1 if was_settled else 0)
    total_loot = _merge_hunt_loot(request_data.get("total_loot"), hunt_data.get("loot"))
    total_contribution = _int_or_zero(request_data.get("total_contribution"))
    if was_settled:
        total_contribution += _int_or_zero(hunt_data.get("contribution"))

    used = _int_or_zero(hunt_data.get("used"))
    limit = _int_or_zero(hunt_data.get("limit"))
    remaining = _int_or_zero(hunt_data.get("remaining"))
    can_continue = bool(was_settled and limit and used < limit and remaining > 0)
    automation_status = "继续执行" if can_continue else "今日次数已满"
    if not was_settled:
        automation_status = "执行失败，已停止"
    if was_settled and not limit:
        automation_status = "已结算，等待下次确认次数"

    previous_rounds = _normalize_hunt_rounds(request_data.get("rounds"))
    next_round_number = len(previous_rounds) + 1 if previous_rounds else previous_runs + 1
    rounds = [
        *previous_rounds,
        _build_hunt_round_summary(hunt_data, round_number=next_round_number),
    ]

    updated_hunt = dict(hunt_data)
    updated_hunt.update(
        {
            "automation_mode": "auto_daily",
            "automation_runs": runs_completed,
            "automation_total_loot": total_loot,
            "automation_total_loot_text": _hunt_loot_text(total_loot),
            "automation_total_contribution": total_contribution,
            "rounds": rounds,
            "automation_status": automation_status,
            "automation_started_at": request_data.get("started_at")
            or request_data.get("requested_at")
            or time.time(),
            "automation_completed_at": time.time() if not can_continue else "",
            "safety_boundary": MINIAPP_HUNT_SAFETY_BOUNDARY,
        }
    )

    next_request = {}
    if can_continue:
        request_max_reveals = _int_or_zero(request_data.get("max_reveals"))
        request_min_ap = _int_or_zero(request_data.get("min_ap_to_settle"))
        next_request = build_estate_miniapp_hunt_request(
            max_reveals=request_max_reveals or 8,
            min_ap_to_settle=request_min_ap
            if "min_ap_to_settle" in request_data
            else 0,
            chat_id=request_data.get("chat_id"),
            thread_id=request_data.get("thread_id"),
            chat_type=request_data.get("chat_type") or "group",
            bot_username=request_data.get("bot_username")
            or ESTATE_MINIAPP_DEFAULT_BOT_USERNAME,
            runs_completed=runs_completed,
            total_loot=total_loot,
            total_contribution=total_contribution,
            started_at=request_data.get("started_at")
            or request_data.get("requested_at")
            or time.time(),
            rounds=rounds,
        )
    return updated_hunt, next_request
