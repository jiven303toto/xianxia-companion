import re

import biz_fanren_game


TIANJI_ENCOUNTER_STRATEGIES = ("谨慎", "均衡", "夺宝", "关闭")


def default_tianji_encounter_state() -> dict:
    return {
        "strategy": "未知",
        "today_count": "0/2",
        "last_encounter": "暂无",
        "records": [],
    }


def build_tianji_encounter_state(
    storage,
    profile_id: int,
    chat_id: int | None,
    *,
    format_timestamp=biz_fanren_game.format_timestamp,
) -> dict:
    state = default_tianji_encounter_state()
    if not chat_id:
        return state

    status_messages = storage.list_bound_messages(
        profile_id=profile_id,
        chat_id=chat_id,
        search_query="天机遭遇战",
        limit=80,
    )

    latest_strategy = ""
    for msg in status_messages:
        text = str(msg.get("text") or "").strip()
        is_bot = bool(msg.get("is_bot"))

        if (
            is_bot
            and text.startswith("【天机遭遇战】")
            and "当前策略:" in text
            and "今日遭遇:" in text
        ):
            strategy_match = re.search(r"当前策略:\s*([^\n]+)", text)
            panel_strategy = strategy_match.group(1).strip() if strategy_match else ""
            if panel_strategy and not latest_strategy:
                latest_strategy = panel_strategy
            count_match = re.search(r"今日遭遇:\s*([^\n]+)", text)
            if count_match:
                state["today_count"] = count_match.group(1).strip()
            last_match = re.search(r"上次遭遇:\s*([^\n]+)", text)
            if last_match:
                state["last_encounter"] = last_match.group(1).strip()
            if state["today_count"] != "0/2" or state["last_encounter"] != "暂无":
                break
        elif (
            is_bot
            and text.startswith("【天机遭遇战】")
            and "策略已改为" in text
            and not latest_strategy
        ):
            strategy_match = re.search(r"策略已改为：([^\n。]+)", text)
            if strategy_match:
                latest_strategy = strategy_match.group(1).strip()
        elif not is_bot and text.startswith(".天机遭遇战 ") and not latest_strategy:
            parts = text.split()
            if len(parts) >= 2 and parts[1] in TIANJI_ENCOUNTER_STRATEGIES:
                latest_strategy = parts[1]

    if latest_strategy:
        state["strategy"] = latest_strategy

    record_messages = storage.list_bound_messages(
        profile_id=profile_id,
        chat_id=chat_id,
        search_query="天机遭遇战记录",
        limit=20,
    )

    records = []
    for msg in record_messages:
        if not msg.get("is_bot"):
            continue
        text = str(msg.get("text") or "").strip()
        if not text.startswith("【天机遭遇战记录】"):
            continue
        time_display = format_timestamp(msg.get("created_at") or 0)

        lines = text.split("\n")[1:]
        for line in lines:
            line = line.strip()
            if line and line != "暂未留下遭遇因果。":
                records.append(
                    {
                        "text": line,
                        "time": time_display,
                    }
                )

    unique_records = []
    seen_texts = set()
    for record in records:
        if record["text"] not in seen_texts:
            seen_texts.add(record["text"])
            unique_records.append(record)

    state["records"] = unique_records[:5]
    return state
