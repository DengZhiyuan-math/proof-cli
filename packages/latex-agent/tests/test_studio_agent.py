"""Unit tests for the agent manager and its backends (latex_agent/agent.py, backend_*.py).

No real CLI is started: the Claude Code and Codex backends are checked through the
command they would run and the events they make from sample output.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from latex_agent import agent, backends
from latex_agent.backend_claude import ClaudeCode
from latex_agent.backend_codex import Codex
from studio_tmpdirs import tmpdir


def manager(root=Path("."), files=lambda: [], **kinds):
    """An AgentManager whose backends are exactly `kinds` (id -> Backend)."""
    return agent.AgentManager(lambda: Path(root), files, backends=(kinds, next(iter(kinds)), None))


def job_for(**kw):
    j = backends.Job(1)
    for k, v in kw.items():
        setattr(j, k, v)
    return j


def no_account_lock(test):
    """Ignore the allowed Claude account in the user's own settings, which would make a
    test run the real `claude auth status`."""
    from unittest import mock
    patcher = mock.patch("latex_agent.backend_claude.allowed_account", return_value="")
    patcher.start()
    test.addCleanup(patcher.stop)


class ModelAndEffort(unittest.TestCase):
    def setUp(self):
        no_account_lock(self)
        self.claude = ClaudeCode("claude", {"bin": "claude"})     # never actually started
        self.m = manager(claude=self.claude)

    def test_model_names(self):
        for ok in ("opus", "sonnet[1m]", "claude-opus-5-5", "opusplan", "deepseek-chat",
                   "deepseek/deepseek-chat"):
            self.assertTrue(agent.MODEL_RE.fullmatch(ok), ok)
        for bad in ("--dangerously-skip-permissions", "-x", "a b", ""):
            self.assertFalse(agent.MODEL_RE.fullmatch(bad), bad)

    def test_rejects_flags_as_model_and_unknown_effort(self):
        self.assertIn("error", self.m.start("hi", None, "ask", model="--dangerously-skip-permissions"))
        self.assertIn("error", self.m.start("hi", None, "ask", effort="turbo"))
        self.assertIn("error", self.m.start("hi", None, "ask", provider="nope"))
        self.assertIsNone(self.m.active)

    def test_efforts_are_per_backend(self):
        codex = Codex("codex", {"bin": "codex"})
        self.assertIsNone(codex.check(None, "minimal"))
        self.assertIsNotNone(codex.check(None, "max"))


class ClaudeScope(unittest.TestCase):
    """The scope note comes from the manager; the permission rules from the backend."""

    def setUp(self):
        no_account_lock(self)
        self.claude = ClaudeCode("claude", {"bin": "claude"})
        self.m = manager(claude=self.claude)
        self.jobs = []
        self.m._run = lambda job, backend: self.jobs.append(job)    # never start Claude

    def cmd(self):
        for _ in range(50):
            if self.jobs:
                return self.claude.command(self.jobs[-1])           # (argv, stdin)
            time.sleep(0.02)
        self.fail("no job")

    def test_mentions_allow_only_those_files(self):
        self.m.start("hi", None, "edit", scope=["main.tex", "sections/intro.tex"])
        cmd, prompt = self.cmd()
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "default")
        rules = cmd[cmd.index("--allowedTools") + 1:]
        self.assertIn("Edit(./main.tex)", rules)
        self.assertIn("Write(./sections/intro.tex)", rules)
        self.assertTrue(prompt.startswith("hi"))
        self.assertIn("ONLY these files in this turn: main.tex, sections/intro.tex", prompt)

    def test_no_mentions_edit_anything(self):
        self.m.start("/code-review", None, "edit")
        cmd, prompt = self.cmd()
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "acceptEdits")
        self.assertNotIn("--allowedTools", cmd)
        self.assertTrue(prompt.startswith("/code-review"), "a /command must stay first")
        self.assertIn("no longer apply", prompt)

    def test_ask_mode_ignores_scope(self):
        self.m.start("hi", None, "ask", scope=["main.tex"])
        cmd, prompt = self.cmd()
        self.assertEqual(cmd[cmd.index("--permission-mode") + 1], "plan")
        self.assertNotIn("--allowedTools", cmd)


class CodexBackend(unittest.TestCase):
    def setUp(self):
        self.codex = Codex("codex", {"bin": "codex"})

    def test_command(self):
        cmd, prompt = self.codex.command(job_for(mode="ask", prompt="hi", model="gpt-5-codex",
                                                 effort="high"))
        self.assertEqual(cmd[:2], ["codex", "exec"])
        self.assertEqual(cmd[cmd.index("--sandbox") + 1], "read-only")
        self.assertIn("model_reasoning_effort=high", cmd)
        self.assertEqual(cmd[-1], "-", "the prompt comes on stdin")
        self.assertIn("prism-local", prompt, "a new conversation carries the editor's rules")
        cmd, prompt = self.codex.command(job_for(mode="edit", prompt="more", session_id="t-1"))
        self.assertEqual(cmd[cmd.index("--sandbox") + 1], "workspace-write")
        self.assertEqual(cmd[-3:], ["resume", "t-1", "-"])
        self.assertEqual(prompt, "more")

    def test_events(self):
        root = Path(tempfile.gettempdir()).resolve()
        lines = [
            {"type": "thread.started", "thread_id": "t-9"},
            {"type": "turn.started"},
            {"type": "item.started", "item": {"id": "i1", "type": "command_execution",
                                              "command": "ls", "status": "in_progress"}},
            {"type": "item.completed", "item": {"id": "i1", "type": "command_execution",
                                                "command": "ls", "exit_code": 1,
                                                "aggregated_output": "boom", "status": "failed"}},
            {"type": "item.completed", "item": {"id": "i2", "type": "file_change",
                                                "changes": [{"path": str(root / "main.tex"),
                                                             "kind": "update"}],
                                                "status": "completed"}},
            {"type": "item.completed", "item": {"id": "i3", "type": "agent_message",
                                                "text": "Done."}},
            {"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 3}},
        ]
        j, st = job_for(root=root), {}
        for d in lines:
            self.codex.handle(d, j, st)
        ev = j.events
        self.assertEqual(ev[0], {"t": "init", "session_id": "t-9", "model": None})
        self.assertEqual([e["t"] for e in ev[1:]],
                         ["tool", "tool_result", "tool", "tool_result", "message_start", "text"])
        self.assertTrue(ev[2]["error"])
        self.assertEqual(ev[3]["summary"], "main.tex")
        self.assertEqual(st["session_id"], "t-9")
        self.assertEqual(st["usage"], {"in": 10, "out": 3})


class RevertOutsideScope(unittest.TestCase):
    """A backend that cannot enforce the scope has its writes outside it undone."""

    def test_revert(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.tex").write_text("a\n", encoding="utf-8")
            (root / "b.tex").write_text("b\n", encoding="utf-8")

            class Wild(backends.Backend):
                enforces_scope = False

                def run(self, job):
                    (job.root / "a.tex").write_text("A\n", encoding="utf-8")
                    (job.root / "b.tex").write_text("B\n", encoding="utf-8")
                    return {"exit": 0}

            m = manager(root, lambda: ["a.tex", "b.tex"], wild=Wild("wild"))
            r = m.start("go", None, "edit", scope=["a.tex"])
            done = wait_done(m.jobs[r["job"]])
            self.assertEqual(done["reverted"], ["b.tex"])
            self.assertEqual([c["path"] for c in done["changed"]], ["a.tex"])
            self.assertEqual((root / "b.tex").read_text(encoding="utf-8"), "b\n")
            self.assertEqual((root / "a.tex").read_text(encoding="utf-8"), "A\n")


class Snapshots(unittest.TestCase):
    def test_undo_puts_back_the_exact_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.tex").write_bytes(b"one\r\ntwo\r\n")
            (root / "latin1.tex").write_bytes("caf\xe9\n".encode("latin-1"))   # not UTF-8

            class Edit(backends.Backend):
                def run(self, job):
                    (job.root / "a.tex").write_bytes(b"ONE\ntwo\n")
                    return {"exit": 0}

            m = manager(root, lambda: ["a.tex", "latin1.tex"], edit=Edit("edit"))
            r = m.start("go", None, "edit")
            done = wait_done(m.jobs[r["job"]])
            self.assertEqual([c["path"] for c in done["changed"]], ["a.tex"])
            self.assertEqual(list(m.turns[done["turn"]].before), ["a.tex"],
                             "only the changed files stay in memory")
            self.assertEqual(m.undo(done["turn"])["restored"], ["a.tex"])
            self.assertEqual((root / "a.tex").read_bytes(), b"one\r\ntwo\r\n")


def wait_done(job, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        evs, done = job.wait_events(0, 0.5)
        if done:
            return next(e for e in evs if e["t"] == "done")
    raise AssertionError("turn did not finish")


class Registry(unittest.TestCase):
    def test_the_clis_and_user_settings(self):
        """The studio runs the Claude Code or Codex CLI only: no API-model presets (#72)."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "agents.json"
            p.write_text(json.dumps({"default": "codex", "providers": {
                "codex": {"bin": "/tools/codex"},
                "claude-fast": {"type": "claude", "label": "Claude (fast)", "default_model": "haiku"}}}), encoding="utf-8")
            old = os.environ.pop("PRISM_AGENT", None)
            try:
                bs, default, err = backends.load_backends(p)
            finally:
                if old is not None:
                    os.environ["PRISM_AGENT"] = old
        self.assertIsNone(err)
        self.assertEqual(default, "codex")
        self.assertEqual(sorted(bs), ["claude", "claude-fast", "codex"])
        self.assertEqual(bs["codex"].bin(), "/tools/codex")
        self.assertEqual(bs["claude-fast"].default_model, "haiku")

    def test_an_api_model_provider_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "agents.json"
            p.write_text(json.dumps({"providers": {"vllm": {"type": "openai", "base_url": "http://gpu:8000/v1"}}}), encoding="utf-8")
            bs, default, err = backends.load_backends(p)
        self.assertNotIn("vllm", bs)
        self.assertIn("isn't supported", err)

    def test_bad_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "agents.json"
            p.write_text("{nope", encoding="utf-8")
            bs, default, err = backends.load_backends(p)
        self.assertIn("agents.json", err)
        self.assertIn("claude", bs)


class ClaudeAccountGuard(unittest.TestCase):
    """Only the account allowed in Home -> Settings may run turns (backend_claude)."""
    OK = {"logged_in": True, "email": "me@uni.example", "org": "Lab", "auth_method": "claude.ai",
          "api_provider": "firstParty", "overrides": []}

    def setUp(self):
        from latex_agent import backend_claude
        self.bc = backend_claude

    def test_no_allowed_account_means_no_check(self):
        self.assertIsNone(self.bc.account_problem({"logged_in": False}, ""))

    def test_matching_account_passes_case_insensitively(self):
        self.assertIsNone(self.bc.account_problem(self.OK, "Me@Uni.Example"))

    def test_refusals(self):
        allowed = "me@uni.example"
        cases = {
            "another account": {**self.OK, "email": "other@example.com"},
            "API key": {**self.OK, "overrides": ["the environment variable ANTHROPIC_API_KEY"]},
            "console login": {**self.OK, "auth_method": "console"},
            "bedrock": {**self.OK, "api_provider": "bedrock"},
            "logged out": {"logged_in": False, "overrides": []},
            "check failed": {"logged_in": False, "error": "boom", "overrides": []},
        }
        for name, info in cases.items():
            msg = self.bc.account_problem(info, allowed)
            self.assertTrue(msg, name)
            self.assertIn("me@uni.example", msg, name)

    def test_probes_are_checked_like_turns(self):
        """The usage probe and the command list start claude only for the allowed account."""
        from unittest import mock
        claude = ClaudeCode("claude", {"bin": "claude"})
        m = manager(claude=claude)
        refusal = "Claude Code is logged in as other@example.com, not me@uni.example."
        with mock.patch.object(claude, "preflight", return_value=refusal), \
                mock.patch("subprocess.run") as run, mock.patch("subprocess.Popen") as popen:
            self.assertEqual(m.probe_rate("claude")["error"], refusal)
            self.assertEqual(m.commands("claude", refresh=True)["error"], refusal)
            run.assert_not_called()
            popen.assert_not_called()

    def test_project_settings_that_switch_to_an_api_key_are_found(self):
        import json, tempfile
        root = tmpdir()
        (root / ".claude").mkdir()
        (root / ".claude" / "settings.json").write_text(json.dumps({"apiKeyHelper": "get-key.sh"}))
        (root / ".claude" / "settings.local.json").write_text(json.dumps({"env": {"ANTHROPIC_API_KEY": "x"}}))
        found = self.bc.auth_overrides(root)
        self.assertTrue(any("apiKeyHelper" in f for f in found))
        self.assertTrue(any("ANTHROPIC_API_KEY" in f and "settings.local.json" in f for f in found))


if __name__ == "__main__":
    unittest.main()


class ClaudeLiveEvents(unittest.TestCase):
    """Thinking and the text of a file being written reach the page while they stream (upstream 2938c05)."""

    def stream(self, *events):
        return [{"type": "stream_event", "parent_tool_use_id": None, "event": e} for e in events]

    def test_write_streams_its_content(self):
        root = Path(tempfile.gettempdir()).resolve()
        text = "\\documentclass{amsart}\n\\title{\"Primes\" é 😀}\n\ttab \\u0041\n"
        raw = json.dumps({"file_path": str(root / "sec" / "a.tex"), "content": text})
        frags = [raw[i:i + 3] for i in range(0, len(raw), 3)]  # cut anywhere, through escapes and surrogate pairs
        lines = self.stream(
            {"type": "message_start"},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking"}},
            {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "Plan the file."}},
            {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "tu1", "name": "Write", "input": {}}},
            *({"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": f}} for f in frags))
        j, st = job_for(root=root), {}
        cc = ClaudeCode("claude", {"bin": "claude"})
        for d in lines:
            cc.handle(d, j, st)
        ev = j.events
        self.assertEqual(ev[1:3], [{"t": "thinking_start"}, {"t": "thinking", "text": "Plan the file."}])
        self.assertEqual(ev[3], {"t": "tool_start", "id": "tu1", "name": "Write"})
        live = [e for e in ev if e["t"] == "tool_live"]
        self.assertEqual([e["path"] for e in live if "path" in e], ["sec/a.tex"])
        self.assertEqual("".join(e.get("text", "") for e in live), text)

    def test_edit_streams_old_and_new_text(self):
        root = Path(tempfile.gettempdir()).resolve()
        raw = json.dumps({"file_path": str(root / "main.tex"), "old_string": "a \\[x\\]", "new_string": "a \\begin{equation}x\\end{equation}"})
        lines = self.stream(
            {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "e1", "name": "Edit", "input": {}}},
            *({"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": raw[i:i + 4]}} for i in range(0, len(raw), 4)))
        j, st = job_for(root=root), {}
        cc = ClaudeCode("claude", {"bin": "claude"})
        for d in lines:
            cc.handle(d, j, st)
        live = [e for e in j.events if e["t"] == "tool_live"]
        self.assertEqual("".join(e.get("old", "") for e in live), "a \\[x\\]")
        self.assertEqual("".join(e.get("text", "") for e in live), "a \\begin{equation}x\\end{equation}")
        done = next(i for i, e in enumerate(live) if e.get("old_done"))
        self.assertFalse(any("text" in e for e in live[:done]), "the old text is complete first")

    def test_tools_say_where_they_work(self):
        root = Path(tempfile.gettempdir()).resolve()
        j, st = job_for(root=root), {}
        cc = ClaudeCode("claude", {"bin": "claude"})
        cc.handle({"type": "assistant", "parent_tool_use_id": None, "message": {"content": [
            {"type": "tool_use", "id": "r1", "name": "Read", "input": {"file_path": str(root / "sec" / "a.tex"), "offset": 20, "limit": 11}},
            {"type": "tool_use", "id": "r2", "name": "Read", "input": {"file_path": str(root / "b.tex")}},
            {"type": "tool_use", "id": "g1", "name": "Grep", "input": {"pattern": "x"}}]}}, j, st)
        r1, r2, g1 = j.events
        self.assertEqual((r1["path"], r1["lines"]), ("sec/a.tex", [20, 30]))
        self.assertEqual(r2["path"], "b.tex")
        self.assertNotIn("lines", r2, "a whole file is not a range to mark")
        self.assertNotIn("path", g1)

    def test_other_tools_stream_nothing(self):
        j, st = job_for(), {}
        cc = ClaudeCode("claude", {"bin": "claude"})
        for d in self.stream(
                {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "b", "name": "Bash", "input": {}}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"command": "ls"}'}}):
            cc.handle(d, j, st)
        self.assertEqual([e["t"] for e in j.events], ["tool_start"])

    def test_refused_steps_are_named(self):
        j, st = job_for(root=tmpdir()), {}
        ClaudeCode("claude", {"bin": "claude"}).handle({"type": "result", "permission_denials": [
            {"tool_name": "Bash", "tool_input": {"command": "latexmk -pdf main.tex"}}]}, j, st)
        self.assertEqual(st["denied"], [{"tool": "Bash", "what": "latexmk -pdf main.tex"}])


class CompileTool(unittest.TestCase):
    """The agent compiles with the node studio's own build (mcp_compile.py), not a shell (upstream 2938c05)."""

    def setUp(self):
        no_account_lock(self)
        self.claude = ClaudeCode("claude", {"bin": "claude"})

    def test_a_turn_with_a_studio_url_gets_the_tool_and_only_that_mcp_server(self):
        from latex_agent import backend_claude
        cmd, _ = self.claude.command(job_for(mode="edit", root=tmpdir(), compile_url="http://127.0.0.1:9/studio/L1/"))
        cfg = json.loads(cmd[cmd.index("--mcp-config") + 1])
        (name,) = cfg["mcpServers"]
        args = cfg["mcpServers"][name]["args"]
        self.assertEqual(name, "studio")
        self.assertEqual(Path(args[0]).parts[-2:], ("latex_agent", "mcp_compile.py"))
        self.assertEqual(args[1:], ["--url", "http://127.0.0.1:9/studio/L1/"])
        self.assertIn("--strict-mcp-config", cmd)
        self.assertIn(backend_claude.COMPILE_TOOL, cmd[cmd.index("--allowedTools") + 1:])

    def test_a_turn_without_a_studio_url_has_no_tool(self):
        cmd, _ = self.claude.command(job_for(mode="edit", root=tmpdir()))
        self.assertNotIn("--mcp-config", cmd)

    def test_an_ask_turn_has_no_tool(self):
        """Plan mode admits no tool that builds: offering it would only make a refused step."""
        cmd, _ = self.claude.command(job_for(mode="ask", root=tmpdir(), compile_url="http://127.0.0.1:9/studio/L1/"))
        self.assertNotIn("--mcp-config", cmd)

    def test_the_tool_posts_the_build_as_the_pages_own_origin(self):
        """proof-cli's server takes a write only from its own origin: the tool's request carries it."""
        from unittest import mock

        from latex_agent import mcp_compile
        seen = []

        class Answer:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b'{"exit": 0, "diagnostics": []}'

        with mock.patch("urllib.request.urlopen", side_effect=lambda req, timeout: (seen.append(req), Answer())[1]):
            r = mcp_compile.build("http://127.0.0.1:8765/studio/L1/", False)
        (req,) = seen
        self.assertEqual(r, {"exit": 0, "diagnostics": []})
        self.assertEqual(req.full_url, "http://127.0.0.1:8765/studio/L1/api/build")
        self.assertEqual(req.get_header("Origin"), "http://127.0.0.1:8765")
        self.assertEqual(req.get_header("Content-type"), "application/json")
        self.assertEqual(json.loads(req.data), {"mode": "draft", "clean": False, "by": "agent"})

    def test_one_name_for_the_tool_in_events(self):
        """Seventh review: the tool shows as "Compile" through one helper, wherever Claude Code names it."""
        from latex_agent import backend_claude
        self.assertEqual(backend_claude.tool_name(backend_claude.COMPILE_TOOL), "Compile")
        self.assertEqual(backend_claude.tool_name("Read"), "Read")
        self.assertEqual(backend_claude.tool_name(None), None)
        j, st = job_for(root=tmpdir()), {}
        self.claude.handle({"type": "stream_event", "parent_tool_use_id": None, "event": {"type": "content_block_start", "index": 0, "content_block": {
            "type": "tool_use", "id": "c1", "name": backend_claude.COMPILE_TOOL}}}, j, st)
        self.claude.handle({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "c1", "name": backend_claude.COMPILE_TOOL, "input": {}}]}}, j, st)
        self.assertEqual([e["name"] for e in j.events if e["t"] in ("tool_start", "tool")], ["Compile", "Compile"])

    def test_codex_names_the_tool_compile_too(self):
        """Last review round: one mapping (backends.tool_name) for both CLIs' names of the compile tool."""
        self.assertEqual(backends.tool_name("mcp__studio__compile"), "Compile")
        self.assertEqual(backends.tool_name("studio.compile"), "Compile")
        self.assertEqual(backends.tool_name("other.compile"), "other.compile")
        j, st = job_for(root=tmpdir()), {}
        Codex("codex", {"bin": "codex"}).handle({"type": "item.started", "item": {
            "id": "m1", "type": "mcp_tool_call", "server": "studio", "tool": "compile"}}, j, st)
        self.assertEqual([e["name"] for e in j.events if e["t"] == "tool"], ["Compile"])

    def test_protocol(self):
        from latex_agent import mcp_compile
        a = mcp_compile.answer({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}, "u")
        self.assertEqual(a["result"]["protocolVersion"], "2025-06-18")
        self.assertIsNone(mcp_compile.answer({"jsonrpc": "2.0", "method": "notifications/initialized"}, "u"))
        tools = mcp_compile.answer({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, "u")
        self.assertEqual([t["name"] for t in tools["result"]["tools"]], ["compile"])

    def test_report_lists_errors_with_lines(self):
        from latex_agent import mcp_compile
        text, failed = mcp_compile.report({"exit": 1, "engine": "pdflatex", "seconds": 2.1, "diagnostics": [
            {"severity": "error", "file": "main.tex", "line": 12, "message": "Undefined control sequence"},
            {"severity": "warning", "file": "main.tex", "line": 3, "message": "Reference `x' undefined"}]})
        self.assertTrue(failed)
        self.assertIn("1 error(s), 1 warning(s)", text)
        self.assertIn("- error: main.tex:12: Undefined control sequence", text)
        text, failed = mcp_compile.report({"exit": 0, "diagnostics": []})
        self.assertFalse(failed)
        self.assertTrue(text.startswith("Build OK."))


class DisplayMathRule(unittest.TestCase):
    """Seventh review: the rule against $$ is LaTeX's; key-ideas.md is Markdown and is typeset only from $…$ and
    $$…$$ (ADR-0013, mathtext.js), so the instructions every turn gets scope it to .tex files and say so."""

    def bullets(self, text):
        return ["- " + b for b in text.split("\n- ")[1:]]

class ClaudeBilling(unittest.TestCase):
    """total_cost_usd is a list price: it is a real cost only with an API key (upstream 2938c05)."""

    def result(self, key_source):
        cc, j, st = ClaudeCode("claude", {"bin": "claude"}), job_for(), {}
        cc.handle({"type": "system", "subtype": "init", "session_id": "s", "apiKeySource": key_source}, j, st)
        cc.handle({"type": "result", "subtype": "success", "total_cost_usd": 5.353,
                   "usage": {"input_tokens": 4, "cache_creation_input_tokens": 100, "cache_read_input_tokens": 900, "output_tokens": 50}}, j, st)
        return st

    def test_subscription_shows_no_price(self):
        st = self.result("none")
        self.assertIsNone(st["cost"])
        self.assertEqual(st["billing"], "subscription")
        self.assertEqual(st["usage"], {"in": 1004, "out": 50})

    def test_api_key_shows_the_price(self):
        st = self.result("ANTHROPIC_API_KEY")
        self.assertEqual(st["cost"], 5.353)
        self.assertEqual(st["billing"], "api")
