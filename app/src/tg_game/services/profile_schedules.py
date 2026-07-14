import time
from typing import Optional
import biz_fanren_game
import biz_sect_game

from tg_game.storage import CompatDb, Storage

STOP_CURRENT_SCHEDULES_REASON = "已通过角色真身页停止当前 profile 的调度任务。"


def _update_existing_table(
    storage: Storage,
    table_name: str,
    fields: dict,
    where_clause: str = "",
    params: tuple = (),
) -> int:
    if not fields:
        return 0
    with storage.connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        if not exists:
            return 0
        assignments = ", ".join(f"{field}=?" for field in fields)
        sql = f"UPDATE {table_name} SET {assignments}"
        if where_clause:
            sql += f" {where_clause}"
        cursor = conn.execute(sql, list(fields.values()) + list(params))
        return int(cursor.rowcount or 0)


def _fail_active_outgoing_commands(
    storage: Storage, reason: str, profile_id: Optional[int] = None
) -> int:
    now_ts = time.time()
    where_clause = "WHERE status IN ('pending', 'sending', 'awaiting_confirm', 'needs_manual_confirm')"
    params = [reason, now_ts]
    if profile_id is not None:
        where_clause += " AND profile_id=?"
        params.append(int(profile_id))
    with storage.connect() as conn:
        cursor = conn.execute(
            f"""
            UPDATE outgoing_commands
            SET status='failed', error_text=?, updated_at=?
            {where_clause}
            """,
            params,
        )
        return int(cursor.rowcount or 0)


def stop_current_profile_schedules(storage: Storage, profile_id: int) -> dict:
    reason = STOP_CURRENT_SCHEDULES_REASON
    target_profile_id = int(profile_id)
    if not storage.get_profile(target_profile_id):
        return {
            "profiles": 0,
            "fanren": 0,
            "sect": 0,
            "fishing": 0,
            "companion": 0,
            "heart": 0,
            "outgoing_cancelled": 0,
        }
    db = CompatDb(storage)
    try:
        biz_fanren_game.ensure_tables(db)
        biz_sect_game.ensure_tables(db)
    finally:
        db.close()
    fanren_rows = _update_existing_table(
        storage,
        "fanren_sessions",
        {
            "enabled": 0,
            "next_check_time": 0,
            "next_check_source": reason,
            "failure_count": 0,
            "stopped_reason": reason,
            "auto_jiyin_enabled": 0,
            "auto_nanlong_enabled": 0,
            "auto_rift_enabled": 0,
            "rift_next_check_time": 0,
            "rift_retry_count": 0,
            "auto_yuanying_enabled": 0,
            "yuanying_next_check_time": 0,
        },
        "WHERE profile_id=?",
        (target_profile_id,),
    )
    sect_rows = _update_existing_table(
        storage,
        "sect_sessions",
        {
            "enabled": 0,
            "next_check_time": 0,
            "next_check_source": reason,
            "auto_lingxiao_enabled": 0,
            "auto_lingxiao_gangfeng_enabled": 0,
            "auto_lingxiao_borrow_enabled": 0,
            "auto_lingxiao_question_enabled": 0,
            "auto_sect_checkin_enabled": 0,
            "auto_sect_teach_enabled": 0,
            "auto_yinluo_sacrifice_enabled": 0,
            "auto_yinluo_blood_wash_enabled": 0,
            "auto_huangfeng_enabled": 0,
            "auto_huangfeng_exchange_enabled": 0,
            "auto_luoyun_enabled": 0,
            "auto_yuanying_wendao_enabled": 0,
            "auto_yuanying_retreat_enabled": 0,
            "auto_companion_greet_enabled": 0,
            "auto_companion_assist_enabled": 0,
            "last_summary": reason,
        },
        "WHERE profile_id=?",
        (target_profile_id,),
    )
    fishing_rows = _update_existing_table(
        storage,
        "fishing_sessions",
        {
            "enabled": 0,
            "next_action_at": 0,
            "last_error": reason,
            "updated_at": time.time(),
        },
        "WHERE profile_id=?",
        (target_profile_id,),
    )
    companion_rows = _update_existing_table(
        storage,
        "companion_auto_tasks",
        {
            "enabled": 0,
            "next_run_at": 0,
            "workflow_state": "",
            "last_error": reason,
            "updated_at": time.time(),
        },
        "WHERE profile_id=?",
        (target_profile_id,),
    )
    heart_rows = _update_existing_table(
        storage,
        "companion_heart_tribulation_tasks",
        {
            "enabled": 0,
            "next_run_at": 0,
            "workflow_state": "",
            "run_id": "",
            "last_error": reason,
            "updated_at": time.time(),
        },
        "WHERE profile_id=?",
        (target_profile_id,),
    )
    outgoing_cancelled = _fail_active_outgoing_commands(
        storage,
        reason,
        profile_id=target_profile_id,
    )
    return {
        "profiles": 1,
        "fanren": fanren_rows,
        "sect": sect_rows,
        "fishing": fishing_rows,
        "companion": companion_rows,
        "heart": heart_rows,
        "outgoing_cancelled": outgoing_cancelled,
    }
