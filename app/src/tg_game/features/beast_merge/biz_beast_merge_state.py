import hashlib
import time
from copy import deepcopy
from typing import Optional


REQUEST_LEASE_SECONDS = 30 * 60
INTERRUPTED_ERROR = "执行进程已中断，未自动开启新局；当前局可能已经消耗一次。"
DEFAULT_DAILY_LIMIT = 5
CONFIRMED_ONLINE_MAX_MOVES = 160
OFFLINE_VERIFIED_MAX_MOVES = 200


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _float(value: object, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _safe_text(value: object, limit: int = 160) -> str:
    text = str(value or "").strip()
    for marker in ("beastmerge_", "beastmerge-", "runToken", "tgWebAppData", "initData"):
        if marker.lower() in text.lower():
            return "敏感运行字段已隐藏"
    return text[: max(0, int(limit))]


def _now_text(value: object = None) -> str:
    return time.strftime(
        "%Y-%m-%d %H:%M:%S",
        time.localtime(_float(value, time.time())),
    )


def _day_key(value: object = None) -> str:
    try:
        return time.strftime("%Y-%m-%d", time.localtime(float(value if value is not None else time.time())))
    except (TypeError, ValueError, OSError):
        return ""


def token_digest(value: object) -> str:
    text = str(value or "").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12] if text else ""


def _request_day(request: dict) -> str:
    queued_at = request.get("queued_at")
    return _day_key(queued_at) if queued_at else ""


def _request_active(request: object, *, now: Optional[float] = None) -> bool:
    source = request if isinstance(request, dict) else {}
    status = str(source.get("status") or "")
    if status == "queued":
        request_day = _request_day(source)
        return not request_day or request_day == _day_key(now)
    if status not in {"resolving", "running"}:
        return False
    return _float(source.get("lease_expires_at")) > _float(now, time.time())


def queue_beast_merge_request(
    payload: object,
    *,
    chat_id: int = 0,
    thread_id: Optional[int] = None,
    chat_type: str = "group",
    bot_username: str = "fanrenxiuxian_bot",
) -> dict:
    updated = deepcopy(payload) if isinstance(payload, dict) else {}
    state = dict(updated.get("beast_merge") or {})
    if _request_active(state.get("request")):
        return updated
    now = time.time()
    state["request"] = {
        "status": "queued",
        "queued_at": now,
        "queued_at_display": _now_text(now),
        "chat_id": int(chat_id or 0),
        "thread_id": int(thread_id) if thread_id is not None else None,
        "chat_type": str(chat_type or "group"),
        "bot_username": str(bot_username or "fanrenxiuxian_bot"),
    }
    previous = dict(state.get("run") or {})
    state["run"] = {
        **previous,
        "status": "queued",
        "status_label": "已排队，等待公共洞府入口",
        "current": {},
        "updated_at": _now_text(now),
        "error": "",
    }
    updated["beast_merge"] = state
    return updated


def get_pending_beast_merge_request(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    state = payload.get("beast_merge") if isinstance(payload.get("beast_merge"), dict) else {}
    request = state.get("request") if isinstance(state.get("request"), dict) else {}
    if str(request.get("status") or "") not in {"queued", "resolving", "running"}:
        return {}
    request_day = _request_day(request)
    if request_day and request_day != _day_key():
        return {}
    return request


def is_beast_merge_request_owned(payload: object, execution_owner: str) -> bool:
    request = get_pending_beast_merge_request(payload)
    return bool(request and str(request.get("execution_owner") or "") == str(execution_owner or ""))


def mark_beast_merge_request_status(
    payload: object,
    status: str,
    *,
    execution_owner: str,
    now: Optional[float] = None,
) -> dict:
    if status not in {"resolving", "running"}:
        raise ValueError("Unsupported beast merge request status")
    updated = deepcopy(payload) if isinstance(payload, dict) else {}
    state = dict(updated.get("beast_merge") or {})
    request = dict(state.get("request") or {})
    if not request or str(request.get("execution_owner") or "") != str(execution_owner or ""):
        return updated
    current_time = _float(now, time.time())
    request.update(
        {
            "status": status,
            "started_at": request.get("started_at") or current_time,
            "lease_expires_at": current_time + REQUEST_LEASE_SECONDS,
        }
    )
    run = dict(state.get("run") or {})
    run.update(
        {
            "status": status,
            "status_label": "正在获取公共洞府入口" if status == "resolving" else "正在自动进化",
            "updated_at": _now_text(current_time),
            "error": "",
        }
    )
    state["request"] = request
    state["run"] = run
    updated["beast_merge"] = state
    return updated


def claim_beast_merge_request(
    payload: object,
    execution_owner: str,
    *,
    now: Optional[float] = None,
) -> dict:
    updated = deepcopy(payload) if isinstance(payload, dict) else {}
    state = dict(updated.get("beast_merge") or {})
    request = dict(state.get("request") or {})
    status = str(request.get("status") or "")
    if not request or status not in {"queued", "resolving", "running"}:
        return updated
    request_day = _request_day(request)
    current_time = _float(now, time.time())
    if request_day and request_day != _day_key(current_time):
        return updated
    current_owner = str(request.get("execution_owner") or "")
    if status == "queued" or current_owner == str(execution_owner or ""):
        request["execution_owner"] = str(execution_owner or "")
        request["claimed_at"] = request.get("claimed_at") or current_time
        state["request"] = request
        updated["beast_merge"] = state
        return mark_beast_merge_request_status(
            updated,
            "resolving",
            execution_owner=execution_owner,
            now=current_time,
        )
    if _request_active(request, now=current_time):
        return updated
    request.update(
        {
            "status": "interrupted",
            "interrupted_at": current_time,
            "lease_expires_at": current_time,
            "error": INTERRUPTED_ERROR,
        }
    )
    run = dict(state.get("run") or {})
    run.update(
        {
            "status": "interrupted",
            "status_label": "执行中断",
            "updated_at": _now_text(current_time),
            "error": INTERRUPTED_ERROR,
        }
    )
    state["request"] = request
    state["run"] = run
    updated["beast_merge"] = state
    return updated


def _normalize_rounds(value: object) -> list[dict]:
    rounds = []
    if not isinstance(value, list):
        return rounds
    for index, item in enumerate(value[-DEFAULT_DAILY_LIMIT:], start=1):
        if not isinstance(item, dict):
            continue
        rounds.append(
            {
                "number": _int(item.get("number"), index),
                "status": _safe_text(item.get("status") or "completed", 30),
                "score": max(0, _int(item.get("score"))),
                "max_tier": max(1, _int(item.get("max_tier"), 1)),
                "merge_count": max(0, _int(item.get("merge_count"))),
                "moves_count": max(0, _int(item.get("moves_count"))),
                "duration_ms": max(0, _int(item.get("duration_ms"))),
                "trace_reward": max(0, _int(item.get("trace_reward"))),
                "rank": max(0, _int(item.get("rank"))),
                "improved": bool(item.get("improved")),
                "updated_at": _safe_text(item.get("updated_at"), 40),
            }
        )
    return rounds


def apply_beast_merge_progress(
    payload: object,
    progress: object,
    *,
    execution_owner: str,
    now: Optional[float] = None,
) -> dict:
    updated = deepcopy(payload) if isinstance(payload, dict) else {}
    if not is_beast_merge_request_owned(updated, execution_owner):
        return updated
    state = dict(updated.get("beast_merge") or {})
    request = dict(state.get("request") or {})
    run = dict(state.get("run") or {})
    source = progress if isinstance(progress, dict) else {}
    current_time = _float(now, time.time())
    request.update(
        {
            "status": "running",
            "lease_expires_at": current_time + REQUEST_LEASE_SECONDS,
        }
    )
    run.update(
        {
            "status": _safe_text(source.get("status") or "running", 30),
            "status_label": _safe_text(source.get("status_label") or "正在自动进化", 80),
            "challenge_date": _safe_text(source.get("challenge_date"), 20),
            "attempts_used": max(0, _int(source.get("attempts_used"), _int(run.get("attempts_used")))),
            "attempts_limit": max(0, _int(source.get("attempts_limit"), _int(run.get("attempts_limit")))),
            "completed_runs": max(0, _int(source.get("completed_runs"), _int(run.get("completed_runs")))),
            "service_max_moves": max(0, _int(source.get("service_max_moves"), _int(run.get("service_max_moves")))),
            "solver_depth": max(1, _int(source.get("solver_depth"), _int(run.get("solver_depth"), 4))),
            "trace_balance": max(0, _int(source.get("trace_balance"), _int(run.get("trace_balance")))),
            "best_score": max(
                0,
                _int(run.get("best_score")),
                _int(source.get("best_score")),
            ),
            "best_tier": max(
                1,
                _int(run.get("best_tier"), 1),
                _int(source.get("best_tier"), 1),
            ),
            "total_trace": max(
                0,
                _int(run.get("total_trace")),
                _int(source.get("total_trace")),
            ),
            "rank": max(0, _int(source.get("rank"), _int(run.get("rank")))),
            "participants": max(0, _int(source.get("participants"), _int(run.get("participants")))),
            "current": dict(source.get("current") or {}),
            "runs": _normalize_rounds(source.get("runs") if "runs" in source else run.get("runs")),
            "entry": dict(source.get("entry") or run.get("entry") or {}),
            "updated_at": _now_text(current_time),
            "error": _safe_text(source.get("error"), 220),
        }
    )
    state["request"] = request
    state["run"] = run
    updated["beast_merge"] = state
    return updated


def finish_beast_merge_request(
    payload: object,
    result: object,
    *,
    execution_owner: str,
    now: Optional[float] = None,
) -> dict:
    updated = deepcopy(payload) if isinstance(payload, dict) else {}
    if not is_beast_merge_request_owned(updated, execution_owner):
        return updated
    source = result if isinstance(result, dict) else {}
    updated = apply_beast_merge_progress(
        updated,
        source,
        execution_owner=execution_owner,
        now=now,
    )
    state = dict(updated.get("beast_merge") or {})
    request = dict(state.get("request") or {})
    run = dict(state.get("run") or {})
    current_time = _float(now, time.time())
    ok = bool(source.get("ok"))
    request.update(
        {
            "status": "completed" if ok else "failed",
            "completed_at": current_time,
            "lease_expires_at": current_time,
            "error": _safe_text(source.get("error"), 220),
        }
    )
    run.update(
        {
            "status": "completed" if ok else "failed",
            "status_label": _safe_text(
                source.get("status_label") or ("今日剩余局数已完成" if ok else "执行失败，未自动开启新局"),
                80,
            ),
            "current": {},
            "updated_at": _now_text(current_time),
            "error": _safe_text(source.get("error"), 220),
        }
    )
    state["request"] = request
    state["run"] = run
    updated["beast_merge"] = state
    return updated


def is_beast_merge_daily_limit_reached(payload: object) -> bool:
    state = payload.get("beast_merge") if isinstance(payload, dict) else {}
    run = state.get("run") if isinstance(state, dict) and isinstance(state.get("run"), dict) else {}
    used = max(0, _int(run.get("attempts_used")))
    limit = max(0, _int(run.get("attempts_limit")))
    return limit > 0 and used >= limit


def was_beast_merge_requested_today(
    payload: object,
    *,
    now: Optional[float] = None,
) -> bool:
    state = payload.get("beast_merge") if isinstance(payload, dict) else {}
    request = state.get("request") if isinstance(state, dict) and isinstance(state.get("request"), dict) else {}
    request_day = _request_day(request)
    return bool(request_day and request_day == _day_key(now))


def _tier_name(value: object) -> str:
    names = {
        1: "金精矿",
        2: "庚金砂",
        3: "幼年噬金虫",
        4: "成熟噬金虫",
        5: "噬金虫群",
        6: "噬金仙",
        7: "噬金虫王",
        8: "虚空虫母",
        9: "万界归一者",
    }
    tier = max(1, min(9, _int(value, 1)))
    return f"{tier} 阶 · {names[tier]}"


def build_beast_merge_view(
    payload: object,
    daily_task: Optional[dict] = None,
    *,
    now: Optional[float] = None,
) -> dict:
    from . import biz_beast_merge_daily_auto

    current_time = _float(now, time.time())
    root = payload if isinstance(payload, dict) else {}
    state = root.get("beast_merge") if isinstance(root.get("beast_merge"), dict) else {}
    request = state.get("request") if isinstance(state.get("request"), dict) else {}
    run = state.get("run") if isinstance(state.get("run"), dict) else {}
    current = run.get("current") if isinstance(run.get("current"), dict) else {}
    active = _request_active(request, now=current_time)
    used = max(0, _int(run.get("attempts_used")))
    limit = max(0, _int(run.get("attempts_limit"), DEFAULT_DAILY_LIMIT)) or DEFAULT_DAILY_LIMIT
    service_max_moves = max(0, _int(run.get("service_max_moves")))
    daily = daily_task or {}
    daily_active = bool(daily) and bool(daily.get("enabled"))
    next_run_at = max(0.0, _float(daily.get("next_run_at")))
    run_time = biz_beast_merge_daily_auto.normalize_run_time(daily.get("strategy"))
    last_error = _safe_text(daily.get("last_error"), 180)
    status_label = _safe_text(run.get("status_label") or "未启动", 80)
    if str(request.get("status") or "") in {"resolving", "running"} and not active:
        status_label = "执行中断（可能已消耗 1 局）"
    limit_reached = limit > 0 and used >= limit
    rounds = _normalize_rounds(run.get("runs"))
    return {
        "active": active,
        "status": _safe_text(run.get("status") or "idle", 30),
        "status_label": status_label,
        "challenge_date": _safe_text(run.get("challenge_date") or "-", 20),
        "attempts_used": used,
        "attempts_limit": limit,
        "attempts_text": f"{used}/{limit}",
        "limit_reached": limit_reached,
        "completed_runs": max(0, _int(run.get("completed_runs"), len(rounds))),
        "service_max_moves": service_max_moves,
        "service_max_moves_text": str(service_max_moves or CONFIRMED_ONLINE_MAX_MOVES),
        "offline_verified_moves": OFFLINE_VERIFIED_MAX_MOVES,
        "solver_depth": max(1, _int(run.get("solver_depth"), 4)),
        "current_moves": max(0, _int(current.get("moves_count"), _int(current.get("seq")))),
        "current_score": max(0, _int(current.get("score"))),
        "current_tier": _tier_name(current.get("max_tier")) if current else "-",
        "current_merges": max(0, _int(current.get("merge_count"))),
        "current_empty": max(0, _int(current.get("empty_count"))) if current else 0,
        "best_score": max([max(0, _int(run.get("best_score"))), *[item["score"] for item in rounds]], default=0),
        "best_tier": _tier_name(max([max(1, _int(run.get("best_tier"), 1)), *[item["max_tier"] for item in rounds]], default=1)),
        "trace_balance": max(0, _int(run.get("trace_balance"))),
        "total_trace": max(0, _int(run.get("total_trace"))),
        "rank": max(0, _int(run.get("rank"))),
        "participants": max(0, _int(run.get("participants"))),
        "rounds": rounds,
        "updated_at": _safe_text(run.get("updated_at") or "-", 40),
        "error": _safe_text(run.get("error"), 220),
        "manual_disabled": active or limit_reached,
        "manual_label": (
            "正在自动进化"
            if active
            else ("今日虫巢已满额" if limit_reached else "自动打满今日剩余局数")
        ),
        "daily_auto_enabled": daily_active,
        "daily_run_time": run_time,
        "daily_next_run_at": next_run_at,
        "daily_status": (
            "等待下次固定时间"
            if daily_active and next_run_at > current_time
            else (last_error or ("已开启" if daily_active else "未开启"))
        ),
        "entry": dict(run.get("entry") or {}),
        "safety_boundary": (
            "仅复用公共洞府入口并串行调用服务端棋局接口；不发送群命令，"
            "不保存 df/beast token、initData 或 runToken。"
        ),
    }
