import math
from typing import Optional


JUMP_TARGET_SCORE = 120
JUMP_PROOF_EVENT_LIMIT = 500
JUMP_CENTER_SCORE_CAP = 6
JUMP_ANIMATION_MS = 560

JUMP_TYPES = (
    "stone",
    "spring",
    "marrow",
    "rift",
    "branch",
)


def jump_hash(seed: object, index: int) -> float:
    text = f"{str(seed or 'luoyun')}:{int(index)}"
    value = 2166136261
    for char in text:
        value ^= ord(char)
        value = (value * 16777619) & 0xFFFFFFFF
    return value / 4294967295


def jump_type(seed: object, index: int) -> str:
    normalized_index = int(index)
    roll = jump_hash(seed, normalized_index * 7 + 3)
    if normalized_index > 0 and normalized_index % 7 == 0:
        return JUMP_TYPES[4]
    if roll > 0.82:
        return JUMP_TYPES[3]
    if roll > 0.62:
        return JUMP_TYPES[2]
    if roll > 0.42:
        return JUMP_TYPES[1]
    return JUMP_TYPES[0]


def make_jump_platform(
    seed: object,
    index: int,
    origin: Optional[dict] = None,
) -> dict:
    base = origin or {"x": 116.0, "y": 246.0}
    normalized_index = int(index)
    if normalized_index <= 0:
        return {
            "x": float(base.get("x") or 116.0),
            "y": float(base.get("y") or 246.0),
            "r": 34.0,
            "type": JUMP_TYPES[0],
            "index": 0,
        }
    dx = 112 + jump_hash(seed, normalized_index * 11 + 1) * 58
    dy = -72 + jump_hash(seed, normalized_index * 13 + 2) * 136
    radius = 29 + jump_hash(seed, normalized_index * 17 + 4) * 8
    return {
        "x": float(base.get("x") or 0) + dx,
        "y": float(base.get("y") or 0) + dy,
        "r": radius,
        "type": jump_type(seed, normalized_index),
        "index": normalized_index,
    }


def jump_distance_for_charge(charge: object) -> float:
    normalized_charge = max(0.0, min(1.0, float(charge or 0)))
    return 54 + normalized_charge * 245


def target_jump_charge(current: dict, target: dict) -> float:
    distance = math.hypot(
        float(target.get("x") or 0) - float(current.get("x") or 0),
        float(target.get("y") or 0) - float(current.get("y") or 0),
    )
    return max(0.0, min(1.0, (distance - 54) / 245))


def _score_landing(
    target: dict,
    current: dict,
    charge: float,
    center_combo: int,
) -> dict:
    distance = math.hypot(
        float(target.get("x") or 0) - float(current.get("x") or 0),
        float(target.get("y") or 0) - float(current.get("y") or 0),
    )
    error = abs(jump_distance_for_charge(charge) - distance)
    perfect = max(11.0, float(target.get("r") or 0) * 0.32)
    edge = max(28.0, float(target.get("r") or 0) * 0.86)
    hit = error <= edge
    center = error <= perfect
    next_center_combo = center_combo + 1 if center else 0
    points = (
        min(next_center_combo * 2, JUMP_CENTER_SCORE_CAP)
        if hit and center
        else 1 if hit else 0
    )
    return {
        "hit": hit,
        "center": center,
        "error": error,
        "points": points,
        "center_combo": next_center_combo,
    }


def replay_jump_proof(seed: object, proof: object) -> dict:
    payload = proof if isinstance(proof, dict) else {}
    charges = payload.get("charges") if isinstance(payload.get("charges"), list) else []
    events = payload.get("events") if isinstance(payload.get("events"), list) else []
    current = make_jump_platform(seed, 0)
    score = 0
    center_steps = 0
    exact_centers = 0
    center_combo = 0
    steps = 0
    game_over = False
    last_error = 0.0
    for index, charge_value in enumerate(charges[:JUMP_PROOF_EVENT_LIMIT], start=1):
        target = make_jump_platform(seed, index, current)
        result = _score_landing(target, current, float(charge_value or 0), center_combo)
        steps += 1
        last_error = float(result["error"])
        if not result["hit"]:
            game_over = True
            break
        score += int(result["points"])
        center_combo = int(result["center_combo"])
        if result["center"]:
            center_steps += 1
            if result["error"] <= 0.02:
                exact_centers += 1
        current = target
    timing_ok = True
    previous_up = -1
    for event in events[: len(charges)]:
        if not isinstance(event, dict):
            timing_ok = False
            break
        down = int(event.get("down") or 0)
        up = int(event.get("up") or 0)
        hold = int(event.get("hold") or 0)
        if down < 0 or up < down or hold != up - down or down < previous_up:
            timing_ok = False
            break
        previous_up = up
    return {
        "ok": timing_ok and len(charges) == len(events),
        "score": score,
        "steps": steps,
        "centerSteps": center_steps,
        "exactCenters": exact_centers,
        "bestCenterCombo": center_combo,
        "gameOver": game_over,
        "error": last_error,
        "maxEvents": JUMP_PROOF_EVENT_LIMIT,
    }


def build_jump_proof(
    seed: object,
    *,
    target_score: int = JUMP_TARGET_SCORE,
    start_delay_ms: int = 600,
    settle_delay_ms: int = 620,
) -> dict:
    requested_score = max(1, int(target_score or JUMP_TARGET_SCORE))
    current = make_jump_platform(seed, 0)
    charges: list[float] = []
    events: list[dict] = []
    score = 0
    center_combo = 0
    down_at = max(0, int(start_delay_ms))
    index = 1
    while score < requested_score:
        if index > JUMP_PROOF_EVENT_LIMIT:
            raise ValueError("jump proof exceeds event limit")
        target = make_jump_platform(seed, index, current)
        ideal_charge = target_jump_charge(current, target)
        hold_ms = max(1, round(ideal_charge * 1200))
        charge = round(hold_ms / 1200, 4)
        result = _score_landing(target, current, charge, center_combo)
        if not result["center"]:
            raise ValueError("generated jump landing is not centered")
        up_at = down_at + hold_ms
        charges.append(charge)
        events.append(
            {
                "c": charge,
                "down": down_at,
                "up": up_at,
                "hold": hold_ms,
                "error": round(float(result["error"]), 2),
                "center": True,
            }
        )
        score += int(result["points"])
        center_combo = int(result["center_combo"])
        current = target
        down_at = up_at + max(JUMP_ANIMATION_MS, int(settle_delay_ms))
        index += 1
    proof = {
        "charges": charges,
        "events": events,
        "durationMs": events[-1]["up"] + max(JUMP_ANIMATION_MS, int(settle_delay_ms)),
        "clientScore": score,
    }
    verified = replay_jump_proof(seed, proof)
    if not verified["ok"] or int(verified["score"]) < requested_score:
        raise ValueError("generated jump proof failed local verification")
    return proof
