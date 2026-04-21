from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DSLCommandCategory = Literal["proof", "retrieval", "grounding", "review"]


_RETRIEVAL_COMMANDS = {"search", "import"}
_GROUNDING_COMMANDS = {"ground"}
_REVIEW_COMMANDS = {"review"}


def _parse_target_and_argument(text: str) -> tuple[str, str]:
    stripped = text.strip()
    if not stripped:
        return "", ""
    parts = stripped.split(maxsplit=1)
    target = parts[0]
    argument = parts[1].strip() if len(parts) > 1 else ""
    return target, argument


def _parse_references(text: str) -> tuple[str, ...]:
    cleaned = text.replace(",", " ")
    references: list[str] = []
    for token in cleaned.split():
        lower = token.lower()
        if lower in {"because", "since", "rationale"}:
            break
        if lower in {"using", "with", "via", "on"} and not references:
            continue
        references.append(token)
    return tuple(reference for reference in references if reference)


@dataclass(frozen=True)
class DSLCommand:
    name: str
    argument: str = ""
    category: DSLCommandCategory = "proof"
    target: str = ""
    references: tuple[str, ...] = ()


def _classify_command(name: str) -> DSLCommandCategory:
    if name in _RETRIEVAL_COMMANDS:
        return "retrieval"
    if name in _GROUNDING_COMMANDS:
        return "grounding"
    if name in _REVIEW_COMMANDS:
        return "review"
    return "proof"


def parse_program(text: str) -> list[DSLCommand]:
    commands: list[DSLCommand] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        name = parts[0].lower()
        argument = parts[1].strip() if len(parts) > 1 else ""
        category = _classify_command(name)
        target = ""
        references: tuple[str, ...] = ()

        if name == "search":
            target = argument
        elif name == "import":
            target, argument = _parse_target_and_argument(argument)
        elif name == "ground":
            target, tail = _parse_target_and_argument(argument)
            references = _parse_references(tail)
        elif name == "review":
            target, argument = _parse_target_and_argument(argument)

        commands.append(
            DSLCommand(
                name=name,
                argument=argument,
                category=category,
                target=target,
                references=references,
            )
        )
    return commands
