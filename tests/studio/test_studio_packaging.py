"""The studio ships whole in a wheel: its page, the vendored libraries and the licences (#68)."""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
STUDIO = REPO / "src" / "proof_cli" / "studio"


@pytest.fixture(scope="module")
def wheel_files(tmp_path_factory) -> set[str]:
    pytest.importorskip("setuptools")
    pytest.importorskip("wheel")
    tree = tmp_path_factory.mktemp("tree")
    shutil.copy(REPO / "pyproject.toml", tree / "pyproject.toml")
    shutil.copytree(REPO / "src", tree / "src", ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"))
    out = tmp_path_factory.mktemp("dist")
    built = subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(tree), "--no-deps", "--no-build-isolation", "--no-index", "-w", str(out), "-q"],
        capture_output=True, text=True,
    )
    assert built.returncode == 0, built.stderr
    (wheel,) = out.glob("*.whl")
    return set(zipfile.ZipFile(wheel).namelist())


def test_the_wheel_carries_every_studio_static_and_vendor_file(wheel_files):
    shipped = {f"proof_cli/studio/{path.relative_to(STUDIO).as_posix()}" for path in (STUDIO / "static").rglob("*") if path.is_file()}
    assert shipped and shipped <= wheel_files, sorted(shipped - wheel_files)


def test_the_wheel_carries_the_three_licences(wheel_files):
    assert {
        "proof_cli/studio/LICENSE",
        "proof_cli/studio/static/vendor/LICENSE-codemirror",
        "proof_cli/studio/static/vendor/LICENSE-pdfjs",
    } <= wheel_files


def test_the_studio_imports_no_home_code_and_leaves_sys_path_alone():
    for path in STUDIO.glob("*.py"):
        text = path.read_text()
        assert "sys.path.insert" not in text, path.name
        for gone in ("hub", "registry", "presence"):
            assert f"import {gone}" not in text and f"from .{gone}" not in text, (path.name, gone)
