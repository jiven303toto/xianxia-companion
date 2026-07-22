import asyncio
import hashlib
import json
import re
import time
from typing import Optional
from urllib.parse import parse_qs, urljoin, urlsplit
import urllib.request

from tg_game.features.estate import biz_estate_miniapp as estate_miniapp
from tg_game.features.estate.biz_estate_constants import (
    ESTATE_MINIAPP_ALLOWED_API_HOSTS,
    ESTATE_MINIAPP_DEFAULT_API_BASE_URL,
)

from . import biz_beast_merge_solver as solver


BEAST_MERGE_WEB_PATH = "/miniapp/xianxia-beast-merge"
BEAST_MERGE_API_PREFIX = "/api/miniapp/xianxia-beast-merge/"
BEAST_MERGE_ENDPOINTS = {
    "start": f"{BEAST_MERGE_API_PREFIX}start",
    "run_start": f"{BEAST_MERGE_API_PREFIX}run/start",
    "move": f"{BEAST_MERGE_API_PREFIX}move",
    "submit": f"{BEAST_MERGE_API_PREFIX}submit",
}
BEAST_MERGE_TOKEN_PATTERN = re.compile(
    r"^beastmerge[_-][A-Za-z0-9_-]{4,160}$",
    re.IGNORECASE,
)
BEAST_MERGE_TOKEN_SEARCH = re.compile(
    r"beastmerge[_-][A-Za-z0-9_-]{4,160}",
    re.IGNORECASE,
)
BEAST_MERGE_KEYWORDS = ("噬金虫", "金虫", "虫巢", "beast", "merge")
DEFAULT_MOVE_INTERVAL_SECONDS = 1.0


def _int(value: object, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return default


def _safe_text(value: object, limit: int = 180) -> str:
    text = str(value or "").strip()
    text = re.sub(r"beastmerge[_-][A-Za-z0-9_-]+", "beastmerge_<redacted>", text, flags=re.I)
    text = re.sub(r"df_[A-Za-z0-9_-]+", "df_<redacted>", text, flags=re.I)
    text = re.sub(r"(tgWebAppData|initData|runToken)=[^\s&]+", r"\1=<redacted>", text, flags=re.I)
    return text[: max(0, int(limit))]


def sanitize_beast_merge_secret_text(value: object, *, limit: int = 180) -> str:
    return _safe_text(value, limit)


def _digest(value: object) -> str:
    text = str(value or "").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12] if text else ""


def _host(value: object) -> str:
    try:
        return (urlsplit(str(value or "")).hostname or "").lower()
    except ValueError:
        return ""


def _path(value: object) -> str:
    try:
        return urlsplit(str(value or "")).path
    except ValueError:
        return ""


def _iter_app_candidates(data: object):
    if not isinstance(data, dict):
        return
    root = data.get("data") if isinstance(data.get("data"), dict) else data
    account = root.get("account") if isinstance(root.get("account"), dict) else root
    external = account.get("externalApps") if isinstance(account, dict) else None
    if external is None and isinstance(root, dict):
        external = root.get("externalApps")
    if isinstance(external, dict):
        groups = external.get("groups")
        if not isinstance(groups, list):
            groups = [external]
    elif isinstance(external, list):
        groups = external
    else:
        groups = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        apps = group.get("apps")
        if not isinstance(apps, list):
            apps = group.get("items") if isinstance(group.get("items"), list) else []
        for app in apps:
            if isinstance(app, dict):
                yield app


def _candidate_url(app: dict) -> str:
    for key in ("url", "href", "webviewUrl", "webViewUrl", "path"):
        value = str(app.get(key) or "").strip()
        if value:
            return value
    return ""


def _candidate_token(app: dict, url: str) -> str:
    for key in ("token", "startapp", "startApp", "startParam", "start_param"):
        value = str(app.get(key) or "").strip()
        if BEAST_MERGE_TOKEN_PATTERN.match(value):
            return value
    try:
        query = parse_qs(urlsplit(url).query)
    except ValueError:
        query = {}
    for key in ("startapp", "tgWebAppStartParam", "start_param"):
        for value in query.get(key, []):
            if BEAST_MERGE_TOKEN_PATTERN.match(str(value or "").strip()):
                return str(value).strip()
    match = BEAST_MERGE_TOKEN_SEARCH.search(json.dumps(app, ensure_ascii=False))
    return match.group(0) if match else ""


def extract_beast_merge_launch(data: object) -> dict:
    for app in _iter_app_candidates(data):
        if not bool(app.get("available", True)):
            continue
        url = _candidate_url(app)
        token = _candidate_token(app, url)
        path = _path(url) or (url if str(url).startswith("/") else "")
        host = _host(url)
        text = " ".join(str(app.get(key) or "") for key in ("title", "name", "description", "label"))
        path_matches = path.rstrip("/") == BEAST_MERGE_WEB_PATH
        keyword_matches = any(keyword.lower() in f"{text} {url}".lower() for keyword in BEAST_MERGE_KEYWORDS)
        if not path_matches or not token or not BEAST_MERGE_TOKEN_PATTERN.match(token):
            continue
        if host and host not in ESTATE_MINIAPP_ALLOWED_API_HOSTS:
            continue
        if not keyword_matches and "xianxia-beast-merge" not in path:
            continue
        return {
            "token": token,
            "entry": {
                "status_label": "公共洞府入口已解析",
                "title": _safe_text(app.get("title") or app.get("name") or "噬金虫进化", 60),
                "host": host or "asc.aiopenai.app",
                "path": BEAST_MERGE_WEB_PATH,
                "token_suffix": token[-4:],
                "token_digest": _digest(token),
            },
        }
    return {}


def _build_api_url(
    endpoint: str,
    *,
    api_base_url: str = ESTATE_MINIAPP_DEFAULT_API_BASE_URL,
) -> str:
    endpoint_path = BEAST_MERGE_ENDPOINTS.get(str(endpoint or "").strip(), "")
    if not endpoint_path:
        raise ValueError(f"unknown beast merge endpoint: {endpoint}")
    origin = f"{urlsplit(str(api_base_url or '')).scheme}://{urlsplit(str(api_base_url or '')).netloc}"
    if not origin or origin == "://":
        raise ValueError("beast merge api base url missing")
    url = urljoin(f"{origin}/", endpoint_path.lstrip("/"))
    parsed = urlsplit(url)
    if (parsed.hostname or "").lower() not in ESTATE_MINIAPP_ALLOWED_API_HOSTS:
        raise ValueError("beast merge api host not allowed")
    if not parsed.path.startswith(BEAST_MERGE_API_PREFIX):
        raise ValueError("beast merge api path not allowed")
    return url


def build_beast_merge_request(
    endpoint: str,
    *,
    token: str,
    init_data: str,
    payload: Optional[dict] = None,
    api_base_url: str = ESTATE_MINIAPP_DEFAULT_API_BASE_URL,
) -> dict:
    clean_token = str(token or "").strip()
    if not BEAST_MERGE_TOKEN_PATTERN.match(clean_token):
        raise ValueError("beast merge token not allowed")
    request_payload = {"token": clean_token, "initData": str(init_data or "")}
    request_payload.update(dict(payload or {}))
    url = _build_api_url(endpoint, api_base_url=api_base_url)
    return {
        "method": "POST",
        "url": url,
        "payload": request_payload,
        "safe_summary": {
            "endpoint": endpoint,
            "url_host": _host(url),
            "payload_keys": sorted(request_payload),
            "token_suffix": clean_token[-4:],
            "token_digest": _digest(clean_token),
            "init_data_digest": _digest(init_data),
        },
    }


def _urllib_transport(request: dict):
    body = json.dumps(request.get("payload") or {}, ensure_ascii=False).encode("utf-8")
    http_request = urllib.request.Request(
        request["url"],
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        method="POST",
    )
    with urllib.request.urlopen(http_request, timeout=20) as response:
        return int(getattr(response, "status", 200) or 200), response.read()


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


def _classify_response(status_code: int, body: object) -> dict:
    source = body if isinstance(body, dict) else {"value": body}
    data = source.get("data") if isinstance(source.get("data"), dict) else source
    if 200 <= int(status_code or 0) < 300 and source.get("ok") is not False:
        return {"ok": True, "status_code": int(status_code), "data": data, "error": ""}
    error = source.get("error") or source.get("message") or f"http_{status_code}"
    return {
        "ok": False,
        "status_code": int(status_code or 0),
        "data": data if isinstance(data, dict) else {},
        "error": _safe_text(error),
    }


def execute_beast_merge_request(request: dict, transport) -> dict:
    if transport is None:
        raise ValueError("beast merge transport missing")
    try:
        status_code, body = _coerce_response(transport(request))
        return _classify_response(status_code, body)
    except Exception as exc:
        return {"ok": False, "status_code": 0, "data": {}, "error": _safe_text(exc)}


def _execute_with_retry(request: dict, transport, sleeper) -> dict:
    result = execute_beast_merge_request(request, transport)
    if result.get("ok"):
        return result
    status_code = _int(result.get("status_code"))
    error = str(result.get("error") or "")
    if error == "run_too_fast":
        sleeper(1.5)
        return execute_beast_merge_request(request, transport)
    if status_code == 0 or status_code >= 500:
        return execute_beast_merge_request(request, transport)
    return result


def _attempts(data: object) -> tuple[int, int]:
    source = data if isinstance(data, dict) else {}
    attempts = source.get("attempts") if isinstance(source.get("attempts"), dict) else {}
    return max(0, _int(attempts.get("used"))), max(0, _int(attempts.get("limit"), 5)) or 5


def _server_state(data: object, fallback: Optional[dict] = None) -> dict:
    source = data if isinstance(data, dict) else {}
    state = source.get("state") if isinstance(source.get("state"), dict) else source
    previous = fallback or {}
    board = solver.normalize_board(state.get("board") if "board" in state else previous.get("board"))
    return {
        "board": board,
        "next_piece": max(1, _int(state.get("nextPiece"), _int(previous.get("next_piece"), 1))),
        "seq": max(0, _int(state.get("seq"), _int(previous.get("seq")))),
        "score": max(0, _int(state.get("score"), _int(previous.get("score")))),
        "max_tier": max(1, _int(state.get("maxTier"), _int(previous.get("max_tier"), 1))),
        "merge_count": max(0, _int(state.get("mergeCount"), _int(previous.get("merge_count")))),
        "game_over": bool(state.get("gameOver", previous.get("game_over", False))),
    }


def _rank(data: dict) -> int:
    own = data.get("self") if isinstance(data.get("self"), dict) else {}
    return max(0, _int(data.get("rank"), _int(own.get("rank"))))


def _best(data: dict) -> tuple[int, int]:
    own = data.get("self") if isinstance(data.get("self"), dict) else {}
    return (
        max(0, _int(own.get("score"), _int(own.get("bestScore")))),
        max(1, _int(own.get("maxTier"), _int(own.get("max_tier"), 1))),
    )


def _round_summary(data: dict, *, number: int, state: dict) -> dict:
    verified = data.get("verified") if isinstance(data.get("verified"), dict) else {}
    reward = data.get("reward") if isinstance(data.get("reward"), dict) else {}
    score = max(0, _int(verified.get("score"), state.get("score", 0)))
    max_tier = max(1, _int(verified.get("maxTier"), state.get("max_tier", 1)))
    return {
        "number": number,
        "status": "completed",
        "score": score,
        "max_tier": max_tier,
        "merge_count": max(0, _int(verified.get("mergeCount"), _int(verified.get("merge_count"), state.get("merge_count", 0)))),
        "moves_count": max(0, _int(verified.get("movesCount"), _int(verified.get("moves_count"), state.get("seq", 0)))),
        "duration_ms": max(0, _int(verified.get("durationMs"), _int(verified.get("duration_ms")))),
        "trace_reward": max(0, _int(reward.get("tianjiTrace"), _int(reward.get("tianji_trace")))),
        "rank": _rank(data),
        "improved": bool(data.get("improved")),
        "updated_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    }


def _progress(
    *,
    status_label: str,
    challenge_date: str,
    attempts_used: int,
    attempts_limit: int,
    service_max_moves: int,
    completed_runs: int,
    runs: list[dict],
    current: Optional[dict],
    trace_balance: int,
    rank: int,
    participants: int,
    entry: Optional[dict],
    solver_depth: int,
    error: str = "",
) -> dict:
    best_score = max([0, *[_int(item.get("score")) for item in runs]])
    best_tier = max([1, *[_int(item.get("max_tier"), 1) for item in runs]])
    total_trace = sum(max(0, _int(item.get("trace_reward"))) for item in runs)
    current_state = current or {}
    return {
        "status": "running" if current is not None else "completed",
        "status_label": status_label,
        "challenge_date": challenge_date,
        "attempts_used": attempts_used,
        "attempts_limit": attempts_limit,
        "service_max_moves": service_max_moves,
        "completed_runs": completed_runs,
        "runs": runs,
        "current": {
            "moves_count": max(0, _int(current_state.get("seq"))),
            "score": max(0, _int(current_state.get("score"))),
            "max_tier": max(1, _int(current_state.get("max_tier"), 1)),
            "merge_count": max(0, _int(current_state.get("merge_count"))),
            "empty_count": solver.normalize_board(current_state.get("board")).count(0),
        }
        if current is not None
        else {},
        "trace_balance": trace_balance,
        "best_score": best_score,
        "best_tier": best_tier,
        "total_trace": total_trace,
        "rank": rank,
        "participants": participants,
        "entry": entry or {},
        "solver_depth": solver_depth,
        "error": _safe_text(error),
    }


def run_beast_merge_flow(
    *,
    token: str,
    init_data: str,
    transport,
    entry: Optional[dict] = None,
    solver_depth: int = solver.DEFAULT_SEARCH_DEPTH,
    sleeper=time.sleep,
    monotonic=time.monotonic,
    move_interval_seconds: float = DEFAULT_MOVE_INTERVAL_SECONDS,
    progress_callback=None,
) -> dict:
    if not BEAST_MERGE_TOKEN_PATTERN.match(str(token or "").strip()):
        return {"ok": False, "status_label": "入口无效", "error": "beast merge token missing"}
    if not str(init_data or "").strip():
        return {"ok": False, "status_label": "入口无效", "error": "initData missing"}
    depth = max(1, int(solver_depth or solver.DEFAULT_SEARCH_DEPTH))
    start_request = build_beast_merge_request("start", token=token, init_data=init_data)
    start_result = execute_beast_merge_request(start_request, transport)
    if not start_result.get("ok"):
        return {"ok": False, "status_label": "读取虫巢状态失败", "error": start_result.get("error")}

    start_data = start_result.get("data") if isinstance(start_result.get("data"), dict) else {}
    used, limit = _attempts(start_data)
    challenge_date = _safe_text(start_data.get("challengeDate"), 20)
    game = start_data.get("game") if isinstance(start_data.get("game"), dict) else {}
    columns = _int(game.get("columns"), solver.COLS)
    rows = _int(game.get("rows"), solver.ROWS)
    max_moves = max(1, _int(game.get("maxMoves"), 160))
    if columns != solver.COLS or rows != solver.ROWS:
        return {"ok": False, "status_label": "棋盘规格不匹配", "error": f"unsupported board: {columns}x{rows}"}
    trace_balance = max(0, _int(start_data.get("traceBalance")))
    rank = _rank(start_data)
    participants = max(0, _int(start_data.get("participants")))
    best_score, best_tier = _best(start_data)
    runs: list[dict] = []

    if progress_callback is not None:
        progress_callback(
            {
                **_progress(
                    status_label="已读取虫巢状态，准备执行剩余局数",
                    challenge_date=challenge_date,
                    attempts_used=used,
                    attempts_limit=limit,
                    service_max_moves=max_moves,
                    completed_runs=0,
                    runs=runs,
                    current=None,
                    trace_balance=trace_balance,
                    rank=rank,
                    participants=participants,
                    entry=entry,
                    solver_depth=depth,
                ),
                "status": "running",
                "best_score": best_score,
                "best_tier": best_tier,
            }
        )

    while used < limit:
        run_start_request = build_beast_merge_request("run_start", token=token, init_data=init_data)
        run_start_result = execute_beast_merge_request(run_start_request, transport)
        if not run_start_result.get("ok"):
            if str(run_start_result.get("error") or "") == "daily_attempt_limit":
                used = limit
                break
            return {
                **_progress(
                    status_label="开局失败，未继续创建新局",
                    challenge_date=challenge_date,
                    attempts_used=used,
                    attempts_limit=limit,
                    service_max_moves=max_moves,
                    completed_runs=len(runs),
                    runs=runs,
                    current=None,
                    trace_balance=trace_balance,
                    rank=rank,
                    participants=participants,
                    entry=entry,
                    solver_depth=depth,
                    error=run_start_result.get("error"),
                ),
                "ok": False,
            }
        run_data = run_start_result.get("data") if isinstance(run_start_result.get("data"), dict) else {}
        run_token = str(run_data.get("runToken") or "").strip()
        if not run_token:
            return {"ok": False, "status_label": "开局失败", "error": "run token missing", "runs": runs}
        used, limit = _attempts(run_data)
        state = _server_state(run_data)
        rejected_columns: set[int] = set()
        recovery_count = 0
        last_move_started = 0.0
        if progress_callback is not None:
            progress_callback(
                _progress(
                    status_label=f"正在执行第 {used}/{limit} 局",
                    challenge_date=challenge_date,
                    attempts_used=used,
                    attempts_limit=limit,
                    service_max_moves=max_moves,
                    completed_runs=len(runs),
                    runs=runs,
                    current=state,
                    trace_balance=trace_balance,
                    rank=rank,
                    participants=participants,
                    entry=entry,
                    solver_depth=depth,
                )
            )

        while state["seq"] < max_moves and not state.get("game_over"):
            column = solver.choose_column(
                state["board"],
                state["next_piece"],
                depth=depth,
                excluded_columns=rejected_columns,
            )
            if column is None:
                break
            if last_move_started:
                remaining_delay = float(move_interval_seconds) - (monotonic() - last_move_started)
                if remaining_delay > 0:
                    sleeper(remaining_delay)
            request = build_beast_merge_request(
                "move",
                token=token,
                init_data=init_data,
                payload={"runToken": run_token, "column": column, "seq": state["seq"]},
            )
            last_move_started = monotonic()
            move_result = _execute_with_retry(request, transport, sleeper)
            if not move_result.get("ok"):
                error_data = move_result.get("data") if isinstance(move_result.get("data"), dict) else {}
                authority = error_data.get("state") if isinstance(error_data.get("state"), dict) else None
                if authority is not None and recovery_count < 3:
                    state = _server_state(authority, state)
                    rejected_columns.clear()
                    recovery_count += 1
                    continue
                return {
                    **_progress(
                        status_label="当前局同步失败，已停止且未开启新局",
                        challenge_date=challenge_date,
                        attempts_used=used,
                        attempts_limit=limit,
                        service_max_moves=max_moves,
                        completed_runs=len(runs),
                        runs=runs,
                        current=state,
                        trace_balance=trace_balance,
                        rank=rank,
                        participants=participants,
                        entry=entry,
                        solver_depth=depth,
                        error=move_result.get("error"),
                    ),
                    "ok": False,
                }
            move_data = move_result.get("data") if isinstance(move_result.get("data"), dict) else {}
            if not bool(move_data.get("accepted", True)):
                state = _server_state(move_data, state)
                rejected_columns.add(column)
                if len(rejected_columns) >= solver.COLS:
                    break
                continue
            state = _server_state(move_data, state)
            rejected_columns.clear()
            recovery_count = 0
            if progress_callback is not None and (state["seq"] % 5 == 0 or state.get("game_over")):
                progress_callback(
                    _progress(
                        status_label=f"第 {used}/{limit} 局 · {state['seq']}/{max_moves} 步",
                        challenge_date=challenge_date,
                        attempts_used=used,
                        attempts_limit=limit,
                        service_max_moves=max_moves,
                        completed_runs=len(runs),
                        runs=runs,
                        current=state,
                        trace_balance=trace_balance,
                        rank=rank,
                        participants=participants,
                        entry=entry,
                        solver_depth=depth,
                    )
                )

        submit_request = build_beast_merge_request(
            "submit",
            token=token,
            init_data=init_data,
            payload={"runToken": run_token},
        )
        submit_result = _execute_with_retry(submit_request, transport, sleeper)
        if not submit_result.get("ok"):
            return {
                **_progress(
                    status_label="当前局结算失败，已停止且未开启新局",
                    challenge_date=challenge_date,
                    attempts_used=used,
                    attempts_limit=limit,
                    service_max_moves=max_moves,
                    completed_runs=len(runs),
                    runs=runs,
                    current=state,
                    trace_balance=trace_balance,
                    rank=rank,
                    participants=participants,
                    entry=entry,
                    solver_depth=depth,
                    error=submit_result.get("error"),
                ),
                "ok": False,
            }
        submit_data = submit_result.get("data") if isinstance(submit_result.get("data"), dict) else {}
        round_result = _round_summary(submit_data, number=len(runs) + 1, state=state)
        runs.append(round_result)
        reward = submit_data.get("reward") if isinstance(submit_data.get("reward"), dict) else {}
        trace_balance = max(0, _int(reward.get("balance"), trace_balance))
        rank = _rank(submit_data) or round_result["rank"] or rank
        participants = max(0, _int(submit_data.get("participants"), participants))
        if progress_callback is not None:
            progress_callback(
                _progress(
                    status_label=f"第 {used}/{limit} 局已结算",
                    challenge_date=challenge_date,
                    attempts_used=used,
                    attempts_limit=limit,
                    service_max_moves=max_moves,
                    completed_runs=len(runs),
                    runs=runs,
                    current=None,
                    trace_balance=trace_balance,
                    rank=rank,
                    participants=participants,
                    entry=entry,
                    solver_depth=depth,
                )
            )

        refresh_result = execute_beast_merge_request(start_request, transport)
        if not refresh_result.get("ok"):
            return {
                **_progress(
                    status_label="本局已结算，刷新剩余次数失败，未开启新局",
                    challenge_date=challenge_date,
                    attempts_used=used,
                    attempts_limit=limit,
                    service_max_moves=max_moves,
                    completed_runs=len(runs),
                    runs=runs,
                    current=None,
                    trace_balance=trace_balance,
                    rank=rank,
                    participants=participants,
                    entry=entry,
                    solver_depth=depth,
                    error=refresh_result.get("error"),
                ),
                "ok": False,
            }
        refreshed = refresh_result.get("data") if isinstance(refresh_result.get("data"), dict) else {}
        used, limit = _attempts(refreshed)
        trace_balance = max(0, _int(refreshed.get("traceBalance"), trace_balance))
        rank = _rank(refreshed) or rank
        participants = max(0, _int(refreshed.get("participants"), participants))

    return {
        **_progress(
            status_label="今日剩余局数已完成" if runs else "今日虫巢已满额",
            challenge_date=challenge_date,
            attempts_used=used,
            attempts_limit=limit,
            service_max_moves=max_moves,
            completed_runs=len(runs),
            runs=runs,
            current=None,
            trace_balance=trace_balance,
            rank=rank,
            participants=participants,
            entry=entry,
            solver_depth=depth,
        ),
        "ok": True,
    }


async def resolve_beast_merge_public_launch(
    client: object,
    storage: object,
    *,
    transport=None,
    sleeper=time.sleep,
) -> dict:
    discovery = await estate_miniapp.resolve_estate_public_miniapp_launch(client, storage)
    if not discovery.get("ok"):
        return {"ok": False, "error": _safe_text(discovery.get("error") or "公共洞府入口未找到")}
    launch = discovery.get("launch") if isinstance(discovery.get("launch"), dict) else {}
    try:
        init_data = await estate_miniapp.request_estate_miniapp_init_data(
            client,
            token=launch.get("token"),
            webview_url=launch.get("webview_url"),
            bot_username=launch.get("bot_username"),
            launch_context=launch,
        )
    except Exception as exc:
        return {"ok": False, "error": _safe_text(exc)}
    estate_request = estate_miniapp.build_estate_miniapp_request(
        "start",
        token=launch.get("token"),
        init_data=init_data,
    )
    lookup = await asyncio.to_thread(
        estate_miniapp.execute_estate_external_app_lookup,
        estate_request,
        transport or _urllib_transport,
        extract_beast_merge_launch,
        action="beast_merge",
        sleeper=sleeper,
    )
    estate_result = lookup.get("result") or {}
    if not estate_result.get("ok"):
        return {"ok": False, "error": _safe_text(estate_result.get("error") or "洞府状态读取失败")}
    beast_launch = lookup.get("launch") or {}
    if not beast_launch:
        return {
            "ok": False,
            "error": (
                f"洞府外府目录连续 {int(lookup.get('attempts') or 1)} 次"
                "未返回噬金虫入口"
            ),
        }
    return {
        "ok": True,
        "token": beast_launch["token"],
        "init_data": init_data,
        "entry": beast_launch["entry"],
        "error": "",
    }


async def run_beast_merge_public_production_flow(
    client: object,
    *,
    discovery_storage: object,
    transport=None,
    solver_depth: int = solver.DEFAULT_SEARCH_DEPTH,
    sleeper=time.sleep,
    monotonic=time.monotonic,
    move_interval_seconds: float = DEFAULT_MOVE_INTERVAL_SECONDS,
    progress_callback=None,
) -> dict:
    try:
        launch = await resolve_beast_merge_public_launch(
            client,
            discovery_storage,
            transport=transport,
            sleeper=sleeper,
        )
        if not launch.get("ok"):
            return {"ok": False, "status_label": "公共洞府入口解析失败", "error": launch.get("error")}
        return await asyncio.to_thread(
            run_beast_merge_flow,
            token=launch.get("token"),
            init_data=launch.get("init_data"),
            transport=transport or _urllib_transport,
            entry=launch.get("entry"),
            solver_depth=solver_depth,
            sleeper=sleeper,
            monotonic=monotonic,
            move_interval_seconds=move_interval_seconds,
            progress_callback=progress_callback,
        )
    except Exception as exc:
        return {"ok": False, "status_label": "执行失败，未自动开启新局", "error": _safe_text(exc)}
