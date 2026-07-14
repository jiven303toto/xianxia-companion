import biz_small_world_game


SMALL_WORLD_ACTION_COMMANDS = (
    biz_small_world_game.SMALL_WORLD_COLLECT_COMMAND,
    biz_small_world_game.SMALL_WORLD_MANIFEST_COMMAND,
    biz_small_world_game.SMALL_WORLD_PREACH_COMMAND,
)

SMALL_WORLD_ACTION_REPLY_STATES = {
    "await_collect_reply": biz_small_world_game.SMALL_WORLD_COLLECT_COMMAND,
    "await_manifest_reply": biz_small_world_game.SMALL_WORLD_MANIFEST_COMMAND,
    "await_preach_reply": biz_small_world_game.SMALL_WORLD_PREACH_COMMAND,
}

SMALL_WORLD_ACTION_STATES_BY_COMMAND = {
    command_text: state
    for state, command_text in SMALL_WORLD_ACTION_REPLY_STATES.items()
}

SMALL_WORLD_QUENCH_REPLY_STATE_PREFIX = "await_quench_reply:"


def build_auto_action_commands(
    panel_state: dict,
    strategy: dict,
    *,
    now: float,
    preach_cooldown_until: float,
) -> list[str]:
    return biz_small_world_game.build_auto_commands(
        panel_state,
        strategy,
        now=now,
        preach_cooldown_until=preach_cooldown_until,
    )


def select_next_action_command(
    command_texts: list[str],
    pending_action_commands: set[str],
) -> str:
    pending = {str(command or "").strip() for command in pending_action_commands}
    if pending:
        return ""
    for command_text in command_texts:
        normalized = str(command_text or "").strip()
        if normalized:
            return normalized
    return ""


def build_quench_command_from_collect_reply(reply_text: str) -> str:
    amount = biz_small_world_game.parse_incense_stock_after_collect(reply_text)
    if not amount or amount <= 0:
        return ""
    return f"{biz_small_world_game.SMALL_WORLD_QUENCH_COMMAND} {amount}"


def build_quench_reply_state(command_text: str) -> str:
    amount_text = str(command_text or "").removeprefix(
        biz_small_world_game.SMALL_WORLD_QUENCH_COMMAND
    ).strip()
    return f"{SMALL_WORLD_QUENCH_REPLY_STATE_PREFIX}{amount_text}"


def resolve_awaited_action_command(workflow_state: str) -> str:
    normalized = str(workflow_state or "").strip()
    command_text = SMALL_WORLD_ACTION_REPLY_STATES.get(normalized)
    if command_text:
        return command_text
    if not normalized.startswith(SMALL_WORLD_QUENCH_REPLY_STATE_PREFIX):
        return ""
    amount_text = normalized.removeprefix(SMALL_WORLD_QUENCH_REPLY_STATE_PREFIX).strip()
    if not amount_text.isdigit() or int(amount_text) <= 0:
        return ""
    return f"{biz_small_world_game.SMALL_WORLD_QUENCH_COMMAND} {amount_text}"
