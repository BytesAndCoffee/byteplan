# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Interoperability with unmodified packages downloaded from PyPI."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from byteplan._todo import verifies
from byteplan.api import Project

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory


@pytest.mark.network
@pytest.mark.parametrize("version", ["0.1.0", "0.2.0"])
@verifies("8756")
def test_released_clients_reject_schema_two_without_touching_tasks(project: ProjectFactory, version: str) -> None:
    target = project.root.parent / f"released-{version}"
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--target", str(target), f"byteplan=={version}"],
        check=True,
        capture_output=True,
        text=True,
    )
    project.init()
    project.write("a.py", "# TODO[abcdef]: retained\n")
    Project.open(project.root).import_task("abcdef")
    env = {**os.environ, "PYTHONPATH": str(target)}
    version_check = subprocess.run(
        [sys.executable, "-m", "byteplan", "--version"],
        cwd=project.root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert version in version_check.stdout
    before = project.snapshot()
    for command in (["check"], ["scan"], ["status", "abcdef", "resolved"], ["init"]):
        result = subprocess.run(
            [sys.executable, "-m", "byteplan", *command, "--project", str(project.root)],
            cwd=project.root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 2, result.stdout + result.stderr
        assert "schema_version 2 is newer" in result.stderr, result.stderr
        assert project.snapshot() == before
