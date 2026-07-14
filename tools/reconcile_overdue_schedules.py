from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_SRC = PROJECT_ROOT / "app" / "src"
RECONCILE_LOCK_PATH = PROJECT_ROOT / "data" / "overdue_schedule_reconcile.lock"
for import_path in (PROJECT_ROOT, APP_SRC):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from tg_game.config import get_settings
from tg_game.services.overdue_schedules import (
    format_reconcile_result,
    reconcile_overdue_schedules,
)
from tg_game.storage import Storage
from tools.sync_telegram_game_bots import bot_sync_process_lock


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="检查并补偿全部 profile 的过期未执行调度。"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="只读检查，不入队")
    mode.add_argument("--apply", action="store_true", help="调用原调度器重新入队")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    settings = get_settings()
    if settings.bound_chat_id is None:
        raise RuntimeError(".env 缺少 TG_GAME_BOUND_CHAT_ID")
    storage = Storage(settings.database_path)
    if args.apply:
        with bot_sync_process_lock(RECONCILE_LOCK_PATH):
            result = asyncio.run(
                reconcile_overdue_schedules(
                    storage,
                    target_chat_id=int(settings.bound_chat_id),
                    apply=True,
                )
            )
    else:
        result = asyncio.run(
            reconcile_overdue_schedules(
                storage,
                target_chat_id=int(settings.bound_chat_id),
                apply=False,
            )
        )
    print(format_reconcile_result(result))
    return 1 if int(result.get("failed_count") or 0) else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("已取消。", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"失败: {exc}", file=sys.stderr)
        raise SystemExit(1)
