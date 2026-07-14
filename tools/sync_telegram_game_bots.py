from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_SRC = PROJECT_ROOT / "app" / "src"
if str(APP_SRC) not in sys.path:
    sys.path.insert(0, str(APP_SRC))

from telethon import TelegramClient
from telethon.tl.types import ChannelParticipantsBots

from tg_game.config import get_settings


ENV_PATH = PROJECT_ROOT / ".env"
DATA_DIR = PROJECT_ROOT / "data"
DATABASE_PATH = DATA_DIR / "tg_game.db"
PROGRESS_PATH = PROJECT_ROOT / "progress.md"
BOT_SCAN_SNAPSHOT_PATH = DATA_DIR / "telegram_game_bot_scan.json"
BOT_SYNC_LOCK_PATH = DATA_DIR / "telegram_game_bot_sync.lock"
GAME_BOT_PATTERN = re.compile(r"^hantianzun(\d+)_bot$", re.IGNORECASE)


@dataclass(frozen=True)
class BotIdentity:
    bot_id: int
    username: str
    sources: tuple[str, ...] = ()


@dataclass
class LocalState:
    profiles: list[dict]
    bindings: list[dict]
    missing_profile_ids: list[int]
    inactive_profile_ids: list[int]
    duplicate_profile_ids: list[int]

    @property
    def blockers(self) -> list[str]:
        messages = []
        if not self.profiles:
            messages.append("数据库没有 profile")
        if self.missing_profile_ids:
            messages.append(
                "缺少当前群绑定的 profile: "
                + ",".join(str(value) for value in self.missing_profile_ids)
            )
        if self.inactive_profile_ids:
            messages.append(
                "当前群绑定不是活动状态的 profile: "
                + ",".join(str(value) for value in self.inactive_profile_ids)
            )
        if self.duplicate_profile_ids:
            messages.append(
                "当前群存在重复绑定的 profile: "
                + ",".join(str(value) for value in self.duplicate_profile_ids)
            )
        return messages


def parse_env(path: Path) -> dict[str, str]:
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


def parse_int_list(raw_value: str) -> list[int]:
    values: list[int] = []
    seen: set[int] = set()
    for raw_item in str(raw_value or "").replace(";", ",").split(","):
        item = raw_item.strip()
        if not item:
            continue
        value = int(item)
        if value not in seen:
            seen.add(value)
            values.append(value)
    return values


def replace_env_value(text: str, key: str, value: str) -> str:
    output = []
    replaced = False
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        ending = raw_line[len(line) :]
        if line.strip().startswith(f"{key}="):
            output.append(f"{key}={value}{ending}")
            replaced = True
        else:
            output.append(raw_line)
    if not replaced:
        raise RuntimeError(f".env 缺少 {key}")
    return "".join(output)


def is_game_bot_username(username: str) -> bool:
    normalized = str(username or "").strip().lower().lstrip("@")
    return normalized == "fanrenxiuxian_bot" or bool(
        GAME_BOT_PATTERN.fullmatch(normalized)
    )


def bot_sort_key(bot: BotIdentity) -> tuple[int, int, str]:
    normalized = bot.username.lower()
    if normalized == "fanrenxiuxian_bot":
        return (0, 0, normalized)
    match = GAME_BOT_PATTERN.fullmatch(normalized)
    return (1, int(match.group(1)) if match else bot.bot_id, normalized)


def merge_ids(*groups: list[int]) -> list[int]:
    merged: list[int] = []
    seen: set[int] = set()
    for group in groups:
        for raw_value in group:
            value = int(raw_value)
            if value not in seen:
                seen.add(value)
                merged.append(value)
    return merged


def session_file_path(session_name: str) -> Path:
    path = Path(str(session_name or "").strip())
    if not path.is_absolute() and path.parent == Path("."):
        path = DATA_DIR / path
    if path.suffix.lower() != ".session":
        path = Path(str(path) + ".session")
    return path


def copy_sqlite_database(source: Path, target: Path) -> None:
    source_connection = sqlite3.connect(source)
    target_connection = sqlite3.connect(target)
    try:
        source_connection.backup(target_connection)
    finally:
        target_connection.close()
        source_connection.close()


def load_local_state(
    database_path: Path, chat_id: int, thread_id: int | None
) -> LocalState:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    try:
        profiles = [
            dict(row)
            for row in connection.execute(
                "SELECT id, name, is_active, telegram_session_name "
                "FROM profiles ORDER BY is_active DESC, id"
            )
        ]
        rows = connection.execute(
            """
            SELECT id, profile_id, chat_id, thread_id, bot_id, bot_ids,
                   bot_usernames, is_active
            FROM chat_bindings
            WHERE chat_id=? AND COALESCE(thread_id, 0)=COALESCE(?, 0)
            ORDER BY profile_id, id
            """,
            (int(chat_id), thread_id),
        ).fetchall()
    finally:
        connection.close()

    bindings = []
    counts: dict[int, int] = {}
    for row in rows:
        item = dict(row)
        item["bot_ids"] = [int(value) for value in json.loads(item["bot_ids"] or "[]")]
        item["bot_usernames"] = {
            int(key): str(value)
            for key, value in json.loads(item["bot_usernames"] or "{}").items()
            if str(value or "").strip()
        }
        bindings.append(item)
        profile_id = int(item["profile_id"])
        counts[profile_id] = counts.get(profile_id, 0) + 1

    profile_ids = {int(profile["id"]) for profile in profiles}
    binding_profile_ids = {int(binding["profile_id"]) for binding in bindings}
    missing = sorted(profile_ids - binding_profile_ids)
    inactive = sorted(
        int(binding["profile_id"])
        for binding in bindings
        if not int(binding["is_active"] or 0)
    )
    duplicates = sorted(profile_id for profile_id, count in counts.items() if count > 1)
    return LocalState(profiles, bindings, missing, inactive, duplicates)


def build_target_state(
    env_ids: list[int], local_state: LocalState, observed_bots: list[BotIdentity]
) -> tuple[list[int], dict[int, str]]:
    binding_id_groups = [binding["bot_ids"] for binding in local_state.bindings]
    observed_sorted = sorted(observed_bots, key=bot_sort_key)
    target_ids = merge_ids(
        env_ids,
        *binding_id_groups,
        [bot.bot_id for bot in observed_sorted],
    )
    usernames: dict[int, str] = {}
    for binding in local_state.bindings:
        usernames.update(binding["bot_usernames"])
    for bot in observed_sorted:
        usernames[bot.bot_id] = bot.username
    return target_ids, usernames


async def resolve_group(client: TelegramClient, chat_id: int):
    try:
        return await client.get_entity(chat_id)
    except Exception:
        async for dialog in client.iter_dialogs():
            if int(dialog.id) == int(chat_id):
                return dialog.entity
    raise RuntimeError(f"当前 Telegram 账号无法访问群 {chat_id}")


async def scan_with_client(
    client: TelegramClient, chat_id: int, message_limit: int
) -> tuple[str, int, list[BotIdentity]]:
    entity = await resolve_group(client, chat_id)
    found: dict[int, dict] = {}
    async for user in client.iter_participants(entity, filter=ChannelParticipantsBots):
        found[int(user.id)] = {
            "username": str(getattr(user, "username", "") or ""),
            "sources": ["participants"],
        }

    message_count = 0
    seen_senders: set[int] = set()
    async for message in client.iter_messages(entity, limit=message_limit):
        message_count += 1
        sender_id = int(message.sender_id or 0)
        if not sender_id or sender_id in seen_senders:
            continue
        seen_senders.add(sender_id)
        sender = getattr(message, "sender", None)
        if sender is None:
            try:
                sender = await message.get_sender()
            except Exception:
                sender = None
        if sender is None or not bool(getattr(sender, "bot", False)):
            continue
        item = found.setdefault(
            sender_id,
            {
                "username": str(getattr(sender, "username", "") or ""),
                "sources": [],
            },
        )
        if "messages" not in item["sources"]:
            item["sources"].append("messages")

    bots = []
    for bot_id, item in found.items():
        username = str(item["username"] or "").strip().lstrip("@")
        if is_game_bot_username(username):
            bots.append(BotIdentity(bot_id, username, tuple(item["sources"])))
    bots.sort(key=bot_sort_key)
    return str(getattr(entity, "title", "") or chat_id), message_count, bots


async def scan_group(
    local_state: LocalState, chat_id: int, message_limit: int
) -> tuple[str, int, list[BotIdentity], int]:
    settings = get_settings()
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise RuntimeError(".env 缺少 TELEGRAM_API_ID 或 TELEGRAM_API_HASH")
    errors = []
    with tempfile.TemporaryDirectory(prefix="tg-bot-sync-") as temp_dir:
        for profile in local_state.profiles:
            session_name = str(profile.get("telegram_session_name") or "").strip()
            if not session_name:
                continue
            source = session_file_path(session_name)
            if not source.exists():
                errors.append(f"profile {profile['id']} session 文件不存在")
                continue
            temp_session = Path(temp_dir) / f"profile-{profile['id']}.session"
            try:
                copy_sqlite_database(source, temp_session)
                client = TelegramClient(
                    str(temp_session),
                    int(settings.telegram_api_id),
                    settings.telegram_api_hash,
                )
                client.session.save_entities = False
                await client.connect()
                try:
                    if not await client.is_user_authorized():
                        errors.append(f"profile {profile['id']} session 未授权")
                        continue
                    title, count, bots = await scan_with_client(
                        client, chat_id, message_limit
                    )
                    return title, count, bots, int(profile["id"])
                finally:
                    await client.disconnect()
            except Exception as exc:
                errors.append(f"profile {profile['id']}: {type(exc).__name__}: {exc}")
    raise RuntimeError("没有可用于扫描当前群的已授权 session：" + "；".join(errors))


def atomic_write(path: Path, text: str) -> None:
    temp_path = path.with_name(path.name + ".tmp")
    try:
        with temp_path.open("w", encoding="utf-8", newline="") as handle:
            handle.write(text)
        if path.exists():
            os.chmod(temp_path, path.stat().st_mode)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


@contextmanager
def bot_sync_process_lock(path: Path | None = None):
    lock_path = path or BOT_SYNC_LOCK_PATH
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise RuntimeError("已有 Bot 同步任务正在运行，请稍后重试") from exc
    try:
        yield
    finally:
        handle.seek(0)
        if os.name == "nt":
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def write_scan_snapshot(
    path: Path,
    *,
    chat_id: int,
    thread_id: int | None,
    title: str,
    message_count: int,
    scan_profile_id: int,
    observed_bots: list[BotIdentity],
) -> None:
    payload = {
        "chat_id": int(chat_id),
        "thread_id": int(thread_id) if thread_id is not None else None,
        "title": str(title or ""),
        "scanned_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "message_count": int(message_count),
        "scan_profile_id": int(scan_profile_id),
        "bot_ids": [int(bot.bot_id) for bot in observed_bots],
    }
    atomic_write(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )


def create_database_backup(database_path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = database_path.with_name(f"tg_game-before-bot-sync-{stamp}.db")
    copy_sqlite_database(database_path, backup)
    return backup


def update_bindings_in_connection(
    connection: sqlite3.Connection,
    binding_ids: list[int],
    target_ids: list[int],
    usernames: dict[int, str],
) -> None:
    bot_ids_json = json.dumps(target_ids, separators=(",", ":"))
    username_json = json.dumps(
        {
            str(bot_id): usernames[bot_id]
            for bot_id in target_ids
            if usernames.get(bot_id)
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    for binding_id in binding_ids:
        cursor = connection.execute(
            "UPDATE chat_bindings SET bot_ids=?, bot_usernames=?, updated_at=? "
            "WHERE id=?",
            (bot_ids_json, username_json, time.time(), int(binding_id)),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(f"更新绑定 {binding_id} 失败")


def apply_sync_transaction(
    database_path: Path,
    env_path: Path,
    binding_ids: list[int],
    target_ids: list[int],
    usernames: dict[int, str],
) -> None:
    original_env = env_path.read_text(encoding="utf-8")
    new_env = replace_env_value(
        original_env,
        "TG_GAME_ALLOWED_BOT_IDS",
        ",".join(str(value) for value in target_ids),
    )
    connection = sqlite3.connect(database_path, timeout=30)
    env_written = False
    try:
        connection.execute("BEGIN IMMEDIATE")
        update_bindings_in_connection(
            connection, binding_ids, target_ids, usernames
        )
        placeholders = ",".join("?" for _ in binding_ids)
        rows = connection.execute(
            f"SELECT id, bot_ids FROM chat_bindings WHERE id IN ({placeholders})",
            binding_ids,
        ).fetchall()
        if len(rows) != len(binding_ids):
            raise RuntimeError("更新后的群绑定数量不完整")
        for binding_id, raw_ids in rows:
            if [int(value) for value in json.loads(raw_ids or "[]")] != target_ids:
                raise RuntimeError(f"绑定 {binding_id} Bot ID 写入不完整")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise RuntimeError(
                f"SQLite 验证失败: integrity={integrity}, foreign_keys={len(foreign_keys)}"
            )
        atomic_write(env_path, new_env)
        env_written = True
        connection.commit()
    except Exception:
        connection.rollback()
        if env_written:
            atomic_write(env_path, original_env)
        raise
    finally:
        connection.close()


def verify_sync(
    database_path: Path,
    env_path: Path,
    chat_id: int,
    thread_id: int | None,
    expected_ids: list[int],
    expected_usernames: dict[int, str],
) -> None:
    values = parse_env(env_path)
    if parse_int_list(values.get("TG_GAME_ALLOWED_BOT_IDS", "")) != expected_ids:
        raise RuntimeError(".env Bot ID 与目标列表不一致")
    state = load_local_state(database_path, chat_id, thread_id)
    if state.blockers:
        raise RuntimeError("；".join(state.blockers))
    for binding in state.bindings:
        if binding["bot_ids"] != expected_ids:
            raise RuntimeError(f"profile {binding['profile_id']} Bot ID 未同步")
        for bot_id, username in expected_usernames.items():
            if binding["bot_usernames"].get(bot_id) != username:
                raise RuntimeError(
                    f"profile {binding['profile_id']} 缺少 {username}/{bot_id}"
                )
    connection = sqlite3.connect(database_path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        connection.close()
    if integrity != "ok":
        raise RuntimeError(f"SQLite integrity_check={integrity}")
    if foreign_keys:
        raise RuntimeError(f"SQLite 存在 {len(foreign_keys)} 条外键违规")


def append_progress(
    new_bots: list[BotIdentity],
    previous_ids: list[int],
    total_count: int,
    profile_count: int,
    message_count: int,
    backup: Path,
) -> None:
    bot_names = ", ".join(bot.username for bot in new_bots) or "none"
    bot_ids = ",".join(str(bot.bot_id) for bot in new_bots) or "none"
    previous_id_text = ",".join(str(bot_id) for bot_id in previous_ids)
    relative_backup = backup.relative_to(PROJECT_ROOT)
    entry = f"""

## {datetime.now().date().isoformat()} - Task: Synchronize Telegram game bot IDs

### What was done
- Scanned the environment-bound Telegram group without sending commands and compared the observed cultivation bots with `.env` and every current-group profile binding.
- Added newly observed bots `{bot_names}` and synchronized the same {total_count}-ID trusted set across all {profile_count} profiles without removing older rotated bot IDs or changing the primary bot.

### Testing
- Telegram member and recent-message scan completed with {message_count} messages inspected.
- Post-apply verification confirmed `.env` and all profile bindings contain the same {total_count} bot IDs and observed username mappings.
- `PRAGMA integrity_check` returned `ok`; `PRAGMA foreign_key_check` returned zero violations.
- No Telegram command was sent and no service restart was performed.

### Notes
- `.env` - synchronizes `TG_GAME_ALLOWED_BOT_IDS`; newly added IDs: `{bot_ids}`.
- `data/tg_game.db` - synchronizes current-group bot IDs and usernames for all profiles.
- `{relative_backup}` - exact SQLite rollback point created before this synchronization.
- `progress.md` - appends this task record.
- Rollback: no service restart is required; run `Remove-Item data\\tg_game.db-wal,data\\tg_game.db-shm -Force -ErrorAction SilentlyContinue`, then run `Copy-Item {relative_backup} data\\tg_game.db -Force`, set `.env` to `TG_GAME_ALLOWED_BOT_IDS={previous_id_text}`, and reverse only this task's `progress.md` entry.
"""
    with PROGRESS_PATH.open("a", encoding="utf-8", newline="") as handle:
        handle.write(entry)


def print_report(
    title: str,
    chat_id: int,
    message_count: int,
    scan_profile_id: int,
    observed_bots: list[BotIdentity],
    env_ids: list[int],
    local_state: LocalState,
    target_ids: list[int],
) -> None:
    local_ids = set(env_ids)
    for binding in local_state.bindings:
        local_ids.update(binding["bot_ids"])
    observed_ids = {bot.bot_id for bot in observed_bots}
    new_bots = [bot for bot in observed_bots if bot.bot_id not in local_ids]
    retained_old = sorted(local_ids - observed_ids)
    print(f"群: {title} ({chat_id})")
    print(f"扫描 session: profile {scan_profile_id}")
    print(f"近期消息扫描数: {message_count}")
    print(f"群上游戏 Bot: {len(observed_bots)}")
    for bot in observed_bots:
        marker = " [新增]" if bot in new_bots else ""
        print(f"- {bot.username}: {bot.bot_id}{marker}")
    print(f".env Bot 数: {len(env_ids)}")
    for binding in local_state.bindings:
        print(
            f"profile {binding['profile_id']} Bot 数: {len(binding['bot_ids'])}"
        )
    print(f"同步后目标 Bot 数: {len(target_ids)}")
    if retained_old:
        print("保留的旧轮换 Bot ID: " + ",".join(str(value) for value in retained_old))
    if local_state.blockers:
        print("阻塞项:")
        for blocker in local_state.blockers:
            print(f"- {blocker}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="检查并同步 Telegram 修仙游戏 Bot ID。默认只检查。"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="只检查，不修改")
    mode.add_argument("--apply", action="store_true", help="备份后同步 .env 和数据库")
    parser.add_argument(
        "--message-limit",
        type=int,
        default=2000,
        help="近期消息扫描数量，默认 2000",
    )
    args = parser.parse_args()
    if args.message_limit <= 0:
        parser.error("--message-limit 必须大于 0")

    env_values = parse_env(ENV_PATH)
    chat_id_raw = env_values.get("TG_GAME_BOUND_CHAT_ID", "").strip()
    if not chat_id_raw:
        raise RuntimeError(".env 缺少 TG_GAME_BOUND_CHAT_ID")
    chat_id = int(chat_id_raw)
    thread_raw = env_values.get("TG_GAME_BOUND_THREAD_ID", "").strip()
    thread_id = int(thread_raw) if thread_raw else None
    env_ids = parse_int_list(env_values.get("TG_GAME_ALLOWED_BOT_IDS", ""))
    local_state = load_local_state(DATABASE_PATH, chat_id, thread_id)

    title, message_count, observed_bots, scan_profile_id = asyncio.run(
        scan_group(local_state, chat_id, args.message_limit)
    )
    refreshed_env = parse_env(ENV_PATH)
    refreshed_chat_id = int(refreshed_env.get("TG_GAME_BOUND_CHAT_ID", "0") or 0)
    refreshed_thread_raw = refreshed_env.get("TG_GAME_BOUND_THREAD_ID", "").strip()
    refreshed_thread_id = int(refreshed_thread_raw) if refreshed_thread_raw else None
    if refreshed_chat_id != chat_id or refreshed_thread_id != thread_id:
        raise RuntimeError("扫描期间目标群配置发生变化，请重新执行")
    env_ids = parse_int_list(refreshed_env.get("TG_GAME_ALLOWED_BOT_IDS", ""))
    local_state = load_local_state(DATABASE_PATH, chat_id, thread_id)
    target_ids, target_usernames = build_target_state(
        env_ids, local_state, observed_bots
    )
    print_report(
        title,
        chat_id,
        message_count,
        scan_profile_id,
        observed_bots,
        env_ids,
        local_state,
        target_ids,
    )

    if not args.apply:
        print("检查完成：未修改任何文件或数据库。")
        return 0
    if local_state.blockers:
        raise RuntimeError("存在绑定阻塞项，拒绝执行 --apply")

    existing_ids = set(env_ids)
    for binding in local_state.bindings:
        existing_ids.update(binding["bot_ids"])
    new_bots = [bot for bot in observed_bots if bot.bot_id not in existing_ids]
    expected_username_map = {
        bot.bot_id: bot.username for bot in observed_bots
    }
    bindings_changed = any(
        set(binding["bot_ids"]) != set(target_ids)
        or any(
            binding["bot_usernames"].get(bot_id) != username
            for bot_id, username in expected_username_map.items()
        )
        for binding in local_state.bindings
    )
    env_changed = set(env_ids) != set(target_ids)
    if not bindings_changed and not env_changed:
        write_scan_snapshot(
            BOT_SCAN_SNAPSHOT_PATH,
            chat_id=chat_id,
            thread_id=thread_id,
            title=title,
            message_count=message_count,
            scan_profile_id=scan_profile_id,
            observed_bots=observed_bots,
        )
        print("本地已经与群上 Bot 清单同步；已更新最近扫描状态。")
        return 0

    backup = create_database_backup(DATABASE_PATH)
    apply_sync_transaction(
        DATABASE_PATH,
        ENV_PATH,
        [int(binding["id"]) for binding in local_state.bindings],
        target_ids,
        target_usernames,
    )
    verify_sync(
        DATABASE_PATH,
        ENV_PATH,
        chat_id,
        thread_id,
        target_ids,
        expected_username_map,
    )
    write_scan_snapshot(
        BOT_SCAN_SNAPSHOT_PATH,
        chat_id=chat_id,
        thread_id=thread_id,
        title=title,
        message_count=message_count,
        scan_profile_id=scan_profile_id,
        observed_bots=observed_bots,
    )

    append_progress(
        new_bots,
        env_ids,
        len(target_ids),
        len(local_state.profiles),
        message_count,
        backup,
    )
    print(f"同步完成：{len(local_state.profiles)} 个 profile，{len(target_ids)} 个 Bot。")
    print(f"数据库备份: {backup}")
    print("服务无需重启；后续消息会读取更新后的数据库绑定。")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        with bot_sync_process_lock():
            raise SystemExit(main())
    except KeyboardInterrupt:
        print("已取消。", file=sys.stderr)
        raise SystemExit(130)
    except Exception as exc:
        print(f"失败: {exc}", file=sys.stderr)
        raise SystemExit(1)
