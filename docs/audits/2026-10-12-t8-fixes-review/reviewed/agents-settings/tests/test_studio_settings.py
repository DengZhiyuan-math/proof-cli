"""`[studio]` keys that nothing reads are named, so a misspelt or invented setting isn't silently ignored (proof-cli#197)."""

from proof_agents.proof_agent import unknown_studio_keys


def test_unknown_studio_keys_are_named_with_a_hint_where_one_is_known(tmp_path):
    (tmp_path / "proof.toml").write_text(
        '[studio]\nlibrary = ["library"]\nparallel = 1\nclaude_config_dir = "~/.claude-other"\nbudget_turn = 4\n'
        "[studio.budget]\nturns = 4\nminute = 5\n", encoding="utf-8")
    found = {item["key"]: item["message"] for item in unknown_studio_keys(tmp_path)}
    assert set(found) == {"claude_config_dir", "budget_turn", "budget.minute"}
    assert "CLAUDE_CONFIG_DIR in the environment" in found["claude_config_dir"]
    assert "budget_turns" in found["budget_turn"]  # the list of settings, to spot the misspelling


def test_known_keys_a_missing_file_and_an_unreadable_one_give_nothing(tmp_path):
    assert unknown_studio_keys(tmp_path) == []
    (tmp_path / "proof.toml").write_text(
        '[studio]\nlibrary = []\nagent_name = "a"\nbudget_turns = 1\nbudget_minutes = 2\nparallel = 1\nopen_command = "x"\n',
        encoding="utf-8")
    assert unknown_studio_keys(tmp_path) == []
    (tmp_path / "proof.toml").write_text("[studio\n", encoding="utf-8")
    assert unknown_studio_keys(tmp_path) == []
