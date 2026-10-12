# Replaying the recorded suites

The archived scripts are historical execution records. They originally ran in `/private/tmp/proof-0021-merge-jbf0__fm`, beside three source checkouts. Running a copied script directly from this audit directory does not reconstruct that workspace.

To replay the final suites on macOS, create a disposable workspace with sibling `core`, `agents`, `web`, and `logs` directories. Clone the following repositories into the named source directories and check out the exact commits.

| Directory | Repository | Commit |
|---|---|---|
| core | https://github.com/DengZhiyuan-math/proof-cli | d433159214156239e31094d1eaea3b7b991b927f |
| agents | https://github.com/zeqome/proof-agents | 7d3f312269b9868415e06302b97637db1a490220 |
| web | https://github.com/zeqome/proof-web | af687b02b7d03dbf5bd2b60062284d8421dfa5c0 |

`latex-agent` is `core/packages/latex-agent` at the core commit. Use a Python environment with the repositories' declared dependencies and pytest. The recorded Python version was 3.11.14. Copy `run_suite.py` into the disposable workspace root. Run these commands from that root:

```sh
python run_suite.py core replay
python run_suite.py agents replay
python run_suite.py web replay
```

The script supplies all four source paths through `PYTHONPATH`. Save new results under their `replay-*` names; preserve the archived `final-*` evidence. Record the actual imported source paths, checkout status, Python version, and available TeX tools for the new run. Availability of pdflatex, XeLaTeX, biber, and other TeX tools affects skips.

`merge_integration.py` and `finalize.py` record the completed merge and archive process. They are not required to replay the test suites. Browser captures in this archive prove only the recorded fixture traversal. A new #197 acceptance run needs its own provider, budget, input hashes, source manifest, and result record.
