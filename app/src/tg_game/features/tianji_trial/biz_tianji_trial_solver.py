import math
from copy import deepcopy
from typing import Optional


def _orientation(a: dict, b: dict, c: dict) -> float:
    return (float(b["x"]) - float(a["x"])) * (float(c["y"]) - float(a["y"])) - (
        float(b["y"]) - float(a["y"])
    ) * (float(c["x"]) - float(a["x"]))


def _on_segment(a: dict, b: dict, c: dict) -> bool:
    eps = 0.000001
    return (
        min(float(a["x"]), float(c["x"])) - eps <= float(b["x"]) <= max(float(a["x"]), float(c["x"])) + eps
        and min(float(a["y"]), float(c["y"])) - eps <= float(b["y"]) <= max(float(a["y"]), float(c["y"])) + eps
        and abs(_orientation(a, c, b)) <= eps
    )


def _segments_cross(a: dict, b: dict, c: dict, d: dict) -> bool:
    eps = 0.000001
    o1 = _orientation(a, b, c)
    o2 = _orientation(a, b, d)
    o3 = _orientation(c, d, a)
    o4 = _orientation(c, d, b)
    if o1 * o2 < -eps and o3 * o4 < -eps:
        return True
    if abs(o1) <= eps and _on_segment(a, c, b):
        return True
    if abs(o2) <= eps and _on_segment(a, d, b):
        return True
    if abs(o3) <= eps and _on_segment(c, a, d):
        return True
    if abs(o4) <= eps and _on_segment(c, b, d):
        return True
    return False


def count_planarity_crossings(challenge: dict, positions: dict[str, dict]) -> int:
    edges = [edge for edge in (challenge.get("edges") or []) if isinstance(edge, dict)]
    count = 0
    for i, left in enumerate(edges):
        left_from = str(left.get("from") or "")
        left_to = str(left.get("to") or "")
        for right in edges[i + 1 :]:
            if left_from in {str(right.get("from") or ""), str(right.get("to") or "")}:
                continue
            if left_to in {str(right.get("from") or ""), str(right.get("to") or "")}:
                continue
            if _segments_cross(
                positions[left_from],
                positions[left_to],
                positions[str(right.get("from") or "")],
                positions[str(right.get("to") or "")],
            ):
                count += 1
    return count


def _cycle_order(node_ids: list[str], edges: list[dict], hub_id: str) -> list[str]:
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids if node_id != hub_id}
    for edge in edges:
        left = str(edge.get("from") or "")
        right = str(edge.get("to") or "")
        if not left or not right or hub_id in {left, right}:
            continue
        if left in adjacency and right in adjacency:
            adjacency[left].append(right)
            adjacency[right].append(left)
    if not adjacency:
        return [node_id for node_id in node_ids if node_id != hub_id]
    start = sorted(adjacency)[0]
    order = [start]
    previous = ""
    current = start
    while len(order) < len(adjacency):
        options = [node for node in adjacency.get(current, []) if node != previous]
        next_node = next((node for node in options if node not in order), "")
        if not next_node:
            break
        order.append(next_node)
        previous, current = current, next_node
    for node_id in node_ids:
        if node_id != hub_id and node_id not in order:
            order.append(node_id)
    return order


def build_planarity_trial_proof(challenge: dict) -> dict:
    nodes = [node for node in (challenge.get("nodes") or []) if isinstance(node, dict)]
    edges = [edge for edge in (challenge.get("edges") or []) if isinstance(edge, dict)]
    node_ids = [str(node.get("id") or "") for node in nodes if str(node.get("id") or "")]
    positions = {
        str(node.get("id")): {"x": float(node.get("x") or 50), "y": float(node.get("y") or 50)}
        for node in nodes
        if str(node.get("id") or "")
    }
    degree = {node_id: 0 for node_id in node_ids}
    for edge in edges:
        for key in ("from", "to"):
            node_id = str(edge.get(key) or "")
            if node_id in degree:
                degree[node_id] += 1
    hub_id = max(degree, key=lambda node_id: degree[node_id]) if degree else ""
    locked_ids = {
        str(value)
        for value in (
            challenge.get("lockedNodeIds")
            or challenge.get("locked_node_ids")
            or []
        )
    }
    if hub_id and hub_id not in locked_ids:
        positions[hub_id] = {"x": 50.0, "y": 50.0}
    order = _cycle_order(node_ids, edges, hub_id)
    candidates = []
    for reverse in (False, True):
        ordered = list(reversed(order)) if reverse else list(order)
        for offset in range(max(1, len(ordered))):
            candidate = deepcopy(positions)
            rotated = ordered[offset:] + ordered[:offset]
            for index, node_id in enumerate(rotated):
                if node_id in locked_ids:
                    continue
                angle = -math.pi / 2 + (2 * math.pi * index / max(1, len(rotated)))
                candidate[node_id] = {
                    "x": 50 + 36 * math.cos(angle),
                    "y": 50 + 36 * math.sin(angle),
                }
            try:
                crossings = count_planarity_crossings({"edges": edges}, candidate)
            except KeyError:
                crossings = 999
            candidates.append((crossings, candidate))
    crossings, best_positions = min(candidates, key=lambda item: item[0]) if candidates else (0, positions)
    if crossings > 0:
        raise ValueError("planarity solver could not remove crossings")
    moves = 0
    for node_id, point in best_positions.items():
        original = positions.get(node_id) or {}
        if abs(float(point["x"]) - float(original.get("x") or 0)) > 0.01 or abs(
            float(point["y"]) - float(original.get("y") or 0)
        ) > 0.01:
            moves += 1
    min_duration = int(float(challenge.get("minDurationMs") or 3200))
    duration = max(min_duration + 700, 4200 + moves * 450)
    return {
        "mode": "tianjiPlanarityV1",
        "challengeId": challenge.get("challengeId"),
        "durationMs": duration,
        "positions": best_positions,
        "moves": moves,
        "misses": 0,
    }


def _lights_neighbors(index: int, size: int) -> list[int]:
    row = index // size
    col = index % size
    values = [index]
    if row > 0:
        values.append(index - size)
    if row < size - 1:
        values.append(index + size)
    if col > 0:
        values.append(index - 1)
    if col < size - 1:
        values.append(index + 1)
    return values


def _solve_gf2(rows: list[int], rhs: list[int], n: int) -> list[int]:
    matrix = [[(rows[row] >> col) & 1 for col in range(n)] + [int(rhs[row]) & 1] for row in range(n)]
    pivot_cols: list[int] = []
    row = 0
    for col in range(n):
        pivot = next((candidate for candidate in range(row, n) if matrix[candidate][col]), -1)
        if pivot < 0:
            continue
        matrix[row], matrix[pivot] = matrix[pivot], matrix[row]
        for candidate in range(n):
            if candidate != row and matrix[candidate][col]:
                for index in range(col, n + 1):
                    matrix[candidate][index] ^= matrix[row][index]
        pivot_cols.append(col)
        row += 1
    for candidate in range(row, n):
        if not any(matrix[candidate][col] for col in range(n)) and matrix[candidate][n]:
            raise ValueError("lights out board has no solution")
    pivot_set = set(pivot_cols)
    free_cols = [col for col in range(n) if col not in pivot_set]
    best_solution: Optional[list[int]] = None
    best_weight = n + 1
    max_variants = 1 << len(free_cols)
    if max_variants > 4096:
        max_variants = 1
    for mask in range(max_variants):
        solution = [0] * n
        for bit, col in enumerate(free_cols):
            solution[col] = (mask >> bit) & 1
        for pivot_row in range(len(pivot_cols) - 1, -1, -1):
            col = pivot_cols[pivot_row]
            value = matrix[pivot_row][n]
            for next_col in range(col + 1, n):
                if matrix[pivot_row][next_col]:
                    value ^= solution[next_col]
            solution[col] = value
        weight = sum(solution)
        if weight < best_weight:
            best_solution = solution
            best_weight = weight
    return best_solution or [0] * n


def build_lightsout_trial_proof(challenge: dict) -> dict:
    size = max(4, min(5, int(float(challenge.get("gridSize") or challenge.get("grid_size") or 4))))
    n = size * size
    cells = [1 if int(value or 0) else 0 for value in (challenge.get("cells") or [])[:n]]
    if len(cells) != n:
        raise ValueError("lights out cells invalid")
    target = 1 if int(challenge.get("targetState", challenge.get("target_state", 1)) or 0) else 0
    rows = []
    for cell in range(n):
        mask = 0
        for press in range(n):
            if cell in _lights_neighbors(press, size):
                mask |= 1 << press
        rows.append(mask)
    rhs = [target ^ cell for cell in cells]
    solution = _solve_gf2(rows, rhs, n)
    press_indexes = [index for index, value in enumerate(solution) if value]
    final_cells = list(cells)
    events = []
    t = 900
    for index in press_indexes:
        for target_index in _lights_neighbors(index, size):
            final_cells[target_index] = 0 if final_cells[target_index] else 1
        events.append({"index": index, "t": t})
        t += 420
    if any(cell != target for cell in final_cells):
        raise ValueError("lights out solver failed")
    min_duration = int(float(challenge.get("minDurationMs") or 5400))
    duration = max(min_duration + 700, (events[-1]["t"] + 700) if events else min_duration + 700)
    return {
        "mode": "tianjiLightsOutV1",
        "challengeId": challenge.get("challengeId"),
        "durationMs": duration,
        "events": events,
        "cells": final_cells,
    }


def build_memory_trial_proof(challenge: dict) -> dict:
    cards = [card for card in (challenge.get("cards") or []) if isinstance(card, dict)]
    if not cards:
        raise ValueError("memory cards missing")
    by_pair: dict[str, list[dict]] = {}
    for card in cards:
        pair = str(card.get("pair") or card.get("symbol") or "")
        card_id = str(card.get("id") or "")
        if pair and card_id:
            by_pair.setdefault(pair, []).append(card)
    events = []
    t = int(float(challenge.get("previewMs") or challenge.get("preview_ms") or 3600)) + 500
    for pair in sorted(by_pair):
        pair_cards = sorted(by_pair[pair], key=lambda item: int(item.get("index") or 0))[:2]
        if len(pair_cards) != 2:
            raise ValueError("memory pair incomplete")
        for card in pair_cards:
            events.append({"id": str(card.get("id") or ""), "index": len(events), "t": t})
            t += 560
    min_duration = int(float(challenge.get("minDurationMs") or 8000))
    duration = max(min_duration + 700, (events[-1]["t"] + 700) if events else min_duration + 700)
    return {
        "mode": "tianjiMemoryV1",
        "challengeId": challenge.get("challengeId"),
        "durationMs": duration,
        "events": events,
        "mismatches": 0,
    }


def build_tianji_trial_proof(challenge: object) -> dict:
    data = challenge if isinstance(challenge, dict) else {}
    mode = str(data.get("mode") or "").strip()
    if mode == "tianjiPlanarityV1":
        return build_planarity_trial_proof(data)
    if mode == "tianjiLightsOutV1":
        return build_lightsout_trial_proof(data)
    if mode == "tianjiMemoryV1":
        return build_memory_trial_proof(data)
    raise ValueError(f"unsupported tianji trial mode: {mode}")
