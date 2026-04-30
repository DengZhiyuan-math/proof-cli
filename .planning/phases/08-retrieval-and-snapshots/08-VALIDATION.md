---
phase: 8
slug: retrieval-and-snapshots
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-29
---

# Phase 8 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Quick run command** | `pytest tests/test_retrieval.py tests/test_proof_state.py tests/test_snapshot.py tests/test_exchange.py tests/test_cli.py -q` |
| **Full suite command** | `pytest tests/test_retrieval.py tests/test_proof_state.py tests/test_snapshot.py tests/test_exchange.py tests/test_cli.py -q` |

## Per-Task Verification Map

| Task ID | Requirement | Automated Command | Status |
|---------|-------------|-------------------|--------|
| 08-01 | PRET-01, PRET-02 | `pytest tests/test_retrieval.py tests/test_proof_state.py tests/test_snapshot.py tests/test_exchange.py tests/test_cli.py -q` | green |
| 08-02 | PRET-03, PSNP-01 | `pytest tests/test_retrieval.py tests/test_proof_state.py tests/test_snapshot.py tests/test_exchange.py tests/test_cli.py -q` | green |

## Validation Sign-Off

- Retrieval prioritized current theorem state, obligations, blockers, recent memory, and explicit neighborhood before loose matching.
- Project analysis produced machine-readable diagnostics with bottlenecks and next steps.
- Recovery snapshots preserved the latest diagnostic report and round-tripped through exchange bundles.
