from pathlib import Path
from typing import Optional
import biz_fanren_game

from tg_game.features.tianxing.biz_tianxing_reward_summary import (
    normalize_tianxing_day_key,
    tianxing_day_start_timestamp,
)
from tg_game.web.biz_web_display_formatting import (
    compact_log_text,
    markdown_fence_text,
    wild_deep_result_label,
    wild_deep_sender_label,
)


WILD_DEEP_COMMAND_PREFIX = ".野外历练 深入"


def wild_deep_time_bucket(timestamp: float) -> str:
    if float(timestamp or 0) <= 0:
        return "-"
    local_time = biz_fanren_game.time.localtime(float(timestamp))
    return f"{local_time.tm_hour:02d}:00-{local_time.tm_hour:02d}:59"


def build_wild_deep_log_rows(
    storage,
    profile_id: int,
    day_key: str,
    chat_id: Optional[int] = None,
) -> list[dict]:
    selected_day_key = normalize_tianxing_day_key(day_key)
    day_start = tianxing_day_start_timestamp(selected_day_key)
    chat_clause = ""
    params: list[object] = [
        int(profile_id),
        float(day_start),
        float(day_start + 86400),
        f"{WILD_DEEP_COMMAND_PREFIX}%",
    ]
    if chat_id is not None:
        chat_clause = " AND parent.chat_id=?"
        params.append(int(chat_id))
    with storage.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT
                parent.id AS command_row_id,
                parent.chat_id AS chat_id,
                parent.thread_id AS thread_id,
                parent.message_id AS command_message_id,
                parent.created_at AS command_created_at,
                parent.sender_id AS command_sender_id,
                parent.sender_username AS command_sender_username,
                parent.direction AS command_direction,
                parent.text AS command_text,
                child.id AS reply_row_id,
                child.message_id AS reply_message_id,
                child.created_at AS reply_created_at,
                child.sender_username AS reply_sender_username,
                child.text AS reply_text
            FROM bound_messages parent
            LEFT JOIN bound_messages child
              ON child.profile_id=parent.profile_id
             AND child.chat_id=parent.chat_id
             AND COALESCE(child.thread_id, 0)=COALESCE(parent.thread_id, 0)
             AND child.reply_to_msg_id=parent.message_id
             AND child.direction='incoming'
             AND child.is_bot=1
            WHERE parent.profile_id=?
              AND parent.created_at>=? AND parent.created_at<?
              AND parent.is_bot=0
              AND parent.text LIKE ?
              {chat_clause}
            ORDER BY parent.created_at ASC, parent.id ASC, child.created_at ASC, child.id ASC
            LIMIT 1000
            """,
            params,
        ).fetchall()
    result_rows = []
    for row in rows:
        row_dict = dict(row)
        command_created_at = float(row_dict.get("command_created_at") or 0)
        reply_created_at = float(row_dict.get("reply_created_at") or 0)
        reply_text = str(row_dict.get("reply_text") or "").strip()
        row_dict["command_time_display"] = biz_fanren_game.format_timestamp(
            command_created_at
        )
        row_dict["reply_time_display"] = biz_fanren_game.format_timestamp(reply_created_at)
        row_dict["time_bucket"] = wild_deep_time_bucket(command_created_at)
        row_dict["sender_label"] = wild_deep_sender_label(row_dict)
        row_dict["direction_label"] = (
            "本机账号"
            if str(row_dict.get("command_direction") or "") == "outgoing"
            else "群内用户"
        )
        row_dict["reply_result_label"] = wild_deep_result_label(reply_text)
        row_dict["reply_summary"] = compact_log_text(reply_text)
        result_rows.append(row_dict)
    return result_rows


def render_wild_deep_log_markdown(
    *, day_key: str, rows: list[dict], chat_id: Optional[int]
) -> str:
    generated_at = biz_fanren_game.format_timestamp(biz_fanren_game.time.time())
    chat_text = str(chat_id) if chat_id is not None else "当前 profile 已记录的全部聊天"
    lines = [
        f"# 野外历练 深入日志 - {day_key}",
        "",
        f"- 生成时间: {generated_at}",
        f"- 统计口径: 当前 profile 本地已记录消息；chat_id={chat_text}",
        f"- 命令前缀: `{WILD_DEEP_COMMAND_PREFIX}`",
        f"- 记录数: {len(rows)}",
        "",
    ]
    if not rows:
        lines.append("暂无本日已记录的 `.野外历练 深入` 命令。")
        return "\n".join(lines) + "\n"

    lines.extend(
        [
            "| # | 命令时间 | 时间段 | 发送者 | 方向 | 结果 | 回复时间 | 摘要 |",
            "| - | - | - | - | - | - | - | - |",
        ]
    )
    for index, row in enumerate(rows, start=1):
        summary = str(row.get("reply_summary") or "暂无已记录回复").replace("|", "\\|")
        lines.append(
            "| {index} | {command_time} | {bucket} | {sender} | {direction} | {result} | {reply_time} | {summary} |".format(
                index=index,
                command_time=row.get("command_time_display") or "-",
                bucket=row.get("time_bucket") or "-",
                sender=str(row.get("sender_label") or "-").replace("|", "\\|"),
                direction=str(row.get("direction_label") or "-").replace("|", "\\|"),
                result=str(row.get("reply_result_label") or "-").replace("|", "\\|"),
                reply_time=row.get("reply_time_display") or "-",
                summary=summary,
            )
        )
    lines.append("")

    for index, row in enumerate(rows, start=1):
        lines.extend(
            [
                f"## {index}. {row.get('command_time_display') or '-'} {row.get('sender_label') or '-'} {row.get('reply_result_label') or '-'}",
                "",
                f"- chat_id: {row.get('chat_id') or '-'}",
                f"- thread_id: {row.get('thread_id') or '-'}",
                f"- command_message_id: {row.get('command_message_id') or '-'}",
                f"- reply_message_id: {row.get('reply_message_id') or '-'}",
                "",
                "### 发送命令",
                "```text",
                markdown_fence_text(row.get("command_text") or ""),
                "```",
                "",
                "### Bot 回复",
                "```text",
                markdown_fence_text(row.get("reply_text") or "暂无已记录回复"),
                "```",
                "",
            ]
        )
    return "\n".join(lines)


def export_wild_deep_log_file(
    storage,
    *,
    profile_id: int,
    day_key: str,
    chat_id: Optional[int],
    log_dir: Path,
) -> dict:
    selected_day_key = normalize_tianxing_day_key(day_key)
    rows = build_wild_deep_log_rows(
        storage, profile_id=profile_id, day_key=selected_day_key, chat_id=chat_id
    )
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{selected_day_key}.md"
    log_path.write_text(
        render_wild_deep_log_markdown(
            day_key=selected_day_key,
            rows=rows,
            chat_id=chat_id,
        ),
        encoding="utf-8",
    )
    return {"day_key": selected_day_key, "rows": len(rows), "path": str(log_path)}


def build_wild_deep_log_export_result(query_params) -> Optional[dict]:
    if query_params.get("wild_deep_export") != "1":
        return None
    try:
        rows = max(int(query_params.get("wild_deep_rows") or 0), 0)
    except (TypeError, ValueError):
        rows = 0
    return {
        "day_key": str(query_params.get("explore_day") or "").strip(),
        "rows": rows,
        "path": str(query_params.get("wild_deep_path") or "").strip(),
    }
