# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Narrowed observations still allocate from the project's complete identity namespace."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

import pytest

from byteplan import api
from byteplan._todo import verifies
from byteplan.api import Project
from byteplan.diagnostics import Code
from byteplan.errors import ScanError, SourceError
from byteplan.ids import allocate
from byteplan.models import Presence
from byteplan.scanner.source import read_source
from tests.gitutil import frozen, git

if TYPE_CHECKING:
    from collections.abc import Collection

    from byteplan.scanner.source import SourceFile
    from tests.conftest import ProjectFactory


@verifies("3d5bb4")
@pytest.mark.parametrize("dry_run", [True, False])
def test_narrowed_scan_avoids_unregistered_id_without_observing_other_tasks(
    project: ProjectFactory, *, dry_run: bool
) -> None:
    project.init()
    project.write("src/retained.py", "# TODO: already registered\n")
    facade = Project.open(project.root)
    facade.scan(dry_run=False)
    (retained,) = facade.list_tasks()
    project.write("src/new.py", "# TODO: selected new task\n")
    candidate = facade.scan(["src/new.py"], cwd=project.root).proposals[0].task_id
    outside = project.write("src/other.py", f"# TODO[{candidate}]: independently authored task\n")
    outside_bytes = outside.read_bytes()
    # The registered task is absent from disk but remains outside this narrowed observation.
    (project.root / "src/retained.py").unlink()
    before = project.snapshot()

    report = facade.scan(["src/new.py"], cwd=project.root, dry_run=dry_run)

    assert report.scope.narrowed
    assert report.scope.files == ("src/new.py",)
    assert [tag.path for tag in report.tags] == ["src/new.py"]
    assert len(report.proposals) == 1
    allocated = report.proposals[0].task_id
    assert allocated != candidate
    assert outside.read_bytes() == outside_bytes
    assert facade.get_task(retained.id) == retained
    assert facade.get_task(retained.id).presence is Presence.PRESENT
    assert candidate not in facade.load_registry().tasks
    if dry_run:
        assert project.snapshot() == before
    else:
        assert f"TODO[{allocated}]" in (project.root / "src/new.py").read_text()
        full = facade.scan()
        assert not full.blocked
        assert all(d.code is not Code.DUPLICATE_ID for d in full.diagnostics)
        assert any(d.code is Code.UNREGISTERED_ID and d.task_id == candidate for d in full.diagnostics)


@verifies("3d5bb4")
def test_reservations_cover_supported_lengths_and_languages(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project.init()
    config = project.root / "pyproject.toml"
    config.write_text(
        config.read_text().replace('include = ["**/*.py"]', 'include = ["**/*.py", "**/*.md", "**/*.json"]')
    )
    project.write("selected.py", "# TODO: selected\n")
    project.write("legacy.py", "# TODO[beef]: legacy\n")
    project.write("six.md", "<!-- TODO[cafe01]: six characters -->\n")
    project.write("long.json", '{"task": "TODO[deadbeef]: longer identity"}\n')
    reservations: list[set[str]] = []

    def capture(seed: str, used: Collection[str]) -> str:
        reservations.append(set(used))
        return allocate(seed, used)

    monkeypatch.setattr(api, "allocate", capture)
    before = project.snapshot()
    report = Project.open(project.root).scan(["selected.py"], cwd=project.root)
    assert len(report.proposals) == 1
    assert {"beef", "cafe01", "deadbeef"} <= reservations[0]
    assert report.scope.files == ("selected.py",)
    assert project.snapshot() == before


@verifies("3d5bb4")
@pytest.mark.parametrize("view", ["index", "commit"])
def test_narrowed_snapshot_reserves_selected_view_not_live_worktree(repo: ProjectFactory, view: str) -> None:
    facade = Project.open(repo.root)
    repo.write("src/new.py", "# TODO: selected new task\n")
    candidate = facade.scan(["src/new.py"], cwd=repo.root).proposals[0].task_id
    repo.write("src/other.py", f"# TODO[{candidate}]: independently authored task\n")
    git(repo.root, "add", "src/new.py", "src/other.py")
    if view == "commit":
        git(repo.root, "commit", "-qm", "unregistered source identities")
        repo.write("src/other.py", "# TODO[feedface]: index differs from selected commit\n")
        git(repo.root, "add", "src/other.py")
    repo.write("src/other.py", "def broken(:\n")
    before = frozen(repo)
    selected = Project.open_snapshot(repo.root, None if view == "index" else "HEAD")
    try:
        report = selected.scan(["src/new.py"], cwd=repo.root)
        assert len(report.proposals) == 1
        assert report.proposals[0].task_id != candidate
        assert report.scope.files == ("src/new.py",)
        assert {tag.path for tag in report.tags} == {"src/new.py"}
    finally:
        selected.close()
    assert frozen(repo) == before


@verifies("3d5bb4")
@pytest.mark.parametrize(
    "content",
    [
        b"def broken(:\n",
        b"value = '\xff'\n",
        b"# -*- coding: no-such-codec -*-\n",
        b"# TODO[not-an-id]: invalid identity\n",
    ],
    ids=["syntax", "encoding", "unknown-codec", "malformed-id"],
)
@pytest.mark.parametrize("dry_run", [True, False])
def test_narrowed_allocation_refuses_incomplete_identity_universe(
    project: ProjectFactory, content: bytes, *, dry_run: bool
) -> None:
    project.init()
    project.write("selected.py", "# TODO: selected\n")
    project.write("other.py", content)
    before = project.snapshot()
    with pytest.raises(ScanError) as raised:
        Project.open(project.root).scan(["selected.py"], cwd=project.root, dry_run=dry_run)
    assert [error.path for error in raised.value.failures] == ["other.py"]
    assert project.snapshot() == before


@verifies("3d5bb4")
def test_narrowed_allocation_refuses_unreadable_reservation_file(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project.init()
    project.write("selected.py", "# TODO: selected\n")
    project.write("other.py", "# TODO[beef]: existing\n")
    facade = Project.open(project.root)

    def unreadable(path: str) -> SourceFile:
        if path == "other.py":
            raise SourceError(path, "cannot read: permission denied")
        return read_source(project.root, path)

    monkeypatch.setattr(facade, "_read", unreadable)
    before = project.snapshot()
    with pytest.raises(ScanError, match="permission denied"):
        facade.scan(["selected.py"], cwd=project.root, dry_run=False)
    assert project.snapshot() == before


@verifies("3d5bb4")
@pytest.mark.parametrize("view", ["index", "commit"])
def test_narrowed_snapshot_refuses_malformed_unselected_identity(repo: ProjectFactory, view: str) -> None:
    repo.write("src/new.py", "# TODO: selected\n")
    repo.write("src/other.py", "# TODO[bad-id]: malformed\n")
    git(repo.root, "add", "src/new.py", "src/other.py")
    if view == "commit":
        git(repo.root, "commit", "-qm", "malformed identity fixture")
    repo.write("src/other.py", "# TODO[beef]: harmless working-tree alternative\n")
    before = frozen(repo)
    selected = Project.open_snapshot(repo.root, None if view == "index" else "HEAD")
    try:
        with pytest.raises(ScanError, match=r"malformed|not a lowercase"):
            selected.scan(["src/new.py"], cwd=repo.root)
    finally:
        selected.close()
    assert frozen(repo) == before


@verifies("3d5bb4")
@pytest.mark.parametrize("auto_annotate", [True, False])
def test_narrowed_scan_without_allocation_does_not_require_unselected_parsing(
    project: ProjectFactory, *, auto_annotate: bool
) -> None:
    project.init()
    project.write("selected.py", "# TODO[beef]: selected\n" if auto_annotate else "# TODO: selected\n")
    project.write("other.py", "def broken(:\n")
    facade = Project.open(project.root)
    if not auto_annotate:
        facade = Project(dataclasses.replace(facade.config, auto_annotate=False))
    report = facade.scan(["selected.py"], cwd=project.root)
    assert not report.proposals


@verifies("3d5bb4")
def test_reservation_scope_honors_excluded_files(project: ProjectFactory) -> None:
    project.init()
    project.write("selected.py", "# TODO: selected\n")
    candidate = Project.open(project.root).scan(["selected.py"], cwd=project.root).proposals[0].task_id
    config = project.root / "pyproject.toml"
    config.write_text(config.read_text().replace('include = ["**/*.py"]', 'include = ["selected.py"]'))
    project.write("excluded.py", f"# TODO[{candidate}]: excluded from the configured scope\n")
    report = Project.open(project.root).scan(["selected.py"], cwd=project.root)
    assert report.proposals[0].task_id == candidate
