import json
import time
from copy import deepcopy
from typing import Optional

def _now_text(value: object = None) -> str:
    try:
        ts = float(value if value is not None else time.time())
    except (TypeError, ValueError):
        ts = time.time()
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def _day_key_from_timestamp(value: object) -> str:
    try:
        return time.strftime("%Y-%m-%d", time.localtime(float(value)))
    except (TypeError, ValueError, OSError):
        return ""


def _day_key_from_text(value: object) -> str:
    text = str(value or "").strip()
    if (
        len(text) >= 10
        and text[4] == "-"
        and text[7] == "-"
        and text[:4].isdigit()
        and text[5:7].isdigit()
        and text[8:10].isdigit()
    ):
        return text[:10]
    return ""


def _current_day_key() -> str:
    return _day_key_from_timestamp(time.time())


def _tianji_trial_request_day_key(request: object) -> str:
    source = request if isinstance(request, dict) else {}
    return _day_key_from_timestamp(source.get("queued_at")) or _day_key_from_text(
        source.get("queued_at_display")
    )


def _is_stale_tianji_trial_request(request: object) -> bool:
    request_day = _tianji_trial_request_day_key(request)
    return bool(request_day and request_day != _current_day_key())


def _miniapp_int(value: object, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _target_runs(value: object) -> int:
    from .biz_tianji_trial_miniapp import TIANJI_TRIAL_DEFAULT_BATCH_RUNS
    return max(
        1,
        min(
            TIANJI_TRIAL_DEFAULT_BATCH_RUNS,
            _miniapp_int(value, TIANJI_TRIAL_DEFAULT_BATCH_RUNS),
        ),
    )


def queue_tianji_trial_request(
    payload: object,
    *,
    chat_id: int = 0,
    thread_id: Optional[int] = None,
    chat_type: str = "group",
    bot_username: str = "fanrenxiuxian_bot",
    target_runs: int = 3,
) -> dict:
    from .biz_tianji_trial_miniapp import TIANJI_TRIAL_MINIAPP_DEFAULT_BOT_USERNAME
    updated = deepcopy(payload) if isinstance(payload, dict) else {}
    trial = dict(updated.get("tianji_trial") or {})
    now = time.time()
    target = _target_runs(target_runs)
    trial["miniapp_request"] = {
        "status": "queued",
        "queued_at": now,
        "queued_at_display": _now_text(now),
        "chat_id": int(chat_id or 0),
        "thread_id": int(thread_id) if thread_id is not None else None,
        "chat_type": str(chat_type or "group"),
        "bot_username": str(bot_username or TIANJI_TRIAL_MINIAPP_DEFAULT_BOT_USERNAME),
        "target_runs": target,
        "completed_runs": 0,
        "rounds": [],
    }
    trial["miniapp_run"] = {
        "status": "queued",
        "status_label": "已排队，等待第1关入口",
        "target_runs": target,
        "completed_runs": 0,
        "rounds": [],
        "progress_text": f"0/{target}",
        "updated_at": _now_text(now),
        "error": "",
    }
    updated["tianji_trial"] = trial
    return updated


def get_pending_tianji_trial_request(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    trial = payload.get("tianji_trial") if isinstance(payload.get("tianji_trial"), dict) else {}
    request = trial.get("miniapp_request") if isinstance(trial.get("miniapp_request"), dict) else {}
    if str(request.get("status") or "") not in {"queued", "running"}:
        return {}
    return {} if _is_stale_tianji_trial_request(request) else request


def _normalize_tianji_trial_rounds(value: object) -> list[dict]:
    from .biz_tianji_trial_miniapp import (
    TIANJI_TRIAL_DEFAULT_BATCH_RUNS,
        _safe_text,
        sanitize_tianji_trial_secret_text,
    )

    rounds: list[dict] = []
    if not isinstance(value, list):
        return rounds
    for index, item in enumerate(value[:TIANJI_TRIAL_DEFAULT_BATCH_RUNS], start=1):
        if not isinstance(item, dict):
            continue
        number = _miniapp_int(item.get("number"), index) or index
        ok = bool(item.get("ok"))
        status = _safe_text(item.get("status") or ("settled" if ok else "failed"), 40)
        rounds.append(
            {
                "number": number,
                "trial_index": _miniapp_int(item.get("trial_index"), number) or number,
                "daily_limit": _miniapp_int(item.get("daily_limit"), TIANJI_TRIAL_DEFAULT_BATCH_RUNS)
                or TIANJI_TRIAL_DEFAULT_BATCH_RUNS,
                "status": status,
                "status_label": _safe_text(
                    item.get("status_label") or ("已完成" if ok else "失败"),
                    40,
                ),
                "ok": ok,
                "mode": _safe_text(item.get("mode") or "", 50),
                "trial_title": _safe_text(item.get("trial_title") or "-", 80),
                "difficulty": _safe_text(item.get("difficulty") or "-", 40),
                "grade": _safe_text(item.get("grade") or "-", 20),
                "score": _miniapp_int(item.get("score")),
                "reward_trace": _miniapp_int(item.get("reward_trace")),
                "duration_ms": _miniapp_int(item.get("duration_ms")),
                "updated_at": _safe_text(item.get("updated_at") or "", 40),
                "error": sanitize_tianji_trial_secret_text(item.get("error") or ""),
            }
        )
    return rounds


def _result_settlement_data(result: object) -> tuple[dict, dict, dict]:
    data = result if isinstance(result, dict) else {}
    result_data = data.get("data") if isinstance(data.get("data"), dict) else {}
    settlement = result_data.get("result") if isinstance(result_data.get("result"), dict) else result_data
    challenge = result_data.get("challenge") if isinstance(result_data.get("challenge"), dict) else {}
    trial = result_data.get("trial") if isinstance(result_data.get("trial"), dict) else {}
    return settlement if isinstance(settlement, dict) else {}, challenge, trial


def build_tianji_trial_round(result: object, *, round_number: int) -> dict:
    from .biz_tianji_trial_miniapp import (
    TIANJI_TRIAL_DEFAULT_BATCH_RUNS,
        _safe_text,
        sanitize_tianji_trial_secret_text,
    )

    data = result if isinstance(result, dict) else {}
    settlement, challenge, trial = _result_settlement_data(data)
    details = settlement.get("details") if isinstance(settlement.get("details"), dict) else {}
    ok = bool(data.get("ok"))
    status = str(data.get("status") or ("settled" if ok else "failed")).strip() or "unknown"
    trial_index = _miniapp_int(challenge.get("trialIndex"), round_number) or round_number
    daily_limit = _miniapp_int(trial.get("dailyLimit"), TIANJI_TRIAL_DEFAULT_BATCH_RUNS) or TIANJI_TRIAL_DEFAULT_BATCH_RUNS
    return {
        "number": max(1, _miniapp_int(round_number, 1)),
        "trial_index": trial_index,
        "daily_limit": daily_limit,
        "status": status,
        "status_label": "已完成" if ok else "失败",
        "ok": ok,
        "mode": str((data.get("proof") or {}).get("mode") or challenge.get("mode") or settlement.get("trial_type") or ""),
        "trial_title": _safe_text(settlement.get("trial_title") or trial.get("title") or "", 80),
        "difficulty": _safe_text(
            details.get("difficulty_label")
            or details.get("difficulty")
            or challenge.get("difficultyLabel")
            or challenge.get("difficulty")
            or "",
            40,
        ),
        "grade": _safe_text(settlement.get("grade") or "", 20),
        "score": int(settlement.get("score") or 0),
        "reward_trace": int(settlement.get("reward_trace") or 0),
        "duration_ms": int(settlement.get("duration_ms") or (data.get("proof") or {}).get("durationMs") or 0),
        "updated_at": _now_text(),
        "error": sanitize_tianji_trial_secret_text(data.get("error") or ""),
    }


def build_next_tianji_trial_request(
    request: object,
    *,
    rounds: object,
    target_runs: int,
) -> dict:
    source = request if isinstance(request, dict) else {}
    normalized_rounds = _normalize_tianji_trial_rounds(rounds)
    now = time.time()
    updated = dict(source)
    updated.update(
        {
            "status": "queued",
            "queued_at": now,
            "queued_at_display": _now_text(now),
            "target_runs": _target_runs(target_runs),
            "completed_runs": len(normalized_rounds),
            "rounds": normalized_rounds,
        }
    )
    return updated


def build_tianji_trial_batch_run(
    result: object,
    *,
    rounds: object,
    target_runs: int,
    captures: Optional[list] = None,
    pending_next: bool = False,
) -> dict:
    run = build_tianji_trial_run(result, captures=captures)
    normalized_rounds = _normalize_tianji_trial_rounds(rounds)
    completed = len(normalized_rounds)
    target = _target_runs(target_runs)
    total_reward = sum(_miniapp_int(round_item.get("reward_trace")) for round_item in normalized_rounds)
    total_duration = sum(_miniapp_int(round_item.get("duration_ms")) for round_item in normalized_rounds)
    latest = normalized_rounds[-1] if normalized_rounds else {}
    all_ok = bool(normalized_rounds) and all(bool(round_item.get("ok")) for round_item in normalized_rounds)
    if pending_next:
        run["status"] = "queued"
        run["status_label"] = f"已完成{completed}/{target}，等待下一关入口"
        run["ok"] = False
    elif all_ok and completed >= target:
        run["status"] = "settled"
        run["status_label"] = f"已完成{completed}/{target}"
        run["ok"] = True
    elif not run.get("ok"):
        run["status_label"] = f"第{completed}关失败" if completed else "失败"
    else:
        run["status_label"] = f"已完成{completed}/{target}"
    run["rounds"] = normalized_rounds
    run["completed_runs"] = completed
    run["target_runs"] = target
    run["progress_text"] = f"{completed}/{target}"
    run["reward_trace"] = total_reward
    run["duration_ms"] = total_duration
    if latest:
        run["trial_title"] = latest.get("trial_title") or run.get("trial_title") or "-"
        run["grade"] = latest.get("grade") or run.get("grade") or "-"
        run["score"] = latest.get("score") or run.get("score") or 0
    return run


def build_tianji_trial_run(result: object, *, captures: Optional[list] = None, error: object = "") -> dict:
    from .biz_tianji_trial_miniapp import (
    TIANJI_TRIAL_DEFAULT_BATCH_RUNS,
        _safe_text,
        sanitize_tianji_trial_secret_text,
    )

    data = result if isinstance(result, dict) else {}
    settlement, _challenge, _trial = _result_settlement_data(data)
    details = settlement.get("details") if isinstance(settlement.get("details"), dict) else {}
    ok = bool(data.get("ok"))
    status = str(data.get("status") or ("settled" if ok else "failed")).strip() or "unknown"
    run = {
        "status": status,
        "status_label": "已完成" if ok else "失败",
        "ok": ok,
        "error": sanitize_tianji_trial_secret_text(error or data.get("error") or ""),
        "mode": str((data.get("proof") or {}).get("mode") or settlement.get("trial_type") or ""),
        "trial_title": _safe_text(settlement.get("trial_title") or "", 80),
        "difficulty": _safe_text(details.get("difficulty_label") or details.get("difficulty") or "", 40),
        "grade": _safe_text(settlement.get("grade") or "", 20),
        "score": int(settlement.get("score") or 0),
        "reward_trace": int(settlement.get("reward_trace") or 0),
        "duration_ms": int(settlement.get("duration_ms") or (data.get("proof") or {}).get("durationMs") or 0),
        "rounds": _normalize_tianji_trial_rounds(data.get("rounds")),
        "completed_runs": _miniapp_int(data.get("completed_runs")),
        "target_runs": _miniapp_int(data.get("target_runs"), TIANJI_TRIAL_DEFAULT_BATCH_RUNS),
        "progress_text": _safe_text(data.get("progress_text") or "", 40),
        "updated_at": _now_text(),
        "capture_report": format_tianji_trial_capture_report(captures or []),
    }
    return run


def default_tianji_trial_run() -> dict:
    from .biz_tianji_trial_miniapp import TIANJI_TRIAL_DEFAULT_BATCH_RUNS
    return {
        "status": "idle",
        "status_label": "未启动",
        "ok": False,
        "error": "",
        "mode": "",
        "trial_title": "-",
        "difficulty": "-",
        "grade": "-",
        "score": 0,
        "reward_trace": 0,
        "duration_ms": 0,
        "rounds": [],
        "completed_runs": 0,
        "target_runs": TIANJI_TRIAL_DEFAULT_BATCH_RUNS,
        "progress_text": "",
        "updated_at": "",
        "capture_report": "",
    }


def build_tianji_trial_run_view(value: object) -> dict:
    from .biz_tianji_trial_miniapp import (
    TIANJI_TRIAL_DEFAULT_BATCH_RUNS,
        _safe_text,
        sanitize_tianji_trial_secret_text,
    )

    base = default_tianji_trial_run()
    if not isinstance(value, dict) or not value:
        return base
    base.update(
        {
            "status": _safe_text(value.get("status") or "unknown", 40),
            "status_label": _safe_text(value.get("status_label") or value.get("status") or "unknown", 40),
            "ok": bool(value.get("ok")),
            "error": sanitize_tianji_trial_secret_text(value.get("error") or ""),
            "mode": _safe_text(value.get("mode") or "", 50),
            "trial_title": _safe_text(value.get("trial_title") or "-", 80),
            "difficulty": _safe_text(value.get("difficulty") or "-", 40),
            "grade": _safe_text(value.get("grade") or "-", 20),
            "score": int(value.get("score") or 0),
            "reward_trace": int(value.get("reward_trace") or 0),
            "duration_ms": int(value.get("duration_ms") or 0),
            "rounds": _normalize_tianji_trial_rounds(value.get("rounds")),
            "completed_runs": _miniapp_int(value.get("completed_runs")),
            "target_runs": _miniapp_int(value.get("target_runs"), TIANJI_TRIAL_DEFAULT_BATCH_RUNS),
            "progress_text": _safe_text(value.get("progress_text") or "", 40),
            "updated_at": _safe_text(value.get("updated_at") or "", 40),
            "capture_report": sanitize_tianji_trial_secret_text(value.get("capture_report") or "", limit=1200),
        }
    )
    return base


def merge_tianji_trial_payload(
    payload: object,
    *,
    entry: Optional[dict] = None,
    run: Optional[dict] = None,
    request: Optional[dict] = None,
    clear_request: bool = False,
) -> dict:
    from .biz_tianji_trial_miniapp import build_tianji_trial_entry_view
    updated = deepcopy(payload) if isinstance(payload, dict) else {}
    trial = dict(updated.get("tianji_trial") or {})
    if entry:
        trial["miniapp_entry"] = build_tianji_trial_entry_view(entry)
    if run:
        trial["miniapp_run"] = build_tianji_trial_run_view(run)
    if request is not None:
        trial["miniapp_request"] = deepcopy(request)
    if clear_request:
        trial.pop("miniapp_request", None)
    updated["tianji_trial"] = trial
    return updated


def build_tianji_trial_view(payload: object) -> dict:
    from .biz_tianji_trial_miniapp import TIANJI_TRIAL_SAFETY_BOUNDARY, build_tianji_trial_entry_view
    data = payload if isinstance(payload, dict) else {}
    trial = data.get("tianji_trial") if isinstance(data.get("tianji_trial"), dict) else {}
    request = trial.get("miniapp_request") if isinstance(trial.get("miniapp_request"), dict) else {}
    request_pending = str(request.get("status") or "") in {"queued", "running"}
    request_stale = request_pending and _is_stale_tianji_trial_request(request)
    pending = request_pending and not request_stale
    run_source = {} if request_stale else trial.get("miniapp_run")
    return {
        "entry": build_tianji_trial_entry_view(trial.get("miniapp_entry")),
        "run": build_tianji_trial_run_view(run_source),
        "request": {} if request_stale else request,
        "pending": pending,
        "safety_boundary": TIANJI_TRIAL_SAFETY_BOUNDARY,
    }


def format_tianji_trial_capture_report(captures: list[dict], *, note: str = "") -> str:
    from .biz_tianji_trial_miniapp import sanitize_tianji_trial_secret_text
    lines = ["【MiniApp天机试炼报告】"]
    clean_note = str(note or "").strip()
    if clean_note:
        lines.append(clean_note[:500])
    if not captures:
        lines.append("HTTP：未发起或未捕获")
        return "\n".join(lines)
    for item in captures[:8]:
        if not isinstance(item, dict):
            continue
        request = item.get("request") if isinstance(item.get("request"), dict) else {}
        response = item.get("response") if isinstance(item.get("response"), dict) else {}
        endpoint = str(request.get("endpoint") or "-").strip() or "-"
        step = str(item.get("step") or endpoint).strip() or endpoint
        status_code = _miniapp_int(response.get("status_code"))
        ok_text = "OK" if response.get("ok") else "FAIL"
        payload_keys = request.get("payload_keys")
        payload_text = ",".join(str(key) for key in payload_keys) if isinstance(payload_keys, list) else "-"
        try:
            shape_text = json.dumps(response.get("data_shape") or {}, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            shape_text = "{}"
        line = (
            f"{step} {endpoint} HTTP {status_code} {ok_text} "
            f"payload={payload_text} shape={shape_text}"
        )
        error_text = str(response.get("error") or "").strip()
        if error_text:
            line = f"{line} error={sanitize_tianji_trial_secret_text(error_text, limit=120)}"
        lines.append(line[:500])
    return "\n".join(lines)
