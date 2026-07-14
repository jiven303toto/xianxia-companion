from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[4]
PYTHON_PATH = (
    PROJECT_ROOT.parent
    / ".venvs"
    / PROJECT_ROOT.name
    / "Scripts"
    / "python.exe"
)
SCRIPT_PATH = PROJECT_ROOT / "tools" / "sync_telegram_game_bots.py"
RESULT_FILE_NAME = "telegram_game_bot_web_result.json"
COMMAND_ARGS = ("--apply", "--message-limit", "5000")


def _parse_int(pattern: str, text: str) -> int:
    match = re.search(pattern, text, re.MULTILINE)
    return int(match.group(1)) if match else 0


def parse_bot_sync_output(
    stdout: str,
    stderr: str,
    returncode: int,
    elapsed_seconds: float,
    *,
    timed_out: bool = False,
) -> dict:
    output = str(stdout or "").replace("\r\n", "\n").replace("\r", "\n")
    error = str(stderr or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    group_match = re.search(r"^群: (.+) \((-?\d+)\)$", output, re.MULTILINE)
    new_bots = [
        {"username": match.group(1), "bot_id": int(match.group(2))}
        for match in re.finditer(
            r"^- ([A-Za-z0-9_]+): (\d+) \[新增\]$",
            output,
            re.MULTILINE,
        )
    ]
    retained_match = re.search(r"^保留的旧轮换 Bot ID: (.+)$", output, re.MULTILINE)
    backup_match = re.search(r"^数据库备份: (.+)$", output, re.MULTILINE)
    unchanged = "本地已经与群上 Bot 清单同步" in output
    ok = not timed_out and int(returncode) == 0
    if timed_out:
        status = "timeout"
        title = "Bot 同步超时"
        message = "同步超过 180 秒，后台进程已停止。"
    elif "已有 Bot 同步任务正在运行" in error:
        status = "busy"
        title = "Bot 同步正在执行"
        message = "定时任务或其他同步正在运行，请等待当前任务完成后再试。"
    elif not ok:
        status = "failed"
        title = "Bot 同步失败"
        message = error or "脚本执行失败，请查看完整输出。"
    elif unchanged:
        status = "unchanged"
        title = "Bot 状态已刷新"
        message = "本地可信名单无需修改，最近群扫描状态已更新。"
    else:
        status = "updated"
        title = "Bot 同步完成"
        message = "已完成群扫描、备份和全部 profile 同步。"
    raw_output = "\n".join(
        value for value in (output.strip(), error) if value
    )[-16000:]
    return {
        "ok": ok,
        "status": status,
        "title": title,
        "message": message,
        "group_title": group_match.group(1) if group_match else "",
        "chat_id": int(group_match.group(2)) if group_match else None,
        "message_count": _parse_int(r"^近期消息扫描数: (\d+)$", output),
        "live_bot_count": _parse_int(r"^群上游戏 Bot: (\d+)$", output),
        "before_count": _parse_int(r"^\.env Bot 数: (\d+)$", output),
        "after_count": _parse_int(r"^同步后目标 Bot 数: (\d+)$", output),
        "profile_count": len(
            re.findall(r"^profile \d+ Bot 数: \d+$", output, re.MULTILINE)
        ),
        "new_bots": new_bots,
        "retained_old_ids": retained_match.group(1).strip()
        if retained_match
        else "",
        "backup_path": backup_match.group(1).strip() if backup_match else "",
        "elapsed_seconds": round(float(elapsed_seconds), 1),
        "returncode": int(returncode),
        "raw_output": raw_output,
    }


async def run_bot_sync_command(timeout_seconds: int = 180) -> dict:
    started_at = time.monotonic()
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = await asyncio.create_subprocess_exec(
        str(PYTHON_PATH),
        str(SCRIPT_PATH),
        *COMMAND_ARGS,
        cwd=str(PROJECT_ROOT),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        creationflags=creationflags,
    )
    timed_out = False
    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(), timeout=max(int(timeout_seconds), 1)
        )
    except asyncio.TimeoutError:
        timed_out = True
        process.kill()
        stdout_bytes, stderr_bytes = await process.communicate()
    elapsed_seconds = time.monotonic() - started_at
    return parse_bot_sync_output(
        stdout_bytes.decode("utf-8", errors="replace"),
        stderr_bytes.decode("utf-8", errors="replace"),
        process.returncode if process.returncode is not None else 1,
        elapsed_seconds,
        timed_out=timed_out,
    )


def build_busy_result() -> dict:
    return {
        "ok": False,
        "status": "busy",
        "title": "Bot 同步正在执行",
        "message": "已有同步任务正在扫描群消息，请等待当前任务完成后再试。",
        "elapsed_seconds": 0,
        "raw_output": "",
    }


def write_bot_sync_result(path: Path, result: dict) -> str:
    result_id = uuid.uuid4().hex
    payload = {**result, "result_id": result_id}
    temp_path = path.with_name(path.name + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()
    return result_id


def load_bot_sync_result(path: Path, result_id: str) -> dict | None:
    normalized_id = str(result_id or "").strip()
    if not normalized_id:
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if str(payload.get("result_id") or "") != normalized_id:
        return None
    provided_details = payload.get("details") or []
    details = [
        (str(item[0]), str(item[1]))
        for item in provided_details
        if isinstance(item, (list, tuple)) and len(item) == 2
    ]
    if details:
        return {**payload, "details": details}
    if payload.get("group_title") or payload.get("chat_id") is not None:
        group_text = str(payload.get("group_title") or "目标群")
        if payload.get("chat_id") is not None:
            group_text += f" ({payload['chat_id']})"
        details.append(("目标群", group_text))
    if payload.get("message_count"):
        details.append(("扫描消息", str(payload["message_count"])))
    if payload.get("live_bot_count"):
        details.append(("群上存活 Bot", str(payload["live_bot_count"])))
    if payload.get("after_count"):
        details.append(
            (
                "可信 Bot",
                f"{payload.get('before_count', 0)} → {payload['after_count']}",
            )
        )
    if payload.get("profile_count"):
        details.append(("同步 profile", str(payload["profile_count"])))
    new_bots = payload.get("new_bots") or []
    details.append(
        (
            "新增 Bot",
            ", ".join(
                f"@{item.get('username')} / {item.get('bot_id')}" for item in new_bots
            )
            or "无",
        )
    )
    if payload.get("retained_old_ids"):
        details.append(("历史保留 ID", str(payload["retained_old_ids"])))
    details.append(("数据库备份", str(payload.get("backup_path") or "未创建")))
    details.append(("执行耗时", f"{float(payload.get('elapsed_seconds') or 0):.1f} 秒"))
    return {**payload, "details": details}
