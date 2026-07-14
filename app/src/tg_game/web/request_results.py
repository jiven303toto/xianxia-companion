from __future__ import annotations

from typing import Optional


def build_refresh_all_result(query_params, *, parse_int) -> Optional[dict]:
    if query_params.get("refresh_all") != "1":
        return None
    return {
        "ok": max(parse_int(query_params.get("ok"), 0), 0),
        "failed": max(parse_int(query_params.get("failed"), 0), 0),
        "skipped": max(parse_int(query_params.get("skipped"), 0), 0),
    }


def build_profile_bulk_result(query_params, *, parse_int) -> Optional[dict]:
    if query_params.get("bulk_cultivation") != "1":
        return None
    return {
        "mode": str(query_params.get("mode") or "").strip(),
        "updated": max(parse_int(query_params.get("updated"), 0), 0),
        "skipped": max(parse_int(query_params.get("skipped"), 0), 0),
        "protected": max(parse_int(query_params.get("protected"), 0), 0),
    }


def build_stop_current_result(query_params, *, parse_int) -> Optional[dict]:
    if query_params.get("stop_current_schedules") != "1":
        return None
    return {
        "profiles": max(parse_int(query_params.get("profiles"), 0), 0),
        "outgoing_cancelled": max(
            parse_int(query_params.get("outgoing_cancelled"), 0),
            0,
        ),
    }


def build_external_session_notice(external_account: Optional[dict]) -> Optional[dict]:
    if not external_account:
        return None
    status = (external_account.get("status") or "").strip().lower()
    last_error = (external_account.get("last_error") or "").strip()
    if status == "logged_out":
        return None
    if status == "expired":
        return {
            "level": "error",
            "title": "天机阁会话已失效",
            "message": "天机阁 session 已失效，请重新获取 Cookie 后在天机阁页重新验证。",
            "detail": last_error,
        }
    if status == "error" and last_error:
        return {
            "level": "error",
            "title": "天机阁同步失败",
            "message": "最近一次天机阁接口校验失败，请检查 Cookie 或稍后重试。",
            "detail": last_error,
        }
    return None
