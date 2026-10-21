# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Crash recovery (spec 16, addendum 17) and concurrent edits (addendum 18)."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

import pytest

from byteplan import persistence
from byteplan.api import Project
from byteplan.errors import ConcurrentModificationError, JournalConflictError
from byteplan.persistence import FileWrite, commit, recover, sha256

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import FakeClock, ProjectFactory, RunCli


class CrashError(Exception):
    pass


def crash_on_replace(monkeypatch: pytest.MonkeyPatch, nth: int) -> None:
    """Make the ``nth`` replacement of a project file raise, simulating a crash."""
    real_replace = os.replace
    calls = {"n": 0}

    def replace(src: Any, dst: Any) -> None:
        if not str(dst).endswith("journal.json"):
            calls["n"] += 1
            if calls["n"] == nth:
                raise CrashError
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)


def three_file_project(project: ProjectFactory) -> None:
    project.init()
    for name in ("a", "b", "c"):
        project.write(f"src/{name}.py", f"# TODO: task {name}\n")


@pytest.mark.parametrize("nth", [1, 2, 3, 4])
def test_crash_mid_commit_rolls_forward(
    project: ProjectFactory, clock: FakeClock, monkeypatch: pytest.MonkeyPatch, nth: int
) -> None:
    three_file_project(project)
    planned = Project.open(project.root, clock=clock).scan(dry_run=True)
    expected_ids = sorted(p.task_id for p in planned.proposals)

    crash_on_replace(monkeypatch, nth)
    with pytest.raises(CrashError):
        Project.open(project.root, clock=clock).scan(dry_run=False)
    monkeypatch.undo()
    assert persistence.pending_journal(project.root)

    # A dry run reports the interruption but doesn't fix it.
    dry = Project.open(project.root, clock=clock).scan(dry_run=True)
    assert "pending_journal" in {str(d.code) for d in dry.diagnostics}

    report = Project.open(project.root, clock=clock).scan(dry_run=False)
    assert report.recovered
    assert not persistence.pending_journal(project.root)
    assert list((project.root / ".byteplan/txn").iterdir()) == []

    tasks = json.loads((project.root / ".byteplan/tasks.json").read_text())["tasks"]
    assert sorted(tasks) == expected_ids  # no ID allocated twice, none orphaned
    for task_id, task in tasks.items():
        assert f"[{task_id}]" in (project.root / task["source"]["path"]).read_text()
    assert Project.open(project.root, clock=clock).scan(dry_run=False).written == ()


def test_crash_before_journal_leaves_files_untouched(
    project: ProjectFactory, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    three_file_project(project)
    before = project.snapshot()

    def fail(*_: Any, **__: Any) -> None:
        raise CrashError

    monkeypatch.setattr(persistence, "_apply", fail)
    monkeypatch.setattr(persistence, "atomic_write_bytes", fail)
    with pytest.raises(CrashError):
        Project.open(project.root, clock=clock).scan(dry_run=False)
    monkeypatch.undo()
    after = {k: v for k, v in project.snapshot().items() if not k.startswith(".byteplan/txn/")}
    assert after == before
    assert not persistence.pending_journal(project.root)
    Project.open(project.root, clock=clock).scan(dry_run=False)
    assert list((project.root / ".byteplan/txn").iterdir()) == []


def test_journal_conflict_is_not_overwritten(
    project: ProjectFactory, clock: FakeClock, monkeypatch: pytest.MonkeyPatch, run_cli: RunCli
) -> None:
    three_file_project(project)
    crash_on_replace(monkeypatch, 2)
    with pytest.raises(CrashError):
        Project.open(project.root, clock=clock).scan(dry_run=False)
    monkeypatch.undo()
    entries = json.loads(persistence.journal_path(project.root).read_text())["entries"]
    unfinished = project.root / entries[-1]["target"]
    unfinished.write_text("# someone edited this meanwhile\n")

    result = run_cli("scan", "--project", project.root)
    assert result.code == 2
    assert "cannot be completed" in result.err
    assert unfinished.read_text() == "# someone edited this meanwhile\n"
    assert persistence.pending_journal(project.root)


def test_concurrent_edit_between_plan_and_commit(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch, run_cli: RunCli
) -> None:
    three_file_project(project)
    real_commit = persistence.commit

    def edit_then_commit(root: Path, writes: Any) -> list[str]:
        (root / "src/b.py").write_text("# TODO: edited in an editor meanwhile\n")
        return real_commit(root, writes)

    monkeypatch.setattr("byteplan.api.commit", edit_then_commit)
    before = {k: v for k, v in project.snapshot().items() if k != "src/b.py"}
    result = run_cli("scan", "--project", project.root)
    assert result.code == 2
    assert "changed while byteplan was running: src/b.py" in result.err
    assert {k: v for k, v in project.snapshot().items() if k != "src/b.py"} == before
    assert (project.root / "src/b.py").read_text() == "# TODO: edited in an editor meanwhile\n"


def test_commit_rejects_stale_before_hash(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("new\n")
    with pytest.raises(ConcurrentModificationError):
        commit(tmp_path, [FileWrite("f.py", sha256(b"old\n"), b"x\n")])
    assert (tmp_path / "f.py").read_text() == "new\n"


def test_commit_skips_unchanged_and_creates_new(tmp_path: Path) -> None:
    (tmp_path / "same.txt").write_bytes(b"same")
    written = commit(
        tmp_path,
        [FileWrite("same.txt", sha256(b"same"), b"same"), FileWrite("new/file.txt", None, b"hi")],
    )
    assert written == ["new/file.txt"]
    assert (tmp_path / "new/file.txt").read_bytes() == b"hi"


def test_unreadable_journal(tmp_path: Path) -> None:
    journal = persistence.journal_path(tmp_path)
    journal.parent.mkdir(parents=True)
    journal.write_text("{not json")
    with pytest.raises(JournalConflictError, match="unreadable journal"):
        recover(tmp_path)


def test_corrupt_staged_copy(tmp_path: Path) -> None:
    txn = persistence.journal_path(tmp_path).parent
    txn.mkdir(parents=True)
    (txn / "0.stage").write_bytes(b"tampered")
    (tmp_path / "f.py").write_bytes(b"old")
    entry = {"target": "f.py", "staged": "0.stage", "before": sha256(b"old"), "after": sha256(b"new"), "mode": None}
    persistence.journal_path(tmp_path).write_text(json.dumps({"version": 1, "entries": [entry]}))
    with pytest.raises(JournalConflictError, match="corrupt"):
        recover(tmp_path)
    assert (tmp_path / "f.py").read_bytes() == b"old"
