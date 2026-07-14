import re


MULAN_AUTO_SUPPORT_FEATURE_KEY = "mulan_support_plan"
MULAN_PANEL_COMMAND_TEXT = ".边境军功"
MULAN_MERIT_OFFICE_COMMAND_TEXT = ".军功司"
MULAN_RANK_COMMAND_TEXT = ".我的军衔"
MULAN_SPY_COMMAND_TEXT = ".慕兰谍影"
MULAN_COLLECT_REPORT_COMMAND_TEXT = ".搜集军报"
MULAN_VERIFY_REPORT_COMMAND_PREFIX = ".辨报"
MULAN_PANEL_COMMAND = {"label": "边境军功", "command": MULAN_PANEL_COMMAND_TEXT}
MULAN_MERIT_COMMANDS = [
    {"label": "军功司", "command": MULAN_MERIT_OFFICE_COMMAND_TEXT},
    {"label": "我的军衔", "command": MULAN_RANK_COMMAND_TEXT},
]
MULAN_MERIT_EXCHANGE_FALLBACK_ITEMS = [
    {"name": "回灵丹", "cost": "5", "label": "回灵丹（5 军功）"},
    {"name": "黄龙军功牌", "cost": "8", "label": "黄龙军功牌（8 军功）"},
    {"name": "慕兰圣灯残焰", "cost": "72", "label": "慕兰圣灯残焰（72 军功）"},
    {"name": "神识玉简", "cost": "24", "label": "神识玉简（24 军功）"},
]
MULAN_SUPPORT_COMMANDS = [
    {"label": "斥候", "command": ".支援慕兰 斥候"},
    {"label": "破灯", "command": ".支援慕兰 破灯"},
    {"label": "护阵", "command": ".支援慕兰 护阵"},
    {"label": "奇袭", "command": ".支援慕兰 奇袭"},
]
MULAN_UTILITY_COMMANDS = [
    {"label": "慕兰谍影", "command": MULAN_SPY_COMMAND_TEXT},
    {"label": "搜集军报", "command": MULAN_COLLECT_REPORT_COMMAND_TEXT},
    {"label": "刻印状态", "command": ".刻印状态"},
    {"label": "残图匣", "command": ".残图匣"},
]
MULAN_WANLING_COMMANDS = [
    {"label": "灵兽边境", "command": ".灵兽边境"},
    {"label": "巡边归来", "command": ".巡边归来"},
]
MULAN_WANLING_PATROL_ROUTES = ["斥候", "护粮", "袭营"]
MULAN_MANUAL_COMMANDS = [
    MULAN_PANEL_COMMAND,
    *MULAN_SUPPORT_COMMANDS,
    *MULAN_MERIT_COMMANDS,
    *MULAN_UTILITY_COMMANDS,
    *MULAN_WANLING_COMMANDS,
]
MULAN_ROUTE_ACTIONS = {
    "斥候探草原": {"label": "斥候", "command": ".支援慕兰 斥候"},
    "破慕兰圣灯": {"label": "破灯", "command": ".支援慕兰 破灯"},
    "固守边境法阵": {"label": "护阵", "command": ".支援慕兰 护阵"},
    "夜袭法士营": {"label": "奇袭", "command": ".支援慕兰 奇袭"},
}
MULAN_VALID_SUPPORT_COMMANDS = {
    item["command"] for item in MULAN_SUPPORT_COMMANDS
}

MULAN_TRUE_REPORT_TEXTS = (
    "边境粮道将过西岭，阵师缺人护送一批阵旗。",
    "今夜圣灯换焰，主灯会短暂离开护灯法士三十息。",
    "法士营北帐换防，附灵蛇胆与妖丹暂存在同一灵袋。",
    "有小股法士借草沟绕行，似在寻找黄龙山外阵缺口。",
)
MULAN_CREDIBLE_REPORT_JUDGEMENTS = {"较高", "可信", "较可信", "可靠", "属实"}
MULAN_SUSPICIOUS_REPORT_JUDGEMENTS = {"可疑", "假", "假报", "不实"}
MULAN_SECTION_TITLES = {"今日军议", "个人战绩"}
MULAN_PROFILE_LABELS = {
    "修士",
    "今日状态",
    "累计边境军功",
    "连续支援",
    "押中密令",
    "险棋得手",
    "最近支援",
}


def _normalize_mulan_section_title(line: str) -> str:
    return str(line or "").strip().strip("【】[]").strip("：:").strip()


def _mulan_labeled_line_key(line: str) -> str:
    normalized = str(line or "").strip().lstrip("-").strip()
    match = re.match(r"^([^：:]+)[：:]\s*(.*)$", normalized)
    return match.group(1).strip() if match else ""


def extract_mulan_section_lines(text: str, section_title: str) -> list[str]:
    target = str(section_title or "").strip()
    lines = []
    collecting = False
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line_title = _normalize_mulan_section_title(line)
        if line_title == target:
            collecting = True
            continue
        if not collecting:
            continue
        if line_title in MULAN_SECTION_TITLES and line_title != target:
            break
        if target == "今日军议" and _mulan_labeled_line_key(line) in MULAN_PROFILE_LABELS:
            break
        if line.startswith("【") and line.endswith("】"):
            break
        if line.startswith("可用行动") or line.startswith("可用指令"):
            break
        if line.startswith("."):
            break
        lines.append(line)
    return lines


def extract_mulan_labeled_value(lines: list[str], label: str) -> str:
    for line in lines:
        normalized = line.strip().lstrip("-").strip()
        match = re.match(rf"^{re.escape(label)}[：:]\s*(.+)$", normalized)
        if match:
            return match.group(1).strip()
    return ""


def parse_mulan_merit_exchange_items(text: str) -> list[dict]:
    items = []
    seen = set()
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        match = re.match(
            r"^[-•]\s*([^：:\n]+)[：:]\s*(\d+)\s*军功\s*(?:->|→)",
            line,
        )
        if not match:
            continue
        name = match.group(1).strip()
        cost = match.group(2).strip()
        if name and name not in seen:
            items.append(
                {
                    "name": name,
                    "cost": cost,
                    "label": f"{name}（{cost} 军功）",
                }
            )
            seen.add(name)
    return items


def extract_mulan_profile_lines(text: str) -> list[str]:
    lines = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _mulan_labeled_line_key(line) in MULAN_PROFILE_LABELS:
            lines.append(line)
    return lines


def refresh_mulan_summary(state: dict) -> dict:
    summary = []
    cultivator = str(state.get("cultivator") or "").strip()
    if cultivator:
        summary.append({"label": "修士", "value": cultivator})
    summary.extend(
        [
            {"label": "今日状态", "value": state.get("status") or "暂无"},
            {"label": "边境军功", "value": state.get("military_merit") or "-"},
            {"label": "连续支援", "value": state.get("streak") or "-"},
            {"label": "押中密令", "value": state.get("matched_orders") or "-"},
            {"label": "险棋得手", "value": state.get("risky_success") or "-"},
            {"label": "最近支援", "value": state.get("latest_support") or "-"},
        ]
    )
    state["summary"] = summary
    return state


def parse_mulan_panel_text(text: str) -> dict:
    raw_text = str(text or "").strip()
    council_lines = extract_mulan_section_lines(raw_text, "今日军议")
    record_lines = extract_mulan_profile_lines(raw_text)
    cultivator = extract_mulan_labeled_value(record_lines, "修士")
    status = extract_mulan_labeled_value(record_lines, "今日状态") or "暂无"
    military_merit = extract_mulan_labeled_value(record_lines, "累计边境军功") or "-"
    streak = extract_mulan_labeled_value(record_lines, "连续支援") or "-"
    matched_orders = extract_mulan_labeled_value(record_lines, "押中密令") or "-"
    risky_success = extract_mulan_labeled_value(record_lines, "险棋得手") or "-"
    latest_support = extract_mulan_labeled_value(record_lines, "最近支援") or "-"
    return refresh_mulan_summary({
        "available": bool(raw_text),
        "cultivator": cultivator,
        "status": status,
        "military_merit": military_merit,
        "streak": streak,
        "matched_orders": matched_orders,
        "risky_success": risky_success,
        "latest_support": latest_support,
        "daily_council": council_lines,
        "records": record_lines,
    })


def parse_mulan_support_result_text(text: str) -> dict:
    raw_text = str(text or "")
    if "【慕兰烽烟 ·" not in raw_text and "【慕兰烽烟·" not in raw_text:
        return {}
    result = {"status": "已支援"}
    merit_match = re.search(r"边境军功\s*\+\s*\d+[，,]\s*累计\s*(\d+)", raw_text)
    if merit_match:
        result["military_merit"] = merit_match.group(1).strip()
    streak_match = re.search(r"连续支援\s*([^\n。]+)", raw_text)
    if streak_match:
        result["streak"] = streak_match.group(1).strip()
    if "押中了今日【军议密令】" in raw_text:
        result["matched_order_hit"] = True
    return result


def mulan_line_value(lines: list[str], label: str) -> str:
    for line in lines:
        normalized = line.strip().lstrip("-").strip()
        if normalized.startswith(f"{label}："):
            return normalized.split("：", 1)[1].strip()
        if normalized.startswith(f"{label}:"):
            return normalized.split(":", 1)[1].strip()
    return ""


def mulan_action_from_route_text(text: str) -> dict:
    raw_text = str(text or "")
    for route, action in MULAN_ROUTE_ACTIONS.items():
        if route in raw_text:
            return {"route": route, **action}
    if "护阵" in raw_text or "边境大阵" in raw_text:
        return {"route": "固守边境法阵", **MULAN_ROUTE_ACTIONS["固守边境法阵"]}
    if "破灯" in raw_text or "圣灯" in raw_text:
        return {"route": "破慕兰圣灯", **MULAN_ROUTE_ACTIONS["破慕兰圣灯"]}
    if "奇袭" in raw_text or "法士营" in raw_text:
        return {"route": "夜袭法士营", **MULAN_ROUTE_ACTIONS["夜袭法士营"]}
    if "斥候" in raw_text or "探草原" in raw_text:
        return {"route": "斥候探草原", **MULAN_ROUTE_ACTIONS["斥候探草原"]}
    return {}


def build_mulan_recommendation(panel_state: dict) -> dict:
    if not panel_state.get("available"):
        return {
            "title": "先刷新边境军功",
            "command": "",
            "label": "",
            "route": "",
            "reasons": ["暂无今日军议，先刷新面板再判断路线。"],
            "blocked": True,
        }

    status = str(panel_state.get("status") or "").strip()
    if "已支援" in status:
        return {
            "title": "今日已支援",
            "command": "",
            "label": "",
            "route": "",
            "reasons": ["面板显示今日已支援，预案不会重复发送支援命令。"],
            "blocked": True,
        }

    council_lines = panel_state.get("daily_council") or []
    military_order = mulan_line_value(council_lines, "军议密令")
    grain_route = mulan_line_value(council_lines, "粮道通畅")
    celestial = mulan_line_value(council_lines, "天象")
    risky = mulan_line_value(council_lines, "险棋窗口")

    scores: dict[str, int] = {}
    actions: dict[str, dict] = {}
    reasons = []

    def add(action: dict, score: int, reason: str) -> None:
        command = str(action.get("command") or "").strip()
        if not command:
            return
        actions[command] = action
        scores[command] = scores.get(command, 0) + score
        if reason:
            reasons.append(reason)

    order_action = mulan_action_from_route_text(military_order)
    add(order_action, 4, f"军议密令指向 {order_action.get('route') or ''}。")
    grain_action = mulan_action_from_route_text(grain_route)
    add(grain_action, 2, f"粮道通畅加成指向 {grain_action.get('route') or ''}。")
    celestial_action = mulan_action_from_route_text(celestial)
    add(celestial_action, 1, f"天象偏向 {celestial_action.get('route') or ''}。")

    risky_action = mulan_action_from_route_text(risky)
    if risky_action:
        reasons.append(f"险棋窗口为 {risky_action.get('route')}，默认不优先贪风险。")

    if not scores:
        fallback = MULAN_ROUTE_ACTIONS["固守边境法阵"]
        return {
            "title": "建议护阵",
            "command": fallback["command"],
            "label": fallback["label"],
            "route": "固守边境法阵",
            "reasons": ["缺少明确军议加成，默认选择风险最低的护阵。"],
            "blocked": False,
        }

    best_command = max(
        scores,
        key=lambda command: (
            scores[command],
            1 if command == ".支援慕兰 护阵" else 0,
        ),
    )
    best_action = actions[best_command]
    return {
        "title": f"建议{best_action.get('label')}",
        "command": best_command,
        "label": best_action.get("label") or "",
        "route": best_action.get("route") or "",
        "reasons": [reason for reason in reasons if reason.strip()][:4],
        "blocked": False,
    }


def build_mulan_auto_support_view(raw_task: dict | None, recommendation: dict) -> dict:
    task = raw_task or {}
    saved_command = str(task.get("strategy") or "").strip()
    saved = bool(task)
    enabled = bool(task.get("enabled")) if task else False
    if enabled:
        status = str(task.get("last_error") or "").strip() or "自动慕兰运行中。"
    elif saved:
        status = str(task.get("last_error") or "").strip() or "自动慕兰已停止。"
    else:
        status = "未开启自动慕兰。"
    candidate_command = str(recommendation.get("command") or "").strip()
    return {
        "feature_key": MULAN_AUTO_SUPPORT_FEATURE_KEY,
        "saved": saved,
        "enabled": enabled,
        "saved_command": "" if saved_command == "auto" else saved_command,
        "status": status,
        "candidate_command": (
            candidate_command if candidate_command in MULAN_VALID_SUPPORT_COMMANDS else "auto"
        ),
        "can_save": True,
        "button_label": "停止自动慕兰" if enabled else "开启自动慕兰",
    }


def parse_mulan_report_options(text: str) -> list[dict]:
    reports = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip().lstrip("-").strip()
        match = re.match(r"^(?:[【\[]?)(\d+)(?:[】\].、:：\s]+)(.+)$", line)
        if not match:
            continue
        number = match.group(1).strip()
        report_text = match.group(2).strip()
        if number and report_text:
            reports.append({"number": number, "text": report_text})
    return reports


def select_known_true_report(text: str) -> dict:
    reports = parse_mulan_report_options(text)
    for report in reports:
        report_text = str(report.get("text") or "")
        for true_text in MULAN_TRUE_REPORT_TEXTS:
            if true_text in report_text:
                return {
                    "number": str(report.get("number") or "").strip(),
                    "text": true_text,
                }
    return {}


def build_mulan_verify_report_command(number: object) -> str:
    normalized = str(number or "").strip()
    return f"{MULAN_VERIFY_REPORT_COMMAND_PREFIX} {normalized}" if normalized else ""


def build_mulan_public_report_command(number: object) -> str:
    normalized = str(number or "").strip()
    return f".公开军报 {normalized}" if normalized else ""


def parse_mulan_report_judgement(text: str) -> dict:
    raw_text = str(text or "")
    limited = "辨报受限" in raw_text
    number_match = re.search(r"【辨报[·#](\d+)】", raw_text)
    public_match = re.search(r"\.公开军报\s+(\d+)", raw_text)
    judgement_match = re.search(r"研判[：:]\s*([^\s\n。]+)", raw_text)
    judgement = judgement_match.group(1).strip() if judgement_match else ""
    suspicious = any(marker in judgement for marker in MULAN_SUSPICIOUS_REPORT_JUDGEMENTS)
    credible = (
        not suspicious
        and bool(judgement)
        and (
            judgement in MULAN_CREDIBLE_REPORT_JUDGEMENTS
            or "高" in judgement
            or "可信" in judgement
            or "可靠" in judgement
            or "属实" in judgement
        )
    )
    number = (
        number_match.group(1).strip()
        if number_match
        else (public_match.group(1).strip() if public_match else "")
    )
    return {
        "number": number,
        "judgement": judgement,
        "public_command": build_mulan_public_report_command(
            public_match.group(1).strip() if public_match else number
        ),
        "credible": credible,
        "suspicious": suspicious,
        "limited": limited,
    }
