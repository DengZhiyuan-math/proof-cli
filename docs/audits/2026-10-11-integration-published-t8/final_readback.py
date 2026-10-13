"""Recheck the published heads and the 18 merged PRs without changing them."""
import concurrent.futures
import datetime
import json
import os
from pathlib import Path
import subprocess

out = Path(__file__).resolve().parent
manifest = json.loads((out / 'manifest.json').read_text())
env = dict(os.environ, XDG_CACHE_HOME='/private/tmp/proof-t8-gh-cache')

def command(args):
    return subprocess.check_output(args, env=env, text=True, timeout=60).strip()

def check_pr(item):
    repo, expected = item
    value = json.loads(command(['gh', 'pr', 'view', str(expected['number']), '--repo', repo,
                                '--json', 'state,headRefOid,baseRefName,mergedAt,mergeCommit,url,number']))
    assert value['state'] == 'MERGED', (repo, value)
    for key in ('headRefOid', 'baseRefName'):
        assert value[key] == expected[key], (repo, key, value[key], expected[key])
    return dict(value, repo=repo)

def check_head(item):
    name, repo = item
    prefix = ['git', '--no-optional-locks', '-C', repo['sourcePath']]
    head = command(prefix + ['rev-parse', 'HEAD'])
    clean = not command(prefix + ['status', '--porcelain'])
    remote = command(prefix + ['ls-remote', '--exit-code', 'origin', 'refs/heads/' + repo['branch']]).split()[0]
    assert head == remote == repo['head'] and clean, (name, head, remote, clean)
    return {'repo': repo['repo'], 'branch': repo['branch'], 'localHead': head, 'remoteHead': remote, 'clean': clean}

items = [(r['repo'], p) for r in manifest['repositories'].values() for p in r['mergedPRs']]
assert len(items) == 18
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
    prs = list(pool.map(check_pr, items))
    heads = list(pool.map(check_head, manifest['repositories'].items()))
issue = json.loads(command(['gh', 'issue', 'view', '197', '--repo', 'DengZhiyuan-math/proof-cli', '--json', 'state,url,title']))
result = {'checkedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'heads': heads, 'prs': prs, 'issue197': issue}
(out / 'final-remote-readback.json').write_text(json.dumps(result, indent=2) + '\n')
print('All three heads match; all 18 PRs remain MERGED. Issue #197:', issue['state'])
