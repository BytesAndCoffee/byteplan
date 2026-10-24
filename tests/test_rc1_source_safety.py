# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""First-run and interrupted-transaction acceptance for the RC1 source-safety audit."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

import pytest

from byteplan import persistence
from byteplan._todo import verifies
from byteplan.api import Project
from byteplan.diagnostics import Code

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import ProjectFactory


@verifies("1b81")
def test_large_first_scan_previews_source_then_applies_idempotently(
    project: ProjectFactory,
) -> None:
    project.init()
    original: dict[str, bytes] = {}
    for index in range(256):
        newline = "\r\n" if index % 2 else "\n"
        text = (
            f"# TODO: Review module {index}\n"
            'raise RuntimeError("scanning must never import repository modules")\n'
            f"def implemented():\n    return {index}\n"
            "def pending():\n    pass\n"
        ).replace("\n", newline)
        data = (b"\xef\xbb\xbf" if index % 3 == 0 else b"") + text.encode()
        path = f"src/pkg{index // 16}/module{index:03d}.py"
        original[path] = data
        project.write(path, data)

    api = Project.open(project.root)
    before = project.snapshot()
    preview = api.scan()
    assert project.snapshot() == before
    assert preview.files_scanned == 256
    assert len(preview.proposals) == 512
    assert len({proposal.task_id for proposal in preview.proposals}) == 512
    assert all(len(proposal.task_id) == 6 for proposal in preview.proposals)
    planned_source = {write.path: write.data for write in preview.planned if write.path in original}
    assert set(planned_source) == set(original)

    result = api.scan(dry_run=False)
    assert {proposal.task_id for proposal in result.proposals} == {proposal.task_id for proposal in preview.proposals}
    assert set(result.written) == {*original, ".byteplan/tasks.json"}
    for path, old in original.items():
        written = (project.root / path).read_bytes()
        assert written == planned_source[path]
        assert ast.dump(ast.parse(written)) == ast.dump(ast.parse(old))
        assert written.startswith(b"\xef\xbb\xbf") == old.startswith(b"\xef\xbb\xbf")
        if b"\r\n" in old:
            assert b"\n" not in written.replace(b"\r\n", b"")

    after = project.snapshot()
    assert api.scan(dry_run=False).written == ()
    assert project.snapshot() == after
    assert len(api.list_tasks()) == 512
    assert all(str(task.status) == "open" for task in api.list_tasks())


@verifies("1b81")
@pytest.mark.parametrize("operation", ["scan", "check", "report", "cleanup", "sync", "migrate", "archive"])
def test_read_only_operations_leave_pending_recovery_untouched(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    project.init()
    project.write("a.py", "# TODO: interrupted first scan\nvalue = 1\n")
    api = Project.open(project.root)

    class InterruptedWriteError(Exception):
        pass

    real_write = persistence.atomic_write_bytes

    def interrupt_registry(path: Path, data: bytes, mode: int | None = None) -> bool:
        if path.name == "tasks.json":
            raise InterruptedWriteError
        return real_write(path, data, mode)

    with monkeypatch.context() as patch:
        patch.setattr(persistence, "atomic_write_bytes", interrupt_registry)
        with pytest.raises(InterruptedWriteError):
            api.scan(dry_run=False)
    assert persistence.pending_journal(project.root)
    assert "TODO[" in (project.root / "a.py").read_text()
    assert api.load_registry().tasks == {}
    before = project.snapshot()

    if operation in {"migrate", "archive"}:
        getattr(api, operation)(dry_run=True)
    else:
        getattr(api, operation)()
    assert project.snapshot() == before
    assert persistence.pending_journal(project.root)
    assert any(d.code is Code.PENDING_JOURNAL for d in api.check().diagnostics)
    assert project.snapshot() == before

    recovered = api.scan(dry_run=False)
    assert recovered.recovered
    assert len(api.load_registry().tasks) == 1
    assert not persistence.pending_journal(project.root)
    assert api.scan(dry_run=False).written == ()
