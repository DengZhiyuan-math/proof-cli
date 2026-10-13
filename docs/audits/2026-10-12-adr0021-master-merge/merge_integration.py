import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
key, number, expected_head, expected_base = sys.argv[1:]
repos = {'core': 'DengZhiyuan-math/proof-cli', 'agents': 'zeqome/proof-agents', 'web': 'zeqome/proof-web'}
repo = repos[key]
before = json.loads(subprocess.check_output(['gh', 'pr', 'view', number, '--repo', repo, '--json', 'state,headRefOid,baseRefOid,baseRefName,mergeable,statusCheckRollup'], text=True))
assert before['state'] == 'OPEN'
assert before['headRefOid'] == expected_head
assert before['baseRefOid'] == expected_base
assert before['baseRefName'] == 'master'
assert before['mergeable'] == 'MERGEABLE'
(ROOT/'remote'/f'{key}-{number}-before-merge.json').write_text(json.dumps(before, indent=2) + '\n')
subprocess.run(['gh', 'pr', 'merge', number, '--repo', repo, '--merge', '--match-head-commit', expected_head], check=True)
after = json.loads(subprocess.check_output(['gh', 'pr', 'view', number, '--repo', repo, '--json', 'number,state,headRefOid,mergeCommit,mergedAt,url,baseRefName'], text=True))
assert after['state'] == 'MERGED'
(ROOT/'remote'/f'{key}-{number}-merged.json').write_text(json.dumps(after, indent=2) + '\n')
subprocess.run(['git', 'fetch', 'origin'], cwd=ROOT/key, check=True, capture_output=True)
subprocess.run(['git', 'switch', '--detach', 'origin/master'], cwd=ROOT/key, check=True, capture_output=True)
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT/key, text=True).strip() == after['mergeCommit']['oid']
print(json.dumps(after, indent=2))
