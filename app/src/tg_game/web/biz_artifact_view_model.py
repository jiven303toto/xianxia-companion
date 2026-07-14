from datetime import datetime, timezone
from typing import Optional
import biz_fanren_game

from tg_game.features.artifact.biz_artifact_touch_auto import (
    ARTIFACT_TOUCH_FEATURE_KEY,
    normalize_artifact_touch_command,
    normalize_artifact_touch_interval,
    pack_artifact_touch_strategy,
    unpack_artifact_touch_strategy,
)
from tg_game.features.artifact.biz_artifact_trial import (
    ARTIFACT_TRIAL_ROUTES,
    build_artifact_trial_command,
    build_artifact_trial_resource_state,
    normalize_artifact_trial_artifact_name,
    normalize_artifact_trial_route,
    pack_artifact_trial_strategy,
    unpack_artifact_trial_strategy,
)
from tg_game.web.biz_web_display_formatting import format_remaining_delta

def build_artifact_touch_auto_view(
    raw_task: Optional[dict],
    *,
    now_ts: Optional[float] = None,
) -> dict:
    task = raw_task or {}
    command_text, interval_seconds = unpack_artifact_touch_strategy(
        task.get("strategy") or ""
    )
    next_run_at = float(task.get("next_run_at") or 0)
    active = bool(task) and bool(task.get("enabled"))
    now = biz_fanren_game.time.time() if now_ts is None else float(now_ts)
    return {
        "active": active,
        "enabled": active,
        "command_text": command_text,
        "interval_minutes": max(interval_seconds // 60, 5),
        "next_run_at": next_run_at,
        "next_run_target": next_run_at if active and next_run_at > now else 0,
        "next_run_display": (
            format_remaining_delta(datetime.fromtimestamp(next_run_at, tz=timezone.utc))
            if active and next_run_at > 0
            else "待命"
        ),
        "last_error": str(task.get("last_error") or "").strip(),
    }


def build_artifact_trial_auto_view(
    raw_task: Optional[dict],
    payload: Optional[dict] = None,
    game_items_dict: Optional[dict] = None,
    *,
    now_ts: Optional[float] = None,
) -> dict:
    task = raw_task or {}
    artifact_name, route = unpack_artifact_trial_strategy(task.get("strategy") or "")
    resources = build_artifact_trial_resource_state(
        payload or {},
        game_items_dict or {},
    )
    next_run_at = float(task.get("next_run_at") or 0)
    active = bool(task) and bool(task.get("enabled"))
    now = biz_fanren_game.time.time() if now_ts is None else float(now_ts)
    return {
        "active": active,
        "enabled": active,
        "artifact_name": artifact_name,
        "trial_route": route,
        "route_options": list(ARTIFACT_TRIAL_ROUTES),
        "command_text": build_artifact_trial_command(artifact_name, route),
        "resources": resources,
        "next_run_at": next_run_at,
        "next_run_target": next_run_at if active and next_run_at > now else 0,
        "next_run_display": (
            format_remaining_delta(datetime.fromtimestamp(next_run_at, tz=timezone.utc))
            if active and next_run_at > 0
            else "待命"
        ),
        "last_error": str(task.get("last_error") or "").strip(),
    }
