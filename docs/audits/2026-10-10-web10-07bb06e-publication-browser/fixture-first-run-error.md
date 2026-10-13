The first release-interrupted browser fixture used the submitted DirectClient
Coordinator fixture without its `running` field. `/api/map` returned
`INTERNAL_ERROR: KeyError`, and the page's refresh did not finish.

The fixture now supplies `running: []`, which the production map requires.
The production source was unchanged. The rerun uses a new synthetic project
`release-interrupted-v2`; the first project's state is retained in /private/tmp.
Do not count the first run as acceptance or as a product regression.
