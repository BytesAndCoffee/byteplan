# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Helpers for tests that run against real Git repositories."""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory

# Git runs BytePlan (hooks, merge driver) in subprocesses; keep their coverage data with
# ours, not inside the repository under test.
COVERAGE_FILE = str(Path(__file__).resolve().parents[1] / ".coverage")


def git(
    cwd: Path, *args: str, check: bool = True, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        # Git writes UTF-8, but hook output (BytePlan's own stdout) is in the locale's encoding,
        # cp1252 on Windows: decode as UTF-8, replacing what isn't.
        encoding="utf-8",
        errors="replace",
        check=check,
        env={**os.environ, "COVERAGE_FILE": COVERAGE_FILE, **(env or {})},
    )


def frozen(repo: ProjectFactory) -> dict[str, str]:
    """Hashes of .git/index and every working-tree file: read-only commands must not change them."""
    top = repo.root.parent
    state = {".git/index": hashlib.sha256((top / ".git/index").read_bytes()).hexdigest()}
    for path in sorted(top.rglob("*")):
        if path.is_file() and ".git" not in path.relative_to(top).parts:
            state[path.relative_to(top).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return state
