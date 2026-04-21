from pathlib import Path

from typer.testing import CliRunner

from proof_cli.cli import app


runner = CliRunner()


def test_help_lists_required_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "goal" in result.stdout
    assert "theorem" in result.stdout
    assert "obligation" in result.stdout
    assert "blocker" in result.stdout


def test_init_status_and_export(tmp_path: Path):
    result = runner.invoke(app, ["init", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "Initialized proof project" in result.stdout

    result = runner.invoke(app, ["status", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "Proof Status" in result.stdout

    result = runner.invoke(app, ["export", "--root", str(tmp_path)])
    assert result.exit_code == 0
    assert "Proof Export" in result.stdout

