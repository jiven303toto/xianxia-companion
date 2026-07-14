import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import BaseModel
from dotenv import load_dotenv


SOURCE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = SOURCE_DIR.parent
PROJECT_ROOT = APP_DIR.parent
load_dotenv(PROJECT_ROOT / ".env")


def _optional_int_env(name: str) -> Optional[int]:
    value = os.getenv(name, "").strip()
    return int(value) if value else None


def _int_set_env(name: str) -> set[int]:
    values = set()
    for value in os.getenv(name, "").replace(";", ",").split(","):
        value = value.strip()
        if value:
            values.add(int(value))
    return values


BOUND_CHAT_ID = _optional_int_env("TG_GAME_BOUND_CHAT_ID")
BOUND_THREAD_ID = _optional_int_env("TG_GAME_BOUND_THREAD_ID")
BOUND_BOT_ID = _optional_int_env("TG_GAME_BOUND_BOT_ID")
DEFAULT_ALLOWED_GAME_BOT_IDS = {8623198690, 8713762761, 8790646155, 8949197142}
ALLOWED_GAME_BOT_IDS = _int_set_env("TG_GAME_ALLOWED_BOT_IDS")
ALLOWED_GAME_BOT_IDS.update(DEFAULT_ALLOWED_GAME_BOT_IDS)
if BOUND_BOT_ID is not None:
    ALLOWED_GAME_BOT_IDS.add(BOUND_BOT_ID)


class Settings(BaseModel):
    app_name: str = "自动修仙"
    app_version: str = "0.1.0"
    debug: bool = os.getenv("TG_GAME_DEBUG", "0") in {
        "1",
        "true",
        "True",
        "yes",
        "on",
    }
    host: str = os.getenv("TG_GAME_HOST", "127.0.0.1")
    port: int = int(os.getenv("TG_GAME_PORT", "8000"))
    domain: str = os.getenv("TG_GAME_DOMAIN", "").strip()
    ssl_certfile: Optional[Path] = (
        Path(os.getenv("TG_GAME_SSL_CERTFILE", "").strip())
        if os.getenv("TG_GAME_SSL_CERTFILE", "").strip()
        else None
    )
    ssl_keyfile: Optional[Path] = (
        Path(os.getenv("TG_GAME_SSL_KEYFILE", "").strip())
        if os.getenv("TG_GAME_SSL_KEYFILE", "").strip()
        else None
    )
    database_path: Path = PROJECT_ROOT / "data" / "tg_game.db"
    telegram_api_id: str = os.getenv("TELEGRAM_API_ID", "")
    telegram_api_hash: str = os.getenv("TELEGRAM_API_HASH", "")
    telegram_session_name: str = os.getenv("TG_GAME_SESSION_NAME", "tg_game")
    telegram_login_session_name: str = os.getenv(
        "TG_GAME_LOGIN_SESSION_NAME", "tg_game_login"
    )
    bound_chat_id: Optional[int] = BOUND_CHAT_ID
    bound_thread_id: Optional[int] = BOUND_THREAD_ID
    bound_chat_type: str = os.getenv("TG_GAME_BOUND_CHAT_TYPE", "group")
    bound_bot_id: Optional[int] = BOUND_BOT_ID
    external_keepalive_seconds: int = int(
        os.getenv("TG_GAME_EXTERNAL_KEEPALIVE_SECONDS", "900")
    )
    external_keepalive_poll_seconds: int = int(
        os.getenv("TG_GAME_EXTERNAL_KEEPALIVE_POLL_SECONDS", "600")
    )
    telegram_log_messages: bool = os.getenv("TG_GAME_LOG_MESSAGES", "0") in {
        "1",
        "true",
        "True",
        "yes",
        "on",
    }
    authorized_user_id: str = os.getenv("AUTHORIZED_USER_ID", "").strip()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
