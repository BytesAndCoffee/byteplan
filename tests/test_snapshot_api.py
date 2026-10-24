# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""A snapshot Project must never execute or mutate its live working-tree counterpart."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, NoReturn

import pytest

from byteplan import api, archive, verification
from byteplan._todo import verifies
from byteplan.api import Project
from byteplan.errors import ConfigError
from byteplan.models import Status
from tests.gitutil import frozen, git

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory


def _linked(repo: ProjectFactory) -> tuple[Project, str]:
    project = Project.open(repo.root)
    repo.write(".gitignore", "__pycache__/\n.pytest_cache/\n")
    task_id = next(task.id for task in project.list_tasks() if task.title == "first task")
    repo.write("tests/test_proof.py", "def test_proof():\n    assert True\n")
    project.link_tests(task_id, ["tests/test_proof.py::test_proof"])
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "commit verification links")
    return project, task_id


@verifies("c35e66")
@pytest.mark.parametrize("view", ["index", "commit"])
@pytest.mark.parametrize(
    "operation",
    [
        "edit_task",
        "set_status",
        "link_tests",
        "unlink_tests",
        "import_task",
        "reassign",
        "verify",
        "scan",
        "write_report",
        "scaffold_test",
        "release",
        "restore",
        "cleanup",
        "sync",
        "archive",
        "restore_archived",
        "reconcile_archive",
        "migrate",
        "archived_task",
    ],
)
def test_snapshot_mutations_fail_before_any_execution_or_recovery(
    repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch, view: str, operation: str
) -> None:
    _, task_id = _linked(repo)

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        pytest.fail("snapshot operation reached execution, transaction recovery or cache mutation")

    monkeypatch.setattr(verification, "run_tests", forbidden)
    monkeypatch.setattr(api, "recover", forbidden)
    monkeypatch.setattr(archive.Store, "put", forbidden)
    with contextlib.closing(Project.open_snapshot(repo.root, rev="HEAD" if view == "commit" else None)) as snap:
        before = frozen(repo)

        def invoke() -> None:
            match operation:
                case "edit_task":
                    snap.edit_task(task_id, notes="must not write")
                case "set_status":
                    snap.set_status(task_id, Status.RESOLVED)
                case "link_tests" | "unlink_tests":
                    getattr(snap, operation)(task_id, ["tests/test_proof.py::test_proof"])
                case "import_task" | "restore_archived" | "archived_task":
                    getattr(snap, operation)(task_id)
                case "reassign":
                    snap.reassign("src/a.py", 2)
                case "verify":
                    snap.verify([task_id])
                case "scan":
                    snap.scan(dry_run=False)
                case "scaffold_test":
                    snap.scaffold_test(task_id)
                case "release":
                    snap.release("1.0.0rc1", smoke_test=True)
                case _:
                    getattr(snap, operation)()

        with pytest.raises(ConfigError, match=r"read-only|working.tree"):
            invoke()
        assert frozen(repo) == before


@verifies("c35e66")
@pytest.mark.parametrize("view", ["index", "commit"])
@pytest.mark.parametrize("operation", ["scaffold_test", "release", "restore", "cleanup", "sync", "archive", "reassign"])
def test_source_and_archive_previews_refuse_mixed_snapshot_working_tree_state(
    repo: ProjectFactory, view: str, operation: str
) -> None:
    _, task_id = _linked(repo)
    with contextlib.closing(Project.open_snapshot(repo.root, rev="HEAD" if view == "commit" else None)) as snap:
        before = frozen(repo)

        def invoke() -> None:
            if operation == "scaffold_test":
                snap.scaffold_test(task_id, dry_run=True)
            elif operation == "reassign":
                snap.reassign("src/a.py", 2, dry_run=True)
            else:
                getattr(snap, operation)(dry_run=True)

        with pytest.raises(ConfigError, match=r"read-only|working.tree"):
            invoke()
        assert frozen(repo) == before


@verifies("c35e66")
def test_snapshot_registry_queries_use_selected_blobs_even_when_working_tree_is_corrupt(repo: ProjectFactory) -> None:
    project, task_id = _linked(repo)
    project.edit_task(task_id, notes="committed")
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "committed notes")
    project.edit_task(task_id, notes="staged")
    git(repo.root, "add", ".byteplan/tasks.json")
    repo.write(".byteplan/tasks.json", "{broken working-tree registry")
    before = frozen(repo)
    for rev, expected in (("HEAD", "committed"), (None, "staged")):
        with contextlib.closing(Project.open_snapshot(repo.root, rev=rev)) as snap:
            assert snap.get_task(task_id).notes == expected
            loaded = snap.load_registry().get(task_id)
            assert loaded is not None
            assert loaded.notes == expected
            assert next(task for task in snap.list_tasks() if task.id == task_id).notes == expected
            assert next(task for task in snap.report()["tasks"] if task["id"] == task_id)["notes"] == expected
    assert frozen(repo) == before


@verifies("c35e66")
@pytest.mark.parametrize("view", ["index", "commit"])
def test_snapshot_readiness_uses_selected_evidence_and_file_fingerprints(repo: ProjectFactory, view: str) -> None:
    project, task_id = _linked(repo)
    assert project.verify([task_id]).returncode == 0
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "record passing evidence")
    with contextlib.closing(Project.open_snapshot(repo.root, rev="HEAD" if view == "commit" else None)) as snap:
        repo.write("tests/test_proof.py", "def test_proof():\n    assert False\n")
        repo.write(verification.STORE, "{broken working-tree evidence")
        before = frozen(repo)
        task = snap.get_task(task_id)
        assert snap.readiness(task).state == "ready_for_review"
        assert [ready.id for ready, _ in snap.ready()] == [task_id]
        assert frozen(repo) == before


@verifies("c35e66")
@pytest.mark.parametrize("view", ["index", "commit"])
def test_snapshot_without_evidence_cannot_borrow_a_working_tree_pass(repo: ProjectFactory, view: str) -> None:
    project, task_id = _linked(repo)
    with contextlib.closing(Project.open_snapshot(repo.root, rev="HEAD" if view == "commit" else None)) as snap:
        assert project.verify([task_id]).returncode == 0
        assert project.readiness(project.get_task(task_id)).state == "ready_for_review"
        before = frozen(repo)
        assert snap.readiness(snap.get_task(task_id)).state == "unverified"
        assert snap.ready() == []
        assert frozen(repo) == before


@verifies("c35e66")
@pytest.mark.parametrize("view", ["index", "commit"])
def test_snapshot_head_freshness_never_uses_current_working_tree_state(
    repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch, view: str
) -> None:
    project, task_id = _linked(repo)
    config = repo.root / "pyproject.toml"
    config.write_text(config.read_text() + '\n[tool.byteplan.tests]\nstale_on = "head"\n')
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "configure head freshness")
    project = Project.open(repo.root)
    assert project.verify([task_id]).returncode == 0
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "save evidence")
    with contextlib.closing(Project.open_snapshot(repo.root, rev="HEAD" if view == "commit" else None)) as snap:
        repo.write("tests/test_proof.py", "def test_proof():\n    assert False\n")
        git(repo.root, "add", "-A")
        git(repo.root, "commit", "-qm", "change live head after selecting snapshot")

        def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
            pytest.fail("snapshot freshness consulted the live working tree")

        monkeypatch.setattr(verification, "git_state", forbidden)
        before = frozen(repo)
        result = snap.readiness(snap.get_task(task_id))
        assert result.state == ("ready_for_review" if view == "commit" else "needs_review")
        if view == "index":
            assert "HEAD freshness is uncertain for an index snapshot" in result.reasons
        assert frozen(repo) == before


@verifies("c35e66")
@pytest.mark.parametrize("view", ["index", "commit"])
@pytest.mark.parametrize("dynamic", [False, True])
def test_snapshot_runtime_and_release_metadata_use_selected_configuration(
    repo: ProjectFactory, view: str, *, dynamic: bool
) -> None:
    _linked(repo)
    config = repo.root / "pyproject.toml"
    text = config.read_text() + '\n[tool.byteplan.annotations]\nruntime_modules = ["custom_markers"]\n'
    if dynamic:
        text = text.replace('version = "0.1"', 'dynamic = ["version"]')
        text += '\n[tool.hatch.version]\npath = "src/_version.py"\n'
        repo.write("src/_version.py", '__version__ = "3.2"\n')
    config.write_text(text)
    shim = repo.write("src/custom_markers.py", "def todo(*args):\n    return lambda value: value\n")
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "configure runtime and version")
    with contextlib.closing(Project.open_snapshot(repo.root, rev="HEAD" if view == "commit" else None)) as snap:
        shim.unlink()
        config.write_text("invalid live TOML = [")
        if dynamic:
            repo.write("src/_version.py", '__version__ = "9.9"\n')
        before = frozen(repo)
        assert snap.runtime_module() == "custom_markers"
        assert snap.release_version(None) == ("3.2" if dynamic else "0.1")
        assert frozen(repo) == before
