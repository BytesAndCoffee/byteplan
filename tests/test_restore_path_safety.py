# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Persisted restore and journal paths do not expand project write authority."""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any

import pytest

from byteplan import persistence
from byteplan._todo import verifies
from byteplan.api import Project
from byteplan.errors import JournalConflictError
from byteplan.operations import release as release_ops
from byteplan.persistence import FileWrite, sha256
from byteplan.release import ReleaseError

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import ProjectFactory


def stripped_project(project: ProjectFactory, files: dict[str, Any]) -> bytes:
    project.init()
    path = project.root / ".byteplan/tasks.json"
    data = json.loads(path.read_text())
    data["release"] = {"state": "stripped", "version": "1.0", "files": files}
    path.write_text(json.dumps(data))
    return path.read_bytes()


@verifies("62edd5")
@pytest.mark.parametrize("defect", ["absolute", "traversal", "vcs", "transaction", "record", "block"])
@pytest.mark.parametrize("dry_run", [True, False])
def test_restore_validates_all_records_before_source_reads(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch, defect: str, *, dry_run: bool
) -> None:
    record = {"sha256": sha256(b"pass\n"), "decorators": [], "imports": []}
    key = {
        "absolute": str(project.root / "z.py"),
        "traversal": "z/../z.py",
        "vcs": ".git/z.py",
        "transaction": ".byteplan/txn/z.py",
    }.get(defect, "z.py")
    invalid: Any = [] if defect == "record" else record
    if defect == "block":
        invalid = {**record, "decorators": [None]}
    before = stripped_project(project, {"a.py": record, key: invalid})
    reads = []

    def forbidden_read(path: Path) -> bytes:
        reads.append(path)
        msg = "source read before complete restore validation"
        raise AssertionError(msg)

    monkeypatch.setattr(release_ops, "_read_bytes", forbidden_read)
    with (
        contextlib.closing(Project.open(project.root)) as opened,
        pytest.raises(ReleaseError, match="unsafe serialized release"),
    ):
        opened.restore(dry_run=dry_run, partial=True)
    assert reads == []
    assert (project.root / ".byteplan/tasks.json").read_bytes() == before
    assert not persistence.pending_journal(project.root)


@verifies("62edd5")
@pytest.mark.parametrize("operation", ["restore", "commit", "recover"])
def test_source_parent_replaced_by_symlink_fails_safely(
    project: ProjectFactory, tmp_path: Path, operation: str
) -> None:
    record = {"sha256": sha256(b"pass\n"), "decorators": [], "imports": []}
    before = stripped_project(project, {"src/a.py": record})
    # Both directories belong to this temporary fixture. No real external file is read.
    sibling = tmp_path / "saved-source"
    sibling.mkdir()
    (sibling / "a.py").write_bytes(b"pass\n")
    source = project.root / "src"
    source.mkdir(exist_ok=True)
    source.rmdir()
    source.symlink_to(sibling, target_is_directory=True)
    if operation == "restore":
        with contextlib.closing(Project.open(project.root)) as opened, pytest.raises(ReleaseError, match="escapes"):
            opened.restore()
    elif operation == "commit":
        with pytest.raises(JournalConflictError, match="escapes"):
            persistence.commit(project.root, [FileWrite("src/a.py", sha256(b"pass\n"), b"new\n")])
    else:
        path = persistence.journal_path(project.root)
        path.parent.mkdir(parents=True)
        (path.parent / "0.stage").write_bytes(b"new\n")
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "entries": [
                        {
                            "target": "src/a.py",
                            "staged": "0.stage",
                            "before": sha256(b"pass\n"),
                            "after": sha256(b"new\n"),
                            "mode": None,
                        }
                    ],
                }
            )
        )
        saved = path.read_bytes()
        with pytest.raises(JournalConflictError, match="escapes"):
            persistence.recover(project.root)
        assert path.read_bytes() == saved
        assert (path.parent / "0.stage").read_bytes() == b"new\n"
    assert (sibling / "a.py").read_bytes() == b"pass\n"
    assert (project.root / ".byteplan/tasks.json").read_bytes() == before
