import json
import re
from typing import Optional


SMALL_WORLD_AUTO_FEATURE_KEY = "small_world_auto"
SMALL_WORLD_PREACH_AUTO_FEATURE_KEY = "small_world_preach_auto"
SMALL_WORLD_PANEL_COMMAND = ".小世界"
SMALL_WORLD_COLLECT_COMMAND = ".收割香火"
SMALL_WORLD_QUENCH_COMMAND = ".神识淬炼"
SMALL_WORLD_MANIFEST_COMMAND = ".显灵"
SMALL_WORLD_PREACH_COMMAND = ".神迹 布道"
SMALL_WORLD_DEFAULT_REFRESH_INTERVAL_SECONDS = 30 * 60
SMALL_WORLD_MIN_REFRESH_INTERVAL_SECONDS = 5 * 60
SMALL_WORLD_DEFAULT_COLLECT_THRESHOLD = 100.0
SMALL_WORLD_MANUAL_COMMANDS = [
    (".小世界", "刷新小世界"),
    (".开辟小世界", "开辟小世界"),
    (SMALL_WORLD_COLLECT_COMMAND, "收割香火"),
    (SMALL_WORLD_MANIFEST_COMMAND, "响应祈愿"),
    (".神庙", "查看神庙"),
    (".升级神庙", "升级神庙"),
    (".护界禁制", "护界禁制"),
    (".神迹 赈灾", "神迹赈灾"),
    (SMALL_WORLD_PREACH_COMMAND, "神迹布道"),
    (".召回灵兽", "召回灵兽"),
]


def _line_value(text: str, label: str) -> str:
    match = re.search(rf"{re.escape(label)}\s*:\s*([^\n]+)", text)
    return match.group(1).strip() if match else ""


def _parse_int(text: str) -> Optional[int]:
    normalized = str(text or "").replace(",", "").strip()
    match = re.search(r"-?\d+", normalized)
    return int(match.group(0)) if match else None


def _parse_float(text: str) -> Optional[float]:
    normalized = str(text or "").replace(",", "").strip()
    match = re.search(r"-?\d+(?:\.\d+)?", normalized)
    return float(match.group(0)) if match else None


def parse_chinese_duration_seconds(text: str) -> int:
    normalized = str(text or "").strip()
    if not normalized:
        return 0
    total = 0
    for pattern, multiplier in (
        (r"(\d+)\s*小时", 3600),
        (r"(\d+)\s*分钟", 60),
        (r"(\d+)\s*秒", 1),
    ):
        for match in re.finditer(pattern, normalized):
            total += int(match.group(1)) * multiplier
    return total


def _parse_ratio_current(text: str) -> Optional[int]:
    match = re.search(r"(-?\d+)\s*/\s*\d+", str(text or ""))
    return int(match.group(1)) if match else None


def parse_small_world_reply(text: str, created_at: float = 0) -> dict:
    normalized = str(text or "").strip()
    view = {
        "available": False,
        "opened": False,
        "owner_name": "",
        "temple_level": "",
        "temple_name": "",
        "population": "",
        "population_value": None,
        "capacity": "",
        "capacity_value": None,
        "faith": "",
        "stability": "",
        "pending_incense": "",
        "pending_incense_value": None,
        "incense_stock": "",
        "incense_stock_value": None,
        "incense_per_hour": "",
        "barrier": "",
        "divine_sense": "",
        "prayer_title": "",
        "prayer_description": "",
        "prayer_cost": "",
        "prayer_cooldown": "",
        "prayer_cooldown_seconds": 0,
        "next_upgrade_cost": "",
        "raw_text": normalized,
        "created_at": float(created_at or 0),
    }
    if not normalized:
        return view

    if "尚未开辟小世界" in normalized:
        view["available"] = True
        return view

    title_match = re.search(r"【([^】]+)的小世界】", normalized)
    temple_match = re.search(r"神庙:\s*Lv\.(\d+)【([^】]+)】", normalized)
    if not title_match and not temple_match:
        return view

    view["available"] = True
    view["opened"] = True
    view["owner_name"] = title_match.group(1).strip() if title_match else ""
    if temple_match:
        view["temple_level"] = temple_match.group(1).strip()
        view["temple_name"] = temple_match.group(2).strip()

    view["population"] = _line_value(normalized, "人口")
    view["population_value"] = _parse_int(view["population"])
    view["capacity"] = _line_value(normalized, "承载上限")
    view["capacity_value"] = _parse_int(view["capacity"])
    view["faith"] = _line_value(normalized, "信仰")
    view["stability"] = _line_value(normalized, "稳定")
    view["pending_incense"] = _line_value(normalized, "待收香火")
    view["pending_incense_value"] = _parse_float(view["pending_incense"])
    view["incense_stock"] = _line_value(normalized, "香火库存")
    view["incense_stock_value"] = _parse_int(view["incense_stock"])
    view["incense_per_hour"] = _line_value(normalized, "预计产出")
    view["barrier"] = _line_value(normalized, "护界禁制")
    view["divine_sense"] = _line_value(normalized, "神识强度")

    prayer_match = re.search(r"凡人祈愿：([^\n]+)", normalized)
    if prayer_match:
        view["prayer_title"] = prayer_match.group(1).strip()
    desc_match = re.search(r"📝\s*([^\n]+)", normalized)
    if desc_match:
        view["prayer_description"] = desc_match.group(1).strip()
    cost_match = re.search(r"显灵消耗:\s*([^\n]+)", normalized)
    if cost_match:
        view["prayer_cost"] = cost_match.group(1).strip()
    cooldown_match = re.search(r"下一次祈愿感应需等待[:：]?\s*([^)）\n]+)", normalized)
    if cooldown_match:
        view["prayer_cooldown"] = cooldown_match.group(1).strip()
        view["prayer_cooldown_seconds"] = parse_chinese_duration_seconds(
            view["prayer_cooldown"]
        )

    upgrade_match = re.search(r"下一阶【([^】]+)】消耗：([^\n]+)", normalized)
    if upgrade_match:
        view["next_upgrade_cost"] = (
            f"{upgrade_match.group(1).strip()}：{upgrade_match.group(2).strip()}"
        )
    return view


def parse_miracle_preach_cooldown_seconds(text: str) -> int:
    match = re.search(r"需再等待\s*([^\n。]+)", str(text or ""))
    if not match:
        return 0
    return parse_chinese_duration_seconds(match.group(1))


def parse_incense_stock_after_collect(text: str) -> Optional[int]:
    normalized = str(text or "").replace(",", "").strip()
    match = re.search(r"当前香火库存\s*[:：]\s*(\d+)", normalized)
    return int(match.group(1)) if match else None


def pack_auto_strategy(
    *,
    collect_enabled: bool = False,
    collect_threshold: float = SMALL_WORLD_DEFAULT_COLLECT_THRESHOLD,
    quench_after_collect_enabled: bool = True,
    manifest_enabled: bool = False,
    preach_enabled: bool = False,
    refresh_interval_seconds: int = SMALL_WORLD_DEFAULT_REFRESH_INTERVAL_SECONDS,
) -> str:
    return json.dumps(
        {
            "c": 1 if collect_enabled else 0,
            "t": max(float(collect_threshold or 0), 0.0),
            "q": 1 if quench_after_collect_enabled else 0,
            "m": 1 if manifest_enabled else 0,
            "p": 1 if preach_enabled else 0,
            "i": max(
                int(refresh_interval_seconds or 0),
                SMALL_WORLD_MIN_REFRESH_INTERVAL_SECONDS,
            ),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def unpack_auto_strategy(value: object) -> dict:
    if isinstance(value, dict):
        raw = value
    else:
        try:
            raw = json.loads(str(value or "").strip() or "{}")
        except (TypeError, json.JSONDecodeError):
            raw = {}
    try:
        threshold = float(
            raw.get("t", raw.get("collect_threshold", SMALL_WORLD_DEFAULT_COLLECT_THRESHOLD))
        )
    except (TypeError, ValueError):
        threshold = SMALL_WORLD_DEFAULT_COLLECT_THRESHOLD
    try:
        interval_seconds = int(
            raw.get(
                "i",
                raw.get(
                    "refresh_interval_seconds",
                    SMALL_WORLD_DEFAULT_REFRESH_INTERVAL_SECONDS,
                ),
            )
        )
    except (TypeError, ValueError):
        interval_seconds = SMALL_WORLD_DEFAULT_REFRESH_INTERVAL_SECONDS
    return {
        "collect_enabled": bool(raw.get("c", raw.get("collect_enabled"))),
        "collect_threshold": max(threshold, 0.0),
        "quench_after_collect_enabled": bool(
            raw.get("q", raw.get("quench_after_collect_enabled", True))
        ),
        "manifest_enabled": bool(raw.get("m", raw.get("manifest_enabled"))),
        "preach_enabled": bool(raw.get("p", raw.get("preach_enabled"))),
        "refresh_interval_seconds": max(
            interval_seconds, SMALL_WORLD_MIN_REFRESH_INTERVAL_SECONDS
        ),
    }


def build_auto_commands(
    panel_state: dict,
    strategy: dict,
    *,
    now: float = 0,
    preach_cooldown_until: float = 0,
) -> list[str]:
    if not panel_state or not panel_state.get("opened"):
        return []
    settings = unpack_auto_strategy(strategy)
    commands: list[str] = []

    pending_incense = panel_state.get("pending_incense_value")
    if (
        settings["collect_enabled"]
        and pending_incense is not None
        and float(pending_incense) >= float(settings["collect_threshold"])
    ):
        commands.append(SMALL_WORLD_COLLECT_COMMAND)

    population_value = int(panel_state.get("population_value") or 0)
    capacity_value = int(panel_state.get("capacity_value") or 0)
    faith_value = _parse_ratio_current(str(panel_state.get("faith") or ""))
    stability_value = _parse_ratio_current(str(panel_state.get("stability") or ""))
    population_full = capacity_value > 0 and population_value >= capacity_value
    faith_full = faith_value is not None and faith_value >= 100
    stability_full = stability_value is not None and stability_value >= 100

    if (
        settings["manifest_enabled"]
        and panel_state.get("prayer_title")
        and not int(panel_state.get("prayer_cooldown_seconds") or 0)
        and not (population_full and faith_full and stability_full)
    ):
        commands.append(SMALL_WORLD_MANIFEST_COMMAND)

    needs_preach = (
        faith_value is not None
        and stability_value is not None
        and (faith_value < 100 or stability_value < 100)
    )
    if (
        settings["preach_enabled"]
        and needs_preach
        and float(preach_cooldown_until or 0) <= float(now or 0)
    ):
        commands.append(SMALL_WORLD_PREACH_COMMAND)

    return commands
