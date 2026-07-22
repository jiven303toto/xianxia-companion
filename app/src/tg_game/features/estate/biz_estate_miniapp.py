import asyncio
import hashlib
import json
import os
import re
import time
from typing import Optional
from urllib.parse import parse_qsl, quote, unquote, urljoin, urlsplit
import urllib.request

from telethon import functions
from .biz_estate_constants import (
    ESTATE_MINIAPP_ALLOWED_API_HOSTS,
    ESTATE_MINIAPP_ALLOWED_WEB_HOSTS,
    ESTATE_MINIAPP_API_PATH_PREFIX,
    ESTATE_MINIAPP_DEFAULT_API_BASE_URL,
    ESTATE_MINIAPP_DEFAULT_BOT_USERNAME,
    ESTATE_MINIAPP_ENDPOINTS,
    ESTATE_MINIAPP_FALLBACK_START_PARAM_ENV,
    ESTATE_MINIAPP_FALLBACK_URL_ENV,
    ESTATE_MINIAPP_PUBLIC_ENTRY_CHANNEL,
    ESTATE_MINIAPP_PUBLIC_ENTRY_STATE_KEY,
    ESTATE_MINIAPP_WEB_PATH,
    MINIAPP_SAFETY_BOUNDARY,
)
from .biz_estate_hunt_queue import (
    _build_hunt_state,
    _choose_hunt_reveal_index,
    _extract_hunt_limits_state,
    build_estate_miniapp_hunt_request,
    claim_estate_miniapp_hunt_request,
    continue_estate_miniapp_hunt_automation,
    get_pending_estate_miniapp_hunt_request,
    is_estate_miniapp_hunt_request_owned,
    is_estate_miniapp_hunt_limit_reached,
    is_estate_miniapp_hunt_state_stale,
    mark_estate_miniapp_hunt_limit_reached,
    mark_estate_miniapp_hunt_request_status,
    queue_estate_miniapp_hunt_request,
)
from .biz_estate_safety import URL_PATTERN as _URL_PATTERN
from .biz_estate_safety import _safe_text
from .biz_estate_view_state import (
    _as_dict,
    _as_list,
    _int_or_zero,
    _stamp_snapshot_sync_time,
    build_estate_miniapp_hunt,
    build_estate_miniapp_snapshot,
    merge_estate_miniapp_payload,
)


_ESTATE_KEYWORDS = ("洞府", "仙府", "灵脉", "静室", "dongfu", "estate")
_ESTATE_TOKEN_PATTERN = re.compile(
    r"^(?:df_|dongfu_|estate_)?[A-Za-z0-9_-]{4,160}$",
    re.IGNORECASE,
)
_START_TOKEN_PATTERN = re.compile(
    r"\b(?P<kind>df|dongfu|estate)_[A-Za-z0-9_-]{4,}\b",
    re.IGNORECASE,
)
_BOT_USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_]{5,64}$")
_START_PARAM_KEYS = {
    "startapp",
    "start_param",
    "startattach",
    "start",
    "tgwebappstartparam",
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
_ESTATE_PUBLIC_ENTRY_DISCOVERY_LOCK = asyncio.Lock()
_ESTATE_PUBLIC_ENTRY_SCAN_LIMIT = 200
_ESTATE_PUBLIC_ENTRY_SEARCH_TERMS = ("洞府公共入口", "洞府")
ESTATE_EXTERNAL_APP_RETRY_DELAYS = (2.0, 5.0, 10.0)


def _flatten_buttons(value: object):
    if value is None:
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _flatten_buttons(item)
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
    for source in (getattr(message, "buttons", None), getattr(event, "buttons", None)):
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
    if lowered.startswith("df"):
        return "df"
    if lowered.startswith("dongfu"):
        return "dongfu"
    if lowered.startswith("estate"):
        return "estate"
    match = re.match(r"([a-z][a-z0-9]{1,15})(?:[_:\-.]|$)", lowered)
    return match.group(1) if match else "present"


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


def _start_param_pair(pairs: list[tuple[str, str]]) -> tuple[str, str]:
    for key, value in pairs:
        normalized_key = str(key or "").strip().lower()
        if normalized_key in _START_PARAM_KEYS:
            return key, str(value or "").strip()
    return "", ""


def _host_from_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    return (parsed.hostname or parsed.netloc or "").lower()


def _bot_username_from_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    if (parsed.hostname or "").lower() not in {"t.me", "telegram.me"}:
        return ""
    username = parsed.path.strip("/").split("/", 1)[0].strip().lstrip("@")
    return username if _BOT_USERNAME_PATTERN.match(username) else ""


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


def _looks_like_estate_entry(button_text: str, url: str, text: str, summary: dict) -> bool:
    haystack = " ".join(
        [
            str(button_text or ""),
            str(url or ""),
            str(text or ""),
            str(summary.get("start_param_kind") or ""),
        ]
    ).lower()
    return any(keyword.lower() in haystack for keyword in _ESTATE_KEYWORDS)


def extract_estate_miniapp_entry(event: object, text: str = "") -> Optional[dict]:
    for button_text, url in _iter_button_links(event):
        summary = _summarize_url(button_text, url)
        if summary and _looks_like_estate_entry(button_text, url, text, summary):
            return summary
    for match in _URL_PATTERN.finditer(str(text or "")):
        url = match.group(0)
        summary = _summarize_url("", url)
        if summary and _looks_like_estate_entry("", url, text, summary):
            return summary
    return None


def extract_estate_miniapp_launch(event: object, text: str = "") -> dict:
    for button_text, url in _iter_button_links(event):
        summary = _summarize_url(button_text, url)
        if not summary or not _looks_like_estate_entry(button_text, url, text, summary):
            continue
        token = _start_param_from_url(url)
        if token and _ESTATE_TOKEN_PATTERN.match(token):
            return {
                "token": token,
                "webview_url": url,
                "bot_username": _bot_username_from_url(url),
                "entry": summary,
            }
    return {}


async def fetch_estate_public_miniapp_launch(client: object) -> dict:
    result = await discover_estate_public_miniapp_launch(client)
    if not result.get("ok"):
        raise RuntimeError(str(result.get("error") or "洞府公共入口未找到"))
    return result["launch"]


def default_estate_public_entry_discovery_state() -> dict:
    return {
        "channel": "",
        "current_message_id": 0,
        "last_scanned_message_id": 0,
        "current_bot_username": "",
        "current_entry_digest": "",
        "verified_at": 0.0,
        "last_scan_at": 0.0,
        "last_scan_status": "not_started",
        "last_error": "",
        "discovery_source": "bootstrap",
    }


def normalize_estate_public_entry_discovery_state(value: object) -> dict:
    state = default_estate_public_entry_discovery_state()
    if not isinstance(value, dict):
        return state
    current_message_id = _int_or_zero(value.get("current_message_id"))
    last_scanned_message_id = _int_or_zero(value.get("last_scanned_message_id"))
    state.update(
        {
            "channel": _safe_text(value.get("channel"), 64),
            "current_message_id": current_message_id,
            "last_scanned_message_id": last_scanned_message_id,
            "current_bot_username": _safe_text(
                value.get("current_bot_username"), 64
            ),
            "current_entry_digest": _safe_text(
                value.get("current_entry_digest"), 20
            ),
            "verified_at": max(0.0, _float_or_zero(value.get("verified_at"))),
            "last_scan_at": max(0.0, _float_or_zero(value.get("last_scan_at"))),
            "last_scan_status": _safe_text(
                value.get("last_scan_status") or "not_started", 40
            ),
            "last_error": sanitize_estate_miniapp_secret_text(
                value.get("last_error"), limit=160
            ),
            "discovery_source": _safe_text(
                value.get("discovery_source") or "bootstrap", 40
            ),
        }
    )
    return state


def load_estate_public_entry_discovery_state(storage: object) -> dict:
    raw_value = ""
    if storage is not None and hasattr(storage, "get_runtime_state"):
        raw_value = str(
            storage.get_runtime_state(ESTATE_MINIAPP_PUBLIC_ENTRY_STATE_KEY) or ""
        )
    if not raw_value:
        return default_estate_public_entry_discovery_state()
    try:
        value = json.loads(raw_value)
    except (TypeError, ValueError, json.JSONDecodeError):
        value = {}
    return normalize_estate_public_entry_discovery_state(value)


def save_estate_public_entry_discovery_state(storage: object, value: object) -> dict:
    state = normalize_estate_public_entry_discovery_state(value)
    if storage is not None and hasattr(storage, "set_runtime_state"):
        storage.set_runtime_state(
            ESTATE_MINIAPP_PUBLIC_ENTRY_STATE_KEY,
            json.dumps(state, ensure_ascii=False, separators=(",", ":")),
        )
    return state


def _float_or_zero(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _first_message(value: object):
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def _message_id(value: object) -> int:
    return max(0, _int_or_zero(getattr(value, "id", 0)))


def _extract_public_estate_launch(message: object) -> dict:
    if not message:
        return {}
    launch = extract_estate_miniapp_launch(
        message,
        str(getattr(message, "message", "") or ""),
    )
    entry = launch.get("entry") if isinstance(launch.get("entry"), dict) else {}
    if (
        not str(launch.get("token") or "").lower().startswith("df_")
        or not str(launch.get("bot_username") or "")
        or str(entry.get("host") or "").lower() not in {"t.me", "telegram.me"}
        or str(entry.get("start_param_key") or "").lower() != "startapp"
        or str(entry.get("start_param_kind") or "").lower() != "df"
    ):
        return {}
    return launch


def _configured_estate_public_miniapp_launch() -> dict:
    fallback_url = os.getenv(ESTATE_MINIAPP_FALLBACK_URL_ENV, "").strip()
    if fallback_url:
        token = _start_param_from_url(fallback_url)
        bot_username = _bot_username_from_url(fallback_url)
        entry = _summarize_url("进入洞府", fallback_url) or {}
        if (
            str(entry.get("host") or "").lower() not in {"t.me", "telegram.me"}
            or str(entry.get("start_param_key") or "").lower() != "startapp"
            or str(entry.get("start_param_kind") or "").lower() != "df"
            or not bot_username
            or not token.lower().startswith("df_")
            or not _ESTATE_TOKEN_PATTERN.fullmatch(token)
        ):
            raise ValueError("配置的洞府 fallback URL 无效")
        return {
            "token": token,
            "webview_url": fallback_url,
            "bot_username": bot_username,
            "entry": entry,
        }
    token = os.getenv(ESTATE_MINIAPP_FALLBACK_START_PARAM_ENV, "").strip()
    if not token:
        return {}
    if not token.lower().startswith("df_") or not _ESTATE_TOKEN_PATTERN.fullmatch(token):
        raise ValueError("配置的洞府 fallback start param 无效")
    webview_url = (
        f"https://t.me/{ESTATE_MINIAPP_DEFAULT_BOT_USERNAME}"
        f"?startapp={quote(token, safe='')}"
    )
    return {
        "token": token,
        "webview_url": webview_url,
        "bot_username": ESTATE_MINIAPP_DEFAULT_BOT_USERNAME,
        "entry": _summarize_url("进入洞府", webview_url) or {},
    }


def _estate_public_entry_chat_id(client: object, storage: object = None) -> int:
    profile_id = _int_or_zero(getattr(client, "_tg_game_profile_id", 0))
    if profile_id and storage is not None and hasattr(storage, "list_chat_bindings"):
        for binding in storage.list_chat_bindings(profile_id):
            if bool(getattr(binding, "is_active", False)):
                chat_id = _int_or_zero(getattr(binding, "chat_id", 0))
                if chat_id:
                    return chat_id
    return int(ESTATE_MINIAPP_PUBLIC_ENTRY_CHANNEL)


def _updated_public_entry_state(
    state: dict,
    *,
    message_id: int,
    launch: dict,
    source: str,
    now: float,
) -> dict:
    result = dict(state)
    entry = launch.get("entry") if isinstance(launch.get("entry"), dict) else {}
    result.update(
        {
            "current_message_id": int(message_id),
            "current_bot_username": _safe_text(launch.get("bot_username"), 64),
            "current_entry_digest": _safe_text(
                entry.get("start_param_digest"), 20
            ),
            "verified_at": now,
            "last_scan_status": "ok",
            "last_error": "",
            "discovery_source": source,
        }
    )
    return result


async def discover_estate_public_miniapp_launch(
    client: object,
    *,
    state: object = None,
    storage: object = None,
    now: Optional[float] = None,
) -> dict:
    discovery_state = (
        load_estate_public_entry_discovery_state(storage)
        if storage is not None
        else normalize_estate_public_entry_discovery_state(state)
    )
    current_time = float(time.time() if now is None else now)
    source_chat_id = _estate_public_entry_chat_id(client, storage)
    previous_channel = str(discovery_state.get("channel") or "")
    source_channel = str(source_chat_id)
    channel = await client.get_entity(source_chat_id)
    current_message_id = int(discovery_state["current_message_id"])
    current_message = (
        await client.get_messages(channel, ids=current_message_id)
        if current_message_id > 0
        else None
    )
    current_launch = _extract_public_estate_launch(current_message)

    latest_value = await client.get_messages(channel, limit=1)
    latest_message = _first_message(latest_value)
    channel_changed = bool(previous_channel and previous_channel != source_channel)
    cursor_floor = (
        0
        if channel_changed and not current_launch
        else int(discovery_state["last_scanned_message_id"])
    )
    latest_message_id = max(
        _message_id(latest_message),
        cursor_floor,
        current_message_id if current_launch or not channel_changed else 0,
    )
    discovered_launch = {}
    discovered_message_id = 0
    if not current_launch:
        async for message in client.iter_messages(
            channel,
            limit=_ESTATE_PUBLIC_ENTRY_SCAN_LIMIT,
        ):
            message_id = _message_id(message)
            if not message_id or message_id > latest_message_id:
                continue
            candidate = _extract_public_estate_launch(message)
            if candidate and message_id > discovered_message_id:
                discovered_launch = candidate
                discovered_message_id = message_id
        if not discovered_launch:
            for search_term in _ESTATE_PUBLIC_ENTRY_SEARCH_TERMS:
                async for message in client.iter_messages(
                    channel,
                    limit=20,
                    search=search_term,
                ):
                    message_id = _message_id(message)
                    candidate = _extract_public_estate_launch(message)
                    if candidate and message_id > discovered_message_id:
                        discovered_launch = candidate
                        discovered_message_id = message_id
                if discovered_launch:
                    break
    discovery_state["channel"] = source_channel
    discovery_state["last_scanned_message_id"] = latest_message_id
    if current_launch:
        launch = current_launch
        discovery_state = _updated_public_entry_state(
            discovery_state,
            message_id=current_message_id,
            launch=launch,
            source="cached_message",
            now=current_time,
        )
    elif discovered_launch:
        launch = discovered_launch
        discovery_state = _updated_public_entry_state(
            discovery_state,
            message_id=discovered_message_id,
            launch=launch,
            source="incremental_scan",
            now=current_time,
        )
    else:
        launch = {}
        discovery_state.update(
            {
                "last_scan_status": "entry_not_found",
                "last_scan_at": current_time,
                "last_error": "洞府公共入口未找到",
                "discovery_source": "incremental_scan",
            }
        )

    discovery_state["last_scan_at"] = current_time
    discovery_state = save_estate_public_entry_discovery_state(
        storage,
        discovery_state,
    )
    return {
        "ok": bool(launch),
        "launch": launch,
        "state": discovery_state,
        "error": "" if launch else "洞府公共入口未找到",
    }


async def resolve_estate_public_miniapp_launch(
    client: object,
    storage: object,
    *,
    now: Optional[float] = None,
) -> dict:
    current_time = float(time.time() if now is None else now)
    async with _ESTATE_PUBLIC_ENTRY_DISCOVERY_LOCK:
        state = load_estate_public_entry_discovery_state(storage)
        try:
            result = await discover_estate_public_miniapp_launch(
                client,
                storage=storage,
                now=current_time,
            )
            if result.get("ok"):
                return result
            state = (
                result.get("state")
                if isinstance(result.get("state"), dict)
                else state
            )
            fallback_launch = _configured_estate_public_miniapp_launch()
            if not fallback_launch:
                return result
            state = _updated_public_entry_state(
                state,
                message_id=0,
                launch=fallback_launch,
                source="configured_fallback",
                now=current_time,
            )
            state = save_estate_public_entry_discovery_state(storage, state)
            return {
                "ok": True,
                "launch": fallback_launch,
                "state": state,
                "error": "",
            }
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            safe_error = sanitize_estate_miniapp_secret_text(exc, limit=160)
            state.update(
                {
                    "last_scan_at": current_time,
                    "last_scan_status": "error",
                    "last_error": safe_error,
                    "discovery_source": "on_demand",
                }
            )
            state = save_estate_public_entry_discovery_state(storage, state)
            return {
                "ok": False,
                "launch": {},
                "state": state,
                "error": safe_error,
            }


def default_estate_miniapp_entry() -> dict:
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
        "safety_boundary": MINIAPP_SAFETY_BOUNDARY,
    }


def build_estate_miniapp_entry_view(value: object) -> dict:
    base = default_estate_miniapp_entry()
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


def sanitize_estate_miniapp_secret_text(text: object, *, limit: int = 220) -> str:
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


def _build_api_url(
    endpoint: str,
    api_base_url: str = ESTATE_MINIAPP_DEFAULT_API_BASE_URL,
) -> str:
    endpoint_path = ESTATE_MINIAPP_ENDPOINTS.get(str(endpoint or "").strip(), "")
    if not endpoint_path:
        raise ValueError(f"unknown estate miniapp endpoint: {endpoint}")
    base_origin = _origin_from_url(str(api_base_url or "").strip())
    if not base_origin:
        raise ValueError("miniapp api base url missing")
    url = urljoin(f"{base_origin}/", endpoint_path.lstrip("/"))
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host not in ESTATE_MINIAPP_ALLOWED_API_HOSTS:
        raise ValueError(f"miniapp api host not allowed: {host}")
    if not parsed.path.startswith(ESTATE_MINIAPP_API_PATH_PREFIX):
        raise ValueError(f"miniapp api path not allowed: {parsed.path}")
    return url


def _build_webview_url(
    token: str,
    api_base_url: str = ESTATE_MINIAPP_DEFAULT_API_BASE_URL,
) -> str:
    base_origin = _origin_from_url(str(api_base_url or "").strip())
    if not base_origin:
        raise ValueError("miniapp webview base url missing")
    url = f"{base_origin}{ESTATE_MINIAPP_WEB_PATH}?startapp={quote(str(token or '').strip(), safe='')}"
    host = _host_from_url(url)
    if host not in ESTATE_MINIAPP_ALLOWED_WEB_HOSTS:
        raise ValueError(f"estate miniapp web host not allowed: {host}")
    return url


def build_estate_miniapp_request(
    endpoint: str,
    *,
    token: str,
    init_data: str,
    payload: Optional[dict] = None,
    api_base_url: str = ESTATE_MINIAPP_DEFAULT_API_BASE_URL,
) -> dict:
    clean_token = str(token or "").strip()
    if not clean_token or not _ESTATE_TOKEN_PATTERN.match(clean_token):
        raise ValueError("estate miniapp token not allowed")
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
        "error": sanitize_estate_miniapp_secret_text(error),
    }


def execute_estate_miniapp_request(request: dict, transport) -> dict:
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
            "error": sanitize_estate_miniapp_secret_text(exc),
        }


def execute_estate_external_app_lookup(
    request: dict,
    transport,
    extractor,
    *,
    action: str = "",
    sleeper=time.sleep,
    retry_delays=None,
) -> dict:
    delays = (
        ESTATE_EXTERNAL_APP_RETRY_DELAYS
        if retry_delays is None
        else tuple(retry_delays)
    )
    attempts = 0
    result = {}
    launch = {}
    for delay_after in (None, *delays):
        if delay_after is not None:
            sleeper(float(delay_after))
        attempts += 1
        result = execute_estate_miniapp_request(request, transport)
        if not result.get("ok"):
            break
        data = result.get("data") or {}
        launch = extractor(data) or {}
        if launch:
            break
        clean_action = str(action or "").strip()
        if not clean_action:
            continue
        payload = request.get("payload") if isinstance(request.get("payload"), dict) else {}
        account = data.get("account") if isinstance(data.get("account"), dict) else {}
        details_request = build_estate_miniapp_request(
            "details",
            token=payload.get("token"),
            init_data=payload.get("initData"),
            payload={"playerId": str(account.get("playerId") or "")},
            api_base_url=request.get("url") or ESTATE_MINIAPP_DEFAULT_API_BASE_URL,
        )
        result = execute_estate_miniapp_request(details_request, transport)
        if not result.get("ok"):
            break
        data = result.get("data") or {}
        launch = extractor(data) or {}
        if launch:
            break
        account = data.get("account") if isinstance(data.get("account"), dict) else {}
        external_apps = account.get("externalApps") if isinstance(account.get("externalApps"), dict) else {}
        groups = external_apps.get("groups") if isinstance(external_apps.get("groups"), list) else []
        target_app = next(
            (
                app
                for group in groups
                if isinstance(group, dict)
                for app in (group.get("apps") if isinstance(group.get("apps"), list) else [])
                if isinstance(app, dict)
                and bool(app.get("available", True))
                and str(app.get("action") or app.get("key") or "").strip() == clean_action
            ),
            None,
        )
        if target_app is None:
            continue
        external_request = build_estate_miniapp_request(
            "external",
            token=payload.get("token"),
            init_data=payload.get("initData"),
            payload={"action": clean_action},
            api_base_url=request.get("url") or ESTATE_MINIAPP_DEFAULT_API_BASE_URL,
        )
        result = execute_estate_miniapp_request(external_request, transport)
        if not result.get("ok"):
            break
        resolved_url = str((result.get("data") or {}).get("url") or "").strip()
        if resolved_url:
            target_app["url"] = resolved_url
            launch = extractor(data) or {}
        if launch:
            break
    return {
        "result": result,
        "launch": launch,
        "attempts": attempts,
    }


def _execute_hunt_reveal_with_retry(request: dict, transport) -> dict:
    result = execute_estate_miniapp_request(request, transport)
    if result.get("ok"):
        return result
    status_code = int(result.get("status_code") or 0)
    if status_code == 0 or status_code >= 500:
        return execute_estate_miniapp_request(request, transport)
    return result


def _unwrap_data(data: object) -> dict:
    if not isinstance(data, dict):
        return {}
    if isinstance(data.get("data"), dict):
        return data["data"]
    if isinstance(data.get("result"), dict) and len(data) == 1:
        return data["result"]
    return data


def _extract_snapshot_source(data: object) -> dict:
    root = _unwrap_data(data)
    for key in ("dwelling", "dongfu", "estate", "cave", "home", "profile", "state"):
        value = root.get(key) if isinstance(root, dict) else None
        if isinstance(value, dict):
            if key == "dwelling":
                account = root.get("account")
                if isinstance(account, dict):
                    value = dict(value)
                    value.setdefault("owner", account.get("daoName") or account.get("username"))
                    value.setdefault("stage", account.get("cultivationLevel"))
            return value
    return root if isinstance(root, dict) else {}


def _flow_result(
    ok: bool,
    status: str,
    *,
    error: object = "",
    snapshot: Optional[dict] = None,
    hunt_limits: Optional[dict] = None,
    events: Optional[list] = None,
) -> dict:
    return {
        "ok": bool(ok),
        "status": str(status or "unknown"),
        "error": sanitize_estate_miniapp_secret_text(error),
        "snapshot": snapshot or {},
        "hunt_limits": hunt_limits or {},
        "events": events or [],
    }


def _append_event(events: list, step: str, result: dict) -> None:
    events.append(
        {
            "step": step,
            "ok": bool(result.get("ok")),
            "status_code": int(result.get("status_code") or 0),
            "error": sanitize_estate_miniapp_secret_text(result.get("error") or ""),
        }
    )


def _hunt_flow_result(
    ok: bool,
    status: str,
    *,
    error: object = "",
    hunt: Optional[dict] = None,
    snapshot: Optional[dict] = None,
    events: Optional[list] = None,
) -> dict:
    return {
        "ok": bool(ok),
        "status": str(status or "unknown"),
        "error": sanitize_estate_miniapp_secret_text(error),
        "hunt": hunt or {},
        "snapshot": snapshot or {},
        "events": events or [],
    }


def run_estate_miniapp_snapshot_flow(
    *,
    token: str,
    init_data: str,
    transport,
    capture_source: str = "",
) -> dict:
    _ = capture_source
    if not str(token or "").strip():
        return _flow_result(False, "failed", error="token missing")
    if not str(init_data or "").strip():
        return _flow_result(False, "failed", error="initData missing")

    events: list[dict] = []
    request = build_estate_miniapp_request("start", token=token, init_data=init_data)
    start_result = execute_estate_miniapp_request(request, transport)
    _append_event(events, "start", start_result)
    if not start_result.get("ok"):
        return _flow_result(
            False,
            "failed",
            error=start_result.get("error"),
            events=events,
        )

    start_data = start_result.get("data") or {}
    snapshot_source = _stamp_snapshot_sync_time(_extract_snapshot_source(start_data))
    snapshot = build_estate_miniapp_snapshot(snapshot_source)
    hunt_limits = _extract_hunt_limits_state(start_data)
    return _flow_result(
        True,
        "synced",
        snapshot=snapshot,
        hunt_limits=hunt_limits,
        events=events,
    )


def run_estate_miniapp_hunt_flow(
    *,
    token: str,
    init_data: str,
    transport,
    max_reveals: int = 8,
    min_ap_to_settle: int = 0,
    capture_source: str = "",
) -> dict:
    _ = capture_source
    if not str(token or "").strip():
        return _hunt_flow_result(False, "failed", error="token missing")
    if not str(init_data or "").strip():
        return _hunt_flow_result(False, "failed", error="initData missing")

    reveal_limit = max(1, min(_int_or_zero(max_reveals), 8))
    min_ap = max(0, min(_int_or_zero(min_ap_to_settle), 8))
    events: list[dict] = []
    revealed_indices: list[int] = []
    dwelling: dict = {}
    run: dict = {}

    start_request = build_estate_miniapp_request(
        "hunt", token=token, init_data=init_data
    )
    start_result = execute_estate_miniapp_request(start_request, transport)
    _append_event(events, "hunt", start_result)
    if not start_result.get("ok"):
        hunt = _build_hunt_state(
            status="failed",
            error=start_result.get("error"),
            events=events,
            revealed_indices=revealed_indices,
        )
        return _hunt_flow_result(
            False,
            "failed",
            error=start_result.get("error"),
            hunt=hunt,
            events=events,
        )

    start_data = _as_dict(start_result.get("data"))
    run = _as_dict(start_data.get("huntRun"))
    dwelling = _as_dict(start_data.get("dwelling"))
    session_id = str(run.get("sessionId") or "").strip()
    if not session_id:
        hunt = _build_hunt_state(
            status="failed",
            run=run,
            dwelling=dwelling,
            error="hunt session missing",
            events=events,
            revealed_indices=revealed_indices,
        )
        return _hunt_flow_result(
            False,
            "failed",
            error="hunt session missing",
            hunt=hunt,
            events=events,
        )

    while str(run.get("status") or "") == "active":
        if len(revealed_indices) >= reveal_limit:
            break
        if _int_or_zero(run.get("ap")) <= min_ap:
            break
        index = _choose_hunt_reveal_index(run, revealed_indices)
        if index is None:
            break
        reveal_request = build_estate_miniapp_request(
            "hunt_reveal",
            token=token,
            init_data=init_data,
            payload={"sessionId": session_id, "index": index},
        )
        reveal_result = _execute_hunt_reveal_with_retry(reveal_request, transport)
        _append_event(events, f"reveal:{index}", reveal_result)
        if not reveal_result.get("ok"):
            hunt = _build_hunt_state(
                status="failed",
                run=run,
                dwelling=dwelling,
                error=reveal_result.get("error"),
                events=events,
                revealed_indices=revealed_indices,
            )
            return _hunt_flow_result(
                False,
                "failed",
                error=reveal_result.get("error"),
                hunt=hunt,
                events=events,
            )
        revealed_indices.append(index)
        reveal_data = _as_dict(reveal_result.get("data"))
        run = _as_dict(reveal_data.get("huntRun")) or run

    settle_request = build_estate_miniapp_request(
        "hunt_settle",
        token=token,
        init_data=init_data,
        payload={"sessionId": session_id},
    )
    settle_result = execute_estate_miniapp_request(settle_request, transport)
    _append_event(events, "settle", settle_result)
    if not settle_result.get("ok"):
        hunt = _build_hunt_state(
            status="failed",
            run=run,
            dwelling=dwelling,
            error=settle_result.get("error"),
            events=events,
            revealed_indices=revealed_indices,
        )
        return _hunt_flow_result(
            False,
            "failed",
            error=settle_result.get("error"),
            hunt=hunt,
            events=events,
        )

    settle_data = _as_dict(settle_result.get("data"))
    hunt_result = _as_dict(settle_data.get("huntResult"))
    dwelling = _as_dict(settle_data.get("dwelling")) or dwelling
    hunt = _build_hunt_state(
        status="settled",
        run=run,
        result=hunt_result,
        dwelling=dwelling,
        events=events,
        revealed_indices=revealed_indices,
    )
    snapshot = {}
    if dwelling:
        snapshot = build_estate_miniapp_snapshot(
            _stamp_snapshot_sync_time(
                _extract_snapshot_source(
                    {
                        "account": settle_data.get("account"),
                        "dwelling": dwelling,
                    }
                )
            )
        )
    return _hunt_flow_result(
        True,
        "settled",
        hunt=hunt,
        snapshot=snapshot,
        events=events,
    )


def run_estate_miniapp_daily_hunt_flow(
    *,
    token: str,
    init_data: str,
    transport,
    max_reveals: int = 8,
    min_ap_to_settle: int = 0,
    capture_source: str = "",
) -> dict:
    _ = capture_source
    if not str(token or "").strip():
        return _hunt_flow_result(False, "failed", error="token missing")
    if not str(init_data or "").strip():
        return _hunt_flow_result(False, "failed", error="initData missing")

    request_state = build_estate_miniapp_hunt_request(
        max_reveals=max_reveals,
        min_ap_to_settle=min_ap_to_settle,
    )
    final_result: dict = {}
    final_hunt: dict = {}
    final_snapshot: dict = {}
    combined_events: list = []

    for _round_index in range(8):
        result = run_estate_miniapp_hunt_flow(
            token=token,
            init_data=init_data,
            transport=transport,
            max_reveals=max_reveals,
            min_ap_to_settle=min_ap_to_settle,
        )
        combined_events.extend(_as_list(result.get("events")))
        hunt = _as_dict(result.get("hunt"))
        if not hunt:
            final_result = result
            break
        final_hunt, next_request = continue_estate_miniapp_hunt_automation(
            request_state,
            hunt,
        )
        snapshot = _as_dict(result.get("snapshot"))
        if snapshot:
            final_snapshot = snapshot
        final_result = result
        if not result.get("ok") or not next_request:
            break
        request_state = next_request
    else:
        final_hunt = dict(final_hunt)
        final_hunt.update(
            {
                "status": "failed",
                "automation_status": "安全轮数已停止",
                "error": "auto hunt round cap reached",
            }
        )
        final_result = _hunt_flow_result(
            False,
            "failed",
            error="auto hunt round cap reached",
            hunt=final_hunt,
            snapshot=final_snapshot,
            events=combined_events,
        )

    if final_hunt:
        final_result = dict(final_result)
        final_result["hunt"] = final_hunt
    if final_snapshot:
        final_result["snapshot"] = final_snapshot
    final_result["events"] = combined_events[-24:]
    return final_result


def _extract_init_data_from_webview_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return ""
    for key, value in _parse_pairs(parsed.fragment):
        if key == "tgWebAppData":
            return unquote(value)
    return ""


async def _request_estate_miniapp_init_data_once(
    client: object,
    *,
    token: str,
    webview_url: str = "",
    bot_username: str = "",
) -> str:
    clean_token = str(token or "").strip()
    if not clean_token or not _ESTATE_TOKEN_PATTERN.match(clean_token):
        raise ValueError("estate miniapp token not allowed")
    host = _host_from_url(str(webview_url or ""))
    if host and host not in ESTATE_MINIAPP_ALLOWED_WEB_HOSTS:
        raise ValueError(f"estate miniapp web host not allowed: {host}")
    resolved_bot_username = str(
        bot_username
        or _bot_username_from_url(str(webview_url or ""))
        or ESTATE_MINIAPP_DEFAULT_BOT_USERNAME
    ).strip().lstrip("@")
    if not _BOT_USERNAME_PATTERN.match(resolved_bot_username):
        raise ValueError("estate miniapp bot username not allowed")
    bot = await client.get_entity(resolved_bot_username)
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
    if result_path != ESTATE_MINIAPP_WEB_PATH:
        raise RuntimeError("WebView URL 不是洞府 MiniApp")
    init_data = _extract_init_data_from_webview_url(result_url)
    if not init_data:
        raise RuntimeError("WebView URL 缺少 tgWebAppData")
    return init_data


async def request_estate_miniapp_init_data(
    client: object,
    *,
    token: str,
    webview_url: str = "",
    bot_username: str = "",
    launch_context: Optional[dict] = None,
) -> str:
    try:
        return await _request_estate_miniapp_init_data_once(
            client,
            token=token,
            webview_url=webview_url,
            bot_username=bot_username,
        )
    except Exception as primary_exc:
        if not isinstance(launch_context, dict):
            raise
        fallback_launch = _configured_estate_public_miniapp_launch()
        if not fallback_launch or (
            str(fallback_launch.get("token") or "") == str(token or "")
            and str(fallback_launch.get("bot_username") or "")
            == str(bot_username or _bot_username_from_url(webview_url) or "")
        ):
            raise
        try:
            init_data = await _request_estate_miniapp_init_data_once(
                client,
                token=fallback_launch.get("token"),
                webview_url=fallback_launch.get("webview_url"),
                bot_username=fallback_launch.get("bot_username"),
            )
        except Exception as fallback_exc:
            raise RuntimeError(
                "公共入口 WebView 失败："
                f"{sanitize_estate_miniapp_secret_text(primary_exc)}；"
                "备用入口 WebView 失败："
                f"{sanitize_estate_miniapp_secret_text(fallback_exc)}"
            ) from fallback_exc
        launch_context.clear()
        launch_context.update(fallback_launch)
        return init_data


async def run_estate_miniapp_production_snapshot_flow(
    client: object,
    *,
    token: str,
    webview_url: str = "",
    bot_username: str = "",
    transport=None,
    capture_source: str = "",
) -> dict:
    try:
        init_data = await request_estate_miniapp_init_data(
            client,
            token=token,
            webview_url=webview_url,
            bot_username=bot_username,
        )
        return await asyncio.to_thread(
            run_estate_miniapp_snapshot_flow,
            token=token,
            init_data=init_data,
            transport=transport or _urllib_transport,
            capture_source=capture_source,
        )
    except Exception as exc:
        return _flow_result(False, "failed", error=exc)


async def run_estate_miniapp_production_hunt_flow(
    client: object,
    *,
    token: str,
    webview_url: str = "",
    bot_username: str = "",
    transport=None,
    capture_source: str = "",
    max_reveals: int = 8,
    min_ap_to_settle: int = 0,
    launch_context: Optional[dict] = None,
) -> dict:
    try:
        init_data = await request_estate_miniapp_init_data(
            client,
            token=token,
            webview_url=webview_url,
            bot_username=bot_username,
            launch_context=launch_context,
        )
        effective_token = (
            launch_context.get("token")
            if isinstance(launch_context, dict)
            else token
        )
        return await asyncio.to_thread(
            run_estate_miniapp_daily_hunt_flow,
            token=effective_token,
            init_data=init_data,
            transport=transport or _urllib_transport,
            capture_source=capture_source,
            max_reveals=max_reveals,
            min_ap_to_settle=min_ap_to_settle,
        )
    except Exception as exc:
        return _hunt_flow_result(
            False,
            "failed",
            error=exc,
            hunt=_build_hunt_state(status="failed", error=exc),
        )


async def run_estate_public_miniapp_production_hunt_flow(
    client: object,
    *,
    discovery_storage: object = None,
    transport=None,
    capture_source: str = "",
    max_reveals: int = 8,
    min_ap_to_settle: int = 0,
    progress_callback=None,
) -> dict:
    try:
        if discovery_storage is not None:
            discovery = await resolve_estate_public_miniapp_launch(
                client,
                discovery_storage,
            )
            if not discovery.get("ok"):
                raise RuntimeError(
                    str(discovery.get("error") or "洞府公共入口未找到")
                )
            launch = (
                discovery.get("launch")
                if isinstance(discovery.get("launch"), dict)
                else {}
            )
        else:
            launch = await fetch_estate_public_miniapp_launch(client)
        if progress_callback is not None:
            progress_callback()
    except Exception as exc:
        return _hunt_flow_result(
            False,
            "failed",
            error=exc,
            hunt=_build_hunt_state(status="failed", error=exc),
        )
    result = await run_estate_miniapp_production_hunt_flow(
        client,
        token=launch.get("token"),
        webview_url=launch.get("webview_url"),
        bot_username=launch.get("bot_username"),
        transport=transport,
        capture_source=capture_source,
        max_reveals=max_reveals,
        min_ap_to_settle=min_ap_to_settle,
        launch_context=launch,
    )
    result = dict(result)
    result["entry"] = launch.get("entry")
    return result
