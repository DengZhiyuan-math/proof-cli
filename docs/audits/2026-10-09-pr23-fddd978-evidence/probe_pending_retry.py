import json
import runpy
import sys
import threading
from pathlib import Path

AGENT = Path(__file__).resolve().parent
sys.path.insert(0, str(AGENT / 'src'))
api = runpy.run_path(str(AGENT / 'tests/test_coordinator.py'))
World, pursuit_for, until = api['World'], api['_pursuit'], api['_until']
worlds = {'T1': World(edges={'T1': []}, kinds={'T1': 'claim'}), 'T2': World(edges={'T2': []}, kinds={'T2': 'claim'})}
pursuit, coordinators = pursuit_for(worlds)
entered, finish = threading.Event(), threading.Event()
retry_answer = []
stopper = None
try:
    pursuit.start('claude')
    until(lambda: worlds['T1'].runs['T1'].starts == 1, 'T1 started')
    run = worlds['T1'].runs['T1']
    run.fail_release = True
    first = pursuit.stop()
    assert first['code'] == 'RELEASE_FAILED'
    until(lambda: not pursuit.active(), 'the first pursuit worker ended')
    original = run.release
    def delayed_release(*args, **kwargs):
        entered.set()
        assert finish.wait(5), 'release gate timed out'
        return original(*args, **kwargs)
    run.release = delayed_release
    stopper = threading.Thread(target=lambda: retry_answer.append(pursuit.stop()), daemon=True)
    stopper.start()
    assert entered.wait(2), 'retried Stop entered release'
    pending = pursuit.view()
    start_answer = pursuit.start('claude')
    if start_answer.get('code') != 'PURSUIT_ACTIVE':
        until(lambda: worlds['T2'].runs['T2'].starts == 1, 'T2 starts while T1 release is still pending')
    print(json.dumps({'head': 'fddd978008e385bbbc0a1c331dc26f099ad64579', 'pending_view': pending, 'start_answer': start_answer, 'T1_release_pending': not finish.is_set(), 'T2_starts': worlds['T2'].runs['T2'].starts}, indent=2))
    assert start_answer.get('code') == 'PURSUIT_ACTIVE', 'A new Pursue must wait for the retried release to finish. T1 still owns its node.'
    assert worlds['T2'].runs['T2'].starts == 0
finally:
    finish.set()
    if stopper is not None:
        stopper.join(2)
    # End the second pursuit if the bug let it start, and release all fixtures.
    pursuit._stop = True
    for world in worlds.values():
        for run in world.runs.values():
            run.fail_release = False
    for coordinator in coordinators.values():
        coordinator.release()
    if pursuit._thread is not None:
        pursuit._thread.join(2)
