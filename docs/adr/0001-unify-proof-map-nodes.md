# Unify proof map nodes into one entity with a `kind` field

**Status**: accepted

The Proof Wayfinder redesign needs a single dependency graph — Theorem, Lemma, Claim, and Imported result all need to sit on equal footing so that frontier, claim, submit, review, and accept can operate uniformly across the whole map. The existing model splits this across two structures: `TheoremContract` (with a `kind` of theorem/lemma/proposition/corollary/result) and `ProofObligation` (a separate, more lightweight obligation record linked back to a contract via `required_for`), plus a free-floating `ProjectState.open_goals` string list with no identity or status of its own.

We considered keeping that split — Lemma/Theorem on `TheoremContract`, Claim on `ProofObligation`, connected by dependency edges — but rejected it: any operation that should treat all proof map nodes the same way (frontier selection, candidate-proof submission, review, promote) would need parallel implementations for both structures, and the two would drift.

Decided instead: one **proof map node** entity, shared by all four kinds. `kind` is narrowed to the three values that drive real state-machine behavior (`theorem`, `lemma`, `claim`) plus `imported_result`; the former `proposition`/`corollary`/`result` values become a free-text display label, since they only affect how a result is described in writing, not how the system treats it. `ProofObligation` is absorbed into the `claim` kind; `open_goals` is retired (a goal becomes a Claim node once it has a precise statement, or stays proof fog otherwise — fog's representation is out of scope for this decision). `BlockerRecord` is unaffected: it remains an annotation attached to a node, not a node itself.

This is hard to reverse once proof map nodes exist in `.proof/project.sqlite3` and are referenced by id from candidate proofs, review records, and dependency edges — splitting them back apart later would require a real migration. See `CONTEXT.md` for the resulting glossary (Proof map node, Theorem, Lemma, Claim, Imported result, Promote, Reference review).
