import re
import time
from datetime import datetime, timedelta
from tg_game.storage import Storage
from .biz_tianxing_parser import get_day_key
from .biz_tianxing_rewards import (
    build_tianxing_reward_entry,
    build_tianxing_reward_entry_from_text,
    normalize_tianxing_reward_source_text,
)
from .biz_tianxing_runtime import ensure_schema

TIANXING_REWARD_AUDIT_FILTER = """
AND (
  route='探索' OR action='探索' OR
  raw_text LIKE '%野外历练%' OR command_text LIKE '%野外历练%' OR
  raw_text LIKE '%探寻成功%' OR command_text LIKE '%探寻成功%' OR
  raw_text LIKE '%裂缝%' OR command_text LIKE '%裂缝%'
)
AND (
  result IN ('prediction_hit', 'prediction_miss', 'change_triggered') OR
  detail_json LIKE '%"result":"prediction_hit"%' OR
  detail_json LIKE '%"result":"prediction_miss"%' OR
  detail_json LIKE '%"result":"change_triggered"%'
)
"""


def normalize_tianxing_day_key(value: str = "", now=None) -> str:
    current_time = float(time.time() if now is None else now)
    raw = str(value or "").strip().replace("/", "-")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        try:
            datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            pass
        else:
            return raw
    return get_day_key(current_time)


def tianxing_day_start_timestamp(day_key: str) -> float:
    return time.mktime(time.strptime(day_key, "%Y-%m-%d"))


def shift_tianxing_day_key(day_key: str, days: int) -> str:
    parsed = datetime.strptime(day_key, "%Y-%m-%d").date()
    return (parsed + timedelta(days=int(days))).isoformat()


def tianxing_day_key_from_timestamp(timestamp: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(float(timestamp or 0)))


def escape_sql_like(value: str) -> str:
    return (
        str(value or "")
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def build_tianxing_reward_marker_days(
    storage: Storage, profile_id: int, now=None
) -> list[str]:
    current_time = float(time.time() if now is None else now)
    cutoff_ts = current_time - 366 * 86400
    ensure_schema(storage)
    profile = storage.get_profile(int(profile_id))
    username = str(getattr(profile, "telegram_username", "") or "").strip()
    day_keys: set[str] = set()
    with storage.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM tianxing_audit_events
            WHERE profile_id=? AND created_at>=?
            {TIANXING_REWARD_AUDIT_FILTER}
            ORDER BY created_at DESC, id DESC
            """,
            (int(profile_id), float(cutoff_ts)),
        ).fetchall()
        bound_rows = conn.execute(
            """
            SELECT child.*, parent.text AS command_text
            FROM bound_messages parent
            JOIN bound_messages child
              ON child.profile_id=parent.profile_id
             AND child.chat_id=parent.chat_id
             AND COALESCE(child.thread_id, 0)=COALESCE(parent.thread_id, 0)
             AND child.reply_to_msg_id=parent.message_id
            WHERE parent.profile_id=?
              AND child.created_at>=?
              AND parent.direction='outgoing'
              AND child.direction='incoming'
              AND child.is_bot=1
              AND (parent.text LIKE ? OR parent.text LIKE ?)
            ORDER BY child.created_at DESC, child.id DESC
            LIMIT 3000
            """,
            (
                int(profile_id),
                float(cutoff_ts),
                ".野外历练%",
                ".探寻裂缝%",
            ),
        ).fetchall()
        mention_rows = []
        if username:
            mention_like = f"%@{escape_sql_like(username)}%"
            mention_rows = conn.execute(
                """
                SELECT child.*, '' AS command_text
                FROM bound_messages child
                WHERE child.profile_id=?
                  AND child.created_at>=?
                  AND child.direction='incoming'
                  AND child.is_bot=1
                  AND child.text LIKE ? ESCAPE '\\'
                  AND (
                    child.text LIKE ? OR child.text LIKE ? OR
                    child.text LIKE ? OR child.text LIKE ?
                  )
                ORDER BY child.created_at DESC, child.id DESC
                LIMIT 3000
                """,
                (
                    int(profile_id),
                    float(cutoff_ts),
                    mention_like,
                    "%野外历练%",
                    "%探寻裂缝%",
                    "%探寻成功%",
                    "%空间裂缝%",
                ),
            ).fetchall()

    for row in rows:
        row_dict = dict(row)
        if build_tianxing_reward_entry(row_dict):
            day_keys.add(
                tianxing_day_key_from_timestamp(row_dict.get("created_at") or 0)
            )

    seen_bound_ids: set[int] = set()
    for row in list(bound_rows) + list(mention_rows):
        row_dict = dict(row)
        bound_id = int(row_dict.get("id") or 0)
        if bound_id and bound_id in seen_bound_ids:
            continue
        seen_bound_ids.add(bound_id)
        entry = build_tianxing_reward_entry_from_text(
            raw_text=str(row_dict.get("text") or "").strip(),
            created_at=float(row_dict.get("created_at") or 0),
            command_text=str(row_dict.get("command_text") or ""),
            allow_text_result=True,
            require_tianxing_result=False,
        )
        if entry:
            day_keys.add(
                tianxing_day_key_from_timestamp(row_dict.get("created_at") or 0)
            )

    return sorted(day_keys)


def build_tianxing_today_exploration_rewards(
    storage: Storage,
    profile_id: int,
    now=None,
    day_key: str = "",
    marked_day_keys: list[str] | None = None,
) -> dict:
    current_time = float(time.time() if now is None else now)
    today_key = get_day_key(current_time)
    selected_day_key = normalize_tianxing_day_key(day_key, current_time)
    day_start = tianxing_day_start_timestamp(selected_day_key)
    ensure_schema(storage)
    profile = storage.get_profile(int(profile_id))
    username = str(getattr(profile, "telegram_username", "") or "").strip()
    with storage.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT *
            FROM tianxing_audit_events
            WHERE profile_id=? AND created_at>=? AND created_at<?
            {TIANXING_REWARD_AUDIT_FILTER}
            ORDER BY created_at DESC, id DESC
            LIMIT 300
            """,
            (int(profile_id), float(day_start), float(day_start + 86400)),
        ).fetchall()
        bound_rows = conn.execute(
            """
            SELECT child.*, parent.text AS command_text
            FROM bound_messages parent
            JOIN bound_messages child
              ON child.profile_id=parent.profile_id
             AND child.chat_id=parent.chat_id
             AND COALESCE(child.thread_id, 0)=COALESCE(parent.thread_id, 0)
             AND child.reply_to_msg_id=parent.message_id
            WHERE parent.profile_id=?
              AND child.created_at>=? AND child.created_at<?
              AND parent.direction='outgoing'
              AND child.direction='incoming'
              AND child.is_bot=1
              AND (parent.text LIKE ? OR parent.text LIKE ?)
            ORDER BY child.created_at DESC, child.id DESC
            LIMIT 300
            """,
            (
                int(profile_id),
                float(day_start),
                float(day_start + 86400),
                ".野外历练%",
                ".探寻裂缝%",
            ),
        ).fetchall()
        mention_rows = []
        if username:
            mention_like = f"%@{escape_sql_like(username)}%"
            mention_rows = conn.execute(
                """
                SELECT child.*, '' AS command_text
                FROM bound_messages child
                WHERE child.profile_id=?
                  AND child.created_at>=? AND child.created_at<?
                  AND child.direction='incoming'
                  AND child.is_bot=1
                  AND child.text LIKE ? ESCAPE '\\'
                  AND (
                    child.text LIKE ? OR child.text LIKE ? OR
                    child.text LIKE ? OR child.text LIKE ?
                  )
                ORDER BY child.created_at DESC, child.id DESC
                LIMIT 300
                """,
                (
                    int(profile_id),
                    float(day_start),
                    float(day_start + 86400),
                    mention_like,
                    "%野外历练%",
                    "%探寻裂缝%",
                    "%探寻成功%",
                    "%空间裂缝%",
                ),
            ).fetchall()

    entries = []
    seen_source_texts: set[str] = set()
    seen_bound_ids: set[int] = set()
    for row in rows:
        row_dict = dict(row)
        entry = build_tianxing_reward_entry(row_dict)
        if not entry:
            continue
        entries.append(entry)
        source_text = normalize_tianxing_reward_source_text(row_dict.get("raw_text"))
        if source_text:
            seen_source_texts.add(source_text)

    for row in list(bound_rows) + list(mention_rows):
        row_dict = dict(row)
        bound_id = int(row_dict.get("id") or 0)
        if bound_id and bound_id in seen_bound_ids:
            continue
        seen_bound_ids.add(bound_id)
        raw_text = str(row_dict.get("text") or "").strip()
        source_text = normalize_tianxing_reward_source_text(raw_text)
        if source_text and source_text in seen_source_texts:
            continue
        entry = build_tianxing_reward_entry_from_text(
            raw_text=raw_text,
            created_at=float(row_dict.get("created_at") or 0),
            command_text=str(row_dict.get("command_text") or ""),
            allow_text_result=True,
            require_tianxing_result=False,
        )
        if not entry:
            continue
        entries.append(entry)
        if source_text:
            seen_source_texts.add(source_text)

    entries.sort(key=lambda item: float(item.get("created_at") or 0), reverse=True)
    totals = {
        "hit_count": 0,
        "miss_count": 0,
        "change_count": 0,
        "tianji_gain": 0,
        "contrib_gain": 0,
        "cultivation_gain": 0,
        "calamity_gain": 0,
        "item_count": 0,
    }
    item_totals: dict[str, int] = {}
    for entry in entries:
        result = entry["result"]
        if result == "prediction_hit":
            totals["hit_count"] += 1
        elif result == "prediction_miss":
            totals["miss_count"] += 1
        elif result == "change_triggered":
            totals["change_count"] += 1
        for key in (
            "tianji_gain",
            "contrib_gain",
            "cultivation_gain",
            "calamity_gain",
            "item_count",
        ):
            totals[key] += int(entry.get(key) or 0)
        for item in entry.get("items") or []:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            item_totals[name] = item_totals.get(name, 0) + int(item.get("count") or 0)

    items = [
        {"name": name, "count": count, "text": f"{name} x{count}"}
        for name, count in item_totals.items()
    ]
    totals["items"] = items
    totals["items_text"] = "、".join(item["text"] for item in items) if items else "-"
    marker_days = (
        list(marked_day_keys)
        if marked_day_keys is not None
        else build_tianxing_reward_marker_days(storage, profile_id, now=current_time)
    )
    if entries and selected_day_key not in marker_days:
        marker_days.append(selected_day_key)
        marker_days.sort()
    return {
        "day_key": selected_day_key,
        "today_key": today_key,
        "prev_day_key": shift_tianxing_day_key(selected_day_key, -1),
        "next_day_key": shift_tianxing_day_key(selected_day_key, 1),
        "is_today": selected_day_key == today_key,
        "title": (
            "今日探索收益"
            if selected_day_key == today_key
            else f"{selected_day_key} 探索收益"
        ),
        "summary_label": (
            "今日合计"
            if selected_day_key == today_key
            else f"{selected_day_key} 合计"
        ),
        "empty_text": (
            "暂无今日探索收益记录。"
            if selected_day_key == today_key
            else "暂无该日探索收益记录。"
        ),
        "marked_day_keys": marker_days,
        "summary": totals,
        "entries": entries,
    }
