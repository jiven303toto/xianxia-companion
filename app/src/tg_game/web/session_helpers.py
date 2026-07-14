from __future__ import annotations

import re
import subprocess
from urllib.parse import quote_plus

from fastapi.responses import RedirectResponse


PUBLIC_PATHS = {
    "/login",
    "/logout",
    "/health",
    "/auth/external/connect",
    "/auth/external/logout",
    "/auth/external/refresh",
    "/auth/telegram/local-login",
    "/auth/telegram/start",
    "/auth/telegram/verify",
    "/auth/telegram/password",
    "/auth/telegram/logout",
}


def is_public_path(path: str) -> bool:
    if path.startswith("/static"):
        return True
    return path in PUBLIC_PATHS


def sign_in_profile(
    storage,
    request,
    profile_id: int,
    *,
    app_session_cookie: str,
    redirect_url: str = "/",
) -> RedirectResponse:
    current_token = request.cookies.get(app_session_cookie, "")
    session_token = storage.create_app_session(profile_id, session_token=current_token)
    response = RedirectResponse(url=redirect_url or "/", status_code=303)
    response.set_cookie(
        app_session_cookie,
        session_token,
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=86400 * 7,
    )
    return response


def login_session_name(settings) -> str:
    return settings.telegram_login_session_name or settings.telegram_session_name


def login_session_name_for_phone(base_name: str, phone: str = "") -> str:
    normalized_base_name = (base_name or "tg_game_login").strip()
    digits = re.sub(r"\D+", "", str(phone or "").strip())
    if not digits:
        return normalized_base_name
    return f"{normalized_base_name}_{digits}"


def is_telegram_runtime_active() -> bool:
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^python(\\.exe)?$' -or $_.Name -match '^pythonw(\\.exe)?$' } | Select-Object -ExpandProperty CommandLine",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except Exception:
        return False
    output = str(completed.stdout or "")
    return "run_telegram.py" in output


def build_tianji_login_redirect(message: str = "") -> RedirectResponse:
    normalized_message = (
        message or ""
    ).strip() or "天机阁会话已失效，请重新粘贴 session Cookie 后再继续。"
    return RedirectResponse(
        url="/login?error=" + quote_plus(normalized_message), status_code=303
    )


def get_authenticated_profile(storage, request, *, app_session_cookie: str):
    session_token = request.cookies.get(app_session_cookie, "")
    profile = storage.get_profile_by_session_token(session_token)
    if profile:
        return profile
    session_profiles = storage.list_profiles_by_session_token(session_token)
    if not session_profiles:
        return None
    fallback_profile = next(
        (
            candidate
            for candidate in session_profiles
            if getattr(candidate, "telegram_verified_at", 0)
        ),
        session_profiles[0],
    )
    restored_profile = storage.set_current_profile_by_session_token(
        session_token, fallback_profile.id
    )
    return restored_profile or fallback_profile


def list_session_profiles(storage, request, *, app_session_cookie: str) -> list:
    return storage.list_profiles_by_session_token(
        request.cookies.get(app_session_cookie, "")
    )


def profile_belongs_to_session(profiles: list, profile_id: int) -> bool:
    return any(profile.id == int(profile_id) for profile in profiles)
