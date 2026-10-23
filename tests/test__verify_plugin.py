# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Verification keeps pytest's spelling of linked symlink paths (review of #43)."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from byteplan._todo import verifies
from byteplan.verification import run_tests

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory


@verifies("ff72")
@pytest.mark.parametrize("ancestor_root", [False, True])
@pytest.mark.parametrize("alias_kind", ["file", "directory"])
@pytest.mark.parametrize("outcome", ["passed", "error"])
def test_verification_preserves_symlink_node_ids(
    project: ProjectFactory, alias_kind: str, outcome: str, *, ancestor_root: bool
) -> None:
    if ancestor_root:
        (project.root.parent / "pytest.ini").write_text("[pytest]\n")
    content = "def test_feature():\n    assert True\n"
    if outcome == "error":
        content = "import definitely_missing_module\n" + content
    target = project.write("real/test_feature.py", content)
    if alias_kind == "file":
        alias = project.root / "test_alias.py"
        destination = target.relative_to(project.root)
        node = "test_alias.py::test_feature"
    else:
        alias = project.root / "alias"
        destination = target.parent.relative_to(project.root)
        node = "alias/test_feature.py::test_feature"
    try:
        alias.symlink_to(destination, target_is_directory=alias_kind == "directory")
    except OSError as exc:
        pytest.skip(f"cannot create symlink: {exc}")

    result = run_tests(project.root, [node], [sys.executable, "-m", "pytest"], 30)
    assert result.results[node].outcome == outcome, result.output
    assert result.returncode == (0 if outcome == "passed" else 2), result.output
