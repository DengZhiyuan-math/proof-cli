"""Unit tests for the agent manager and its backends (proof_cli/studio/agent.py, backend_*.py).

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

from proof_cli.studio import agent, backends
from proof_cli.studio.backend_claude import ClaudeCode
from proof_cli.studio.backend_codex import Codex
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
    patcher = mock.patch("proof_cli.studio.backend_claude.allowed_account", return_value="")
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
        from proof_cli.studio import backend_claude
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
