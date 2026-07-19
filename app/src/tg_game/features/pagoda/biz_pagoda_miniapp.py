import asyncio
import hashlib
import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit
import urllib.request

from tg_game.features.estate import biz_estate_miniapp as estate_miniapp
from tg_game.features.estate.biz_estate_constants import (
    ESTATE_MINIAPP_ALLOWED_API_HOSTS,
    ESTATE_MINIAPP_DEFAULT_API_BASE_URL,
)


PAGODA_WEB_PATH = "/miniapp/xianxia-pagoda"
PAGODA_API_PREFIX = "/api/miniapp/xianxia-pagoda/"
PAGODA_ENDPOINTS = {
    "start": f"{PAGODA_API_PREFIX}start",
    "challenge": f"{PAGODA_API_PREFIX}challenge",
}
PAGODA_TOKEN_PATTERN = re.compile(
    r"^pagoda[_-][A-Za-z0-9_-]{4,160}$",
    re.IGNORECASE,
)
PAGODA_TOKEN_SEARCH = re.compile(
    r"\bpagoda[_-][A-Za-z0-9_-]{4,160}\b",
    re.IGNORECASE,
)


def _safe_text(value: object, limit: int = 500) -> str:
    text = " ".join(str(value or "").split())
    text = PAGODA_TOKEN_SEARCH.sub("<pagoda-token>", text)
    text = re.sub(
        r"(?i)(initData|tgWebAppData)(\s*[:=]\s*)[^\s,&]+",
        r"\1\2<redacted>",
        text,
    )
    return text[: max(int(limit or 0), 0)]


def _safe_report(value: object, limit: int = 12000) -> str:
    text = PAGODA_TOKEN_SEARCH.sub("<pagoda-token>", str(value or ""))
    text = re.sub(
        r"(?i)(initData|tgWebAppData)(\s*[:=]\s*)[^\s,&]+",
        r"\1\2<redacted>",
        text,
    )
    return text[: max(int(limit or 0), 0)]


def _digest(value: object) -> str:
    text = str(value or "")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12] if text else ""


def _iter_app_candidates(value: object):
    if isinstance(value, dict):
        if any(key in value for key in ("url", "webviewUrl", "webview_url", "href")):
            yield value
        for child in value.values():
            yield from _iter_app_candidates(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_app_candidates(child)


def _candidate_url(app: dict) -> str:
    return str(
        app.get("url")
        or app.get("webviewUrl")
        or app.get("webview_url")
        or app.get("href")
        or ""
    ).strip()


def _candidate_token(app: dict, url: str) -> str:
    query = parse_qs(urlsplit(url).query)
    for key in ("startapp", "tgWebAppStartParam", "start_param"):
        for value in query.get(key, []):
            token = str(value or "").strip()
            if PAGODA_TOKEN_PATTERN.match(token):
                return token
    match = PAGODA_TOKEN_SEARCH.search(json.dumps(app, ensure_ascii=False))
    return match.group(0) if match else ""


def extract_pagoda_launch(data: object) -> dict:
    for app in _iter_app_candidates(data):
        if not bool(app.get("available", True)):
            continue
        raw_url = _candidate_url(app)
        url = urljoin(f"{ESTATE_MINIAPP_DEFAULT_API_BASE_URL}/", raw_url)
        parsed = urlsplit(url)
        token = _candidate_token(app, url)
        if parsed.path.rstrip("/") != PAGODA_WEB_PATH:
            continue
        if (parsed.hostname or "").lower() not in ESTATE_MINIAPP_ALLOWED_API_HOSTS:
            continue
        if not token or not PAGODA_TOKEN_PATTERN.match(token):
            continue
        title = str(app.get("title") or app.get("name") or "琉璃问心塔")
        return {
            "token": token,
            "entry": {
                "status_label": "公共洞府入口已解析",
                "title": _safe_text(title, 60),
                "host": (parsed.hostname or "").lower(),
                "path": PAGODA_WEB_PATH,
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
    endpoint_path = PAGODA_ENDPOINTS.get(str(endpoint or "").strip(), "")
    if not endpoint_path:
        raise ValueError(f"unknown pagoda endpoint: {endpoint}")
    parsed_base = urlsplit(str(api_base_url or ""))
    url = urljoin(f"{parsed_base.scheme}://{parsed_base.netloc}/", endpoint_path.lstrip("/"))
    parsed = urlsplit(url)
    if (parsed.hostname or "").lower() not in ESTATE_MINIAPP_ALLOWED_API_HOSTS:
        raise ValueError("pagoda api host not allowed")
    if not parsed.path.startswith(PAGODA_API_PREFIX):
        raise ValueError("pagoda api path not allowed")
    return url


def build_pagoda_request(
    endpoint: str,
    *,
    token: str,
    init_data: str,
    api_base_url: str = ESTATE_MINIAPP_DEFAULT_API_BASE_URL,
) -> dict:
    clean_token = str(token or "").strip()
    if not PAGODA_TOKEN_PATTERN.match(clean_token):
        raise ValueError("pagoda miniapp token not allowed")
    url = _build_api_url(endpoint, api_base_url=api_base_url)
    payload = {"token": clean_token, "initData": str(init_data or "")}
    return {
        "method": "POST",
        "url": url,
        "payload": payload,
        "safe_summary": {
            "endpoint": str(endpoint or ""),
            "host": (urlsplit(url).hostname or "").lower(),
            "payload_keys": sorted(payload),
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
        method=str(request.get("method") or "POST"),
    )
    with urllib.request.urlopen(http_request, timeout=90) as response:
        return int(getattr(response, "status", 200) or 200), response.read()


def _coerce_response(raw_response) -> tuple[int, object]:
    if isinstance(raw_response, tuple) and len(raw_response) == 2:
        status_code, body = raw_response
    else:
        status_code = int(getattr(raw_response, "status", 200) or 200)
        body = raw_response.read() if hasattr(raw_response, "read") else raw_response
    if isinstance(body, bytes):
        body = body.decode("utf-8", errors="replace")
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = {"text": body}
    return int(status_code or 0), body


def execute_pagoda_request(request: dict, transport) -> dict:
    if transport is None:
        raise ValueError("pagoda miniapp transport missing")
    try:
        status_code, body = _coerce_response(transport(request))
    except Exception as exc:
        return {"ok": False, "status_code": 0, "data": {}, "error": _safe_text(exc)}
    root = body if isinstance(body, dict) else {"value": body}
    data = root.get("data") if isinstance(root.get("data"), dict) else root
    ok = 200 <= status_code < 300 and root.get("ok") is not False
    return {
        "ok": ok,
        "status_code": status_code,
        "data": data if isinstance(data, dict) else {},
        "error": "" if ok else _safe_text(root.get("message") or root.get("error") or f"http_{status_code}"),
    }


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def sanitize_pagoda_state(value: object) -> dict:
    source = value if isinstance(value, dict) else {}
    aura = source.get("aura") if isinstance(source.get("aura"), dict) else {}
    return {
        "daoName": _safe_text(source.get("daoName"), 80),
        "level": _safe_text(source.get("level"), 80),
        "power": _int(source.get("power")),
        "todayHighest": _int(source.get("todayHighest")),
        "recordHighest": _int(source.get("recordHighest")),
        "towerMarks": _int(source.get("towerMarks")),
        "failedFloor": _int(source.get("failedFloor")),
        "resetsToday": _int(source.get("resetsToday")),
        "resetCost": _int(source.get("resetCost")),
        "canChallenge": bool(source.get("canChallenge")),
        "aura": {
            "name": _safe_text(aura.get("name"), 80),
            "desc": _safe_text(aura.get("desc"), 240),
        },
    }


def extract_pagoda_reward_lines(report: object) -> list[str]:
    lines = []
    for raw_line in str(report or "").splitlines():
        line = raw_line.strip().lstrip("- ").strip()
        if not line:
            continue
        if line.startswith(("修为", "宗门贡献", "威望", "获得", "塔印", "另有")):
            lines.append(_safe_text(line, 240))
        if len(lines) >= 30:
            break
    return lines


def sanitize_pagoda_replay(value: object) -> dict:
    source = value if isinstance(value, dict) else {}
    report = _safe_report(source.get("report"))
    floors = source.get("floors") if isinstance(source.get("floors"), list) else []
    return {
        "startFloor": _int(source.get("startFloor")),
        "endFloor": _int(source.get("endFloor")),
        "failedFloor": _int(source.get("failedFloor")),
        "clearedCount": _int(source.get("clearedCount")),
        "recordBroken": bool(source.get("recordBroken")),
        "floorCount": len(floors),
        "report": report,
        "rewardLines": extract_pagoda_reward_lines(report),
    }


def run_pagoda_flow(*, token: str, init_data: str, transport, progress_callback=None) -> dict:
    if progress_callback is not None:
        progress_callback("start")
    start_result = execute_pagoda_request(
        build_pagoda_request("start", token=token, init_data=init_data),
        transport,
    )
    state = sanitize_pagoda_state(start_result.get("data", {}).get("state"))
    if not start_result.get("ok"):
        return {"ok": False, "status": "failed", "state": state, "replay": {}, "error": start_result.get("error")}
    if not state.get("canChallenge"):
        return {
            "ok": True,
            "status": "skipped",
            "state": state,
            "replay": {},
            "error": "今日已闯塔，服务端当前不可再次挑战。",
        }
    if progress_callback is not None:
        progress_callback("challenge")
    challenge_result = execute_pagoda_request(
        build_pagoda_request("challenge", token=token, init_data=init_data),
        transport,
    )
    challenge_data = challenge_result.get("data") or {}
    final_state = (
        sanitize_pagoda_state(challenge_data.get("state"))
        if isinstance(challenge_data.get("state"), dict)
        else state
    )
    replay = sanitize_pagoda_replay(challenge_data.get("replay"))
    if not challenge_result.get("ok"):
        return {
            "ok": False,
            "status": "failed",
            "state": final_state,
            "replay": replay,
            "error": challenge_result.get("error"),
        }
    return {"ok": True, "status": "settled", "state": final_state, "replay": replay, "error": ""}


async def resolve_pagoda_public_launch(
    client: object,
    storage: object,
    *,
    transport=None,
) -> dict:
    discovery = await estate_miniapp.resolve_estate_public_miniapp_launch(client, storage)
    if not discovery.get("ok"):
        return {"ok": False, "error": _safe_text(discovery.get("error") or "公共洞府入口未找到")}
    estate_launch = discovery.get("launch") if isinstance(discovery.get("launch"), dict) else {}
    try:
        init_data = await estate_miniapp.request_estate_miniapp_init_data(
            client,
            token=estate_launch.get("token"),
            webview_url=estate_launch.get("webview_url"),
            bot_username=estate_launch.get("bot_username"),
        )
    except Exception as exc:
        return {"ok": False, "error": _safe_text(exc)}
    estate_request = estate_miniapp.build_estate_miniapp_request(
        "start",
        token=estate_launch.get("token"),
        init_data=init_data,
    )
    estate_result = estate_miniapp.execute_estate_miniapp_request(
        estate_request,
        transport or estate_miniapp._urllib_transport,
    )
    if not estate_result.get("ok"):
        return {"ok": False, "error": _safe_text(estate_result.get("error") or "洞府状态读取失败")}
    pagoda_launch = extract_pagoda_launch(estate_result.get("data"))
    if not pagoda_launch:
        return {"ok": False, "error": "公共洞府未返回琉璃问心塔入口"}
    return {
        "ok": True,
        "token": pagoda_launch["token"],
        "init_data": init_data,
        "entry": pagoda_launch["entry"],
        "error": "",
    }


async def run_pagoda_public_production_flow(
    client: object,
    *,
    discovery_storage: object,
    transport=None,
    progress_callback=None,
) -> dict:
    try:
        launch = await resolve_pagoda_public_launch(
            client,
            discovery_storage,
            transport=transport,
        )
        if not launch.get("ok"):
            return {"ok": False, "status": "failed", "state": {}, "replay": {}, "error": launch.get("error")}
        result = await asyncio.to_thread(
            run_pagoda_flow,
            token=launch.get("token"),
            init_data=launch.get("init_data"),
            transport=transport or _urllib_transport,
            progress_callback=progress_callback,
        )
        result = dict(result)
        result["entry"] = launch.get("entry")
        return result
    except Exception as exc:
        return {"ok": False, "status": "failed", "state": {}, "replay": {}, "error": _safe_text(exc)}
