import asyncio
import hashlib
import json
import re
import time
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qsl, quote, unquote, urljoin, urlsplit
import urllib.request

from telethon import functions
from tg_game.features.estate import biz_estate_miniapp as estate_miniapp

from .biz_xinggong_star_board import (
    XINGGONG_STARBOARD_DEFAULT_STAR,
    XINGGONG_STAR_DURATIONS,
    normalize_starboard_target,
)


XINGGONG_STARBOARD_COMMAND = ".观星台"
XINGGONG_STARBOARD_MINIAPP_DEFAULT_BOT_USERNAME = "fanrenxiuxian_bot"
XINGGONG_STARBOARD_MINIAPP_DEFAULT_API_BASE_URL = "https://asc.aiopenai.app"
XINGGONG_STARBOARD_MINIAPP_WEB_PATH = "/miniapp/xianxia-sect-farm"
XINGGONG_STARBOARD_MINIAPP_API_PATH_PREFIX = "/api/miniapp/xianxia-sect-farm/"
XINGGONG_STARBOARD_MINIAPP_ENDPOINTS = {
    "start": f"{XINGGONG_STARBOARD_MINIAPP_API_PATH_PREFIX}start",
    "action": f"{XINGGONG_STARBOARD_MINIAPP_API_PATH_PREFIX}action",
}
XINGGONG_STARBOARD_ALLOWED_WEB_HOSTS = {"t.me", "telegram.me", "asc.aiopenai.app"}
XINGGONG_STARBOARD_ALLOWED_API_HOSTS = {"asc.aiopenai.app"}
XINGGONG_STARBOARD_REQUEST_TTL_SECONDS = 30 * 60
XINGGONG_STARBOARD_HISTORY_LIMIT = 24
XINGGONG_STARBOARD_HISTORY_TZ = timezone(timedelta(hours=8))
XINGGONG_STARBOARD_SAFETY_BOUNDARY = (
    "自动星辰采集通过公共洞府入口获取星宫 MiniApp，临时请求 Telegram WebView，"
    "随后只调用洞府 start/details/external，以及 xianxia-sect-farm/start 与 action；"
    "不保存 initData/tgWebAppData/hash/user/raw URL。"
)

_STARBOARD_KEYWORDS = ("星宫", "观星台", "灵圃", "引星", "xianxia-sect-farm", "farm")
_URL_PATTERN = re.compile(r"(?:https?|tg)://[^\s<>'\"）)]+", re.IGNORECASE)
_FARM_TOKEN_PATTERN = re.compile(r"^(?:farm_)?[A-Za-z0-9_-]{4,160}$", re.IGNORECASE)
_START_TOKEN_PATTERN = re.compile(r"\b(?P<kind>farm)_[A-Za-z0-9_-]{4,}\b", re.IGNORECASE)
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
_NON_FATAL_ACTION_ERRORS = {"nothing_to_soothe", "nothing_ready"}
_SOOTHE_STATUSES = {"元磁紊乱", "星光黯淡"}
_COLLECT_STATUSES = {"可收集", "精华已成", "精华已成 · 待收集"}
_REWARD_TEXT_PATTERN = re.compile(
    r"(?P<name>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9_·]{0,24})\s*(?:[xX*×:：]\s*)?(?P<qty>\d+)"
)


def _safe_text(value: object, max_length: int = 80) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    text = _URL_PATTERN.sub("[url]", text)
    if len(text) > max_length:
        return f"{text[: max_length - 1]}..."
    return text


def _safe_digest(value: object) -> str:
    text = str(value or "")
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def sanitize_xinggong_starboard_secret_text(text: object, *, limit: int = 220) -> str:
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
    if lowered.startswith("farm"):
        return "farm"
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
        _safe_digest(param),
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


def _looks_like_starboard_entry(button_text: str, url: str, text: str, summary: dict) -> bool:
    haystack = " ".join(
        [
            str(button_text or ""),
            str(url or ""),
            str(text or ""),
            str(summary.get("start_param_kind") or ""),
        ]
    ).lower()
    return any(keyword.lower() in haystack for keyword in _STARBOARD_KEYWORDS)


def looks_like_xinggong_starboard_prompt(text: object) -> bool:
    normalized = str(text or "")
    return ("观星台" in normalized or "星宫" in normalized) and any(
        marker in normalized for marker in ("进入灵圃", "牵引星辰", "收取星辰精华", "点击下方")
    )


def extract_xinggong_starboard_miniapp_entry(event: object, text: str = "") -> Optional[dict]:
    for button_text, url in _iter_button_links(event):
        summary = _summarize_url(button_text, url)
        if summary and _looks_like_starboard_entry(button_text, url, text, summary):
            return summary
    for match in _URL_PATTERN.finditer(str(text or "")):
        url = match.group(0)
        summary = _summarize_url("", url)
        if summary and _looks_like_starboard_entry("", url, text, summary):
            return summary
    return None


def extract_xinggong_starboard_miniapp_launch(event: object, text: str = "") -> dict:
    for button_text, url in _iter_button_links(event):
        summary = _summarize_url(button_text, url)
        if not summary or not _looks_like_starboard_entry(button_text, url, text, summary):
            continue
        token = _start_param_from_url(url)
        if token and _FARM_TOKEN_PATTERN.match(token):
            return {"token": token, "webview_url": url, "entry": summary}
    return {}


def extract_public_xinggong_starboard_launch(data: object) -> dict:
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
            if not isinstance(app, dict) or not bool(app.get("available", True)):
                continue
            url = urljoin(
                f"{XINGGONG_STARBOARD_MINIAPP_DEFAULT_API_BASE_URL}/",
                str(app.get("url") or "").strip(),
            )
            try:
                path = urlsplit(url).path
            except ValueError:
                continue
            if path != XINGGONG_STARBOARD_MINIAPP_WEB_PATH:
                continue
            summary = _summarize_url(
                str(app.get("buttonText") or app.get("title") or ""),
                url,
            )
            token = _start_param_from_url(url)
            if summary and token and _FARM_TOKEN_PATTERN.match(token):
                return {"token": token, "webview_url": url, "entry": summary}
    return {}


def _build_api_url(
    endpoint: str,
    api_base_url: str = XINGGONG_STARBOARD_MINIAPP_DEFAULT_API_BASE_URL,
) -> str:
    endpoint_path = XINGGONG_STARBOARD_MINIAPP_ENDPOINTS.get(str(endpoint or "").strip(), "")
    if not endpoint_path:
        raise ValueError(f"unknown xinggong starboard miniapp endpoint: {endpoint}")
    base_origin = _origin_from_url(str(api_base_url or "").strip())
    if not base_origin:
        raise ValueError("miniapp api base url missing")
    url = urljoin(f"{base_origin}/", endpoint_path.lstrip("/"))
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host not in XINGGONG_STARBOARD_ALLOWED_API_HOSTS:
        raise ValueError(f"xinggong starboard miniapp api host not allowed: {host}")
    if not parsed.path.startswith(XINGGONG_STARBOARD_MINIAPP_API_PATH_PREFIX):
        raise ValueError(f"xinggong starboard miniapp api path not allowed: {parsed.path}")
    return url


def _build_webview_url(
    token: str,
    api_base_url: str = XINGGONG_STARBOARD_MINIAPP_DEFAULT_API_BASE_URL,
) -> str:
    base_origin = _origin_from_url(str(api_base_url or "").strip())
    if not base_origin:
        raise ValueError("miniapp webview base url missing")
    url = (
        f"{base_origin}{XINGGONG_STARBOARD_MINIAPP_WEB_PATH}"
        f"?startapp={quote(str(token or '').strip(), safe='')}"
    )
    host = _host_from_url(url)
    if host not in XINGGONG_STARBOARD_ALLOWED_WEB_HOSTS:
        raise ValueError(f"xinggong starboard miniapp web host not allowed: {host}")
    return url


def build_xinggong_starboard_miniapp_request(
    endpoint: str,
    *,
    token: str,
    init_data: str,
    payload: Optional[dict] = None,
    api_base_url: str = XINGGONG_STARBOARD_MINIAPP_DEFAULT_API_BASE_URL,
) -> dict:
    clean_token = str(token or "").strip()
    if not clean_token or not _FARM_TOKEN_PATTERN.match(clean_token):
        raise ValueError("xinggong starboard miniapp token not allowed")
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
        "error": sanitize_xinggong_starboard_secret_text(error),
    }


def execute_xinggong_starboard_miniapp_request(request: dict, transport) -> dict:
    if transport is None:
        raise ValueError("miniapp transport missing")
    try:
        status_code, body = _coerce_response(transport(request))
        return _classify_http_response(status_code, body)
    except Exception as exc:
        return {
            "ok": False,
            "status_code": 0,
            "data": {},
            "error": sanitize_xinggong_starboard_secret_text(exc),
        }


def _int_or_zero(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _first_text(*values: object) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _coerce_reward_quantity(value: object) -> int:
    try:
        return max(int(float(value or 0)), 0)
    except (TypeError, ValueError):
        return 0


def _normalize_reward_items(value: object) -> list[dict]:
    items: list[dict] = []
    if isinstance(value, dict):
        name = _first_text(
            value.get("name"),
            value.get("item"),
            value.get("itemName"),
            value.get("material"),
            value.get("label"),
        )
        quantity = _coerce_reward_quantity(
            value.get("quantity")
            or value.get("count")
            or value.get("amount")
            or value.get("qty")
            or value.get("value")
        )
        if name and quantity > 0:
            items.append({"name": _safe_text(name, 40), "quantity": quantity})
            return items
        for key, raw_qty in value.items():
            quantity = _coerce_reward_quantity(raw_qty)
            if quantity > 0:
                items.append({"name": _safe_text(key, 40), "quantity": quantity})
        return items
    if isinstance(value, list):
        for item in value:
            items.extend(_normalize_reward_items(item))
        return items
    if isinstance(value, str):
        for match in _REWARD_TEXT_PATTERN.finditer(value):
            name = _safe_text(match.group("name"), 40)
            quantity = _coerce_reward_quantity(match.group("qty"))
            if name and quantity > 0 and name not in {"消耗修为", "引星盘"}:
                items.append({"name": name, "quantity": quantity})
    return items


def _collect_reward_items(action_data: dict) -> list[dict]:
    for key in (
        "rewards",
        "rewardItems",
        "reward_items",
        "items",
        "materials",
        "drops",
        "loot",
        "gains",
    ):
        rewards = _normalize_reward_items(action_data.get(key))
        if rewards:
            return _merge_reward_items(rewards)
    return _merge_reward_items(
        _normalize_reward_items(action_data.get("message") or "")
    )


def _merge_reward_items(items: list[dict]) -> list[dict]:
    totals: dict[str, int] = {}
    order: list[str] = []
    for item in items:
        name = _safe_text(item.get("name") or "", 40)
        quantity = _coerce_reward_quantity(item.get("quantity"))
        if not name or quantity <= 0:
            continue
        if name not in totals:
            order.append(name)
            totals[name] = 0
        totals[name] += quantity
    return [{"name": name, "quantity": totals[name]} for name in order]


def _reward_summary(items: list[dict]) -> str:
    rewards = _merge_reward_items(items)
    return "、".join(
        f"{item['name']}×{item['quantity']}" for item in rewards
    )


def _reward_total(items: list[dict]) -> int:
    return sum(_coerce_reward_quantity(item.get("quantity")) for item in items)


def _domain_from_data(data: object) -> dict:
    root = _as_dict(data)
    if isinstance(root.get("domain"), dict):
        return root["domain"]
    nested = root.get("data")
    if isinstance(nested, dict) and isinstance(nested.get("domain"), dict):
        return nested["domain"]
    return {}


def _plot_sort_key(value: object) -> int:
    try:
        return int(str(value or ""))
    except (TypeError, ValueError):
        return 9999


def _domain_plot_items(domain: object) -> list[tuple[str, dict]]:
    raw = _as_dict(domain).get("plots")
    items: list[tuple[str, dict]] = []
    if isinstance(raw, dict):
        for key, value in raw.items():
            plot = _as_dict(value)
            plot.setdefault("key", str(key))
            items.append((str(key), plot))
    elif isinstance(raw, list):
        for index, value in enumerate(raw, start=1):
            plot = _as_dict(value)
            key = str(plot.get("key") or plot.get("plotKey") or index).strip()
            if key:
                items.append((key, plot))
    return sorted(items, key=lambda item: _plot_sort_key(item[0]))


def _domain_options(domain: object) -> list[dict]:
    options = []
    for item in _as_list(_as_dict(domain).get("options")):
        if not isinstance(item, dict):
            continue
        name = _first_text(item.get("name"), item.get("id"))
        if not name:
            continue
        options.append(
            {
                "id": _safe_text(item.get("id") or name, 40),
                "name": _safe_text(name, 40),
                "cost": _int_or_zero(item.get("cost")),
                "hours": float(item.get("hours") or 0),
                "produces": _safe_text(item.get("produces") or "", 160),
            }
        )
    return options


def _duration_seconds_for_star(star_name: str, options: list[dict]) -> int:
    for option in options:
        if option.get("name") == star_name or option.get("id") == star_name:
            return int(float(option.get("hours") or 0) * 3600)
    return int(XINGGONG_STAR_DURATIONS.get(star_name, 0))


def build_xinggong_star_platform_from_domain(domain: object, *, now_ts: Optional[float] = None) -> dict:
    domain_data = _as_dict(domain)
    now = float(now_ts if now_ts is not None else time.time())
    options = _domain_options(domain_data)
    plots: dict[str, Optional[dict]] = {}
    for key, plot in _domain_plot_items(domain_data):
        if bool(plot.get("empty")):
            plots[key] = None
            continue
        star_name = _first_text(plot.get("star_name"), plot.get("starName"), plot.get("name"))
        status = _first_text(plot.get("statusLabel"), plot.get("status"))
        remaining_seconds = _int_or_zero(
            plot.get("remainingSeconds")
            or plot.get("remaining_seconds")
            or plot.get("remaining")
        )
        duration_seconds = _duration_seconds_for_star(star_name, options)
        start_time = ""
        if duration_seconds > 0:
            elapsed = max(duration_seconds - remaining_seconds, 0)
            start_ts = now - elapsed
            start_time = datetime.fromtimestamp(start_ts, tz=timezone.utc).isoformat()
        plots[key] = {
            "star_name": star_name,
            "status": status,
            "start_time": start_time,
            "miniapp": {
                "key": key,
                "remaining_seconds": remaining_seconds,
                "remaining_text": _safe_text(plot.get("remainingText") or "", 40),
                "status_label": _safe_text(plot.get("statusLabel") or status, 40),
            },
        }
    return {
        "mode": _safe_text(domain_data.get("mode") or "", 20),
        "title": _safe_text(domain_data.get("title") or "", 80),
        "sect_name": _safe_text(domain_data.get("sectName") or "", 40),
        "size": _int_or_zero(domain_data.get("size")) or len(plots),
        "options": options,
        "plots": plots,
        "miniapp_synced_at": now,
    }


def _domain_requires_mode_stars(domain: dict) -> Optional[str]:
    mode = str(domain.get("mode") or "").strip()
    if mode != "stars":
        return f"unexpected miniapp mode: {mode or '-'}"
    sect_name = str(domain.get("sectName") or "").strip()
    if sect_name != "星宫":
        return f"unexpected miniapp sect: {sect_name or '-'}"
    return None


def _plot_status(plot: dict) -> str:
    return _first_text(plot.get("statusLabel"), plot.get("status"))


def _plot_is_empty_or_ready(plot: dict) -> bool:
    if bool(plot.get("empty")):
        return True
    status = _plot_status(plot)
    name = _first_text(plot.get("name"), plot.get("starName"), plot.get("star_name"))
    return status in {"空闲", "星轨已校准", "READY"} or not name


def _domain_needs_soothe(domain: dict) -> bool:
    for _key, plot in _domain_plot_items(domain):
        status = _plot_status(plot)
        if status in _SOOTHE_STATUSES or "需安抚" in status:
            return True
    return False


def _domain_has_collectable(domain: dict) -> bool:
    for _key, plot in _domain_plot_items(domain):
        status = _plot_status(plot)
        if status in _COLLECT_STATUSES or "待收集" in status:
            return True
    return False


def _domain_pull_keys(domain: dict) -> list[str]:
    keys = []
    for key, plot in _domain_plot_items(domain):
        if _plot_is_empty_or_ready(plot):
            keys.append(key)
    return keys


def _action_result(data: object) -> dict:
    root = _as_dict(data)
    result = root.get("actionResult")
    if isinstance(result, dict):
        return result
    nested = root.get("data")
    if isinstance(nested, dict) and isinstance(nested.get("actionResult"), dict):
        return nested["actionResult"]
    return {}


def _append_event(events: list, step: str, result: dict, *, action_result: Optional[dict] = None) -> None:
    action_data = action_result or {}
    events.append(
        {
            "step": step,
            "ok": bool(result.get("ok")),
            "status_code": int(result.get("status_code") or 0),
            "action_ok": action_data.get("ok") if action_data else None,
            "action_error": sanitize_xinggong_starboard_secret_text(action_data.get("error") or ""),
            "message": sanitize_xinggong_starboard_secret_text(action_data.get("message") or "", limit=160),
            "error": sanitize_xinggong_starboard_secret_text(result.get("error") or ""),
        }
    )


def _action_error(action_data: dict) -> str:
    return str(action_data.get("error") or "").strip()


def _action_failed(result: dict, action_data: dict) -> bool:
    if not result.get("ok"):
        return True
    if action_data and action_data.get("ok") is False:
        return _action_error(action_data) not in _NON_FATAL_ACTION_ERRORS
    return False


def _run_action(
    *,
    token: str,
    init_data: str,
    transport,
    action: str,
    plot_key: str = "",
    star_name: str = "",
) -> dict:
    payload = {"action": action, "plotKey": str(plot_key or "")}
    if star_name:
        payload["starName"] = star_name
    request = build_xinggong_starboard_miniapp_request(
        "action",
        token=token,
        init_data=init_data,
        payload=payload,
    )
    return execute_xinggong_starboard_miniapp_request(request, transport)


def _flow_result(
    ok: bool,
    status: str,
    *,
    target_star: str,
    error: object = "",
    star_platform: Optional[dict] = None,
    events: Optional[list] = None,
    pulled_slots: Optional[list[str]] = None,
    soothed: bool = False,
    collected: bool = False,
    reward_items: Optional[list[dict]] = None,
) -> dict:
    now = time.time()
    safe_error = sanitize_xinggong_starboard_secret_text(error)
    pulled = list(pulled_slots or [])
    rewards = _merge_reward_items(list(reward_items or []))
    if ok:
        if status == "synced":
            message = "观星台状态已同步。"
        elif status == "idle":
            message = "本轮星辰采集无需操作。"
        elif pulled:
            message = f"星辰采集完成：已牵星 {len(pulled)} 个槽位，目标 {target_star}。"
        else:
            actions = []
            if soothed:
                actions.append("已安抚")
            if collected:
                actions.append("已收集")
            message = "星辰采集完成：" + "、".join(actions) + "。" if actions else "星辰采集完成。"
    else:
        message = safe_error or "星辰采集失败。"
    run = {
        "status": status,
        "level": "success" if ok else "error",
        "message": message,
        "target_star": target_star,
        "pulled_slots": pulled,
        "soothed": bool(soothed),
        "collected": bool(collected),
        "reward_items": rewards,
        "reward_summary": _reward_summary(rewards),
        "reward_total": _reward_total(rewards),
        "error": safe_error,
        "updated_at": now,
        "time_display": datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M:%S"),
        "events": list(events or [])[-16:],
        "safety_boundary": XINGGONG_STARBOARD_SAFETY_BOUNDARY,
    }
    return {
        "ok": bool(ok),
        "status": status,
        "error": safe_error,
        "star_platform": star_platform or {},
        "run": run,
        "events": list(events or [])[-16:],
    }


def run_xinggong_starboard_snapshot_flow(*, token: str, init_data: str, transport) -> dict:
    if not str(token or "").strip():
        return _flow_result(False, "failed", target_star=XINGGONG_STARBOARD_DEFAULT_STAR, error="token missing")
    if not str(init_data or "").strip():
        return _flow_result(False, "failed", target_star=XINGGONG_STARBOARD_DEFAULT_STAR, error="initData missing")
    events: list[dict] = []
    request = build_xinggong_starboard_miniapp_request("start", token=token, init_data=init_data)
    start_result = execute_xinggong_starboard_miniapp_request(request, transport)
    _append_event(events, "start", start_result)
    if not start_result.get("ok"):
        return _flow_result(False, "failed", target_star=XINGGONG_STARBOARD_DEFAULT_STAR, error=start_result.get("error"), events=events)
    domain = _domain_from_data(start_result.get("data") or {})
    mode_error = _domain_requires_mode_stars(domain)
    if mode_error:
        return _flow_result(False, "failed", target_star=XINGGONG_STARBOARD_DEFAULT_STAR, error=mode_error, events=events)
    return _flow_result(
        True,
        "synced",
        target_star=XINGGONG_STARBOARD_DEFAULT_STAR,
        star_platform=build_xinggong_star_platform_from_domain(domain),
        events=events,
    )


def run_xinggong_starboard_miniapp_flow(
    *,
    token: str,
    init_data: str,
    transport,
    target_star: str = XINGGONG_STARBOARD_DEFAULT_STAR,
) -> dict:
    target = normalize_starboard_target(target_star)
    if not str(token or "").strip():
        return _flow_result(False, "failed", target_star=target, error="token missing")
    if not str(init_data or "").strip():
        return _flow_result(False, "failed", target_star=target, error="initData missing")

    events: list[dict] = []
    pulled_slots: list[str] = []
    soothed = False
    collected = False
    reward_items: list[dict] = []
    request = build_xinggong_starboard_miniapp_request("start", token=token, init_data=init_data)
    start_result = execute_xinggong_starboard_miniapp_request(request, transport)
    _append_event(events, "start", start_result)
    if not start_result.get("ok"):
        return _flow_result(False, "failed", target_star=target, error=start_result.get("error"), events=events)

    domain = _domain_from_data(start_result.get("data") or {})
    mode_error = _domain_requires_mode_stars(domain)
    if mode_error:
        return _flow_result(False, "failed", target_star=target, error=mode_error, events=events)

    if _domain_needs_soothe(domain):
        soothe_result = _run_action(
            token=token,
            init_data=init_data,
            transport=transport,
            action="soothe",
        )
        soothe_action = _action_result(soothe_result.get("data") or {})
        _append_event(events, "soothe", soothe_result, action_result=soothe_action)
        if _action_failed(soothe_result, soothe_action):
            return _flow_result(
                False,
                "failed",
                target_star=target,
                error=soothe_action.get("error") or soothe_result.get("error"),
                star_platform=build_xinggong_star_platform_from_domain(domain),
                events=events,
            )
        soothed = not soothe_action or soothe_action.get("ok") is not False
        domain = _domain_from_data(soothe_result.get("data") or {}) or domain

    if _domain_has_collectable(domain):
        collect_result = _run_action(
            token=token,
            init_data=init_data,
            transport=transport,
            action="collect",
        )
        collect_action = _action_result(collect_result.get("data") or {})
        _append_event(events, "collect", collect_result, action_result=collect_action)
        if _action_failed(collect_result, collect_action):
            return _flow_result(
                False,
                "failed",
                target_star=target,
                error=collect_action.get("error") or collect_result.get("error"),
                star_platform=build_xinggong_star_platform_from_domain(domain),
                events=events,
                soothed=soothed,
            )
        collected = not collect_action or collect_action.get("ok") is not False
        if collected:
            reward_items = _collect_reward_items(collect_action)
        domain = _domain_from_data(collect_result.get("data") or {}) or domain

    for plot_key in _domain_pull_keys(domain):
        pull_result = _run_action(
            token=token,
            init_data=init_data,
            transport=transport,
            action="pull",
            plot_key=plot_key,
            star_name=target,
        )
        pull_action = _action_result(pull_result.get("data") or {})
        _append_event(events, f"pull:{plot_key}", pull_result, action_result=pull_action)
        if _action_failed(pull_result, pull_action):
            return _flow_result(
                False,
                "failed",
                target_star=target,
                error=pull_action.get("error") or pull_result.get("error"),
                star_platform=build_xinggong_star_platform_from_domain(domain),
                events=events,
                pulled_slots=pulled_slots,
                soothed=soothed,
                collected=collected,
            )
        if not pull_action or pull_action.get("ok") is not False:
            pulled_slots.append(str(plot_key))
        domain = _domain_from_data(pull_result.get("data") or {}) or domain

    status = "completed" if (soothed or collected or pulled_slots) else "idle"
    return _flow_result(
        True,
        status,
        target_star=target,
        star_platform=build_xinggong_star_platform_from_domain(domain),
        events=events,
        pulled_slots=pulled_slots,
        soothed=soothed,
        collected=collected,
        reward_items=reward_items,
    )


def build_xinggong_starboard_request(
    *,
    chat_id: object = "",
    thread_id: object = None,
    chat_type: str = "group",
    bot_username: str = XINGGONG_STARBOARD_MINIAPP_DEFAULT_BOT_USERNAME,
    target_star: str = XINGGONG_STARBOARD_DEFAULT_STAR,
    run_mode: str = "auto",
) -> dict:
    now = time.time()
    normalized_run_mode = "snapshot" if str(run_mode or "").strip() == "snapshot" else "auto"
    return {
        "status": "queued",
        "requested_at": now,
        "chat_id": _int_or_zero(chat_id),
        "thread_id": _int_or_zero(thread_id) if thread_id not in (None, "") else None,
        "chat_type": _safe_text(chat_type or "group", 20) or "group",
        "bot_username": _safe_text(
            bot_username or XINGGONG_STARBOARD_MINIAPP_DEFAULT_BOT_USERNAME,
            64,
        )
        or XINGGONG_STARBOARD_MINIAPP_DEFAULT_BOT_USERNAME,
        "target_star": normalize_starboard_target(target_star),
        "run_mode": normalized_run_mode,
    }


def queue_xinggong_starboard_request(
    payload: object,
    *,
    chat_id: object = "",
    thread_id: object = None,
    chat_type: str = "group",
    bot_username: str = XINGGONG_STARBOARD_MINIAPP_DEFAULT_BOT_USERNAME,
    target_star: str = XINGGONG_STARBOARD_DEFAULT_STAR,
    run_mode: str = "auto",
) -> dict:
    updated = deepcopy(payload if isinstance(payload, dict) else {})
    board = dict(updated.get("xinggong_starboard") or {})
    request = build_xinggong_starboard_request(
        chat_id=chat_id,
        thread_id=thread_id,
        chat_type=chat_type,
        bot_username=bot_username,
        target_star=target_star,
        run_mode=run_mode,
    )
    board["miniapp_request"] = request
    board["miniapp_run"] = {
        "status": "queued",
        "level": "info",
        "message": (
            "观星台状态同步已排队，等待公共洞府入口。"
            if request["run_mode"] == "snapshot"
            else f"自动星辰采集已排队，目标 {request['target_star']}，等待公共洞府入口。"
        ),
        "target_star": request["target_star"],
        "updated_at": request["requested_at"],
        "time_display": datetime.fromtimestamp(request["requested_at"]).strftime("%Y-%m-%d %H:%M:%S"),
        "error": "",
        "events": [],
        "safety_boundary": XINGGONG_STARBOARD_SAFETY_BOUNDARY,
    }
    updated["xinggong_starboard"] = board
    return updated


def get_pending_xinggong_starboard_request(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    board = payload.get("xinggong_starboard") if isinstance(payload.get("xinggong_starboard"), dict) else {}
    request = board.get("miniapp_request") if isinstance(board.get("miniapp_request"), dict) else {}
    if str(request.get("status") or "") not in {"queued", "running"}:
        return {}
    requested_at = float(request.get("requested_at") or 0)
    if requested_at and time.time() - requested_at > XINGGONG_STARBOARD_REQUEST_TTL_SECONDS:
        return {}
    return request


def merge_xinggong_starboard_payload(
    payload: object,
    *,
    entry: Optional[dict] = None,
    star_platform: Optional[dict] = None,
    run: Optional[dict] = None,
    request: Optional[dict] = None,
    clear_request: bool = False,
) -> dict:
    updated = deepcopy(payload if isinstance(payload, dict) else {})
    board = dict(updated.get("xinggong_starboard") or {})
    if entry is not None:
        board["miniapp_entry"] = entry
    if run is not None:
        board["miniapp_run"] = build_xinggong_starboard_run_view(run)
        board["miniapp_history"] = _merge_today_history(
            board.get("miniapp_history"),
            board["miniapp_run"],
        )
    if request is not None:
        board["miniapp_request"] = dict(request)
    elif clear_request:
        board.pop("miniapp_request", None)
    if star_platform is not None:
        updated["star_platform"] = star_platform
        board["miniapp_snapshot"] = {
            "mode": star_platform.get("mode"),
            "title": star_platform.get("title"),
            "sect_name": star_platform.get("sect_name"),
            "size": star_platform.get("size"),
            "synced_at": star_platform.get("miniapp_synced_at"),
        }
    updated["xinggong_starboard"] = board
    return updated


def build_xinggong_starboard_run_view(value: object) -> dict:
    if not isinstance(value, dict) or not value:
        return {}
    level = _safe_text(value.get("level") or ("success" if value.get("status") in {"synced", "completed", "idle"} else "error"), 20)
    reward_items = _merge_reward_items(
        _normalize_reward_items(value.get("reward_items") or value.get("rewards") or [])
    )
    return {
        "status": _safe_text(value.get("status") or "", 40),
        "level": level,
        "message": sanitize_xinggong_starboard_secret_text(value.get("message") or value.get("error") or ""),
        "target_star": normalize_starboard_target(value.get("target_star")),
        "pulled_slots": [str(item) for item in (value.get("pulled_slots") or [])],
        "soothed": bool(value.get("soothed")),
        "collected": bool(value.get("collected")),
        "reward_items": reward_items,
        "reward_summary": _safe_text(
            value.get("reward_summary") or _reward_summary(reward_items),
            160,
        ),
        "reward_total": _coerce_reward_quantity(
            value.get("reward_total") or _reward_total(reward_items)
        ),
        "error": sanitize_xinggong_starboard_secret_text(value.get("error") or ""),
        "updated_at": float(value.get("updated_at") or 0),
        "time_display": _safe_text(value.get("time_display") or "", 40),
        "events": list(value.get("events") or [])[-16:],
        "safety_boundary": XINGGONG_STARBOARD_SAFETY_BOUNDARY,
    }


def _history_day_key(timestamp: object = None) -> str:
    ts = float(timestamp if timestamp not in (None, "") else time.time())
    return datetime.fromtimestamp(ts, tz=XINGGONG_STARBOARD_HISTORY_TZ).strftime(
        "%Y-%m-%d"
    )


def _build_history_entry(value: object) -> dict:
    if isinstance(value, dict) and value.get("day_key"):
        reward_items = _merge_reward_items(
            _normalize_reward_items(value.get("reward_items") or [])
        )
        pulled_slots = [str(item) for item in (value.get("pulled_slots") or [])]
        return {
            "day_key": _safe_text(value.get("day_key") or "", 20),
            "updated_at": float(value.get("updated_at") or 0),
            "time_display": _safe_text(value.get("time_display") or "", 40),
            "target_star": normalize_starboard_target(value.get("target_star")),
            "action_summary": _safe_text(value.get("action_summary") or "", 80),
            "message": sanitize_xinggong_starboard_secret_text(
                value.get("message") or ""
            ),
            "pulled_slots": pulled_slots,
            "pulled_count": len(pulled_slots),
            "collected": bool(value.get("collected")),
            "soothed": bool(value.get("soothed")),
            "reward_items": reward_items,
            "reward_summary": _reward_summary(reward_items),
            "reward_total": _reward_total(reward_items),
        }
    run = build_xinggong_starboard_run_view(value)
    if not run:
        return {}
    pulled_slots = [str(item) for item in (run.get("pulled_slots") or [])]
    collected = bool(run.get("collected"))
    soothed = bool(run.get("soothed"))
    reward_items = _merge_reward_items(run.get("reward_items") or [])
    if str(run.get("status") or "") not in {"completed", "idle"}:
        return {}
    if not (pulled_slots or collected or soothed or reward_items):
        return {}
    updated_at = float(run.get("updated_at") or time.time())
    actions = []
    if soothed:
        actions.append("安抚")
    if collected:
        actions.append("收集")
    if pulled_slots:
        actions.append(f"牵星{len(pulled_slots)}个")
    return {
        "day_key": _history_day_key(updated_at),
        "updated_at": updated_at,
        "time_display": _safe_text(
            run.get("time_display")
            or datetime.fromtimestamp(
                updated_at, tz=XINGGONG_STARBOARD_HISTORY_TZ
            ).strftime("%Y-%m-%d %H:%M:%S"),
            40,
        ),
        "target_star": normalize_starboard_target(run.get("target_star")),
        "action_summary": "、".join(actions) if actions else "状态同步",
        "message": sanitize_xinggong_starboard_secret_text(run.get("message") or ""),
        "pulled_slots": pulled_slots,
        "pulled_count": len(pulled_slots),
        "collected": collected,
        "soothed": soothed,
        "reward_items": reward_items,
        "reward_summary": _reward_summary(reward_items),
        "reward_total": _reward_total(reward_items),
    }


def _merge_today_history(history_value: object, run_view: dict) -> list[dict]:
    entry = _build_history_entry(run_view)
    day_key = _history_day_key((entry or {}).get("updated_at") or time.time())
    history: list[dict] = []
    for item in history_value if isinstance(history_value, list) else []:
        item_entry = _build_history_entry(item)
        if item_entry and item_entry.get("day_key") == day_key:
            history.append(item_entry)
    if entry:
        history.append(entry)
    return history[-XINGGONG_STARBOARD_HISTORY_LIMIT:]


def build_xinggong_starboard_payload_history(
    payload: object,
    *,
    now_ts: Optional[float] = None,
) -> dict:
    if not isinstance(payload, dict):
        return {
            "entries": [],
            "entry_count": 0,
            "pulled_total": 0,
            "collected_total": 0,
            "reward_items": [],
            "reward_summary": "",
            "reward_total": 0,
        }
    board = payload.get("xinggong_starboard") if isinstance(payload.get("xinggong_starboard"), dict) else {}
    day_key = _history_day_key(now_ts if now_ts is not None else time.time())
    entries = []
    for item in board.get("miniapp_history") if isinstance(board.get("miniapp_history"), list) else []:
        entry = _build_history_entry(item)
        if entry and entry.get("day_key") == day_key:
            entries.append(entry)
    entries = sorted(entries, key=lambda item: float(item.get("updated_at") or 0), reverse=True)
    reward_items = _merge_reward_items(
        [
            reward
            for entry in entries
            for reward in (entry.get("reward_items") or [])
        ]
    )
    return {
        "entries": entries,
        "entry_count": len(entries),
        "pulled_total": sum(int(entry.get("pulled_count") or 0) for entry in entries),
        "collected_total": sum(1 for entry in entries if entry.get("collected")),
        "reward_items": reward_items,
        "reward_summary": _reward_summary(reward_items),
        "reward_total": _reward_total(reward_items),
    }


def build_xinggong_starboard_payload_result(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    board = payload.get("xinggong_starboard") if isinstance(payload.get("xinggong_starboard"), dict) else {}
    return build_xinggong_starboard_run_view(board.get("miniapp_run"))


def cancel_xinggong_starboard_request(payload: object, *, reason: str = "用户手动关闭自动星辰采集。") -> dict:
    run = {
        "status": "stopped",
        "level": "info",
        "message": reason,
        "target_star": XINGGONG_STARBOARD_DEFAULT_STAR,
        "updated_at": time.time(),
        "time_display": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "error": "",
        "events": [],
        "safety_boundary": XINGGONG_STARBOARD_SAFETY_BOUNDARY,
    }
    return merge_xinggong_starboard_payload(payload, run=run, clear_request=True)


def _extract_init_data_from_webview_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    for key, value in _parse_pairs(parsed.fragment):
        if key == "tgWebAppData":
            return unquote(value)
    return ""


async def request_xinggong_starboard_miniapp_init_data(
    client: object,
    *,
    token: str,
    webview_url: str = "",
) -> str:
    clean_token = str(token or "").strip()
    if not clean_token or not _FARM_TOKEN_PATTERN.match(clean_token):
        raise ValueError("xinggong starboard miniapp token not allowed")
    host = _host_from_url(str(webview_url or ""))
    if host and host not in XINGGONG_STARBOARD_ALLOWED_WEB_HOSTS:
        raise ValueError(f"xinggong starboard miniapp web host not allowed: {host}")
    bot = await client.get_entity(XINGGONG_STARBOARD_MINIAPP_DEFAULT_BOT_USERNAME)
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
    if result_path != XINGGONG_STARBOARD_MINIAPP_WEB_PATH:
        raise RuntimeError("WebView URL 不是星宫观星台 MiniApp")
    init_data = _extract_init_data_from_webview_url(result_url)
    if not init_data:
        raise RuntimeError("WebView URL 缺少 tgWebAppData")
    return init_data


async def run_xinggong_starboard_snapshot_production_flow(
    client: object,
    *,
    token: str,
    webview_url: str = "",
    transport=None,
) -> dict:
    try:
        init_data = await request_xinggong_starboard_miniapp_init_data(
            client,
            token=token,
            webview_url=webview_url,
        )
        return await asyncio.to_thread(
            run_xinggong_starboard_snapshot_flow,
            token=token,
            init_data=init_data,
            transport=transport or _urllib_transport,
        )
    except Exception as exc:
        return _flow_result(False, "failed", target_star=XINGGONG_STARBOARD_DEFAULT_STAR, error=exc)


async def run_xinggong_starboard_miniapp_production_flow(
    client: object,
    *,
    token: str,
    webview_url: str = "",
    target_star: str = XINGGONG_STARBOARD_DEFAULT_STAR,
    transport=None,
) -> dict:
    target = normalize_starboard_target(target_star)
    try:
        init_data = await request_xinggong_starboard_miniapp_init_data(
            client,
            token=token,
            webview_url=webview_url,
        )
        return await asyncio.to_thread(
            run_xinggong_starboard_miniapp_flow,
            token=token,
            init_data=init_data,
            transport=transport or _urllib_transport,
            target_star=target,
        )
    except Exception as exc:
        return _flow_result(False, "failed", target_star=target, error=exc)


async def run_xinggong_starboard_public_miniapp_production_flow(
    client: object,
    *,
    discovery_storage: object = None,
    transport=None,
    target_star: str = XINGGONG_STARBOARD_DEFAULT_STAR,
    snapshot_only: bool = False,
    sleeper=time.sleep,
) -> dict:
    target = normalize_starboard_target(target_star)
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
        init_data = await estate_miniapp.request_estate_miniapp_init_data(
            client,
            token=estate_launch.get("token"),
            webview_url=estate_launch.get("webview_url"),
            bot_username=estate_launch.get("bot_username"),
            launch_context=estate_launch,
        )
        request = estate_miniapp.build_estate_miniapp_request(
            "start",
            token=estate_launch.get("token"),
            init_data=init_data,
        )
        lookup = await asyncio.to_thread(
            estate_miniapp.execute_estate_external_app_lookup,
            request,
            transport or estate_miniapp._urllib_transport,
            extract_public_xinggong_starboard_launch,
            action="sect_farm",
            sleeper=sleeper,
        )
        start_result = lookup.get("result") or {}
        if not start_result.get("ok"):
            return _flow_result(
                False,
                "failed",
                target_star=target,
                error=start_result.get("error"),
            )
        starboard_launch = lookup.get("launch") or {}
        if not starboard_launch:
            return _flow_result(
                False,
                "failed",
                target_star=target,
                error=(
                    f"洞府外府目录连续 {int(lookup.get('attempts') or 1)} 次"
                    "未返回星宫观星台链接"
                ),
            )
        flow = (
            run_xinggong_starboard_snapshot_flow
            if snapshot_only
            else run_xinggong_starboard_miniapp_flow
        )
        flow_kwargs = {
            "token": starboard_launch.get("token"),
            "init_data": init_data,
            "transport": transport or _urllib_transport,
        }
        if not snapshot_only:
            flow_kwargs["target_star"] = target
        result = await asyncio.to_thread(flow, **flow_kwargs)
        result = dict(result)
        result["entry"] = starboard_launch.get("entry")
        return result
    except Exception as exc:
        return _flow_result(False, "failed", target_star=target, error=exc)
