import json
import re
from typing import Optional


def build_tianxing_reward_entry(event: dict) -> Optional[dict]:
    raw_text = str(event.get("raw_text") or "").strip()
    command_text = str(event.get("command_text") or "").strip()
    detail = decode_json_object(event.get("detail_json"))
    parsed = detail.get("parsed") if isinstance(detail.get("parsed"), dict) else {}
    result = str(parsed.get("result") or event.get("result") or "").strip()
    action = str(parsed.get("action") or event.get("action") or "").strip()
    route = str(event.get("route") or parsed.get("last_route") or "").strip()
    return build_tianxing_reward_entry_from_text(
        raw_text=raw_text,
        created_at=float(event.get("created_at") or 0),
        command_text=command_text,
        parsed=parsed,
        result=result,
        action=action,
        route=route,
        allow_text_result=False,
        require_tianxing_result=True,
    )


def build_tianxing_reward_entry_from_text(
    *,
    raw_text: str,
    created_at: float,
    command_text: str = "",
    parsed: Optional[dict] = None,
    result: str = "",
    action: str = "",
    route: str = "",
    allow_text_result: bool = False,
    require_tianxing_result: bool = True,
) -> Optional[dict]:
    parsed = parsed or {}
    raw_text = str(raw_text or "").strip()
    command_text = str(command_text or "").strip()
    result = str(result or "").strip()
    action = str(action or "").strip()
    route = str(route or "").strip()
    if allow_text_result and not result:
        result = tianxing_result_from_text(raw_text)
    activity = tianxing_exploration_activity_label(raw_text, command_text, action)
    is_exploration = activity or route == "探索" or action == "探索"
    if not is_exploration:
        return None

    tianji_gain = int_from_parsed_or_text(
        parsed, "last_tianji_gain", raw_text, r"天机值\s*\+(\d+)"
    )
    contrib_gain = int_from_parsed_or_text(
        parsed, "last_contrib_gain", raw_text, r"宗门贡献\s*\+(\d+)"
    )
    bonus_gain = int_from_parsed_or_text(
        parsed,
        "last_bonus_gain",
        raw_text,
        r"因【天星宗】灵脉加持，你额外获得了\s*(\d+)\s*点修为",
    )
    cultivation_gain = bonus_gain + sum(
        int(value) for value in re.findall(r"获得修为\s*\+?(\d+)", raw_text)
    )
    calamity_gain = int_from_parsed_or_text(
        parsed, "calamity_delta", raw_text, r"逆命劫\s*\+(\d+)"
    )
    items = parse_tianxing_reward_items(raw_text)
    item_count = sum(item["count"] for item in items)
    has_reward = any(
        (tianji_gain, contrib_gain, cultivation_gain, calamity_gain, item_count)
    )
    if result not in {"prediction_hit", "prediction_miss", "change_triggered"}:
        if require_tianxing_result:
            return None
        if not has_reward:
            return None
        result = "settlement"
    summary_parts = []
    if tianji_gain:
        summary_parts.append(f"天机值 +{tianji_gain}")
    if contrib_gain:
        summary_parts.append(f"宗门贡献 +{contrib_gain}")
    if cultivation_gain:
        summary_parts.append(f"修为 +{cultivation_gain}")
    if calamity_gain and result == "prediction_miss":
        summary_parts.append(f"逆命劫 +{calamity_gain}")
    if items:
        summary_parts.append("、".join(item["text"] for item in items))

    return {
        "created_at": float(created_at or 0),
        "activity": activity or "探索",
        "result": result,
        "result_label": tianxing_result_label(result),
        "summary_text": "；".join(summary_parts) if summary_parts else "仅记录推命结果",
        "tianji_gain": tianji_gain,
        "contrib_gain": contrib_gain,
        "cultivation_gain": cultivation_gain,
        "calamity_gain": calamity_gain if result == "prediction_miss" else 0,
        "items": items,
        "item_count": item_count,
    }


def normalize_tianxing_reward_source_text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def tianxing_result_from_text(text: str) -> str:
    if "【推命命中】" in text:
        return "prediction_hit"
    if "【推命落空】" in text:
        return "prediction_miss"
    if "【改命回天】" in text:
        return "change_triggered"
    return ""


def parse_tianxing_reward_items(text: str) -> list[dict]:
    item_totals: dict[str, int] = {}

    def add_item(raw_name: str, raw_count: int) -> None:
        name = str(raw_name or "").strip()
        if not name:
            return
        item_totals[name] = item_totals.get(name, 0) + max(1, int(raw_count or 1))

    for name, count in re.findall(
        r"获得(?:了)?[：:\s]*【([^】]+)】\s*x\s*(\d+)", text or ""
    ):
        add_item(name, int(count))
    for segment in re.findall(
        r"(?:获得了|带来了)[：:](.*?)(?:[。！!\n]|$)", text or "", flags=re.S
    ):
        for name, count in re.findall(r"【([^】]+)】(?:\s*x\s*(\d+))?", segment):
            if name.strip() in item_totals:
                continue
            add_item(name, int(count) if count else 1)

    return [
        {"name": name, "count": count, "text": f"{name} x{count}"}
        for name, count in item_totals.items()
    ]


def decode_json_object(value) -> dict:
    try:
        decoded = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return decoded if isinstance(decoded, dict) else {}


def int_from_parsed_or_text(parsed: dict, key: str, text: str, pattern: str) -> int:
    value = parsed.get(key)
    if value is not None:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0
    match = re.search(pattern, text or "")
    return int(match.group(1)) if match else 0


def tianxing_exploration_activity_label(
    raw_text: str, command_text: str, action: str
) -> str:
    combined = f"{raw_text}\n{command_text}\n{action}"
    if "探寻裂缝" in combined or "探寻成功" in combined or "裂缝" in combined:
        return "探寻裂缝"
    if "野外历练" in combined:
        return "野外历练"
    return ""


def tianxing_result_label(value: str) -> str:
    return {
        "prediction_hit": "推命命中",
        "prediction_miss": "推命落空",
        "change_triggered": "改命回天",
        "success": "成功",
        "settlement": "结算",
        "panel": "查盘",
        "observe": "观命",
    }.get(str(value or "").strip(), str(value or "").strip() or "-")
