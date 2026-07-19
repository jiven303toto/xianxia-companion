from functools import lru_cache
from typing import Iterable, Optional


COLS = 5
ROWS = 7
SIZE = COLS * ROWS
MAX_TIER = 9
DEFAULT_SEARCH_DEPTH = 4
HIGH_TIER_LEFT_ANCHOR_WEIGHT = 15


def normalize_board(value: object) -> tuple[int, ...]:
    items = list(value) if isinstance(value, (list, tuple)) else []
    board = []
    for item in items[:SIZE]:
        try:
            tier = int(item or 0)
        except (TypeError, ValueError):
            tier = 0
        board.append(max(0, min(MAX_TIER, tier)))
    board.extend([0] * (SIZE - len(board)))
    return tuple(board)


def legal_columns(board: object, excluded: Optional[Iterable[int]] = None) -> list[int]:
    values = normalize_board(board)
    blocked = {int(column) for column in (excluded or [])}
    return [column for column in range(COLS) if values[column] == 0 and column not in blocked]


def _gravity(values: list[int]) -> list[int]:
    result = [0] * SIZE
    for column in range(COLS):
        pieces = [
            values[row * COLS + column]
            for row in range(ROWS - 1, -1, -1)
            if values[row * COLS + column] > 0
        ]
        for offset, tier in enumerate(pieces):
            result[(ROWS - 1 - offset) * COLS + column] = tier
    return result


def _find_pair(values: list[int]) -> Optional[tuple[int, int, int]]:
    for row in range(ROWS - 1, -1, -1):
        for column in range(COLS):
            index = row * COLS + column
            tier = values[index]
            if not tier or tier >= MAX_TIER:
                continue
            if column + 1 < COLS and values[index + 1] == tier:
                return index, index + 1, tier
            if row > 0 and values[index - COLS] == tier:
                return index, index - COLS, tier
    return None


def apply_move(board: object, column: int, piece: int) -> dict:
    values = list(normalize_board(board))
    try:
        resolved_column = int(column)
    except (TypeError, ValueError):
        resolved_column = -1
    try:
        resolved_piece = max(1, min(MAX_TIER, int(piece or 1)))
    except (TypeError, ValueError):
        resolved_piece = 1
    if resolved_column < 0 or resolved_column >= COLS:
        return {
            "accepted": False,
            "board": tuple(values),
            "score_gained": 0,
            "merges": 0,
            "max_tier": max(values or [1]),
        }

    landing_row = -1
    for row in range(ROWS - 1, -1, -1):
        index = row * COLS + resolved_column
        if values[index] == 0:
            values[index] = resolved_piece
            landing_row = row
            break
    if landing_row < 0:
        return {
            "accepted": False,
            "board": tuple(values),
            "score_gained": 0,
            "merges": 0,
            "max_tier": max(values or [1]),
        }

    score_gained = 0
    merges = 0
    while True:
        pair = _find_pair(values)
        if pair is None:
            break
        first, second, tier = pair
        values[first] = min(MAX_TIER, tier + 1)
        values[second] = 0
        values = _gravity(values)
        merges += 1
        score_gained += 10 * (2 ** min(12, tier)) + max(0, merges - 1) * 5

    return {
        "accepted": True,
        "board": tuple(values),
        "score_gained": score_gained,
        "merges": merges,
        "max_tier": max(max(values or [1]), resolved_piece, 1),
    }


def _column_heights(board: tuple[int, ...]) -> list[int]:
    return [
        sum(1 for row in range(ROWS) if board[row * COLS + column] > 0)
        for column in range(COLS)
    ]


def evaluate_board(board: object) -> float:
    values = normalize_board(board)
    heights = _column_heights(values)
    empty_count = values.count(0)
    open_columns = sum(1 for height in heights if height < ROWS)
    max_height = max(heights or [0])
    height_spread = max_height - min(heights or [0])
    tier_nine_count = values.count(MAX_TIER)
    left_anchor_score = sum(
        (COLS - (index % COLS)) * (2 ** max(0, tier - 1))
        for index, tier in enumerate(values)
        if tier
    )
    return (
        empty_count * 2600
        + open_columns * 9000
        - max_height * 700
        - sum(height * height for height in heights) * 90
        - height_spread * 300
        + max(values or [1]) * 180
        - tier_nine_count * 600
        + left_anchor_score * HIGH_TIER_LEFT_ANCHOR_WEIGHT
    )


def choose_column(
    board: object,
    piece: int,
    *,
    depth: int = DEFAULT_SEARCH_DEPTH,
    excluded_columns: Optional[Iterable[int]] = None,
) -> Optional[int]:
    values = normalize_board(board)
    blocked = tuple(sorted({int(column) for column in (excluded_columns or [])}))
    search_depth = max(1, int(depth or 1))

    @lru_cache(maxsize=None)
    def decision(state: tuple[int, ...], current_piece: int, remaining: int) -> float:
        columns = legal_columns(state)
        if not columns:
            return -100_000_000.0
        if remaining <= 0:
            return evaluate_board(state)
        best = -100_000_000.0
        for column in columns:
            result = apply_move(state, column, current_piece)
            next_state = result["board"]
            immediate = result["score_gained"] * 2.5 + result["merges"] * 650
            if remaining == 1:
                future = evaluate_board(next_state)
            else:
                future = (
                    0.8 * decision(next_state, 1, remaining - 1)
                    + 0.2 * decision(next_state, 2, remaining - 1)
                )
            best = max(best, immediate + future)
        return best

    best_column = None
    best_value = -100_000_000.0
    for column in legal_columns(values, blocked):
        result = apply_move(values, column, piece)
        next_state = result["board"]
        immediate = result["score_gained"] * 2.5 + result["merges"] * 650
        if search_depth == 1:
            future = evaluate_board(next_state)
        else:
            future = (
                0.8 * decision(next_state, 1, search_depth - 1)
                + 0.2 * decision(next_state, 2, search_depth - 1)
            )
        value = immediate + future
        if best_column is None or value > best_value:
            best_column = column
            best_value = value
    return best_column
