import json
import runpy
from pathlib import Path

module = runpy.run_path(str(Path(__file__).with_name('coordinator-c5d742c.py')))
Coordinator, CoordinatorHooks = module['Coordinator'], module['CoordinatorHooks']
started = []

class Run:
    def __init__(self, node_id):
        self.node_id = node_id
    def view(self):
        if self.node_id == 'T':
            return {'status': 'needs-human', 'reason': 'the statement asks x > 0 and x <= 0', 'turns': 1, 'started_at': 1.0}
        return {'status': 'idle', 'turns': 0}
    def start(self, provider, **kwargs):
        started.append(self.node_id)
        return {'started_at': 2.0}

nodes = [
    {'id': 'T', 'kind': 'theorem', 'dependencies': ['C1', 'C2', 'S'], 'split_children': ['C1', 'C2']},
    {'id': 'C1', 'kind': 'claim', 'dependencies': []},
    {'id': 'C2', 'kind': 'claim', 'dependencies': []},
    {'id': 'S', 'kind': 'claim', 'dependencies': []},
]
for node in nodes:
    node.update(has_run=True, accepted=False, provisional=False, workflow='open', claimed_by=None)
runs = {node['id']: Run(node['id']) for node in nodes}
c = Coordinator(CoordinatorHooks(subtree=lambda: nodes, run=runs.__getitem__, budget=lambda: (3, 10.0), parallel=lambda: 4), 'T')
c.state.status, c.state.name, c.state.provider = 'running', 'agent', 'claude'
c.state.running = ['T']
c.state.decomposed = ['T']
c.state.nodes = {'T': {'starts': 1, 'turns': 0, 'last': None, 'role': 'decomposer', 'started_at': 1.0}}
c._step()
print(json.dumps({'source_head': 'c5d742cf20c28569726d4081012cefef71ea92df', 'started': started, 'parked': c.state.parked, 'expected_started': ['S']}, indent=2))
assert started == ['S'], 'The Claims of the contradictory split must wait; only the existing sibling may start.'
