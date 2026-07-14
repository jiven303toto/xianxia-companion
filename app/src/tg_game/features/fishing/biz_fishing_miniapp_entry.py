import hashlib
import re
from typing import Optional
from urllib.parse import parse_qsl, unquote, urlsplit


MINIAPP_ENTRY_MARKER = "【MiniApp入口诊断】"
MINIAPP_SAFETY_BOUNDARY = (
    "自动会话未启用时只记录入口；启用后可自动请求 Telegram WebView 和 MiniApp HTTP；"
    "不保存 initData/tgWebAppData/hash/user/raw URL。"
)
MAX_FISHING_RESULT_TEXT_LENGTH = 4000

_FISHING_KEYWORDS = ("灵溪", "垂钓", "钓鱼", "fish", "fishing")
_URL_PATTERN = re.compile(r"(?:https?|tg)://[^\s<>'\"）)]+", re.IGNORECASE)
_FISH_TOKEN_PATTERN = re.compile(r"^(?:fish_)?[A-Za-z0-9_-]{4,160}$", re.IGNORECASE)
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


def _safe_text(value: object, max_length: int = 60) -> str:
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
        web_app = getattr(source, "web_app", None)
        web_app_url = getattr(web_app, "url", None) if web_app is not None else None
        if isinstance(web_app_url, str) and web_app_url.strip():
            return web_app_url.strip()
        for attr in ("webview", "web_view"):
            webview = getattr(source, attr, None)
            webview_url = getattr(webview, "url", None) if webview is not None else None
            if isinstance(webview_url, str) and webview_url.strip():
                return webview_url.strip()
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


def describe_miniapp_button_debug(event: object) -> str:
    message = getattr(event, "message", None)
    sources = [
        ("message.buttons", getattr(message, "buttons", None)),
        ("event.buttons", getattr(event, "buttons", None)),
        ("message.reply_markup", getattr(message, "reply_markup", None)),
        ("event.reply_markup", getattr(event, "reply_markup", None)),
    ]
    parts = []
    for label, source in sources:
        if source is None:
            continue
        buttons = list(_flatten_buttons(source))
        if not buttons:
            parts.append(f"{label}:{type(source).__name__}:empty")
            continue
        for button in buttons[:4]:
            inner = getattr(button, "button", None)
            inner_type = type(inner).__name__ if inner is not None else "-"
            attrs = []
            for attr in ("url", "web_app", "button", "data"):
                value = getattr(button, attr, None)
                if value:
                    attrs.append(attr)
            if inner is not None:
                for attr in ("url", "web_app", "data"):
                    value = getattr(inner, attr, None)
                    if value:
                        attrs.append(f"inner.{attr}")
            text = _button_text(button) or "-"
            has_url = "yes" if _button_url(button) else "no"
            parts.append(
                f"{label}:{type(button).__name__}/{inner_type}:text={text}:url={has_url}:attrs={','.join(attrs) or '-'}"
            )
    return "；".join(parts[:8]) or "no button sources"


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
    if lowered.startswith("fishing"):
        return "fishing"
    if lowered.startswith("fish"):
        return "fish"
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
        if normalized_key not in _START_PARAM_KEYS:
            continue
        return key, str(value or "").strip()
    return "", ""


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


def _looks_like_fishing_entry(button_text: str, url: str, text: str, summary: dict) -> bool:
    haystack = " ".join(
        [
            str(button_text or ""),
            str(url or ""),
            str(text or ""),
            str(summary.get("start_param_kind") or ""),
        ]
    ).lower()
    return any(keyword.lower() in haystack for keyword in _FISHING_KEYWORDS)


def looks_like_fishing_miniapp_prompt(text: object) -> bool:
    normalized = str(text or "")
    return "进入灵溪垂钓" in normalized and "点击" in normalized


def extract_fishing_miniapp_entry(event: object, text: str = "") -> Optional[dict]:
    for button_text, url in _iter_button_links(event):
        summary = _summarize_url(button_text, url)
        if summary and _looks_like_fishing_entry(button_text, url, text, summary):
            return summary
    for match in _URL_PATTERN.finditer(str(text or "")):
        url = match.group(0)
        summary = _summarize_url("", url)
        if summary and _looks_like_fishing_entry("", url, text, summary):
            return summary
    return None


def extract_fishing_miniapp_launch(event: object, text: str = "") -> dict:
    for button_text, url in _iter_button_links(event):
        summary = _summarize_url(button_text, url)
        if not summary or not _looks_like_fishing_entry(button_text, url, text, summary):
            continue
        token = _start_param_from_url(url)
        if token and _FISH_TOKEN_PATTERN.match(token):
            return {
                "token": token,
                "webview_url": url,
                "entry": summary,
            }
    return {}


def default_miniapp_entry() -> dict:
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


def format_miniapp_entry_block(entry: Optional[dict]) -> str:
    data = entry or {}
    sensitive_keys = data.get("sensitive_keys") or []
    sensitive_keys_text = ", ".join(str(key) for key in sensitive_keys) or "-"
    return "\n".join(
        [
            MINIAPP_ENTRY_MARKER,
            "状态：已捕获入口",
            f"按钮：{_safe_text(data.get('button_text') or '-', 40)}",
            f"Host：{_safe_text(data.get('host') or '-', 80)}",
            f"StartKey：{_safe_text(data.get('start_param_key') or '-', 32)}",
            f"StartKind：{_safe_text(data.get('start_param_kind') or '-', 32)}",
            f"StartSuffix：{_safe_text(data.get('start_param_suffix') or '-', 12)}",
            f"StartDigest：{_safe_text(data.get('start_param_digest') or '-', 20)}",
            f"敏感字段：{sensitive_keys_text}",
            f"边界：{MINIAPP_SAFETY_BOUNDARY}",
        ]
    )


def strip_miniapp_entry_block(text: str) -> str:
    base = str(text or "")
    marker_index = base.find(MINIAPP_ENTRY_MARKER)
    if marker_index < 0:
        return base
    return base[:marker_index].rstrip()


def append_miniapp_entry_block(
    text: str,
    entry: Optional[dict],
    *,
    max_length: int = MAX_FISHING_RESULT_TEXT_LENGTH,
) -> str:
    if not entry:
        return str(text or "")[:max_length]
    base = strip_miniapp_entry_block(text)
    block = format_miniapp_entry_block(entry)
    separator = "\n\n" if base.strip() else ""
    available_base_length = max(max_length - len(separator) - len(block), 0)
    safe_base = base[:available_base_length].rstrip()
    return f"{safe_base}{separator}{block}"[:max_length]


def parse_miniapp_entry_block(text: str) -> dict:
    base = default_miniapp_entry()
    marker_index = str(text or "").find(MINIAPP_ENTRY_MARKER)
    if marker_index < 0:
        return base
    fields = {}
    for line in str(text or "")[marker_index:].splitlines()[1:]:
        if "：" not in line:
            continue
        key, value = line.split("：", 1)
        fields[key.strip()] = value.strip() or "-"
    base.update(
        {
            "status": "captured",
            "status_label": "已捕获入口",
            "button_text": fields.get("按钮", "-"),
            "host": fields.get("Host", "-"),
            "start_param_key": fields.get("StartKey", "-"),
            "start_param_kind": fields.get("StartKind", "-"),
            "start_param_suffix": fields.get("StartSuffix", "-"),
            "start_param_digest": fields.get("StartDigest", "-"),
        }
    )
    sensitive_keys_text = fields.get("敏感字段", "-")
    base["sensitive_keys_text"] = sensitive_keys_text
    base["sensitive_keys"] = (
        []
        if sensitive_keys_text == "-"
        else [item.strip() for item in sensitive_keys_text.split(",") if item.strip()]
    )
    return base
