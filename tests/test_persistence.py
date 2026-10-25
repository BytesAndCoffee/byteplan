# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Crash recovery (spec 16, addendum 17) and concurrent edits (addendum 18)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest

from byteplan import persistence
from byteplan._todo import verifies
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


def test_edit_after_journal_is_written_is_not_overwritten(
    project: ProjectFactory, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex review: an editor saving a target mid-commit must not be clobbered."""
    three_file_project(project)
    real_write = persistence.atomic_write_bytes

    def write_then_edit(path: Path, data: bytes, mode: int | None = None) -> bool:
        written = real_write(path, data, mode)
        if path.name == persistence.JOURNAL:
            (project.root / "src/c.py").write_text("# TODO: saved by an editor just now\n")
        return written

    monkeypatch.setattr(persistence, "atomic_write_bytes", write_then_edit)
    with pytest.raises(JournalConflictError, match=r"src/c\.py changed while byteplan was writing"):
        Project.open(project.root, clock=clock).scan(dry_run=False)
    monkeypatch.undo()
    assert (project.root / "src/c.py").read_text() == "# TODO: saved by an editor just now\n"
    assert persistence.pending_journal(project.root)
    with pytest.raises(JournalConflictError):
        Project.open(project.root, clock=clock).scan(dry_run=False)
    assert (project.root / "src/c.py").read_text() == "# TODO: saved by an editor just now\n"


def test_target_directories_are_fsynced_before_the_journal_is_removed(
    project: ProjectFactory, clock: FakeClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Codex review: renames must be durable before recovery information is deleted."""
    project.init()
    project.write("src/a.py", "# TODO: a\n")
    project.write("lib/b.py", "# TODO: b\n")
    events: list[tuple[str, Path]] = []
    real_fsync_dir, real_finish = persistence._fsync_dir, persistence._finish  # noqa: SLF001

    def record_fsync(path: Path) -> None:
        events.append(("fsync", path.resolve()))
        real_fsync_dir(path)

    def record_finish(txn: Path) -> None:
        events.append(("finish", txn))
        real_finish(txn)

    monkeypatch.setattr(persistence, "_fsync_dir", record_fsync)
    monkeypatch.setattr(persistence, "_finish", record_finish)
    Project.open(project.root, clock=clock).scan(dry_run=False)

    finish = next(i for i, (kind, _) in enumerate(events) if kind == "finish")
    synced = {path for kind, path in events[:finish] if kind == "fsync"}
    root = project.root.resolve()
    assert {root / "src", root / "lib", root / ".byteplan"} <= synced


def test_uncreatable_directory_fails_before_the_journal(tmp_path: Path) -> None:
    """A target whose directory can't be created (a file is in the way) fails the commit cleanly:
    no journal is left behind for every later write to trip over."""
    (tmp_path / "tests").write_bytes(b"not a directory\n")
    writes = [FileWrite("a.txt", None, b"a\n"), FileWrite("tests/test_a.py", None, b"x = 1\n")]
    with pytest.raises(OSError):  # noqa: PT011 - FileExistsError or NotADirectoryError, by OS
        commit(tmp_path, writes)
    assert not persistence.journal_path(tmp_path).exists()
    assert not (tmp_path / "a.txt").exists()
    assert recover(tmp_path) == []
    assert commit(tmp_path, writes[:1]) == ["a.txt"]


def recovery_plan(root: Path) -> dict[str, Any]:
    txn = persistence.journal_path(root).parent
    txn.mkdir(parents=True)
    entries = []
    for number, name in enumerate(("a.py", "b.py")):
        (root / name).write_bytes(b"old")
        staged = f"{number}.stage"
        (txn / staged).write_bytes(b"new")
        entries.append(
            {"target": name, "staged": staged, "before": sha256(b"old"), "after": sha256(b"new"), "mode": None}
        )
    return {"version": 1, "entries": entries}


@verifies("62edd5")
@pytest.mark.parametrize(
    "defect",
    [
        "version",
        "version_bool",
        "container",
        "entry",
        "unknown",
        "duplicate_target",
        "duplicate_copy",
        "absolute",
        "traversal",
        "vcs",
        "transaction",
        "copy_path",
        "hash",
        "mode",
        "duplicate_key",
    ],
)
def test_recover_rejects_whole_invalid_journal_without_changes(tmp_path: Path, defect: str) -> None:
    journal = recovery_plan(tmp_path)
    entry = journal["entries"][1]
    if defect == "version":
        journal["version"] = 2
    elif defect == "version_bool":
        journal["version"] = True
    elif defect == "container":
        journal["entries"] = {}
    elif defect == "entry":
        journal["entries"][1] = []
    elif defect == "unknown":
        entry["extra"] = True
    elif defect == "duplicate_target":
        entry["target"] = "a.py"
    elif defect == "duplicate_copy":
        entry["staged"] = "0.stage"
    elif defect in {"absolute", "traversal", "vcs", "transaction"}:
        entry["target"] = {
            "absolute": str(tmp_path / "b.py"),
            "traversal": "src/../b.py",
            "vcs": ".git/config",
            "transaction": ".byteplan/txn/1.stage",
        }[defect]
    elif defect == "copy_path":
        entry["staged"] = "../1.stage"
    elif defect == "hash":
        entry["after"] = 2
    elif defect == "mode":
        entry["mode"] = True
    encoded = json.dumps(journal)
    if defect == "duplicate_key":
        encoded = encoded.replace('"version": 1', '"version": 1, "version": 1')
    path = persistence.journal_path(tmp_path)
    path.write_text(encoded)
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with pytest.raises(JournalConflictError, match="journal"):
        recover(tmp_path)
    assert {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


@verifies("62edd5")
def test_recover_checks_all_copies_before_first_write(tmp_path: Path) -> None:
    journal = recovery_plan(tmp_path)
    path = persistence.journal_path(tmp_path)
    path.write_text(json.dumps(journal))
    (path.parent / "1.stage").write_bytes(b"truncated")
    before = path.read_bytes()
    with pytest.raises(JournalConflictError, match="corrupt"):
        recover(tmp_path)
    assert (tmp_path / "a.py").read_bytes() == b"old"
    assert (tmp_path / "b.py").read_bytes() == b"old"
    assert path.read_bytes() == before
    assert (path.parent / "0.stage").read_bytes() == b"new"


@verifies("62edd5")
@pytest.mark.parametrize("target", ["/absolute.py", "../escape.py", ".git/config", ".byteplan/txn/journal.json"])
def test_commit_validates_entire_target_set_first(tmp_path: Path, target: str) -> None:
    with pytest.raises(JournalConflictError, match="unsafe write plan"):
        commit(tmp_path, [FileWrite("a.py", None, b"new"), FileWrite(target, None, b"new")])
    assert list(tmp_path.iterdir()) == []


def test_atomic_write_exclusive_collision_preserves_existing_temp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "a.py"
    alias = tmp_path / ".a.py.byteplan-collision.tmp"
    alias.write_bytes(b"keep")
    tokens = iter(("collision", "fresh"))
    monkeypatch.setattr("byteplan.persistence.secrets.token_hex", lambda _: next(tokens))
    assert persistence.atomic_write_bytes(target, b"new")
    assert target.read_bytes() == b"new"
    assert alias.read_bytes() == b"keep"
    assert not (tmp_path / ".a.py.byteplan-fresh.tmp").exists()


@verifies("62edd5")
def test_recover_rejects_symlink_copy_without_cleanup(tmp_path: Path) -> None:
    journal = recovery_plan(tmp_path)
    path = persistence.journal_path(tmp_path)
    path.write_text(json.dumps(journal))
    copy = path.parent / "1.stage"
    copy.unlink()
    copy.symlink_to("0.stage")
    before = path.read_bytes()
    with pytest.raises(JournalConflictError, match="non-symlink"):
        recover(tmp_path)
    assert path.read_bytes() == before
    assert copy.is_symlink()
    assert (tmp_path / "a.py").read_bytes() == b"old"
    assert (tmp_path / "b.py").read_bytes() == b"old"


def test_atomic_write_preserves_umask_permissions_and_binary_bytes(tmp_path: Path) -> None:
    # Isolate umask in a child; never change the process-wide mask of the test runner.
    script = """
import os
import stat
import sys
from pathlib import Path
from byteplan.persistence import atomic_write_bytes
root = Path(sys.argv[1])
os.umask(0o027)
reference = root / "reference"
fd = os.open(reference, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
os.close(fd)
created = root / "created"
payload = bytes((0, 10, 13, 26, 255))
assert atomic_write_bytes(created, payload)
assert created.read_bytes() == payload
assert stat.S_IMODE(created.stat().st_mode) == stat.S_IMODE(reference.stat().st_mode)
created.chmod(0o604)
mode = stat.S_IMODE(created.stat().st_mode)
assert atomic_write_bytes(created, payload + b"changed")
assert stat.S_IMODE(created.stat().st_mode) == mode
"""
    subprocess.run([sys.executable, "-B", "-c", script, str(tmp_path)], check=True, capture_output=True)
