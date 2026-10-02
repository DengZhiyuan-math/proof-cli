"""The studio's agent panel is the node's proof agent (ADR-0011 point 8, #72).

A stub Claude Code (tests/js is not needed here: a small Python script on CLAUDE_BIN) records
how the studio started it and runs the `proof` commands a turn would, so the tests check the
real launch: its cwd, PROOF_ROOT, its permissions, and what Undo does and doesn't restore.
"""

import json
import os
import stat
import sys
import time
from pathlib import Path

import pytest

from _proofs import write_key_ideas
from proof_cli.proof_map import add_dependency, create_node, get_acceptance_state, get_active_claim, get_node, list_candidate_proofs
from proof_cli.storage import ensure_project
from proof_cli.studio.backends import Job
from proof_cli.studio.backend_codex import Codex
from proof_cli.studio.proof_agent import ProofAgentContext, library_folders
from proof_cli.webapp.studios import StudioHub

SRC = Path(__file__).resolve().parents[1] / "src"

FAKE_CLAUDE = r'''#!{python}
import json, os, subprocess, sys
if sys.argv[1:3] == ["auth", "status"]:
    print(json.dumps({{"loggedIn": True, "email": "stub@example.org"}})); sys.exit(0)
prompt = sys.stdin.read()
log = {{"argv": sys.argv[1:], "cwd": os.getcwd(), "PROOF_ROOT": os.environ.get("PROOF_ROOT"), "ran": []}}
for command in json.loads(os.environ.get("FAKE_SCRIPT", "[]")):
    if command[0] == "write":
        path = os.path.join(os.getcwd(), command[1]); os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w").write(command[2]); continue
    done = subprocess.run(command, capture_output=True, text=True)
    log["ran"].append({{"argv": command, "code": done.returncode, "out": done.stdout[-2000:], "err": done.stderr[-2000:]}})
open(os.environ["FAKE_LOG"], "w").write(json.dumps(log))
print(json.dumps({{"type": "system", "subtype": "init", "session_id": "stub-session", "model": "stub"}}))
print(json.dumps({{"type": "result", "session_id": "stub-session", "is_error": False, "subtype": "success"}}))
'''


def _executable(path: Path, text: str) -> Path:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.fixture
def studio(tmp_path: Path, monkeypatch):
    """A project with node A, a stub Claude Code, and `proof` running this checkout."""
    project = tmp_path / "project"
    store = ensure_project(project)
    create_node(store, node_id="A", kind="claim", statement="a claim")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _executable(bin_dir / "claude", FAKE_CLAUDE.format(python=sys.executable))
    _executable(bin_dir / "proof", f'#!/bin/sh\nexec "{sys.executable}" -m proof_cli.cli "$@"\n')
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("PYTHONPATH", f"{SRC}{os.pathsep}{os.environ.get('PYTHONPATH', '')}")
    monkeypatch.setenv("CLAUDE_BIN", str(bin_dir / "claude"))
    monkeypatch.delenv("PROOF_ROOT", raising=False)
    monkeypatch.delenv("PROOF_CLAUDE_ACCOUNT", raising=False)
    log = tmp_path / "claude-log.json"
    monkeypatch.setenv("FAKE_LOG", str(log))
    hub = StudioHub(store)
    yield store, hub, log, monkeypatch
    hub.close()


def _turn(hub, monkeypatch, script, mode="edit"):
    monkeypatch.setenv("FAKE_SCRIPT", json.dumps(script))
    agent = hub.studio("A").agent
    started = agent.start("prove the node", None, mode, provider="claude")
    assert "job" in started, started
    job = agent.jobs[started["job"]]
    deadline = time.monotonic() + 60
    while not job.done and time.monotonic() < deadline:
        time.sleep(0.05)
    assert job.done
    return started["job"]


def _log(log: Path) -> dict:
    return json.loads(log.read_text())


# -- rooted at the project -------------------------------------------------------------


def test_a_turn_runs_in_the_node_folder_and_its_proof_calls_act_on_the_project(studio):
    store, hub, log, monkeypatch = studio
    _turn(hub, monkeypatch, [["proof", "node", "claim", "A", "--assignee", "studio-agent", "--json"]])

    ran = _log(log)
    assert Path(ran["cwd"]).resolve() == (store.root / "proofs" / "A").resolve()
    assert ran["PROOF_ROOT"] == str(store.root)
    assert ran["ran"][0]["code"] == 0, ran["ran"][0]
    assert get_active_claim(store, "A").claimant_id == "studio-agent"
    assert not (store.root / "proofs" / "A" / ".proof").exists()  # never a nested project


def test_no_agent_turn_can_record_a_human_review_decision(studio):
    store, hub, log, monkeypatch = studio
    (store.root / "proofs" / "A" / "proof.tex").write_text("a proof\n")
    _turn(hub, monkeypatch, [
        ["proof", "node", "request-review", "A", "--rationale", "scoped", "--requested-by", "studio-agent", "--json"],
        ["proof", "node", "review", "A", "accept", "--json"],
    ])
    review = _log(log)["ran"][1]
    assert json.loads(review["out"])["error"]["code"] == "HUMAN_REVIEW_REQUIRED"
    assert get_acceptance_state(store, "A") == "unreviewed"


# -- explicit permissions, not inherited ------------------------------------------------


def test_claude_code_gets_the_proof_agents_permissions_and_none_of_the_repositorys(studio, tmp_path):
    store, hub, log, monkeypatch = studio
    papers = tmp_path / "papers"
    papers.mkdir()
    (store.root / "proof.toml").write_text(f'[studio]\nlibrary = ["{papers}"]\n')
    _turn(hub, monkeypatch, [])

    argv = _log(log)["argv"]
    value = lambda flag: argv[argv.index(flag) + 1]  # noqa: E731
    assert value("--setting-sources") == "user"  # not the project's settings or Bash allowlist
    assert value("--permission-prompts") == "none"  # nobody is there to approve: refused, never hung
    excluded = json.loads(value("--settings"))["claudeMdExcludes"]  # nor the repository's CLAUDE.md
    for name in ("CLAUDE.md", "AGENTS.md"):
        assert f"{store.root}/{name}" in excluded and f"{store.root}/**/{name}" in excluded
        assert f"{store.root.parent}/{name}" in excluded
    assert not [path for path in excluded if path.endswith("/.claude/CLAUDE.md") and not path.startswith(str(store.root))]
    assert value("--permission-mode") == "default"  # a headless run refuses whatever no rule allows
    add = argv[argv.index("--add-dir") + 1:argv.index("--allowedTools")]
    assert add == [str(store.root), str(papers)]
    allowed = argv[argv.index("--allowedTools") + 1:argv.index("--disallowedTools")]
    for rule in ("WebSearch", "WebFetch", "Bash(proof *)", "Bash(python *)", "Bash(sage *)", "Bash(lean *)", "Edit(./**)", "Write(./**)"):
        assert rule in allowed, rule
    denied = argv[argv.index("--disallowedTools") + 1:]
    for rule in ("Edit(./snapshots/**)", "Write(./build/**)", "Edit(./reviews.jsonl)"):
        assert rule in denied, rule
    brief = value("--append-system-prompt")
    assert "Retrieval first" in brief and "request-review A" in brief and str(papers) in brief


def test_an_ask_turn_can_read_and_search_but_not_edit(studio):
    store, hub, log, monkeypatch = studio
    _turn(hub, monkeypatch, [], mode="ask")
    argv = _log(log)["argv"]
    allowed = argv[argv.index("--allowedTools") + 1:argv.index("--disallowedTools")]
    assert argv[argv.index("--permission-mode") + 1] == "plan"
    assert "WebSearch" in allowed and not [rule for rule in allowed if rule.startswith(("Edit", "Write"))]


def test_codex_gets_web_search_the_project_and_the_network_but_not_the_projects_agents_md(tmp_path):
    job = Job(1)
    job.mode, job.prompt = "edit", "prove it"
    job.context = ProofAgentContext("A", tmp_path, [])
    argv, prompt = Codex("codex").command(job)
    assert argv[1:3] == ["--search", "exec"]  # a global flag, before the subcommand
    assert argv[argv.index("--add-dir") + 1] == str(tmp_path)  # proof writes the project database
    assert "sandbox_workspace_write.network_access=true" in argv
    # nor the repository's AGENTS.md, which Codex loads on its own (PR #79 review): project docs off
    assert argv[argv.index("project_doc_max_bytes=0") - 1] == "-c"
    assert "Retrieval first" in prompt


# -- the library is read, never written -------------------------------------------------


def test_a_library_folder_is_listed_readable_and_never_writable(studio, tmp_path):
    store, hub, log, monkeypatch = studio
    papers = tmp_path / "papers"
    papers.mkdir()
    (store.root / "proof.toml").write_text('[studio]\nlibrary = ["../papers", "/does/not/exist"]\n')
    assert library_folders(store.root) == [papers.resolve()]
    studio_a = hub.studio("A")
    with pytest.raises(ValueError):
        studio_a.agent_writable(str(Path("..") / ".." / ".." / "papers" / "x.tex"))
    context = ProofAgentContext("A", store.root, library_folders(store.root))
    assert not [rule for rule in context.claude_args(True) if str(papers) in rule and rule.startswith(("Edit", "Write"))]


# -- Undo covers files only ---------------------------------------------------------------


def test_undo_restores_the_turns_files_and_leaves_its_split(studio):
    store, hub, log, monkeypatch = studio
    folder = store.root / "proofs" / "A"
    before = (folder / "proof.tex").read_text()
    turn = _turn(hub, monkeypatch, [
        ["write", "proof.tex", "the agent's proof\n"],
        ["write", "scratch/check.py", "print(2 + 2)\n"],
        ["proof", "node", "split", "A", "--child", "A1=a smaller claim", "--created-by", "studio-agent", "--json"],
    ])
    assert get_node(store, "A").dependencies == ["A1"]

    undone = hub.studio("A").agent.undo(turn)

    assert sorted(undone["restored"]) == ["proof.tex", "scratch/check.py"]
    assert (folder / "proof.tex").read_text() == before and not (folder / "scratch" / "check.py").exists()
    assert get_node(store, "A").dependencies == ["A1"] and get_node(store, "A1") is not None  # the split stays


def test_the_panel_says_undo_covers_files_and_runs_on_the_clis_only(studio):
    store, hub, log, monkeypatch = studio
    app_js = (SRC / "proof_cli" / "studio" / "static" / "app.js").read_text()
    assert "Undo this turn's file changes" in app_js and "does not undo a claim, a split" in app_js
    info = hub.studio("A").agent.info()
    assert info["proof_agent"] and sorted(p["kind"] for p in info["providers"]) == ["claude", "codex"]  # the CLIs only


def test_scratch_files_are_not_part_of_a_snapshot(studio):
    from proof_cli.proof_map import request_review

    store, hub, log, monkeypatch = studio
    folder = store.root / "proofs" / "A"
    (folder / "scratch").mkdir()
    (folder / "scratch" / "check.py").write_text("print(1)\n")
    write_key_ideas(store, "A")
    record = request_review(store, "A", requested_by="studio-agent", rationale="scoped")
    manifest = json.loads((store.root / record.file_path).read_text()) if record.file_path.endswith(".json") else {"files": {}}
    assert not [name for name in manifest.get("files", {}) if name.startswith("scratch/")]
    assert [p.version for p in list_candidate_proofs(store, "A")] == [1]


# -- PR #79 review: no inherited project rules; the API assistant reads the library -----------


def test_no_backend_tells_the_proof_agent_to_follow_the_repositorys_rules(studio, tmp_path):
    store, hub, log, monkeypatch = studio
    for folder in (store.root, store.root / "proofs" / "A"):
        (folder / "AGENTS.md").write_text("REPOSITORY RULE: commit everything\n")
        (folder / "CLAUDE.md").write_text("REPOSITORY RULE: commit everything\n")
    _turn(hub, monkeypatch, [])
    argv = _log(log)["argv"]
    claude_prompt = argv[argv.index("--append-system-prompt") + 1]

    job = Job(1)
    job.mode, job.prompt, job.root = "edit", "prove it", store.root / "proofs" / "A"
    job.context = ProofAgentContext("A", store.root, [])
    codex_prompt = Codex("codex").command(job)[1]

    ask = Job(2)
    ask.mode, ask.prompt, ask.root, ask.context = "ask", "look", job.root, job.context
    assert "project_doc_max_bytes=0" in Codex("codex").command(ask)[0]  # an Ask turn too

    for prompt in (claude_prompt, codex_prompt):
        assert "follow it exactly" not in prompt and "REPOSITORY RULE" not in prompt
        assert "Retrieval first" in prompt


# -- ADR-0013: the key-ideas summary, written by the Typesetter's turn ------------------------------


def test_the_standing_brief_asks_for_the_key_ideas_before_review(studio):
    store, hub, log, monkeypatch = studio
    brief = hub.studio("A").agent.context_fn().brief()
    assert "key-ideas.md" in brief and brief.index("key-ideas.md") < brief.index("request-review A")


def test_the_typesetters_brief_names_the_proof_the_dependencies_and_the_four_fields(studio):
    """The Typesetter writes the key-ideas summary (spec #145); its brief says how, with the node's dependencies as of
    the turn. Whatever agent turn writes key-ideas.md is recorded as that agent's draft: tests/test_agent_run.py."""
    store, hub, log, monkeypatch = studio
    create_node(store, node_id="L", kind="lemma", statement="a lemma")
    add_dependency(store, "A", "L", edited_by="author")
    context = hub.studio("A").agent.context_fn({"role": "typesetter", "name": "claude-code"})  # made fresh each turn
    assert context.dependencies == ["L"]
    brief = context.brief()
    for text in ("key-ideas.md", "proof.tex", "L (../L/)", "## 核心思路", "## 主要步骤", "## 难点", "## 未覆盖", "$…$"):
        assert text in brief, text
    assert "## 核心思路" not in hub.studio("A").agent.context_fn({"role": "prover", "name": "claude-code"}).brief()


def test_the_old_prompt_driven_drafting_route_is_gone(studio):
    store, hub, log, monkeypatch = studio
    assert hub.studio("A").post("/api/key-ideas/draft", {"provider": "claude"}).status == 404


def test_the_standing_brief_says_where_a_difficulty_and_its_experiments_go(studio):
    """A difficulty the agent can't state goes in the Proof fog, and a computation about one is an Experiment (spec #136)."""
    store, hub, log, monkeypatch = studio
    brief = hub.studio("A").agent.context_fn().brief()
    assert "proof fog add" in brief and "--near A" in brief
    assert "proof fog experiment record" in brief and "proofs/A/scratch/" in brief
    assert brief.index("proof fog") > brief.index("evidence record")  # after the proof's own steps
