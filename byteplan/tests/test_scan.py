# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from byteplan.api import Project
from byteplan.diagnostics import EXIT_FINDINGS, EXIT_OK, Code
from byteplan.errors import ScanError
from byteplan.ids import is_valid_id

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory


def register(project: ProjectFactory, task_id: str, **fields: str) -> None:
    path = project.root / ".byteplan/tasks.json"
    data = json.loads(path.read_text())
    data["reserved_ids"] = sorted({*data["reserved_ids"], task_id})
    data["tasks"][task_id] = {"id": task_id, "kind": "TODO", "title": "t", **fields}
    path.write_text(json.dumps(data))


def test_scan_proposes_ids_in_stable_order(project: ProjectFactory) -> None:
    project.init()
    project.write("src/b.py", "# TODO: b\n")
    project.write("src/a.py", "# TODO: a1\nx = 1\n# FIXME: a2\n")
    report = Project.open(project.root).scan()
    assert [(p.tag.path, p.tag.line) for p in report.proposals] == [("src/a.py", 1), ("src/a.py", 3), ("src/b.py", 1)]
    ids = [p.task_id for p in report.proposals]
    assert all(is_valid_id(i) for i in ids)
    assert len(set(ids)) == 3
    assert [p.task_id for p in Project.open(project.root).scan().proposals] == ids


def test_identical_occurrences_get_distinct_ids(project: ProjectFactory) -> None:
    project.init()
    project.write("a.py", "# TODO: same\n# TODO: same\n")
    ids = [p.task_id for p in Project.open(project.root).scan().proposals]
    assert len(set(ids)) == 2


def test_inserted_lines_do_not_change_proposed_ids(project: ProjectFactory) -> None:
    project.init()
    project.write("a.py", "# TODO: stable\n")
    before = Project.open(project.root).scan().proposals[0].task_id
    project.write("a.py", "import os\n\n\n# TODO: stable\n")
    assert Project.open(project.root).scan().proposals[0].task_id == before


def test_reserved_and_in_source_ids_are_avoided(project: ProjectFactory) -> None:
    project.init()
    project.write("a.py", "# TODO: x\n")
    first = Project.open(project.root).scan().proposals[0].task_id
    register(project, first)
    project.write("b.py", f"# TODO[{first}]: x\n")
    report = Project.open(project.root).scan()
    assert report.proposals[0].task_id != first


def test_duplicate_ids_fail(project: ProjectFactory) -> None:
    project.init()
    register(project, "7fa2")
    project.write("src/a.py", "# TODO[7fa2]: original\n")
    project.write("src/b.py", "# TODO[7fa2]: copy\n")
    project_ = Project.open(project.root)
    report = project_.scan()
    duplicates = [d for d in report.diagnostics if d.code is Code.DUPLICATE_ID]
    assert len(duplicates) == 1
    assert [str(loc) for loc in duplicates[0].locations] == ["src/a.py:1", "src/b.py:1"]
    assert report.proposals == ()  # never silently reassigned
    assert project_.exit_code(report.diagnostics) == EXIT_FINDINGS


def test_unregistered_id_is_reported_not_replaced(project: ProjectFactory) -> None:
    project.init()
    project.write("a.py", "# TODO[beef]: from elsewhere\n")
    project_ = Project.open(project.root)
    report = project_.scan()
    assert [d.code for d in report.diagnostics] == [Code.UNREGISTERED_ID]
    assert report.proposals == ()
    assert project_.exit_code(report.diagnostics) == EXIT_OK


def test_resolved_task_still_in_source_is_stale(project: ProjectFactory) -> None:
    project.init()
    register(project, "7fa2", status="resolved")
    project.write("a.py", "# TODO[7fa2]: done already\n")
    assert [d.code for d in Project.open(project.root).scan().diagnostics] == [Code.STALE_ANNOTATION]


def test_failed_file_aborts_the_whole_scan(project: ProjectFactory) -> None:
    project.init()
    project.write("good.py", "# TODO: fine\n")
    project.write("bad.py", "def f(:\n")
    project.write("worse.py", b"x = '\xff'\n")
    with pytest.raises(ScanError) as excinfo:
        Project.open(project.root).scan()
    assert sorted(f.path for f in excinfo.value.failures) == ["bad.py", "worse.py"]


def test_narrowed_scan(project: ProjectFactory) -> None:
    project.init()
    project.write("src/a.py", "# TODO: a\n")
    project.write("src/b.py", "# TODO: b\n")
    report = Project.open(project.root).scan(["src/b.py"], cwd=project.root)
    assert report.scope.narrowed
    assert [t.path for t in report.tags] == ["src/b.py"]


def test_scan_never_writes(project: ProjectFactory) -> None:
    project.init()
    project.write("a.py", "# TODO: x\n")
    before = project.snapshot()
    Project.open(project.root).scan()
    assert project.snapshot() == before
