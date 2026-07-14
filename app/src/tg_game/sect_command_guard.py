from functools import lru_cache
from typing import Iterable

from tg_game.sect_features import SECT_FEATURES


class SectCommandScopeError(ValueError):
    pass


COMMON_SECT_COMMANDS = {
    ".晋升长老",
}

COMPANION_COMMANDS = {
    ".我的侍妾",
    ".每日问安",
    ".赠予侍妾",
    ".灵力反哺",
    ".侍妾卜算",
    ".远航状态",
    ".远航归来",
    ".侍妾远航",
    ".入梦",
    ".入梦寻图",
    ".天机代卜",
    ".共历心劫",
    ".安置侍妾",
    ".召回侍妾",
    ".拼图",
    ".立誓",
    ".毁誓",
}

EXTRA_SECT_COMMANDS = {
    "星宫": [
        ".观星台",
    ],
    "天星宗": [
        ".天机盘",
        ".观命",
        ".定命",
        ".推命",
        ".改命",
        ".消劫",
    ],
    "阴罗宗": [
        ".一键安抚幡灵",
        ".一键收取精华",
    ],
    "万灵宗": [
        ".灵兽边境",
        ".灵兽巡边",
        ".巡边归来",
        ".灵兽巡游",
        ".灵兽互动",
    ],
}


def normalize_sect_name(value: object) -> str:
    return str(value or "").replace("【", "").replace("】", "").strip()


def _normalize_command(value: object) -> str:
    return " ".join(str(value or "").strip().split())


def _iter_feature_commands() -> Iterable[tuple[str, str]]:
    for feature in SECT_FEATURES:
        sect_name = normalize_sect_name(feature.get("name"))
        if not sect_name:
            continue
        for command in feature.get("commands") or []:
            normalized = _normalize_command(command)
            if (
                normalized
                and normalized not in COMMON_SECT_COMMANDS
                and normalized not in COMPANION_COMMANDS
            ):
                yield normalized, sect_name
    for sect_name, commands in EXTRA_SECT_COMMANDS.items():
        for command in commands:
            normalized = _normalize_command(command)
            if normalized:
                yield normalized, normalize_sect_name(sect_name)


@lru_cache(maxsize=1)
def _sect_command_patterns() -> tuple[tuple[str, frozenset[str]], ...]:
    owners_by_command: dict[str, set[str]] = {}
    for command, sect_name in _iter_feature_commands():
        owners_by_command.setdefault(command, set()).add(sect_name)
    return tuple(
        (command, frozenset(owners))
        for command, owners in sorted(
            owners_by_command.items(), key=lambda item: len(item[0]), reverse=True
        )
    )


def sect_command_owners(command_text: object) -> set[str]:
    normalized = _normalize_command(command_text)
    if not normalized.startswith("."):
        return set()
    owners: set[str] = set()
    for command, command_owners in _sect_command_patterns():
        if normalized == command or normalized.startswith(command + " "):
            owners.update(command_owners)
    return owners


def is_companion_command(command_text: object) -> bool:
    normalized = _normalize_command(command_text)
    if not normalized.startswith("."):
        return False
    return any(
        normalized == command or normalized.startswith(command + " ")
        for command in COMPANION_COMMANDS
    )


def validate_sect_command_scope(
    current_sect_name: object, command_text: object, *, has_companion: bool = False
) -> None:
    if is_companion_command(command_text):
        if has_companion:
            return
        raise SectCommandScopeError("当前角色没有侍妾，不能发送侍妾命令")
    owners = sect_command_owners(command_text)
    if not owners:
        return
    current = normalize_sect_name(current_sect_name)
    if current in owners:
        return
    owner_text = "、".join(sorted(owners))
    current_text = current or "未入宗门"
    raise SectCommandScopeError(
        f"当前角色宗门为 {current_text}，不能发送 {owner_text} 专属命令"
    )
