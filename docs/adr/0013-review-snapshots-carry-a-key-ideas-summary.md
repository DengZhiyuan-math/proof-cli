# A Review snapshot carries a key-ideas summary, and review starts from it

**Status**: accepted (decided in #100; implemented in #103).
- **Amends** ADR-0010 point 2 and ADR-0011 point 5: a Review snapshot also freezes the node's key-ideas summary, `key-ideas.md`, and requesting review needs one.
- **Amends** ADR-0011 point 2 (and #71): the studio's review view shows the snapshot's key ideas and the decisions, not its frozen LaTeX sources or PDF.

## Context

Since ADR-0011 a Review snapshot freezes every LaTeX input of a node's proof, and the studio's review view (#71) was built around those files: each frozen file opened read-only, beside the archived PDF. The home page's review card pasted the snapshot's `proof.tex` in full. In use the researcher doesn't review a proof by reading its posted LaTeX from the top. They start from its **key ideas**: why it holds, the steps it takes and which dependency each step uses, where it is most likely wrong, and what it leaves out. Only then do they go into the details. Nothing in the snapshot said any of that, so every review began by reconstructing it.

## Decision

1. **Each node keeps a key-ideas summary, `proofs/<id>/key-ideas.md`.** It is Markdown, with mathematics written `$…$`, and has four fixed fields, each a heading:
   - **核心思路** (required): in a sentence or two, why the result holds.
   - **主要步骤** (required): 3–7 steps, each naming the dependency node it uses.
   - **难点**: where the proof is most likely wrong, what a reviewer should check hardest; may be 「无」.
   - **未覆盖**: boundary cases, extra assumptions, or parts not yet handled; may be 「无」.

   A field's text runs from its heading to the next field's. HTML comments don't count, so a template's prompts leave a field empty.

2. **The summary is frozen with the proof, and bound by the same hash.**
   - It is one of the node's working inputs, so requesting review copies it into `snapshots/v<N>/` (as `node/key-ideas.md`), lists it in the manifest, and counts it toward the snapshot's SHA-256.
   - What an Acceptance accepts is therefore **the summary the researcher read, together with the frozen proof**. Editing the frozen summary after a decision makes that decision unverifiable, exactly as editing a frozen `.tex` file does.
   - A change to the summary alone is a new version. `request_review`'s one unchanged-check covers it: the same inputs (the summary among them), on the same dependencies, with the snapshot intact, are refused as `WORKING_PROOF_UNCHANGED`; anything else is `v<N+1>`, and the node is review-needed again.
   - The summary isn't compiled into the PDF, so editing it doesn't make the studio's build stale for archiving.

3. **Requesting review needs the summary.** A missing `key-ideas.md`, or one whose 核心思路 or 主要步骤 is empty, is refused with `KEY_IDEAS_REQUIRED`. The same refusal comes from the CLI (in its text output and its `--json` envelope, naming the file and the missing fields), from the node panel, and from the proof agent's own `proof node request-review`.

4. **Review starts from the summary.**
   - **The studio's review view shows only the snapshot's key ideas and the decision controls.** It doesn't render the frozen LaTeX sources or the archived PDF. It links to the node's page, which shows every frozen file exactly and links the archived PDF.
   - **The home page's review card shows 核心思路 and 难点**, not the snapshot's LaTeX.
   - **Hovering a node on the map shows its current snapshot's 核心思路**, under its statement; the tree's links carry it as their title.
   - **Maths is typeset with KaTeX.** Inline `$…$` and display `$$…$$` in the summary are rendered in the review view and on the review cards by [KaTeX](https://katex.org) 0.18.9, vendored with its `.woff2` fonts under the studio's `static/vendor/` (MIT), the way CodeMirror and PDF.js are. The map page loads the same files from `/static/shared/`, and nothing is fetched from the network. KaTeX builds DOM nodes and styles them through the CSSOM, which both pages' Content-Security-Policy allows. Everything else in the summary is inserted as text, never as HTML.
   - A formula KaTeX can't parse shows as the literal text it was written as, with the parse error on hover, and the rest of the summary still renders; rendering never throws. `\$` is a dollar sign, not a delimiter.
   - The map's hover is an SVG `<title>`, which can't hold markup, so there 核心思路 is plain text, `$…$` as written.

5. **The proof agent drafts a missing summary; the author confirms it.**
   - When the working `key-ideas.md` is missing, the node panel offers **Draft key ideas with the proof agent**. The studio runs one edit turn of the node's proof agent, briefed to summarise `proof.tex` and the dependencies under the four headings, that may write only `key-ideas.md`. The turn shows in the agent panel, and its Undo removes the draft.
     *Update (spec #145, PR #149):* the drafting is the Typesetter's — a run's turn, or the "+" menu's one-off *Typesetter · draft key ideas* — briefed with the same four headings; the separate drafting route is gone. Every agent turn that leaves `key-ideas.md` changed is recorded as that agent's draft, below, whatever role it was. So the drafting turn is no longer "one edit turn that may write only `key-ideas.md`": it is a Typesetter turn of a run, which holds the node's claim under the agent's name and may also write the node's `*.tex`. The record can over-credit the agent but never hides it: a summary the author wrote and an agent turn then edited reads, when the author keeps it as it is, as the agent's draft confirmed by the author. A save of `key-ideas.md` from the studio's Files view is refused (`KEY_IDEAS_AGENT_TURN`) while an agent's edit turn runs on the node, so the researcher's own save is never folded into the agent's turn.
   - **Who wrote the summary is recorded in project state, not in the file.** A line in the file could be deleted by its author, and the audit trail would then say nothing. After an agent turn that wrote it the studio records a `proof_map_key_ideas_drafted` event for the node: which agent wrote `key-ideas.md`, and the SHA-256 of what it wrote. The file is left exactly as the agent wrote it.
   - The author edits the draft, or doesn't, and **requesting review is how they confirm it**. `request_review` derives the snapshot's `key_ideas_drafted_by` from the node's latest recorded draft:
     - `agent (confirmed by author at request-review)` when the frozen summary's SHA-256 is the draft's;
     - `agent draft, edited by author` when it differs;
     - `author` when no draft was ever recorded for the node.
   - The value is stored on the snapshot's Candidate proof record, and on its `request_review` result and event. Every decision made on the snapshot (an Acceptance, an Evidence review, a Lightweight re-review, a Promote) carries it in its payload, which the decision's binding covers, and in its `reviews.jsonl` line. A change to the recorded value after a decision makes the decision unverifiable, as a change to a frozen file does. The pages show it as 「由 agent 起草、作者确认」, 「由 agent 起草、作者修改」 or 「作者撰写」.
   - A summary whose first line is `<!-- key-ideas drafted-by: … -->`, the marker an earlier draft of this ADR wrote, parses as before: the line is an HTML comment and counts for nothing, provenance included.
   - The record is of drafts, not of every edit: a draft the author deleted and replaced with one of their own still reads `agent draft, edited by author`.
   - The proof agent's standing brief asks it to write the summary before it requests review.

6. **Older snapshots stay reviewable.** A snapshot frozen before this ADR, folder or single file, has no summary. It is reviewed as before: its review view says 「这个 snapshot 没有关键思路摘要」 and links to the node's page, and its review card says the same. Nothing asks for a summary to be written for it, and its decisions are unchanged. Only a new review request needs one.

## Consequences

- Every new Review snapshot holds one more file, and its SHA-256 covers it. The manifest format and the digest rule are unchanged, so no older snapshot or decision needs migrating.
- A request for review costs the author a short summary. The proof agent can draft it, and it is the first thing the researcher reads.
- Reading a proof's LaTeX in full moves one click away from deciding on it: the node's page shows it exactly, and the studio's editor has the working files. A decision still binds the whole frozen snapshot, sources and summary alike.
- An imported result has no proof and no summary. Its Reference review and review card are unchanged (ADR-0012).
