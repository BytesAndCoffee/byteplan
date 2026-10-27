# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Validate persisted staged plans before any worktree or index side effect."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from byteplan import gitwrite
from byteplan._todo import verifies
from byteplan.gitwrite import RollbackConflictError, StagedJournal
from byteplan.persistence import atomic_write_bytes as real_atomic
from tests.gitutil import git

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from tests.conftest import ProjectFactory


def staged_plan(repo: ProjectFactory) -> StagedJournal:
    repo.write("src/c.py", "# TODO: first new task\n")
    repo.write("src/d.py", "# TODO: second new task\n")
    top = repo.root.parent
    git(top, "add", "proj/src/c.py", "proj/src/d.py")
    plan = gitwrite._plan(repo.root, top, gitwrite.index_path(top), lambda: "2026-10-25T00:00:00Z", framework=False)  # noqa: SLF001
    assert isinstance(plan, tuple)
    return plan[0]


def snapshot(repo: ProjectFactory) -> dict[str, bytes]:
    files = {str(p.relative_to(repo.root)): p.read_bytes() for p in repo.root.rglob("*") if p.is_file()}
    files["INDEX"] = (repo.root.parent / ".git/index").read_bytes()
    return files


def index_blob(top: Path, index: Path, path: str) -> bytes:
    """Read exact blob bytes from the selected index, without text-mode newline decoding."""
    return subprocess.run(
        ["git", "cat-file", "blob", f":{path}"],
        cwd=top,
        env={**os.environ, "GIT_INDEX_FILE": str(index)},
        capture_output=True,
        check=True,
    ).stdout


@verifies("dcd417")
@pytest.mark.parametrize("direction", ["forward", "rollback"])
@pytest.mark.parametrize("copy_kind", ["before", "after", "missing"])
def test_recovery_validates_all_copies_before_any_side_effect(
    repo: ProjectFactory, direction: str, copy_kind: str
) -> None:
    journal = staged_plan(repo)
    first, last = journal.entries[0], journal.entries[-1]
    directory = StagedJournal.path(repo.root).parent
    # An earlier target already changed before the crash. Rejection must preserve it,
    # including when rollback would otherwise restore the before copy immediately.
    (repo.root / first.path).write_bytes((directory / first.after_copy).read_bytes())
    first.written = True
    journal.direction = direction
    journal.save(repo.root)
    name = last.before_copy if copy_kind == "before" else last.after_copy
    assert name is not None
    if copy_kind == "missing":
        (directory / name).unlink()
    else:
        (directory / name).write_bytes(b"truncated scratch copy")
    before = snapshot(repo)
    with pytest.raises(RollbackConflictError, match=r"corrupt|invalid staged recovery copy"):
        gitwrite.recover(repo.root)
    assert snapshot(repo) == before


@verifies("62edd5")
@pytest.mark.parametrize(
    "defect",
    [
        "version",
        "duplicate_key",
        "entry",
        "direction",
        "target",
        "top_path",
        "copy",
        "mode",
        "written",
        "hash",
        "oid",
        "duplicate_target",
        "duplicate_copy",
        "index",
    ],
)
def test_staged_recovery_rejects_whole_invalid_journal(repo: ProjectFactory, defect: str) -> None:
    staged_plan(repo)
    path = StagedJournal.path(repo.root)
    data = json.loads(path.read_text())
    entry = data["entries"][-1]
    if defect == "version":
        data["version"] = 3
    elif defect == "entry":
        data["entries"][-1] = []
    elif defect == "direction":
        data["direction"] = []
    elif defect == "target":
        entry["path"] = "../elsewhere.py"
    elif defect == "top_path":
        entry["top_path"] = "other/file.py"
    elif defect == "copy":
        entry["after_copy"] = "../0.after"
    elif defect == "mode":
        entry["mode"] = "120000"
    elif defect == "written":
        entry["written"] = 1
    elif defect == "hash":
        entry["after_hash"] = None
    elif defect == "oid":
        entry["after_oid"] = True
    elif defect == "duplicate_target":
        entry["path"] = data["entries"][0]["path"]
    elif defect == "duplicate_copy":
        entry["after_copy"] = data["entries"][0]["after_copy"]
    elif defect == "index":
        data["index"] = str(repo.root / "unused-index")
    encoded = json.dumps(data)
    if defect == "duplicate_key":
        encoded = encoded.replace('"version": 2', '"version": 2, "version": 2')
    path.write_text(encoded)
    before = snapshot(repo)
    with pytest.raises(RollbackConflictError):
        gitwrite.recover(repo.root)
    assert snapshot(repo) == before


@verifies("62edd5")
def test_saved_index_cannot_select_existing_sibling_by_prefix(repo: ProjectFactory) -> None:
    journal = staged_plan(repo)
    sibling = repo.root.parent / ".git/index.backup"
    sibling.write_bytes(b"ordinary scratch metadata")
    journal.index = str(sibling)
    journal.save(repo.root)
    before = snapshot(repo)
    with pytest.raises(RollbackConflictError, match="supported index"):
        gitwrite.recover(repo.root)
    assert snapshot(repo) == before
    assert sibling.read_bytes() == b"ordinary scratch metadata"


@verifies("62edd5")
@pytest.mark.parametrize("mode", ["selected", "index.lock", "framework"])
def test_supported_index_modes_recover(repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    journal = staged_plan(repo)
    if mode == "framework":
        journal.index = None
    else:
        top = repo.root.parent
        selected = top / ("selected-index" if mode == "selected" else ".git/index.lock")
        shutil.copyfile(top / ".git/index", selected)
        journal.index = str(selected)
        if mode == "selected":
            monkeypatch.setenv("GIT_INDEX_FILE", str(selected))
    journal.save(repo.root)
    messages = gitwrite.recover(repo.root)
    assert any("completed" in message for message in messages)
    assert not StagedJournal.path(repo.root).exists()
    assert b"TODO[" in (repo.root / "src/c.py").read_bytes()


@verifies("62edd5")
def test_staged_recovery_rejects_symlink_copy(repo: ProjectFactory) -> None:
    journal = staged_plan(repo)
    directory = StagedJournal.path(repo.root).parent
    copy = directory / journal.entries[-1].after_copy
    copy.unlink()
    copy.symlink_to(journal.entries[0].after_copy)
    before = snapshot(repo)
    with pytest.raises(RollbackConflictError, match="non-symlink"):
        gitwrite.recover(repo.root)
    assert snapshot(repo) == before
    assert copy.is_symlink()


@verifies("62edd5")
def test_linked_worktree_uses_its_own_git_index(repo: ProjectFactory, tmp_path: Path) -> None:
    top = repo.root.parent
    linked = tmp_path / "linked-worktree"
    git(top, "worktree", "add", "--detach", str(linked), "HEAD")
    project = linked / "proj"
    (project / "src/c.py").write_text("# TODO: linked worktree task\n")
    git(linked, "add", "proj/src/c.py")
    original_index = (top / ".git/index").read_bytes()
    outcome = gitwrite.reconcile_staged(project)
    assert outcome.code == 0
    assert b"TODO[" in (project / "src/c.py").read_bytes()
    assert (top / ".git/index").read_bytes() == original_index
    assert not StagedJournal.path(project).exists()


@verifies("62edd5")
@pytest.mark.parametrize("direction", ["forward", "rollback"])
@pytest.mark.parametrize(
    "present",
    [
        (False, False, True),
        (False, True, False),
        (False, True, True),
        (True, False, False),
        (True, False, True),
        (True, True, False),
    ],
)
def test_recovery_rejects_inconsistent_original_presence_before_any_side_effect(
    repo: ProjectFactory, direction: str, present: tuple[bool, bool, bool]
) -> None:
    journal = staged_plan(repo)
    top = repo.root.parent
    assert journal.index is not None
    gitwrite._swap_index(  # noqa: SLF001
        top,
        Path(journal.index),
        {
            entry.top_path: None if entry.before_oid is None else (entry.mode, entry.before_oid)
            for entry in journal.entries
        },
        {entry.top_path: (entry.mode, entry.after_oid) for entry in journal.entries},
    )
    gitwrite._write_worktree(repo.root, journal)  # noqa: SLF001
    journal.direction = direction
    journal.save(repo.root)
    path = StagedJournal.path(repo.root)
    data = json.loads(path.read_text())
    # Damage a later entry after index/worktree writes. Complete validation must
    # reject it before rollback can restore any earlier target or index entry.
    entry = data["entries"][-1]
    for key, keep in zip(("before_oid", "before_hash", "before_copy"), present, strict=True):
        assert entry[key] is not None
        if not keep:
            entry[key] = None
    path.write_text(json.dumps(data))
    before = snapshot(repo)
    with pytest.raises(RollbackConflictError, match="original object/copy/fingerprint presence disagree"):
        gitwrite.recover(repo.root)
    assert snapshot(repo) == before


@verifies("28e56f")
@pytest.mark.parametrize("eol", ["lf", "crlf"])
@pytest.mark.parametrize("object_format", ["sha1", "sha256"])
@pytest.mark.parametrize("operation", ["forward", "rollback", "recover_forward", "recover_rollback"])
@pytest.mark.parametrize("index_mode", ["default", "selected", "linked"])
def test_task_28e56f(
    project: ProjectFactory,
    monkeypatch: pytest.MonkeyPatch,
    object_format: str,
    operation: str,
    index_mode: str,
    eol: str,
) -> None:
    """Reconcile and recover a newly added registry in each supported object format."""
    top = project.root.parent
    initialized = git(top, "init", "-q", f"--object-format={object_format}", check=False)
    if object_format == "sha256" and initialized.returncode:
        # Skip only explicit Git capability failures; unrelated setup failures
        # must still fail this test rather than concealing broken fixtures.
        stderr = initialized.stderr.lower()
        if ("unknown option" in stderr and "object-format" in stderr) or "unknown hash algorithm 'sha256'" in stderr:
            pytest.skip(f"installed Git lacks SHA-256 repository support: {initialized.stderr.strip()}")
    assert initialized.returncode == 0, initialized.stderr
    # Explicit attributes exercise both Git views on every host, independently
    # of the user's core.autocrlf setting. Git blobs stay LF; checkout bytes vary.
    project.write(".gitattributes", f"src/*.py text eol={eol}\n.byteplan/tasks.json text eol={eol}\nuser.txt -text\n")
    line_ending = b"\r\n" if eol == "crlf" else b"\n"
    project.write("src/new.py", b"# TODO: object format task" + line_ending)
    project.write("user.txt", b"user staged bytes" + line_ending)
    git(top, "add", "proj/.gitattributes", "proj/pyproject.toml", "proj/src/new.py", "proj/user.txt")
    root = project.root
    main_index: tuple[Path, bytes] | None = None
    if index_mode == "linked":
        git(
            top,
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "base",
        )
        linked = top / "linked"
        git(top, "worktree", "add", "--detach", str(linked), "HEAD")
        main_path = gitwrite.index_path(top)
        main_index = (main_path, main_path.read_bytes())
        top, root = linked, linked / "proj"
    original_index = gitwrite.index_path(top)
    original_bytes = original_index.read_bytes()
    if index_mode == "selected":
        selected = top / "selected-index"
        shutil.copyfile(original_index, selected)
        monkeypatch.setenv("GIT_INDEX_FILE", str(selected))
    index = gitwrite.index_path(top)
    entries_before = git(top, "ls-files", "--stage").stdout
    source = root / "src/new.py"
    source_before = source.read_bytes()
    assert source_before == b"# TODO: object format task" + line_ending
    assert index_blob(top, index, "proj/src/new.py") == b"# TODO: object format task\n"
    user_before = index_blob(top, index, "proj/user.txt")
    # -text retains CRLF inside the blob too, proving the binary reader does
    # not silently normalize the unrelated staged content.
    assert user_before == b"user staged bytes" + line_ending
    (root / "user.txt").write_text("user unstaged bytes\n")
    user_worktree_before = (root / "user.txt").read_bytes()
    registry = root / ".byteplan/tasks.json"
    real_swap = gitwrite._swap_index  # noqa: SLF001
    swaps = 0

    def fail_source(path: Path, data: bytes, mode: int | None = None) -> None:
        if path == source:
            msg = "injected source write failure"
            raise OSError(msg)
        real_atomic(path, data, mode)

    def fail_rollback_swap(
        top: Path,
        index: Path,
        expected: Mapping[str, tuple[str, str] | None],
        wanted: Mapping[str, tuple[str, str] | None],
        precheck: Callable[[], None] | None = None,
    ) -> None:
        nonlocal swaps
        swaps += 1
        if swaps == 2:
            msg = "injected rollback publication failure"
            raise OSError(msg)
        real_swap(top, index, expected, wanted, precheck)

    if operation == "recover_forward":
        plan = gitwrite._plan(root, top, index, lambda: "2026-10-25T00:00:00Z", framework=False)  # noqa: SLF001
        assert isinstance(plan, tuple)
        assert StagedJournal.path(root).exists()
        assert "completed" in " ".join(gitwrite.recover(root))
    elif "rollback" in operation:
        with monkeypatch.context() as patch:
            patch.setattr(gitwrite, "atomic_write_bytes", fail_source)
            if operation == "recover_rollback":
                patch.setattr(gitwrite, "_swap_index", fail_rollback_swap)
            with pytest.raises(OSError, match="injected source write failure"):
                gitwrite.reconcile_staged(root)
        if operation == "recover_rollback":
            journal = StagedJournal.load(root)
            assert journal is not None
            assert journal.direction == "rollback"
            assert git(top, "ls-files", "--", "proj/.byteplan/tasks.json").stdout
            assert "undid" in " ".join(gitwrite.recover(root))
        assert git(top, "ls-files", "--stage").stdout == entries_before
        assert source.read_bytes() == source_before
        assert not registry.exists()
    else:
        assert gitwrite.reconcile_staged(root).code == 0
    if "rollback" not in operation:
        assert b"TODO[" in source.read_bytes()
        for path in ("src/new.py", ".byteplan/tasks.json"):
            blob = index_blob(top, index, f"proj/{path}")
            assert b"\n" in blob
            assert b"\r" not in blob
            assert (root / path).read_bytes() == blob.replace(b"\n", line_ending)
        oid = git(top, "rev-parse", ":proj/.byteplan/tasks.json").stdout.strip()
        assert len(oid) == (64 if object_format == "sha256" else 40)
    assert git(top, "show", ":proj/user.txt").stdout == "user staged bytes\n"
    assert index_blob(top, index, "proj/user.txt") == user_before
    assert (root / "user.txt").read_text() == "user unstaged bytes\n"
    assert (root / "user.txt").read_bytes() == user_worktree_before
    assert not StagedJournal.path(root).exists()
    if index_mode == "selected":
        assert original_index.read_bytes() == original_bytes
    if main_index is not None:
        assert main_index[0].read_bytes() == main_index[1]


@verifies("17f1f0")
@pytest.mark.parametrize("eol", ["lf", "crlf"])
@pytest.mark.parametrize("interrupted", [False, True])
def test_task_17f1f0(repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch, eol: str, *, interrupted: bool) -> None:
    """Legal short writes must preserve the entire index and unrelated staged content."""
    top = repo.root.parent
    repo.write(".gitattributes", f"src/new.py text eol={eol}\nuser.txt -text\n")
    line_ending = b"\r\n" if eol == "crlf" else b"\n"
    source = repo.write("src/new.py", b"# TODO: index short write task" + line_ending)
    repo.write("user.txt", b"user staged bytes" + line_ending)
    git(top, "add", "proj/src/new.py", "proj/user.txt")
    git(top, "update-index", "--chmod=+x", "proj/user.txt")
    index = gitwrite.index_path(top)
    assert source.read_bytes() == b"# TODO: index short write task" + line_ending
    assert index_blob(top, index, "proj/src/new.py") == b"# TODO: index short write task\n"
    user_before = index_blob(top, index, "proj/user.txt")
    assert user_before == b"user staged bytes" + line_ending
    user_entry = git(top, "ls-files", "--stage", "--", "proj/user.txt").stdout
    repo.write("user.txt", "user unstaged bytes\n")
    user_worktree_before = (repo.root / "user.txt").read_bytes()
    real_write = os.write
    calls = 0
    index_fd: int | None = None

    def short_write(fd: int, data: bytes | memoryview) -> int:
        nonlocal calls, index_fd
        if bytes(data[:4]) == b"DIRC":
            index_fd = fd
        if fd != index_fd:
            return real_write(fd, data)
        calls += 1
        if interrupted and calls == 2:
            raise InterruptedError
        return real_write(fd, data[: max(1, len(data) // 2)])

    monkeypatch.setattr(os, "write", short_write)
    assert gitwrite.reconcile_staged(repo.root).code == 0
    assert calls > 2
    assert git(top, "show", ":proj/user.txt").stdout == "user staged bytes\n"
    assert index_blob(top, index, "proj/user.txt") == user_before
    assert git(top, "ls-files", "--stage", "--", "proj/user.txt").stdout == user_entry
    assert (repo.root / "user.txt").read_text() == "user unstaged bytes\n"
    assert (repo.root / "user.txt").read_bytes() == user_worktree_before
    blob = index_blob(top, index, "proj/src/new.py")
    assert b"\n" in blob
    assert b"\r" not in blob
    assert source.read_bytes() == blob.replace(b"\n", line_ending)
    assert b"TODO[" in (repo.root / "src/new.py").read_bytes()
    assert not StagedJournal.path(repo.root).exists()


@verifies("17f1f0")
@pytest.mark.parametrize(
    "fault",
    ["zero", "error", "short_error", "interrupt", "corrupt", "fsync", "replace"],
)
def test_failed_index_publication_preserves_original_and_recovery(
    repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    top = repo.root.parent
    repo.write("user.txt", "user staged bytes\n")
    git(top, "add", "proj/user.txt")
    repo.write("user.txt", "user unstaged bytes\n")
    journal = staged_plan(repo)
    assert journal.index is not None
    index = Path(journal.index)
    before = snapshot(repo)
    real_write = os.write
    calls = 0
    index_fd: int | None = None

    def faulty_write(fd: int, data: bytes | memoryview) -> int:
        nonlocal calls, index_fd
        if bytes(data[:4]) == b"DIRC":
            index_fd = fd
        if fd != index_fd:
            return real_write(fd, data)
        calls += 1
        if fault == "zero":
            return 0
        if fault == "error" or (fault == "short_error" and calls > 1):
            msg = "injected index write failure"
            raise OSError(msg)
        if fault == "interrupt":
            raise KeyboardInterrupt
        if fault == "corrupt":
            return real_write(fd, b"X" * len(data))
        return real_write(fd, data[: max(1, len(data) // 2)])

    def fail_sync(_fd: int) -> None:
        msg = "injected fsync failure"
        raise OSError(msg)

    def fail_replace(_source: Path, _target: Path) -> None:
        msg = "injected index replace failure"
        raise OSError(msg)

    with monkeypatch.context() as patch:
        patch.setattr(os, "write", faulty_write)
        if fault == "fsync":
            patch.setattr(os, "fsync", fail_sync)
        if fault == "replace":
            patch.setattr(os, "replace", fail_replace)
        with pytest.raises(KeyboardInterrupt if fault == "interrupt" else OSError):
            gitwrite._swap_index(  # noqa: SLF001
                top,
                index,
                {entry.top_path: (entry.mode, entry.before_oid) for entry in journal.entries if entry.before_oid},
                {entry.top_path: (entry.mode, entry.after_oid) for entry in journal.entries},
            )
    assert calls > 0
    assert snapshot(repo) == before
    assert not index.with_name(index.name + ".lock").exists()
    assert not index.with_name(index.name + ".byteplan-scratch").exists()
    assert StagedJournal.path(repo.root).exists()
    assert "completed" in " ".join(gitwrite.recover(repo.root))
    assert git(top, "show", ":proj/user.txt").stdout == "user staged bytes\n"
    assert (repo.root / "user.txt").read_text() == "user unstaged bytes\n"
    assert not StagedJournal.path(repo.root).exists()


@verifies("6944ec")
def test_index_swap_never_writes_through_a_planted_scratch_link(
    repo: ProjectFactory, tmp_path_factory: pytest.TempPathFactory
) -> None:
    journal = staged_plan(repo)
    top = repo.root.parent
    assert journal.index is not None
    index = Path(journal.index)
    victim = tmp_path_factory.mktemp("outside") / "unrelated.txt"
    victim.write_bytes(b"important unrelated content\n")
    try:
        index.with_name(index.name + ".byteplan-scratch").symlink_to(victim)
    except OSError:
        pytest.skip("symlinks are not available")
    gitwrite._swap_index(  # noqa: SLF001
        top,
        index,
        {e.top_path: None if e.before_oid is None else (e.mode, e.before_oid) for e in journal.entries},
        {e.top_path: (e.mode, e.after_oid) for e in journal.entries},
    )
    assert victim.read_bytes() == b"important unrelated content\n"
    assert not [p for p in index.parent.iterdir() if p.name.endswith(".scratch")]  # its own copy is removed
