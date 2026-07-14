from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ROOT_DIR / ".env.example"
ENV_FILE = ROOT_DIR / ".env"
REQUIREMENTS = ROOT_DIR / "requirements.txt"
DATA_DIR = ROOT_DIR / "data"
PLACEHOLDERS = {"", "your_api_id", "your_api_hash", "change_me", "changeme"}

REQUIRED_ENV_KEYS = (
    ("TELEGRAM_API_ID", "Telegram API id"),
    ("TELEGRAM_API_HASH", "Telegram API hash"),
    ("TG_GAME_BOUND_CHAT_ID", "target group/chat id"),
    ("TG_GAME_BOUND_BOT_ID", "game bot numeric id"),
)

OPTIONAL_ENV_KEYS = (
    ("TG_GAME_BOUND_THREAD_ID", "required only when the target group uses topics"),
    ("TG_GAME_ALLOWED_BOT_IDS", "comma-separated extra bot ids, optional"),
    ("AUTHORIZED_USER_ID", "admin user id, optional"),
)


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values


def _missing(value: str | None) -> bool:
    return value is None or value.strip() in PLACEHOLDERS


def _resolve_venv(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return ROOT_DIR / path


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform.startswith("win"):
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _run(command: list[str]) -> None:
    print("$ " + " ".join(command))
    subprocess.run(command, cwd=ROOT_DIR, check=True)


def _print_env_report(values: dict[str, str]) -> list[str]:
    missing_required = [
        key for key, _ in REQUIRED_ENV_KEYS if _missing(values.get(key))
    ]

    if missing_required:
        print("\nMissing required .env values:")
        for key, description in REQUIRED_ENV_KEYS:
            if key in missing_required:
                print(f"- {key}: {description}")
    else:
        print("\nRequired .env values are present.")

    print("\nOptional .env values to review:")
    for key, description in OPTIONAL_ENV_KEYS:
        current = values.get(key, "")
        status = "set" if not _missing(current) else "empty"
        print(f"- {key}: {description} ({status})")

    return missing_required


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare or inspect the local Xianxia Companion environment."
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="create a virtual environment and install requirements",
    )
    parser.add_argument(
        "--venv",
        default=".venv",
        help="virtual environment directory, default: .venv",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="only inspect the current checkout; do not create files or install packages",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="return a non-zero exit code when required .env values are missing",
    )
    args = parser.parse_args()

    if sys.version_info < (3, 10):
        print("Python 3.10 or newer is required.")
        return 1

    print(f"Project root: {ROOT_DIR}")

    if args.check:
        print("Check mode: no files will be created or changed.")
    else:
        DATA_DIR.mkdir(exist_ok=True)
        print(f"Ensured data directory: {DATA_DIR}")

        if ENV_FILE.exists():
            print(".env already exists; left unchanged.")
        else:
            shutil.copy2(ENV_EXAMPLE, ENV_FILE)
            print("Created .env from .env.example; edit it before starting Telegram.")

    venv_dir = _resolve_venv(args.venv)
    launch_python = Path(sys.executable)
    if args.install and not args.check:
        if not _venv_python(venv_dir).exists():
            _run([sys.executable, "-m", "venv", str(venv_dir)])
        else:
            print(f"Virtual environment already exists: {venv_dir}")
        launch_python = _venv_python(venv_dir)
        _run([str(launch_python), "-m", "pip", "install", "-r", str(REQUIREMENTS)])

    values = _parse_env(ENV_FILE)
    missing_required = _print_env_report(values)

    print("\nNext commands:")
    print("1. Edit .env and fill the missing values above.")
    print(f"2. Start both services: {launch_python} run_services.py all")
    print(f"3. Open Web UI: http://127.0.0.1:{values.get('TG_GAME_PORT', '8787')}")

    if missing_required and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
