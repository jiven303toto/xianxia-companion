import asyncio
import hashlib
import json
import re
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib import error as urllib_error
from urllib.parse import parse_qsl, urljoin, urlsplit
import urllib.request

from tg_game.features.estate import biz_estate_miniapp as estate_miniapp

from .biz_luoyun_fly_solver import FLY_TARGET_SCORE, build_fly_proof
from .biz_luoyun_jump_solver import JUMP_TARGET_SCORE, build_jump_proof
from .biz_luoyun_spirit_tree_daily_auto import DEFAULT_RUN_TIME


LUOYUN_SPIRIT_TREE_MINIAPP_DEFAULT_API_BASE_URL = "https://asc.aiopenai.app"
LUOYUN_SPIRIT_TREE_MINIAPP_WEB_PATH = "/miniapp/xianxia-spirit-tree"
LUOYUN_SPIRIT_TREE_MINIAPP_API_PATH_PREFIX = "/api/miniapp/xianxia-spirit-tree/"
LUOYUN_SPIRIT_TREE_MINIAPP_ENDPOINTS = {
    "start": f"{LUOYUN_SPIRIT_TREE_MINIAPP_API_PATH_PREFIX}start",
    "run_start": f"{LUOYUN_SPIRIT_TREE_MINIAPP_API_PATH_PREFIX}run/start",
    "run_submit": f"{LUOYUN_SPIRIT_TREE_MINIAPP_API_PATH_PREFIX}run/submit",
}
LUOYUN_SPIRIT_TREE_ALLOWED_API_HOSTS = {"asc.aiopenai.app"}
LUOYUN_SPIRIT_TREE_REQUEST_TTL_SECONDS = 30 * 60
LUOYUN_SPIRIT_TREE_PENDING_RETRY_SECONDS = 60
LUOYUN_SPIRIT_TREE_RETRY_DELAYS_SECONDS = (60, 120, 300, 600)
LUOYUN_SPIRIT_TREE_HISTORY_LIMIT = 14
LUOYUN_SPIRIT_TREE_TZ = timezone(timedelta(hours=8))
LUOYUN_SPIRIT_TREE_MODE_ORDER = ("fly", "jump")
LUOYUN_SPIRIT_TREE_TARGETS = {
    "jump": JUMP_TARGET_SCORE,
    "fly": FLY_TARGET_SCORE,
}
LUOYUN_SPIRIT_TREE_FLY_PROOF_TARGETS = (30, 45)
LUOYUN_SPIRIT_TREE_JUMP_PROOF_TARGETS = (120, 126, 132, 138)
LUOYUN_SPIRIT_TREE_SAFETY_BOUNDARY = (
    "只通过公共洞府入口获取云梦山灵眼赛链接，临时请求 Telegram WebView，"
    "随后只调用 xianxia-dwelling/start、xianxia-spirit-tree/start、"
    "run/start 与 run/submit；不发送群命令，不保存 initData、token 或原始 URL。"
)

_TREE_TOKEN_PATTERN = re.compile(r"^tree_[A-Za-z0-9_-]{4,160}$", re.IGNORECASE)
_TREE_TOKEN_TEXT_PATTERN = re.compile(r"\btree_[A-Za-z0-9_-]{4,}\b", re.IGNORECASE)
_START_PARAM_KEYS = {
    "startapp",
    "start_param",
    "startattach",
    "start",
    "tgwebappstartparam",
}


def _safe_text(value: object, limit: int = 220) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _safe_digest(value: object) -> str:
    text = str(value or "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12] if text else ""


def sanitize_luoyun_spirit_tree_secret_text(text: object, *, limit: int = 220) -> str:
    raw = str(text or "")
    raw = re.sub(
        r"(?P<key>tgWebAppData|initData|query_id|hash|user|signature|token|startapp|start_param)=([^&#\s]+)",
        lambda match: f"{match.group('key')}=<redacted>",
        raw,
        flags=re.IGNORECASE,
    )
    raw = _TREE_TOKEN_TEXT_PATTERN.sub("tree_<redacted>", raw)
    return _safe_text(raw, limit)


def _host_from_url(url: str) -> str:
    try:
        return (urlsplit(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


def _start_param_from_url(url: str) -> str:
    try:
        parsed = urlsplit(str(url or ""))
    except ValueError:
        return ""
    pairs = [
        *parse_qsl(parsed.query, keep_blank_values=True),
        *parse_qsl(parsed.fragment, keep_blank_values=True),
    ]
    for key, value in pairs:
        if str(key or "").strip().lower() in _START_PARAM_KEYS:
            return str(value or "").strip()
    return ""


def extract_public_luoyun_spirit_tree_launch(data: object) -> dict:
    root = data if isinstance(data, dict) else {}
    if isinstance(root.get("data"), dict):
        root = root["data"]
    account = root.get("account") if isinstance(root.get("account"), dict) else {}
    external_apps = (
        account.get("externalApps")
        if isinstance(account.get("externalApps"), dict)
        else {}
    )
    groups = external_apps.get("groups") if isinstance(external_apps.get("groups"), list) else []
    for group in groups:
        apps = (
            group.get("apps")
            if isinstance(group, dict) and isinstance(group.get("apps"), list)
            else []
        )
        for app in apps:
            if not isinstance(app, dict) or not bool(app.get("available", True)):
                continue
            url = urljoin(
                f"{LUOYUN_SPIRIT_TREE_MINIAPP_DEFAULT_API_BASE_URL}/",
                str(app.get("url") or "").strip(),
            )
            try:
                parsed = urlsplit(url)
            except ValueError:
                continue
            if parsed.path != LUOYUN_SPIRIT_TREE_MINIAPP_WEB_PATH:
                continue
            token = _start_param_from_url(url)
            if not _TREE_TOKEN_PATTERN.match(token):
                continue
            return {
                "token": token,
                "webview_url": url,
                "entry": {
                    "status": "captured",
                    "button_text": _safe_text(
                        app.get("buttonText") or app.get("title") or "云梦山灵眼赛",
                        48,
                    ),
                    "host": (parsed.hostname or "").lower(),
                    "path": parsed.path,
                    "token_suffix": token[-4:],
                    "token_digest": _safe_digest(token),
                },
            }
    return {}


def _build_api_url(
    endpoint: str,
    api_base_url: str = LUOYUN_SPIRIT_TREE_MINIAPP_DEFAULT_API_BASE_URL,
) -> str:
    endpoint_path = LUOYUN_SPIRIT_TREE_MINIAPP_ENDPOINTS.get(str(endpoint or "").strip(), "")
    if not endpoint_path:
        raise ValueError(f"unknown luoyun spirit tree endpoint: {endpoint}")
    base = urlsplit(str(api_base_url or "").strip())
    origin = f"{base.scheme}://{base.netloc}" if base.scheme and base.netloc else ""
    if not origin:
        raise ValueError("luoyun spirit tree api base url missing")
    url = urljoin(f"{origin}/", endpoint_path.lstrip("/"))
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host not in LUOYUN_SPIRIT_TREE_ALLOWED_API_HOSTS:
        raise ValueError(f"luoyun spirit tree api host not allowed: {host}")
    if not parsed.path.startswith(LUOYUN_SPIRIT_TREE_MINIAPP_API_PATH_PREFIX):
        raise ValueError(f"luoyun spirit tree api path not allowed: {parsed.path}")
    return url


def build_luoyun_spirit_tree_miniapp_request(
    endpoint: str,
    *,
    token: str,
    init_data: str,
    payload: Optional[dict] = None,
    api_base_url: str = LUOYUN_SPIRIT_TREE_MINIAPP_DEFAULT_API_BASE_URL,
) -> dict:
    clean_token = str(token or "").strip()
    if not _TREE_TOKEN_PATTERN.match(clean_token):
        raise ValueError("luoyun spirit tree token not allowed")
    request_payload = {"token": clean_token, "initData": str(init_data or "")}
    request_payload.update(dict(payload or {}))
    url = _build_api_url(endpoint, api_base_url=api_base_url)
    return {
        "method": "POST",
        "url": url,
        "payload": request_payload,
        "safe_summary": {
            "endpoint": str(endpoint or "").strip(),
            "url_host": _host_from_url(url),
            "payload_keys": sorted(request_payload),
            "token_suffix": clean_token[-4:],
            "token_digest": _safe_digest(clean_token),
            "init_data_digest": _safe_digest(init_data),
            "has_init_data": bool(init_data),
        },
    }


def _urllib_transport(request: dict):
    body = json.dumps(request.get("payload") or {}, ensure_ascii=False).encode("utf-8")
    http_request = urllib.request.Request(
        request["url"],
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        method=str(request.get("method") or "POST"),
    )
    try:
        with urllib.request.urlopen(http_request, timeout=25) as response:
            return int(getattr(response, "status", 200) or 200), response.read()
    except urllib_error.HTTPError as exc:
        return int(exc.code or 0), exc.read()


def _coerce_response(raw_response) -> tuple[int, object]:
    if isinstance(raw_response, tuple) and len(raw_response) == 2:
        status, body = raw_response
    else:
        status = int(getattr(raw_response, "status", 200) or 200)
        body = raw_response.read() if hasattr(raw_response, "read") else raw_response
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = {"text": body}
    return int(status or 0), body


def execute_luoyun_spirit_tree_miniapp_request(request: dict, transport) -> dict:
    if transport is None:
        raise ValueError("luoyun spirit tree transport missing")
    try:
        status_code, body = _coerce_response(transport(request))
    except Exception as exc:
        return {
            "ok": False,
            "status_code": 0,
            "data": {},
            "error": sanitize_luoyun_spirit_tree_secret_text(exc),
        }
    body = body if isinstance(body, dict) else {"value": body}
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    if 200 <= status_code < 300 and body.get("ok") is not False:
        return {"ok": True, "status_code": status_code, "data": data, "error": ""}
    return {
        "ok": False,
        "status_code": status_code,
        "data": data if isinstance(data, dict) else {},
        "error": sanitize_luoyun_spirit_tree_secret_text(
            body.get("error") or body.get("message") or f"http_{status_code}"
        ),
    }


def _int_or_zero(value: object) -> int:
    try:
        return max(int(float(value or 0)), 0)
    except (TypeError, ValueError):
        return 0


def _signed_int_or_zero(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _mode_state(daily: object, mode: str) -> dict:
    value = daily.get(mode) if isinstance(daily, dict) and isinstance(daily.get(mode), dict) else {}
    limit = _int_or_zero(value.get("limit"))
    return {
        "best": _int_or_zero(value.get("best")),
        "used": _int_or_zero(value.get("used")),
        "limit": limit if limit > 0 else 3,
    }


def _ranking_view(value: object) -> dict:
    ranking = value if isinstance(value, dict) else {}
    rows = ranking.get("branchTop") if isinstance(ranking.get("branchTop"), list) else ranking.get("rows")
    safe_rows = []
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, dict):
            continue
        safe_rows.append(
            {
                "rank": _int_or_zero(item.get("rank")),
                "username": _safe_text(item.get("username") or "-", 48),
                "points": _int_or_zero(item.get("points")),
                "jump": _int_or_zero(item.get("jump")),
                "fly": _int_or_zero(item.get("fly")),
                "self": bool(item.get("self")),
            }
        )
        if len(safe_rows) >= 10:
            break
    self_row = ranking.get("self") if isinstance(ranking.get("self"), dict) else {}
    return {
        "top": safe_rows,
        "self": {
            "rank": _int_or_zero(self_row.get("rank")),
            "username": _safe_text(self_row.get("username") or "", 48),
            "points": _int_or_zero(self_row.get("points")),
            "jump": _int_or_zero(self_row.get("jump")),
            "fly": _int_or_zero(self_row.get("fly")),
        },
        "self_excluded": bool(
            ranking.get("selfExcluded") or ranking.get("branchRankSelfExcluded")
        ),
    }


def _season_view(value: object) -> dict:
    season = value if isinstance(value, dict) else {}
    return {
        "season_id": _safe_text(season.get("seasonId") or season.get("season_id") or "", 48),
        "start_date": _safe_text(season.get("startDate") or "", 16),
        "end_date": _safe_text(season.get("endDate") or "", 16),
        "today": _safe_text(season.get("today") or "", 16),
        "day_index": _int_or_zero(season.get("dayIndex")),
        "status": _safe_text(season.get("status") or "", 24),
    }


def _snapshot_from_data(data: object, previous: Optional[dict] = None) -> dict:
    root = data if isinstance(data, dict) else {}
    season_state = root.get("seasonState") if isinstance(root.get("seasonState"), dict) else {}
    council = root.get("council") if isinstance(root.get("council"), dict) else {}
    daily = season_state.get("daily") if isinstance(season_state.get("daily"), dict) else council.get("daily")
    ranking = season_state.get("ranking") if isinstance(season_state.get("ranking"), dict) else root.get("ranking")
    season = season_state.get("season") if isinstance(season_state.get("season"), dict) else council.get("season")
    old = previous if isinstance(previous, dict) else {}
    normalized_daily = {
        "jump": _mode_state(daily, "jump"),
        "fly": _mode_state(daily, "fly"),
    }
    day_key = _safe_text(
        (season or {}).get("today") if isinstance(season, dict) else "",
        16,
    ) or _safe_text(old.get("day_key") or "", 16)
    normalized_daily["day_key"] = day_key
    return {
        "daily": normalized_daily,
        "season": _season_view(season) if isinstance(season, dict) else dict(old.get("season") or {}),
        "ranking": _ranking_view(ranking) if isinstance(ranking, dict) else dict(old.get("ranking") or {}),
    }


def _targets_reached(snapshot: dict) -> bool:
    daily = snapshot.get("daily") if isinstance(snapshot.get("daily"), dict) else {}
    return all(
        _mode_state(daily, mode)["best"] >= LUOYUN_SPIRIT_TREE_TARGETS[mode]
        for mode in LUOYUN_SPIRIT_TREE_MODE_ORDER
    )


def _proof_for_mode(mode: str, seed: object, *, attempt_number: int = 1) -> dict:
    normalized_attempt = max(1, int(attempt_number or 1))
    target_roll = int.from_bytes(
        hashlib.sha256(f"{mode}:{seed}".encode("utf-8")).digest()[:2],
        "big",
    )
    if mode == "fly":
        minimum, maximum = LUOYUN_SPIRIT_TREE_FLY_PROOF_TARGETS
        target_score = (
            FLY_TARGET_SCORE
            if normalized_attempt == 1
            else minimum + target_roll % (maximum - minimum + 1)
        )
        return build_fly_proof(seed, target_score=target_score)
    if mode == "jump":
        target_score = (
            JUMP_TARGET_SCORE
            if normalized_attempt == 1
            else LUOYUN_SPIRIT_TREE_JUMP_PROOF_TARGETS[
                target_roll % len(LUOYUN_SPIRIT_TREE_JUMP_PROOF_TARGETS)
            ]
        )
        return build_jump_proof(seed, target_score=target_score)
    raise ValueError(f"unknown luoyun spirit tree mode: {mode}")


def _submit_with_same_run_retry(request: dict, transport) -> dict:
    result = execute_luoyun_spirit_tree_miniapp_request(request, transport)
    if result.get("ok"):
        return result
    status_code = int(result.get("status_code") or 0)
    if status_code == 0 or status_code >= 500:
        return execute_luoyun_spirit_tree_miniapp_request(request, transport)
    return result


def resolve_luoyun_spirit_tree_retry_delay(retry_count: object) -> int:
    count = max(_int_or_zero(retry_count), 1)
    index = min(count - 1, len(LUOYUN_SPIRIT_TREE_RETRY_DELAYS_SECONDS) - 1)
    return LUOYUN_SPIRIT_TREE_RETRY_DELAYS_SECONDS[index]


def _flow_result(
    ok: bool,
    status: str,
    *,
    run_mode: str,
    snapshot: Optional[dict] = None,
    entry: Optional[dict] = None,
    events: Optional[list] = None,
    accepted_modes: Optional[list] = None,
    error: object = "",
    failure_kind: str = "",
    pending_submission: Optional[dict] = None,
) -> dict:
    state = snapshot if isinstance(snapshot, dict) else {"daily": {}, "season": {}, "ranking": {}}
    daily = state.get("daily") if isinstance(state.get("daily"), dict) else {}
    jump_best = _mode_state(daily, "jump")["best"]
    fly_best = _mode_state(daily, "fly")["best"]
    safe_error = sanitize_luoyun_spirit_tree_secret_text(error)
    message = (
        f"跃 {jump_best}/{JUMP_TARGET_SCORE}，飞 {fly_best}/{FLY_TARGET_SCORE}，今日双赛已达目标。"
        if ok and _targets_reached(state)
        else safe_error or f"跃 {jump_best}/{JUMP_TARGET_SCORE}，飞 {fly_best}/{FLY_TARGET_SCORE}。"
    )
    return {
        "ok": bool(ok),
        "status": status,
        "run_mode": "canary" if run_mode == "canary" else "daily",
        "message": message,
        "error": safe_error,
        "failure_kind": _safe_text(failure_kind, 40),
        "daily": daily,
        "season": state.get("season") if isinstance(state.get("season"), dict) else {},
        "ranking": state.get("ranking") if isinstance(state.get("ranking"), dict) else {},
        "entry": entry if isinstance(entry, dict) else {},
        "events": list(events or [])[-12:],
        "accepted_modes": list(accepted_modes or []),
        "pending_submission": pending_submission if isinstance(pending_submission, dict) else {},
        "updated_at": time.time(),
        "safety_boundary": LUOYUN_SPIRIT_TREE_SAFETY_BOUNDARY,
    }


def run_luoyun_spirit_tree_flow(
    *,
    estate_token: str,
    init_data: str,
    transport,
    run_mode: str = "daily",
    pending_submission: Optional[dict] = None,
) -> dict:
    mode = "canary" if str(run_mode or "").strip() == "canary" else "daily"
    max_attempts_per_mode = 1 if mode == "canary" else 3
    recovery = pending_submission if isinstance(pending_submission, dict) else {}
    dwelling_request = estate_miniapp.build_estate_miniapp_request(
        "start",
        token=estate_token,
        init_data=init_data,
    )
    dwelling_result = estate_miniapp.execute_estate_miniapp_request(
        dwelling_request,
        transport,
    )
    if not dwelling_result.get("ok"):
        return _flow_result(
            False,
            "retry_pending",
            run_mode=mode,
            error=dwelling_result.get("error") or "公共洞府入口启动失败。",
            failure_kind="dwelling_start_failed",
            pending_submission=recovery,
        )
    launch = extract_public_luoyun_spirit_tree_launch(dwelling_result.get("data") or {})
    if not launch:
        return _flow_result(
            False,
            "retry_pending",
            run_mode=mode,
            error="公共洞府外府未返回云梦山灵眼赛链接。",
            failure_kind="entry_missing",
            pending_submission=recovery,
        )
    token = str(launch.get("token") or "")
    tree_start_request = build_luoyun_spirit_tree_miniapp_request(
        "start",
        token=token,
        init_data=init_data,
    )
    tree_start_result = execute_luoyun_spirit_tree_miniapp_request(
        tree_start_request,
        transport,
    )
    if not tree_start_result.get("ok"):
        return _flow_result(
            False,
            "retry_pending",
            run_mode=mode,
            entry=launch.get("entry"),
            error=tree_start_result.get("error") or "云梦山灵眼赛启动失败。",
            failure_kind="tree_start_failed",
            pending_submission=recovery,
        )
    start_data = tree_start_result.get("data") or {}
    account = start_data.get("account") if isinstance(start_data.get("account"), dict) else {}
    account_id = account.get("accountId") or account.get("playerId")
    if account_id in (None, ""):
        return _flow_result(
            False,
            "retry_pending",
            run_mode=mode,
            entry=launch.get("entry"),
            error="云梦山灵眼赛未返回参赛账号。",
            failure_kind="account_missing",
            pending_submission=recovery,
        )
    snapshot = _snapshot_from_data(start_data)
    events: list[dict] = []
    accepted_modes: list[str] = [
        str(item)
        for item in (recovery.get("accepted_modes") or [])
        if item in LUOYUN_SPIRIT_TREE_MODE_ORDER
    ]
    if recovery.get("runToken") and recovery.get("mode") in LUOYUN_SPIRIT_TREE_MODE_ORDER:
        submit_request = build_luoyun_spirit_tree_miniapp_request(
            "run_submit",
            token=token,
            init_data=init_data,
            payload={
                "mode": recovery["mode"],
                "runToken": recovery["runToken"],
                "proof": recovery.get("proof") if isinstance(recovery.get("proof"), dict) else {},
                "accountId": account_id,
            },
        )
        submit_result = _submit_with_same_run_retry(submit_request, transport)
        if not submit_result.get("ok"):
            status_code = int(submit_result.get("status_code") or 0)
            return _flow_result(
                False,
                "retry_pending" if status_code == 0 or status_code >= 500 else "failed",
                run_mode=mode,
                snapshot=snapshot,
                entry=launch.get("entry"),
                error=submit_result.get("error") or "断线局重提失败。",
                failure_kind=(
                    "submit_network_error"
                    if status_code == 0 or status_code >= 500
                    else "proof_rejected"
                ),
                pending_submission=(recovery if status_code == 0 or status_code >= 500 else {}),
            )
        submit_data = submit_result.get("data") or {}
        snapshot = _snapshot_from_data(submit_data, snapshot)
        accepted_modes.append(str(recovery["mode"]))
        events.append(
            {
                "mode": str(recovery["mode"]),
                "status": "recovered",
                "score": _int_or_zero(submit_data.get("score")),
            }
        )
        recovery = {}

    for game_mode in LUOYUN_SPIRIT_TREE_MODE_ORDER:
        current = _mode_state(snapshot.get("daily") or {}, game_mode)
        if mode == "canary" and game_mode in accepted_modes:
            events.append({"mode": game_mode, "status": "already_accepted", "score": current["best"]})
            continue
        automatic_attempt_limit = max(current["limit"], 0)
        available_attempts = min(
            max_attempts_per_mode,
            max(automatic_attempt_limit - current["used"], 0),
        )
        if available_attempts <= 0:
            events.append(
                {
                    "mode": game_mode,
                    "status": "daily_limit_reached",
                    "score": current["best"],
                }
            )
            continue
        for _attempt in range(available_attempts):
            attempt_number = current["used"] + 1
            run_start_request = build_luoyun_spirit_tree_miniapp_request(
                "run_start",
                token=token,
                init_data=init_data,
                payload={"mode": game_mode, "accountId": account_id},
            )
            run_start_result = execute_luoyun_spirit_tree_miniapp_request(
                run_start_request,
                transport,
            )
            if not run_start_result.get("ok"):
                return _flow_result(
                    False,
                    "retry_pending",
                    run_mode=mode,
                    snapshot=snapshot,
                    entry=launch.get("entry"),
                    events=events,
                    accepted_modes=accepted_modes,
                    error=run_start_result.get("error") or f"{game_mode} 开局失败。",
                    failure_kind="run_start_failed",
                )
            run_data = run_start_result.get("data") or {}
            run = run_data.get("run") if isinstance(run_data.get("run"), dict) else {}
            snapshot = _snapshot_from_data(run_data, snapshot)
            run_token = str(run.get("runToken") or "").strip()
            seed = run.get("seed")
            if not run_token or seed in (None, ""):
                return _flow_result(
                    False,
                    "retry_pending",
                    run_mode=mode,
                    snapshot=snapshot,
                    entry=launch.get("entry"),
                    events=events,
                    accepted_modes=accepted_modes,
                    error=f"{game_mode} 开局未返回 runToken 或 seed。",
                    failure_kind="run_contract_invalid",
                )
            try:
                proof = _proof_for_mode(
                    game_mode,
                    seed,
                    attempt_number=attempt_number,
                )
            except Exception as exc:
                return _flow_result(
                    False,
                    "failed",
                    run_mode=mode,
                    snapshot=snapshot,
                    entry=launch.get("entry"),
                    events=events,
                    accepted_modes=accepted_modes,
                    error=exc,
                    failure_kind="proof_generation_failed",
                )
            pending = {
                "mode": game_mode,
                "runToken": run_token,
                "proof": proof,
                "accepted_modes": list(accepted_modes),
                "created_at": time.time(),
            }
            submit_request = build_luoyun_spirit_tree_miniapp_request(
                "run_submit",
                token=token,
                init_data=init_data,
                payload={
                    "mode": game_mode,
                    "runToken": run_token,
                    "proof": proof,
                    "accountId": account_id,
                },
            )
            submit_result = _submit_with_same_run_retry(submit_request, transport)
            if not submit_result.get("ok"):
                status_code = int(submit_result.get("status_code") or 0)
                retryable = status_code == 0 or status_code >= 500
                return _flow_result(
                    False,
                    "retry_pending" if retryable else "failed",
                    run_mode=mode,
                    snapshot=snapshot,
                    entry=launch.get("entry"),
                    events=events,
                    accepted_modes=accepted_modes,
                    error=submit_result.get("error") or f"{game_mode} proof 提交失败。",
                    failure_kind="submit_network_error" if retryable else "proof_rejected",
                    pending_submission=pending if retryable else {},
                )
            submit_data = submit_result.get("data") or {}
            snapshot = _snapshot_from_data(submit_data, snapshot)
            score = _int_or_zero(submit_data.get("score"))
            accepted_modes.append(game_mode)
            events.append({"mode": game_mode, "status": "accepted", "score": score})
            current = _mode_state(snapshot.get("daily") or {}, game_mode)

    completed = _targets_reached(snapshot)
    return _flow_result(
        completed,
        "completed" if completed else "partial",
        run_mode=mode,
        snapshot=snapshot,
        entry=launch.get("entry"),
        events=events,
        accepted_modes=accepted_modes,
        error="" if completed else "本轮已停止，但今日分数尚未达到双赛目标。",
        failure_kind="" if completed else "target_not_reached",
    )


async def run_luoyun_spirit_tree_public_production_flow(
    client: object,
    *,
    discovery_storage: object,
    transport=None,
    run_mode: str = "daily",
    pending_submission: Optional[dict] = None,
) -> dict:
    try:
        discovery = await estate_miniapp.resolve_estate_public_miniapp_launch(
            client,
            discovery_storage,
        )
        if not discovery.get("ok"):
            raise RuntimeError(str(discovery.get("error") or "洞府公共入口未找到"))
        launch = discovery.get("launch") if isinstance(discovery.get("launch"), dict) else {}
        init_data = await estate_miniapp.request_estate_miniapp_init_data(
            client,
            token=launch.get("token"),
            webview_url=launch.get("webview_url"),
            bot_username=launch.get("bot_username"),
        )
        return await asyncio.to_thread(
            run_luoyun_spirit_tree_flow,
            estate_token=launch.get("token"),
            init_data=init_data,
            transport=transport or _urllib_transport,
            run_mode=run_mode,
            pending_submission=pending_submission,
        )
    except Exception as exc:
        return _flow_result(
            False,
            "retry_pending",
            run_mode=run_mode,
            error=exc,
            failure_kind="public_entry_failed",
            pending_submission=(
                pending_submission if isinstance(pending_submission, dict) else {}
            ),
        )


def build_luoyun_spirit_tree_request(
    *,
    chat_id: object = "",
    thread_id: object = None,
    chat_type: str = "group",
    bot_username: str = "fanrenxiuxian_bot",
    run_mode: str = "daily",
    not_before: float = 0,
    retry_count: int = 0,
    day_key: str = "",
) -> dict:
    now = time.time()
    normalized_mode = (
        "canary" if str(run_mode or "").strip() == "canary" else "daily"
    )
    return {
        "status": "queued",
        "requested_at": now,
        "not_before": float(not_before or 0),
        "retry_count": max(_int_or_zero(retry_count), 0),
        "day_key": _safe_text(day_key or _today_key(now), 16),
        "chat_id": _signed_int_or_zero(chat_id),
        "thread_id": _signed_int_or_zero(thread_id) if thread_id not in (None, "") else None,
        "chat_type": _safe_text(chat_type or "group", 20) or "group",
        "bot_username": _safe_text(bot_username or "fanrenxiuxian_bot", 64),
        "run_mode": normalized_mode,
    }


def queue_luoyun_spirit_tree_request(
    payload: object,
    **request_kwargs,
) -> dict:
    updated = deepcopy(payload if isinstance(payload, dict) else {})
    board = dict(updated.get("luoyun_spirit_tree") or {})
    request = build_luoyun_spirit_tree_request(**request_kwargs)
    pending = (
        board.get("pending_submission")
        if isinstance(board.get("pending_submission"), dict)
        else {}
    )
    pending_created_at = float(pending.get("created_at") or 0)
    if not pending_created_at or _today_key(pending_created_at) != request["day_key"]:
        board.pop("pending_submission", None)
    board["miniapp_request"] = request
    board["miniapp_run"] = {
        "status": "queued",
        "run_mode": request["run_mode"],
        "message": "云梦山灵眼赛已排队，等待公共洞府入口。",
        "updated_at": request["requested_at"],
        "error": "",
        "events": [],
        "safety_boundary": LUOYUN_SPIRIT_TREE_SAFETY_BOUNDARY,
    }
    updated["luoyun_spirit_tree"] = board
    return updated


def get_pending_luoyun_spirit_tree_request(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    board = payload.get("luoyun_spirit_tree") if isinstance(payload.get("luoyun_spirit_tree"), dict) else {}
    request = board.get("miniapp_request") if isinstance(board.get("miniapp_request"), dict) else {}
    if str(request.get("status") or "") not in {"queued", "running"}:
        return {}
    requested_at = float(request.get("requested_at") or 0)
    if requested_at and time.time() - requested_at > LUOYUN_SPIRIT_TREE_REQUEST_TTL_SECONDS:
        return {}
    if str(request.get("run_mode") or "daily") == "daily":
        request_day_key = _safe_text(
            request.get("day_key") or (_today_key(requested_at) if requested_at else ""),
            16,
        )
        if request_day_key and request_day_key != _today_key():
            return {}
    if float(request.get("not_before") or 0) > time.time():
        return {}
    return request


def get_pending_luoyun_spirit_tree_submission(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    board = payload.get("luoyun_spirit_tree") if isinstance(payload.get("luoyun_spirit_tree"), dict) else {}
    pending = board.get("pending_submission") if isinstance(board.get("pending_submission"), dict) else {}
    return pending if pending.get("runToken") and pending.get("mode") else {}


def build_luoyun_spirit_tree_run_view(value: object) -> dict:
    if not isinstance(value, dict) or not value:
        return {}
    return {
        "status": _safe_text(value.get("status") or "", 40),
        "run_mode": "canary" if value.get("run_mode") == "canary" else "daily",
        "message": sanitize_luoyun_spirit_tree_secret_text(
            value.get("message") or value.get("error") or ""
        ),
        "error": sanitize_luoyun_spirit_tree_secret_text(value.get("error") or ""),
        "failure_kind": _safe_text(value.get("failure_kind") or "", 40),
        "events": list(value.get("events") or [])[-12:],
        "accepted_modes": [
            str(item) for item in (value.get("accepted_modes") or []) if item in LUOYUN_SPIRIT_TREE_MODE_ORDER
        ],
        "updated_at": float(value.get("updated_at") or time.time()),
        "safety_boundary": LUOYUN_SPIRIT_TREE_SAFETY_BOUNDARY,
    }


def merge_luoyun_spirit_tree_payload(
    payload: object,
    result: object,
    *,
    request: Optional[dict] = None,
    clear_request: bool = True,
) -> dict:
    updated = deepcopy(payload if isinstance(payload, dict) else {})
    board = dict(updated.get("luoyun_spirit_tree") or {})
    run_result = result if isinstance(result, dict) else {}
    if isinstance(run_result.get("entry"), dict) and run_result.get("entry"):
        board["miniapp_entry"] = dict(run_result["entry"])
    for key in ("daily", "season", "ranking"):
        if isinstance(run_result.get(key), dict) and run_result.get(key):
            board[key] = dict(run_result[key])
    run_view = build_luoyun_spirit_tree_run_view(run_result)
    if run_view:
        board["miniapp_run"] = run_view
        history = [item for item in (board.get("history") or []) if isinstance(item, dict)]
        history.append(run_view)
        board["history"] = history[-LUOYUN_SPIRIT_TREE_HISTORY_LIMIT:]
    pending = run_result.get("pending_submission") if isinstance(run_result.get("pending_submission"), dict) else {}
    if pending:
        board["pending_submission"] = pending
    else:
        board.pop("pending_submission", None)
    if run_result.get("run_mode") == "canary":
        passed = bool(run_result.get("ok"))
        board["canary"] = {
            "passed": passed,
            "status": "passed" if passed else "failed",
            "message": (
                "跃、飞各一次真实 proof 已通过服务端验证。"
                if passed
                else sanitize_luoyun_spirit_tree_secret_text(
                    run_result.get("error") or "Canary 未通过。"
                )
            ),
            "updated_at": float(run_result.get("updated_at") or time.time()),
        }
    if request is not None:
        board["miniapp_request"] = dict(request)
    elif clear_request:
        board.pop("miniapp_request", None)
    updated["luoyun_spirit_tree"] = board
    return updated


def cancel_luoyun_spirit_tree_request(payload: object, *, reason: str) -> dict:
    result = _flow_result(
        False,
        "cancelled",
        run_mode="daily",
        error=reason,
        failure_kind="cancelled",
    )
    return merge_luoyun_spirit_tree_payload(payload, result, clear_request=True)


def _today_key(now: Optional[float] = None) -> str:
    return datetime.fromtimestamp(
        float(time.time() if now is None else now),
        tz=LUOYUN_SPIRIT_TREE_TZ,
    ).strftime("%Y-%m-%d")


def is_luoyun_spirit_tree_daily_target_reached(
    payload: object,
    *,
    now: Optional[float] = None,
) -> bool:
    if not isinstance(payload, dict):
        return False
    board = payload.get("luoyun_spirit_tree") if isinstance(payload.get("luoyun_spirit_tree"), dict) else {}
    daily = board.get("daily") if isinstance(board.get("daily"), dict) else {}
    if str(daily.get("day_key") or "") != _today_key(now):
        return False
    mode_states = [_mode_state(daily, mode) for mode in LUOYUN_SPIRIT_TREE_MODE_ORDER]
    return all(
        state["limit"] > 0 and state["used"] >= state["limit"]
        for state in mode_states
    )


def build_luoyun_spirit_tree_view(payload: object, task: Optional[dict]) -> dict:
    root = payload if isinstance(payload, dict) else {}
    board = root.get("luoyun_spirit_tree") if isinstance(root.get("luoyun_spirit_tree"), dict) else {}
    daily = board.get("daily") if isinstance(board.get("daily"), dict) else {}
    canary = board.get("canary") if isinstance(board.get("canary"), dict) else {}
    run = build_luoyun_spirit_tree_run_view(board.get("miniapp_run"))
    ranking = board.get("ranking") if isinstance(board.get("ranking"), dict) else {}
    self_row = ranking.get("self") if isinstance(ranking.get("self"), dict) else {}
    top = ranking.get("top") if isinstance(ranking.get("top"), list) else []
    return {
        "available": True,
        "daily": {
            "day_key": _safe_text(daily.get("day_key") or "", 16),
            "jump": _mode_state(daily, "jump"),
            "fly": _mode_state(daily, "fly"),
        },
        "season": board.get("season") if isinstance(board.get("season"), dict) else {},
        "ranking": {
            "self": self_row,
            "top": top,
            "self_excluded": bool(ranking.get("self_excluded")),
        },
        "run": run,
        "canary": {
            "passed": bool(canary.get("passed")),
            "status": _safe_text(canary.get("status") or "not_run", 20),
            "message": sanitize_luoyun_spirit_tree_secret_text(
                canary.get("message") or "尚未执行真实 Canary。"
            ),
            "updated_at": float(canary.get("updated_at") or 0),
        },
        "auto": {
            "enabled": bool((task or {}).get("enabled")),
            "run_time": _safe_text((task or {}).get("strategy") or DEFAULT_RUN_TIME, 8),
            "next_run_at": float((task or {}).get("next_run_at") or 0),
            "last_run_at": float((task or {}).get("last_run_at") or 0),
            "last_error": sanitize_luoyun_spirit_tree_secret_text(
                (task or {}).get("last_error") or ""
            ),
        },
        "pending": bool(get_pending_luoyun_spirit_tree_request(root)),
        "history": [
            build_luoyun_spirit_tree_run_view(item)
            for item in (board.get("history") or [])[-5:]
            if isinstance(item, dict)
        ],
        "safety_boundary": LUOYUN_SPIRIT_TREE_SAFETY_BOUNDARY,
    }
