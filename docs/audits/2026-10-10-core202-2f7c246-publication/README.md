# Core #202: scope decisions, checks, and PR publication

Date: 2026-10-10 (Europe/Zurich).

[PR #207](https://github.com/DengZhiyuan-math/proof-cli/pull/207) was created and
attached to this chat. Exact head:
`2f7c2460bca05bc2d823403f17b05ed28766412b`, branch
`fix/202-reference-edit`. Base: `integ/0021`, exact parent and merge base
`b7f394374ce73e9a23754e12506e87e97326efd9`. The comparison contains one commit
and the six expected files. The working tree was clean.

The title and body were published exactly as supplied. The preserved body is
`pr202-original.md`; GitHub readback matches it byte-for-byte, including the
terminal newline. The source was the user's scratchpad `pr202.md`, which was
present this time. The implementation and published commit were not changed.
Issue #202 remains OPEN and its body was not edited. No merge was performed.

## Scope decisions

1. Keep `origin` and `bibliographic_source` editable. They are existing
   ReferenceRecord fields and both hold bibliographic text. They do not change
   the imported node's mathematical interface. The same partial-update,
   required-reason and event-recording contract applies to them.
2. Keep bibliography edits available to cooperative agents. `--by` records
   attribution; it is not an authorization check. ADR-0014 point 3 permits
   typed metadata to satisfy a rule declared by the researcher. ADR-0022
   decisions 2 and 4 check the imported node's author and preserve the rule
   behavior of researcher-created nodes. They do not impose a researcher-only
   editor requirement. An agent can therefore complete the DOI of a
   researcher-created import and change whether it meets the existing rule.

The ADR-0022 guarantee for agent-created imported nodes is not implemented on
this base: `trust_rules_of` does not inspect the node's `created_by`.
[PR #204](https://github.com/DengZhiyuan-math/proof-cli/pull/204) is the separate
implementation. #202 alone does not establish that guarantee. Integrated
acceptance must include #204 and the agent-import tests; no such guarantee is
claimed from the #202 tests. This matches the supplied PR's explicit limitation.

The next listed implementation task remains core #203. It was not implemented
as part of this publication task.

## Independent verification

Runtime: `/opt/anaconda3/bin/python3`, using exact #202 source.

| Check | Result |
| --- | --- |
| Reference edit, references, trust rules, CLI contract | 102 passed in 9.73s |
| Trust-rule CLI | 6 passed in 0.90s |
| Total related tests, including all 16 new tests | 108 passed |
| Independent CLI/service probes | 3 passed |
| `git diff b7f3943..2f7c246 --check` | Passed |

The three probes verify:

- CLI edits of `origin` and `bibliographic_source` preserve id, creator and
  creation time and record `PROOF_AGENT_NAME` plus the exact field differences.
- An agent CLI edit adds a DOI to a researcher-created import and changes its
  dependent from blocked to open. Removing the DOI restores blocked.
- An injected event-write failure rolls the bibliographic update back.

`scope_probe.py` uses a fresh synthetic project under `/private/tmp`, the normal
CLI subprocess for bibliography edits, and the existing researcher test helper
to declare the synthetic rule. It modifies no real proof project's reviews.
Its observations are in `scope-probe-results.json`.

No full-suite rerun was performed. The 1123 passed, 15 skipped, 3 failed result
and the matching base failures are the implementer's report, not independently
rerun evidence from this task.

Publication metadata, the comparison, and readback assertions are preserved in
`pr207-published.json`, `pr207-compare.json`, and `publication-verified.json`.
The latest readback (`ci-latest.json`) shows all four GitHub test jobs still
running: Ubuntu and Windows, Python 3.11 and 3.12. No remote CI pass is claimed.
