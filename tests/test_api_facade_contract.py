# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Public facade identities and edit semantics across internal operation extraction."""

from __future__ import annotations

import inspect
import pickle
from pathlib import Path
from typing import TYPE_CHECKING, get_type_hints

import pytest

from byteplan import api, persistence
from byteplan._todo import verifies
from byteplan.diagnostics import Diagnostic

if TYPE_CHECKING:
    from byteplan.persistence import FileWrite
    from tests.conftest import ProjectFactory


@pytest.fixture
def result_instances(project: ProjectFactory) -> dict[str, object]:
    initialized = api.init_project(project.root)
    project.write("src/feature.py", "# TODO: implement feature\nvalue = 1\n")
    facade = api.Project.open(project.root)
    preview = facade.scan()
    facade.scan(dry_run=False)
    (task,) = facade.list_tasks()
    return {
        "InitResult": initialized,
        "Proposal": preview.proposals[0],
        "ScanReport": preview,
        "TaskVerification": api.TaskVerification(task, facade.readiness(task), {}),
        "VerifyReport": facade.verify(),
        "ScaffoldResult": facade.scaffold_test(task.id, link_style="managed", dry_run=True),
        "ReleaseReport": api.ReleaseReport("1.0.0rc1", (), 0, 0, (), dry_run=True),
        "RestoreReport": api.RestoreReport((), 0, 0, (), dry_run=True),
        "CleanupReport": facade.cleanup(),
        "SyncReport": facade.sync(),
        "ArchiveReport": facade.archive(dry_run=True),
        "ReconcileReport": api.ReconcileReport((), (), 0),
        "RepairResult": api.RepairResult(task, (), dry_run=True),
    }


@verifies("3844")
@pytest.mark.parametrize(
    "name",
    [
        "InitResult",
        "Proposal",
        "ScanReport",
        "TaskVerification",
        "VerifyReport",
        "ScaffoldResult",
        "ReleaseReport",
        "RestoreReport",
        "CleanupReport",
        "SyncReport",
        "ArchiveReport",
        "ReconcileReport",
        "RepairResult",
    ],
)
def test_result_types_retain_public_import_and_pickle_identity(result_instances: dict[str, object], name: str) -> None:
    result = result_instances[name]
    public_type = getattr(api, name)
    assert type(result) is public_type
    assert public_type.__module__ == "byteplan.api"
    assert public_type.__qualname__ == name
    restored = pickle.loads(pickle.dumps(result))  # Trusted bytes produced immediately above.
    assert type(restored) is public_type
    assert restored == result


@verifies("3844")
@pytest.mark.parametrize(
    ("name", "parameter", "annotation"),
    [
        ("InitResult", "root", Path),
        ("ReleaseReport", "warnings", tuple[Diagnostic, ...]),
        ("CleanupReport", "diagnostics", tuple[Diagnostic, ...]),
        ("VerifyReport", "tasks", tuple[api.TaskVerification, ...]),
        ("RestoreReport", "files", tuple[str, ...]),
        ("ArchiveReport", "tasks", tuple[str, ...]),
        ("ReconcileReport", "recovered", tuple[str, ...]),
    ],
)
def test_result_constructor_annotations_remain_resolvable(name: str, parameter: str, annotation: object) -> None:
    hints = get_type_hints(getattr(api, name).__init__)
    assert hints[parameter] == annotation
    assert hints["return"] is type(None)


@verifies("3844")
def test_edit_task_preserves_omitted_fields_and_clears_only_explicit_none(project: ProjectFactory) -> None:
    project.init()
    project.write("src/feature.py", "# TODO: feature\nvalue = 1\n")
    facade = api.Project.open(project.root)
    facade.scan(dry_run=False)
    (task,) = facade.list_tasks()
    facade.edit_task(task.id, assignee="sam", title_override="Displayed title")
    signature = inspect.signature(api.Project.edit_task)
    assert signature.parameters["assignee"].default is api.UNSET
    assert signature.parameters["title_override"].default is api.UNSET

    before = facade.config.registry_path.read_bytes()
    unchanged, changed = facade.edit_task(task.id)
    assert not changed
    assert (unchanged.assignee, unchanged.title_override) == ("sam", "Displayed title")
    assert facade.config.registry_path.read_bytes() == before

    edited, changed = facade.edit_task(task.id, assignee=None)
    assert changed
    assert (edited.assignee, edited.title_override) == (None, "Displayed title")
    cleared, changed = facade.edit_task(task.id, title_override=None)
    assert changed
    assert (cleared.assignee, cleared.title_override) == (None, None)
    assert (facade.get_task(task.id).assignee, facade.get_task(task.id).title_override) == (None, None)


@verifies("3844")
def test_registry_edit_keeps_the_facade_commit_patch_target(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project.init()
    project.write("src/feature.py", "# TODO: feature\nvalue = 1\n")
    facade = api.Project.open(project.root)
    facade.scan(dry_run=False)
    (task,) = facade.list_tasks()
    calls: list[tuple[str, ...]] = []
    original = persistence.commit

    def record(root: Path, writes: list[FileWrite]) -> list[str]:
        calls.append(tuple(write.path for write in writes))
        return original(root, writes)

    monkeypatch.setattr(api, "commit", record)
    edited, changed = facade.edit_task(task.id, notes="written through the public facade")
    assert changed
    assert calls == [(facade.registry_rel,)]
    assert edited.notes == facade.get_task(task.id).notes == "written through the public facade"


@verifies("3844")
def test_runtime_template_does_not_add_unshipped_facade_decorator_exports() -> None:
    assert "def todo(" in api.RUNTIME_SHIM
    assert "def verifies(" in api.RUNTIME_SHIM
    assert not hasattr(api, "todo")
    assert not hasattr(api, "verifies")
