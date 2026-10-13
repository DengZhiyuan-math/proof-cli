import json
import runpy
import sys
import threading
from pathlib import Path

AGENT = Path(__file__).resolve().parent / 'agents17'
MANIFEST = json.loads((Path(__file__).resolve().parent / 'manifest.json').read_text())
sys.path.insert(0, str(Path(MANIFEST['agents']['path']) / 'src'))
sys.path.insert(0, str(Path(MANIFEST['core']['path']) / 'src'))
assert (Path(MANIFEST['agents']['path']) / 'src/proof_agents/coordinator.py').read_bytes() == (AGENT / 'src/proof_agents/coordinator.py').read_bytes(), 'dependency source changed'
api = runpy.run_path(str(AGENT / 'tests/test_coordinator.py'))
World, pursuit_for, until = api['World'], api['_pursuit'], api['_until']
worlds = {'T1': World(edges={'T1': []}, kinds={'T1': 'claim'}, budget=(1, 60.0)), 'T2': World(edges={'T2': []}, kinds={'T2': 'claim'})}
pursuit, coordinators = pursuit_for(worlds)
entered, finish = threading.Event(), threading.Event()
answers, outside_threads = [], []
coordinator = coordinators['T1']
original_release = coordinator.release
run = worlds['T1'].runs['T1']
original_run_release = run.release

def delayed_run_release(*args, **kwargs):
    entered.set()
    assert finish.wait(5), 'release gate timed out'
    return original_run_release(*args, **kwargs)

run.release = delayed_run_release

def release_overlapping_another_stop():
    # Another caller's Stop arrives just before this release call. Both use the
    # real Coordinator; its second call returns COORDINATOR_ACTIVE while pending.
    outside = threading.Thread(target=original_release, daemon=True)
    outside_threads.append(outside)
    outside.start()
    assert entered.wait(2), 'another Stop entered release'
    result = original_release()
    answers.append(result)
    return result

coordinator.release = release_overlapping_another_stop
try:
    pursuit.start('claude')
    until(lambda: run.starts == 1, 'T1 started')
    run.end('budget', turns=1, reason='out of turns')
    until(lambda: answers, 'the budget path sees the concurrent-release answer')
    print(json.dumps({'head': 'e2d6f9ee570f81e99ccaf69a40315ad46bb9cc96', 'release_answer': answers[0], 'T1_release_pending': not finish.is_set(), 'T2_starts': worlds['T2'].runs['T2'].starts, 'project_view': pursuit.view()}, indent=2))
    assert worlds['T2'].runs['T2'].starts == 0, 'COORDINATOR_ACTIVE means release is pending; it is not NO_COORDINATOR and must not allow the next Theorem.'
finally:
    finish.set()
    for thread in outside_threads:
        thread.join(2)
    coordinator.release = original_release
    pursuit._stop = True
    for c in coordinators.values():
        c.release()
    if pursuit._thread is not None:
        pursuit._thread.join(2)
