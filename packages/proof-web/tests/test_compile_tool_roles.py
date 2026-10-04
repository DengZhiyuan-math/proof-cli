"""Which turn gets the compile tool (latex-agent's `mcp_compile.py`) is decided by the role's context (proof-agents'
`ProofAgentContext.compiles`), read by either backend without importing it: the Typesetter and the solo agent do,
the Prover and Numerics don't, on Claude Code and on Codex alike (upstream 2938c05; fourth review F3)."""

import json
import sys
from unittest import mock

import pytest

from latex_agent import backends
from latex_agent.backend_claude import ClaudeCode
from latex_agent.backend_codex import Codex
from proof_agents.proof_agent import ProofAgentContext


def job_for(**kw):
    job = backends.Job(1)
    for key, value in kw.items():
        setattr(job, key, value)
    return job


@pytest.fixture
def claude():
    with mock.patch("latex_agent.backend_claude.allowed_account", return_value=""):  # never run the real `claude auth status`
        yield ClaudeCode("claude", {"bin": "claude"})  # never actually started


def test_a_role_that_does_not_typeset_has_no_tool(claude, tmp_path):
    for role, expected in (("prover", False), ("numerics", False), ("typesetter", True), (None, True)):
        ctx = ProofAgentContext("N", tmp_path, role=role)
        cmd, _ = claude.command(job_for(mode="edit", root=tmp_path, server_url="http://127.0.0.1:9/studio/N/", context=ctx))
        assert ("--mcp-config" in cmd) is expected, role


def test_codex_gets_the_same_tool_through_its_configuration(tmp_path):
    codex = Codex("codex", {"bin": "codex"})
    ctx = ProofAgentContext("N", tmp_path, role="typesetter")
    cmd, _ = codex.command(job_for(mode="edit", root=tmp_path, server_url="http://127.0.0.1:9/studio/N/", context=ctx))
    overrides = [cmd[i + 1] for i, x in enumerate(cmd) if x == "-c"]
    command = next(o for o in overrides if o.startswith("mcp_servers.studio.command="))
    args = next(o for o in overrides if o.startswith("mcp_servers.studio.args="))
    assert json.loads(command.split("=", 1)[1]) == sys.executable
    assert json.loads(args.split("=", 1)[1])[1:] == ["--url", "http://127.0.0.1:9/studio/N/"]
    assert json.loads(args.split("=", 1)[1])[0].endswith("latex_agent/mcp_compile.py")
    for job in (job_for(mode="ask", root=tmp_path, server_url="http://127.0.0.1:9/studio/N/", context=ctx),
                job_for(mode="edit", root=tmp_path, server_url="http://127.0.0.1:9/studio/N/", context=ProofAgentContext("N", tmp_path, role="prover")),
                job_for(mode="edit", root=tmp_path, context=ctx)):
        assert not any(x.startswith("mcp_servers.") for x in codex.command(job)[0]), job.mode
