import re


ACTION_KEYWORDS = {
    "artifact_status": ["状态", "法宝耐久", "耐久"],
    "artifact_repair": ["修理", "一键修理"],
    "artifact_touch": ["抚摸法宝", "器灵经验"],
    "artifact_trial": ["器灵试炼", "试炼消耗"],
    "artifact_nurture": ["温养器灵"],
    "artifact_awaken": ["唤醒器灵", "器灵"],
    "artifact_spirit": ["我的器灵", "器灵信息"],
}

SUCCESS_KEYWORDS = ["成功", "获得", "完成", "已", "提升"]
COOLDOWN_PATTERN = re.compile(
    r"(?:(?P<hours>\d+)\s*小时)?\s*"
    r"(?:(?P<minutes>\d+)\s*分钟)?\s*"
    r"(?:(?P<seconds>\d+)\s*秒)?"
    r"\s*后"
)
TRIAL_COOLDOWN_PATTERN = re.compile(
    r"(?:下次)?试炼冷却[:：]?\s*"
    r"(?:(?P<hours>\d+)\s*小时)?\s*"
    r"(?:(?P<minutes>\d+)\s*分钟)?\s*"
    r"(?:(?P<seconds>\d+)\s*秒)?"
)

ARTIFACT_PATTERN = re.compile(r"御使法宝[:：]\s*(?P<value>[^\n]+)")
STAGE_PATTERN = re.compile(r"当前境界[:：]\s*(?P<value>[^\n]+)")
PROGRESS_PATTERN = re.compile(r"当前修为[:：]\s*(?P<value>[^\n]+)")
STATUS_HEADER_PATTERN = re.compile(r"【修士状态\s*·\s*@(?P<value>[^】\n]+)】")
STATUS_ARTIFACT_PATTERN = re.compile(
    r"本命法宝耐久[:：]\s*(?P<value>(?:\n-\s*[^\n]+)+)", re.MULTILINE
)


def _parse_cooldown_seconds(text):
    for match in COOLDOWN_PATTERN.finditer(text or ""):
        parts = {
            key: int(value or 0)
            for key, value in match.groupdict().items()
        }
        total = (
            parts["hours"] * 3600
            + parts["minutes"] * 60
            + parts["seconds"]
        )
        if total > 0:
            return total
    return 0


def _parse_artifact_trial_cooldown_seconds(text):
    for match in TRIAL_COOLDOWN_PATTERN.finditer(text or ""):
        parts = {
            key: int(value or 0)
            for key, value in match.groupdict().items()
        }
        total = (
            parts["hours"] * 3600
            + parts["minutes"] * 60
            + parts["seconds"]
        )
        if total > 0:
            return total
    return _parse_cooldown_seconds(text)


def _is_artifact_trial_text(text):
    return (
        "器灵试炼" in text
        or ("试炼消耗" in text and ("养魂木" in text or "灵石" in text))
        or ("试炼" in text and ("养魂木不足" in text or "灵石不足" in text))
    )


def _is_artifact_trial_insufficient(text):
    return any(
        keyword in (text or "")
        for keyword in ("灵石不足", "养魂木不足", "资源不足", "材料不足")
    )


def _is_artifact_nurture_text(text):
    return any(
        keyword in (text or "")
        for keyword in (
            "【温养器灵】",
            "温养器灵需要",
            "后再行温养",
        )
    )


def _is_artifact_nurture_insufficient(text):
    normalized = text or ""
    return "温养器灵需要" in normalized and "当前尚缺" in normalized


def _build_artifact_action_result(event_name, text):
    summary = f"收到法宝消息: {event_name}"
    if any(keyword in text for keyword in SUCCESS_KEYWORDS):
        summary = f"法宝动作成功: {event_name}"
    result = {
        "event": event_name,
        "summary": summary,
        "feature_name": event_name.replace("artifact_", ""),
    }
    if event_name == "artifact_touch":
        result["cooldown_seconds"] = _parse_cooldown_seconds(text)
    if event_name == "artifact_trial":
        result["cooldown_seconds"] = _parse_artifact_trial_cooldown_seconds(text)
        result["insufficient_resources"] = _is_artifact_trial_insufficient(text)
    if event_name == "artifact_nurture":
        result["cooldown_seconds"] = _parse_cooldown_seconds(text)
        result["insufficient_resources"] = _is_artifact_nurture_insufficient(text)
    return result


def parse_message(text):
    text = (text or "").strip()
    if not text:
        return None
    if _is_artifact_nurture_text(text):
        return _build_artifact_action_result("artifact_nurture", text)
    if _is_artifact_trial_text(text):
        return _build_artifact_action_result("artifact_trial", text)
    if "后再与它互动" in text and _parse_cooldown_seconds(text):
        return _build_artifact_action_result("artifact_touch", text)
    if (
        "联系更加紧密" in text
        and "器灵传来了" in text
        and "默契" in text
        and "经验" in text
    ):
        return _build_artifact_action_result("artifact_touch", text)
    if "御使法宝" in text or "当前境界" in text or "当前修为" in text:
        artifact_text = (
            ARTIFACT_PATTERN.search(text).group("value").strip()
            if ARTIFACT_PATTERN.search(text)
            else ""
        )
        stage_text = (
            STAGE_PATTERN.search(text).group("value").strip()
            if STAGE_PATTERN.search(text)
            else ""
        )
        progress_text = (
            PROGRESS_PATTERN.search(text).group("value").strip()
            if PROGRESS_PATTERN.search(text)
            else ""
        )
        return {
            "event": "artifact_status_profile",
            "summary": "收到状态面板",
            "feature_name": "status",
            "artifact_text": artifact_text,
            "stage_name": stage_text,
            "cultivation_text": progress_text,
        }
    if "【修士状态" in text and "本命法宝耐久" in text:
        header_match = STATUS_HEADER_PATTERN.search(text)
        artifact_block_match = STATUS_ARTIFACT_PATTERN.search(text)
        artifact_lines = []
        if artifact_block_match:
            artifact_lines = [
                line.strip()
                for line in artifact_block_match.group("value").splitlines()
                if line.strip()
            ]
        stage_text = (
            re.search(r"境界[:：]\s*(?P<value>[^\n]+)", text).group("value").strip()
            if re.search(r"境界[:：]\s*(?P<value>[^\n]+)", text)
            else ""
        )
        return {
            "event": "artifact_status_profile",
            "summary": "收到状态面板",
            "feature_name": "status",
            "artifact_text": "\n".join(artifact_lines),
            "stage_name": stage_text,
            "telegram_username": (
                header_match.group("value").strip() if header_match else ""
            ),
        }
    for event_name, keywords in ACTION_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return _build_artifact_action_result(event_name, text)
    return None
