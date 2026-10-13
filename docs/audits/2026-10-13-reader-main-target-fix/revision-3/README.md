# Revision 3 offline evidence

This record follows the second audit of Draft PRs [agents #30](https://github.com/zeqome/proof-agents/pull/30), [core #220](https://github.com/DengZhiyuan-math/proof-cli/pull/220) and [web #25](https://github.com/zeqome/proof-web/pull/25). Prior evidence is retained unchanged. The first #197 run remains failed and does not enter Human Review or macOS maturity.

Ask with an agent name and no role cannot confirm a summary for its author. Agent/gated requests distinguish recorded drafts, changed drafts and unknown authorship. Review-now explicitly freezes without confirmation. Parsed CLI guards allow scoped Prover/Decomposer literature imports only under their current node. Accepted ADR-0021 text is retained; corrections are separately proposed in ADR-0023.

`offline-verification.json` records the release base, candidate parent, cumulative source hashes, loaded package locations relative to the development clone, commands, distinct counts, wheel digest and lint comparison. `pytest.xml` is the full suite; other XML files cover affected cases and overlap. Local host/clone identifiers in new XML files are sanitized without changing results. Distinct: **1168 passed, 15 skipped, 0 failed**. The coupled three-repository totals are **2233 passed, 16 skipped**. Existing lint debt remains; no new diagnostics. Wheels and modified JavaScript syntax checks pass.

Offline tests use fake provider boundaries and fresh temporary projects. Retrieval checks cover instructions, permissions, real launch wiring and scripted CLI imports, not real-model search, source discovery, theorem matching or mathematical correctness. Structural coverage does not identify the main theorem. Full and affected-suite counts overlap and are deduplicated by classname/name.

The Reader and proof roles share unseeded retrieval instructions and existing native WebSearch/WebFetch or Codex search. Test sources are generic fixtures. No paper, author, URL, identifier or mathematical result was supplied to production instructions. A real rerun is required to assess autonomous search and Reader target recognition.

Core must be paired with agents and web changes: scoped node-creation permissions rely on core's parsed checks; web supplies coverage metadata and persists timeouts. Web #26's header count is outside this change. CI is distinct from coupled local validation; web CI packages wheels and checks syntax, without running this complete suite.

[Core revision-3 preservation evidence](https://github.com/DengZhiyuan-math/proof-cli/tree/D_m/reader-main-target/docs/audits/2026-10-13-reader-main-target-fix/revision-3) compares 134 captured files (130 run-related and 4 later diagnostic files) with the first-publication snapshot. Every byte hash matches; aggregate before/after: `12f3749b60e8fa08086b191003cca45aefbc14ce24188e93641df2dce9a9ee5e`. This is not a full run-start environment inventory. The existing verifier in `../revision-2/verify_preservation.py` recomputes the new manifest and optionally checks local trial bytes.

No new real Proof provider call, trial service update, pin change, merge, issue closure, or Acceptance was performed. #197 and #132 remain open. Semantic main-target correctness, mathematical correctness and macOS maturity still require the researcher's trial and decision.
