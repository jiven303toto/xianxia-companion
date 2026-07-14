import re
import time
from typing import Any, Optional


TIANXING_PREDICTION_SECONDS = 8 * 3600
TIANXING_CHANGE_FATE_SECONDS = 24 * 3600
TIANXING_STARS = ("紫微", "天府", "太阴", "贪狼")
TIANXING_ROUTES = ("闭关", "炼制", "探索", "斗法")

RE_BRACKET = re.compile(r"【([^】]+)】")
RE_TIANJI_VALUE = re.compile(r"天机值[:：]\s*(\d+)")
RE_CALAMITY = re.compile(r"逆命劫[:：]\s*(\d+)")
RE_COUNTS = re.compile(r"命中\s*/\s*落空\s*/\s*改命[:：]\s*(\d+)\s*/\s*(\d+)\s*/\s*(\d+)")
RE_TIANJI_GAIN = re.compile(r"天机值\s*\+(\d+)")
RE_CONTRIB_GAIN = re.compile(r"宗门贡献\s*\+(\d+)")
RE_CALAMITY_GAIN = re.compile(r"逆命劫\s*\+(\d+)")
RE_BONUS_GAIN = re.compile(r"因【天星宗】灵脉加持，你额外获得了\s*(\d+)\s*点修为")
RE_STAR_EFFECT = re.compile(r"命盘【([^】]+)】照命([^\n]*)")
RE_SET_STAR = re.compile(r"你将今日命轨定在\s*【([^】]+)】")
RE_PREDICT = re.compile(r"为\s*【([^】]+)】\s*推下了?一段命数")
RE_CHANGE_FATE = re.compile(r"为\s*【([^】]+)】\s*预留了?一次改命回天")
RE_EXISTING_ROUTE = re.compile(r"你已有一道关于\s*【([^】]+)】\s*的")
RE_CRAFT_DONE = re.compile(r"共开炉\s*(\d+)\s*次，成功\s*(\d+)\s*次")
RE_CRAFT_GAIN = re.compile(r"最终获得【([^】]+)】x(\d+)")


def get_day_key(now: Optional[float] = None) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(time.time() if now is None else now))


def parse_chinese_duration_seconds(text: str) -> int:
    raw = str(text or "")
    total = 0
    for pattern, scale in (
        (r"(\d+)\s*天", 24 * 3600),
        (r"(\d+)\s*小时", 3600),
        (r"(\d+)\s*分钟", 60),
        (r"(\d+)\s*秒", 1),
    ):
        match = re.search(pattern, raw)
        if match:
            total += int(match.group(1)) * scale
    return total


def looks_like_tianxing_text(text: str) -> bool:
    raw = str(text or "")
    markers = (
        "天机盘",
        "观命结果",
        "司命盘",
        "命盘【",
        "推命命中",
        "推命落空",
        "改命待发",
        "改命回天",
        "逆命劫",
        "天星宗",
    )
    return any(marker in raw for marker in markers)


def family_for_command(command: str) -> str:
    raw = str(command or "").strip()
    if raw == ".天机盘":
        return "tianxing_panel"
    if raw == ".观命":
        return "tianxing_observe"
    if raw.startswith(".定命"):
        return "tianxing_set_star"
    if raw.startswith(".推命"):
        return "tianxing_predict"
    if raw.startswith(".改命"):
        return "tianxing_change_fate"
    if raw == ".消劫":
        return "tianxing_clear_calamity"
    if raw.startswith(".炼制"):
        return "tianxing_craft_farm"
    if raw.startswith(".闭关") or raw.startswith(".闭关修炼"):
        return "tianxing_retreat_farm"
    if looks_like_tianxing_text(raw):
        return "tianxing_modifier"
    return ""


def command_for_action(action: str, arg: str = "") -> str:
    normalized = str(action or "").strip()
    value = str(arg or "").strip()
    if normalized == "panel":
        return ".天机盘"
    if normalized == "observe":
        return ".观命"
    if normalized == "clear_calamity":
        return ".消劫"
    if normalized == "set_star" and value:
        return f".定命 {value}"
    if normalized == "predict" and value:
        return f".推命 {value}"
    if normalized == "change_fate" and value:
        return f".改命 {value}"
    return ""


def _bracket_values(line: str) -> list[str]:
    return [item.strip() for item in RE_BRACKET.findall(line or "") if item.strip()]


def _route_from_text(text: str) -> str:
    for route in TIANXING_ROUTES:
        if route in str(text or ""):
            return route
    return ""


def _settlement_route_from_text(text: str) -> str:
    raw = str(text or "")
    if "野外历练" in raw or "探寻成功" in raw or "裂缝" in raw:
        return "探索"
    if "炼制结束" in raw or "共开炉" in raw:
        return "炼制"
    if "闭关成功" in raw or "本次闭关" in raw:
        return "闭关"
    if "天道战报" in raw or "斗法" in raw:
        return "斗法"
    return _route_from_text(raw)


def _duration_until(text: str, now: float, default_seconds: int) -> float:
    duration = parse_chinese_duration_seconds(text)
    return now + float(duration if duration > 0 else default_seconds)


def _explicit_duration_until(text: str, now: float) -> float:
    duration = parse_chinese_duration_seconds(text)
    return now + float(duration) if duration > 0 else 0


def _parse_panel(text: str, now: float) -> dict[str, Any]:
    parsed: dict[str, Any] = {"action": "天机盘", "result": "panel"}
    for line in str(text or "").splitlines():
        if "今日可选命星" in line:
            parsed["available_stars"] = [
                star for star in _bracket_values(line) if star in TIANXING_STARS
            ]
            parsed["available_stars_source"] = "panel"
            parsed["available_stars_day"] = get_day_key(now)
        elif "今日已定命星" in line:
            stars = [star for star in _bracket_values(line) if star in TIANXING_STARS]
            parsed["fixed_star"] = stars[0] if stars else ""
            parsed["fixed_star_day"] = get_day_key(now) if stars else ""
        elif "当前推命" in line:
            route = _route_from_text(line)
            parsed["current_prediction"] = route
            parsed["current_prediction_until"] = _explicit_duration_until(line, now) if route else 0
            parsed["current_prediction_until_source"] = "panel" if route else ""
        elif "当前改命" in line:
            route = _route_from_text(line)
            parsed["current_change"] = route
            parsed["current_change_until"] = _explicit_duration_until(line, now) if route else 0
            parsed["current_change_until_source"] = "panel" if route else ""
    return parsed


def _parse_observe(text: str, now: float) -> dict[str, Any]:
    stars = []
    for line in str(text or "").splitlines():
        values = [star for star in _bracket_values(line) if star in TIANXING_STARS]
        for star in values:
            if star not in stars:
                stars.append(star)
    return {
        "action": "观命",
        "result": "observe",
        "available_stars": stars,
        "available_stars_source": "observe",
        "available_stars_day": get_day_key(now),
    }


def parse_tianxing_text(text: str, *, now: Optional[float] = None, family: str = "") -> dict[str, Any]:
    raw = str(text or "").strip()
    current_time = float(time.time() if now is None else now)
    parsed: dict[str, Any] = {
        "family": str(family or "").strip(),
        "raw_text": raw,
        "is_tianxing": looks_like_tianxing_text(raw)
        or str(family or "").strip().startswith("tianxing_"),
    }
    if not raw:
        return {**parsed, "action": "", "result": "empty", "is_tianxing": False}

    if "【天机盘】" in raw or "今日可选命星" in raw or "当前推命" in raw:
        parsed.update(_parse_panel(raw, current_time))
    elif "【观命结果】" in raw or "今日可定下的命星" in raw:
        parsed.update(_parse_observe(raw, current_time))
    elif "此命星并未在你今日观命结果中显化" in raw:
        parsed.update({
            "action": "定命",
            "result": "need_observe",
            "available_stars": [],
            "available_stars_source": "",
        })
    elif (match := RE_SET_STAR.search(raw)):
        star = match.group(1).strip()
        parsed.update({
            "action": "定命",
            "result": "success",
            "fixed_star": star,
            "fixed_star_day": get_day_key(current_time),
        })
    elif (match := RE_PREDICT.search(raw)):
        route = match.group(1).strip()
        parsed.update({
            "action": "推命",
            "result": "success",
            "current_prediction": route,
            "current_prediction_until": _duration_until(raw, current_time, TIANXING_PREDICTION_SECONDS),
            "current_prediction_until_source": "predict_reply",
            "current_prediction_set_at": current_time,
        })
    elif (match := RE_CHANGE_FATE.search(raw)):
        route = match.group(1).strip()
        parsed.update({
            "action": "改命",
            "result": "success",
            "current_change": route,
            "current_change_until": _duration_until(raw, current_time, TIANXING_CHANGE_FATE_SECONDS),
            "current_change_until_source": "change_reply",
        })
    elif "你已有一道关于" in raw and (match := RE_EXISTING_ROUTE.search(raw)):
        route = match.group(1).strip()
        action = "改命" if "改命" in raw else "推命"
        parsed.update({
            "action": action,
            "result": "cooldown",
            "current_change" if action == "改命" else "current_prediction": route,
            "current_change_until" if action == "改命" else "current_prediction_until": _duration_until(
                raw,
                current_time,
                TIANXING_CHANGE_FATE_SECONDS if action == "改命" else TIANXING_PREDICTION_SECONDS,
            ),
            "current_change_until_source" if action == "改命" else "current_prediction_until_source": "cooldown_reply",
        })
    elif "当前并无逆命劫" in raw:
        parsed.update({"action": "消劫", "result": "noop", "calamity_count": 0})
    elif "成功化去" in raw and "逆命劫" in raw:
        parsed.update({"action": "消劫", "result": "success"})
    elif "兑换成功" in raw and "合气丹" in raw:
        parsed.update({"action": "兑换合气丹", "result": "success"})
    elif "储物袋中没有名为【合气丹】" in raw:
        parsed.update({"action": "合气丹", "result": "missing"})
    elif "闭关" in raw and ("无法立即再次闭关" in raw or "灵气尚未平复" in raw):
        parsed.update({
            "action": "闭关",
            "result": "cooldown",
            "normal_retreat_next_time": current_time + parse_chinese_duration_seconds(raw),
        })
    elif "闭关成功" in raw or "本次闭关" in raw:
        parsed.update({"action": "闭关", "result": "settlement"})
    elif "炼制结束" in raw or "共开炉" in raw:
        parsed.update({"action": "炼制", "result": "settlement"})
    elif "【推命命中】" in raw:
        parsed.update({"action": _settlement_route_from_text(raw) or "路线结算", "result": "prediction_hit"})
    elif "【推命落空】" in raw:
        parsed.update({"action": _settlement_route_from_text(raw) or "路线结算", "result": "prediction_miss"})
    elif "【改命回天】" in raw:
        parsed.update({"action": _settlement_route_from_text(raw) or "路线结算", "result": "change_triggered"})
    elif "【天星宗" in raw and "司命推演" in raw:
        parsed.update({"action": "玩法帮助", "result": "guide"})
    elif "成功拜入【天星宗】" in raw:
        parsed.update({"action": "拜入天星宗", "result": "success"})
    elif "已是【天星宗】" in raw:
        parsed.update({"action": "拜入天星宗", "result": "already_member"})
    elif parsed["is_tianxing"]:
        parsed.update({"action": "未知天星宗文案", "result": "observed", "unknown": True})
    else:
        parsed.update({"action": "", "result": "ignored", "is_tianxing": False})

    if "【推命命中】" in raw:
        parsed["result"] = "prediction_hit"
        parsed["action"] = _settlement_route_from_text(raw) or parsed.get("action") or "路线结算"
    if "【推命落空】" in raw:
        parsed["result"] = "prediction_miss"
        parsed["action"] = _settlement_route_from_text(raw) or parsed.get("action") or "路线结算"
        parsed["calamity_delta"] = int((RE_CALAMITY_GAIN.search(raw) or [None, 1])[1] or 1)
    if "【改命回天】" in raw:
        parsed["result"] = "change_triggered"
        parsed["action"] = _settlement_route_from_text(raw) or parsed.get("action") or "路线结算"
        parsed["current_change"] = ""
        parsed["current_change_until"] = 0
        parsed["current_change_until_source"] = ""
    if "【改命待发】" in raw:
        parsed["change_pending_until"] = _duration_until(raw, current_time, TIANXING_CHANGE_FATE_SECONDS)
        parsed["current_change_until_source"] = "settlement_reply"

    if match := RE_TIANJI_VALUE.search(raw):
        parsed["tianji_value"] = int(match.group(1))
    if match := RE_CALAMITY.search(raw):
        parsed["calamity_count"] = int(match.group(1))
    if match := RE_COUNTS.search(raw):
        parsed["hit_count"] = int(match.group(1))
        parsed["miss_count"] = int(match.group(2))
        parsed["change_count"] = int(match.group(3))
    if match := RE_TIANJI_GAIN.search(raw):
        parsed["last_tianji_gain"] = int(match.group(1))
    if match := RE_CONTRIB_GAIN.search(raw):
        parsed["last_contrib_gain"] = int(match.group(1))
    if match := RE_BONUS_GAIN.search(raw):
        parsed["last_bonus_gain"] = int(match.group(1))
    if match := RE_STAR_EFFECT.search(raw):
        parsed["last_star_effect"] = f"{match.group(1).strip()} {match.group(2).strip()}".strip()
    if match := RE_CRAFT_DONE.search(raw):
        parsed["craft_count"] = int(match.group(1))
        parsed["craft_success_count"] = int(match.group(2))
    if match := RE_CRAFT_GAIN.search(raw):
        parsed["craft_item"] = match.group(1).strip()
        parsed["craft_gain_count"] = int(match.group(2))
    return parsed
