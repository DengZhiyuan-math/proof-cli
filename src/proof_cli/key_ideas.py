"""A Review snapshot's key-ideas summary (ADR-0013, issue #103).

Review starts from the proof's key ideas, not from its LaTeX. Each node keeps a working
`proofs/<id>/key-ideas.md` beside `proof.tex`: Markdown, maths written `$…$`, with four
fixed fields, each a heading:

- 核心思路 (required): in a sentence or two, why the result holds.
- 主要步骤 (required): 3–7 steps, each naming the dependency it uses.
- 难点: where the proof is most likely wrong, what a reviewer should watch; may be 「无」.
- 未覆盖: boundary cases, extra assumptions, what isn't handled yet; may be 「无」.

It is an input of the proof like any other file in the node folder, so a Review snapshot
freezes it under its manifest and its SHA-256 counts toward the snapshot's: an Acceptance
is of "the summary the researcher read, and the frozen proof". Requesting review needs it,
with both required fields filled in (KEY_IDEAS_REQUIRED). When the proof agent drafted it,
the file's first line says so, and the review records "drafted by agent, confirmed by author".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

KEY_IDEAS_FILE = "key-ideas.md"

# (key, heading): the four fields, in order
FIELDS: tuple[tuple[str, str], ...] = (
    ("core_idea", "核心思路"),
    ("main_steps", "主要步骤"),
    ("difficulties", "难点"),
    ("not_covered", "未覆盖"),
)
REQUIRED: tuple[str, ...] = ("core_idea", "main_steps")
HEADINGS = dict(FIELDS)

_HEADING = re.compile(r"^#{1,6}[ \t]*(" + "|".join(re.escape(title) for _, title in FIELDS) + r")[ \t]*#*[ \t]*$", re.MULTILINE)
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
# the first line of a summary the proof agent drafted; the author confirms it by requesting review
_DRAFTED = re.compile(r"<!--\s*key-ideas\s+drafted-by:\s*(.*?)\s*-->")


def drafted_marker(agent: str) -> str:
    return f"<!-- key-ideas drafted-by: {agent} -->"


@dataclass
class KeyIdeas:
    """A parsed summary: each field's text (comments removed, stripped), and who drafted it."""

    fields: dict[str, str] = field(default_factory=dict)
    drafted_by: str | None = None

    @property
    def missing(self) -> list[str]:
        """The required fields that are absent or empty, by heading."""
        return [HEADINGS[key] for key in REQUIRED if not self.fields.get(key)]

    def as_json(self, text: str) -> dict:
        return {"text": text, "fields": {key: self.fields.get(key, "") for key, _ in FIELDS}, "drafted_by": self.drafted_by}


def parse(text: str) -> KeyIdeas:
    """Read the four fields from a summary's Markdown. A field's text runs from its heading to
    the next field's; HTML comments (a template's prompts, the drafted marker) don't count."""
    drafted = _DRAFTED.search(text)
    matches = list(_HEADING.finditer(text))
    fields: dict[str, str] = {}
    key_of = {title: key for key, title in FIELDS}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        key = key_of[match.group(1)]
        if key not in fields:  # a field written twice: the first counts
            fields[key] = _COMMENT.sub("", text[match.end():end]).strip()
    return KeyIdeas(fields=fields, drafted_by=(drafted.group(1) or None) if drafted else None)


def view(data: bytes | None) -> dict | None:
    """A frozen or working summary as the page shows it; None when there is none."""
    if data is None:
        return None
    text = data.decode("utf-8", errors="replace")
    return parse(text).as_json(text)


TEMPLATE = """\
## 核心思路

<!-- 必填：一两句话，说明为什么成立。数学公式写成 $…$。 -->

## 主要步骤

<!-- 必填：3–7 步，每一步写明用到哪个依赖节点。 -->

## 难点

<!-- 最容易出错、审阅时最该盯住的地方；可以写「无」。 -->

## 未覆盖

<!-- 边界情形、额外假设或尚未处理的部分；可以写「无」。 -->
"""
