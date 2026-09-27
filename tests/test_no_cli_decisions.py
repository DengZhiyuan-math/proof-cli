"""No CLI command, codex route or MCP tool can make a Human Review decision (ADR-0009, issue #37).

Walks the whole command tree against a project holding every kind of
protected state, invoking each command with every interesting target and
the most permissive flags an agent could try — and checks that nothing
protected changed: acceptance, Reference review, Challenge resolution, kind,
another session's claim, legacy theorem trust, reference approval, and
obligation/blocker resolution. (Integrity is not protected: opening a
Challenge or editing a dependency is ordinary agent work.)
"""

import ast
import contextlib
import json
import os
import shutil
import sqlite3
from pathlib import Path

import click
import pytest
import typer
from typer.testing import CliRunner

from _authenticator import researcher
from _legacy_seed import seed_reference_review
from proof_cli.blockers import add_blocker
from proof_cli.cli import app
from proof_cli.collaboration import list_review_records
from proof_cli.exchange import bundle_to_json, export_exchange_bundle
from proof_cli.domain import BlockerRecord, ProofObligation, TheoremStatus, TrustLevel
from proof_cli.obligations import add_obligation
from proof_cli.proof_map import (
    claim_node,
    create_node,
    get_acceptance_state,
    get_node,
    get_reference_review_state,
    list_challenges,
    list_nodes,
    open_challenge,
    submit_candidate_proof,
)
from proof_cli.references import ReferenceRecord, ReferenceReviewStatus, ReferenceSourceType
from proof_cli.storage import (
    ensure_project,
    get_active_claim,
    import_reference,
    list_blockers,
    list_obligations,
    list_references,
)
from proof_cli.theorems import add_theorem, list_theorems

runner = CliRunner()

# commands that don't return: a server, a browser
SKIPPED = {("review", "serve"), ("review", "open")}
PLUGIN_SERVER = Path(__file__).resolve().parents[1] / "plugins" / "proof-routing" / "scripts" / "proof_mcp_server.py"


def _submit(store, node_id, claimant="agent_a", session="s"):
    claim = claim_node(store, node_id, claimant_id=claimant, session_id=session)
    submit_candidate_proof(
        store, node_id, claimant_id=claimant, session_id=session, scoping_rationale="scoped", content=f"proof of {node_id}", claim_token=claim.claim_token
    )


def _rich_project(root: Path):
    store = ensure_project(root)
    reviewer = researcher(store)
    create_node(store, node_id="lem_a", kind="lemma", statement="A")
    _submit(store, "lem_a")
    reviewer.decide_acceptance("lem_a", "accept")
    create_node(store, node_id="clm_b", kind="claim", statement="B", dependencies=["lem_a"])
    _submit(store, "clm_b")
    reviewer.decide_acceptance("clm_b", "accept")
    create_node(store, node_id="rej", kind="claim", statement="R")
    _submit(store, "rej")
    reviewer.decide_acceptance("rej", "reject")
    create_node(store, node_id="rev", kind="claim", statement="V")
    _submit(store, "rev")  # awaiting review
    create_node(store, node_id="ref", kind="imported_result", statement="K", source_locator="doi:k", source_version="v1")
    reviewer.decide_reference_review("ref")
    create_node(store, node_id="clm_c", kind="claim", statement="C")
    claim_node(store, "clm_c", claimant_id="agent_owner", session_id="owner_session")  # someone else's claim
    dismissed = open_challenge(store, "lem_a", opened_by="agent_x", rationale="old worry")
    reviewer.dismiss_challenge(dismissed.id, rationale="checked")
    open_challenge(store, "clm_b", opened_by="agent_x", rationale="open worry")
    add_theorem(store, theorem_id="thm_t", kind="lemma", name="T", statement="T", status=TheoremStatus.verified, trust_level=TrustLevel.project_verified)
    import_reference(store, ReferenceRecord(id="ref_std", title="Std", authors=["A"], year=2020, source_type=ReferenceSourceType.standard_reference, origin="zbmath"))
    seed_reference_review(store, "ref_std", ReferenceReviewStatus.approved)
    add_obligation(store, ProofObligation(id="obl_1", goal_statement="G", required_for="thm_t"))
    add_blocker(store, BlockerRecord(id="blk_1", description="stuck", scope="thm_t", failure_type="gap"))
    return store


def _protected(store) -> dict:
    nodes = {}
    for node in list_nodes(store):
        judged = get_reference_review_state if node.kind.value == "imported_result" else get_acceptance_state
        nodes[node.id] = (get_node(store, node.id).kind.value, judged(store, node.id))
    claims = {}
    for node in list_nodes(store):
        claim = get_active_claim(store, node.id)
        if claim is not None:  # a new claim on a free node is ordinary agent work; a held one must stay held
            claims[node.id] = (claim.id, claim.claimant_id)
    return {
        "nodes": nodes,
        "challenges": {c.id: c.status.value for c in list_challenges(store)},
        "claims": claims,
        "theorems": {t.id: (t.status.value, t.trust_level.value) for t in list_theorems(store)},
        "references": {r.id: (r.review_status.value, r.is_callable) for r in list_references(store)},
        "obligations": {o.id: o.status.value for o in list_obligations(store)},
        "blockers": {b.id: b.status.value for b in list_blockers(store)},
    }


class _Pristine:
    """The project and the user config as the walk found them, restored before every command.

    Without this, one command's leftovers change what the next one reaches
    — `theorem add obl_1` made `verify run obl_1` verify a theorem instead of
    the obligation, hiding #27. The database is written back in place with
    SQLite's backup, so it stays the same file and long-lived connections see
    the change; every other file is copied back.
    """

    def __init__(self, store, snapshot_dir: Path) -> None:
        self.store = store
        self.live_db = {store.db_path.with_name(store.db_path.name + suffix) for suffix in ("", "-wal", "-shm", "-journal")}
        self.db_copy = snapshot_dir / "project.sqlite3"
        self.dirs = {store.root: snapshot_dir / "project", Path(os.environ["PROOF_CLI_CONFIG_HOME"]): snapshot_dir / "config"}
        snapshot_dir.mkdir(parents=True)
        self._backup(store.db_path, self.db_copy)
        for live_dir, copy_dir in self.dirs.items():
            shutil.copytree(live_dir, copy_dir, ignore=self._the_live_db)

    @staticmethod
    def _backup(source: Path, target: Path) -> None:
        with contextlib.closing(sqlite3.connect(source)) as src, contextlib.closing(sqlite3.connect(target)) as dst:
            src.backup(dst)

    def _the_live_db(self, directory, names):
        return [name for name in names if Path(directory) / name in self.live_db]

    def restore(self) -> None:
        self._backup(self.db_copy, self.store.db_path)
        for live_dir, copy_dir in self.dirs.items():
            for path in sorted(live_dir.rglob("*"), reverse=True):
                if path in self.live_db or not path.exists() or (copy_dir / path.relative_to(live_dir)).exists():
                    continue
                shutil.rmtree(path) if path.is_dir() else path.unlink()
            shutil.copytree(copy_dir, live_dir, dirs_exist_ok=True)


def _commands(group: click.Group, prefix=()):
    for name, command in sorted(group.commands.items()):
        path = (*prefix, name)
        if isinstance(command, click.Group):
            yield from _commands(command, path)
        elif path not in SKIPPED:
            yield path, command


# free-text slots rotate through the words an agent would try to talk its way past a check with
WORDS = ["accept", "verified", "approved", "project_verified", "resolved", "dismissed", "lemma", "trusted", "foundational", "callable"]
ACTOR_OPTIONS = {"--claimant", "--claimant-id", "--actor", "--reviewer", "--reviewer-id", "--promoted-by", "--opened-by", "--approved-by", "--created-by", "--updated-by"}


def _value(param: click.Parameter, target: str, turn: int) -> str:
    """A value for one parameter: the target where an id goes, else something the type accepts."""
    name = (param.opts[0] if isinstance(param, click.Option) else param.name).lstrip("-").replace("_", "-")
    if isinstance(param.type, click.Choice):
        return param.type.choices[turn % len(param.type.choices)]
    if isinstance(param.type, (click.types.IntParamType, click.types.FloatParamType)):
        return "2020"
    if isinstance(param, click.Option) and param.opts[0] in ACTOR_OPTIONS:
        return "agent_owner"
    if name in ("session", "session-id"):
        return "owner_session"
    if name == "child":
        return f"x{turn}=y"
    if "json" in name:
        return "[]"
    if name.endswith("id") or name in ("target", "node", "dependency", "depends-on", "parent", "reference", "theorem"):
        return target
    return WORDS[turn % len(WORDS)]


def _invocations(path, command, root: Path, targets: list[str]):
    """Each target in the first positional, the other slots filled so the command runs, and every flag set."""
    positionals = [param for param in command.params if isinstance(param, click.Argument)]
    options = [param for param in command.params if isinstance(param, click.Option) and param.opts[0] not in ("--json", "--help", "--root")]
    has_root = any(isinstance(param, click.Option) and param.opts[0] == "--root" for param in command.params)
    for turn, target in enumerate(targets if positionals else targets[:1]):
        args: list[str] = [*path]
        for index, param in enumerate(positionals):
            args.append(target if index == 0 else _value(param, target, turn))
        for option in options:
            if option.is_flag:
                args.append(option.opts[0])
            elif option.required or turn % 2 == 0:  # optional values on every other turn, so bare defaults run too
                args += [option.opts[0], _value(option, target, turn)]
        if has_root:
            args += ["--root", str(root)]
        yield args


def test_no_command_changes_any_protected_state(tmp_path: Path, monkeypatch):
    root = tmp_path / "project"
    store = _rich_project(root)
    monkeypatch.chdir(root)
    monkeypatch.setenv("PROOF_CLI_ROOT", str(root))
    baseline = _protected(store)
    challenge_ids = list(baseline["challenges"])
    review_ids = [review.id for review in list_review_records(store)]
    own_bundle = bundle_to_json(export_exchange_bundle(store))
    foreign_bundle = bundle_to_json(export_exchange_bundle(_rich_project(tmp_path / "foreign")))
    targets = ["lem_a", "clm_b", "rej", "rev", "ref", "clm_c", *challenge_ids, *review_ids, "thm_t", "ref_std", "obl_1", "blk_1", own_bundle, foreign_bundle]

    pristine = _Pristine(store, tmp_path / "pristine")
    walked = 0
    changed = []
    for path, command in _commands(typer.main.get_command(app)):
        pristine.restore()
        for args in _invocations(path, command, root, targets):
            runner.invoke(app, args, catch_exceptions=True)
            walked += 1
        # checked per command, not per invocation: the check is what's slow
        now = _protected(store)
        for section, before in baseline.items():
            for key, value in before.items():
                if now[section].get(key) != value:
                    changed.append((" ".join(path), section, key, value, now[section].get(key)))

    assert not changed, changed
    assert walked > 1000  # the whole tree, not a sample


def test_the_mcp_tools_only_reach_codex_routes():
    """Every MCP tool shells out to `proof codex …`, whose routes the walk above covers."""
    tree = ast.parse(PLUGIN_SERVER.read_text())
    tools = [node for node in tree.body if isinstance(node, ast.FunctionDef) and any(
        isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "tool" for d in node.decorator_list
    )]
    assert tools
    for tool in tools:
        calls = {call.func.id for call in ast.walk(tool) if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)}
        assert calls <= {"_run_proof_codex", "_effective_root", "str", "list", "dict", "RuntimeError"}, (tool.name, calls)
        for literal in ast.walk(tool):
            if isinstance(literal, ast.List) and literal.elts and getattr(literal.elts[0], "value", None) == "proof":
                assert getattr(literal.elts[1], "value", None) == "codex", tool.name


def test_adding_a_theorem_that_exists_does_not_replace_its_trust(tmp_path: Path):
    """A new version over a verified contract used to quietly reset it to a draft — found by the walk above."""
    store = ensure_project(tmp_path)
    add_theorem(store, theorem_id="thm_t", kind="lemma", name="T", statement="T", status=TheoremStatus.verified, trust_level=TrustLevel.project_verified)
    for args in (["theorem", "add", "thm_t", "T", "T2", "--root", str(tmp_path)], ["codex", "new", "theorem", "thm_t", "T", "T2", "--root", str(tmp_path)]):
        runner.invoke(app, args)
        (theorem,) = list_theorems(store)
        assert (theorem.statement, theorem.status, theorem.trust_level) == ("T", TheoremStatus.verified, TrustLevel.project_verified)


def test_an_imported_claim_stays_bound_to_a_token_nobody_here_holds(tmp_path: Path):
    """Naming the claimant and session of an imported claim must not make you its holder."""
    from proof_cli.exchange import bundle_from_json, import_exchange_bundle
    from proof_cli.proof_map import ProofMapError, release_node

    source = ensure_project(tmp_path / "source")
    create_node(source, node_id="clm_c", kind="claim", statement="C")
    claim_node(source, "clm_c", claimant_id="agent_owner", session_id="owner_session")
    target = ensure_project(tmp_path / "target")
    import_exchange_bundle(target, bundle_from_json(bundle_to_json(export_exchange_bundle(source))))

    claim = get_active_claim(target, "clm_c")
    assert claim is not None and claim.has_token
    with pytest.raises(ProofMapError):
        release_node(target, "clm_c", claimant_id="agent_owner", session_id="owner_session")
    assert get_active_claim(target, "clm_c") is not None


def test_a_refusal_outside_a_project_does_not_create_one(tmp_path: Path):
    result = runner.invoke(app, ["node", "review", "lem_a", "--root", str(tmp_path), "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error"]["code"] == "HUMAN_REVIEW_REQUIRED"
    assert not (tmp_path / ".proof").exists()


def test_a_reference_that_exists_is_not_imported_over(tmp_path: Path):
    store = ensure_project(tmp_path)
    import_reference(store, ReferenceRecord(id="ref_std", title="Std", authors=["A"], year=2020, source_type=ReferenceSourceType.standard_reference, origin="zbmath"))
    seed_reference_review(store, "ref_std", ReferenceReviewStatus.approved)
    result = runner.invoke(app, ["reference", "import", "ref_std", "Std again", "2021", "--root", str(tmp_path)])
    assert result.exit_code == 1 and "already exists" in result.output
    (reference,) = list_references(store)
    assert (reference.title, reference.review_status, reference.is_callable) == ("Std", ReferenceReviewStatus.approved, True)


def test_importing_a_bundle_keeps_every_local_record_it_names(tmp_path: Path):
    """Re-importing the project's own export (or a copy's) overwrites nothing and completes."""
    from proof_cli.exchange import import_exchange_bundle

    store = _rich_project(tmp_path / "project")
    before = _protected(store)
    report = import_exchange_bundle(store, export_exchange_bundle(_rich_project(tmp_path / "copy")))
    assert _protected(store) == before
    assert any("already exists here" in warning for warning in report.warnings)
