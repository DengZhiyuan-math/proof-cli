# agents #19 publication

Date: 2026-10-10.

- Restored the saved patch as the exact commit `d9f98faf76a64bc5609ea134183dc8096041257f`, with parent `7e742b5823ad72ee37f429aa4983e8d632102796`.
- Pushed `fix/19-structure-budget` without force. The remote SHA was read back and matched.
- Created [proof-agents PR #26](https://github.com/zeqome/proof-agents/pull/26), base `fix/18-park-at-budget`, using the supplied title and `pr19.md` verbatim. The PR is OPEN and attached to this chat.
- Created [proof-web issue #18](https://github.com/zeqome/proof-web/issues/18). The draft's first heading is its title. The remaining body is unchanged. The issue is OPEN.
- Read both items back. Their titles and bodies match the saved drafts. PR head and base also match.

## Validation

The independently restored checkout passed all 177 agents tests once in 17.12 seconds, with proof-cli at `b7f394374ce73e9a23754e12506e87e97326efd9`. The interpreter was `/opt/anaconda3/bin/python`. This run is separate from the implementer's reported three passing runs and 17 new tests.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/private/tmp/proof-agents19-publication-jqjt55pi/core/src:/private/tmp/proof-agents19-publication-jqjt55pi/agents/src /opt/anaconda3/bin/python -m pytest -q /private/tmp/proof-agents19-publication-jqjt55pi/agents/tests --basetemp=/private/tmp/proof-agents19-publication-jqjt55pi/pytest-tmp -o cache_dir=/private/tmp/proof-agents19-publication-jqjt55pi/pytest-cache
```

At the publication check, Python 3.12 CI was SUCCESS and Python 3.11 CI was IN_PROGRESS. This is a snapshot, not a final CI result.

## Pending

The web assertion update from 120 to 122, the before-Start display and submission, and browser verification remain in proof-web #18. This publication did not rerun proof-web tests or run a real provider. It did not merge either PR or delete branches.

The reconstruction checkout is `/private/tmp/proof-agents19-publication-jqjt55pi/agents`. The user's source checkout was not changed. Machine-readable metadata, draft hashes, remote refs and the CI snapshot are in [publication-verified.json](publication-verified.json).
