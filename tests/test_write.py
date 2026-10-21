# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Phase 2: annotation, reconciliation, and registry-only lifecycle commands."""

from __future__ import annotations

import ast
import json
import os
import stat
import sys
from typing import TYPE_CHECKING, Any

import pytest

from byteplan.api import Project
from byteplan.diagnostics import EXIT_FINDINGS, Code
from byteplan.models import Presence, Status

if TYPE_CHECKING:
    from tests.conftest import FakeClock, ProjectFactory, RunCli


def open_project(project: ProjectFactory, clock: FakeClock) -> Project:
    return Project.open(project.root, clock=clock)


def registry(project: ProjectFactory) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((project.root / ".byteplan/tasks.json").read_text(encoding="utf-8"))
    return data


def only_task(project: ProjectFactory) -> dict[str, Any]:
    tasks = registry(project)["tasks"]
    assert len(tasks) == 1, tasks
    task: dict[str, Any] = next(iter(tasks.values()))
    return task


def scan(project: ProjectFactory, clock: FakeClock, *targets: str) -> Any:
    return open_project(project, clock).scan(list(targets) or None, cwd=project.root, dry_run=False)


# Annotation (spec 6) ----------------------------------------------------------


def test_fresh_scan_annotates_source_and_registers_tasks(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    path = project.write(
        "src/rip.py",
        """\
        class Router:
            # TODO: Implement route poisoning
            #   Support split horizon and poisoned reverse.
            def send(self):
                x = 1  # fixme: trailing
        """,
    )
    report = scan(project, clock)
    ids = [p.task_id for p in report.proposals]
    text = path.read_text()
    assert f"    # TODO[{ids[0]}]: Implement route poisoning\n" in text
    assert f"x = 1  # fixme[{ids[1]}]: trailing\n" in text
    assert "#   Support split horizon and poisoned reverse.\n" in text

    tasks = registry(project)["tasks"]
    assert sorted(tasks) == sorted(ids)
    todo = tasks[ids[0]]
    assert todo["title"] == "Implement route poisoning"
    assert todo["description"] == "Support split horizon and poisoned reverse."
    assert todo["source"] == {"path": "src/rip.py", "line": 2, "symbol": "Router.send"}
    assert (todo["status"], todo["presence"]) == ("open", "present")
    assert [e["event"] for e in todo["history"]] == ["created"]
    assert sorted(registry(project)["reserved_ids"]) == sorted(ids)


@pytest.mark.parametrize(
    "data",
    [
        b"# TODO: crlf\r\nx = 1\r\n",
        b"x = 1\n# TODO: no final newline",
        b"\xef\xbb\xbf# TODO: bom\n",
        b"# -*- coding: latin-1 -*-\n# TODO: caf\xe9\nname = '\xe9'\n",
        "# TODO: Überprüfen 路由\n#   détail\n".encode(),
        b"#!/usr/bin/env python\nif True:\n\t# XXX: tabs\n\tpass\n",
    ],
    ids=["crlf", "no-final-newline", "bom", "latin-1", "non-ascii", "tabs-shebang"],
)
def test_annotation_changes_only_the_id(project: ProjectFactory, clock: FakeClock, data: bytes) -> None:
    project.init()
    path = project.write("a.py", data)
    task_id = scan(project, clock).proposals[0].task_id
    after = path.read_bytes()
    tag_end = data.lower().index(b"todo") if b"todo" in data.lower() else data.index(b"XXX")
    tag_end += 3 if data[tag_end : tag_end + 3] == b"XXX" else 4
    assert after == data[:tag_end] + f"[{task_id}]".encode() + data[tag_end:]
    ast.parse(after)


def test_permissions_are_preserved(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    path = project.write("tool.py", "#!/usr/bin/env python\n# TODO: x\n")
    path.chmod(0o751)
    scan(project, clock)
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) == 0o751


# Identity (spec 7, addendum 19 for comments) ----------------------------------------------


def test_inserted_lines_moves_and_renames_keep_the_id(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    project.write("src/a.py", "def f():\n    # TODO: keep me\n    pass\n")
    scan(project, clock)
    task_id = only_task(project)["id"]
    tagged = (project.root / "src/a.py").read_text()

    project.write("src/a.py", "import os\n\n\n" + tagged)
    scan(project, clock)
    assert only_task(project)["source"]["line"] == 5
    assert [e["event"] for e in only_task(project)["history"]] == ["created"]  # line shifts aren't events

    (project.root / "src/a.py").unlink()
    project.write("src/pkg/b.py", "import os\n\n\n" + tagged.replace("def f", "def g"))
    scan(project, clock)
    task = only_task(project)
    assert task["id"] == task_id
    assert task["source"] == {"path": "src/pkg/b.py", "line": 5, "symbol": "g"}
    moved = task["history"][-1]
    assert moved["event"] == "moved"
    assert moved["old"] == {"path": "src/a.py", "symbol": "f"}
    assert task["presence"] == "present"


def test_text_change_updates_display_fields_not_identity(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    path = project.write("a.py", "# TODO: old title\n")
    scan(project, clock)
    task_id = only_task(project)["id"]
    path.write_text(path.read_text().replace("old title", "new title") + "#   and detail\n")
    scan(project, clock)
    task = only_task(project)
    assert (task["id"], task["title"], task["description"]) == (task_id, "new title", "and detail")
    event = task["history"][-1]
    assert event["event"] == "text_changed"
    assert event["old"] == {"title": "old title", "description": ""}


# Managed fields survive (spec 8) -------------------------------------------------


def test_managed_fields_survive_rescans(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    path = project.write("a.py", "# TODO: title from source\n")
    scan(project, clock)
    task_id = only_task(project)["id"]
    proj = open_project(project, clock)
    proj.set_status(task_id, Status.IN_PROGRESS)
    proj.edit_task(
        task_id,
        priority="high",
        assignee="sam",
        add_labels=["routing"],
        notes="see RFC",
        title_override="Better title",
    )
    path.write_text(path.read_text().replace("title from source", "edited in source"))
    scan(project, clock)
    task = only_task(project)
    assert (task["status"], task["priority"], task["assignee"]) == ("in_progress", "high", "sam")
    assert (task["labels"], task["notes"], task["title_override"]) == (["routing"], "see RFC", "Better title")
    assert task["title"] == "edited in source"


# Missing and reappearing (spec 9, 10; addendum 15) ---------------------------------


def test_deleted_annotation_is_missing_not_resolved(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    path = project.write("a.py", "# TODO: will vanish\nx = 1\n")
    scan(project, clock)
    task_id = only_task(project)["id"]
    tagged = path.read_text()

    path.write_text("x = 1\n")
    report = scan(project, clock)
    task = only_task(project)
    assert (task["status"], task["presence"]) == ("open", "missing")
    assert task["history"][-1]["event"] == "missing"
    assert task_id in registry(project)["reserved_ids"]
    assert [d.code for d in report.diagnostics] == [Code.MISSING]

    path.write_text(tagged)
    scan(project, clock)
    task = only_task(project)
    assert (task["id"], task["status"], task["presence"]) == (task_id, "open", "present")
    assert [e["event"] for e in task["history"]] == ["created", "missing", "reappeared"]


def test_missing_is_logged_once(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    path = project.write("a.py", "# TODO: x\n")
    scan(project, clock)
    path.write_text("")
    scan(project, clock)
    before = (project.root / ".byteplan/tasks.json").read_bytes()
    scan(project, clock)
    assert (project.root / ".byteplan/tasks.json").read_bytes() == before


def test_missing_policy_ignore_and_fail(project: ProjectFactory, clock: FakeClock, run_cli: RunCli) -> None:
    project.init()
    path = project.write("a.py", "# TODO: x\n")
    scan(project, clock)
    path.write_text("")
    pyproject = (project.root / "pyproject.toml").read_text()
    project.write("pyproject.toml", pyproject + "\n[tool.byteplan.check]\nfail_on_missing = true\n", dedent=False)
    assert run_cli("scan", "--project", project.root).code == EXIT_FINDINGS
    project.write("pyproject.toml", pyproject.replace("[tool.byteplan]", '[tool.byteplan]\nmissing_policy = "ignore"'))
    result = run_cli("scan", "--project", project.root)
    assert "MISSING" not in result.err


def test_task_outside_configured_scope_is_excluded_not_missing(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    project.write("legacy/old.py", "# TODO: legacy\n")
    scan(project, clock)
    pyproject = (project.root / "pyproject.toml").read_text()
    project.write("pyproject.toml", pyproject.replace('include = ["**/*.py"]', 'include = ["src/**/*.py"]'))
    scan(project, clock)
    task = only_task(project)
    assert (task["presence"], task["scope_state"]) == ("present", "excluded")


# Narrowed and failed scans (spec 14) -----------------------------------------------


def test_narrowed_scan_never_marks_other_tasks_missing(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    project.write("src/a.py", "# TODO: a\n")
    other = project.write("src/b.py", "# TODO: b\n")
    scan(project, clock)
    other.write_text("")  # b's task is gone, but we only scan a.py
    project.write("src/a.py", (project.root / "src/a.py").read_text() + "# TODO: a2\n")
    report = scan(project, clock, "src/a.py")
    assert len(report.summary.added) == 1
    assert {t["presence"] for t in registry(project)["tasks"].values()} == {"present"}


def test_failed_scan_writes_nothing(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    project.write("a.py", "# TODO: a\n")
    scan(project, clock)
    (project.root / "a.py").write_text("")
    project.write("broken.py", "def f(:\n")
    before = project.snapshot()
    with pytest.raises(Exception, match="scan aborted"):
        scan(project, clock)
    assert project.snapshot() == before
    assert only_task(project)["presence"] == "present"


# Stale, duplicate, unregistered (spec 11, 12, 13) ------------------------------------


def test_resolve_does_not_touch_source_and_leaves_stale_warning(
    project: ProjectFactory, clock: FakeClock, run_cli: RunCli
) -> None:
    project.init()
    project.write("a.py", "# TODO: done soon\n")
    scan(project, clock)
    task_id = only_task(project)["id"]
    source_before = (project.root / "a.py").read_bytes()
    result = run_cli("resolve", task_id, "--note", "shipped in 1.2", "--project", project.root)
    assert result.code == 0
    assert "still in source" in result.err
    assert (project.root / "a.py").read_bytes() == source_before
    event = only_task(project)["history"][-1]
    assert (event["event"], event["old"], event["new"], event["note"]) == (
        "resolved",
        "open",
        "resolved",
        "shipped in 1.2",
    )
    report = scan(project, clock)
    assert [d.code for d in report.diagnostics] == [Code.STALE_ANNOTATION]
    assert only_task(project)["status"] == "resolved"


def test_duplicate_ids_block_all_writes(project: ProjectFactory, clock: FakeClock, run_cli: RunCli) -> None:
    project.init()
    project.write("a.py", "# TODO: original\n")
    scan(project, clock)
    task_id = only_task(project)["id"]
    project.write("b.py", f"# TODO[{task_id}]: pasted copy\n# TODO: new one\n")
    before = project.snapshot()
    result = run_cli("scan", "--project", project.root)
    assert result.code == EXIT_FINDINGS
    assert "Nothing was written" in result.out
    assert project.snapshot() == before
    assert run_cli("duplicates", "--project", project.root).code == EXIT_FINDINGS


def test_unregistered_id_is_never_rewritten_or_imported(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    path = project.write("a.py", "# TODO[beef]: from another project\n")
    report = scan(project, clock)
    assert [d.code for d in report.diagnostics] == [Code.UNREGISTERED_ID]
    assert path.read_text() == "# TODO[beef]: from another project\n"
    assert registry(project)["tasks"] == {}


# Idempotence (spec 15) ----------------------------------------------------------------


def test_repeated_scans_change_nothing(project: ProjectFactory, clock: FakeClock, run_cli: RunCli) -> None:
    project.init()
    project.write("src/a.py", "# TODO: a\n#   detail\nclass C:\n    pass  # HACK: b\n")
    project.write("src/b.py", "def f():\n    ...  # XXX: c\n")
    scan(project, clock)
    first = project.snapshot()
    for _ in range(3):
        report = scan(project, clock)
        assert report.written == ()
        assert project.snapshot() == first
    result = run_cli("scan", "--project", project.root)
    assert "+0 added · ~0 relocated · !0 missing" in result.out
    assert project.snapshot() == first


# Dry run and read-only commands (spec 17) ----------------------------------------------


def test_dry_run_and_reads_never_write(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    project.write("a.py", "# TODO: x\n")
    before = project.snapshot()
    result = run_cli("scan", "--dry-run", "--project", project.root)
    assert "Would annotate" in result.out
    assert "Dry run" in result.out
    for args in (["list"], ["missing"], ["duplicates"], ["scan", "--dry-run", "--format", "json"]):
        run_cli(*args, "--project", project.root)
    assert project.snapshot() == before


# Registry commands -----------------------------------------------------------------------


def test_status_edit_cli(project: ProjectFactory, clock: FakeClock, run_cli: RunCli) -> None:
    project.init()
    project.write("a.py", "# TODO: x\n")
    scan(project, clock)
    task_id = only_task(project)["id"]
    root = project.root
    assert run_cli("status", task_id, "blocked", "--project", root).out.strip().endswith("status is now blocked")
    assert "unchanged" in run_cli("status", task_id, "blocked", "--project", root).out
    run_cli(
        "edit", task_id, "--priority", "high", "--assignee", "sam", "--label", "a", "--label", "b", "--project", root
    )
    run_cli("edit", task_id, "--remove-label", "a", "--add-note", "first", "--project", root)
    run_cli("edit", task_id, "--add-note", "second", "--unassign", "--project", root)
    task = only_task(project)
    assert (task["status"], task["priority"], task["assignee"], task["labels"]) == ("blocked", "high", None, ["b"])
    assert task["notes"] == "first\n\nsecond"
    edited = [e for e in task["history"] if e["event"] == "edited"]
    assert edited[0]["new"]["labels"] == ["a", "b"]
    payload = json.loads(run_cli("edit", task_id, "--title", "Shown", "--format", "json", "--project", root).out)
    assert payload["changed"]
    assert payload["task"]["title_override"] == "Shown"
    assert "[" + task_id + "] TODO: Shown" in run_cli("show", task_id, "--project", root).out
    assert run_cli("status", "ffff", "open", "--project", root).code == 2


def test_missing_command(project: ProjectFactory, clock: FakeClock, run_cli: RunCli) -> None:
    project.init()
    path = project.write("a.py", "# TODO: x\n")
    scan(project, clock)
    assert "No missing tasks" in run_cli("missing", "--project", project.root).out
    path.write_text("")
    scan(project, clock)
    task_id = only_task(project)["id"]
    assert task_id in run_cli("missing", "--project", project.root).out
    run_cli("resolve", task_id, "--project", project.root)
    assert [d.code for d in scan(project, clock).diagnostics] == []  # resolved + gone = finished
    shown = run_cli("show", task_id, "--project", project.root).out
    assert "created  line=1, path=a.py" in shown
    assert "missing  present → missing" in shown


def test_auto_annotate_off_tracks_only_tagged(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    pyproject = (project.root / "pyproject.toml").read_text()
    project.write("pyproject.toml", pyproject.replace("[tool.byteplan]", "[tool.byteplan]\nauto_annotate = false"))
    path = project.write("a.py", "# TODO: untagged\n")
    report = scan(project, clock)
    assert report.proposals == ()
    assert path.read_text() == "# TODO: untagged\n"


def test_lock_held_by_live_process(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    lock = project.root / ".byteplan/scan.lock"
    lock.write_text(str(os.getpid()))
    result = run_cli("scan", "--project", project.root)
    assert result.code == 2
    assert "holds .byteplan/scan.lock" in result.err
    assert lock.exists()


@pytest.mark.skipif(sys.platform == "win32", reason="stale-lock probing is POSIX-only")
def test_stale_lock_is_taken_over(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    project.write("a.py", "# TODO: x\n")
    (project.root / ".byteplan/scan.lock").write_text("999999999")
    scan(project, clock)
    assert not (project.root / ".byteplan/scan.lock").exists()
    assert len(registry(project)["tasks"]) == 1


def test_presence_values_are_reported_by_list(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    project.write("a.py", "# TODO: x\n")
    scan(project, clock)
    assert [t.presence for t in open_project(project, clock).list_tasks()] == [Presence.PRESENT]


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs POSIX permissions as non-root")
def test_unreadable_directory_aborts_instead_of_marking_missing(project: ProjectFactory, clock: FakeClock) -> None:
    """Codex review: an unlistable directory must not look like deleted source."""
    project.init()
    project.write("src/locked/a.py", "# TODO: still here\n")
    scan(project, clock)
    locked = project.root / "src/locked"
    locked.chmod(0)
    try:
        registry_before = (project.root / ".byteplan/tasks.json").read_bytes()
        with pytest.raises(Exception, match=r"src/locked: cannot list directory"):
            scan(project, clock)
        assert (project.root / ".byteplan/tasks.json").read_bytes() == registry_before
    finally:
        locked.chmod(0o755)
    assert only_task(project)["presence"] == "present"
