import json
from datetime import datetime, timezone
from typing import Optional


XINGGONG_STARBOARD_FEATURE_KEY = "xinggong_starboard"
XINGGONG_STARBOARD_DEFAULT_STAR = "庚金星"
XINGGONG_STARBOARD_RECHECK_SECONDS = 300
XINGGONG_STARBOARD_READY_CHECK_SECONDS = 10
XINGGONG_STARBOARD_PENDING_CHECK_SECONDS = 60
XINGGONG_STARBOARD_COOLDOWN_BUFFER_SECONDS = 60
XINGGONG_STARBOARD_HEALTH_CHECK_SECONDS = 30 * 60
XINGGONG_STARBOARD_COMMAND_DELAY_SECONDS = 3
XINGGONG_STARBOARD_PULL_PREFIX = ".牵引星辰"
XINGGONG_STARBOARD_COMFORT_COMMAND = ".安抚星辰"
XINGGONG_STARBOARD_COLLECT_COMMAND = ".收集精华"
XINGGONG_STARBOARD_INSUFFICIENT_ERROR = (
    "修为不足，已自动关闭自动引星盘，避免重复牵引。"
)

XINGGONG_STAR_INFOS = (
    ("赤血星", 4, "无"),
    ("庚金星", 6, "无"),
    ("建木星", 8, "无"),
    ("天雷星", 36, "星宫长老"),
    ("帝魂星", 48, "星宫双圣"),
)
XINGGONG_STAR_OPTIONS = tuple(name for name, _hours, _requirement in XINGGONG_STAR_INFOS)
XINGGONG_STAR_DURATIONS = {
    name: hours * 3600 for name, hours, _requirement in XINGGONG_STAR_INFOS
}


def normalize_starboard_target(value: object) -> str:
    normalized = str(value or "").strip()
    if normalized in XINGGONG_STAR_DURATIONS:
        return normalized
    return XINGGONG_STARBOARD_DEFAULT_STAR


def coerce_dict_value(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def get_starboard_platform(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    return coerce_dict_value(payload.get("star_platform"))


def get_starboard_plots(payload: dict) -> dict:
    plots = coerce_dict_value(get_starboard_platform(payload).get("plots"))
    return plots if isinstance(plots, dict) else {}


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


def _sort_key(raw_key: object) -> int:
    try:
        return int(str(raw_key))
    except (TypeError, ValueError):
        return 9999


def build_starboard_plot_state(
    plot_id: object,
    plot: object,
    *,
    now: float,
) -> Optional[dict]:
    slot = str(plot_id).strip()
    if not slot:
        return None
    if plot is None:
        return {
            "slot": slot,
            "empty_slot": True,
            "star_name": "",
            "status": "",
            "raw_status": "",
            "status_is_empty": True,
            "start_ts": 0.0,
            "cooldown_total": 0,
            "cooldown_remaining": 0,
            "cd_expired": False,
            "needs_comfort": False,
            "collectable": False,
            "condensing": False,
            "is_ready": True,
        }
    if not isinstance(plot, dict):
        return None

    star_name = str(plot.get("star_name") or "").strip()
    raw_status_value = plot.get("status")
    status = str(raw_status_value or "").strip()
    start_ts = parse_iso_to_ts(plot.get("start_time"))
    cooldown_total = XINGGONG_STAR_DURATIONS.get(star_name, 0)
    cooldown_remaining = 0
    if start_ts > 0 and cooldown_total > 0:
        cooldown_remaining = max(int(start_ts + cooldown_total - now), 0)

    cd_expired = start_ts > 0 and cooldown_remaining <= 0
    status_is_empty = raw_status_value is None or status == ""
    needs_comfort = status in {"元磁紊乱", "星光黯淡"}
    collectable = status in {"可收集", "精华已成"} or (
        status == "凝聚中" and cd_expired
    )
    condensing = status == "凝聚中" and not cd_expired
    is_ready = (
        status_is_empty
        and cooldown_remaining <= 0
        and not collectable
        and not condensing
    )

    return {
        "slot": slot,
        "empty_slot": False,
        "star_name": star_name,
        "status": status,
        "raw_status": status,
        "status_is_empty": status_is_empty,
        "start_ts": start_ts,
        "cooldown_total": cooldown_total,
        "cooldown_remaining": cooldown_remaining,
        "cd_expired": cd_expired,
        "needs_comfort": needs_comfort,
        "collectable": collectable,
        "condensing": condensing,
        "is_ready": is_ready,
    }


def iter_starboard_plot_states(payload: dict, *, now: float) -> list[dict]:
    states = []
    plots = get_starboard_plots(payload)
    for plot_id in sorted(plots.keys(), key=_sort_key):
        state = build_starboard_plot_state(plot_id, plots.get(plot_id), now=now)
        if state is not None:
            states.append(state)
    return states


def build_starboard_next_check_time(payload: dict, now: float) -> float:
    states = iter_starboard_plot_states(payload, now=now)
    if not states:
        return now + XINGGONG_STARBOARD_RECHECK_SECONDS

    next_candidates: list[float] = []
    for state in states:
        if (
            state["empty_slot"]
            or state["needs_comfort"]
            or state["collectable"]
            or state["is_ready"]
        ):
            return now + XINGGONG_STARBOARD_READY_CHECK_SECONDS
        if (
            state["cooldown_remaining"] > 0
            and state["start_ts"] > 0
            and state["cooldown_total"] > 0
        ):
            next_candidates.append(
                state["start_ts"]
                + state["cooldown_total"]
                + XINGGONG_STARBOARD_COOLDOWN_BUFFER_SECONDS
            )

    if next_candidates:
        return max(
            now + XINGGONG_STARBOARD_READY_CHECK_SECONDS,
            min(min(next_candidates), now + XINGGONG_STARBOARD_HEALTH_CHECK_SECONDS),
        )
    return now + XINGGONG_STARBOARD_RECHECK_SECONDS


def build_starboard_commands(
    payload: dict, target_star: str, now: float
) -> tuple[list[str], Optional[float]]:
    target = normalize_starboard_target(target_star)
    states = iter_starboard_plot_states(payload, now=now)
    if not states:
        return [], None

    commands: list[str] = []
    next_candidates: list[float] = []
    needs_comfort_command = False
    needs_collect_command = False
    needs_pull_command = False

    for state in states:
        if state["empty_slot"]:
            needs_pull_command = True
            continue
        if state["needs_comfort"]:
            needs_comfort_command = True
            if state["start_ts"] > 0 and state["cooldown_remaining"] > 0:
                next_candidates.append(now + state["cooldown_remaining"])
                continue
            if state["cd_expired"]:
                needs_collect_command = True
                needs_pull_command = True
            continue
        if state["collectable"]:
            needs_collect_command = True
            needs_pull_command = True
            continue
        if state["is_ready"]:
            needs_pull_command = True
            continue
        if state["condensing"] and state["cooldown_remaining"] > 0:
            next_candidates.append(now + state["cooldown_remaining"])

    if needs_comfort_command:
        commands.append(XINGGONG_STARBOARD_COMFORT_COMMAND)
    if needs_collect_command:
        commands.append(XINGGONG_STARBOARD_COLLECT_COMMAND)
    if needs_pull_command:
        commands.append(f"{XINGGONG_STARBOARD_PULL_PREFIX} {target}")

    return commands, min(next_candidates) if next_candidates else None


def build_starboard_pending_candidates(
    payload: dict, target_star: str, commands: list[str]
) -> list[str]:
    target = normalize_starboard_target(target_star)
    candidates = list(commands)
    for plot_id in get_starboard_plots(payload).keys():
        slot = str(plot_id).strip()
        if not slot:
            continue
        candidates.extend(
            [
                f"{XINGGONG_STARBOARD_COMFORT_COMMAND} {slot}",
                f"{XINGGONG_STARBOARD_COLLECT_COMMAND} {slot}",
                f"{XINGGONG_STARBOARD_PULL_PREFIX} {slot} {target}",
            ]
        )
    return list(dict.fromkeys(candidates))


def is_starboard_insufficient_reply(text: str) -> bool:
    normalized = " ".join(str(text or "").split())
    return (
        "修为不足" in normalized
        and "牵引" in normalized
        and "引星盘" in normalized
        and "需要" in normalized
        and "你拥有" in normalized
    )


def is_starboard_success_reply(text: str) -> bool:
    normalized = " ".join(str(text or "").split())
    return "牵引成功" in normalized and "引星盘" in normalized


def extract_starboard_pull_target(command_text: str) -> str:
    normalized = str(command_text or "").strip()
    if not (
        normalized == XINGGONG_STARBOARD_PULL_PREFIX
        or normalized.startswith(f"{XINGGONG_STARBOARD_PULL_PREFIX} ")
    ):
        return ""
    parts = normalized.split()
    return parts[-1] if len(parts) >= 2 else ""


def is_starboard_pull_command_for_target(command_text: str, target_star: str) -> bool:
    target = str(target_star or "").strip()
    return bool(target) and extract_starboard_pull_target(command_text) == target


def build_star_options(sect_position: object, inventory: object) -> list[dict]:
    position = str(sect_position or "")
    is_elder = "长老" in position or "双圣" in position
    is_shuangsheng = "双圣" in position
    has_bottle = False
    if isinstance(inventory, dict):
        items = inventory.get("items") or []
        for item in items:
            if isinstance(item, dict) and item.get("item_id") == "zhangtianping":
                has_bottle = True
                break

    options = []
    for name, hours, requirement in XINGGONG_STAR_INFOS:
        disabled = False
        disabled_reason = ""
        if requirement == "星宫长老" and not is_elder and not has_bottle:
            disabled = True
            disabled_reason = "需要星宫长老或掌天瓶"
        elif requirement == "星宫双圣" and not is_shuangsheng and not has_bottle:
            disabled = True
            disabled_reason = "需要星宫双圣或掌天瓶"
        label = f"{name}（{hours}小时）"
        if disabled:
            label += f" — {disabled_reason}"
        options.append(
            {
                "value": name,
                "label": label,
                "disabled": disabled,
            }
        )
    return options
