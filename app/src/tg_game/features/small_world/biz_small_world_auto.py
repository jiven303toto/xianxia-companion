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
