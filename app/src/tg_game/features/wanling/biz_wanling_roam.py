import json
from datetime import datetime, timezone
from typing import Optional


WANLING_ROAM_FEATURE_KEY = "wanling_roam"
WANLING_ROAM_COMMAND = ".一键放养"
WANLING_ROAM_MAX_BEASTS = 10
WANLING_ROAM_STRATEGY_PREFIX = "v1|"
WANLING_ROAM_COMMAND_SEQUENCE = (WANLING_ROAM_COMMAND,)
WANLING_ROAM_LEGACY_COMMAND_SEQUENCE = (
    ".灵兽巡游 猪皮",
    ".灵兽巡游 哈皮",
    ".灵兽互动 哈皮 安抚",
    ".灵兽互动 猪皮 安抚",
    WANLING_ROAM_COMMAND,
)
WANLING_ROAM_RETURN_BUFFER_SECONDS = 10 * 60
WANLING_ROAM_DURATION_SECONDS = 4 * 3600 + WANLING_ROAM_RETURN_BUFFER_SECONDS
WANLING_ROAM_AUTO_AFTER_RETURN_SECONDS = 10 * 60
WANLING_ROAM_RECHECK_SECONDS = 300
WANLING_ROAM_POST_SEND_GRACE_SECONDS = 1800
WANLING_ROAM_COMMAND_DELAY_SECONDS = 10


def is_wanling_profile(profile: object) -> bool:
    return str(getattr(profile, "sect_name", "") or "").strip() == "万灵宗"


def _coerce_list_value(value: object) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _normalize_beast_name(value: object) -> str:
    return (
        str(value or "")
        .replace("|", "")
        .replace(",", "")
        .replace("\n", "")
        .strip()
    )


def normalize_wanling_roam_beast_names(values: object) -> list[str]:
    raw_values = values if isinstance(values, (list, tuple)) else _coerce_list_value(values)
    names = []
    seen = set()
    for value in raw_values:
        name = _normalize_beast_name(value)
        if not name or name in seen:
            continue
        names.append(name)
        seen.add(name)
        if len(names) >= WANLING_ROAM_MAX_BEASTS:
            break
    return names


def pack_wanling_roam_strategy(beast_names: object) -> str:
    packed_names = []
    for name in normalize_wanling_roam_beast_names(beast_names):
        candidate = WANLING_ROAM_STRATEGY_PREFIX + ",".join([*packed_names, name])
        if len(candidate) > 100:
            break
        packed_names.append(name)
    if not packed_names:
        return ""
    return WANLING_ROAM_STRATEGY_PREFIX + ",".join(packed_names)


def unpack_wanling_roam_strategy(strategy: object) -> list[str]:
    text = str(strategy or "").strip()
    if not text:
        return []
    if text.startswith(WANLING_ROAM_STRATEGY_PREFIX):
        return normalize_wanling_roam_beast_names(
            text[len(WANLING_ROAM_STRATEGY_PREFIX) :].split(",")
        )
    return normalize_wanling_roam_beast_names(text.split(","))


def build_wanling_roam_command_sequence(
    strategy: object, payload: Optional[dict] = None
) -> tuple[str, ...]:
    beast_names = unpack_wanling_roam_strategy(strategy)
    if payload is not None:
        available_names = list_spirit_beast_names(payload if isinstance(payload, dict) else {})
        available_set = set(available_names)
        beast_names = [name for name in beast_names if name in available_set]
    commands = [
        *(f".灵兽巡游 {name}" for name in beast_names),
        *(f".灵兽互动 {name} 安抚" for name in beast_names),
        WANLING_ROAM_COMMAND,
    ]
    return tuple(commands)


def build_wanling_roam_cancel_commands(strategy: object) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            [
                *build_wanling_roam_command_sequence(strategy),
                *WANLING_ROAM_LEGACY_COMMAND_SEQUENCE,
            ]
        )
    )


def parse_wanling_roam_timestamp(raw_value: object) -> float:
    if raw_value is None:
        return 0.0
    if isinstance(raw_value, (int, float)):
        return float(raw_value or 0)
    text = str(raw_value or "").strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except (TypeError, ValueError):
        pass
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).timestamp()


def list_spirit_beasts(payload: dict) -> list[dict]:
    return [
        beast
        for beast in _coerce_list_value((payload or {}).get("spirit_beasts"))
        if isinstance(beast, dict)
    ]


def list_spirit_beast_names(payload: dict) -> list[str]:
    return normalize_wanling_roam_beast_names(
        [beast.get("name") or beast.get("id") for beast in list_spirit_beasts(payload)]
    )


def resolve_wanling_roam_next_finish_at(
    payload: dict,
    *,
    now: float,
) -> Optional[float]:
    beasts = list_spirit_beasts(payload)
    if not beasts:
        return None
    finish_candidates = []
    for beast in beasts:
        finish_ts = parse_wanling_roam_timestamp(beast.get("mission_finish_time"))
        if finish_ts > 0:
            finish_ts += WANLING_ROAM_RETURN_BUFFER_SECONDS
        else:
            last_roam_ts = parse_wanling_roam_timestamp(beast.get("last_roam_time"))
            if last_roam_ts > 0:
                finish_ts = last_roam_ts + WANLING_ROAM_DURATION_SECONDS
        if finish_ts > now:
            finish_candidates.append(finish_ts)
    return min(finish_candidates) if finish_candidates else 0.0
