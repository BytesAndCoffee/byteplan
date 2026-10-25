# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Validate persisted staged plans before any worktree or index side effect."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from byteplan import gitwrite
from byteplan._todo import verifies
from byteplan.gitwrite import RollbackConflictError, StagedJournal
from tests.gitutil import git

if TYPE_CHECKING:
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
        data["version"] = 2
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
        encoded = encoded.replace('"version": 1', '"version": 1, "version": 1')
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
