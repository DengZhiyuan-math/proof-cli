# A node's proof may be a computation: the Medium of a node

**Status**: accepted (decided in #141, #142, #143; landed with PR #146, part 1 of spec #145). Amends ADR-0010 point 1 (a node's proof is a standalone LaTeX document) and ADR-0011 (a local node's computation lives in `scratch/`, never frozen).

## Context

Some nodes are established by a computation — a case-by-case check, an enumeration, a formal verification, a simulation — not by a written argument. proof-cli gave every local node a `proof.tex`, so such work had nowhere to live and no way to be reviewed: ADR-0011 let an agent keep scripts and their output in `scratch/`, which a Review snapshot never freezes. The researcher asked that these nodes stay ordinary nodes of the map.

## Decision

1. **Medium is a node attribute, not a kind.** `medium: latex | computation` on a Theorem, Lemma or Claim (default `latex`; a node recorded before the field reads `latex`). An Imported result has none: every write path refuses one on it (`MEDIUM_NOT_APPLICABLE`) — `node create`, `node medium set` and exchange import alike. It says what the Candidate proof is made of. The state machine, Acceptance and the Accepted mathematical interface do not depend on it, and it may be changed at any time (`node medium set`): files stay, the missing entry is scaffolded, an Acceptance stands.
2. **A computation node's proof is its program.** `run.sh` is the entry, `out/` holds what it writes. The researcher's Acceptance judges whether what was frozen establishes the statement, as it always did.
3. **A computation's Review snapshot freezes its inputs and its outputs, and tells them apart** (the researcher's rule, 2026-10-02). Its *inputs* are its scripts, its data and its hidden environment files at the node root (`.python-version`, `.envrc`, `.tool-versions`, …), each script with its executable bit; its *outputs* are `out/`. Never frozen, for either medium: `scratch/`, `build/`, hidden folders (`.git`, `.venv`, `.pytest_cache`, …), `__pycache__` and `*.pyc` anywhere. A computation does not freeze the shared `../preamble.tex`: its program doesn't read it, so a preamble edit is no new program version. A file the snapshot would freeze that can't be read is refused (`WORKING_FILE_UNREADABLE`) and nothing is written.
   - The manifest (format 2) records which frozen files are executable, and the snapshot's hash covers it; a snapshot with none — every LaTeX one, every format-1 one — is hashed exactly as before, so existing snapshots still verify.
   - `vault.frozen_role(path)` says whether a frozen path is an input or an output; `frozen_inputs_digest(snapshot)` and `working_inputs_digest(root, node, medium)` hash the inputs alone.
4. **A large `out/` is a notice, never a refusal.** Requesting review returns `SNAPSHOT_LARGE_OUTPUT` (registered in `errors.NOTICE_CODES`, under `data.notices`) when the snapshot froze more of `out/` than `proof.toml`'s `[snapshot] large_output_mb` (default 50): big data is the researcher's `.gitignore`.

## Consequences

- `node create --medium`, `node medium set`, `--medium` on `fog crystallize`; `medium` in every node view and `--json`, and in exchange bundles (which carry a computation's environment files and executable bits); the sample fixture gains a computation claim.
- The key-ideas summary keeps its four headings and its requirement (#103) for both media; its skeleton for a computation hints at what each holds. Request review, snapshots and every Review decision work as before.
- ADR-0011's "scripts and their output in `scratch/`" remains true of a LaTeX node's working computation; a computation node's program is its candidate proof and is frozen.
- Reversing this means removing one field; nothing in the trust model would have to be undone.

## Not yet (later parts of spec #145)

- **Run, as Evidence** (#147): the studio's Run runs `./run.sh` and records an Evidence check — exit 0 `passed`, otherwise `failed`, a run that could not start `error`; `inconclusive` is a human's or an agent's to record. A Run counts as Evidence on a snapshot only when its inputs match the frozen ones (`working_inputs_digest` equals `frozen_inputs_digest`); `out/` may differ.
- **Showing frozen outputs** (#147): the node page and review page list a snapshot's `out/` artefacts, with image previews.
- **The studio's computation mode** and the Numerics role (#147 onward): Open in VS Code, the Files view, the agent-first work log of #144.
