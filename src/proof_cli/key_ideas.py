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
with both required fields filled in (KEY_IDEAS_REQUIRED).

Who wrote it is project state, not a line in the file (which its author could delete): the
studio records each draft the proof agent writes, with its SHA-256, and requesting review
derives the snapshot's provenance from that record (`provenance`). It is stored on the
snapshot's record and in every decision's payload, which the decision's binding covers.
"""

from __future__ import annotations

import hashlib
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
# HTML comments don't count: a template's prompts, or the `<!-- key-ideas drafted-by: … -->`
# first line an earlier draft of ADR-0013 wrote, which is read as a comment and nothing more
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

# a snapshot's key-ideas provenance, derived at request-review from the recorded drafts
AUTHOR = "author"
AGENT_CONFIRMED = "agent (confirmed by author at request-review)"
AGENT_EDITED = "agent draft, edited by author"
PROVENANCES = (AUTHOR, AGENT_CONFIRMED, AGENT_EDITED)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def provenance(frozen: bytes, drafted_sha256: str | None) -> str:
    """Who wrote the summary a snapshot freezes: the author, when no draft was recorded; the
    agent, when the frozen bytes are exactly the draft it wrote (the author confirmed it by
    requesting review); an agent draft the author edited, otherwise."""
    if drafted_sha256 is None:
        return AUTHOR
    return AGENT_CONFIRMED if digest(frozen) == drafted_sha256 else AGENT_EDITED


@dataclass
class KeyIdeas:
    """A parsed summary: each field's text (comments removed, stripped)."""

    fields: dict[str, str] = field(default_factory=dict)

    @property
    def missing(self) -> list[str]:
        """The required fields that are absent or empty, by heading."""
        return [HEADINGS[key] for key in REQUIRED if not self.fields.get(key)]

    def as_json(self, text: str) -> dict:
        return {"text": text, "fields": {key: self.fields.get(key, "") for key, _ in FIELDS}}


def parse(text: str) -> KeyIdeas:
    """Read the four fields from a summary's Markdown. A field's text runs from its heading to
    the next field's; HTML comments don't count."""
    matches = list(_HEADING.finditer(text))
    fields: dict[str, str] = {}
    key_of = {title: key for key, title in FIELDS}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        key = key_of[match.group(1)]
        if key not in fields:  # a field written twice: the first counts
            fields[key] = _COMMENT.sub("", text[match.end():end]).strip()
    return KeyIdeas(fields=fields)


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
