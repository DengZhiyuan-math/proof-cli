from proof_agents.coordinator import ProjectPursuit, PursuitHooks

class RefusesRelease:

    def release(self):
        return {'error': 'the node is still assigned', 'code': 'RELEASE_FAILED', 'status': 'release-failed'}

def test_project_stop_must_surface_coordinator_release_failure():
    pursuit = ProjectPursuit(PursuitHooks(read=lambda _: {}, theorems=lambda: ['T'], coordinator=lambda _: RefusesRelease()))
    pursuit.state.update(status='pursuing', current='T')
    result = pursuit.stop()
    assert result.get('code') == 'RELEASE_FAILED', result
    assert result['status'] == 'release-failed'

class BudgetCoordinator(RefusesRelease):

    def start(self, provider):
        return {'status': 'budget'}

    def active(self):
        return False

    def view(self):
        return {'status': 'budget', 'reason': 'budget spent; its run still owns a node'}

def test_next_theorem_waits_when_previous_release_failed():
    started = []

    class Tracked(BudgetCoordinator):

        def __init__(self, name):
            self.name = name

        def start(self, provider):
            started.append(self.name)
            return super().start(provider)
    coordinators = {name: Tracked(name) for name in ['T1', 'T2']}
    pursuit = ProjectPursuit(PursuitHooks(read=lambda _: {}, theorems=lambda: ['T1', 'T2'], coordinator=coordinators.__getitem__))
    pursuit._loop('stub')
    assert started == ['T1'], started
    assert pursuit.view()['status'] == 'release-failed'
