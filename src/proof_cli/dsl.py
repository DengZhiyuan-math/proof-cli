from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DSLCommand:
    name: str
    argument: str = ""


def parse_program(text: str) -> list[DSLCommand]:
    commands: list[DSLCommand] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        name = parts[0].lower()
        argument = parts[1].strip() if len(parts) > 1 else ""
        commands.append(DSLCommand(name=name, argument=argument))
    return commands

