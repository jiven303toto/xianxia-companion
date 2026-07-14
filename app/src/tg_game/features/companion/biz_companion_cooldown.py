import json
from datetime import datetime, timezone
from typing import Optional


DREAM_SEEK_FEATURE_KEY = "dream_seek"
DIVINATION_CHAIN_FEATURE_KEY = "divination_chain"
WILD_EXPERIENCE_FEATURE_KEY = "wild_experience"

SIMPLE_COOLDOWN_AUTO_FEATURES = {
    DREAM_SEEK_FEATURE_KEY: {
        "label": "入梦寻图",
        "command": ".入梦寻图",
        "payload_field": "last_dream_map_seek_time",
        "cooldown_hours": 8,
        "payload_scope": "companion",
    },
    DIVINATION_CHAIN_FEATURE_KEY: {
        "label": "天机代卜",
        "command": ".天机代卜",
        "payload_field": "last_divination_chain_time",
        "cooldown_hours": 12,
        "payload_scope": "companion",
    },
    WILD_EXPERIENCE_FEATURE_KEY: {
        "label": "野外历练",
        "command": ".野外历练",
        "payload_field": "last_wild_experience_time",
        "cooldown_hours": 2,
        "payload_scope": "root",
    },
}

WILD_EXPERIENCE_STRATEGY_OPTIONS = ("谨慎", "均衡", "深入")


def normalize_wild_experience_strategy(value: object) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized in WILD_EXPERIENCE_STRATEGY_OPTIONS else "均衡"


def parse_iso_to_ts(raw_value: object) -> float:
    text = str(raw_value or "").strip()
    if not text:
        return 0.0
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).timestamp()


def _coerce_dict_value(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def resolve_simple_cooldown_next_run_at(
    payload: dict,
    feature_key: str,
) -> Optional[float]:
    feature = SIMPLE_COOLDOWN_AUTO_FEATURES.get(feature_key) or {}
    payload_field = str(feature.get("payload_field") or "").strip()
    cooldown_hours = int(feature.get("cooldown_hours") or 0)
    payload_scope = str(feature.get("payload_scope") or "companion").strip()
    if cooldown_hours <= 0 or not payload_field:
        return None
    if payload_scope == "root":
        if payload_field not in payload:
            return None
        last_ts = parse_iso_to_ts(payload.get(payload_field))
        if last_ts <= 0:
            return 0.0
        return last_ts + cooldown_hours * 3600

    companion = _coerce_dict_value((payload or {}).get("companion"))
    dongfu = _coerce_dict_value((payload or {}).get("dongfu"))
    companion_residence = _coerce_dict_value(dongfu.get("companion_residence"))
    if payload_field in companion:
        raw_value = companion.get(payload_field)
    elif payload_field in companion_residence:
        raw_value = companion_residence.get(payload_field)
    else:
        return None
    last_ts = parse_iso_to_ts(raw_value)
    if last_ts <= 0:
        return None
    return last_ts + cooldown_hours * 3600
