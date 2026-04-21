from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .storage import ProjectStore


@dataclass
class LayeredMemory:
    working: list[str] = field(default_factory=list)
    semantic: list[str] = field(default_factory=list)
    episodic: list[str] = field(default_factory=list)
    procedural: list[str] = field(default_factory=list)
    tracked_symbols: list[str] = field(default_factory=list)


def _memory_path(store: ProjectStore) -> Path:
    return store.root / ".proof" / "memory.json"


def load_memory(store: ProjectStore) -> LayeredMemory:
    path = _memory_path(store)
    if not path.exists():
        return LayeredMemory()
    data = json.loads(path.read_text())
    return LayeredMemory(
        working=list(data.get("working", [])),
        semantic=list(data.get("semantic", [])),
        episodic=list(data.get("episodic", [])),
        procedural=list(data.get("procedural", [])),
        tracked_symbols=list(data.get("tracked_symbols", [])),
    )


def save_memory(store: ProjectStore, memory: LayeredMemory) -> LayeredMemory:
    path = _memory_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "working": memory.working,
                "semantic": memory.semantic,
                "episodic": memory.episodic,
                "procedural": memory.procedural,
                "tracked_symbols": memory.tracked_symbols,
            },
            indent=2,
        )
    )
    return memory


def record_memory(store: ProjectStore, layer: str, entry: str) -> LayeredMemory:
    memory = load_memory(store)
    bucket = getattr(memory, layer)
    bucket.append(entry)
    return save_memory(store, memory)


def track_symbol(store: ProjectStore, symbol: str) -> LayeredMemory:
    memory = load_memory(store)
    if symbol not in memory.tracked_symbols:
        memory.tracked_symbols.append(symbol)
    return save_memory(store, memory)


def recent_symbols(store: ProjectStore) -> list[str]:
    return list(load_memory(store).tracked_symbols)

