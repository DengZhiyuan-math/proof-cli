# Implementation tickets for ADR-0025 — as published (2026-10-20)

The tickets in the private zeqome repositories keep their bodies there; only their links are here.

Language and shape follow the ADR-0021 slices (proof-cli #194–#196, proof-agents #15–#32, proof-web #39–#44): English, a title that states the behaviour, `Part of #<tracking>`, bullets, `Acceptance criteria:`. Public proof-cli tickets carry design, counts and pointers into the local inventory only (`docs/research/2026-10-19-state-inventory/`, untracked); no per-item detail and no private file locations. Private-repo tickets may name their own files.

Ids below (T0, C1…, A1…, W1…) are draft handles; replace with issue numbers on creation. "Blocked by" becomes native issue dependencies.

---

## T0 · proof-cli · ADR-0025: five stored states, four computed conclusions

Tracking issue, like #193 for ADR-0021.

- Decided on the map 系统状态清单与精简 (#267) and the paused map #254; recorded in ADR-0025 and the revised CONTEXT.md.
- Only five states are kept as source facts and read by gates: Seal, Statement layer, Proof layer, Assignee, Run state. The conclusion (uncertain / true / verified true / false) is computed; a node's conclusion is never above its weakest dependency.
- Measured by three checks: gates read only the five states and what is computed from them, parse no text and name the error they prevent (95 violations today); one fact in one place (123 stored derivable fields, 148 duplicated fields over 50 facts, 28 facts computed twice); one name for one thing (16 names still clashing).
- Tickets: listed below as they are created, in proof-cli, zeqome/proof-agents and zeqome/proof-web.

Blocked by: —

---

## Core (DengZhiyuan-math/proof-cli)

### C1 · A node's states are Seal, Statement layer, Proof layer and Assignee, and its conclusion is computed (ADR-0025)

Part of T0.
- One core reading gives each node its Seal (unsealed / sealed true / sealed false), Statement layer (unchallenged / challenged as false / false), Proof layer (incomplete / checks passed / expert-verified) and Assignee, computed from the records that hold them, and its conclusion from the table in ADR-0025, capped by its weakest dependency (a false dependency makes the node uncertain, not false).
- It replaces the workflow, acceptance and integrity axes: Rejected, Unverifiable, Potentially stale, Blocked and their reasons are gone; Provisional and Conditional are read off the conclusion; frontier, awaiting-decision and dropped are computed from it. Until the new decision records land (C4), an existing Acceptance or Reference review line reads as expert-verified.
- `node show --json`, `node list --json` and `frontier` show the four node states and the conclusion; nothing else in core reads the old axes.
- Error it prevents: two readings of one node's conclusion that disagree (today three axes plus overlays, 40 values).

Acceptance criteria:
- synthetic maps cover every row of the conclusion table and the dependency rule: a verified parent over an unverified dependency reads true and becomes verified true, with no action, when the dependency is verified; a dependency that becomes false leaves the parent uncertain;
- no core gate or output reads workflow, acceptance or integrity;
- the existing trust tests pass, rewritten to the new words.

Local inventory: `core-concepts.tsv` concepts 1–15 (40 values: 25 computed, 8 states, 7 deleted).
Blocked by: —

### C2 · Challenges carry a kind, take effect at once, and are withdrawn with a reason (ADR-0025)

Part of T0.
- A Challenge records its kind (statement or proof), who raised it, the version it targets and why. A proof Challenge returns Proof layer to incomplete; a statement Challenge sets Statement layer to challenged as false and, raised by an agent, must link a counterexample, itself an ordinary proposition. Anyone may raise one on any unsealed node; no review of the Challenge first.
- Withdrawal, with a reason: the researcher withdraws their own; any agent withdraws any agent's; no agent withdraws the researcher's. The researcher's "not a problem" withdraws an agent's Challenge (restoring a verification is C4's click).
- A Challenge follows a restatement to the new version; a proof gap is superseded by the restatement, a counterexample follows the statement.
- Which nodes are stopped by a statement Challenge is computed: everything under each direct user of the challenged node, and nothing beside it.
- Replaces Challenge-on-Accepted-only, researcher-only resolution and the stored dismissed status; the four-state refutation relation and its pauses are not built.

Acceptance criteria:
- a synthetic A ← U1 ← {N, S}, A ← U2: N challenged as false stops U1's subtree including S, leaves U2 running, and A reads uncertain;
- an agent cannot withdraw the researcher's Challenge; any agent can withdraw another agent's, and the reason enters the next briefing;
- a sealed node refuses an agent's Challenge.

Local inventory: `core-concepts.tsv` concept 21 (6 values); `other-values.tsv` concepts 47–51 and 53 (13 values, 9 deleted); `gates.tsv` layer=core family=legacy-fallback (3).
Blocked by: C1

### C3 · A verdict has an id and numbered objections, and each objection's ending is recorded (ADR-0025)

Part of T0.
- A Verifier verdict carries a stable id; its objections are numbered inside it and bound to the version read. Each objection ends in one of three ways, recorded in the work log: fixed (the passing verdict says where and why), withdrawn (with a reason), superseded by a restatement (recorded by the system).
- A passing verdict that omits an ending for any objection still open on the previous version is refused. An audit records no endings; old objections are left to the next ordinary Verifier.
- Check records carry a structured marker for who checked and what (Verifier, audit, mechanical check), so Proof layer and audit outcomes are computed without reading notes.
- Error it prevents: a passing verdict that silently drops an objection; an audit outcome read off free text.

Acceptance criteria:
- recording a passing verdict without an ending for an open objection fails with a named error; with one, it passes and the objection reads fixed;
- Proof layer reads checks passed only from a structured passing verdict on the current inputs;
- `node show --json` lists each objection with its ending.

Local inventory: `other-values.tsv` concept 54 (1 value); `core-concepts.tsv` concepts 17 and 20 (8 values); `gates.tsv` rows whose note names audit or verdict text (counted in layer=core family=other).
Blocked by: C2

### C4 · Verify, seal and unseal are the researcher's decisions in reviews.jsonl (ADR-0025)

Part of T0.
- New decision lines: verify (local node or imported result), seal true, seal false, unseal, and "not a problem" when it restores a verification. Each names who, when, which version and the explanation; the commit author is the researcher. Agents never record one; a project that is not a git repo, or a failed commit, records it locally marked uncommitted.
- Seal true seals everything it rests on: only the directly sealed node is recorded, the covered set is computed, and unseal releases the same set. Seal false seals only the node. Sealed nodes are not challenged by agents and not audited; the seal's explanation goes into every later briefing.
- A verification counts only for the version it verified; a node may be verified above unverified dependencies (C1 caps it); a dependency that becomes false voids it.
- Replaces accept / revision requested / reject and the Reference review outcomes (reviewed → verify; no longer callable → seal false). Promote and Trust rules stay.

Acceptance criteria:
- every new line round-trips through `reviews.jsonl` and is refused from the CLI and from any agent;
- sealing true over a three-node chain records one line, reads all three sealed, and unsealing releases all three;
- a changed version reads unverified with no action.

Local inventory: `human-operations.tsv` op_disposition=改为 (3 keys, 8 rows); `new-operations.tsv` (8 actions, 5 take effect only on a click); `core-concepts.tsv` concept 16 (14 values) and concept 3 (5 values).
Blocked by: C1, C2

### C5 · Remove Lightweight re-review, Dependent migration and Evidence review (ADR-0025)

Part of T0.
- Delete the three operations, the pin-lag reading behind Potentially stale, and Unverifiable. Their old records stay as history; nothing reads them.
- A dependency that moved or changed reads through C1 (the dependent's Proof layer and conclusion), not through a separate revalidation.

Acceptance criteria:
- no command, service function or gate for the three operations remains; their error codes are unregistered;
- an existing project with such records loads and shows them in history only.

Local inventory: `human-operations.tsv` op_disposition=删除 (3 keys, 5 rows); `gates.tsv` layer=core family=deleted-operation (10); `core-concepts.tsv` concepts 18, 19, 23 (11 values, 7 deleted).
Blocked by: C4

### C6 · Uses of dependencies, the node's assumptions and the version diff in core checks (ADR-0025, from #256, #261, #264, #266)

Part of T0.
- The mechanical check reads the `Uses of dependencies` section of `proof.tex`: one `depuse` entry per dependency, each application with Substitution, Premises, Conclusion and Constants; it checks structure and coverage only. Recording a verdict re-checks coverage against the same `proof.tex`. Without a covering section, Proof layer cannot reach checks passed.
- The node's own assumptions go into the scaffolded `proof.tex` and the mechanical check.
- The check marks other nodes' ids found in a statement, as a hint for the Verifier; it blocks nothing.
- What changed between two versions is computed from the two snapshots, never declared.

Acceptance criteria:
- a synthetic proof missing one dependency's entry fails the check and cannot record a passing verdict; adding it passes;
- a statement naming another node's id is flagged and still accepted;
- the diff between two synthetic snapshots names the changed parts.

Local inventory: `other-values.tsv` concepts 46 and 52 (2 values).
Blocked by: C3

### C7 · Existing projects switch to the five states once, on first open (ADR-0025, from #259)

Part of T0.
- On first open, in the one-shot pattern core already uses (a `project_meta` flag set in the same transaction, like the review-history and side-document migrations), convert by the rules of #259: Accepted, Reference-reviewed and Trust-rule-covered → expert-verified (read, `reviews.jsonl` not rewritten), nothing sealed; Rejected with nothing resting on it → history, otherwise a researcher Challenge carrying the original reason; open Challenges → Challenges of the same raiser, text kept, kind left for the Coordinator (C2's stop applies until classified); no longer callable → sealed false; passing verdicts from before → do not count, Proof layer incomplete; old objections go into the briefing as text, not gated.
- Before converting, keep one copy of the database; afterwards write one work-log entry with what changed and how many. Runs from before the switch read as interrupted, assignees released, drafts and work log kept.
- No dedicated migration flow and no confirmation step.

Acceptance criteria:
- a synthetic old project with each case converts as listed, once; a second open changes nothing;
- the copy exists and the entry's counts match the conversions.

Local inventory: `core-concepts.tsv` concepts 2, 3, 21 (lands_in column).
Blocked by: C2, C3, C4, C5

### C8 · Core gates read only the five states, and core names mean one thing (ADR-0025 checks 1 and 3)

Part of T0.
- Every remaining core gate reads only the five states and values computed from them, parses no descriptive text, and its error code says which error it prevents.
- Node and text authorship, read by several gates, is treated as structure, like node kind.
- CLI output, error codes and JSON keys use the CONTEXT.md names; the clashing names with core surfaces are renamed.
- The 7 one-ending-per-record gates are kept (they read run records and prevent a double ending).

Acceptance criteria:
- `count.py` over a refreshed inventory shows no core violation in family=other;
- no CLI output uses a name CONTEXT.md lists under _Avoid_.

Local inventory: `gates.tsv` layer=core family=other (21: 19 read a non-state value, 1 reads text, 3 name no error); `names.tsv` survives=yes with a CLI, reviews.jsonl or CONTEXT.md surface (13).
Blocked by: C4, C5, C7

### C9 · One fact in one place in core state (ADR-0025 check 2)

Part of T0.
- Stop writing stored copies of what can be computed: fields whose disposition is computed or deleted are no longer written; fields moved out of proof state leave it.
- For each duplicated fact, one carrier is the source and readers read it; a record keeps only what happened.
- Each fact computed in two places is computed once in core, and the other side calls it.

Acceptance criteria:
- `count.py` shows no stored-but-derivable field with disposition computed or deleted, and every fact_key with one writer;
- the computed-twice pairs that involve core are down to one computation each.

Local inventory: `fields.tsv` stored_but_derivable=yes (123: 88 records, 16 deleted, 13 moved out, 6 computed) and duplicate=yes (148 over 50 fact_keys); `computed-twice.tsv` rows naming proof-cli (11 of 28).
Blocked by: C1, C5

---

## Agents (zeqome/proof-agents)

### A1 · Runs expose only the run state; the rest is records or computed (ADR-0025)

Private: zeqome/proof-agents#46 (https://github.com/zeqome/proof-agents/issues/46). The body is kept in that issue.

### A2 · The Coordinator is always listening and is the one parser of the researcher's words (ADR-0025, from #271, #273)

Private: zeqome/proof-agents#47 (https://github.com/zeqome/proof-agents/issues/47). The body is kept in that issue.

### A3 · Prover and Verifier work to the new proof rules (ADR-0025, from #255, #256, #258, #261, #264, #266)

Private: zeqome/proof-agents#48 (https://github.com/zeqome/proof-agents/issues/48). The body is kept in that issue.

### A4 · A statement challenged as false is checked from both sides (ADR-0025, from #257, #269)

Private: zeqome/proof-agents#49 (https://github.com/zeqome/proof-agents/issues/49). The body is kept in that issue.

### A5 · Agent gates read only the five states, one computation per fact, one name per thing (ADR-0025 checks 1–3)

Private: zeqome/proof-agents#50 (https://github.com/zeqome/proof-agents/issues/50). The body is kept in that issue.

---

## Web (zeqome/proof-web)

### W1 · Every page shows the five states and the conclusion, the same everywhere (ADR-0025)

Private: zeqome/proof-web#45 (https://github.com/zeqome/proof-web/issues/45). The body is kept in that issue.

### W2 · The researcher verifies, seals and unseals with one click, after the list (ADR-0025, from #271)

Private: zeqome/proof-web#46 (https://github.com/zeqome/proof-web/issues/46). The body is kept in that issue.

### W3 · One input box talks to the Coordinator (ADR-0025, from #273)

Private: zeqome/proof-web#47 (https://github.com/zeqome/proof-web/issues/47). The body is kept in that issue.

### W4 · Pages drop the deleted operations; web gates and names follow the checks (ADR-0025 checks 1–3)

Private: zeqome/proof-web#48 (https://github.com/zeqome/proof-web/issues/48). The body is kept in that issue.
