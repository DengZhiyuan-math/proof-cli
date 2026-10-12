from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
OUT = Path('/Volumes/Codex-Workspace/live/home/zhdeng/proof-cli/docs/audits/2026-10-12-adr0021-master-merge')
repos = {'core': ('DengZhiyuan-math/proof-cli', 217, 'integ/0021'), 'agents': ('zeqome/proof-agents', 29, 'integ/0021'), 'web': ('zeqome/proof-web', 24, 'feat/0021-pursue-review-queue')}

def run(args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True).strip()

def gh(args):
    return json.loads(run(['gh', *args]))

manifest = {'date': datetime.now(timezone.utc).date().isoformat(), 'recordedAt': datetime.now(timezone.utc).isoformat(), 'issue': 'DengZhiyuan-math/proof-cli#198', 'interpreter': sys.executable, 'host': platform.platform(), 'note': 'Each base_sha is the master head immediately before its integration merge. All final test and browser sources are pinned to the final master heads. latex-agent shares the core repository commit; its source tree and last path commit are also pinned.', 'merge_order': ['core', 'agents', 'web']}
for key, (repo, number, branch) in repos.items():
    record = json.loads((ROOT/'remote'/f'{key}-{number}-merged.json').read_text())
    before = json.loads((ROOT/'remote'/f'{key}-{number}-before-merge.json').read_text())
    head = run(['git', 'rev-parse', 'HEAD'], ROOT/key)
    remote_head = gh(['api', f'repos/{repo}/git/ref/heads/master'])['object']['sha']
    assert head == remote_head == record['mergeCommit']['oid']
    integration_head = run(['git', 'rev-parse', 'origin/' + branch], ROOT/key)
    manifest[key] = {'repo': f'https://github.com/{repo}.git', 'branch': 'master', 'head': head, 'tree': run(['git', 'rev-parse', 'HEAD^{tree}'], ROOT/key), 'base': 'master', 'base_sha': before['baseRefOid'], 'merge_base': run(['git', 'merge-base', head, before['baseRefOid']], ROOT/key), 'integration_branch': branch, 'integration_head': integration_head, 'merge_base_with_integration': run(['git', 'merge-base', head, integration_head], ROOT/key), 'pull_request': record['url'], 'source_path': str(ROOT/key), 'status': run(['git', 'status', '--porcelain'], ROOT/key)}
    assert not manifest[key]['status']
manifest['latex_agent'] = {**manifest['core'], 'path': 'packages/latex-agent', 'source_path': str(ROOT/'core/packages/latex-agent'), 'tree': run(['git', 'rev-parse', 'HEAD:packages/latex-agent'], ROOT/'core'), 'last_path_commit': run(['git', 'log', '-1', '--format=%H', '--', 'packages/latex-agent'], ROOT/'core'), 'shares_commit_with': 'core'}
results = {}
for key in repos:
    d = json.loads((ROOT/'logs'/f'final-{key}.json').read_text())
    assert d['exit'] == d['failures'] == d['errors'] == 0
    assert d['heads'] == {k: manifest[k]['head'] for k in repos}
    results[key] = d
manifest['tests'] = results
manifest['upstream_validation'] = [json.loads((ROOT/'logs'/f'{name}.json').read_text()) for name in ('master-core', 'after-core-agents', 'after-agents-web')]
manifest['browser'] = json.loads((ROOT/'browser-master/checks.json').read_text())
assert manifest['browser']['passed'] and manifest['browser']['model_calls'] == 0
manifest['real_provider'] = {'status': 'not_run', 'issue': 197}
manifest['mathematical_acceptance'] = {'status': 'not_performed', 'issue': 132}
remote = {}
for key, (repo, number, _) in repos.items():
    remote[key] = {'integration': gh(['pr', 'view', str(number), '--repo', repo, '--json', 'number,state,url,headRefOid,baseRefOid,mergeCommit,mergedAt,statusCheckRollup']), 'master_checks': gh(['api', f'repos/{repo}/commits/{manifest[key]["head"]}/check-runs'])}
    assert remote[key]['integration']['state'] == 'MERGED'
for key, repo, numbers in [('core', 'DengZhiyuan-math/proof-cli', [183,184,210,211,212]), ('agents', 'zeqome/proof-agents', [8,27,28]), ('web', 'zeqome/proof-web', [5,6,17,22,23])]:
    remote[key]['other_prs'] = [gh(['pr','view',str(n),'--repo',repo,'--json','number,state,url,title,headRefOid,mergeCommit,mergedAt,statusCheckRollup']) for n in numbers]
for n in [197,132]:
    issue = gh(['issue','view',str(n),'--repo','DengZhiyuan-math/proof-cli','--json','number,state,url'])
    assert issue['state'] == 'OPEN'
    remote[f'issue{n}'] = issue
(OUT/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
(OUT/'remote-readback.json').write_text(json.dumps(remote, ensure_ascii=False, indent=2) + '\n')
decisions = json.loads((OUT/'decisions.json').read_text()); decisions['Q5']['web6'] = 'merged automatically after integration'; (OUT/'decisions.json').write_text(json.dumps(decisions,ensure_ascii=False,indent=2)+'\n')
for name in ('logs','remote','browser-candidate','browser-master','browser-master-empty-providers'):
    shutil.copytree(ROOT/name, OUT/name, dirs_exist_ok=True, ignore=shutil.ignore_patterns('project', 'user-config'))
for name in ('run_suite.py','browser_server.py','merge_integration.py','finalize.py'):
    shutil.copyfile(ROOT/name, OUT/name)
old = json.loads((ROOT/'logs/candidate-web-port-cases.json').read_text())
cases = list(ET.parse(ROOT/'logs/final-web.xml').getroot().iter('testcase'))
port = []
for item in old:
    path, test = item['test'].split('::',1)
    match = [c for c in cases if c.get('classname') == path[:-3].replace('/','.') and c.get('name') == test]
    assert len(match)==1 and all(match[0].find(k) is None for k in ('failure','error','skipped'))
    port.append({'test':item['test'],'status':'passed','seconds':match[0].get('time')})
(OUT/'port-cases.json').write_text(json.dumps(port,indent=2)+'\n')
rows = '\n'.join(f'| {key} | {d["tests"]-d["skipped"]} | {d["skipped"]} | {d["failures"]} | {d["errors"]} |' for key,d in results.items())
heads = '\n'.join(f'| {key} | `{manifest[key]["head"]}` | `{manifest[key]["merge_base"]}` |' for key in (*repos,'latex_agent'))
report = f'''# ADR-0021 master integration, 2026-10-12

Q1–Q6 executed. Integration merges used the order core → agents → web. All seven prerequisite PRs were merged before the first master merge.

| Decision | Result |
|---|---|
| Q1 | core #210–#212, agents #27–#28, web #22–#23 merged into integration first. |
| Q2 | Real-provider Pursue remains #197 after master integration. No model trial ran here. |
| Q3 | core [#217](https://github.com/DengZhiyuan-math/proof-cli/pull/217), agents [#29](https://github.com/zeqome/proof-agents/pull/29), web [#24](https://github.com/zeqome/proof-web/pull/24) merged in that order. Exact heads, bases and merge-bases are in manifest.json. |
| Q4 | Final macOS full suites and browser Home → Proof map → Studio → Review passed. Skips are recorded separately. |
| Q5 | web #5 closed as superseded; core #184 and web #6 became merged automatically; web #17 merged independently; core #183 remains open; agents #8 closed. |
| Q6 | CLAUDE_CONFIG_DIR stays in the serving process environment. core #183 was trimmed at d4e977fa9c02a5525e0bd2b29a1f0d12639a11c5; context ring, Show here and no-git-remote remain. Unpublished unknown-key branches were preserved. |

## Final source versions

| Package | Master head | Merge-base with pre-integration master |
|---|---|---|
{heads}

latex-agent is a path in the core repository. It shares the core commit; manifest.json separately records its source tree and last path commit. The independent core #183 changes are not in this merged master.

## Final macOS full suites

| Suite | Passed | Skipped | Failed | Errors |
|---|---:|---:|---:|---:|
{rows}

The core suite includes latex-agent. Core skips cover two optional wall-clock benchmarks, two Windows-only checks, and eleven checks that need a full TeX distribution. The web skip needs pdflatex. No local-port test was skipped: all 19 known port cases passed in the final web suite (port-cases.json). Skips are not counted as passes.

Before agents merged, its full suite passed against the merged core master (logs/after-core-agents.json). Before web merged, its full suite passed against merged core and agents master (logs/after-agents-web.json). All three full suites then ran on the exact final master heads. Commands, XML, timing and source versions are under logs/.

## Browser evidence

browser-master/checks.json records Home → Proof map → Studio → Review, page URLs and actual loaded source paths. Both CLI executables point to `/usr/bin/false`, the system program that exits without contacting any provider. This preserves the normal provider-list interface with zero model calls. No Start, Send, Compile or Record Selected Decisions action was used. The fixture has a pending Candidate proof and no mathematical Acceptance. Screenshots and accessibility snapshots are under browser-master/.

The first fixture disabled both providers. Studio misread its empty provider list as an older server. This is a preexisting configuration edge case: the affected app.js file is identical before and after this integration. browser-master/empty-provider-observation.json and browser-master-empty-providers/ preserve it. The final four-step smoke passed with the two non-model CLI stand-ins and no legacy-server warning. Production code was not changed for this separate observation.

## Evidence boundaries

- Local full suites: passed with the skips above.
- Browser smoke: passed on the final master sources, with zero model calls.
- Real-provider Pursue: not run; #197 remains open.
- Researcher mathematical Acceptance: not performed; #132 remains open.
- GitHub CI: separate compatibility/packaging evidence. remote-readback.json records the snapshot; pending jobs are not reported as passed. No separate CI edit or branch-protection change was made. The workflow changes in #212 were merged as approved.

The shared primary checkout's dirty and untracked files were preserved. Verification used isolated macOS checkouts under {ROOT}. This audit directory is local evidence; no audit commit or separate audit PR was published.
'''
(OUT/'README.md').write_text(report)
print(json.dumps({'heads': {k:manifest[k]['head'] for k in (*repos,'latex_agent')}, 'tests': {k:{field:d[field] for field in ('tests','failures','errors','skipped')} for k,d in results.items()}, 'port_tests':len(port), 'out':str(OUT)},indent=2))
