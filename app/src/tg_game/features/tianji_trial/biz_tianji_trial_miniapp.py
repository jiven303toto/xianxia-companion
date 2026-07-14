import asyncio
import hashlib
import json
import re
import time
from typing import Optional
from urllib.parse import parse_qsl, quote, unquote, urljoin, urlsplit
import urllib.request

from telethon import functions
from tg_game.features.estate import biz_estate_miniapp as estate_miniapp
from .biz_tianji_trial_solver import (
    build_lightsout_trial_proof,
    build_memory_trial_proof,
    build_planarity_trial_proof,
    build_tianji_trial_proof,
    count_planarity_crossings,
)
from .biz_tianji_trial_view_state import (
    _miniapp_int,
    _normalize_tianji_trial_rounds,
    build_next_tianji_trial_request,
    build_tianji_trial_batch_run,
    build_tianji_trial_round,
    build_tianji_trial_run,
    build_tianji_trial_run_view,
    build_tianji_trial_view,
    default_tianji_trial_run,
    format_tianji_trial_capture_report,
    get_pending_tianji_trial_request,
    mark_tianji_trial_request_status,
    merge_tianji_trial_payload,
    queue_tianji_trial_request,
)


TIANJI_TRIAL_COMMAND = ".天机试炼"
TIANJI_REMNANT_COMMAND = ".天机残痕"
TIANJI_TRIAL_MINIAPP_DEFAULT_BOT_USERNAME = "fanrenxiuxian_bot"
TIANJI_TRIAL_MINIAPP_DEFAULT_API_BASE_URL = "https://asc.aiopenai.app"
TIANJI_TRIAL_MINIAPP_WEB_PATH = "/miniapp/xianxia-trial"
TIANJI_TRIAL_MINIAPP_API_PATH_PREFIX = "/api/miniapp/xianxia-trial/"
TIANJI_TRIAL_MINIAPP_ENDPOINTS = {
    "start": f"{TIANJI_TRIAL_MINIAPP_API_PATH_PREFIX}start",
    "finish": f"{TIANJI_TRIAL_MINIAPP_API_PATH_PREFIX}finish",
}
TIANJI_TRIAL_ALLOWED_WEB_HOSTS = {"t.me", "telegram.me", "asc.aiopenai.app"}
TIANJI_TRIAL_ALLOWED_API_HOSTS = {"asc.aiopenai.app"}
TIANJI_TRIAL_DEFAULT_BATCH_RUNS = 3
TIANJI_TRIAL_SAFETY_BOUNDARY = (
    "自动试炼会临时请求 Telegram WebView，并只调用 xianxia-trial/start 与 finish；"
    "不保存 initData/tgWebAppData/hash/user/raw URL。"
)

_TRIAL_KEYWORDS = ("天机试炼", "试炼台", "天机残痕", "trial", "xianxia-trial")
_URL_PATTERN = re.compile(r"(?:https?|tg)://[^\s<>'\"）)]+", re.IGNORECASE)
_TRIAL_TOKEN_PATTERN = re.compile(r"^(?:trial_)?[A-Za-z0-9_-]{4,160}$", re.IGNORECASE)
_START_TOKEN_PATTERN = re.compile(
    r"\b(?P<kind>trial)_[A-Za-z0-9_-]{4,}\b",
    re.IGNORECASE,
)
_START_PARAM_KEYS = {
    "startapp",
    "start_param",
    "startattach",
    "start",
    "tgwebappstartparam",
}
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
_SENSITIVE_KEY_LABELS = {
    "auth_date": "auth_date",
    "hash": "hash",
    "initdata": "initData",
    "query_id": "query_id",
    "signature": "signature",
    "tgwebappdata": "tgWebAppData",
    "user": "user",
}


def _safe_text(value: object, max_length: int = 80) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    text = _URL_PATTERN.sub("[url]", text)
    if len(text) > max_length:
        return f"{text[: max_length - 1]}..."
    return text


def _flatten_buttons(value: object):
    if value is None:
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _flatten_buttons(item)
        return
    for attr in ("rows", "buttons"):
        child = getattr(value, attr, None)
        if child is not None and child is not value:
            yield from _flatten_buttons(child)
            return
    yield value


def _button_text(button: object) -> str:
    for source in (button, getattr(button, "button", None)):
        if source is None:
            continue
        text = getattr(source, "text", None)
        if text:
            return _safe_text(text, 40)
    return ""


def _button_url(button: object) -> str:
    for source in (button, getattr(button, "button", None)):
        if source is None:
            continue
        direct_url = getattr(source, "url", None)
        if isinstance(direct_url, str) and direct_url.strip():
            return direct_url.strip()
        for attr in ("web_app", "webview", "web_view"):
            web_app = getattr(source, attr, None)
            web_app_url = getattr(web_app, "url", None) if web_app is not None else None
            if isinstance(web_app_url, str) and web_app_url.strip():
                return web_app_url.strip()
    return ""


def _iter_button_links(event: object):
    message = getattr(event, "message", None)
    for source in (
        getattr(message, "buttons", None),
        getattr(event, "buttons", None),
        getattr(message, "reply_markup", None),
        getattr(event, "reply_markup", None),
    ):
        for button in _flatten_buttons(source):
            url = _button_url(button)
            if url:
                yield _button_text(button), url


def _parse_pairs(text: str) -> list[tuple[str, str]]:
    if not text or "=" not in text:
        return []
    try:
        return [(str(key), str(value)) for key, value in parse_qsl(text, keep_blank_values=True)]
    except ValueError:
        return []


def _canonical_sensitive_key(key: str) -> Optional[str]:
    return _SENSITIVE_KEY_LABELS.get(str(key or "").strip().lower())


def _collect_sensitive_keys(pairs: list[tuple[str, str]]) -> list[str]:
    found: list[str] = []

    def add(key: str) -> None:
        canonical = _canonical_sensitive_key(key)
        if canonical and canonical not in found:
            found.append(canonical)

    for key, value in pairs:
        add(key)
        decoded = unquote(str(value or ""))
        for nested_key, _nested_value in _parse_pairs(decoded):
            add(nested_key)
        lowered = decoded.lower()
        for candidate in _SENSITIVE_KEY_LABELS:
            if f"{candidate}=" in lowered:
                add(candidate)
    return sorted(found)


def _start_param_kind(value: str) -> str:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return ""
    if lowered.startswith("trial"):
        return "trial"
    match = re.match(r"([a-z][a-z0-9]{1,15})(?:[_:\-.]|$)", lowered)
    return match.group(1) if match else "present"


def _start_param_pair(pairs: list[tuple[str, str]]) -> tuple[str, str]:
    for key, value in pairs:
        if str(key or "").strip().lower() in _START_PARAM_KEYS:
            return key, str(value or "").strip()
    return "", ""


def _start_param_summary(pairs: list[tuple[str, str]]) -> tuple[str, str, str, str]:
    key, param = _start_param_pair(pairs)
    if not key:
        return "", "", "", ""
    if not param:
        return key, "", "", ""
    return (
        key,
        _start_param_kind(param),
        param[-4:] if len(param) >= 4 else "",
        hashlib.sha256(param.encode("utf-8")).hexdigest()[:12],
    )


def _host_from_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    return (parsed.hostname or parsed.netloc or "").lower()


def _origin_from_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _summarize_url(button_text: str, url: str) -> Optional[dict]:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"http", "https", "tg"}:
        return None
    pairs = _parse_pairs(parsed.query) + _parse_pairs(parsed.fragment)
    start_key, start_kind, start_suffix, start_digest = _start_param_summary(pairs)
    return {
        "status": "captured",
        "button_text": _safe_text(button_text, 40),
        "host": _host_from_url(url),
        "start_param_key": _safe_text(start_key, 32),
        "start_param_kind": _safe_text(start_kind, 32),
        "start_param_suffix": _safe_text(start_suffix, 12),
        "start_param_digest": start_digest,
        "sensitive_keys": _collect_sensitive_keys(pairs),
    }


def _start_param_from_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    pairs = _parse_pairs(parsed.query) + _parse_pairs(parsed.fragment)
    _key, value = _start_param_pair(pairs)
    return value


def _looks_like_trial_entry(button_text: str, url: str, text: str, summary: dict) -> bool:
    haystack = " ".join(
        [
            str(button_text or ""),
            str(url or ""),
            str(text or ""),
            str(summary.get("start_param_kind") or ""),
        ]
    ).lower()
    return any(keyword.lower() in haystack for keyword in _TRIAL_KEYWORDS)


def looks_like_tianji_trial_miniapp_prompt(text: object) -> bool:
    normalized = str(text or "")
    return "天机试炼" in normalized and any(
        marker in normalized
        for marker in (
            "点击",
            "按钮",
            "试炼已绑定",
            "分钟内有效",
            "今日还可完成",
            "进入后可连续完成",
        )
    )


def extract_tianji_trial_miniapp_entry(event: object, text: str = "") -> Optional[dict]:
    for button_text, url in _iter_button_links(event):
        summary = _summarize_url(button_text, url)
        if summary and _looks_like_trial_entry(button_text, url, text, summary):
            return summary
    for match in _URL_PATTERN.finditer(str(text or "")):
        url = match.group(0)
        summary = _summarize_url("", url)
        if summary and _looks_like_trial_entry("", url, text, summary):
            return summary
    return None


def extract_tianji_trial_miniapp_launch(event: object, text: str = "") -> dict:
    for button_text, url in _iter_button_links(event):
        summary = _summarize_url(button_text, url)
        if not summary or not _looks_like_trial_entry(button_text, url, text, summary):
            continue
        token = _start_param_from_url(url)
        if token and _TRIAL_TOKEN_PATTERN.match(token):
            return {"token": token, "webview_url": url, "entry": summary}
    return {}


def extract_public_tianji_trial_launch(data: object) -> dict:
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
        apps = group.get("apps") if isinstance(group, dict) and isinstance(group.get("apps"), list) else []
        for app in apps:
            if not isinstance(app, dict) or str(app.get("key") or "").strip() != "tianji_trial":
                continue
            url = urljoin(
                f"{TIANJI_TRIAL_MINIAPP_DEFAULT_API_BASE_URL}/",
                str(app.get("url") or "").strip(),
            )
            summary = _summarize_url(str(app.get("buttonText") or app.get("title") or ""), url)
            token = _start_param_from_url(url)
            if (
                bool(app.get("available", True))
                and summary
                and token
                and _TRIAL_TOKEN_PATTERN.match(token)
            ):
                return {"token": token, "webview_url": url, "entry": summary}
    return {}


def default_tianji_trial_entry() -> dict:
    return {
        "status": "not_seen",
        "status_label": "未捕获",
        "button_text": "-",
        "host": "-",
        "start_param_key": "-",
        "start_param_kind": "-",
        "start_param_suffix": "-",
        "start_param_digest": "-",
        "sensitive_keys": [],
        "sensitive_keys_text": "-",
        "safety_boundary": TIANJI_TRIAL_SAFETY_BOUNDARY,
    }


def build_tianji_trial_entry_view(value: object) -> dict:
    base = default_tianji_trial_entry()
    if not isinstance(value, dict) or not value:
        return base
    sensitive_keys = [
        _safe_text(item, 32)
        for item in (value.get("sensitive_keys") or [])
        if _safe_text(item, 32)
    ]
    base.update(
        {
            "status": "captured",
            "status_label": "已捕获入口",
            "button_text": _safe_text(value.get("button_text") or "-", 40),
            "host": _safe_text(value.get("host") or "-", 80),
            "start_param_key": _safe_text(value.get("start_param_key") or "-", 32),
            "start_param_kind": _safe_text(value.get("start_param_kind") or "-", 32),
            "start_param_suffix": _safe_text(value.get("start_param_suffix") or "-", 12),
            "start_param_digest": _safe_text(value.get("start_param_digest") or "-", 20),
            "sensitive_keys": sensitive_keys,
            "sensitive_keys_text": ", ".join(sensitive_keys) or "-",
        }
    )
    return base


def _safe_digest(value: object) -> str:
    text = str(value or "")
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def sanitize_tianji_trial_secret_text(text: object, *, limit: int = 220) -> str:
    raw = str(text or "")
    raw = re.sub(
        r"(?P<key>tgWebAppData|initData|query_id|hash|user|signature|token|startapp|start_param)=([^&#\s]+)",
        lambda match: f"{match.group('key')}=<redacted>",
        raw,
        flags=re.IGNORECASE,
    )
    raw = _START_TOKEN_PATTERN.sub(
        lambda match: f"{match.group('kind').lower()}_<redacted>",
        raw,
    )
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw[:limit]


def _safe_payload_value(key: str, value: object):
    key_text = str(key or "")
    if key_text in _SENSITIVE_PAYLOAD_KEYS or key_text.lower() in {
        "initdata",
        "tgwebappdata",
    }:
        return {"redacted": True, "digest": _safe_digest(value)}
    if isinstance(value, dict):
        return {str(k): _safe_payload_value(str(k), v) for k, v in value.items()}
    if isinstance(value, list):
        return [_safe_payload_value("", item) for item in value[:8]]
    if isinstance(value, str):
        return sanitize_tianji_trial_secret_text(value, limit=120)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _safe_text(value, 120)


def _json_shape(value: object, depth: int = 0):
    if depth > 3:
        return "..."
    if isinstance(value, dict):
        return {
            str(key): _json_shape(child, depth + 1)
            for key, child in sorted(value.items(), key=lambda item: str(item[0]))[:20]
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


def _build_api_url(
    endpoint: str,
    api_base_url: str = TIANJI_TRIAL_MINIAPP_DEFAULT_API_BASE_URL,
) -> str:
    endpoint_path = TIANJI_TRIAL_MINIAPP_ENDPOINTS.get(str(endpoint or "").strip(), "")
    if not endpoint_path:
        raise ValueError(f"unknown tianji trial miniapp endpoint: {endpoint}")
    base_origin = _origin_from_url(str(api_base_url or "").strip())
    if not base_origin:
        raise ValueError("miniapp api base url missing")
    url = urljoin(f"{base_origin}/", endpoint_path.lstrip("/"))
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host not in TIANJI_TRIAL_ALLOWED_API_HOSTS:
        raise ValueError(f"tianji trial miniapp api host not allowed: {host}")
    if not parsed.path.startswith(TIANJI_TRIAL_MINIAPP_API_PATH_PREFIX):
        raise ValueError(f"tianji trial miniapp api path not allowed: {parsed.path}")
    return url


def _build_webview_url(
    token: str,
    api_base_url: str = TIANJI_TRIAL_MINIAPP_DEFAULT_API_BASE_URL,
) -> str:
    base_origin = _origin_from_url(str(api_base_url or "").strip())
    if not base_origin:
        raise ValueError("miniapp webview base url missing")
    url = (
        f"{base_origin}{TIANJI_TRIAL_MINIAPP_WEB_PATH}"
        f"?startapp={quote(str(token or '').strip(), safe='')}"
    )
    host = _host_from_url(url)
    if host not in TIANJI_TRIAL_ALLOWED_WEB_HOSTS:
        raise ValueError(f"tianji trial miniapp web host not allowed: {host}")
    return url


def build_tianji_trial_miniapp_request(
    endpoint: str,
    *,
    token: str,
    init_data: str,
    payload: Optional[dict] = None,
    api_base_url: str = TIANJI_TRIAL_MINIAPP_DEFAULT_API_BASE_URL,
) -> dict:
    clean_token = str(token or "").strip()
    if not clean_token or not _TRIAL_TOKEN_PATTERN.match(clean_token):
        raise ValueError("tianji trial miniapp token not allowed")
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
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
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
        "error": sanitize_tianji_trial_secret_text(error),
    }


def _emit_capture(
    capture_sink,
    *,
    request: dict,
    response: dict,
    step_key: str,
    source: str,
    elapsed_ms: int,
) -> None:
    if capture_sink is None:
        return
    safe_request = dict(request.get("safe_summary") or {})
    payload = dict(request.get("payload") or {})
    record = {
        "source": sanitize_tianji_trial_secret_text(source, limit=120),
        "step": str(step_key or safe_request.get("endpoint") or ""),
        "elapsed_ms": int(elapsed_ms or 0),
        "request": {
            **safe_request,
            "payload": {
                str(key): _safe_payload_value(str(key), value)
                for key, value in payload.items()
            },
            "payload_shape": _json_shape(payload),
        },
        "response": {
            "ok": bool(response.get("ok")),
            "status_code": int(response.get("status_code") or 0),
            "data_shape": _json_shape(response.get("data") or {}),
            "error": sanitize_tianji_trial_secret_text(response.get("error") or ""),
        },
    }
    if hasattr(capture_sink, "append"):
        capture_sink.append(record)
    else:
        capture_sink(record)


def execute_tianji_trial_miniapp_request(
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
            "error": sanitize_tianji_trial_secret_text(exc),
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


def _flow_result(
    ok: bool,
    status: str,
    *,
    error: object = "",
    data: Optional[dict] = None,
    proof: Optional[dict] = None,
    events: Optional[list] = None,
) -> dict:
    result = {
        "ok": bool(ok),
        "status": str(status or "unknown"),
        "error": sanitize_tianji_trial_secret_text(error),
        "data": data or {},
        "events": events or [],
    }
    if proof:
        result["proof"] = {
            "mode": proof.get("mode"),
            "durationMs": proof.get("durationMs"),
            "event_count": len(proof.get("events") or []),
            "moves": proof.get("moves"),
            "misses": proof.get("misses") or proof.get("mismatches") or 0,
        }
    return result


def _append_event(events: list, step: str, result: dict) -> None:
    events.append(
        {
            "step": step,
            "ok": bool(result.get("ok")),
            "status_code": int(result.get("status_code") or 0),
            "error": sanitize_tianji_trial_secret_text(result.get("error") or ""),
        }
    )


def _extract_challenge(data: object) -> dict:
    if not isinstance(data, dict):
        return {}
    if isinstance(data.get("challenge"), dict):
        return data["challenge"]
    nested = data.get("data")
    if isinstance(nested, dict) and isinstance(nested.get("challenge"), dict):
        return nested["challenge"]
    return {}


def _extract_trial_meta(data: object) -> dict:
    if not isinstance(data, dict):
        return {}
    if isinstance(data.get("trial"), dict):
        return data["trial"]
    nested = data.get("data")
    if isinstance(nested, dict) and isinstance(nested.get("trial"), dict):
        return nested["trial"]
    return {}


def _wait_for_trial_duration(proof: dict, sleeper) -> None:
    if sleeper is None:
        return
    duration_ms = max(int(proof.get("durationMs") or 0), 0)
    if duration_ms > 0:
        sleeper(duration_ms / 1000.0)


def run_tianji_trial_miniapp_flow(
    *,
    token: str,
    init_data: str,
    transport,
    sleeper=None,
    capture_sink=None,
    capture_source: str = "",
    challenge: Optional[dict] = None,
    trial: Optional[dict] = None,
) -> dict:
    if not str(token or "").strip():
        return _flow_result(False, "failed", error="token missing")
    if not str(init_data or "").strip():
        return _flow_result(False, "failed", error="initData missing")
    events: list[dict] = []
    current_challenge = dict(challenge or {})
    current_trial = dict(trial or {})
    if not current_challenge:
        start_request = build_tianji_trial_miniapp_request(
            "start",
            token=token,
            init_data=init_data,
        )
        start_result = execute_tianji_trial_miniapp_request(
            start_request,
            transport,
            capture_sink=capture_sink,
            capture_source=capture_source,
            step_key="start",
        )
        _append_event(events, "start", start_result)
        if not start_result.get("ok"):
            return _flow_result(False, "failed", error=start_result.get("error"), events=events)
        start_data = start_result.get("data") or {}
        current_challenge = _extract_challenge(start_data)
        current_trial = _extract_trial_meta(start_data)
    if not current_challenge:
        return _flow_result(False, "failed", error="challenge missing", events=events)
    try:
        proof = build_tianji_trial_proof(current_challenge)
    except Exception as exc:
        return _flow_result(False, "solver_failed", error=exc, data={"challenge_mode": current_challenge.get("mode")}, events=events)
    events.append(
        {
            "step": "build_proof",
            "ok": True,
            "mode": proof.get("mode"),
            "durationMs": proof.get("durationMs"),
        }
    )
    _wait_for_trial_duration(proof, sleeper)
    finish_request = build_tianji_trial_miniapp_request(
        "finish",
        token=token,
        init_data=init_data,
        payload={"trialProof": proof},
    )
    finish_result = execute_tianji_trial_miniapp_request(
        finish_request,
        transport,
        capture_sink=capture_sink,
        capture_source=capture_source,
        step_key="finish",
    )
    _append_event(events, "finish", finish_result)
    if not finish_result.get("ok"):
        return _flow_result(False, "failed", error=finish_result.get("error"), events=events, proof=proof)
    finish_data = dict(finish_result.get("data") or {})
    finish_data["challenge"] = {
        "challengeId": current_challenge.get("challengeId"),
        "mode": current_challenge.get("mode"),
        "trialIndex": current_challenge.get("trialIndex"),
        "difficulty": current_challenge.get("difficulty"),
        "difficultyLabel": current_challenge.get("difficultyLabel"),
    }
    finish_data["trial"] = current_trial
    return _flow_result(True, "settled", data=finish_data, events=events, proof=proof)


def run_tianji_trial_miniapp_batch_flow(
    *,
    token: str,
    init_data: str,
    transport,
    sleeper=None,
    capture_sink=None,
    capture_source: str = "",
    target_runs: int = TIANJI_TRIAL_DEFAULT_BATCH_RUNS,
) -> dict:
    target = max(1, min(TIANJI_TRIAL_DEFAULT_BATCH_RUNS, _miniapp_int(target_runs, TIANJI_TRIAL_DEFAULT_BATCH_RUNS)))
    round_results: list[dict] = []
    next_challenge: Optional[dict] = None
    next_trial: Optional[dict] = None
    for round_number in range(1, target + 1):
        result = run_tianji_trial_miniapp_flow(
            token=token,
            init_data=init_data,
            transport=transport,
            sleeper=sleeper,
            capture_sink=capture_sink,
            capture_source=f"{capture_source}:round-{round_number}",
            challenge=next_challenge,
            trial=next_trial,
        )
        round_results.append(result)
        if not result.get("ok"):
            return {
                "ok": False,
                "status": str(result.get("status") or "failed"),
                "error": sanitize_tianji_trial_secret_text(result.get("error") or ""),
                "round_results": round_results,
            }
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        next_challenge = data.get("nextChallenge") if isinstance(data.get("nextChallenge"), dict) else None
        next_trial = data.get("nextTrial") if isinstance(data.get("nextTrial"), dict) else None
        if not next_challenge:
            break
    return {
        "ok": True,
        "status": "settled",
        "error": "",
        "round_results": round_results,
    }


def _extract_init_data_from_webview_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    for key, value in _parse_pairs(parsed.fragment):
        if key == "tgWebAppData":
            return unquote(value)
    return ""


async def request_tianji_trial_miniapp_init_data(
    client: object,
    *,
    token: str,
    webview_url: str = "",
) -> str:
    clean_token = str(token or "").strip()
    if not clean_token or not _TRIAL_TOKEN_PATTERN.match(clean_token):
        raise ValueError("tianji trial miniapp token not allowed")
    host = _host_from_url(str(webview_url or ""))
    if host and host not in TIANJI_TRIAL_ALLOWED_WEB_HOSTS:
        raise ValueError(f"tianji trial miniapp web host not allowed: {host}")
    bot = await client.get_entity(TIANJI_TRIAL_MINIAPP_DEFAULT_BOT_USERNAME)
    bot_input = await client.get_input_entity(bot)
    launch_url = _build_webview_url(clean_token)
    result = await client(
        functions.messages.RequestWebViewRequest(
            peer=bot_input,
            bot=bot_input,
            platform="android",
            url=launch_url,
            start_param=clean_token,
        )
    )
    result_url = getattr(result, "url", "") or ""
    try:
        result_path = urlsplit(result_url).path
    except ValueError:
        result_path = ""
    if result_path != TIANJI_TRIAL_MINIAPP_WEB_PATH:
        raise RuntimeError("WebView URL 不是天机试炼 MiniApp")
    init_data = _extract_init_data_from_webview_url(result_url)
    if not init_data:
        raise RuntimeError("WebView URL 缺少 tgWebAppData")
    return init_data


async def run_tianji_trial_miniapp_production_flow(
    client: object,
    *,
    token: str,
    webview_url: str = "",
    transport=None,
    sleeper=None,
    capture_sink=None,
    capture_source: str = "",
    target_runs: int = TIANJI_TRIAL_DEFAULT_BATCH_RUNS,
) -> dict:
    try:
        init_data = await request_tianji_trial_miniapp_init_data(
            client,
            token=token,
            webview_url=webview_url,
        )
        return await asyncio.to_thread(
            run_tianji_trial_miniapp_batch_flow,
            token=token,
            init_data=init_data,
            transport=transport or _urllib_transport,
            sleeper=sleeper or time.sleep,
            capture_sink=capture_sink,
            capture_source=capture_source,
            target_runs=target_runs,
        )
    except Exception as exc:
        return _flow_result(False, "failed", error=exc)


async def run_tianji_trial_public_miniapp_production_flow(
    client: object,
    *,
    discovery_storage: object = None,
    transport=None,
    sleeper=None,
    capture_sink=None,
    capture_source: str = "",
    target_runs: int = TIANJI_TRIAL_DEFAULT_BATCH_RUNS,
    progress_callback=None,
) -> dict:
    try:
        if discovery_storage is not None:
            discovery = await estate_miniapp.resolve_estate_public_miniapp_launch(
                client,
                discovery_storage,
            )
            if not discovery.get("ok"):
                raise RuntimeError(
                    str(discovery.get("error") or "洞府公共入口未找到")
                )
            estate_launch = (
                discovery.get("launch")
                if isinstance(discovery.get("launch"), dict)
                else {}
            )
        else:
            estate_launch = await estate_miniapp.fetch_estate_public_miniapp_launch(
                client
            )
        if progress_callback is not None:
            progress_callback()
        init_data = await estate_miniapp.request_estate_miniapp_init_data(
            client,
            token=estate_launch.get("token"),
            webview_url=estate_launch.get("webview_url"),
            bot_username=estate_launch.get("bot_username"),
        )
        request = estate_miniapp.build_estate_miniapp_request(
            "start",
            token=estate_launch.get("token"),
            init_data=init_data,
        )
        start_result = await asyncio.to_thread(
            estate_miniapp.execute_estate_miniapp_request,
            request,
            transport or estate_miniapp._urllib_transport,
        )
        if not start_result.get("ok"):
            return _flow_result(False, "failed", error=start_result.get("error"))
        trial_launch = extract_public_tianji_trial_launch(start_result.get("data") or {})
        if not trial_launch:
            return _flow_result(False, "failed", error="洞府公共入口未返回天机试炼链接")
        result = await asyncio.to_thread(
            run_tianji_trial_miniapp_batch_flow,
            token=trial_launch.get("token"),
            init_data=init_data,
            transport=transport or _urllib_transport,
            sleeper=sleeper or time.sleep,
            capture_sink=capture_sink,
            capture_source=capture_source,
            target_runs=target_runs,
        )
        result = dict(result)
        result["entry"] = trial_launch.get("entry")
        return result
    except Exception as exc:
        return _flow_result(False, "failed", error=exc)
