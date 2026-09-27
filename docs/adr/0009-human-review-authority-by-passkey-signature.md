# Human Review authority is a passkey signature issued from the web app

**Status**: accepted (supersedes the "Human-only operations" bullet of ADR-0007; refines ADR-0004 Invariant 1 and ADR-0006 point 12)

A post-#31 audit (issue #32) showed that ADR-0004's Human Acceptance Authority was only a promise. Every human-only operation was gated by a boolean `confirmed=True` (CLI `--confirm`) and a self-declared `--reviewer` name. An agent with shell access could pass both, and did: an agent accepted its own Candidate proof. The service layer had no way to tell who was calling. ADR-0007 made this worse by listing the CLI's `confirmed=True` pattern as an acceptable human confirmation.

Options considered:

- Convention plus cheap guards, such as reviewer ≠ submitter. Rejected: nothing stops an agent that misbehaves.
- An interactive TTY retype-to-confirm. Rejected: it adds too much friction for the researcher on every decision.
- A human-held secret whose signature the service layer verifies.
- A human-only surface, the web app.

Decided: combine the last two.

1. **A Human Review decision is a signed record.** Only a decision signed by an enrolled reviewer passkey counts. A passkey is a WebAuthn credential with user verification: Touch ID, Windows Hello, or a security key. The signature covers a canonical payload:
   - the project id
   - the decision kind (`acceptance`, `reference_review`, `evidence_review`, `dependency_revalidation`, `challenge_resolution`, `promote`, `force_release`, `reviewer_enrollment`)
   - the target object id
   - the Candidate proof id together with the SHA-256 of its vault file content, so the decision binds to the exact text the researcher read
   - the dependency pins the decision is made against
   - the decision value and the rationale
   - a timestamp
   - the hash of the previous review-history row, which makes the history a hash chain
2. **Verification happens in the service layer, on read.** `get_acceptance_state` and every other derived axis count only records whose signature verifies against an enrolled reviewer key. Unsigned, invalid, or foreign-key records never grant, revoke, or resolve anything. They are surfaced as an integrity warning ("unverifiable review record"), never silently dropped. No service function takes a `confirmed` boolean any more. Human-only operations take a signed decision, and those calls fail without one.
3. **The web app is the only surface that issues signed decisions.** This is the first slice of the ADR-0007/0008 web app. A local server bound to `127.0.0.1` shows exactly what is being decided: the Candidate proof text, its dependencies and pins, its Evidence checks, and any open Challenges. The researcher confirms with one passkey tap. Several pending decisions can be signed in one batch with one tap, so reviewing ten nodes does not mean ten prompts. The server holds no authority of its own. A request to it without a fresh passkey assertion produces nothing. An agent that `curl`s the server is therefore no better off than one that calls the CLI.
4. **The CLI and agent adapters can only request.** Human-only CLI commands lose `--confirm`. They return `HUMAN_REVIEW_REQUIRED` with the URL of the decision page. `proof review open <node>` opens the page in the browser. Claim, submit, split, opening a Challenge, recording an Evidence check, and requesting review stay agent-reachable, unchanged.
5. **Reviewer enrollment is itself a signed decision.** The first passkey is enrolled on first use, from the web app, and the web app shows its fingerprint prominently. Every later enrollment or revocation must be signed by an already-enrolled key. The registry is append-only and lives in the project database. Its first key's fingerprint is also recorded in the researcher's user-level config. A project whose registry does not match that config is flagged, not trusted.
6. **Exchange carries signatures, never authority.** An imported bundle's review records keep their signatures. A signature from a key not enrolled in the receiving project is shown as a *foreign attestation* next to the node, and the node's local acceptance stays `unreviewed`. The receiving researcher can accept it with one tap, or deliberately enroll the other reviewer's key.
7. **Legacy unsigned decisions do not count.** Projects that predate this ADR show their past decisions as "unsigned legacy decision, re-sign to keep". The web app offers a batch re-sign page, so migration costs one tap per batch.

Threat model, stated honestly: agents run as the same OS user as the researcher. They can read and write the project files, but cannot produce a passkey assertion, because the private key sits in the Secure Enclave, a TPM, or a security key and needs user presence. So no agent-reachable path, whether the CLI, an adapter, an HTTP call, or an exchange import, can produce a decision that counts. What an agent *can* do is tamper with or delete files. Signatures and the hash chain make that detectable, but cannot prevent it. The two remaining weak spots are:

- An agent that initializes a project and enrolls its own software authenticator before the researcher does. The user-level fingerprint pin and the enrollment banner exist to surface this.
- Wholesale deletion of history, which git and backups cover.

What this costs: human-only decisions are impossible without a browser and an authenticator. Headless or remote-only use (e.g. over SSH) needs a security key or passkey on the machine where the browser runs. A passphrase-protected software key for headless machines is a possible later addition, and would need its own ADR.

This is hard to reverse: once review history is a signed hash chain and agents are built against "request, never decide", going back to a trust-me flag would silently re-open the hole this ADR closes.

**Update (issue #35, service layer):** the implementation settled a few details this ADR left open, and the audit on #35 tightened several of them.

- **What a signature binds.** Besides this ADR's point 1 fields, every payload carries:
  - the project's random **instance id**. It is generated when the project is created and never carried by exchange, so a decision signed for any other project never verifies, even one with the same display id. It also seeds both hash chains' genesis.
  - the node's accepted **interface**: `interface_fingerprint(statement, assumptions)` for a local node, or statement and source for an imported result.
  - the **Challenges** an Acceptance or Reference review resolves, by id.
  - for enrollment, the **credential id**.

  A timestamp without a timezone is refused when the payload is parsed.
- **Batch signing.** A passkey signs one challenge: the SHA-256 of the ordered list of payload hashes. So N decisions cost one tap, and a single decision is a batch of one.
- **Chain prefixes.** A payload commits to the newest row it saw in each of the three chains:
  - `previous_row_hash` for the review history;
  - `registry_head` for the Reviewer key registry;
  - `ledger_head` for the proof ledger.

  If a row an anchored prefix contains is deleted or edited, every decision that committed past it stops verifying.
- **What counts on read.** Only the **newest** decision on an object and kind is ever read. If it doesn't verify, the axis reads `unverifiable`. It never falls back to an older decision. A decision verifies when all of these hold:
  - its signature verifies under a key active in the registry prefix the payload committed to. Validity is a matter of chain position, never of a timestamp: a revocation appended later, however it is dated, can't reach back over a decision signed before it.
  - the row is exactly what was signed: kind, target, decision value, rationale, and the reviewer as `passkey:<fingerprint>`;
  - the prefix it commits to is still in the chain and already holds every earlier decision on the same object and kind. This is what stops replays.

  An Acceptance also counts only while it still describes its node:
  - its Candidate proof is this node's, with the text still hashing to the signed value;
  - the node still asserts the signed interface;
  - the node's dependency list is exactly the one its signed pins cover.

  That accepted proof may be an earlier version while a newer submission awaits review; the workflow axis then reads `review-needed`.
- **Reject is terminal however it is recorded.** Any Reject row keeps the node `rejected`. That includes an unsigned legacy one, one whose signature stopped verifying, and one whose proof text was edited since. At worst a forged Reject is denial of service, never an escalation, and it is flagged `UNSIGNED_LEGACY_REJECT`.
- **Records outside the signed rows are checked against them.** Promotes and revalidations are signed rows, so the service layer refuses any trust-bearing review without a signature that verifies.
  - **Kind** is the kind the node was created as (a chained `proof_ledger` entry), plus verified signed promotes. The `kind` column is advisory. A pre-#35 project's nodes and Challenges are adopted into the ledger once, at first open, with their stored kind and status. After that, a node or Challenge without a ledger entry is flagged (`NODE_NOT_IN_LEDGER`, `CHALLENGE_NOT_IN_LEDGER`) rather than read as legacy, and such a Challenge counts as open.
  - **Pins** of an Accepted node are the ones its counted Acceptance signed, as refreshed by later verified revalidations.
  - **Challenges** exist because the ledger recorded their opening, and are resolved only by a verified signed decision that names them. The `challenges` table is advisory, and deleting a row doesn't remove the Challenge.
  - **Workflow currency** follows the signed `candidate_proof_id`, never the `review_record_id` column.

  A disagreement with the signed record is surfaced as a warning (`KIND_MISMATCH`, `DEPENDENCY_PIN_MISMATCH`, `CHALLENGE_TABLE_MISMATCH`) and changes no axis.
- **Warning codes for records that don't count.** `UNSIGNED_DECISION` marks a trust-bearing row with no signature at all: legacy, or appended behind the service's back. `UNVERIFIABLE_REVIEW_RECORD` marks one whose signature is there but doesn't verify. `DECISION_NO_LONGER_APPLIES` marks a verified decision that no longer describes its node.
- **The registry and its anchor.**
  - **Trust on first use** applies only to a project that has never had keys: no registry rows, no pin, and no signed decisions in its history.
  - **Enrollment and fingerprints.** Fingerprints are unique. An enrollment binds its credential id, and a replayed registry payload is refused.
  - **Timing.** Enrollments and revocations take effect at their position in the registry chain, never at a timestamp. A key signing a registry row must be active in the prefix before it. The last active key can't be revoked.
  - **The pin** in the user-level config holds the first key's fingerprint, the project instance, and the newest row of each chain this machine has seen. The registry head is written on every enrollment and revocation. The review-history and ledger heads are written, best-effort, after every signed decision and ledger append. A head that isn't advanced (for example because the agent's sandbox can't write the pin file) is only an older lower bound, never a false alarm.
  - **When the registry isn't trusted:** the pin is missing, unreadable or mismatched; the registry was emptied; or a pinned head is gone from its chain (`HISTORY_TRUNCATED`: the newest rows were deleted, such as a revocation, a Reject, or a Challenge's opening). No decision then counts, and trust on first use is not re-run.
  - **Bad rows never crash a read.** A malformed registry or history row is simply not honoured, and is surfaced.
- **No CLI path enrolls a key.** Enrollment happens only in the web app's WebAuthn registration ceremony (#36). Human-only CLI commands accept `--signed-decision FILE` (a payload from `proof review payload` plus an assertion); without one they fail `HUMAN_REVIEW_REQUIRED`. Until #36 lands no researcher can enroll a key, which is why #35, #36 and the legacy re-sign step (#42) land together.
- **Legacy projects (point 7).** A pre-ADR-0009 node or Challenge has no ledger entry: its stored kind stands, and a stored dismissal keeps its Challenge closed, flagged `UNSIGNED_LEGACY_DISMISSAL`. Unsigned legacy approvals read `unverifiable`, and such a node can't be reclaimed until it is re-signed (#42). A legacy Reject stays terminal. Nothing in a migrated project is reopened.

**Protecting the anchor.** The pin file is the one thing a same-user agent must not be able to write. Keep `~/.config/proof-cli/` (or `$PROOF_CLI_CONFIG_HOME`) outside the agent's writable sandbox, for example by denying writes to it in Claude Code's sandbox settings. That is the only real barrier: macOS iCloud-Keychain passkeys return `none` attestation, so the service can't tell a real passkey from a software key presented by an agent. The first enrollment can be made observable, not impossible.

**Researcher recovery.** If a project reads untrusted (`REVIEWER_PIN_MISSING`, `REVIEWER_REGISTRY_MISMATCH`, `REVIEWER_REGISTRY_TRUNCATED`, `REVIEWER_REGISTRY_EMPTIED`), recover by hand, at the machine:
1. Run `proof review warnings` and `proof reviewer list`, and compare the listed fingerprints with the key your web app shows when you sign.
2. If the registry is genuinely yours, for example after moving or cloning the project, add or correct the project's entry in `reviewer-pins.json`: its absolute path, then `first_key_fingerprint`, `project_instance` and `registry_head`.
3. If it is not yours, or you can't tell, restore the project's `.proof/` from git or a backup taken before the problem. Then re-pin as above.

Nothing automates these steps. They are what re-anchors trust, so they must stay a deliberate human act.

**Known limits.**
- A compromised but not yet revoked key can sign whatever it likes. After revocation, it can still date a decision to before the revocation.
- Deleting the newest rows is detected only as far as this machine's pin has advanced. Rows appended by a process that couldn't write the pin file, and not yet covered by a later signed decision, can be removed without trace.
- A copy of a project shares its instance id, so decisions carry over to the copy. That is intended.
- Claim ownership is still self-declared (`claimant_id`/`session_id`); #37 covers this.
- Integrity warnings are surfaced by `proof review warnings`; showing them next to each node is #36.
- The legacy theorem-contract and reference trust functions in `review.py`/`storage.py` still take `confirmed`; #37 removes them.
