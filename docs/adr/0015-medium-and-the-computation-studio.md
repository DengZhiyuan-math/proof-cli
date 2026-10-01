# A node's proof may be a computation: the Medium of a node, and its studio's computation mode

**Status**: accepted (decided in #141, #142, #143; the Medium landed with PR #146, the studio's computation mode follows in later parts of spec #145). Amends ADR-0010 point 1 (a node's proof is a standalone LaTeX document) and ADR-0011 (a local node's page is a LaTeX workspace; computation lives in `scratch/`). Rests on the agent-first studio decided in #144, recorded in its own ADR.

## Context

Some nodes are established by a computation — a case-by-case check, an enumeration, a formal verification, a simulation — not by a written argument. proof-cli gave every local node a `proof.tex` and a LaTeX studio, so such work had nowhere to live and no way to be reviewed: ADR-0011 let an agent keep scripts and their output in `scratch/`, which a Review snapshot never freezes. The researcher asked that these nodes open the computation in VS Code rather than a LaTeX editor, while staying ordinary nodes of the map.

## Decision

1. **Medium is a node attribute, not a kind.** `medium: latex | computation` on a Theorem, Lemma or Claim (default `latex`; never on an Imported result; a node recorded before the field reads `latex`). It says what the Candidate proof is made of. The state machine, Acceptance and the Accepted mathematical interface do not depend on it, and it may be changed at any time (`node medium set`): files stay, the missing entry is scaffolded, an Acceptance stands.
2. **A computation node's proof is its program.** `run.sh` is the entry, `out/` holds what it writes; the Review snapshot freezes the folder as for any node — the scripts, the environment files, `out/`, `key-ideas.md` — PDF and all optional, `scratch/` and `build/` excluded as before. The researcher's Acceptance judges whether what was frozen establishes the statement, as it always did. A large `out/` is a reminder at snapshot time, never a refusal: big data is the researcher's `.gitignore`.
3. **Each run is an Evidence check, never a decision.** Exit 0 reads `passed`, otherwise `failed`, a run that could not start `error`; `inconclusive` is a human's or an agent's to record. Runs may be concurrent.
4. **The studio has one shape for both media.** Its centre is the Proof agent's work log (the ADR of #144); the editor and the PDF, or the program and `out/`, are the Files view. A computation node's bar offers Run and Open in VS Code (`vscode://file/<folder>`, or a configured `[studio] open_command`); a LaTeX node's offers Compile.
5. **The Numerics role owns the computation.** On a computation node it produces the candidate proof; on a LaTeX node it supplies evidence to the Prover. Its write scope is the scripts, `run.sh` and `out/`, never the LaTeX.

## Consequences

- `node create --medium`, `node medium set`, `--medium` on `fog crystallize`; `medium` in every node view and `--json`; the sample fixture gains a computation claim.
- The key-ideas summary keeps its four headings for both media; its skeleton for a computation hints at what each holds. Request review, snapshots and every Review decision are untouched; the review page and node page learn to show frozen outputs.
- ADR-0011's "scripts and their output in `scratch/`" remains true of a LaTeX node's working computation; a computation node's program is its candidate proof and is frozen.
- Reversing this means removing one field and one studio mode; nothing in the trust model would have to be undone.
