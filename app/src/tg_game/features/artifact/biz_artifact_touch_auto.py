ARTIFACT_TOUCH_FEATURE_KEY = "artifact_touch"
ARTIFACT_TOUCH_AWAIT_REPLY_STATE = "artifact_touch_await_reply"
ARTIFACT_TOUCH_BOT_COOLDOWN_STATE = "artifact_touch_bot_cooldown"
ARTIFACT_TOUCH_DEFAULT_INTERVAL_SECONDS = 6 * 3600
ARTIFACT_TOUCH_MIN_INTERVAL_SECONDS = 5 * 60


def normalize_artifact_touch_command(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ".抚摸法宝"
    if normalized.startswith("."):
        return normalized[:80]
    return f".抚摸法宝 {normalized}"[:80]


def normalize_artifact_touch_interval(value: object) -> int:
    try:
        interval_seconds = int(value or 0)
    except (TypeError, ValueError):
        interval_seconds = ARTIFACT_TOUCH_DEFAULT_INTERVAL_SECONDS
    return max(interval_seconds, ARTIFACT_TOUCH_MIN_INTERVAL_SECONDS)


def pack_artifact_touch_strategy(command_text: str, interval_seconds: int) -> str:
    command = normalize_artifact_touch_command(command_text)
    interval = normalize_artifact_touch_interval(interval_seconds)
    return f"{interval}|{command}"[:100]


def unpack_artifact_touch_strategy(value: object) -> tuple[str, int]:
    raw = str(value or "").strip()
    if "|" not in raw:
        return (
            normalize_artifact_touch_command(raw),
            ARTIFACT_TOUCH_DEFAULT_INTERVAL_SECONDS,
        )
    interval_text, command_text = raw.split("|", 1)
    return (
        normalize_artifact_touch_command(command_text),
        normalize_artifact_touch_interval(interval_text),
    )
