from copy import deepcopy
import time
from typing import Optional
from .biz_estate_constants import MINIAPP_HUNT_SAFETY_BOUNDARY, MINIAPP_SAFETY_BOUNDARY
from .biz_estate_safety import _safe_text

def _miniapp_safe_text(value: object, max_length: int = 80) -> str:
    return _safe_text(value, max_length)


def _sanitize_estate_miniapp_secret_text(text: object, *, limit: int = 220) -> str:
    from .biz_estate_miniapp import sanitize_estate_miniapp_secret_text
    return sanitize_estate_miniapp_secret_text(text, limit=limit)


def _format_sync_time(value: object) -> str:
    if isinstance(value, bool) or value in (None, ""):
        return ""
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp <= 0:
            return ""
        if timestamp > 10_000_000_000:
            timestamp = timestamp / 1000
        try:
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(timestamp))
        except (OverflowError, OSError, ValueError):
            return ""
    text = _miniapp_safe_text(value, 40)
    return "" if text in {"-", "0"} else text


def _stamp_snapshot_sync_time(raw_value: object) -> object:
    if not isinstance(raw_value, dict):
        return raw_value
    stamped = dict(raw_value)
    if not _format_sync_time(stamped.get("updated_at") or stamped.get("updatedAt")):
        stamped["updated_at"] = time.time()
    return stamped


def _as_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _as_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _int_or_zero(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _coerce_dict(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _coerce_list(value: object) -> list:
    return value if isinstance(value, list) else []


def _first_text(*values: object) -> str:
    for value in values:
        text = _miniapp_safe_text(value, 80)
        if text:
            return text
    return ""


def _normalize_hunt_loot(value: object) -> list[dict]:
    normalized = []
    for item in _as_list(value):
        if not isinstance(item, dict):
            continue
        name = _first_text(item.get("name"), item.get("label"), item.get("itemId"))
        quantity = _int_or_zero(item.get("quantity") or item.get("count") or 1)
        if name:
            normalized.append(
                {
                    "name": name,
                    "quantity": max(quantity, 1),
                    "is_material": bool(item.get("isMaterial") or item.get("is_material")),
                }
            )
    return normalized[:12]


def _hunt_loot_text(loot: list[dict]) -> str:
    if not loot:
        return "-"
    return "、".join(
        f"{item['name']} x{item['quantity']}" for item in loot if item.get("name")
    ) or "-"


def _hunt_status_label(status: object) -> str:
    labels = {
        "queued": "等待回包",
        "synced": "已同步",
        "settled": "已结算",
        "failed": "失败",
        "limit_reached": "已达上限",
    }
    clean_status = _miniapp_safe_text(status or "unknown", 32)
    return labels.get(clean_status, clean_status or "未知")


def _hunt_chance_text(used: object, limit: object, remaining: object) -> str:
    used_value = _int_or_zero(used)
    limit_value = _int_or_zero(limit)
    remaining_value = _int_or_zero(remaining)
    if not limit_value:
        return "-"
    return f"{used_value}/{limit_value}，剩余{remaining_value}"


def _hunt_ap_text(ap: object, max_ap: object) -> str:
    ap_value = _int_or_zero(ap)
    max_ap_value = _int_or_zero(max_ap)
    if max_ap_value:
        return f"{ap_value}/{max_ap_value}"
    if ap_value:
        return str(ap_value)
    return "-"


def _hunt_failure_step(events: object) -> str:
    for event in reversed(_as_list(events)):
        event_data = _as_dict(event)
        if event_data and not event_data.get("ok"):
            return _miniapp_safe_text(event_data.get("step") or "-", 40)
    return "-"


def _merge_hunt_loot(*loot_lists: object) -> list[dict]:
    totals: dict[tuple[str, bool], dict] = {}
    for loot_list in loot_lists:
        for item in _normalize_hunt_loot(loot_list):
            key = (str(item.get("name") or ""), bool(item.get("is_material")))
            if not key[0]:
                continue
            entry = totals.setdefault(
                key,
                {"name": key[0], "quantity": 0, "is_material": key[1]},
            )
            entry["quantity"] += _int_or_zero(item.get("quantity"))
    return list(totals.values())[:12]


def _hunt_logs(value: object) -> list[str]:
    logs = []
    for item in _as_list(value):
        text = _sanitize_estate_miniapp_secret_text(item, limit=120)
        if text:
            logs.append(text)
    return logs[-6:]


def _build_hunt_round_summary(hunt: object, *, round_number: int) -> dict:
    hunt_data = _as_dict(hunt)
    status = _miniapp_safe_text(hunt_data.get("status") or "unknown", 32)
    ap_value = _int_or_zero(
        hunt_data.get("ap_value") if "ap_value" in hunt_data else hunt_data.get("ap")
    )
    max_ap = _int_or_zero(hunt_data.get("max_ap"))
    used = _int_or_zero(hunt_data.get("used"))
    limit = _int_or_zero(hunt_data.get("limit"))
    remaining = _int_or_zero(hunt_data.get("remaining"))
    chance_text = _hunt_chance_text(used, limit, remaining)
    if chance_text == "-":
        chance_text = _miniapp_safe_text(hunt_data.get("chance_text") or "-", 80)
    loot = (
        _normalize_hunt_loot(hunt_data.get("loot"))
        if status == "settled"
        else []
    )
    loot_text = _hunt_loot_text(loot)
    if status == "settled" and not loot:
        loot_text = _miniapp_safe_text(hunt_data.get("loot_text") or "-", 160)
    failure_step = _hunt_failure_step(hunt_data.get("events"))
    if failure_step == "-":
        failure_step = _miniapp_safe_text(hunt_data.get("failure_step") or "-", 40)
    return {
        "number": max(1, _int_or_zero(round_number)),
        "title": f"第{max(1, _int_or_zero(round_number))}轮",
        "status": status,
        "status_label": _hunt_status_label(status),
        "ended_at": _format_sync_time(hunt_data.get("updated_at")) or "-",
        "used": used,
        "limit": limit,
        "remaining": remaining,
        "chance_text": chance_text,
        "ap": _hunt_ap_text(ap_value, max_ap),
        "ap_value": ap_value,
        "max_ap": max_ap,
        "revealed_count": str(_int_or_zero(hunt_data.get("revealed_count"))),
        "grade": _first_text(hunt_data.get("grade")) or "-",
        "score": str(_int_or_zero(hunt_data.get("score")))
        if hunt_data.get("score") not in (None, "")
        else "-",
        "contribution": str(_int_or_zero(hunt_data.get("contribution")))
        if hunt_data.get("contribution") not in (None, "")
        else "0",
        "found_main_label": "已命中" if hunt_data.get("found_main") else "未命中",
        "loot": loot,
        "loot_text": loot_text,
        "error": _sanitize_estate_miniapp_secret_text(hunt_data.get("error") or ""),
        "failure_step": failure_step,
    }


def _normalize_hunt_rounds(value: object) -> list[dict]:
    rounds = []
    for index, item in enumerate(_as_list(value)[:8], start=1):
        round_data = _as_dict(item)
        if not round_data:
            continue
        number = _int_or_zero(round_data.get("number")) or index
        rounds.append(_build_hunt_round_summary(round_data, round_number=number))
    return rounds


def _legacy_hunt_rounds(
    raw: dict,
    *,
    status: str,
    used: int,
    limit: int,
    remaining: int,
    ap: int,
    max_ap: int,
    total_loot_text: str,
) -> list[dict]:
    runs_completed = _int_or_zero(raw.get("automation_runs"))
    rows = []
    if runs_completed > 0:
        rows.append(
            {
                "number": 1,
                "title": f"前{runs_completed}轮",
                "status": "settled",
                "status_label": "已结算",
                "chance_text": "旧记录未保存",
                "ap": "-",
                "ap_value": 0,
                "max_ap": 0,
                "revealed_count": "-",
                "grade": "-",
                "score": "-",
                "contribution": str(
                    _int_or_zero(raw.get("automation_total_contribution"))
                ),
                "found_main_label": "未保存",
                "loot": [],
                "loot_text": total_loot_text,
                "error": "",
                "failure_step": "-",
                "note": "旧记录只保存成功轮累计，无法还原每一轮的单独奖励和神识。",
            }
        )
    if status == "failed":
        failed_number = used if used > runs_completed else runs_completed + 1
        rows.append(
            {
                "number": failed_number,
                "title": f"第{failed_number}轮",
                "status": "failed",
                "status_label": "失败",
                "chance_text": _hunt_chance_text(used, limit, remaining),
                "ap": _hunt_ap_text(ap, max_ap),
                "ap_value": ap,
                "max_ap": max_ap,
                "revealed_count": str(_int_or_zero(raw.get("revealed_count"))),
                "grade": _first_text(raw.get("grade")) or "-",
                "score": str(_int_or_zero(raw.get("score")))
                if raw.get("score") not in (None, "")
                else "-",
                "contribution": str(_int_or_zero(raw.get("contribution")))
                if raw.get("contribution") not in (None, "")
                else "0",
                "found_main_label": "已命中" if raw.get("found_main") else "未命中",
                "loot": _normalize_hunt_loot(raw.get("loot")),
                "loot_text": _miniapp_safe_text(raw.get("loot_text") or "-", 160),
                "error": _sanitize_estate_miniapp_secret_text(raw.get("error") or ""),
                "failure_step": "-",
                "note": "这轮是旧记录保留下来的最后一轮状态。",
            }
        )
    return rows


def _format_number(value: object) -> str:
    if value is None or value == "":
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _miniapp_safe_text(value, 32)
    if number.is_integer():
        return str(int(number))
    return str(round(number, 2)).rstrip("0").rstrip(".")


def _format_pool(value: object) -> str:
    if isinstance(value, dict):
        current = _format_number(
            value.get("current")
            or value.get("value")
            or value.get("amount")
            or value.get("used")
        )
        maximum = _format_number(
            value.get("max")
            or value.get("maximum")
            or value.get("capacity")
            or value.get("total")
        )
        if current and maximum:
            return f"{current} / {maximum}"
        return current or maximum
    return _miniapp_safe_text(value, 40)


def _format_count(value: object) -> str:
    if isinstance(value, dict):
        used = _format_number(value.get("used") or value.get("current") or value.get("count"))
        maximum = _format_number(value.get("max") or value.get("maximum") or value.get("total"))
        if used and maximum:
            return f"{used}/{maximum}"
        return used or maximum
    return _miniapp_safe_text(value, 40)


def _format_scenery_count(raw: dict, metrics: dict) -> str:
    explicit = (
        raw.get("scenery_count")
        or raw.get("sceneryCount")
        or metrics.get("sceneryCount")
    )
    text = _format_count(explicit)
    if text:
        return text
    placed = raw.get("placedScenery")
    scenery = raw.get("scenery")
    if isinstance(placed, list) and isinstance(scenery, list):
        return f"{len(placed)}/{len(scenery)}"
    if isinstance(placed, list):
        maximum = _format_number(raw.get("visualCapacity"))
        return f"{len(placed)}/{maximum}" if maximum else str(len(placed))
    return ""


def _material_text(value: object) -> str:
    if isinstance(value, bool):
        return "材料已足" if value else "材料不足"
    return _miniapp_safe_text(value, 80)


def _upgrade_materials_text(value: object) -> str:
    upgrade = _coerce_dict(value)
    if not upgrade:
        return ""
    if upgrade.get("maxed"):
        return "已满级"
    if isinstance(upgrade.get("canUpgrade"), bool):
        return "材料已足" if upgrade.get("canUpgrade") else "材料不足"
    cost = _coerce_list(upgrade.get("cost"))
    missing = [
        _miniapp_safe_text(item.get("text") or item.get("name"), 32)
        for item in cost
        if isinstance(item, dict) and int(item.get("missing") or 0) > 0
    ]
    return "缺 " + "、".join(item for item in missing if item) if missing else ""


def _facility_view(value: object) -> dict:
    facility = _coerce_dict(value)
    upgrade = _coerce_dict(facility.get("upgrade"))
    name = _first_text(
        facility.get("name"),
        facility.get("label"),
        facility.get("title"),
        facility.get("key"),
    )
    level = _first_text(facility.get("level_text"), facility.get("level"))
    if level and level.isdigit():
        level = f"Lv. {level}"
    return {
        "name": name or "-",
        "level": level or "-",
        "summary": _first_text(
            facility.get("summary"),
            facility.get("description"),
            facility.get("grade"),
            facility.get("flavor"),
        ),
        "next": _first_text(
            facility.get("next"),
            facility.get("next_name"),
            upgrade.get("nextName"),
            upgrade.get("currentName"),
        ),
        "materials": _material_text(
            facility.get("materials_text")
            if "materials_text" in facility
            else facility.get("materials")
            if "materials" in facility
            else facility.get("materialsReady")
        )
        or _upgrade_materials_text(upgrade),
    }


def default_estate_miniapp_hunt() -> dict:
    return {
        "status": "not_requested",
        "status_label": "未执行",
        "updated_at": "-",
        "strategy_label": "耗尽神识",
        "automation_status": "未启动",
        "automation_runs": 0,
        "automation_total_loot": [],
        "automation_total_loot_text": "-",
        "automation_total_contribution": "0",
        "automation_started_at": "-",
        "automation_completed_at": "-",
        "rounds": [],
        "legacy_rounds": [],
        "rounds_note": "",
        "grade": "-",
        "score": "-",
        "contribution": "-",
        "found_main": False,
        "found_main_label": "未命中",
        "ap": "-",
        "ap_value": 0,
        "max_ap": 0,
        "revealed_count": "-",
        "remaining": 0,
        "used": 0,
        "limit": 0,
        "chance_text": "-",
        "loot": [],
        "loot_text": "-",
        "latest_hint": "-",
        "logs": [],
        "error": "",
        "safety_boundary": MINIAPP_HUNT_SAFETY_BOUNDARY,
    }


def build_estate_miniapp_hunt(value: object) -> dict:
    raw = _coerce_dict(value)
    base = default_estate_miniapp_hunt()
    if not raw:
        return base
    status = _miniapp_safe_text(raw.get("status") or "unknown", 32)
    remaining = _int_or_zero(raw.get("remaining"))
    used = _int_or_zero(raw.get("used"))
    limit = _int_or_zero(raw.get("limit"))
    chance_text = _hunt_chance_text(used, limit, remaining)
    if chance_text == "-":
        chance_text = _miniapp_safe_text(raw.get("chance_text") or "-", 80)
    ap = _int_or_zero(raw.get("ap_value") if "ap_value" in raw else raw.get("ap"))
    max_ap = _int_or_zero(raw.get("max_ap"))
    ap_text = _hunt_ap_text(ap, max_ap)
    rounds = _normalize_hunt_rounds(raw.get("rounds"))
    last_round_settled = bool(rounds and rounds[-1].get("status") == "settled")
    loot = (
        _normalize_hunt_loot(raw.get("loot"))
        if status != "failed" and (not rounds or last_round_settled)
        else []
    )
    total_loot = (
        _merge_hunt_loot(
            *(
                round_data.get("loot")
                for round_data in rounds
                if round_data.get("status") == "settled"
            )
        )
        if rounds
        else _merge_hunt_loot(raw.get("automation_total_loot"))
    )
    total_loot_text = (
        _hunt_loot_text(total_loot)
        if total_loot
        else (
            "-"
            if rounds
            else _miniapp_safe_text(
                raw.get("automation_total_loot_text") or "-", 160
            )
        )
    )
    loot_text = (
        _hunt_loot_text(loot)
        if loot
        else (
            "-"
            if rounds or status == "failed"
            else _miniapp_safe_text(raw.get("loot_text") or "-", 160)
        )
    )
    legacy_rounds = []
    if not rounds and status not in {"not_requested", "queued"}:
        legacy_rounds = _legacy_hunt_rounds(
            raw,
            status=status,
            used=used,
            limit=limit,
            remaining=remaining,
            ap=ap,
            max_ap=max_ap,
            total_loot_text=total_loot_text,
        )
    base.update(
        {
            "status": status,
            "status_label": _hunt_status_label(status),
            "updated_at": _format_sync_time(raw.get("updated_at")) or "-",
            "automation_status": _miniapp_safe_text(
                raw.get("automation_status") or base["automation_status"], 80
            ),
            "automation_runs": _int_or_zero(raw.get("automation_runs")),
            "automation_total_loot": total_loot,
            "automation_total_loot_text": total_loot_text,
            "automation_total_contribution": str(
                _int_or_zero(raw.get("automation_total_contribution"))
            ),
            "automation_started_at": _format_sync_time(
                raw.get("automation_started_at")
            )
            or "-",
            "automation_completed_at": _format_sync_time(
                raw.get("automation_completed_at")
            )
            or "-",
            "rounds": rounds,
            "legacy_rounds": legacy_rounds,
            "rounds_note": ""
            if rounds or legacy_rounds or status in {"not_requested", "queued"}
            else "本次旧记录未保存每轮明细；后续执行会自动记录。",
            "grade": _first_text(raw.get("grade")) or "-",
            "score": str(_int_or_zero(raw.get("score")))
            if raw.get("score") not in (None, "")
            else "-",
            "contribution": str(_int_or_zero(raw.get("contribution")))
            if raw.get("contribution") not in (None, "")
            else "-",
            "found_main": bool(raw.get("found_main")),
            "found_main_label": "已命中" if raw.get("found_main") else "未命中",
            "ap": ap_text,
            "ap_value": ap,
            "max_ap": max_ap,
            "revealed_count": str(_int_or_zero(raw.get("revealed_count")))
            if raw.get("revealed_count") not in (None, "")
            else "-",
            "remaining": remaining,
            "used": used,
            "limit": limit,
            "chance_text": chance_text,
            "loot": loot,
            "loot_text": loot_text,
            "latest_hint": _miniapp_safe_text(raw.get("latest_hint") or "-", 160),
            "logs": _hunt_logs(raw.get("logs")),
            "error": _sanitize_estate_miniapp_secret_text(raw.get("error") or ""),
        }
    )
    return base


def default_estate_miniapp_snapshot() -> dict:
    return {
        "status": "not_seen",
        "status_label": "未同步",
        "name": "-",
        "owner": "-",
        "stage": "-",
        "lingqi_pool": "-",
        "lingmai_rate": "-",
        "jingshi_conversion": "-",
        "array_mode": "-",
        "scenery_count": "-",
        "facilities": [],
        "updated_at": "-",
        "safety_boundary": MINIAPP_SAFETY_BOUNDARY,
    }


def build_estate_miniapp_snapshot(raw_value: object) -> dict:
    raw = _coerce_dict(raw_value)
    base = default_estate_miniapp_snapshot()
    if not raw:
        return base
    metrics = _coerce_dict(raw.get("metrics"))
    formation = _coerce_dict(raw.get("formation"))
    pool = raw.get("lingqiPool") or raw.get("lingqi_pool") or raw.get("auraPool")
    facilities = [
        _facility_view(item)
        for item in _coerce_list(raw.get("facilities") or raw.get("buildings"))
    ]
    base.update(
        {
            "status": "captured",
            "status_label": "已同步",
            "name": _first_text(raw.get("name"), raw.get("title"), raw.get("dongfuName")) or "-",
            "owner": _first_text(raw.get("owner"), raw.get("master"), raw.get("username")) or "-",
            "stage": _first_text(raw.get("stage"), raw.get("realm"), raw.get("levelName")) or "-",
            "lingqi_pool": _format_pool(pool) or "-",
            "lingmai_rate": _first_text(
                raw.get("lingmai_rate"),
                raw.get("lingmaiRate"),
                metrics.get("lingmaiRate"),
                _format_number(raw.get("productionHint")),
            )
            or "-",
            "jingshi_conversion": _first_text(
                raw.get("jingshi_conversion"),
                raw.get("jingshiConversion"),
                metrics.get("jingshiConversion"),
                _format_number(raw.get("conversionHint")),
            )
            or "-",
            "array_mode": _first_text(
                raw.get("array_mode"),
                raw.get("arrayMode"),
                raw.get("dazhenMode"),
                metrics.get("arrayMode"),
                formation.get("mode"),
                formation.get("title"),
            )
            or "-",
            "scenery_count": _format_scenery_count(raw, metrics) or "-",
            "facilities": facilities[:6],
            "updated_at": _format_sync_time(raw.get("updated_at") or raw.get("updatedAt"))
            or "-",
        }
    )
    return base


def merge_estate_miniapp_payload(
    payload: dict,
    *,
    entry: Optional[dict] = None,
    snapshot: Optional[dict] = None,
    hunt: Optional[dict] = None,
    hunt_limits: Optional[dict] = None,
) -> dict:
    from .biz_estate_miniapp import (
    build_estate_miniapp_entry_view,
    )

    result = deepcopy(payload if isinstance(payload, dict) else {})
    dongfu = result.get("dongfu")
    if not isinstance(dongfu, dict):
        dongfu = {}
    else:
        dongfu = dict(dongfu)
    dongfu.pop("miniapp_launch", None)
    if entry:
        dongfu["miniapp_entry"] = build_estate_miniapp_entry_view(entry)
    if snapshot:
        dongfu["miniapp_snapshot"] = build_estate_miniapp_snapshot(
            _stamp_snapshot_sync_time(snapshot)
        )
    if hunt_limits:
        existing_hunt = dict(dongfu.get("miniapp_hunt") or {})
        normalized_limits = build_estate_miniapp_hunt(hunt_limits)
        existing_hunt.update(
            {
                "status": normalized_limits["status"],
                "updated_at": normalized_limits["updated_at"],
                "used": normalized_limits["used"],
                "limit": normalized_limits["limit"],
                "remaining": normalized_limits["remaining"],
                "chance_text": normalized_limits["chance_text"],
                "automation_status": normalized_limits["automation_status"],
                "error": normalized_limits["error"],
                "safety_boundary": MINIAPP_HUNT_SAFETY_BOUNDARY,
            }
        )
        dongfu["miniapp_hunt"] = build_estate_miniapp_hunt(existing_hunt)
    if hunt:
        dongfu["miniapp_hunt"] = build_estate_miniapp_hunt(hunt)
        dongfu.pop("miniapp_hunt_request", None)
    result["dongfu"] = dongfu
    return result
