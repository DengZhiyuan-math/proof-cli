"""Read-only failure injection for ADR-0021 Standing-question persistence."""

from types import SimpleNamespace

from proof_agents.agent_run import AgentRun


def fail_record(*args):
    raise OSError("simulated Standing-question write failure")


run = object.__new__(AgentRun)
closing_notes = []
run.hooks = SimpleNamespace(
    record_question=fail_record,
    record_close=lambda *args: closing_notes.append(args),
)

# The current code returns normally, with no question and no fallback note.
# Its caller then clears `asked` and continues after a Decomposer split.
run._question("decomposer", "agent", "choose A; alternative B")
assert closing_notes == []
print("REPRODUCED: recording failure is swallowed; no fallback note is kept")
