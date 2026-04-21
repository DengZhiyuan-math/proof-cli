from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


DSLCommandCategory = Literal[
    "proof",
    "retrieval",
    "grounding",
    "review",
    "reasoning",
    "bug",
    "evidence",
    "debug",
    "repair",
    "trace",
    "explain",
]


_RETRIEVAL_COMMANDS = {"search", "import"}
_GROUNDING_COMMANDS = {"ground"}
_REVIEW_COMMANDS = {"review"}
_COMPOUND_COMMANDS: dict[str, dict[str, str]] = {
    "obligation": {"derive": "obligation_derive"},
    "bug": {"scan": "bug_scan", "list": "bug_list", "show": "bug_show"},
    "evidence": {"show": "evidence_show"},
    "debug": {"generate": "debug_generate", "list": "debug_list"},
    "repair": {"mark": "repair_mark"},
    "review": {"suspicion": "review_suspicion"},
    "trace": {"dependency": "trace_dependency"},
    "explain": {"apply": "explain_apply"},
}
_COMPOUND_CATEGORIES: dict[str, DSLCommandCategory] = {
    "obligation_derive": "reasoning",
    "reason": "reasoning",
    "bug_scan": "bug",
    "bug_list": "bug",
    "bug_show": "bug",
    "evidence_show": "evidence",
    "debug_generate": "debug",
    "debug_list": "debug",
    "repair_mark": "repair",
    "review_suspicion": "review",
    "trace_dependency": "trace",
    "explain_apply": "explain",
}


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


def _parse_name_and_payload(parts: list[str]) -> tuple[str, list[str]]:
    if not parts:
        return "", []
    name = parts[0].lower()
    payload = parts[1:]
    if payload:
        subcommand = payload[0].lower()
        if name in _COMPOUND_COMMANDS and subcommand in _COMPOUND_COMMANDS[name]:
            return _COMPOUND_COMMANDS[name][subcommand], payload[1:]
    return name, payload


def _parse_target_and_argument_from_parts(parts: list[str]) -> tuple[str, str]:
    if not parts:
        return "", ""
    target = parts[0]
    argument = " ".join(parts[1:]).strip()
    return target, argument


@dataclass(frozen=True)
class DSLCommand:
    name: str
    argument: str = ""
    category: DSLCommandCategory = "proof"
    target: str = ""
    references: tuple[str, ...] = ()


def _classify_command(name: str) -> DSLCommandCategory:
    if name in _COMPOUND_CATEGORIES:
        return _COMPOUND_CATEGORIES[name]
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
        parts = line.split()
        name, payload = _parse_name_and_payload(parts)
        argument = " ".join(payload).strip()
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
        elif name in {
            "reason",
            "obligation_derive",
            "bug_scan",
            "bug_list",
            "bug_show",
            "evidence_show",
            "debug_generate",
            "debug_list",
            "repair_mark",
            "review_suspicion",
            "trace_dependency",
            "explain_apply",
        }:
            target, argument = _parse_target_and_argument_from_parts(payload)

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
