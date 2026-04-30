---
phase: 13-codex-e2e-validation
type: research
focus: codex-driven workflow validation, realistic theorem-cluster demo, usability evidence
date: 2026-04-30
---

# Phase 13 Research

## Research Question

How should the final validation prove that the hardened Codex-facing Proof CLI workflow is genuinely usable for ongoing proof work, rather than merely technically functional?

## Findings

### 1. The final proof point should be behavioral, not merely structural

Phases 10, 11, and 12 already demonstrated that:

- commands route correctly
- mutations go through the Proof CLI
- root resolution is explicit
- degraded states are diagnosed

So Phase 13 should not spend most of its energy re-proving those isolated facts. It should prove that the *whole workflow* feels coherent in actual use.

### 2. A realistic miniature theorem cluster is better than a toy proposition

The user explicitly prefers a validation slice closer to real research practice.

That means the final demo should likely include:

- a small theorem cluster rather than a single detached proposition
- at least one obligation
- at least one blocker
- a snapshot/handoff point

This keeps the validation aligned with what the system is for: stateful long-horizon proof work, not just command invocation.

### 3. Human-driven Codex use should be the primary artifact

Automated tests are still important for regression safety, but they are not the main evidence the user wants.

The primary validation artifact should therefore be a documented or scripted walkthrough of a real `$proof ...` / `proof codex ...` flow that shows:

- open or initialize workspace
- inspect current state
- create theorem
- create obligation
- create blocker
- snapshot state
- interpret readiness or root information when relevant

### 4. The validation must compare against the earlier experience implicitly or explicitly

The user wants a stronger success standard: not just "it works," but "it is now easier and less ambiguous."

So the validation should check:

- command discoverability
- reduced ambiguity around root selection and mutation intent
- reduced ambiguity around entrypoint choice
- smoother transition from "I want to prove something" to "I have structured state"

This can be shown through a before/after framing in the phase summary, even if the tests themselves only exercise the current implementation.

### 5. Phase 9 offers the right validation pattern to reuse

Phase 9 already established a useful pattern:

- validate on a bounded theorem cluster
- keep the structure realistic
- use workflow outputs to judge practical usefulness, not only serialization or storage

Phase 13 should reuse that pattern, but focus on the command surface rather than the retrieval/snapshot internals.

### 6. Final validation likely needs two complementary artifacts

The strongest plan is:

1. **interactive/user-facing validation artifact**
   - a realistic walkthrough or fixture that mirrors Codex usage

2. **supporting regression coverage**
   - smoke tests that exercise the same command-layer path in reproducible form

This pairing satisfies both product confidence and engineering repeatability.

## Recommendations

1. Build a realistic small theorem-cluster fixture specifically for Phase 13.
2. Validate the full wrapper workflow around that fixture, not just isolated commands.
3. Produce a summary that explicitly argues the new command surface is clearer and less ambiguous than before.
4. Keep `$proof ...` phrasing visible in the validation narrative even if the automated checks use `proof codex ...` directly under the hood.

## Planning Implications

- Phase 13 should include one task for the realistic validation fixture and walkthrough.
- It should include one task for end-to-end wrapper smoke/regression coverage.
- It should include one task for writing a strong validation summary that argues usability improvement, not just command correctness.
