# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Recovery guidance for test links that no longer match collected tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from byteplan._todo import verifies
from byteplan.api import Project

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory


@verifies("b29c72")
@pytest.mark.parametrize("missing_file", [False, True])
def test_missing_managed_test_explains_recovery_without_rescanning(
    project: ProjectFactory, *, missing_file: bool
) -> None:
    project.init()
    project.write("src/a.py", "# TODO: feature\nx = 1\n")
    p = Project.open(project.root)
    p.scan(dry_run=False)
    (task,) = p.list_tasks()
    node = "tests/test_feature.py::test_old"
    p.link_tests(task.id, [node])
    if not missing_file:
        project.write("tests/test_feature.py", "def test_new():\n    assert True\n")
    registry_before = p.config.registry_path.read_bytes()
    report = p.verify([task.id])
    result = report.tasks[0].results[node]
    assert result.outcome == "not_found"
    assert "byteplan scan" in result.message
    assert "managed link" in result.message
    assert "byteplan tests remove" in result.message
    assert "byteplan tests add" in result.message
    assert p.config.registry_path.read_bytes() == registry_before
    assert p.get_task(task.id).tests_managed == [node]
    assert report.tasks[0].readiness.state == "needs_review"


@verifies("b29c72")
def test_renamed_discovered_test_requires_explicit_scan(project: ProjectFactory) -> None:
    project.init()
    project.write("src/a.py", "# TODO: feature\nx = 1\n")
    project.write("byteplan_runtime.py", "def verifies(*ids):\n    return lambda target: target\n")
    p = Project.open(project.root)
    p.scan(dry_run=False)
    (task,) = p.list_tasks()
    old_node = "tests/test_feature.py::test_old"
    new_node = "tests/test_feature.py::test_new"
    text = f'from byteplan_runtime import verifies\n\n@verifies("{task.id}")\ndef test_old():\n    assert True\n'
    test_path = project.write("tests/test_feature.py", text)
    p.scan(dry_run=False)
    assert old_node in p.get_task(task.id).linked_tests()
    test_path.write_text(text.replace("test_old", "test_new"))
    before = p.config.registry_path.read_bytes()
    missing = p.verify([task.id])
    assert missing.tasks[0].results[old_node].outcome == "not_found"
    assert "byteplan scan" in missing.tasks[0].results[old_node].message
    assert p.config.registry_path.read_bytes() == before
    p.scan(dry_run=False)
    assert set(p.get_task(task.id).linked_tests()) == {new_node}
    passed = p.verify([task.id])
    assert passed.tasks[0].results[new_node].outcome == "passed"
    assert passed.tasks[0].readiness.state == "ready_for_review"
