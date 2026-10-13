import json
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'src'))
world_api = runpy.run_path(str(HERE / 'test_coordinator.py'))
World, FakeRun, until = world_api['World'], world_api['FakeRun'], world_api['_until']
world = World(edges={'T': ['A', 'B'], 'A': [], 'B': []}, parallel=3, budget=(5, 60.0))
c = world.coordinator()
try:
    c.start('claude')
    until(lambda: world.runs['A'].starts == 1 and world.runs['B'].starts == 1, 'A and B started')
    world.runs['A'].end('needs-human', turns=1, reason='cannot be stated as is')
    until(lambda: world.runs['T'].starts == 1, 'T Decomposer started')
    world.runs['A2'] = FakeRun()
    world.edges.update({'T': ['A', 'B', 'A2'], 'A2': []})
    # The split command commits now. The provider still has to report needs-human.
    until(lambda: world.runs['A2'].starts == 1, 'A2 starts during the Decomposer turn')
    world.runs['T'].end('needs-human', turns=1, reason='the statement asks x > 0 and x <= 0')
    world.runs['T'].claim = None
    until(lambda: any(e['node'] == 'T' for e in c.view()['parked']), 'T parked')
    print(json.dumps({'head': '15ce077519f881c28d73ec8390dcb831697716e5', 'A2_starts': world.runs['A2'].starts, 'A2_status_after_parent_needs_human': world.runs['A2'].status, 'held': c.view()['held'], 'parked': c.view()['parked']}, indent=2))
    assert world.runs['A2'].starts == 0, 'The split Claim ran before the decision, and marking it held did not stop its active run.'
finally:
    c.release()
