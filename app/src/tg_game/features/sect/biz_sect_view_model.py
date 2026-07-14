import time
from typing import Optional
import biz_sect_game


SECT_RELATED_KEYWORDS = {
    "宗门",
    "大殿",
    "贡献",
    "传功",
    "签到",
    "俸禄",
    "宝库",
    "兑换",
    "小药园",
    "播种",
    "采药",
    "除草",
    "除虫",
    "浇水",
    "黄枫谷",
    "凌霄宫",
    "登天阶",
    "问心台",
    "借宝阁",
    "天罡风",
    "阴罗宗",
    "献祭",
    "血洗",
    "落云宗",
    "灵树",
    "灌溉",
    "采摘",
    "灵果",
    "守山",
    "协同守山",
    "古剑门",
}

NO_SECT_NAMES = {"散修", "未入宗门", "无宗门", "无", "暂无"}


def _now_ts(now_ts: Optional[float] = None) -> float:
    if now_ts is None:
        return time.time()
    return float(now_ts or 0)


def build_sect_daily_view(payload: dict, *, now_ts: Optional[float] = None) -> dict:
    data = payload or {}
    now = _now_ts(now_ts)
    last_check_in_time = biz_sect_game._parse_iso_timestamp(data.get("last_sect_check_in"))
    checked_in_today = (
        biz_sect_game._parse_date_key(data.get("last_sect_check_in"))
        == biz_sect_game.current_date_key(now)
    )
    last_teach_date = biz_sect_game._parse_date_key(data.get("last_teach_date"))
    teach_count = max(biz_sect_game._parse_int(data.get("teach_count"), 0), 0)
    if last_teach_date != biz_sect_game.current_date_key(now):
        teach_count = 0
    return {
        "last_check_in_time": last_check_in_time,
        "checked_in_today": checked_in_today,
        "consecutive_check_in_days": biz_sect_game._parse_int(
            data.get("consecutive_check_in_days"), 0
        ),
        "last_teach_date": last_teach_date,
        "teach_count": teach_count,
        "teach_progress_text": f"{teach_count}/{biz_sect_game.SECT_DAILY_TEACH_LIMIT}",
    }


def merge_sect_daily_view_with_session(
    daily_view: dict, sect_session: Optional[dict], *, now_ts: Optional[float] = None
) -> dict:
    merged = dict(daily_view or {})
    if not sect_session:
        return merged
    now = _now_ts(now_ts)
    session_teach_date = biz_sect_game._parse_date_key(sect_session.get("last_teach_date"))
    session_teach_count = max(
        biz_sect_game._parse_int(sect_session.get("last_teach_count"), 0), 0
    )
    if session_teach_date == biz_sect_game.current_date_key(now) and session_teach_count > int(
        merged.get("teach_count") or 0
    ):
        merged["last_teach_date"] = session_teach_date
        merged["teach_count"] = session_teach_count
        merged["teach_progress_text"] = (
            f"{session_teach_count}/{biz_sect_game.SECT_DAILY_TEACH_LIMIT}"
        )
    return merged


def build_sect_recent_reply_text(
    messages: list[dict],
    current_sect_feature: Optional[dict],
    fallback_text: str = "",
    is_related_message=None,
) -> str:
    predicate = is_related_message or is_sect_related_message
    sect_texts = []
    for msg in messages:
        if not msg.get("is_bot"):
            continue
        text = str(msg.get("text") or "").strip()
        if not text:
            continue
        if not predicate(text, current_sect_feature):
            continue
        sect_texts.append(text[:400])
    if sect_texts:
        return "\n\n---\n\n".join(sect_texts[:8])
    return str(fallback_text or "").strip()


def is_sect_related_message(text: str, current_sect_feature: Optional[dict]) -> bool:
    sect_keywords = set(SECT_RELATED_KEYWORDS)
    if current_sect_feature and current_sect_feature.get("name"):
        sect_keywords.add(current_sect_feature["name"])
    return any(kw in text for kw in sect_keywords)


def normalize_sect_name_text(value: str) -> str:
    return str(value or "").replace("【", "").replace("】", "").strip()


def has_joined_sect(active_profile, normalize_name=normalize_sect_name_text) -> bool:
    if not active_profile:
        return False
    sect_name = normalize_name(getattr(active_profile, "sect_name", ""))
    return bool(sect_name) and sect_name not in NO_SECT_NAMES


def is_tianxing_sect_profile(
    active_profile, normalize_name=normalize_sect_name_text
) -> bool:
    if not active_profile:
        return False
    return normalize_name(getattr(active_profile, "sect_name", "")) == "天星宗"


def sect_matches_current(
    item_sect_name: str,
    current_sect_name: str,
    normalize_name=normalize_sect_name_text,
) -> bool:
    current = normalize_name(current_sect_name)
    item_sect = normalize_name(item_sect_name)
    if not item_sect:
        return True
    if not current:
        return False
    return current in item_sect or item_sect in current


def build_sect_treasury_items(
    active_profile,
    shop_items: list[dict],
    game_items_dict: dict,
    *,
    format_display_text,
    item_type_label,
    matches_current=sect_matches_current,
) -> list[dict]:
    if not active_profile:
        return []
    current_sect_name = normalize_sect_name_text(
        getattr(active_profile, "sect_name", "")
    )
    all_entries = []
    for item in shop_items:
        item_id = str(item.get("item_id") or "").strip()
        meta = game_items_dict.get(item_id) or {}
        sect_exclusive_name = (
            format_display_text(item.get("sect_exclusive"), game_items_dict)
            or str(item.get("sect_exclusive") or "").strip()
        )
        display_name = str(meta.get("name") or item.get("name") or item_id).strip()
        if not display_name:
            continue
        all_entries.append(
            {
                **item,
                "display_name": display_name,
                "display_type": item_type_label(item.get("type") or meta.get("type")),
                "shop_price_text": f"{int(item.get('shop_price') or 0)} 贡献",
                "sect_exclusive_name": sect_exclusive_name,
                "sect_exclusive_label": sect_exclusive_name or "通用",
            }
        )
    return sorted(
        [
            entry
            for entry in all_entries
            if matches_current(
                entry.get("sect_exclusive_name") or "", current_sect_name
            )
        ],
        key=lambda entry: (
            int(entry.get("shop_price") or 0),
            entry.get("display_name") or "",
        ),
    )
