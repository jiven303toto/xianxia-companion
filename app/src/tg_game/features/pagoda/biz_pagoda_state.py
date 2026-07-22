import json
import time
from copy import deepcopy
from typing import Optional


PAGODA_REQUEST_LEASE_SECONDS = 5 * 60
PAGODA_INTERRUPTED_ERROR = "闯塔执行进程已中断，未自动重试；请重新发起。"
ACTIVE_REQUEST_STATUSES = {"queued", "resolving", "running"}


def _now_text(value: object = None) -> str:
    try:
        timestamp = float(time.time() if value is None else value)
    except (TypeError, ValueError):
        timestamp = time.time()
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))


def _day_key(value: object = None) -> str:
    try:
        timestamp = float(time.time() if value is None else value)
    except (TypeError, ValueError):
        return ""
    return time.strftime("%Y-%m-%d", time.localtime(timestamp))


def _float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _dict(value: object) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _pagoda_root(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    return payload.get("pagoda_miniapp") if isinstance(payload.get("pagoda_miniapp"), dict) else {}


def get_pagoda_request(payload: object) -> dict:
    root = _pagoda_root(payload)
    return root.get("request") if isinstance(root.get("request"), dict) else {}


def has_active_pagoda_request(payload: object, *, now: Optional[float] = None) -> bool:
    return _request_is_active(get_pagoda_request(payload), now=now)


def _request_is_active(request: object, *, now: Optional[float] = None) -> bool:
    source = request if isinstance(request, dict) else {}
    status = str(source.get("status") or "")
    current = float(time.time() if now is None else now)
    if status == "queued":
        return _day_key(source.get("queued_at")) in {"", _day_key(current)}
    if status in {"resolving", "running"}:
        return _float(source.get("lease_expires_at")) > current
    return False


def queue_pagoda_request(
    payload: object,
    *,
    chat_id: int = 0,
    thread_id: Optional[int] = None,
    chat_type: str = "group",
    bot_username: str = "fanrenxiuxian_bot",
    delay_seconds: int = 0,
) -> dict:
    updated = deepcopy(payload) if isinstance(payload, dict) else {}
    root = dict(updated.get("pagoda_miniapp") or {})
    if _request_is_active(root.get("request")):
        return updated
    now = time.time()
    root["request"] = {
        "status": "queued",
        "queued_at": now,
        "queued_at_display": _now_text(now),
        "not_before": now + max(int(delay_seconds or 0), 0),
        "chat_id": int(chat_id or 0),
        "thread_id": int(thread_id) if thread_id is not None else None,
        "chat_type": str(chat_type or "group"),
        "bot_username": str(bot_username or "fanrenxiuxian_bot"),
    }
    root["run"] = {
        "status": "queued",
        "phase": "queued",
        "status_label": "已排队，等待公共洞府入口",
        "updated_at": _now_text(now),
        "day_key": _day_key(now),
        "error": "",
    }
    updated["pagoda_miniapp"] = root
    return updated


def get_pending_pagoda_request(payload: object, *, now: Optional[float] = None) -> dict:
    request = get_pagoda_request(payload)
    current = float(time.time() if now is None else now)
    if not _request_is_active(request, now=current):
        return {}
    if str(request.get("status") or "") == "queued" and _float(request.get("not_before")) > current:
        return {}
    return request


def is_pagoda_request_owned(payload: object, execution_owner: str) -> bool:
    request = get_pending_pagoda_request(payload)
    return bool(request and str(request.get("execution_owner") or "") == str(execution_owner or ""))


def claim_pagoda_request(
    payload: object,
    execution_owner: str,
    *,
    now: Optional[float] = None,
) -> dict:
    updated = deepcopy(payload) if isinstance(payload, dict) else {}
    root = dict(updated.get("pagoda_miniapp") or {})
    request = dict(root.get("request") or {})
    current = float(time.time() if now is None else now)
    status = str(request.get("status") or "")
    if status in {"resolving", "running"} and _float(request.get("lease_expires_at")) <= current:
        request["status"] = "interrupted"
        request["error"] = PAGODA_INTERRUPTED_ERROR
        root["request"] = request
        root["run"] = {
            **dict(root.get("run") or {}),
            "status": "interrupted",
            "status_label": "执行已中断",
            "updated_at": _now_text(current),
            "error": PAGODA_INTERRUPTED_ERROR,
        }
        updated["pagoda_miniapp"] = root
        return updated
    if status != "queued" or _float(request.get("not_before")) > current:
        return updated
    if _day_key(request.get("queued_at")) not in {"", _day_key(current)}:
        return updated
    request.update(
        {
            "status": "resolving",
            "phase": "entry",
            "execution_owner": str(execution_owner or ""),
            "started_at": current,
            "lease_expires_at": current + PAGODA_REQUEST_LEASE_SECONDS,
        }
    )
    root["request"] = request
    root["run"] = {
        **dict(root.get("run") or {}),
        "status": "resolving",
        "phase": "entry",
        "status_label": "正在解析公共洞府入口",
        "updated_at": _now_text(current),
        "error": "",
    }
    updated["pagoda_miniapp"] = root
    return updated


def mark_pagoda_request_running(
    payload: object,
    *,
    execution_owner: str,
    phase: str = "start",
    now: Optional[float] = None,
) -> dict:
    updated = deepcopy(payload) if isinstance(payload, dict) else {}
    root = dict(updated.get("pagoda_miniapp") or {})
    request = dict(root.get("request") or {})
    if str(request.get("execution_owner") or "") != str(execution_owner or ""):
        return updated
    current = float(time.time() if now is None else now)
    requested_phase = str(phase or "")
    current_phase = (
        requested_phase
        if requested_phase in {"challenge", "settlement_confirm"}
        else "start"
    )
    request["status"] = "running"
    request["phase"] = current_phase
    request["lease_expires_at"] = current + PAGODA_REQUEST_LEASE_SECONDS
    root["request"] = request
    root["run"] = {
        **dict(root.get("run") or {}),
        "status": "running",
        "phase": current_phase,
        "status_label": {
            "challenge": "服务端正在结算闯塔",
            "settlement_confirm": "等待服务端结算核验",
        }.get(current_phase, "正在读取琉璃塔况"),
        "updated_at": _now_text(current),
        "error": "",
    }
    updated["pagoda_miniapp"] = root
    return updated


def renew_pagoda_request_lease(
    payload: object,
    *,
    execution_owner: str,
    now: Optional[float] = None,
) -> dict:
    updated = deepcopy(payload) if isinstance(payload, dict) else {}
    root = dict(updated.get("pagoda_miniapp") or {})
    request = dict(root.get("request") or {})
    if str(request.get("execution_owner") or "") != str(execution_owner or ""):
        return updated
    if str(request.get("status") or "") not in {"resolving", "running"}:
        return updated
    current = float(time.time() if now is None else now)
    request["lease_expires_at"] = current + PAGODA_REQUEST_LEASE_SECONDS
    request["lease_renewed_at"] = current
    root["request"] = request
    root["run"] = {
        **dict(root.get("run") or {}),
        "updated_at": _now_text(current),
    }
    updated["pagoda_miniapp"] = root
    return updated


def finish_pagoda_request(
    payload: object,
    result: object,
    *,
    execution_owner: str,
    now: Optional[float] = None,
) -> dict:
    updated = deepcopy(payload) if isinstance(payload, dict) else {}
    root = dict(updated.get("pagoda_miniapp") or {})
    request = dict(root.get("request") or {})
    if str(request.get("execution_owner") or "") != str(execution_owner or ""):
        return updated
    source = result if isinstance(result, dict) else {}
    current = float(time.time() if now is None else now)
    status = str(source.get("status") or "failed")
    if not source.get("ok"):
        status = "failed"
    state = source.get("state") if isinstance(source.get("state"), dict) else {}
    replay = source.get("replay") if isinstance(source.get("replay"), dict) else {}
    status_label = {
        "settled": "闯塔已结算",
        "skipped": "今日已闯塔，无需重复执行",
        "failed": "闯塔执行失败",
    }.get(status, "闯塔执行结束")
    root.pop("request", None)
    root["entry"] = source.get("entry") if isinstance(source.get("entry"), dict) else root.get("entry", {})
    root["run"] = {
        "status": status,
        "phase": "completed",
        "status_label": status_label,
        "ok": bool(source.get("ok")),
        "state": state,
        "replay": replay,
        "reward_lines": list(replay.get("rewardLines") or []),
        "day_key": _day_key(current),
        "updated_at": _now_text(current),
        "updated_at_ts": current,
        "error": str(source.get("error") or "")[:500],
    }
    updated["pagoda_miniapp"] = root

    if status in {"settled", "skipped"}:
        progress = _dict(updated.get("pagoda_progress"))
        progress["highest_floor"] = int(state.get("recordHighest") or progress.get("highest_floor") or 0)
        progress["last_attempt_date"] = _now_text(current)
        progress["is_in_pagoda"] = False
        updated["pagoda_progress"] = progress
        updated["pagoda_failed_floor"] = int(state.get("failedFloor") or replay.get("failedFloor") or 0)
        updated["pagoda_resets_today"] = int(state.get("resetsToday") or 0)
    return updated


def was_pagoda_completed_today(payload: object, *, now: Optional[float] = None) -> bool:
    run = _pagoda_root(payload).get("run")
    run = run if isinstance(run, dict) else {}
    return str(run.get("status") or "") in {"settled", "skipped"} and str(run.get("day_key") or "") == _day_key(now)


def build_pagoda_miniapp_view(payload: object) -> dict:
    root = _pagoda_root(payload)
    request = get_pagoda_request(payload)
    run = root.get("run") if isinstance(root.get("run"), dict) else {}
    state = run.get("state") if isinstance(run.get("state"), dict) else {}
    replay = run.get("replay") if isinstance(run.get("replay"), dict) else {}
    active = str(request.get("status") or "") in ACTIVE_REQUEST_STATUSES
    return {
        "active": active,
        "status": str(run.get("status") or "idle"),
        "phase": str(run.get("phase") or request.get("phase") or ""),
        "status_label": str(run.get("status_label") or "尚未通过 MiniApp 执行"),
        "updated_at": str(run.get("updated_at") or ""),
        "error": str(run.get("error") or ""),
        "state": state,
        "replay": replay,
        "reward_lines": list(run.get("reward_lines") or replay.get("rewardLines") or []),
    }
