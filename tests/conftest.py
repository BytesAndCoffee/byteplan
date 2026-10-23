# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import shutil
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from byteplan.api import init_project
from byteplan.cli import EXIT_OK, main
from tests.gitutil import git

if TYPE_CHECKING:
    from pathlib import Path

PYPROJECT = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "demo"
version = "0.1"
"""


@dataclass
class CliResult:
    code: int
    out: str
    err: str


class ProjectFactory:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, rel: str, content: str | bytes, *, dedent: bool = True) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_bytes((textwrap.dedent(content) if dedent else content).encode())
        return path

    def init(self) -> None:
        init_project(self.root)

    def snapshot(self) -> dict[str, str]:
        """Content hash of every file, for asserting that nothing was written."""
        return {
            p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(self.root.rglob("*"))
            if p.is_file()
        }


@pytest.fixture(autouse=True)
def quiet_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """No background gc/maintenance in test repositories: tests compare `.git/` before and after,
    and an automatic repack in between would look like a write. Applies to every Git process,
    including those BytePlan and the hooks start."""
    for n, (key, value) in enumerate((("gc.auto", "0"), ("maintenance.auto", "false"))):
        monkeypatch.setenv(f"GIT_CONFIG_KEY_{n}", key)
        monkeypatch.setenv(f"GIT_CONFIG_VALUE_{n}", value)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "2")


@pytest.fixture
def project(tmp_path: Path) -> ProjectFactory:
    factory = ProjectFactory(tmp_path / "proj")
    factory.write("pyproject.toml", PYPROJECT, dedent=False)
    return factory


RunCli = Callable[..., CliResult]


@pytest.fixture
def run_cli(capsys: pytest.CaptureFixture[str]) -> RunCli:
    def run(*args: str | Path) -> CliResult:
        code = main([str(arg) for arg in args])
        captured = capsys.readouterr()
        return CliResult(code, captured.out, captured.err)

    return run


class FakeClock:
    """Deterministic, strictly increasing UTC timestamps."""

    def __init__(self) -> None:
        self.ticks = 0

    def __call__(self) -> str:
        self.ticks += 1
        return f"2026-10-21T00:00:{self.ticks:02d}Z"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def repo(project: ProjectFactory, run_cli: RunCli) -> ProjectFactory:
    """A committed, fully reconciled project in ``<git repo>/proj`` (so path offsets are exercised)."""
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    top = project.root.parent
    git(top, "init", "-q", "-b", "main")
    git(top, "config", "user.email", "test@example.com")
    git(top, "config", "user.name", "Test")
    git(top, "config", "commit.gpgsign", "false")
    project.init()
    project.write("src/a.py", "def f():\n    # TODO: first task\n    return 1\n")
    project.write("src/b.py", "# FIXME: second task\nx = 1\n")
    assert run_cli("scan", "--project", project.root).code == EXIT_OK
    git(top, "add", "-A")
    git(top, "commit", "-qm", "base")
    return project
