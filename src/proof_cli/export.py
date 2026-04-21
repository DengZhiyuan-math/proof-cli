from __future__ import annotations

from pathlib import Path

from .rendering import render_export
from .storage import ProjectStore
from .proof_state import summarize_state


def build_export(store: ProjectStore) -> str:
    return render_export(summarize_state(store))


def write_export(store: ProjectStore, path: str | Path) -> str:
    content = build_export(store)
    output = Path(path)
    output.write_text(content)
    return content

