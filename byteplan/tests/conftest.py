# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from byteplan.api import init_project
from byteplan.cli import main

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
