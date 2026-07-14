import re

import biz_fanren_game


def tianji_remnant_int(value: object) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else 0


def tianji_remnant_fraction(value: object) -> tuple[int, int]:
    match = re.search(r"(\d+)\s*/\s*(\d+)", str(value or ""))
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def tianji_remnant_day_key(timestamp: object = None) -> str:
    try:
        source = biz_fanren_game.time.time() if timestamp is None else float(timestamp)
    except (TypeError, ValueError):
        source = biz_fanren_game.time.time()
    return biz_fanren_game.time.strftime(
        "%Y-%m-%d", biz_fanren_game.time.localtime(source)
    )


def apply_tianji_trial_entry_state(
    state: dict, *, panel_ts: object = None
) -> dict:
    entry_used, entry_limit = tianji_remnant_fraction(state.get("entry_count"))
    limit_reached = entry_limit > 0 and entry_used >= entry_limit
    panel_stale = False
    if panel_ts:
        panel_stale = tianji_remnant_day_key(panel_ts) != tianji_remnant_day_key()
    state["trial_daily_limit_reached"] = limit_reached
    state["trial_daily_limit_text"] = (
        f"{entry_used}/{entry_limit}" if entry_limit else ""
    )
    state["trial_state_stale"] = panel_stale
    state["trial_button_label"] = "MiniApp 自动试炼三关"
    if panel_stale:
        stale_time = str(state.get("panel_time") or "").strip()
        state["trial_status_override"] = (
            f"状态需刷新（上次更新 {stale_time}）" if stale_time else "状态需刷新"
        )
    else:
        state["trial_status_override"] = (
            f"今日入口已满（{entry_used}/{entry_limit}）" if limit_reached else ""
        )
    return state


def parse_tianji_remnant_exchange_items(text: str) -> list[dict]:
    items = []
    seen = set()
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        match = re.match(
            r"^[-•]\s*([^：:\n]+)[：:]\s*(\d+)\s*残痕\s*(?:->|→)\s*([^x×\n]+?)\s*[x×]\s*(\d+)",
            line,
        )
        if not match:
            match = re.match(
                r"^[-•]\s*([^：:\n]+)[：:]\s*(\d+)\s*残痕\s*(?:->|→)",
                line,
            )
        if not match:
            continue
        name = match.group(1).strip()
        cost = match.group(2).strip()
        if name and name not in seen:
            output_quantity = (
                int(match.group(4))
                if match.lastindex and match.lastindex >= 4
                else 1
            )
            label = (
                f"{name}（{cost} 残痕 -> x{output_quantity}）"
                if output_quantity > 1
                else f"{name}（{cost} 残痕）"
            )
            items.append(
                {
                    "name": name,
                    "cost": cost,
                    "quantity_step": output_quantity,
                    "label": label,
                }
            )
            seen.add(name)
    return items


def build_tianji_exchange_items(
    items: list[dict], balance: object
) -> tuple[list[dict], list[int], bool]:
    balance_amount = tianji_remnant_int(balance)
    built_items: list[dict] = []
    selected_seen = False
    for raw_item in items:
        item = dict(raw_item or {})
        name = str(item.get("name") or "").strip()
        cost = tianji_remnant_int(item.get("cost"))
        quantity_step = max(tianji_remnant_int(item.get("quantity_step")) or 1, 1)
        max_quantity = balance_amount // cost if cost > 0 else 0
        quantity_options = [max_quantity] if max_quantity > 0 else []
        if "->" in str(item.get("label") or ""):
            label = re.sub(
                r"）$",
                f"，最多 {max_quantity} 次）" if max_quantity > 0 else "，余额不足）",
                str(item.get("label") or ""),
            )
        else:
            label = (
                f"{name}（{cost} 残痕，最多 {max_quantity} 次）"
                if max_quantity > 0
                else f"{name}（{cost} 残痕，余额不足）"
            )
        item.update(
            {
                "name": name,
                "cost": str(cost) if cost else str(item.get("cost") or ""),
                "label": label,
                "quantity_step": quantity_step,
                "max_quantity": max_quantity,
                "quantity_options": quantity_options,
                "selected": False,
            }
        )
        if not selected_seen and max_quantity > 0:
            item["selected"] = True
            selected_seen = True
        built_items.append(item)
    if built_items and not selected_seen:
        built_items[0]["selected"] = True
    selected_item = next((item for item in built_items if item.get("selected")), {})
    return built_items, list(selected_item.get("quantity_options") or []), any(
        int(item.get("max_quantity") or 0) > 0 for item in built_items
    )


def tianji_remnant_summary(state: dict) -> list[dict]:
    return [
        {"label": "当前残痕", "value": state.get("balance") or "-"},
        {"label": "今日入口", "value": state.get("entry_count") or "-"},
        {"label": "今日完成", "value": state.get("completed_count") or "-"},
    ]


def parse_tianji_remnant_panel_text(text: str) -> dict:
    state = {
        "balance": "-",
        "entry_count": "-",
        "completed_count": "-",
    }
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^当前(?:天机)?残痕[：:]\s*(.+)$", line)
        if match:
            state["balance"] = match.group(1).strip()
            continue
        match = re.match(r"^当前余额[：:]\s*(.+)$", line)
        if match:
            state["balance"] = match.group(1).strip()
            continue
        match = re.match(r"^今日入口[：:]\s*(.+)$", line)
        if match:
            state["entry_count"] = match.group(1).strip()
            continue
        match = re.match(r"^今日完成[：:]\s*(.+)$", line)
        if match:
            state["completed_count"] = match.group(1).strip()
    state["summary"] = tianji_remnant_summary(state)
    return apply_tianji_trial_entry_state(state)
