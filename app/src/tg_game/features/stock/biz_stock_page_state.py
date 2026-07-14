from typing import Optional
import biz_fanren_game

from tg_game.features.stock.biz_stock_view_model import parse_stock_market_batch

def latest_stock_player_reply_view(
    storage,
    profile_id: int,
    command_text: str,
    *,
    format_timestamp=None,
) -> dict:
    formatter = format_timestamp or biz_fanren_game.format_timestamp
    reply = storage.get_stock_player_reply(profile_id, command_text) or {}
    created_at = float(
        (reply or {}).get("updated_at") or (reply or {}).get("created_at") or 0
    )
    return {
        "text": str((reply or {}).get("reply_text") or "").strip(),
        "created_at": created_at,
        "created_at_display": formatter(created_at) if created_at else "-",
    }


def build_stock_view(
    storage,
    profile_id: int,
    chat_id: Optional[int],
    thread_id: Optional[int] = None,
    command_sender_id: Optional[int] = None,
    command_sender_username: str = "",
    *,
    authorized_user_id: str = "",
    format_timestamp=None,
) -> dict:
    formatter = format_timestamp or biz_fanren_game.format_timestamp
    source_profile_id = profile_id
    authorized_user_id = str(authorized_user_id or "").strip()
    if authorized_user_id:
        admin_profile = storage.get_profile_by_telegram_user_id(authorized_user_id)
        if admin_profile:
            source_profile_id = admin_profile.id
    rows = storage.list_stock_market_info(source_profile_id)
    if not rows:
        fallback_rows = storage.list_stock_source_messages(limit=200)
        if fallback_rows:
            rows = []
            for msg in fallback_rows:
                raw_text = str(msg.get("text") or "")
                observed_at = float(msg.get("created_at") or 0)
                msg_id = int(msg.get("message_id") or 0)
                chat_id = int(msg.get("chat_id") or 0)
                profile_id = int(msg.get("profile_id") or 0)
                batch_stocks = parse_stock_market_batch(raw_text, observed_at)
                if batch_stocks:
                    for stock in batch_stocks:
                        try:
                            storage.upsert_stock_market_history(
                                profile_id or None,
                                chat_id,
                                msg_id,
                                stock["stock_code"],
                                observed_at=stock["observed_at"],
                                **{
                                    k: v
                                    for k, v in stock.items()
                                    if k not in ("stock_code", "observed_at")
                                },
                            )
                        except Exception:
                            pass
                        rows.append(
                            {
                                "stock_code": stock["stock_code"],
                                "stock_name": stock["stock_name"],
                                "current_price": stock["current_price"],
                                "previous_price": stock["current_price"],
                                "change_percent": stock["change_percent"],
                                "sector": stock["sector"],
                                "trend": stock["trend"],
                                "heat": stock["heat"],
                                "liquidity": stock["liquidity"],
                                "volume": stock["volume"],
                                "updated_at": observed_at,
                            }
                        )
                else:
                    price = float(msg.get("current_price") or 0)
                    prev = float(msg.get("previous_price") or price)
                    rows.append(
                        {
                            "stock_code": str(msg.get("stock_code") or ""),
                            "stock_name": str(msg.get("stock_name") or ""),
                            "current_price": price,
                            "previous_price": prev,
                            "change_percent": round((price - prev) / prev * 100, 2)
                            if prev > 0
                            else 0,
                            "updated_at": float(
                                msg.get("observed_at") or msg.get("created_at") or 0
                            ),
                        }
                    )
    for row in rows:
        latest_updated_at = float(row.get("updated_at") or 0)
        row["data_time"] = latest_updated_at
        row["data_time_display"] = formatter(latest_updated_at)
    gainers = sorted(
        rows, key=lambda row: float(row.get("change_percent") or 0), reverse=True
    )
    losers = sorted(rows, key=lambda row: float(row.get("change_percent") or 0))
    latest_updated_at = max(
        (float(row.get("data_time") or 0) for row in rows), default=0
    )
    latest_account = latest_stock_player_reply_view(
        storage,
        profile_id,
        ".我的持仓",
        format_timestamp=formatter,
    )
    latest_task = latest_stock_player_reply_view(
        storage,
        profile_id,
        ".股市任务",
        format_timestamp=formatter,
    )
    return {
        "rows": rows,
        "count": len(rows),
        "top_gainer": gainers[0] if gainers else None,
        "top_loser": losers[0] if losers else None,
        "latest_updated_at": latest_updated_at,
        "latest_updated_display": formatter(latest_updated_at),
        "latest_account_text": latest_account["text"],
        "latest_account_time_display": latest_account["created_at_display"],
        "latest_task_text": latest_task["text"],
        "latest_task_time_display": latest_task["created_at_display"],
        "tracked_stocks": [
            {
                "stock_code": str(row.get("stock_code") or ""),
                "stock_name": str(row.get("stock_name") or "").strip(),
            }
            for row in rows
            if row.get("stock_code")
        ],
        "tracked_codes": [
            str(row.get("stock_code") or "") for row in rows if row.get("stock_code")
        ],
    }
