from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


def resolve_child_python(
    executable: str | Path, *, platform_name: str | None = None
) -> Path:
    path = Path(executable)
    platform = os.name if platform_name is None else str(platform_name)
    return path.with_name("python.exe") if platform == "nt" else path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_PATH = resolve_child_python(sys.executable)
SCRIPT_PATH = PROJECT_ROOT / "tools" / "sync_telegram_game_bots.py"
RECONCILE_SCRIPT_PATH = PROJECT_ROOT / "tools" / "reconcile_overdue_schedules.py"
LOG_PATH = PROJECT_ROOT / "data" / "telegram_game_bot_schedule.log"
COMMAND_ARGS = ("--apply", "--message-limit", "5000")
RECONCILE_COMMAND_ARGS = ("--apply",)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


def build_command() -> list[str]:
    return [str(PYTHON_PATH), str(SCRIPT_PATH), *COMMAND_ARGS]


def build_reconcile_command() -> list[str]:
    return [str(PYTHON_PATH), str(RECONCILE_SCRIPT_PATH), *RECONCILE_COMMAND_ARGS]


def _run_command(command: list[str]) -> subprocess.CompletedProcess:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
        check=False,
    )


def _section(title: str, value: str) -> str:
    text = str(value or "").strip()
    return f"=== {title} ===\n{text}" if text else f"=== {title} ==="


def append_run_log(
    *,
    started_at: datetime,
    elapsed_seconds: float,
    returncode: int,
    stdout: str,
    stderr: str,
) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    status = "success" if int(returncode) == 0 else "failed"
    output = "\n".join(
        value.strip() for value in (str(stdout or ""), str(stderr or "")) if value.strip()
    )
    entry = (
        f"\n[{started_at.isoformat(timespec='seconds')}] "
        f"status={status} exit={int(returncode)} elapsed={elapsed_seconds:.1f}s\n"
        f"{output}\n"
    )
    with LOG_PATH.open("a", encoding="utf-8", newline="") as handle:
        handle.write(entry)


def main() -> int:
    started_at = datetime.now().astimezone()
    started = time.monotonic()
    sync_result = _run_command(build_command())
    stdout_sections = [_section("Bot 同步", sync_result.stdout)]
    stderr_sections = []
    if sync_result.stderr:
        stderr_sections.append(_section("Bot 同步错误", sync_result.stderr))
    returncode = int(sync_result.returncode)
    if returncode == 0:
        reconcile_result = _run_command(build_reconcile_command())
        stdout_sections.append(_section("调度补偿", reconcile_result.stdout))
        if reconcile_result.stderr:
            stderr_sections.append(
                _section("调度补偿错误", reconcile_result.stderr)
            )
        returncode = int(reconcile_result.returncode)
    stdout = "\n".join(stdout_sections)
    stderr = "\n".join(stderr_sections)
    elapsed_seconds = time.monotonic() - started
    append_run_log(
        started_at=started_at,
        elapsed_seconds=elapsed_seconds,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )
    if stdout and sys.stdout is not None:
        print(stdout)
    if stderr and sys.stderr is not None:
        print(stderr, file=sys.stderr)
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
