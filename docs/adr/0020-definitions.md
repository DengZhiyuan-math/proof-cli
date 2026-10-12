# Definitions: the named text a statement is written in

**Status**: accepted (2026-10-06; the researcher's decision on the #132 tier 3 trial, option C). Amends ADR-0001 (a node's shape gains the definitions it names) and ADR-0005 (the Accepted mathematical interface includes them). ADR-0004, ADR-0010 and ADR-0011 point 5 stand: Definitions never decide anything, and a snapshot still freezes the proof, not the statement.

## Context

The #132 tier 3 trial put an open research note on the map: a stochastic model of synaptic release, reduced step by step. Every node's statement was unreadable. The Theorem crammed the model's setting, its symbols and three conclusions into one paragraph, and still left out what $a_n^-$, $K_n$, the conditioning or the left limits meant. Its four Claims each began "In the setting of MAIN", so none could be read alone. The agents filled the gaps themselves. MEAN's proof opens with "Conventions (reading of MAIN)", SITES's with "The hypotheses are read as follows", GATE's with "Reading of the hypothesis", and the Verifier checked each proof against its author's own reading. The researcher, who must judge every Acceptance, could not read what was being accepted.

A node had nowhere to put this text. The map holds results only (ADR-0001: theorem, lemma, claim, imported result), `assumptions` are short conditions, `preamble.tex` holds LaTeX macros, and a statement is fixed once the node exists, so a badly written one can only be replaced by a new node. Mathematics writes definitions, the setting of a model and notation once and then states results in their terms. The map had to be able to do the same without loosening what makes an Acceptance mean something: what a node says never changes under it.

## Decision

1. **A Definition** is a project's named piece of mathematical text: a definition, the setting of a model, notation. It has an id (`release-unit`), a term to show ("Stochastic release unit") and its text, Markdown with `$…$` maths as a statement is. It is kept in SQLite (`definitions`) and written through `proof definition add|edit|remove`. Its readers are `proof definition list|show`, `proof node show` and the pages.
2. **A node names the definitions its statement is written in, at creation, and the names are fixed.** `proof node create … --definition <id>` names one, repeatably, and every name must exist (DEFINITION_NOT_FOUND). The names never change afterwards, as the statement never does.
3. **A Claim is written in its parent's definitions.** A Split's children, a node created under a parent (`--parent`) and a Claim crystallized from fog under a parent name the parent's definitions, then any of their own (`--definition` with a single `--child`). A Claim of a Theorem is about the Theorem's objects; "in the setting of <node>" is what this replaces.
4. **A definition a node names is fixed.** It may be edited or removed only while no node names it (DEFINITION_IN_USE, which names the nodes). A corrected definition is a new one, under a new id, named by new nodes, the way a corrected imported result is a new node (ADR-0005). So no edit anywhere can change what an existing node says, Accepted or not.
5. **What a node says is its statement, its assumptions and the definitions it names.** They are its Accepted mathematical interface, so the interface fingerprint includes the definitions by id. A named definition can no longer change, so its id stands for its text. A node that names none has exactly the fingerprint it had before this decision, so no pin and no Acceptance moves.
6. **A snapshot still freezes the proof, not the statement.** Definitions are not copied into `snapshots/v<N>/` and are not in the manifest digest. They are as fixed on the record as the statement is, and the review page shows them from there. The verdict gate's digest, the request-review gate and Evidence bindings are unchanged. A new node's `proof.tex` opens with its definitions (a `Definitions` section of `\paragraph{<term>.} <text>`), so the document reads on its own and what a snapshot freezes includes them as the author wrote them.
7. **The agents read them.** Every turn's briefing gives the node's definitions in full before its statement. The Decomposer writes its Claims in the Theorem's definitions, so they read alone, and names a new one it needs for the researcher to add. Every role may read `proof definition list|show`; adding, editing and removing are the researcher's, like the statement of a node they create.
8. **They travel.** An exchange bundle carries the project's definitions. On import, one whose id is here must say the same (DEFINITION_CONFLICT), and every definition an imported node names must be in the bundle or here.

## Considered options

- **A free "definitions" document per project** (`proofs/definitions.md`, like the preamble). It is simple to write, but an edit would silently change what every Accepted node means, and nothing would record which node relies on which text.
- **A `definition` node kind.** A definition is not a result: it has no proof, no Acceptance, no frontier and no dependents in the sense of the map. Every graph operation would have to special-case it, which is the reason ADR-0008 kept fog out of the graph.
- **Versioned definitions, with nodes pinning a version.** This allows correcting a definition in place, with old nodes pinned to the old text. It costs a version history, a pin per node and definition, and a "your definition moved" state on every page. Fixed-once-named gives the same guarantee with none of that, at the price of a new id for a correction. That price is the one statements and imported results already pay.

## Consequences

- Statements can be short and readable. "For every $n$, $\mathbb E[K_n]=M u_n^- x_n^-$" makes sense once the release unit is defined beside it.
- An existing node keeps no definitions and reads as before. A project that wants them for existing work states new nodes in them, as a corrected statement always required.
- The proof map page shows a node's definitions on its page, in its studio's node panel and on its review page. The node form names them from a list. Those are proof-web's.
- The `proof-cli` skill tells agents to read a node's definitions before its statement.
