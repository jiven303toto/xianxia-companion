import math
from dataclasses import dataclass

from .biz_luoyun_jump_solver import jump_hash


FLY_TARGET_SCORE = 30
FLY_WORLD_TOP = 12.0
FLY_WORLD_BOTTOM = 348.0
FLY_GRAVITY = 560.0
FLY_FLAP_VELOCITY = -255.0
FLY_GATE_GAP = 112.0
FLY_GATE_WIDTH = 54.0
FLY_GATE_SPACING = 174.0
FLY_VERIFY_STEP_MS = 16

FLY_FOX_HIT_POLYGON = (
    (-24.0, 2.0),
    (-18.0, -8.0),
    (-7.0, -12.0),
    (8.0, -12.0),
    (20.0, -8.0),
    (25.0, -2.0),
    (22.0, 7.0),
    (10.0, 11.0),
    (-6.0, 10.0),
    (-19.0, 7.0),
)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def make_fly_gate(seed: object, index: int, x: float) -> dict:
    normalized_index = int(index)
    center = 102 + jump_hash(seed, normalized_index * 19 + 5) * 152
    return {
        "x": float(x),
        "gapY": center,
        "gap": FLY_GATE_GAP,
        "width": FLY_GATE_WIDTH,
        "passed": False,
        "index": normalized_index,
    }


def _fly_polygon(y: float, velocity_y: float) -> list[tuple[float, float]]:
    angle = _clamp(float(velocity_y) / 520, -0.38, 0.48)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return [
        (
            86.0 + point_x * cosine - point_y * sine,
            float(y) + point_x * sine + point_y * cosine,
        )
        for point_x, point_y in FLY_FOX_HIT_POLYGON
    ]


def _point_in_rect(point: tuple[float, float], rect: tuple[float, float, float, float]) -> bool:
    x, y = point
    left, right, top, bottom = rect
    return left <= x <= right and top <= y <= bottom


def _point_in_polygon(point: tuple[float, float], polygon: list[tuple[float, float]]) -> bool:
    x, y = point
    inside = False
    previous = len(polygon) - 1
    for index, current_point in enumerate(polygon):
        current_x, current_y = current_point
        previous_x, previous_y = polygon[previous]
        crosses = (current_y > y) != (previous_y > y)
        if crosses:
            x_at_y = (
                (previous_x - current_x)
                * (y - current_y)
                / ((previous_y - current_y) or 1e-9)
                + current_x
            )
            if x <= x_at_y:
                inside = not inside
        previous = index
    return inside


def _segment_intersects(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    def cross(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    def between(p, q, r):
        return (
            min(p[0], q[0]) <= r[0] <= max(p[0], q[0])
            and min(p[1], q[1]) <= r[1] <= max(p[1], q[1])
        )

    ab_c = cross(a, b, c)
    ab_d = cross(a, b, d)
    cd_a = cross(c, d, a)
    cd_b = cross(c, d, b)
    if ab_c == 0 and between(a, b, c):
        return True
    if ab_d == 0 and between(a, b, d):
        return True
    if cd_a == 0 and between(c, d, a):
        return True
    if cd_b == 0 and between(c, d, b):
        return True
    return (ab_c > 0) != (ab_d > 0) and (cd_a > 0) != (cd_b > 0)


def _polygon_intersects_rect(
    polygon: list[tuple[float, float]],
    rect: tuple[float, float, float, float],
) -> bool:
    if any(_point_in_rect(point, rect) for point in polygon):
        return True
    left, right, top, bottom = rect
    corners = [(left, top), (right, top), (right, bottom), (left, bottom)]
    if any(_point_in_polygon(point, polygon) for point in corners):
        return True
    for index, point in enumerate(polygon):
        next_point = polygon[(index + 1) % len(polygon)]
        for corner_index, corner in enumerate(corners):
            if _segment_intersects(
                point,
                next_point,
                corner,
                corners[(corner_index + 1) % len(corners)],
            ):
                return True
    return False


def _fly_hit(y: float, velocity_y: float, gates: list[dict]) -> bool:
    polygon = _fly_polygon(y, velocity_y)
    if any(point_y <= FLY_WORLD_TOP or point_y >= FLY_WORLD_BOTTOM for _, point_y in polygon):
        return True
    for gate in gates:
        gap_top = float(gate["gapY"]) - FLY_GATE_GAP / 2
        gap_bottom = float(gate["gapY"]) + FLY_GATE_GAP / 2
        left = float(gate["x"])
        right = left + FLY_GATE_WIDTH
        if _polygon_intersects_rect(polygon, (left, right, -40.0, gap_top)):
            return True
        if _polygon_intersects_rect(polygon, (left, right, gap_bottom, 400.0)):
            return True
    return False


def replay_fly_proof(
    seed: object,
    proof: object,
    *,
    step_ms: int = FLY_VERIFY_STEP_MS,
) -> dict:
    payload = proof if isinstance(proof, dict) else {}
    flaps = sorted(max(0, int(value)) for value in (payload.get("flaps") or []))
    duration_ms = max(0, int(payload.get("durationMs") or 0))
    normalized_step_ms = max(1, int(step_ms))
    gates = [
        make_fly_gate(seed, 1, 314),
        make_fly_gate(seed, 2, 488),
        make_fly_gate(seed, 3, 662),
    ]
    y = 178.0
    velocity_y = 0.0
    score = 0
    flap_index = 0
    elapsed_ms = 0
    collision = False
    collision_ms = 0
    while elapsed_ms < duration_ms and not collision:
        while flap_index < len(flaps) and flaps[flap_index] <= elapsed_ms:
            velocity_y = FLY_FLAP_VELOCITY
            flap_index += 1
        next_elapsed_ms = min(duration_ms, elapsed_ms + normalized_step_ms)
        delta_seconds = (next_elapsed_ms - elapsed_ms) / 1000
        velocity_y += FLY_GRAVITY * delta_seconds
        y += velocity_y * delta_seconds
        speed = 112 + min(70, score * 3)
        for gate in gates:
            gate["x"] = float(gate["x"]) - speed * delta_seconds
            if not gate["passed"] and float(gate["x"]) + FLY_GATE_WIDTH < 76:
                gate["passed"] = True
                score += 1
        last_gate = gates[-1]
        while gates and float(gates[0]["x"]) < -80:
            gates.pop(0)
        while len(gates) < 3:
            tail = gates[-1] if gates else last_gate
            gates.append(
                make_fly_gate(
                    seed,
                    int(tail.get("index") or 0) + 1,
                    float(tail.get("x") or 300) + FLY_GATE_SPACING,
                )
            )
        collision = _fly_hit(y, velocity_y, gates)
        elapsed_ms = next_elapsed_ms
        if collision:
            collision_ms = elapsed_ms
    return {
        "ok": duration_ms > 0,
        "score": score,
        "hit": collision,
        "collisionMs": collision_ms,
        "durationMs": duration_ms,
        "flapsUsed": flap_index,
        "y": y,
        "velocityY": velocity_y,
    }


@dataclass(frozen=True)
class _SearchState:
    elapsed_ms: int
    y: float
    velocity_y: float
    score: int
    gates: tuple[tuple[float, float, int, bool], ...]
    last_flap_ms: int
    flaps: tuple[int, ...]


def _search_gate_tuple(seed: object, index: int, x: float) -> tuple[float, float, int, bool]:
    gate = make_fly_gate(seed, index, x)
    return (float(gate["x"]), float(gate["gapY"]), int(gate["index"]), False)


def _search_step(
    seed: object,
    state: _SearchState,
    *,
    flap: bool,
    decision_ms: int,
) -> _SearchState | None:
    y = state.y
    velocity_y = FLY_FLAP_VELOCITY if flap else state.velocity_y
    score = state.score
    gates = [list(gate) for gate in state.gates]
    last_flap_ms = state.elapsed_ms if flap else state.last_flap_ms
    elapsed_ms = state.elapsed_ms
    remaining_ms = decision_ms
    while remaining_ms > 0:
        segment_ms = min(FLY_VERIFY_STEP_MS, remaining_ms)
        delta_seconds = segment_ms / 1000
        velocity_y += FLY_GRAVITY * delta_seconds
        y += velocity_y * delta_seconds
        speed = 112 + min(70, score * 3)
        for gate in gates:
            gate[0] -= speed * delta_seconds
            if not gate[3] and gate[0] + FLY_GATE_WIDTH < 76:
                gate[3] = True
                score += 1
        last_gate = gates[-1]
        while gates and gates[0][0] < -80:
            gates.pop(0)
        while len(gates) < 3:
            tail = gates[-1] if gates else last_gate
            gates.append(
                list(_search_gate_tuple(seed, int(tail[2]) + 1, float(tail[0]) + FLY_GATE_SPACING))
            )
        if y - 20 <= FLY_WORLD_TOP or y + 20 >= FLY_WORLD_BOTTOM:
            return None
        for gate_x, gap_y, _gate_index, _passed in gates:
            if gate_x <= 111 and gate_x + FLY_GATE_WIDTH >= 61:
                if y - 20 <= gap_y - FLY_GATE_GAP / 2:
                    return None
                if y + 20 >= gap_y + FLY_GATE_GAP / 2:
                    return None
        elapsed_ms += segment_ms
        remaining_ms -= segment_ms
    return _SearchState(
        elapsed_ms=elapsed_ms,
        y=y,
        velocity_y=velocity_y,
        score=score,
        gates=tuple((float(g[0]), float(g[1]), int(g[2]), bool(g[3])) for g in gates),
        last_flap_ms=last_flap_ms,
        flaps=state.flaps + ((state.elapsed_ms,) if flap else ()),
    )


def _search_quality(state: _SearchState) -> float:
    speed = 112 + min(70, state.score * 3)
    next_gate = next((gate for gate in state.gates if gate[0] + FLY_GATE_WIDTH >= 61), state.gates[0])
    time_to_gate = max(0.0, (next_gate[0] - 86) / speed)
    horizon = min(0.5, time_to_gate)
    predicted_y = state.y + state.velocity_y * horizon + 280 * horizon * horizon
    weight = 20 if time_to_gate < 0.7 else 7 if time_to_gate < 1.2 else 2
    return (
        state.score * 1_000_000
        - weight * abs(predicted_y - next_gate[1])
        - 0.05 * abs(state.velocity_y)
        - 0.01 * len(state.flaps)
    )


def _search_key(state: _SearchState) -> tuple:
    next_gate = next((gate for gate in state.gates if gate[0] + FLY_GATE_WIDTH >= 61), state.gates[0])
    return (
        state.score,
        int(next_gate[2]),
        round(next_gate[0] / 4),
        round(state.y / 3),
        round(state.velocity_y / 12),
        min(20, round((state.elapsed_ms - state.last_flap_ms) / 50)),
    )


def build_fly_proof(
    seed: object,
    *,
    target_score: int = FLY_TARGET_SCORE,
    max_duration_ms: int = 90_000,
    decision_ms: int = 32,
    min_flap_interval_ms: int = 96,
    beam_width: int = 2200,
) -> dict:
    requested_score = max(1, int(target_score or FLY_TARGET_SCORE))
    state = _SearchState(
        elapsed_ms=0,
        y=178.0,
        velocity_y=FLY_FLAP_VELOCITY,
        score=0,
        gates=(
            _search_gate_tuple(seed, 1, 314),
            _search_gate_tuple(seed, 2, 488),
            _search_gate_tuple(seed, 3, 662),
        ),
        last_flap_ms=0,
        flaps=(0,),
    )
    beam = [state]
    best_candidate: _SearchState | None = None
    while beam and beam[0].elapsed_ms < max_duration_ms:
        candidates: dict[tuple, _SearchState] = {}
        for current in beam:
            for should_flap in (False, True):
                if should_flap and current.elapsed_ms - current.last_flap_ms < min_flap_interval_ms:
                    continue
                next_state = _search_step(
                    seed,
                    current,
                    flap=should_flap,
                    decision_ms=decision_ms,
                )
                if next_state is None:
                    continue
                if next_state.score >= requested_score:
                    if best_candidate is None or _search_quality(next_state) > _search_quality(best_candidate):
                        best_candidate = next_state
                    continue
                key = _search_key(next_state)
                previous = candidates.get(key)
                if previous is None or _search_quality(next_state) > _search_quality(previous):
                    candidates[key] = next_state
        if best_candidate is not None:
            candidate_duration = min(max_duration_ms, best_candidate.elapsed_ms + 10_000)
            proof = {
                "flaps": list(best_candidate.flaps),
                "durationMs": candidate_duration,
                "clientScore": requested_score,
            }
            verified = replay_fly_proof(seed, proof)
            if verified["score"] >= requested_score and verified["hit"]:
                proof["durationMs"] = int(verified["collisionMs"]) + 1000
                return proof
            best_candidate = None
        beam = sorted(candidates.values(), key=_search_quality, reverse=True)[: max(1, int(beam_width))]
    raise ValueError("unable to solve fly proof within duration limit")
