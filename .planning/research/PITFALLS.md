# Pitfalls Research

**Domain:** Research mathematics CLI / proof workflow OS
**Researched:** 2026-04-21
**Confidence:** MEDIUM

## Critical Pitfalls

### Pitfall 1: Treating summaries as proof objects

**What goes wrong:**
The system starts accepting high-level summaries as if they were reusable mathematical results.

**Why it happens:**
Summaries are easier to generate than explicit contracts, so the implementation drifts toward convenience.

**How to avoid:**
Make theorem contracts the primary object and require assumptions, exports, and dependencies for reuse.

**Warning signs:**
Users can reuse results without seeing the contract metadata or dependency chain.

**Phase to address:**
Phase 2

---

### Pitfall 2: Hiding proof obligations behind "standard step" language

**What goes wrong:**
Compressed proof prose creates missing obligations that are never checked.

**Why it happens:**
It is tempting to optimize for readability before the elaboration rules are complete.

**How to avoid:**
Force every omitted step to become an explicit obligation that the checker stack can see.

**Warning signs:**
"Obvious" or "standard" steps are accepted without traceable validation.

**Phase to address:**
Phase 3

---

### Pitfall 3: Building a memory layer that only stores text

**What goes wrong:**
The system remembers notes, but not active goals, blockers, or callability constraints.

**Why it happens:**
Text storage is much easier than state modeling, so the implementation stops too early.

**How to avoid:**
Separate working memory, semantic memory, episodic memory, and project snapshots.

**Warning signs:**
Recovery after a restart cannot tell you what remains open or why a result is blocked.

**Phase to address:**
Phase 1

---

### Pitfall 4: Importing external results without a trust workflow

**What goes wrong:**
Foreign results enter the project as if they were already verified locally.

**Why it happens:**
Import flow is often treated as a convenience feature instead of a trust boundary.

**How to avoid:**
Require source metadata and an explicit approval or downgrade step for imports.

**Warning signs:**
Imported results can be called without showing trust level or source history.

**Phase to address:**
Phase 5

---

### Pitfall 5: Replacing the CLI with a browser too early

**What goes wrong:**
The project spends effort on UI polish before the proof workflow is trustworthy.

**Why it happens:**
Browser interfaces feel approachable, but they are not the core requirement here.

**How to avoid:**
Keep the first release CLI-first and defer browser tooling until the proof workflow is stable.

**Warning signs:**
The roadmap starts allocating major effort to dashboards before the state model is complete.

**Phase to address:**
Phase 4

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Plain-text notes for theorem state | Fast to ship | Breaks trust boundaries and recovery | Never |
| One big summary file for all memory | Easy to inspect initially | Loses structure and history | Never |
| No explicit import trust levels | Lower friction | Hidden provenance risk | Never |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| External theorem sources | Importing results without source metadata | Store source, trust level, and assumptions together |
| Proof script elaboration | Translating prose without emitting obligations | Emit explicit obligations before validation |
| Search workflows | Searching outside the project first | Check current project state and registry first |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Recomputing the whole dependency graph on every command | Slow CLI responses | Cache projections and update incrementally | Medium-sized projects |
| Searching every memory layer on every query | Laggy retrieval | Use layered retrieval and targeted queries | Large proof archives |
| Revalidating unchanged contracts repeatedly | Wasted compute | Track dirty state and stable snapshots | Repeated sessions |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Trusting imported results blindly | Invalid proof reuse | Require explicit trust levels and human approval |
| Letting external artifacts mutate state implicitly | State corruption | Keep imports and state updates explicit |
| Treating generated text as verified math | False confidence | Separate generation from validation |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Too much hidden automation | Users cannot tell what changed | Show state transitions and obligations explicitly |
| No visible blocker log | Users do not know what to fix next | Keep blockers surfaced in the primary CLI flow |
| Overly chatty outputs | Important proof failures get buried | Favor concise, structured status messages |

## "Looks Done But Isn't" Checklist

- [ ] Theorem registry: often missing dependency metadata - verify callability and exports
- [ ] Proof elaboration: often missing explicit obligations - verify omissions become checkable steps
- [ ] Memory: often missing restart recovery - verify goals and blockers survive a new session
- [ ] Import workflow: often missing trust levels - verify sources cannot be reused silently

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Summary-only memory | HIGH | Rebuild structured state from remaining artifacts and add snapshots |
| Hidden obligations | HIGH | Re-run elaboration on affected scripts and patch checkers |
| Blind imports | MEDIUM | Reclassify imported results and force human review before reuse |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Summary-only memory | Phase 1 | Restart the CLI and confirm state is restored |
| Hidden obligations | Phase 3 | Run a compressed proof script and verify obligations appear |
| Blind imports | Phase 5 | Import a result and confirm approval is required |
| CLI replaced too early | Phase 4 | Confirm the roadmap still keeps the terminal experience primary |

## Sources

- Project proposal in `mathematical_proof_cli_project_plan.md`
- Common failures in proof tooling and local-first knowledge systems

---
*Pitfalls research for: Research mathematics CLI / proof workflow OS*
*Researched: 2026-04-21*
