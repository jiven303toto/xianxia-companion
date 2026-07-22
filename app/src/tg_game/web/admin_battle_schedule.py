import re
from datetime import datetime

from tg_game.features.battle import biz_battle_schedule as battle_schedule
from tg_game.storage import Storage


STATUS_LABELS = {
    "idle": "未执行",
    "running": "执行中",
    "completed": "已完成",
    "failed": "失败",
    "stopped": "已停止",
    "waiting": "等待调度",
    "awaiting_reply": "等待战报",
    "skipped": "已跳过",
}

EVENT_LABELS = {
    "started": "批次开始",
    "queued": "命令入队",
    "lost": "战败",
    "escape": "逃脱",
    "unexpected_win": "意外获胜",
    "daily_limit": "次数已满",
    "target_win_limit": "目标受限",
    "failed": "失败",
    "timeout": "战报超时",
    "stopped": "已停止",
    "completed": "批次完成",
}

LOSS_RESULT_PATTERN = re.compile(
    r"战败，向目标转移\s*(?P<gain>[^\s]+)\s*修为；双方磨损\s*(?P<loser>[^/]+)/(?P<winner>\S+)"
)
AFTERMATH_PATTERN = re.compile(
    r"败者进入【(?P<status>[^】]+)】\s*(?P<minutes>\d+)\s*分钟"
)
LOOT_PATTERN = re.compile(r"【杀人夺宝】\s*(?P<value>[^\r\n]+)")


def _format_timestamp(value: float | int | None) -> str:
    timestamp = float(value or 0)
    if timestamp <= 0:
        return "—"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _format_clock(value: float | int | None) -> str:
    timestamp = float(value or 0)
    if timestamp <= 0:
        return ""
    return datetime.fromtimestamp(timestamp).strftime("%H:%M:%S")


def _build_result_view(item: dict, *, reply_text: str = "") -> dict:
    result_text = str(item.get("last_result") or item.get("last_error") or "").strip()
    remaining = item.get("remaining_spirit")
    details = []
    if result_text.startswith("战败"):
        match = LOSS_RESULT_PATTERN.search(result_text)
        summary = result_text
        if match:
            summary = f"向目标转移 {match.group('gain')} 修为"
            details.append(
                {
                    "label": "法宝磨损",
                    "value": f"攻击方 {match.group('loser')} · 目标 {match.group('winner')}",
                }
            )
        if remaining is not None:
            details.append({"label": "剩余神念", "value": f"{remaining}/10"})
        next_action = _format_clock(item.get("next_action_at"))
        if next_action:
            details.append(
                {
                    "label": "再次出手",
                    "value": f"{next_action} · 安全等待 15分15秒",
                }
            )
        aftermath = AFTERMATH_PATTERN.search(reply_text)
        details.append(
            {
                "label": "战后状态",
                "value": (
                    f"{aftermath.group('status')} {aftermath.group('minutes')}分钟"
                    if aftermath
                    else "败者虚弱约 10 分钟"
                ),
            }
        )
        loot = LOOT_PATTERN.search(reply_text)
        if loot:
            details.append(
                {
                    "label": "目标方战后掉落",
                    "value": loot.group("value").strip(),
                }
            )
        transferred = int(item.get("cultivation_transferred") or 0)
        if transferred:
            details.append({"label": "累计转移", "value": f"{transferred:,} 修为"})
        return {
            "label": "战败",
            "tone": "lost",
            "summary": summary,
            "details": details,
        }
    if result_text.startswith("侥幸逃脱"):
        if remaining is not None:
            details.append({"label": "剩余神念", "value": f"{remaining}/10"})
        next_action = _format_clock(item.get("next_action_at"))
        if next_action:
            details.append({"label": "再次出手", "value": next_action})
        return {
            "label": "逃脱",
            "tone": "escape",
            "summary": "神念已消耗，本次未转移修为",
            "details": details,
        }
    if result_text.startswith("斗法命令已入队"):
        return {
            "label": "等待战报",
            "tone": "queued",
            "summary": "命令已发送，等待 Bot 最终结算",
            "details": [],
        }
    if result_text.startswith("目标正在进行其他战斗"):
        next_action = _format_clock(item.get("next_action_at"))
        return {
            "label": "目标忙碌",
            "tone": "waiting",
            "summary": "目标正在进行其他战斗",
            "details": ([{"label": "再次检查", "value": next_action}] if next_action else []),
        }
    if result_text.startswith("目标元神尚未平复"):
        next_action = _format_clock(item.get("next_action_at"))
        return {
            "label": "目标冷却",
            "tone": "waiting",
            "summary": "目标仍处于斗法冷却",
            "details": ([{"label": "再次检查", "value": next_action}] if next_action else []),
        }
    if result_text.startswith("当前 Profile 仍有其他群命令"):
        next_action = _format_clock(item.get("next_action_at"))
        return {
            "label": "排队中",
            "tone": "waiting",
            "summary": result_text,
            "details": ([{"label": "再次检查", "value": next_action}] if next_action else []),
        }
    if result_text:
        return {
            "label": "状态更新" if not item.get("last_error") else "失败",
            "tone": "info" if not item.get("last_error") else "failed",
            "summary": result_text,
            "details": [],
        }
    return {
        "label": "等待执行",
        "tone": "idle",
        "summary": "尚无斗法结果",
        "details": [],
    }


def build_dashboard(
    storage: Storage,
) -> dict:
    state = battle_schedule.load_state(storage)
    config = state["config"]
    batch = state["batch"]
    selected_profile_ids = {
        int(profile_id) for profile_id in config.get("selected_profile_ids") or []
    }
    profile_options = []
    for profile_number, profile in enumerate(
        sorted(storage.list_profiles(), key=lambda value: int(value.id)),
        start=1,
    ):
        try:
            account_name = battle_schedule.normalize_username(
                profile.account_name or profile.telegram_username
            )
        except ValueError:
            account_name = ""
        unavailable_reason = battle_schedule._profile_unavailable_reason(storage, profile)
        profile_options.append(
            {
                "id": int(profile.id),
                "profile_label": f"Profile {profile_number}",
                "profile_name": profile.display_name or profile.game_name or profile.name,
                "account_name": account_name or "未绑定 username",
                "stage_name": profile.stage_name or "境界未同步",
                "cultivation_text": profile.cultivation_text or "修为未同步",
                "available": not unavailable_reason,
                "unavailable_reason": unavailable_reason,
                "selected": int(profile.id) in selected_profile_ids,
            }
        )
    items = []
    try:
        battle_command = battle_schedule.build_command(batch.get("target_username") or "")
    except ValueError:
        battle_command = ""
    for item in batch.get("items") or []:
        remaining = item.get("remaining_spirit")
        reply_text = ""
        if battle_command and str(item.get("last_result") or "").startswith("战败"):
            reply = storage.get_latest_bot_reply_for_command(
                int(item.get("chat_id") or 0),
                battle_command,
                profile_id=int(item.get("profile_id") or 0),
                thread_id=item.get("thread_id"),
            )
            if reply:
                reply_text = str(reply.get("text") or "")
        result_view = _build_result_view(item, reply_text=reply_text)
        items.append(
            {
                **item,
                "status_label": STATUS_LABELS.get(
                    item.get("status") or "",
                    item.get("status") or "未知",
                ),
                "progress": f"{int(item.get('attempts') or 0)}/{int(item.get('daily_attempts') or 0)}",
                "remaining_display": f"{remaining}/10" if remaining is not None else "—",
                "transferred_display": f"{int(item.get('cultivation_transferred') or 0):,}",
                "next_action_display": _format_timestamp(item.get("next_action_at")),
                "result_view": result_view,
            }
        )
    events = []
    for event in reversed(batch.get("events") or []):
        events.append(
            {
                **event,
                "at_display": _format_timestamp(event.get("at")),
                "profile_name": event.get("profile_name") or "全局",
                "result_label": EVENT_LABELS.get(
                    event.get("result") or "",
                    event.get("result") or "状态更新",
                ),
                "result_tone": event.get("result") or "info",
            }
        )
    return {
        "config": {
            **config,
            "next_run_display": _format_timestamp(config.get("next_run_at")),
            "last_run_display": _format_timestamp(config.get("last_run_at")),
        },
        "batch": {
            **batch,
            "status_label": STATUS_LABELS.get(
                batch.get("status") or "idle",
                batch.get("status") or "未知",
            ),
            "started_at_display": _format_timestamp(batch.get("started_at")),
            "completed_at_display": _format_timestamp(batch.get("completed_at")),
            "target_ready_display": _format_timestamp(batch.get("target_ready_at")),
            "items": items,
            "events": events,
        },
        "profile_options": profile_options,
        "active": batch.get("status") == "running",
        "can_start": bool(config.get("target_username") and selected_profile_ids)
        and batch.get("status") != "running",
        "total_transferred": sum(
            int(item.get("cultivation_transferred") or 0) for item in items
        ),
    }
