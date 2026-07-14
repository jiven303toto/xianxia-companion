import re
from typing import Optional


COMPANION_VOYAGE_FEATURE_KEY = "companion_voyage"
COMPANION_VOYAGE_STRATEGY_OPTIONS = ("稳妥", "均衡", "冒险")


def normalize_companion_voyage_strategy(value: object) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized in COMPANION_VOYAGE_STRATEGY_OPTIONS else "均衡"


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


def is_companion_panel_text(text: str) -> bool:
    normalized = str(text or "").strip()
    return (
        ("你的道心侍妾" in normalized or "你的红尘道侣" in normalized)
        and "入梦寻图冷却" in normalized
        and "共历心劫冷却" in normalized
        and "天机代卜冷却" in normalized
    )


def build_companion_voyage_state_from_reply(reply: Optional[dict]) -> dict:
    raw_reply = reply or {}
    text = str(raw_reply.get("text") or "").strip()
    created_at = float(raw_reply.get("created_at") or 0)
    state = {
        "text": text,
        "target_ts": 0.0,
        "status": "unknown",
        "task": "",
    }
    if not text:
        return state
    remaining_match = re.search(r"预计归航还需\s*([^\n。]+)", text)
    if remaining_match:
        remaining_seconds = parse_chinese_duration_seconds(remaining_match.group(1))
        if remaining_seconds and created_at:
            state["target_ts"] = created_at + remaining_seconds
        task_match = re.search(r"正在执行【([^】]+)】远航", text)
        if task_match:
            state["task"] = task_match.group(1).strip()
        state["status"] = "voyaging"
        return state
    retry_match = re.search(r"远航中.*?请在\s*([^\n。]+?)\s*后再试", text)
    if retry_match:
        remaining_seconds = parse_chinese_duration_seconds(retry_match.group(1))
        if remaining_seconds and created_at:
            state["target_ts"] = created_at + remaining_seconds
        state["status"] = "voyaging"
        return state
    panel_match = re.search(r"远航状态:\s*([^，\n]+).*?剩余约\s*(\d+)\s*分钟", text)
    if panel_match:
        state["task"] = panel_match.group(1).strip().replace("航线进行中", "")
        if created_at:
            state["target_ts"] = created_at + int(panel_match.group(2)) * 60
        state["status"] = "voyaging"
        return state
    if (
        "远航归来" in text
        and (
            "待结算" in text
            or "尚未结算" in text
            or "等你接引" in text
        )
    ):
        state["status"] = "returned_waiting"
        return state
    if "已自" in text and "远航归来" in text:
        state["status"] = "returned_waiting"
        return state
    if "远航途中" in text or "远航中" in text:
        state["status"] = "voyaging"
        return state
    if "当前并未执行远航任务" in text or "并无可结算的远航任务" in text:
        state["status"] = "idle"
        return state
    if "当前并未随行" in text or "无法探查远航状态" in text:
        state["status"] = "not_following"
        return state
    if is_companion_panel_text(text):
        state["status"] = "idle"
        return state
    return state
