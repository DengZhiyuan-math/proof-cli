from __future__ import annotations

from .goals import add_goal, set_current_context, set_current_theorem
from .obligations import add_obligation, close_obligation
from .proof_state import load_state, note_unresolved_trust_call, record_theorem_usage
from .storage import ProjectStore
from .theorems import apply_theorem, theorem_callability
from .domain import ProofObligation
from .dsl import DSLCommand
from .commands import (
    cmd_proof_bug_list,
    cmd_proof_bug_scan,
    cmd_proof_bug_show,
    cmd_proof_debug_generate,
    cmd_proof_debug_list,
    cmd_proof_evidence_show,
    cmd_proof_explain_apply,
    cmd_proof_formalize_edit,
    cmd_proof_formalize_recommend,
    cmd_proof_formalize_show,
    cmd_proof_ground,
    cmd_proof_import,
    cmd_proof_obligation_derive,
    cmd_proof_reason,
    cmd_proof_repair_mark,
    cmd_proof_review,
    cmd_proof_review_suspicion,
    cmd_proof_revalidate,
    cmd_proof_trace_machine_check,
    cmd_proof_search,
    cmd_proof_verify_accept,
    cmd_proof_verify_queue,
    cmd_proof_verify_reject,
    cmd_proof_verify_result,
    cmd_proof_verify_run,
    cmd_proof_verify_stale,
    cmd_proof_verify_status,
    cmd_proof_trace_dependency,
)


def _is_vague(argument: str) -> bool:
    lower = argument.lower()
    return any(token in lower for token in ["obvious", "standard", "similar", "clear", "routine"])


def _options(command: DSLCommand) -> dict[str, str]:
    return {key: value for key, value in command.options}


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
    if name == "reason":
        theorem_id = command.target or state.current_theorem or argument
        if not theorem_id:
            return "reason:missing-target"
        return cmd_proof_reason(theorem_id, root=store.root, notes=argument)
    if name == "obligation_derive":
        theorem_id = command.target or state.current_theorem or argument
        if not theorem_id:
            return "obligation:derive:missing-target"
        return cmd_proof_obligation_derive(theorem_id, root=store.root, notes=argument)
    if name == "bug_scan":
        theorem_id = command.target or state.current_theorem or argument
        if not theorem_id:
            return "bug:scan:missing-target"
        return cmd_proof_bug_scan(theorem_id, root=store.root)
    if name == "bug_list":
        theorem_id = command.target or state.current_theorem or ""
        return cmd_proof_bug_list(root=store.root, theorem_id=theorem_id)
    if name == "bug_show":
        bug_id = command.target or argument
        if not bug_id:
            return "bug:show:missing-target"
        return cmd_proof_bug_show(bug_id, root=store.root)
    if name == "evidence_show":
        bug_id = command.target or argument
        if not bug_id:
            return "evidence:show:missing-target"
        return cmd_proof_evidence_show(bug_id, root=store.root)
    if name == "debug_generate":
        theorem_id = command.target or state.current_theorem or argument
        if not theorem_id:
            return "debug:generate:missing-target"
        return cmd_proof_debug_generate(theorem_id, root=store.root)
    if name == "debug_list":
        theorem_id = command.target or state.current_theorem or ""
        return cmd_proof_debug_list(root=store.root, theorem_id=theorem_id)
    if name == "repair_mark":
        bug_id = command.target or argument
        if not bug_id:
            return "repair:mark:missing-target"
        repair_argument = argument.strip()
        repair_parts = repair_argument.split(maxsplit=1) if repair_argument else []
        repair_status = repair_parts[0] if repair_parts else "repaired"
        repair_note = repair_parts[1] if len(repair_parts) > 1 else ""
        return cmd_proof_repair_mark(bug_id, repair_status, root=store.root, note=repair_note)
    if name == "review_suspicion":
        bug_id = command.target or argument
        if not bug_id:
            return "review:suspicion:missing-target"
        review_argument = argument.strip()
        review_parts = review_argument.split(maxsplit=1) if review_argument else []
        review_status = review_parts[0] if review_parts else "under_review"
        review_note = review_parts[1] if len(review_parts) > 1 else ""
        return cmd_proof_review_suspicion(bug_id, review_status, root=store.root, rationale=review_note)
    if name == "trace_dependency":
        target_id = command.target or state.current_theorem or argument
        if not target_id:
            return "trace:dependency:missing-target"
        return cmd_proof_trace_dependency(target_id, root=store.root)
    if name == "formalize_recommend":
        source_id = command.target or argument
        if not source_id:
            return "formalize:recommend:missing-target"
        return cmd_proof_formalize_recommend(
            source_id,
            root=store.root,
            backend_target=_options(command).get("backend", ""),
            notes=argument,
        )
    if name == "formalize_show":
        source_id = command.target or argument
        if not source_id:
            return "formalize:show:missing-target"
        return cmd_proof_formalize_show(source_id, root=store.root)
    if name == "formalize_edit":
        source_id = command.target or argument
        if not source_id:
            return "formalize:edit:missing-target"
        options = _options(command)
        return cmd_proof_formalize_edit(
            source_id,
            root=store.root,
            backend_target=options.get("backend", ""),
            notes=options.get("notes", argument),
        )
    if name == "verify_queue":
        source_id = command.target or argument
        if not source_id:
            return "verify:queue:missing-target"
        options = _options(command)
        return cmd_proof_verify_queue(
            source_id,
            root=store.root,
            backend_target=options.get("backend", ""),
            route_id=options.get("route", ""),
            notes=argument,
        )
    if name == "verify_run":
        source_id = command.target or argument
        if not source_id:
            return "verify:run:missing-target"
        options = _options(command)
        return cmd_proof_verify_run(
            source_id,
            root=store.root,
            backend_target=options.get("backend", ""),
            notes=argument,
        )
    if name == "verify_status":
        source_id = command.target or argument
        if not source_id:
            return "verify:status:missing-target"
        return cmd_proof_verify_status(source_id, root=store.root)
    if name == "verify_result":
        source_id = command.target or argument
        if not source_id:
            return "verify:result:missing-target"
        return cmd_proof_verify_result(source_id, root=store.root)
    if name == "verify_accept":
        source_id = command.target or argument
        if not source_id:
            return "verify:accept:missing-target"
        return cmd_proof_verify_accept(source_id, root=store.root, notes=argument)
    if name == "verify_reject":
        source_id = command.target or argument
        if not source_id:
            return "verify:reject:missing-target"
        return cmd_proof_verify_reject(source_id, root=store.root, notes=argument)
    if name == "verify_stale":
        source_id = command.target or argument
        if not source_id:
            return "verify:stale:missing-target"
        options = _options(command)
        dependency_ids = [item.strip() for item in options.get("dependency", "").split(",") if item.strip()]
        return cmd_proof_verify_stale(
            source_id,
            root=store.root,
            reason=argument,
            changed_dependency_ids=dependency_ids or None,
        )
    if name == "trace_machine_check":
        target_id = command.target or argument
        if not target_id:
            return "trace:machine-check:missing-target"
        return cmd_proof_trace_machine_check(target_id, root=store.root)
    if name == "revalidate":
        source_id = command.target or argument
        if not source_id:
            return "revalidate:missing-target"
        options = _options(command)
        return cmd_proof_revalidate(
            source_id,
            root=store.root,
            backend_target=options.get("backend", ""),
            notes=argument,
        )
    if name == "explain_apply":
        theorem_id = command.target or state.current_theorem or argument
        if not theorem_id:
            return "explain:apply:missing-target"
        return cmd_proof_explain_apply(theorem_id, root=store.root)
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
            close_obligation(store, obligations[-1], rationale="resolved by DSL close")
            return f"close:{obligations[-1]}"
        return "close:no-open-obligations"
    raise ValueError(f"Unknown DSL command: {name}")


def elaborate_program(store: ProjectStore, commands: list[DSLCommand]) -> list[str]:
    return [elaborate_command(store, command) for command in commands]
