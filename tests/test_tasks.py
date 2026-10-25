# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Permanent archived identities cannot be recreated through import repair."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from byteplan import registry as registry_io
from byteplan import verification
from byteplan._todo import verifies
from byteplan.api import Project
from byteplan.errors import ConfigError
from byteplan.models import Status
from tests.gitutil import git

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import ProjectFactory, RunCli


def _files(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*") if path.is_file()}


@verifies("38e8db")
@pytest.mark.parametrize("entrypoint", ["api", "cli"])
@pytest.mark.parametrize("cache", ["present", "missing", "clone"])
def test_import_refuses_archived_identity_without_masking_state(
    repo: ProjectFactory, run_cli: RunCli, tmp_path: Path, entrypoint: str, cache: str
) -> None:
    project = Project.open(repo.root)
    task = next(task for task in project.list_tasks() if task.title == "second task")
    task_id = task.id
    project.edit_task(task_id, notes="Authored history must survive", assignee="maintainer", add_labels=["important"])
    repo.write("tests/test_proof.py", "def test_proof():\n    assert 2 + 2 == 4\n")
    project.link_tests(task_id, ["tests/test_proof.py::test_proof"])
    project.set_status(task_id, Status.RESOLVED, note="Explicitly accepted by the maintainer")
    project.cleanup([task_id], dry_run=False)
    project.scan(dry_run=False)
    assert project.verify([task_id]).returncode == 0
    record = registry_io.task_to_dict(project.get_task(task_id))
    evidence = verification.Evidence.load(repo.root)
    assert evidence.tasks[task_id]["tests"]["tests/test_proof.py::test_proof"]["outcome"] == "passed"
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "durable archived task and passing evidence")
    assert project.archive(older_than=0).tasks == (task_id,)
    repo.write("src/reappeared.py", f"# FIXME[{task_id}]: returned from an old branch\n")
    root = repo.root
    if cache == "missing":
        (root / ".byteplan/archive.sqlite").unlink()
    elif cache == "clone":
        git(root, "add", "-A")
        git(root, "commit", "-qm", "archive and reappeared annotation")
        destination = tmp_path / "fresh"
        git(tmp_path, "clone", "-q", str(root.parent), str(destination))
        root = destination / "proj"
        project = Project.open(root)
    before = _files(root)
    if entrypoint == "api":
        with pytest.raises(ConfigError, match=f"archive --restore {task_id}"):
            project.import_task(task_id.upper())
    else:
        result = run_cli("repair", "--import", task_id.upper(), "--project", root)
        assert result.code == 2
        assert f"archive --restore {task_id}" in result.err
    assert _files(root) == before
    assert task_id not in project.load_registry().tasks
    assert task_id in project.archive_index().tasks
    if cache != "present":
        assert not (root / ".byteplan/archive.sqlite").exists()

    # The prescribed restore path retains the selected lifecycle and authored record.
    assert project.restore_archived(task_id)
    restored = project.get_task(task_id)
    assert registry_io.task_to_dict(restored) == record
    assert restored.status is Status.RESOLVED
    assert restored.notes == "Authored history must survive"
    assert restored.assignee == "maintainer"
    if cache == "present":
        restored_evidence = verification.Evidence.load(root)
        assert restored_evidence.tasks[task_id] == evidence.tasks[task_id]
        run = evidence.tasks[task_id]["run"]
        assert restored_evidence.runs[run] == evidence.runs[run]


@verifies("38e8db")
def test_import_still_registers_a_genuinely_unregistered_identity(project: ProjectFactory) -> None:
    project.init()
    project.write("src/imported.py", "# TODO[abc123]: existing source obligation\n")
    facade = Project.open(project.root)
    result = facade.import_task("ABC123")
    assert result.task.id == "abc123"
    assert result.task.status is Status.OPEN
    assert result.task.title == "existing source obligation"
    assert [event.event for event in result.task.history] == ["created"]
