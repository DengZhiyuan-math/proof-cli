"""The studio ships whole in a wheel: its page, the vendored libraries and the licences (#68)."""

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
STUDIO = REPO / "src" / "latex_agent"


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
    shipped = {f"latex_agent/{path.relative_to(STUDIO).as_posix()}" for path in (STUDIO / "static").rglob("*") if path.is_file()}
    assert shipped and shipped <= wheel_files, sorted(shipped - wheel_files)


def test_the_wheel_carries_the_licences(wheel_files):
    assert {
        "latex_agent/LICENSE",
        "latex_agent/static/vendor/LICENSE-codemirror",
        "latex_agent/static/vendor/LICENSE-pdfjs",
        "latex_agent/static/vendor/LICENSE-katex",  # ADR-0013
    } <= wheel_files


def test_the_studio_imports_no_home_code_and_leaves_sys_path_alone():
    for path in STUDIO.glob("*.py"):
        text = path.read_text()
        assert "sys.path.insert" not in text, path.name
        for gone in ("hub", "registry", "presence"):
            assert f"import {gone}" not in text and f"from .{gone}" not in text, (path.name, gone)
