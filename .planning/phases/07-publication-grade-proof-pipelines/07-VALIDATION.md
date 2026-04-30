---
phase: 7
slug: publication-grade-proof-pipelines
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-04-29
---

# Phase 7 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Quick run command** | `pytest tests/test_publication.py tests/test_export.py tests/test_exchange.py tests/test_cli.py -q` |
| **Full suite command** | `pytest tests/test_publication.py tests/test_export.py tests/test_exchange.py tests/test_cli.py -q` |

## Per-Task Verification Map

| Task ID | Requirement | Automated Command | Status |
|---------|-------------|-------------------|--------|
| 07-01 | PUB-01..PUB-07 | `pytest tests/test_publication.py tests/test_export.py tests/test_exchange.py tests/test_cli.py -q` | green |
| 07-02 | PUB-08..PUB-10 | `pytest tests/test_publication.py tests/test_export.py tests/test_exchange.py tests/test_cli.py -q` | green |

## Validation Sign-Off

- Paper, supplement, and bundle exports were validated on a real mixed-provenance slice.
- Internal-only material stayed suppressed in paper-facing output.
- Bundle round-tripping preserved provenance and release history.

