# Feature Research

**Domain:** Research mathematics CLI / proof workflow OS
**Researched:** 2026-04-21
**Confidence:** MEDIUM

## Feature Landscape

### Table Stakes (Users Expect These)

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Persistent project state | Long proof work must survive context loss | HIGH | Needs explicit project memory, not just chat history |
| Theorem/lemma registry | Users need callable results with assumptions | HIGH | Core trust boundary of the product |
| Proof goal tracking | Users need to see open goals and obligations | MEDIUM | Should be visible from the CLI at all times |
| Dependency tracking | Proofs rely on prior results and assumptions | HIGH | Needed for callability and circularity checks |
| Import/source metadata | Users need to know where external claims came from | MEDIUM | Required for trust management |

### Differentiators (Competitive Advantage)

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Contract-based theorem calls | Lets users reuse results without reopening proof bodies | HIGH | Stronger than plain note-taking |
| Omission elaboration | Turns "standard steps" into checkable obligations | HIGH | Makes compressed proof writing safer |
| Retrieval-first workflow | Encourages reuse before new proof search | MEDIUM | Matches actual research practice |
| Human review gate for imported results | Keeps trust explicit instead of implicit | MEDIUM | Supports safer collaboration with agents |
| Multi-layer proof memory | Separates working, semantic, episodic, and procedural memory | HIGH | Better than a flat notes dump |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Fully automatic theorem proving | Sounds like the end goal | It hides uncertainty and breaks trust boundaries | Human-in-the-loop proof assistance |
| "Just a vector DB" memory | Easy to prototype | It cannot represent obligations or dependencies accurately | Structured proof state plus retrieval metadata |
| Browser-first product surface | Familiar UI pattern | It risks distracting from the core proof workflow | CLI-first with optional later console |
| Silent trust upgrades for imports | Convenient | It can smuggle in unjustified assumptions | Explicit approval or downgrade workflow |

## Feature Dependencies

```text
[Persistent project state]
    └──requires──> [Proof goal tracking]
                       └──requires──> [Dependency tracking]

[Theorem/lemma registry]
    └──requires──> [Import/source metadata]

[Contract-based theorem calls]
    └──requires──> [Theorem/lemma registry]
    └──requires──> [Dependency tracking]

[Omission elaboration]
    └──requires──> [Proof goal tracking]
    └──requires──> [Checker stack]

[Human review gate]
    ──supports──> [Imported results with trust levels]
```

### Dependency Notes

- Persistent project state needs proof goals and blockers so it can recover the current session accurately.
- Contract-based theorem calls only work if the registry knows assumptions, exports, and dependencies.
- Omission elaboration only makes sense if the checker stack can evaluate the resulting obligations.

## MVP Definition

### Launch With (v1)

- [ ] Persistent project state — without it, long proof work cannot resume
- [ ] Theorem/lemma registry — this is the trust boundary of the product
- [ ] Proof goal tracking — users must always know what remains open
- [ ] Dependency tracking — needed for safe theorem reuse
- [ ] Checker stack for assumptions, circularity, and export strength — prevents invalid proof calls

### Add After Validation (v1.x)

- [ ] Omission elaboration improvements — add once the basic checker path is working
- [ ] Better retrieval ranking — add after the core search loop is useful
- [ ] Richer memory taxonomy tooling — refine after observing actual project usage

### Future Consideration (v2+)

- [ ] Browser console — useful, but not required to validate the core workflow
- [ ] Automatic proof suggestion modes — defer until the trust model is stable
- [ ] Collaborative multi-user project sharing — only after the single-user workflow is solid

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Persistent project state | HIGH | HIGH | P1 |
| Theorem/lemma registry | HIGH | HIGH | P1 |
| Proof goal tracking | HIGH | MEDIUM | P1 |
| Dependency tracking | HIGH | HIGH | P1 |
| Omission elaboration | HIGH | HIGH | P2 |
| Browser console | MEDIUM | HIGH | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

## Competitor Feature Analysis

| Feature | Competitor A | Competitor B | Our Approach |
|---------|--------------|--------------|--------------|
| Proof state | Formal assistants expose proof context directly | General note tools do not | Use explicit, persistent proof state with obligations |
| Result reuse | Theorem provers rely on formal lemmas | Agents often summarize instead of contracting | Treat reusable results as contracts with trust levels |
| Error handling | Formal tools fail hard on invalid proof steps | Chat tools fail softly and ambiguously | Use actionable checker errors and blocker logs |

## Sources

- Project proposal in `mathematical_proof_cli_project_plan.md`
- Common patterns from research workflow tools and theorem-management systems

---
*Feature research for: Research mathematics CLI / proof workflow OS*
*Researched: 2026-04-21*
