#!/bin/bash
# usage: hubload.sh <agents dir name> <prefix>
S=/private/tmp/claude-502/-Volumes-Codex-Workspace-live-home-zhdeng-proof-cli/a1dcf6b7-5a7e-4737-9c30-60241cd19074/scratchpad
cd $S/web && source ../env18.sh && export PYTHONPATH=${PYTHONPATH/agents-combined/$1}
for i in 1 2 3 4 5 6; do python -m pytest tests/test_coordinator_hub.py -q -p no:cacheprovider -k works_the_children > $S/$2-$i.txt 2>&1 & done
wait
for i in 1 2 3 4 5 6; do tail -n1 $S/$2-$i.txt; done
grep -h '"reason"' $S/$2-*.txt | head -3
