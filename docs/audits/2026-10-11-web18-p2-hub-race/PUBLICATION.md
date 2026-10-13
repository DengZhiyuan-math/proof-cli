# P2 and hub-race patch publication

Verified on 2026-10-11 (Europe/Zurich). This record supplements the implementer's [README](README.md). Its original sandbox results are preserved.

The four supplied patches were applied with `git am --committer-date-is-author-date` in fresh temporary checkouts. Each branch contains exactly the two supplied commits above its specified base. Both pushes were ordinary fast-forward pushes.

| Repository | Base | Published head | Pull request | CI |
| --- | --- | --- | --- | --- |
| proof-agents | `d9f98faf76a64bc5609ea134183dc8096041257f` | `ead54fe8d3480f1d4ba45a5b7b1bfb97b0f796ee` | [#26](https://github.com/zeqome/proof-agents/pull/26) | Python 3.11 and 3.12: SUCCESS |
| proof-web | `c0232effb7f130368a4053d5491fabdfc7cd6c73` | `355837c333fd8189c105aa241d4e9fa8ffe50e6f` | [#19](https://github.com/zeqome/proof-web/pull/19) | package: SUCCESS |

The remote branch SHA and PR head match in each repository. Both PRs remain OPEN. Their original branch names, bases, titles and bodies were read back and match the pre-push records. Neither PR was merged.

## Independent tests

Python: `/opt/anaconda3/bin/python`. Core and latex-agent: exported core `09e64a365153650cade0579afca52a56028b0f07`. The agents combined build reuses the saved #23/#26 resolution and adapted tests, then applies the two new agents patches. Both patches applied cleanly. This combined build was not published; the future #23/#26 merge still needs the saved resolution.

| Check | Result | Evidence |
| --- | --- | --- |
| Exact agents `ead54fe` | 178 passed in 15.82s | [log](publication/agents-suite.log) |
| Combined agents build | 182 passed in 16.38s | [log](publication/combined-suite.log) |
| Full web `355837c`, with combined agents and local port binding enabled | 779 passed, 1 skipped; no failures or errors, in 251.05s | [log](publication/web-suite.log) |

The full web run includes all 19 previously port-blocked cases. These results are separate from the implementer's sandbox run and 36-copy load test. The load test was not repeated.

## Browser

Chrome 155.0.8059.39 and agent-browser 0.33.1 used a fresh isolated profile. The original deterministic [browser fixture](../2026-10-11-web18-c0232ef-publication-browser/browser_server.py) served the published web source with the combined agents build. No model calls or mathematical Review decisions were made.

At `http://localhost:27807/`, title `Proof map`, Pursue was started through the observed browser button. After the Reader-only Pursue ended (`stuck`, `the Reader stated no Theorem`), the panel showed `Turns 1/5 (1 structure)`. The real HTTP response reported `budget.spent=1`, `budget.structure_spent=1`, `spend.turns=1` and `spend.structure_turns=1`. This closes the prior Reader-only browser finding. Cumulative counts across Theorems were covered by tests; no multi-Theorem browser scenario was run.

The screenshot was inspected visually. Browser JavaScript errors were empty. The temporary server and Chrome profile were closed, and the server and CDP ports were checked closed. Temporary source checkouts were retained at `/private/tmp/proof-p2-publication-kd8u79bb`. Primary checkouts and unrelated work were preserved.

- [Browser snapshot](publication/browser-after.txt)
- [Browser API and panel values](publication/browser-after.json)
- [Browser screenshot](publication/browser-after.png)
- [Publication metadata, source hashes and results](publication/publication-verified.json)
