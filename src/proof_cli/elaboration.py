from __future__ import annotations

from .goals import add_goal, set_current_context, set_current_theorem
from .obligations import add_obligation, close_obligation
from .proof_state import load_state, note_unresolved_trust_call, record_theorem_usage
from .storage import ProjectStore
from .theorems import apply_theorem, theorem_callability
from .domain import ProofObligation
from .dsl import DSLCommand
from .commands import cmd_proof_ground, cmd_proof_import, cmd_proof_review, cmd_proof_search


def _is_vague(argument: str) -> bool:
    lower = argument.lower()
    return any(token in lower for token in ["obvious", "standard", "similar", "clear", "routine"])


def elaborate_command(store: ProjectStore, command: DSLCommand) -> str:
    state = load_state(store)
    name = command.name
    argument = command.argument

    if name == "goal":
        add_goal(store, argument)
        set_current_theorem(store, argument)
        return f"goal:{argument}"
    if name == "assume":
        assumptions = list(state.current_context)
        if argument not in assumptions:
            assumptions.append(argument)
        set_current_context(store, assumptions)
        return f"assume:{argument}"
    if name in {"use", "apply"}:
        ok, reason = theorem_callability(store, argument)
        if ok:
            if name == "apply":
                apply_theorem(store, argument)
            else:
                record_theorem_usage(store, argument)
            return f"{name}:{argument}"
        note_unresolved_trust_call(store, argument)
        if reason.startswith("missing assumptions:"):
            missing = [item.strip() for item in reason.split(":", 1)[1].split(",") if item.strip()]
            for item in missing:
                add_obligation(
                    store,
                    ProofObligation(
                        id=f"obl_{abs(hash((argument, item))) % 100000}",
                        goal_statement=item,
                        required_for=argument,
                        blocking_reason=reason,
                    ),
                )
        return f"{name}:blocked:{reason}"
    if name == "import":
        return cmd_proof_import(command.target or argument, root=store.root)
    if name == "search":
        return cmd_proof_search(argument, root=store.root)
    if name == "ground":
        return cmd_proof_ground(command.target or argument, list(command.references), root=store.root)
    if name == "review":
        if not command.target:
            return "review:missing-target"
        review_argument = argument.strip()
        if review_argument:
            review_parts = review_argument.split(maxsplit=1)
            review_action = review_parts[0]
            review_rationale = review_parts[1] if len(review_parts) > 1 else ""
            if review_action.lower() not in {"approve", "approved", "reject", "rejected", "defer", "deferred", "candidate", "downgrade"}:
                review_rationale = review_argument
                review_action = "approve"
        else:
            review_action = "approve"
            review_rationale = ""
        return cmd_proof_review(command.target, review_action, root=store.root, rationale=review_rationale)
    if name in {"assert", "defer", "suffices"}:
        statement = argument
        if not statement:
            add_obligation(
                store,
                ProofObligation(
                    id=f"obl_{abs(hash((name, argument, state.current_theorem))) % 100000}",
                    goal_statement=f"{name} requires a statement",
                    required_for=state.current_theorem,
                    blocking_reason="missing statement",
                ),
            )
            return f"{name}:missing-statement"
        add_obligation(
            store,
            ProofObligation(
                id=f"obl_{abs(hash((name, statement, state.current_theorem))) % 100000}",
                goal_statement=statement,
                required_for=state.current_theorem,
                blocking_reason="compressed reasoning" if _is_vague(statement) else None,
            ),
        )
        return f"{name}:{statement}"
    if name == "split":
        target = state.current_theorem or (state.open_goals[-1] if state.open_goals else "current goal")
        add_obligation(
            store,
            ProofObligation(
                id=f"obl_{abs(hash((target, 'split-1'))) % 100000}",
                goal_statement=f"{target} (subgoal 1)",
                required_for=target,
            ),
        )
        add_obligation(
            store,
            ProofObligation(
                id=f"obl_{abs(hash((target, 'split-2'))) % 100000}",
                goal_statement=f"{target} (subgoal 2)",
                required_for=target,
            ),
        )
        return f"split:{target}"
    if name == "close":
        obligations = load_state(store).open_obligations
        if obligations:
            close_obligation(store, obligations[-1], rationale="closed by DSL close")
            return f"close:{obligations[-1]}"
        return "close:no-open-obligations"
    raise ValueError(f"Unknown DSL command: {name}")


def elaborate_program(store: ProjectStore, commands: list[DSLCommand]) -> list[str]:
    return [elaborate_command(store, command) for command in commands]
