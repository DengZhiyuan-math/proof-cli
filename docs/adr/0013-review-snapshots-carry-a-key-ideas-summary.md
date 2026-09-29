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
   - The summary is shown as text. `$…$` is shown as written, not typeset: the page ships no maths renderer.

5. **The proof agent drafts a missing summary; the author confirms it.**
   - When the working `key-ideas.md` is missing, the node panel offers **Draft key ideas with the proof agent**. The studio runs one edit turn of the node's proof agent, briefed to summarise `proof.tex` and the dependencies under the four headings, that may write only `key-ideas.md`. The turn shows in the agent panel, and its Undo removes the draft.
   - After the turn, the draft's first line records who drafted it: `<!-- key-ideas drafted-by: studio-agent -->`. The author edits the draft, and **requesting review is how they confirm it**. An author who removes that line is taking the summary as their own.
   - The review record says so. The snapshot's `request_review` result and its `proof_map_review_requested` event carry `key_ideas_drafted_by`, and an Acceptance on it writes `key_ideas_drafted_by` in its `reviews.jsonl` line. The pages show it as 「由 agent 起草、作者确认」. It is read from the frozen summary, so it is bound by the snapshot's hash like the rest of it, and isn't part of the decision's binding.
   - The proof agent's standing brief asks it to write the summary before it requests review.

6. **Older snapshots stay reviewable.** A snapshot frozen before this ADR, folder or single file, has no summary. It is reviewed as before: its review view says 「这个 snapshot 没有关键思路摘要」 and links to the node's page, and its review card says the same. Nothing asks for a summary to be written for it, and its decisions are unchanged. Only a new review request needs one.

## Consequences

- Every new Review snapshot holds one more file, and its SHA-256 covers it. The manifest format and the digest rule are unchanged, so no older snapshot or decision needs migrating.
- A request for review costs the author a short summary. The proof agent can draft it, and it is the first thing the researcher reads.
- Reading a proof's LaTeX in full moves one click away from deciding on it: the node's page shows it exactly, and the studio's editor has the working files. A decision still binds the whole frozen snapshot, sources and summary alike.
- An imported result has no proof and no summary. Its Reference review and review card are unchanged (ADR-0012).
