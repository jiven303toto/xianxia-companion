import hashlib
import json
import os
from pathlib import Path
import time


BASE_DIR = Path(__file__).resolve().parent.parent
GAME_BEHAVIOR_FILES = [
    "biz_artifact_game.py",
    "biz_basic_game.py",
    "biz_battle_game.py",
    "biz_breakthrough_game.py",
    "biz_companion_game.py",
    "biz_diplomacy_game.py",
    "biz_dungeon_game.py",
    "biz_estate_game.py",
    "biz_fanren_game.py",
    "biz_fishing_game.py",
    "biz_inventory_game.py",
    "biz_market_game.py",
    "biz_sect_game.py",
    "biz_shop_game.py",
    "biz_small_world_game.py",
    "biz_stock_game.py",
]

RUNTIME_CORE_FILES = [
    "tg_game/pagoda_auto.py",
    "tg_game/runtime_status.py",
    "tg_game/storage.py",
    "tg_game/features/artifact/biz_artifact_touch_auto.py",
    "tg_game/web/biz_artifact_view_model.py",
    "tg_game/features/companion/biz_companion_cooldown.py",
    "tg_game/features/companion/biz_companion_voyage.py",
    "tg_game/web/biz_companion_view_model.py",
    "tg_game/web/biz_cultivation_view_model.py",
    "tg_game/web/biz_dungeon_view_model.py",
    "tg_game/web/module_availability.py",
    "tg_game/features/countdowns/biz_countdowns_view_model.py",
    "tg_game/features/cultivation/biz_cultivation_countdown.py",
    "tg_game/features/estate/biz_estate_miniapp.py",
    "tg_game/web/biz_estate_view_model.py",
    "tg_game/features/fishing/biz_fishing_auto.py",
    "tg_game/features/fishing/biz_fishing_miniapp_entry.py",
    "tg_game/features/fishing/biz_fishing_miniapp.py",
    "tg_game/features/fishing/biz_fishing_replies.py",
    "tg_game/features/fishing/biz_fishing_view_model.py",
    "tg_game/features/sect/biz_sect_view_model.py",
    "tg_game/features/small_world/biz_small_world_auto.py",
    "tg_game/features/small_world/biz_small_world_view_model.py",
    "tg_game/features/stock/biz_stock_page_state.py",
    "tg_game/features/stock/biz_stock_view_model.py",
    "tg_game/features/tianji_trial/biz_tianji_trial_encounter_state.py",
    "tg_game/features/tianji_trial/biz_tianji_trial_miniapp.py",
    "tg_game/features/tianji_trial/biz_tianji_trial_remnant_state.py",
    "tg_game/features/tianji_trial/biz_tianji_trial_remnant_view.py",
    "tg_game/features/tianji_trial/biz_tianji_trial_view_state.py",
    "tg_game/features/tianxing/biz_tianxing_parser.py",
    "tg_game/features/tianxing/biz_tianxing_reward_summary.py",
    "tg_game/features/tianxing/biz_tianxing_rewards.py",
    "tg_game/features/tianxing/biz_tianxing_runtime.py",
    "tg_game/features/xinggong/biz_xinggong_miniapp.py",
    "tg_game/features/xinggong/biz_xinggong_star_board.py",
    "tg_game/features/wanling/biz_wanling_roam.py",
    "tg_game/features/wanling/biz_wanling_view_model.py",
    "tg_game/web/app_helpers.py",
    "tg_game/web/biz_inventory_view_model.py",
    "tg_game/web/biz_mulan_view_model.py",
    "tg_game/web/biz_other_play_view_model.py",
    "tg_game/web/module_detail_state.py",
    "tg_game/web/pagination.py",
    "tg_game/web/profile_card_state.py",
    "tg_game/web/request_results.py",
    "tg_game/web/session_helpers.py",
    "tg_game/web/shared_context.py",
    "tg_game/web/biz_tianxing_wild_deep_log.py",
    "tg_game/web/biz_xinggong_view_model.py",
    "tg_game/runtime/context.py",
    "tg_game/runtime/executors.py",
    "tg_game/runtime/queue_service.py",
    "tg_game/runtime/router.py",
    "tg_game/telegram/network_guard.py",
    "tg_game/telegram/resume_guard.py",
    "tg_game/telegram/runtime.py",
    "tg_game/telegram/send_utils.py",
]

RUNTIME_FINGERPRINT_FILES = GAME_BEHAVIOR_FILES + RUNTIME_CORE_FILES


def compute_runtime_code_fingerprint() -> str:
    digest = hashlib.sha256()
    for relative_path in RUNTIME_FINGERPRINT_FILES:
        path = BASE_DIR / relative_path
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()[:16]


def build_runtime_status(component: str, *, started_at: float) -> dict:
    return {
        "component": component,
        "pid": os.getpid(),
        "started_at": float(started_at),
        "updated_at": time.time(),
        "code_fingerprint": compute_runtime_code_fingerprint(),
    }


def dump_runtime_status(status: dict) -> str:
    return json.dumps(status, ensure_ascii=False, sort_keys=True)


def load_runtime_status(value: str) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
