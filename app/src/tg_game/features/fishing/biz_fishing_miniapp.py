import asyncio
import hashlib
import json
import math
import random
import re
import time
from typing import Optional
from urllib.parse import unquote, urljoin, urlsplit
import urllib.request

from telethon import functions
from tg_game.features.estate import biz_estate_miniapp as estate_miniapp
from tg_game.features.fishing.biz_fishing_miniapp_entry import (
    MAX_FISHING_RESULT_TEXT_LENGTH,
    MINIAPP_ENTRY_MARKER,
    MINIAPP_SAFETY_BOUNDARY,
    _FISH_TOKEN_PATTERN,
    _host_from_url,
    _origin_from_url,
    _parse_pairs,
    _safe_text,
    _start_param_kind,
    append_miniapp_entry_block,
    default_miniapp_entry,
    describe_miniapp_button_debug,
    extract_fishing_miniapp_entry,
    extract_fishing_miniapp_launch,
    format_miniapp_entry_block,
    looks_like_fishing_miniapp_prompt,
    parse_miniapp_entry_block,
    strip_miniapp_entry_block,
)


FISHING_MINIAPP_DEFAULT_BOT_USERNAME = "fanrenxiuxian_bot"
FISHING_MINIAPP_DEFAULT_API_BASE_URL = "https://asc.aiopenai.app"
FISHING_MINIAPP_WEB_PATH = "/miniapp/xianxia-fishing"
FISHING_MINIAPP_API_PATH_PREFIX = "/api/miniapp/xianxia-fishing/"
FISHING_MINIAPP_ENDPOINTS = {
    "start": f"{FISHING_MINIAPP_API_PATH_PREFIX}start",
    "shop": f"{FISHING_MINIAPP_API_PATH_PREFIX}shop",
    "buy_bait": f"{FISHING_MINIAPP_API_PATH_PREFIX}buy-bait",
    "finish": f"{FISHING_MINIAPP_API_PATH_PREFIX}finish",
    "result": f"{FISHING_MINIAPP_API_PATH_PREFIX}result",
    "next": f"{FISHING_MINIAPP_API_PATH_PREFIX}next",
}
FISHING_MINIAPP_ALLOWED_WEB_HOSTS = {"t.me", "telegram.me", "asc.aiopenai.app"}
FISHING_MINIAPP_ALLOWED_API_HOSTS = {"asc.aiopenai.app"}
FISHING_MINIAPP_PROOF_DURATION_CAP_MS = 120_000
FISHING_MINIAPP_BITE_WAIT_CAP_MS = 75_000
FISHING_MINIAPP_RESULT_POLL_LIMIT = 18
FISHING_MINIAPP_RESULT_POLL_DELAY_SEC = 0.65
FISHING_MINIAPP_CHAIN_REST_RANGE_SEC = (2.0, 4.0)
FISHING_MINIAPP_MAX_DAILY_ROUNDS = 20
FISHING_MINIAPP_DAILY_LIMIT_FALLBACK = 5

_START_TOKEN_PATTERN = re.compile(
    r"\b(?P<kind>fish|farm|boss|rpt|stk|trial|df)_[A-Za-z0-9_-]{4,}\b",
    re.IGNORECASE,
)
_SENSITIVE_PAYLOAD_KEYS = {
    "auth_date",
    "hash",
    "initData",
    "query_id",
    "signature",
    "tgWebAppData",
    "token",
    "user",
}


def _safe_digest(value: object) -> str:
    text = str(value or "")
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def sanitize_miniapp_secret_text(text: object, *, limit: int = 220) -> str:
    raw = str(text or "")
    raw = re.sub(
        r"(?P<key>tgWebAppData|initData|query_id|hash|user|signature|token|startapp|start_param)=([^&#\s]+)",
        lambda m: f"{m.group('key')}=<redacted>",
        raw,
        flags=re.IGNORECASE,
    )
    raw = _START_TOKEN_PATTERN.sub(lambda m: f"{m.group('kind')}_<redacted>", raw)
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw[:limit]


def _safe_payload_value(key: str, value: object):
    key_text = str(key or "")
    if key_text in _SENSITIVE_PAYLOAD_KEYS or key_text.lower() in {
        "initdata",
        "tgwebappdata",
    }:
        return {
            "redacted": True,
            "digest": _safe_digest(value),
        }
    if isinstance(value, dict):
        return {str(k): _safe_payload_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_payload_value("", item) for item in value[:8]]
    if isinstance(value, str):
        return sanitize_miniapp_secret_text(value, limit=120)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _safe_text(value, 120)


def _json_shape(value: object, depth: int = 0):
    if depth > 3:
        return "..."
    if isinstance(value, dict):
        return {
            str(key): _json_shape(child, depth + 1)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))[:16]
        }
    if isinstance(value, list):
        return [_json_shape(value[0], depth + 1)] if value else []
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"


def _proof_capture_summary(payload: object) -> dict:
    payload = payload if isinstance(payload, dict) else {}
    proof = payload.get("fishingProof") if isinstance(payload.get("fishingProof"), dict) else {}
    if not proof:
        return {}
    challenge_id = str(proof.get("challengeId") or "").strip()
    summary = {}
    mode = str(proof.get("mode") or "").strip()
    if mode:
        summary["mode"] = mode
    if challenge_id:
        summary["challenge_suffix"] = challenge_id[-4:]
        summary["challenge_digest"] = _safe_digest(challenge_id)
    events = proof.get("events") if isinstance(proof.get("events"), list) else []
    if events:
        summary["events"] = len(events)
    for key in ("durationMs",):
        if key in proof:
            value = proof.get(key)
            if isinstance(value, (int, float)):
                summary[key] = round(float(value), 4) if isinstance(value, float) else int(value)
    return summary


def _response_capture_summary(data: object) -> dict:
    view = _unwrap_data(data)
    result = view.get("result") if isinstance(view.get("result"), dict) else view
    if not isinstance(result, dict):
        return {}
    summary = {}
    for key in ("ready", "caught", "status", "reason", "grade", "score", "duration_ms", "quality_bonus"):
        value = result.get(key)
        if isinstance(value, (str, int, float, bool)) and value not in ("", None):
            summary[key] = value
    fish = result.get("fish")
    if isinstance(fish, dict):
        name = str(fish.get("name") or "").strip()
        if name:
            summary["fish"] = sanitize_miniapp_secret_text(name, limit=40)
    rarity = str(result.get("rarityLabel") or result.get("rarity") or "").strip()
    if rarity:
        summary["rarity"] = sanitize_miniapp_secret_text(rarity, limit=40)
    return summary


def _build_api_url(endpoint: str, api_base_url: str = FISHING_MINIAPP_DEFAULT_API_BASE_URL) -> str:
    endpoint_path = FISHING_MINIAPP_ENDPOINTS.get(str(endpoint or "").strip(), "")
    if not endpoint_path:
        raise ValueError(f"unknown fishing miniapp endpoint: {endpoint}")
    base_origin = _origin_from_url(str(api_base_url or "").strip())
    if not base_origin:
        raise ValueError("miniapp api base url missing")
    url = urljoin(f"{base_origin}/", endpoint_path.lstrip("/"))
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host not in FISHING_MINIAPP_ALLOWED_API_HOSTS:
        raise ValueError(f"miniapp api host not allowed: {host}")
    if not parsed.path.startswith(FISHING_MINIAPP_API_PATH_PREFIX):
        raise ValueError(f"miniapp api path not allowed: {parsed.path}")
    return url


def build_fishing_miniapp_request(
    endpoint: str,
    *,
    token: str,
    init_data: str,
    payload: Optional[dict] = None,
    api_base_url: str = FISHING_MINIAPP_DEFAULT_API_BASE_URL,
) -> dict:
    clean_token = str(token or "").strip()
    if not clean_token or not _FISH_TOKEN_PATTERN.match(clean_token):
        raise ValueError("fishing miniapp token not allowed")
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
            "token_kind": _start_param_kind(clean_token),
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
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        },
        method=str(request.get("method") or "POST"),
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
        text = body.decode("utf-8", errors="replace")
        try:
            body = json.loads(text)
        except json.JSONDecodeError:
            body = {"text": text}
    elif isinstance(body, str):
        try:
            body = json.loads(body)
        except json.JSONDecodeError:
            body = {"text": body}
    return int(status or 0), body


def _classify_http_response(status_code: int, body: object) -> dict:
    if not isinstance(body, dict):
        body = {"value": body}
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    if 200 <= int(status_code or 0) < 300 and body.get("ok") is not False:
        return {"ok": True, "status_code": int(status_code), "data": data, "error": ""}
    error = body.get("error") or body.get("message") or f"http_{status_code}"
    return {
        "ok": False,
        "status_code": int(status_code or 0),
        "data": data if isinstance(data, dict) else {},
        "error": sanitize_miniapp_secret_text(error),
    }


def _emit_capture(capture_sink, *, request: dict, response: dict, step_key: str, source: str, elapsed_ms: int) -> None:
    if capture_sink is None:
        return
    safe_request = dict(request.get("safe_summary") or {})
    payload = dict(request.get("payload") or {})
    record = {
        "source": sanitize_miniapp_secret_text(source, limit=120),
        "step": str(step_key or safe_request.get("endpoint") or ""),
        "elapsed_ms": int(elapsed_ms or 0),
        "request": {
            **safe_request,
            "payload": {
                str(key): _safe_payload_value(str(key), value)
                for key, value in payload.items()
            },
            "payload_shape": _json_shape(payload),
            "proof": _proof_capture_summary(payload),
        },
        "response": {
            "ok": bool(response.get("ok")),
            "status_code": int(response.get("status_code") or 0),
            "data_shape": _json_shape(response.get("data") or {}),
            "summary": _response_capture_summary(response.get("data") or {}),
            "error": sanitize_miniapp_secret_text(response.get("error") or ""),
        },
    }
    if hasattr(capture_sink, "append"):
        capture_sink.append(record)
    else:
        capture_sink(record)


def execute_fishing_miniapp_request(
    request: dict,
    transport,
    *,
    capture_sink=None,
    capture_source: str = "",
    step_key: str = "",
) -> dict:
    if transport is None:
        raise ValueError("miniapp transport missing")
    started = time.time()
    try:
        status_code, body = _coerce_response(transport(request))
        result = _classify_http_response(status_code, body)
    except Exception as exc:
        result = {
            "ok": False,
            "status_code": 0,
            "data": {},
            "error": sanitize_miniapp_secret_text(exc),
        }
    elapsed_ms = int((time.time() - started) * 1000)
    _emit_capture(
        capture_sink,
        request=request,
        response=result,
        step_key=step_key,
        source=capture_source,
        elapsed_ms=elapsed_ms,
    )
    return result


def _unwrap_data(data: object) -> dict:
    if not isinstance(data, dict):
        return {}
    if isinstance(data.get("data"), dict):
        return data["data"]
    if isinstance(data.get("result"), dict) and len(data) == 1:
        return data["result"]
    return data


def _nested_dict(data: object, key: str) -> dict:
    if not isinstance(data, dict):
        return {}
    value = data.get(key)
    return value if isinstance(value, dict) else {}


def _number(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _extract_start_view(data: object) -> dict:
    view = _unwrap_data(data)
    session = _nested_dict(view, "session")
    challenge = view.get("challenge")
    if isinstance(challenge, dict):
        return {"phase": "bite", "challenge": challenge, "bite_in_ms": 0.0}
    server_now = _number(
        view.get("serverNow")
        or view.get("server_now")
        or session.get("serverNow")
        or session.get("server_now")
    )
    bite_at = _number(
        view.get("biteAt")
        or view.get("bite_at")
        or session.get("biteAt")
        or session.get("bite_at")
    )
    bite_in_ms = max(0.0, bite_at - server_now) if bite_at and server_now else 0.0
    return {
        "phase": str(view.get("phase") or session.get("phase") or ("waiting" if bite_at else "")),
        "challenge": None,
        "bite_in_ms": bite_in_ms,
    }


def _start_param_from_url(url: str) -> str:
    try:
        parsed = urlsplit(str(url or ""))
    except ValueError:
        return ""
    for key, value in [*_parse_pairs(parsed.query), *_parse_pairs(parsed.fragment)]:
        if str(key or "").strip().lower() in {
            "startapp",
            "start_param",
            "tgwebappstartparam",
        }:
            return str(value or "").strip()
    return ""


def extract_public_fishing_launch(data: object) -> dict:
    root = _unwrap_data(data)
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
                f"{FISHING_MINIAPP_DEFAULT_API_BASE_URL}/",
                str(app.get("url") or "").strip(),
            )
            try:
                parsed = urlsplit(url)
            except ValueError:
                continue
            if parsed.path != FISHING_MINIAPP_WEB_PATH:
                continue
            token = _start_param_from_url(url)
            if not _FISH_TOKEN_PATTERN.match(token):
                continue
            return {
                "token": token,
                "webview_url": url,
                "entry": {
                    "status": "captured",
                    "button_text": _safe_text(
                        app.get("buttonText") or app.get("title") or "灵溪垂钓",
                        48,
                    ),
                    "host": (parsed.hostname or "").lower(),
                    "path": parsed.path,
                    "token_suffix": token[-4:],
                    "token_digest": _safe_digest(token),
                },
            }
    return {}


def build_fishing_proof(challenge: object, *, rng=None) -> dict:
    challenge_data = challenge if isinstance(challenge, dict) else {}
    target_low = _number(challenge_data.get("targetLow"), 41.0)
    target_high = max(target_low + 1.0, _number(challenge_data.get("targetHigh"), 68.0))
    fish_power = max(0.1, _number(challenge_data.get("fishPower"), 1.7))
    min_duration = max(0.0, _number(challenge_data.get("minDurationMs"), 5200.0))
    max_duration = max(min_duration, _number(challenge_data.get("maxDurationMs"), 70000.0))
    duration_limit = min(max_duration, float(FISHING_MINIAPP_PROOF_DURATION_CAP_MS))
    seed_text = str(challenge_data.get("fishSeed") or "seed")
    seed_offset = sum(ord(ch) for ch in seed_text) / 19.0

    elapsed_ms = 0
    progress = 0.0
    tension = (target_low + target_high) / 2.0 - 8.0
    holding = False
    events = []
    hold_at = target_low
    release_at = max(target_low + 3.0, target_high - 24.0)

    while elapsed_ms < duration_limit:
        if not holding and tension < hold_at:
            holding = True
            events.append({"t": elapsed_ms + 20, "holding": True})
        elif holding and tension > release_at:
            holding = False
            events.append({"t": elapsed_ms + 20, "holding": False})

        elapsed_ms += 20
        dt = 0.02
        pulse = math.sin(elapsed_ms * 0.0027 * fish_power + seed_offset)
        surge = max(0.0, math.sin(elapsed_ms * 0.0041 + seed_offset * 1.7))
        fish_pull = fish_power * (0.72 + pulse * 0.24 + surge * 0.42)
        if holding:
            tension += (24.0 + fish_pull * 3.1) * dt
        else:
            tension += (fish_pull * 4.8 - 24.0) * dt
        tension += math.sin(elapsed_ms * 0.012 + seed_offset) * 0.24
        tension = max(0.0, min(100.0, tension))

        if target_low <= tension <= target_high:
            progress += (8.2 + fish_power * 0.7 + (2.2 if holding else 0.5)) * dt
        elif tension > target_high:
            progress -= (1.5 + fish_power * 0.25) * dt
        else:
            progress -= 0.9 * dt
        if holding and tension < target_low:
            progress += 1.1 * dt
        progress = max(0.0, min(100.0, progress))
        if progress >= 100.0 and elapsed_ms >= min_duration:
            break

    if progress < 100.0:
        raise ValueError("fishing_not_landed")
    return {
        "mode": "xianxiaFishingV2",
        "challengeId": str(challenge_data.get("challengeId") or ""),
        "durationMs": int(elapsed_ms),
        "events": events,
    }


def _flow_result(ok: bool, status: str, *, error: object = "", data: Optional[dict] = None, events: Optional[list] = None, proof: Optional[dict] = None) -> dict:
    result = {
        "ok": bool(ok),
        "status": str(status or "unknown"),
        "error": sanitize_miniapp_secret_text(error),
        "data": data or {},
        "events": events or [],
    }
    if proof:
        result["proof"] = {
            "mode": proof.get("mode"),
            "durationMs": proof.get("durationMs"),
            "events": len(proof.get("events") or []),
        }
    return result


def _append_event(events: list, step: str, result: dict) -> None:
    events.append(
        {
            "step": step,
            "ok": bool(result.get("ok")),
            "status_code": int(result.get("status_code") or 0),
            "error": sanitize_miniapp_secret_text(result.get("error") or ""),
        }
    )


def _extract_result_view(data: object) -> dict:
    view = _unwrap_data(data)
    result = view.get("result") if isinstance(view.get("result"), dict) else None
    return result or view


def _poll_fishing_result(
    *,
    token: str,
    init_data: str,
    transport,
    result_poll_limit: int,
    capture_sink=None,
    capture_source: str = "",
    events: Optional[list] = None,
    sleeper=None,
) -> dict:
    events = events if events is not None else []
    result_data = {}
    for _attempt in range(max(1, int(result_poll_limit or 0))):
        if sleeper is not None:
            sleeper(
                FISHING_MINIAPP_RESULT_POLL_DELAY_SEC if _attempt < 4 else 1.0
            )
        request = build_fishing_miniapp_request("result", token=token, init_data=init_data)
        result = execute_fishing_miniapp_request(
            request,
            transport,
            capture_sink=capture_sink,
            capture_source=capture_source,
            step_key="result",
        )
        _append_event(events, "result", result)
        if not result.get("ok"):
            return _flow_result(False, "failed", error=result.get("error"), events=events)
        result_data = _extract_result_view(result.get("data") or {})
        if result_data.get("ready") is True:
            return _flow_result(True, "settled", data=result_data, events=events)
    return _flow_result(
        False,
        "result_pending",
        error="fishing_result_pending",
        data=result_data,
        events=events,
    )


def _extract_next_token(data: object) -> str:
    if isinstance(data, dict):
        for key in ("nextToken", "next_token", "token"):
            value = str(data.get(key) or "").strip()
            if value and _FISH_TOKEN_PATTERN.match(value):
                return value
        for child in data.values():
            token = _extract_next_token(child)
            if token:
                return token
    if isinstance(data, list):
        for child in data:
            token = _extract_next_token(child)
            if token:
                return token
    return ""


def _extract_server_progress(data: object) -> tuple[int, int]:
    view = _unwrap_data(data)
    today = int(_number(view.get("today") or view.get("dailyUsed") or view.get("daily_count"), -1))
    limit = int(_number(view.get("limit") or view.get("dailyLimit") or view.get("daily_limit"), 0))
    return today, limit


def _extract_shop(data: object) -> dict:
    view = _unwrap_data(data)
    return view.get("shop") if isinstance(view.get("shop"), dict) else {}


def _find_shop_option(options: object, selected: object, *, key_fields: tuple[str, ...]) -> dict:
    selected_text = str(selected or "").strip()
    for option in options if isinstance(options, list) else []:
        if not isinstance(option, dict):
            continue
        values = {str(option.get(key) or "").strip() for key in key_fields}
        if selected_text in values:
            return option
    return {}


def _prepare_fishing_cast(
    *,
    token: str,
    init_data: str,
    pond: str,
    bait: str,
    required_bait_count: int,
    auto_buy_bait: bool,
    transport,
    capture_sink=None,
    capture_source: str = "",
    events: Optional[list] = None,
) -> dict:
    events = events if events is not None else []
    shop_request = build_fishing_miniapp_request("shop", token=token, init_data=init_data)
    shop_result = execute_fishing_miniapp_request(
        shop_request,
        transport,
        capture_sink=capture_sink,
        capture_source=capture_source,
        step_key="shop",
    )
    _append_event(events, "shop", shop_result)
    if not shop_result.get("ok"):
        return _flow_result(False, "failed", error=shop_result.get("error"), events=events)

    shop = _extract_shop(shop_result.get("data") or {})
    pond_option = _find_shop_option(shop.get("ponds"), pond, key_fields=("key", "name"))
    bait_option = _find_shop_option(shop.get("baits"), bait, key_fields=("key", "name", "itemId"))
    if not pond_option or not bool(pond_option.get("unlocked", True)):
        return _flow_result(False, "failed", error="fishing_pond_locked", events=events)
    if not bait_option or not bool(bait_option.get("unlocked", True)):
        return _flow_result(False, "failed", error="fishing_bait_level_low", events=events)

    required_count = max(1, int(required_bait_count or 1))
    bait_count = max(0, int(_number(bait_option.get("count"), 0)))
    if bait_count < required_count:
        if not auto_buy_bait:
            return _flow_result(False, "failed", error="fishing_bait_missing", events=events)
        quantity = required_count - bait_count
        buy_request = build_fishing_miniapp_request(
            "buy_bait",
            token=token,
            init_data=init_data,
            payload={"baitKey": str(bait_option.get("key") or ""), "quantity": quantity},
        )
        buy_result = execute_fishing_miniapp_request(
            buy_request,
            transport,
            capture_sink=capture_sink,
            capture_source=capture_source,
            step_key="buy_bait",
        )
        _append_event(events, "buy_bait", buy_result)
        if not buy_result.get("ok"):
            return _flow_result(False, "failed", error=buy_result.get("error"), events=events)

    next_request = build_fishing_miniapp_request(
        "next",
        token=token,
        init_data=init_data,
        payload={
            "pondKey": str(pond_option.get("key") or ""),
            "baitItemId": str(bait_option.get("itemId") or ""),
        },
    )
    next_result = execute_fishing_miniapp_request(
        next_request,
        transport,
        capture_sink=capture_sink,
        capture_source=capture_source,
        step_key="next",
    )
    _append_event(events, "next", next_result)
    if not next_result.get("ok"):
        if str(next_result.get("error") or "") == "fishing_daily_limit_reached":
            return _flow_result(True, "daily_limit", events=events)
        return _flow_result(False, "failed", error=next_result.get("error"), events=events)
    next_token = _extract_next_token(next_result.get("data") or {})
    if not next_token:
        return _flow_result(False, "failed", error="next token missing", events=events)
    today, limit = _extract_server_progress(next_result.get("data") or {})
    return _flow_result(
        True,
        "prepared",
        data={
            "token": next_token,
            "dailyUsed": today,
            "dailyLimit": limit,
            "pond": str(pond_option.get("name") or pond),
            "bait": str(bait_option.get("name") or bait),
        },
        events=events,
    )


def extract_fishing_miniapp_catches(data: object) -> list[dict]:
    data = _unwrap_data(data)
    if not isinstance(data, dict):
        return []
    catches = data.get("catches")
    if isinstance(catches, list):
        return [item for item in catches if isinstance(item, dict)]
    result = data.get("result") if isinstance(data.get("result"), dict) else data
    fish_value = result.get("fish")
    fish_data = fish_value if isinstance(fish_value, dict) else {}
    fish = str(
        fish_data.get("name")
        or fish_value
        or result.get("fishName")
        or result.get("name")
        or ""
    ).strip()
    if not fish:
        return []
    rewards = result.get("rewards") if isinstance(result.get("rewards"), list) else []
    return [
        {
            "fish": fish,
            "grade": str(result.get("grade") or result.get("rarityLabel") or result.get("quality") or "").strip(),
            "weight": str(fish_data.get("weight") or result.get("weight") or "").strip(),
            "rewards": [item for item in rewards if isinstance(item, dict)],
        }
    ]


def run_fishing_miniapp_flow(
    *,
    token: str,
    init_data: str,
    transport,
    sleeper=None,
    result_poll_limit: int = FISHING_MINIAPP_RESULT_POLL_LIMIT,
    bite_wait_cap_ms: int = FISHING_MINIAPP_BITE_WAIT_CAP_MS,
    capture_sink=None,
    capture_source: str = "",
) -> dict:
    if not str(token or "").strip():
        return _flow_result(False, "failed", error="token missing")
    if not str(init_data or "").strip():
        return _flow_result(False, "failed", error="initData missing")

    events: list[dict] = []
    request = build_fishing_miniapp_request("start", token=token, init_data=init_data)
    start_result = execute_fishing_miniapp_request(
        request,
        transport,
        capture_sink=capture_sink,
        capture_source=capture_source,
        step_key="start_waiting",
    )
    _append_event(events, "start_waiting", start_result)
    if not start_result.get("ok"):
        if start_result.get("error") == "fishing_token_used":
            return _poll_fishing_result(
                token=token,
                init_data=init_data,
                transport=transport,
                result_poll_limit=result_poll_limit,
                capture_sink=capture_sink,
                capture_source=capture_source,
                events=events,
                sleeper=sleeper,
            )
        return _flow_result(False, "failed", error=start_result.get("error"), events=events)

    view = _extract_start_view(start_result.get("data") or {})
    if view["challenge"] is None:
        if view["phase"] == "lobby":
            return _flow_result(True, "lobby", data={"phase": "lobby"}, events=events)
        if view["phase"] in {"expired", "settled", "missed"}:
            return _poll_fishing_result(
                token=token,
                init_data=init_data,
                transport=transport,
                result_poll_limit=result_poll_limit,
                capture_sink=capture_sink,
                capture_source=capture_source,
                events=events,
                sleeper=sleeper,
            )
        if view["phase"] != "waiting" or view["bite_in_ms"] > float(bite_wait_cap_ms or 0):
            return _flow_result(False, "not_ready", data={"phase": view["phase"], "bite_in_ms": view["bite_in_ms"]}, events=events)
        if sleeper is not None and view["bite_in_ms"] > 0:
            sleeper(view["bite_in_ms"] / 1000.0)
        request = build_fishing_miniapp_request("start", token=token, init_data=init_data)
        start_result = execute_fishing_miniapp_request(
            request,
            transport,
            capture_sink=capture_sink,
            capture_source=capture_source,
            step_key="start_bite",
        )
        _append_event(events, "start_bite", start_result)
        if not start_result.get("ok"):
            return _flow_result(False, "failed", error=start_result.get("error"), events=events)
        view = _extract_start_view(start_result.get("data") or {})

    if not view["challenge"]:
        return _flow_result(False, "not_ready", data={"phase": view["phase"]}, events=events)
    try:
        proof = build_fishing_proof(view["challenge"])
    except (TypeError, ValueError) as exc:
        return _flow_result(False, "failed", error=exc, events=events)
    events.append(
        {
            "step": "build_proof",
            "ok": True,
            "mode": proof["mode"],
            "durationMs": proof["durationMs"],
            "events": len(proof["events"]),
        }
    )
    if sleeper is not None and proof["durationMs"] > 0:
        sleeper(proof["durationMs"] / 1000.0)

    request = build_fishing_miniapp_request(
        "finish",
        token=token,
        init_data=init_data,
        payload={"fishingProof": proof},
    )
    finish_result = execute_fishing_miniapp_request(
        request,
        transport,
        capture_sink=capture_sink,
        capture_source=capture_source,
        step_key="finish",
    )
    _append_event(events, "finish", finish_result)
    if not finish_result.get("ok"):
        return _flow_result(False, "failed", error=finish_result.get("error"), events=events, proof=proof)

    result = _poll_fishing_result(
        token=token,
        init_data=init_data,
        transport=transport,
        result_poll_limit=result_poll_limit,
        capture_sink=capture_sink,
        capture_source=capture_source,
        events=events,
        sleeper=sleeper,
    )
    if proof and result.get("ok"):
        result["proof"] = {
            "mode": proof.get("mode"),
            "durationMs": proof.get("durationMs"),
            "events": len(proof.get("events") or []),
        }
    return result


def run_fishing_miniapp_loop_flow(
    *,
    token: str,
    init_data: str,
    transport,
    sleeper=None,
    max_rounds: int = 1,
    pond: str = "青溪浅滩",
    bait: str = "凡饵",
    auto_buy_bait: bool = True,
    capture_sink=None,
    capture_source: str = "",
) -> dict:
    try:
        max_rounds = max(1, int(max_rounds or 1))
    except (TypeError, ValueError):
        max_rounds = 1
    current_token = str(token or "").strip()
    settled_count = 0
    rounds = []
    events = []
    last_result = {}
    catches = []
    server_today = -1
    server_limit = 0
    limit_reached = False
    index = 0
    while settled_count < max_rounds:
        last_result = run_fishing_miniapp_flow(
            token=current_token,
            init_data=init_data,
            transport=transport,
            sleeper=sleeper,
            capture_sink=capture_sink,
            capture_source=capture_source,
        )
        if last_result.get("ok") and last_result.get("status") == "lobby":
            prepared = _prepare_fishing_cast(
                token=current_token,
                init_data=init_data,
                pond=pond,
                bait=bait,
                required_bait_count=1,
                auto_buy_bait=auto_buy_bait,
                transport=transport,
                capture_sink=capture_sink,
                capture_source=capture_source,
                events=events,
            )
            if prepared.get("status") == "daily_limit":
                data = {
                    "settled_count": settled_count,
                    "rounds": rounds,
                    "catches": catches,
                    "dailyUsed": max(server_today, 0),
                    "dailyLimit": server_limit or FISHING_MINIAPP_DAILY_LIMIT_FALLBACK,
                }
                return _flow_result(True, "daily_limit", data=data, events=events)
            if not prepared.get("ok"):
                return _flow_result(False, "failed", error=prepared.get("error"), data={"settled_count": settled_count, "rounds": rounds, "catches": catches}, events=events)
            prepared_data = prepared.get("data") if isinstance(prepared.get("data"), dict) else {}
            current_token = str(prepared_data.get("token") or "")
            server_today = int(_number(prepared_data.get("dailyUsed"), server_today))
            server_limit = int(_number(prepared_data.get("dailyLimit"), server_limit))
            continue

        index += 1
        round_catch = (extract_fishing_miniapp_catches(last_result.get("data") or {}) or [{}])[0]
        rounds.append(
            {
                "index": index,
                "ok": bool(last_result.get("ok")),
                "status": last_result.get("status"),
                "catch": round_catch,
            }
        )
        if round_catch:
            catches.append(round_catch)
        events.append({"step": "round", "ok": bool(last_result.get("ok")), "index": index})
        if not last_result.get("ok"):
            return _flow_result(settled_count > 0, last_result.get("status") or "failed", error=last_result.get("error"), data={"settled_count": settled_count, "rounds": rounds, "catches": catches, "dailyUsed": max(server_today, 0), "dailyLimit": server_limit or FISHING_MINIAPP_DAILY_LIMIT_FALLBACK}, events=events)
        settled_count += 1
        if settled_count >= max_rounds or (server_limit > 0 and server_today >= server_limit):
            break

        remaining_target = max_rounds - settled_count
        if server_limit > 0 and server_today >= 0:
            remaining_target = min(remaining_target, max(server_limit - server_today, 1))
        prepared = _prepare_fishing_cast(
            token=current_token,
            init_data=init_data,
            pond=pond,
            bait=bait,
            required_bait_count=remaining_target,
            auto_buy_bait=auto_buy_bait,
            transport=transport,
            capture_sink=capture_sink,
            capture_source=capture_source,
            events=events,
        )
        if prepared.get("status") == "daily_limit":
            limit_reached = True
            if server_limit > 0:
                server_today = server_limit
            break
        if not prepared.get("ok"):
            return _flow_result(True, "next_failed", error=prepared.get("error"), data={"settled_count": settled_count, "rounds": rounds, "catches": catches, "dailyUsed": max(server_today, 0), "dailyLimit": server_limit or FISHING_MINIAPP_DAILY_LIMIT_FALLBACK}, events=events)
        prepared_data = prepared.get("data") if isinstance(prepared.get("data"), dict) else {}
        current_token = str(prepared_data.get("token") or "")
        server_today = int(_number(prepared_data.get("dailyUsed"), server_today))
        server_limit = int(_number(prepared_data.get("dailyLimit"), server_limit))
        if sleeper is not None:
            low, high = FISHING_MINIAPP_CHAIN_REST_RANGE_SEC
            sleeper(random.uniform(low, high))

    data = {
        "settled_count": settled_count,
        "rounds": rounds,
        "catches": catches,
        "dailyUsed": max(server_today, settled_count),
        "dailyLimit": server_limit or FISHING_MINIAPP_DAILY_LIMIT_FALLBACK,
    }
    if isinstance(last_result.get("data"), dict):
        data.update(last_result["data"])
    status = (
        "daily_limit"
        if limit_reached or (server_limit > 0 and server_today >= server_limit)
        else "settled"
    )
    return _flow_result(True, status, data=data, events=events)


def _extract_init_data_from_webview_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    for key, value in _parse_pairs(parsed.fragment):
        if key == "tgWebAppData":
            return unquote(value)
    return ""


def run_fishing_miniapp_public_flow(
    *,
    estate_token: str,
    init_data: str,
    pond: str,
    bait: str,
    max_rounds: int,
    auto_buy_bait: bool,
    transport,
    sleeper=None,
    capture_sink=None,
    capture_source: str = "",
) -> dict:
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
            "failed",
            error=dwelling_result.get("error") or "公共洞府入口启动失败。",
        )
    launch = extract_public_fishing_launch(dwelling_result.get("data") or {})
    if not launch:
        return _flow_result(False, "failed", error="公共洞府未返回灵溪垂钓入口。")
    result = run_fishing_miniapp_loop_flow(
        token=launch.get("token"),
        init_data=init_data,
        transport=transport,
        sleeper=sleeper,
        max_rounds=max_rounds,
        pond=pond,
        bait=bait,
        auto_buy_bait=auto_buy_bait,
        capture_sink=capture_sink,
        capture_source=capture_source,
    )
    result["entry"] = launch.get("entry") or {}
    return result


async def request_fishing_miniapp_init_data(client: object, *, token: str, webview_url: str = "") -> str:
    clean_token = str(token or "").strip()
    if not clean_token or not _FISH_TOKEN_PATTERN.match(clean_token):
        raise ValueError("fishing miniapp token not allowed")
    host = _host_from_url(str(webview_url or ""))
    if host and host not in FISHING_MINIAPP_ALLOWED_WEB_HOSTS:
        raise ValueError(f"fishing miniapp web host not allowed: {host}")
    bot = await client.get_entity(FISHING_MINIAPP_DEFAULT_BOT_USERNAME)
    bot_input = await client.get_input_entity(bot)
    result = await client(
        functions.messages.RequestMainWebViewRequest(
            peer=bot_input,
            bot=bot_input,
            platform="android",
            start_param=clean_token,
        )
    )
    init_data = _extract_init_data_from_webview_url(getattr(result, "url", "") or "")
    if not init_data:
        raise RuntimeError("WebView URL 缺少 tgWebAppData")
    return init_data


async def run_fishing_miniapp_production_flow(
    client: object,
    *,
    token: str,
    webview_url: str = "",
    max_rounds: int = 1,
    transport=None,
    sleeper=None,
    capture_sink=None,
    capture_source: str = "",
) -> dict:
    try:
        init_data = await request_fishing_miniapp_init_data(
            client,
            token=token,
            webview_url=webview_url,
        )
        return await asyncio.to_thread(
            run_fishing_miniapp_loop_flow,
            token=token,
            init_data=init_data,
            transport=transport or _urllib_transport,
            sleeper=sleeper or time.sleep,
            max_rounds=max_rounds,
            capture_sink=capture_sink,
            capture_source=capture_source,
        )
    except Exception as exc:
        return _flow_result(False, "failed", error=exc)


async def run_fishing_miniapp_public_production_flow(
    client: object,
    *,
    discovery_storage: object,
    pond: str,
    bait: str,
    max_rounds: int,
    auto_buy_bait: bool = True,
    transport=None,
    sleeper=None,
    capture_sink=None,
    capture_source: str = "",
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
        )
        return await asyncio.to_thread(
            run_fishing_miniapp_public_flow,
            estate_token=launch.get("token"),
            init_data=init_data,
            pond=pond,
            bait=bait,
            max_rounds=max_rounds,
            auto_buy_bait=auto_buy_bait,
            transport=transport or _urllib_transport,
            sleeper=sleeper or time.sleep,
            capture_sink=capture_sink,
            capture_source=capture_source,
        )
    except Exception as exc:
        return _flow_result(False, "failed", error=exc)
