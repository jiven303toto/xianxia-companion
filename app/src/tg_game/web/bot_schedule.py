from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
TASK_NAME = "ZidongXiuxian Telegram Bot Sync"
INSTALL_SCRIPT_PATH = PROJECT_ROOT / "tools" / "install_telegram_game_bot_schedule.ps1"
LOG_PATH = PROJECT_ROOT / "data" / "telegram_game_bot_schedule.log"
ALLOWED_INTERVAL_HOURS = (1, 2, 3, 6, 12, 24)
INTERRUPTED_TASK_RESULT = 0xC000013A


def normalize_interval_hours(value: object) -> int:
    interval = int(str(value or "").strip())
    if interval not in ALLOWED_INTERVAL_HOURS:
        raise ValueError("执行间隔只允许 1、2、3、6、12 或 24 小时")
    return interval


def _run_powershell(arguments: list[str], timeout_seconds: int = 20) -> subprocess.CompletedProcess:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", *arguments],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(int(timeout_seconds), 1),
        creationflags=creationflags,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "计划任务操作失败").strip())
    return result


def _query_task() -> dict:
    script = f"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ErrorActionPreference = 'Stop'
$task = Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue
if ($null -eq $task) {{
    [pscustomobject]@{{ exists = $false }} | ConvertTo-Json -Compress
    exit 0
}}
$info = Get-ScheduledTaskInfo -TaskName '{TASK_NAME}'
$trigger = @($task.Triggers)[0]
[pscustomobject]@{{
    exists = $true
    state = [string]$task.State
    interval = [string]$trigger.Repetition.Interval
    start_boundary = [string]$trigger.StartBoundary
    last_run = if ($info.LastRunTime.Year -gt 2000) {{ $info.LastRunTime.ToString('o') }} else {{ '' }}
    next_run = if ($info.NextRunTime.Year -gt 2000) {{ $info.NextRunTime.ToString('o') }} else {{ '' }}
    last_result = [long]$info.LastTaskResult
}} | ConvertTo-Json -Compress
"""
    result = _run_powershell(["-Command", script])
    output = str(result.stdout or "").strip()
    if not output:
        raise RuntimeError("计划任务状态为空")
    return json.loads(output.splitlines()[-1])


def _format_datetime(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "尚无"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone().strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except ValueError:
        return text


def _interval_from_iso(value: object) -> int:
    match = re.fullmatch(r"PT(\d+)H", str(value or "").strip(), re.IGNORECASE)
    if not match:
        return 1
    interval = int(match.group(1))
    return interval if interval in ALLOWED_INTERVAL_HOURS else 1


def load_latest_schedule_log(path: Path | None = None) -> dict:
    log_path = path or LOG_PATH
    result = {
        "last_log_time": "尚无",
        "last_elapsed_seconds": None,
        "last_status": "",
        "latest_summary": "尚无执行记录",
        "last_live_bot_count": None,
        "last_trusted_bot_count": None,
        "last_new_bot_count": 0,
        "last_schedule_profiles_checked": None,
        "last_schedule_tasks_checked": None,
        "last_schedule_overdue_count": None,
        "last_schedule_requeued_count": None,
        "last_schedule_skipped_count": None,
        "last_schedule_skip_reasons": "",
        "last_output": "",
    }
    try:
        text = log_path.read_text(encoding="utf-8")
    except OSError:
        return result
    matches = list(
        re.finditer(
            r"^\[(?P<time>[^\]]+)\] status=(?P<status>\w+) "
            r"exit=(?P<exit>-?\d+) elapsed=(?P<elapsed>[\d.]+)s$",
            text,
            re.MULTILINE,
        )
    )
    if not matches:
        return result
    header = matches[-1]
    output = text[header.end() :].strip()
    live_match = re.search(r"^群上游戏 Bot: (\d+)$", output, re.MULTILINE)
    trusted_match = re.search(r"^同步后目标 Bot 数: (\d+)$", output, re.MULTILINE)
    reconcile_match = re.search(
        r"^调度补偿统计: profiles=(\d+) checked=(\d+) overdue=(\d+) "
        r"eligible=(\d+) requeued=(\d+) commands=(\d+) skipped=(\d+) failed=(\d+)$",
        output,
        re.MULTILINE,
    )
    reconcile_skip_match = re.search(
        r"^调度补偿跳过: (.+)$", output, re.MULTILINE
    )
    new_count = len(re.findall(r"\[新增\]$", output, re.MULTILINE))
    status = header.group("status")
    if status != "success":
        summary = "执行失败"
    elif "本地已经与群上 Bot 清单同步" in output:
        summary = "无新增，扫描状态已刷新"
    elif "同步完成" in output:
        summary = f"新增并同步 {new_count} 个 Bot" if new_count else "同步完成"
    else:
        summary = "执行成功"
    if status == "success" and reconcile_match:
        requeued_count = int(reconcile_match.group(5))
        overdue_count = int(reconcile_match.group(3))
        if requeued_count:
            summary += f"；补偿入队 {requeued_count} 项"
        elif overdue_count:
            summary += "；过期项均已跳过或复核"
        else:
            summary += "；无漏执行调度"
    result.update(
        {
            "last_log_time": _format_datetime(header.group("time")),
            "last_elapsed_seconds": float(header.group("elapsed")),
            "last_status": status,
            "latest_summary": summary,
            "last_live_bot_count": int(live_match.group(1)) if live_match else None,
            "last_trusted_bot_count": int(trusted_match.group(1)) if trusted_match else None,
            "last_new_bot_count": new_count,
            "last_schedule_profiles_checked": (
                int(reconcile_match.group(1)) if reconcile_match else None
            ),
            "last_schedule_tasks_checked": (
                int(reconcile_match.group(2)) if reconcile_match else None
            ),
            "last_schedule_overdue_count": (
                int(reconcile_match.group(3)) if reconcile_match else None
            ),
            "last_schedule_requeued_count": (
                int(reconcile_match.group(5)) if reconcile_match else None
            ),
            "last_schedule_skipped_count": (
                int(reconcile_match.group(7)) if reconcile_match else None
            ),
            "last_schedule_skip_reasons": (
                reconcile_skip_match.group(1).strip()
                if reconcile_skip_match
                else ""
            ),
            "last_output": output[-6000:],
        }
    )
    return result


def load_bot_schedule_state() -> dict:
    log_state = load_latest_schedule_log()
    server_time = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    state = {
        "exists": False,
        "enabled": False,
        "running": False,
        "state": "Missing",
        "state_label": "任务未安装",
        "status_class": "is-disabled",
        "interval_hours": 1,
        "interval_options": ALLOWED_INTERVAL_HOURS,
        "server_time": server_time,
        "first_run": "尚无",
        "last_run": "尚无",
        "next_run": "尚无",
        "last_task_result": None,
        "last_task_result_label": "尚无",
        "error": "",
        **log_state,
    }
    try:
        task = _query_task()
    except Exception as exc:
        state.update(
            {
                "state": "Error",
                "state_label": "状态读取失败",
                "status_class": "is-error",
                "error": str(exc),
            }
        )
        return state
    if not bool(task.get("exists")):
        return state
    task_state = str(task.get("state") or "Unknown")
    running = task_state.lower() == "running"
    enabled = task_state.lower() != "disabled"
    last_result = int(task.get("last_result") or 0)
    last_run_value = str(task.get("last_run") or "").strip()
    if running:
        state_label = "正在执行"
        status_class = "is-running"
    elif enabled:
        state_label = "已开启"
        status_class = "is-enabled"
    else:
        state_label = "已关闭"
        status_class = "is-disabled"
    state.update(
        {
            "exists": True,
            "enabled": enabled,
            "running": running,
            "state": task_state,
            "state_label": state_label,
            "status_class": status_class,
            "interval_hours": _interval_from_iso(task.get("interval")),
            "first_run": _format_datetime(task.get("start_boundary")),
            "last_run": _format_datetime(last_run_value),
            "next_run": _format_datetime(task.get("next_run")) if enabled else "已暂停",
            "last_task_result": last_result,
            "last_task_result_label": (
                "尚无"
                if not last_run_value
                else (
                    "成功"
                    if last_result == 0
                    else (
                        "已被用户中断 (0xC000013A)"
                        if last_result == INTERRUPTED_TASK_RESULT
                        else f"失败 ({last_result})"
                    )
                )
            ),
        }
    )
    return state


def update_bot_schedule(
    interval_hours: object,
    *,
    keep_disabled: bool = False,
) -> str:
    interval = normalize_interval_hours(interval_hours)
    arguments = [
        "-File",
        str(INSTALL_SCRIPT_PATH),
        "-IntervalHours",
        str(interval),
    ]
    if keep_disabled:
        arguments.append("-KeepDisabled")
    return str(_run_powershell(arguments).stdout or "").strip()


def set_bot_schedule_enabled(enabled: bool, current_state: dict) -> str:
    if enabled:
        return update_bot_schedule(
            current_state.get("interval_hours", 1),
        )
    return str(
        _run_powershell(["-File", str(INSTALL_SCRIPT_PATH), "-Disable"]).stdout or ""
    ).strip()


def build_schedule_action_result(
    title: str,
    message: str,
    state: dict,
    *,
    ok: bool = True,
    raw_output: str = "",
) -> dict:
    details = [
        ("自动化状态", state.get("state_label") or "未知"),
        ("执行周期", f"每 {state.get('interval_hours', 1)} 小时"),
        ("服务器时间", state.get("server_time") or "尚无"),
        ("首次执行", state.get("first_run") or "尚无"),
        ("上次执行", state.get("last_run") or "尚无"),
        ("下次执行", state.get("next_run") or "尚无"),
        ("最近结果", state.get("latest_summary") or "尚无执行记录"),
    ]
    return {
        "ok": bool(ok),
        "status": "updated" if ok else "failed",
        "title": title,
        "message": message,
        "details": details,
        "elapsed_seconds": 0,
        "raw_output": str(raw_output or ""),
    }
