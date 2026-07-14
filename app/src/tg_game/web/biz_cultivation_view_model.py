import re

import biz_fanren_game

from tg_game.storage import CompatDb, Storage

DEFAULT_BULK_CULTIVATION_PROTECTED_PROFILE_ID = 0
CULTIVATION_STAGE_CAPS = {
    "练气初期": 2000,
    "练气中期": 5000,
    "练气后期": 10000,
    "筑基初期": 30000,
    "筑基中期": 60000,
    "筑基后期": 100000,
    "结丹初期": 120000,
    "结丹中期": 160000,
    "结丹后期": 200000,
    "元婴初期": 300000,
    "元婴中期": 400000,
    "元婴后期": 500000,
    "化神初期": 700000,
    "化神中期": 900000,
    "化神后期": 1200000,
}

ITEM_DELTA_PATTERNS = (
    re.compile(r"(?:奇遇)?获得[^\n:：]*[:：]?\s*(?P<value>.+)"),
    re.compile(r"(?:奇遇)?减少[^\n:：]*[:：]?\s*(?P<value>.+)"),
    re.compile(r"(?:奇遇)?失去[^\n:：]*[:：]?\s*(?P<value>.+)"),
    re.compile(r"(?:奇遇)?消耗[^\n:：]*[:：]?\s*(?P<value>.+)"),
)


def get_profile_cultivation_binding(storage: Storage, profile):
    return storage.get_primary_chat_binding(
        profile.id,
        bot_username=biz_fanren_game.FANREN_BOT_USERNAME,
    ) or storage.get_primary_chat_binding(profile.id)


def build_all_profile_cultivation_state(
    storage: Storage,
    profiles: list,
    protected_profile_id: int = DEFAULT_BULK_CULTIVATION_PROTECTED_PROFILE_ID,
) -> dict:
    protected_profile_id = int(protected_profile_id or 0)
    db = CompatDb(storage)
    normal = 0
    deep = 0
    enabled = 0
    bound = 0
    protected = 0
    profile_states = {}
    try:
        biz_fanren_game.ensure_tables(db)
        for profile in profiles:
            is_protected = bool(protected_profile_id and profile.id == protected_profile_id)
            if is_protected:
                protected += 1
            profile_state = {
                "enabled": False,
                "mode": "normal",
                "status_text": "自动闭关未开启",
                "mode_text": "普通闭关",
            }
            profile_states[profile.id] = profile_state
            binding = get_profile_cultivation_binding(storage, profile)
            if not binding:
                continue
            session = biz_fanren_game.get_session(
                db,
                binding.chat_id,
                profile_id=profile.id,
            )
            if session:
                mode = (
                    "deep"
                    if str(session.get("retreat_mode") or "").strip().lower()
                    == "deep"
                    else "normal"
                )
                profile_state.update(
                    {
                        "enabled": bool(session.get("enabled")),
                        "mode": mode,
                        "status_text": (
                            "自动闭关已开启"
                            if session.get("enabled")
                            else "自动闭关未开启"
                        ),
                        "mode_text": "深度闭关" if mode == "deep" else "普通闭关",
                    }
                )
            if is_protected:
                continue
            bound += 1
            if not session or not profile_state["enabled"]:
                continue
            enabled += 1
            if profile_state["mode"] == "deep":
                deep += 1
            else:
                normal += 1
    finally:
        db.close()
    return {
        "bound": bound,
        "enabled": enabled,
        "normal": normal,
        "deep": deep,
        "protected": protected,
        "all_normal": bool(bound and normal == bound),
        "all_deep": bool(bound and deep == bound),
        "profiles": profile_states,
    }


def format_cultivation_progress(
    stage_name: str, cultivation_points, stage_caps: dict | None = None
) -> str:
    points_text = str(cultivation_points or "").strip()
    if not points_text:
        return ""
    caps = stage_caps or CULTIVATION_STAGE_CAPS
    cap = caps.get((stage_name or "").strip())
    if not cap:
        return points_text
    return f"({points_text} / {cap})"


def extract_item_delta_lines(raw_text: str) -> list[str]:
    lines = []
    for raw_line in (raw_text or "").splitlines():
        line = raw_line.strip().lstrip("-• ")
        if not line or "修为" in line:
            continue
        for pattern in ITEM_DELTA_PATTERNS:
            match = pattern.search(line)
            if match:
                lines.append(match.group(0).strip("，。；; "))
                break
    return lines


def extract_adventure_lines(raw_text: str) -> list[str]:
    lines = []
    for raw_line in (raw_text or "").splitlines():
        line = raw_line.strip().lstrip("-• ")
        if line and "奇遇" in line:
            lines.append(line.strip("，。；; "))
    return lines


def build_cultivation_result_view(
    result: dict,
    *,
    extract_item_delta=extract_item_delta_lines,
    extract_adventure=extract_adventure_lines,
) -> dict:
    row = dict(result or {})
    gain_value = row.get("gain_value")
    if gain_value is None:
        gain_text = "修为变化未识别"
    elif int(gain_value) >= 0:
        gain_text = f"+{int(gain_value)}"
    else:
        gain_text = f"-{abs(int(gain_value))}"

    item_lines = extract_item_delta(row.get("raw_text") or "")
    adventure_lines = extract_adventure(row.get("raw_text") or "")
    row["gain_text"] = gain_text
    row["item_lines"] = item_lines[:3]
    row["item_summary"] = "；".join(item_lines[:2]) if item_lines else "无明显物品变化"
    row["adventure_lines"] = adventure_lines[:3]
    row["adventure_summary"] = (
        "；".join(adventure_lines[:2]) if adventure_lines else "无奇遇信息"
    )
    row["stage_display"] = (row.get("stage_name") or "-").strip() or "-"
    row["progress_display"] = (row.get("progress_text") or "-").strip() or "-"
    row["mode_label"] = "深度闭关" if row.get("mode") == "deep" else "普通闭关"
    return row
