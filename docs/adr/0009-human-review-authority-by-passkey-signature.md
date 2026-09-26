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

**Update (issue #35, service layer):** the implementation settled a few details this ADR left open.

- **Batch signing.** A passkey signs one challenge: the SHA-256 of the ordered list of payload hashes. So a batch of N decisions costs one tap, and a single decision is a batch of one. `previous_row_hash` in a payload is the history head the signer saw. It commits the payload to that prefix of the chain; it is not the row's own chain link, which `review_history.prev_row_hash` stores.
- **What makes a decision count on read.** The signature verifies under a registry key that was active at the payload's `signed_at`. The payload is exactly the recorded row: kind, target and decision value. The prefix it commits to is still in the chain. That prefix already contains every earlier decision on the same object and kind; anyone can append a validly-linked row, so this rule is what stops a replayed or reordered decision. A decision about a Candidate proof also needs the proof's text on disk to still hash to the signed value.
- **Trust on first use** applies only while no key has *ever* been enrolled. A self-signed enrollment therefore can't be backdated in ahead of the researcher's key. The user-level pin is keyed by the project's location on disk, not its id, because many projects share the default id. A registry whose first key disagrees with the pin is not trusted at all.
- **Interim CLI, until #36/#37.** Human-only commands take `--signed-decision FILE`: the payload from `proof review payload` plus a WebAuthn assertion over it. Without one, they fail with `HUMAN_REVIEW_REQUIRED`. `--confirm` is gone. The signature carries the authority, not the surface, so submitting through the CLI grants an agent nothing. The legacy theorem-contract and reference trust functions in `review.py` and `storage.py` still take `confirmed`; #37 removes them.
- **Identity.** A decision is attributed to `passkey:<first 16 hex of the key fingerprint>`, never to the self-declared display name. A row's recorded rationale and reviewer must equal what was signed, or the row doesn't verify.
- **Challenge resolution.** A stored dismissal counts only if the signed decision it points at is about that Challenge: a `challenge_resolution` on its id, or an Acceptance / Reference review of its target made after it was opened.
- **Known limits.**
  - Revocation relies on the signer's own `signed_at`, so a compromised key can still backdate decisions to before its revocation.
  - Deleting the newest history rows can't be detected from the chain.
  - Tables outside the two chains, such as `dependency_pins` and node `kind`, are protected only by the service layer: a promote or revalidation is signature-gated when it happens, but not re-verified on read.
  - Claim ownership is still self-declared (`claimant_id`/`session_id`), so an agent can release another claim "as its owner"; #37 covers this.
  - Integrity warnings are surfaced by `proof review warnings`, not yet next to each node; #36 shows them in the web app.
