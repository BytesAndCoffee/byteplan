# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Archiving long-closed tasks: the local store, the committed index, and reconciling clones."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from byteplan import archive
from byteplan.cli import EXIT_FINDINGS, EXIT_OK
from byteplan.config import parse_config
from byteplan.errors import ConfigError
from byteplan.gitio import archive_driver_main
from tests.gitutil import git

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import ProjectFactory, RunCli


def _tasks(project: ProjectFactory) -> dict[str, dict[str, object]]:
    data: dict[str, dict[str, object]] = json.loads((project.root / ".byteplan/tasks.json").read_text())["tasks"]
    return data


def _registry(project: ProjectFactory) -> dict[str, object]:
    data: dict[str, object] = json.loads((project.root / ".byteplan/tasks.json").read_text())
    return data


def _id_of(project: ProjectFactory, title: str) -> str:
    return next(t for t, task in _tasks(project).items() if task["title"] == title)


def _close_and_commit(repo: ProjectFactory, run_cli: RunCli, title: str = "second task") -> str:
    """Resolve a task, take its annotation out of source, rescan, and commit."""
    task_id = _id_of(repo, title)
    assert run_cli("resolve", task_id, "--sync-source", "--project", repo.root).code == EXIT_OK
    assert run_cli("scan", "--project", repo.root).code == EXIT_OK
    git(repo.root.parent, "add", "-A")
    git(repo.root.parent, "commit", "-qm", "close")
    return task_id


def test_archive_moves_a_closed_gone_task_out_of_the_registry(repo: ProjectFactory, run_cli: RunCli) -> None:
    task_id = _close_and_commit(repo, run_cli)
    record = _tasks(repo)[task_id]
    dry = run_cli("archive", "--older-than", "0", "--dry-run", "--project", repo.root)
    assert dry.code == EXIT_OK
    assert f"would archive 1 task(s): {task_id}" in dry.out
    assert task_id in _tasks(repo)

    done = run_cli("archive", "--older-than", "0", "--project", repo.root)
    assert done.code == EXIT_OK
    assert f"archived 1 task(s): {task_id}" in done.out
    assert task_id not in _tasks(repo)
    assert task_id in _registry(repo)["reserved_ids"]  # type: ignore[operator]

    index = json.loads((repo.root / ".byteplan/archive.json").read_text())
    entry = index["tasks"][task_id]
    assert entry["sha256"] == archive.record_hash(record)
    assert entry["status"] == "resolved"
    assert entry["title"] == "second task"
    assert "archive.sqlite" in (repo.root / ".byteplan/.gitignore").read_text().split()
    assert "archive.sqlite" not in git(repo.root.parent, "status", "--porcelain").stdout

    shown = run_cli("show", task_id, "--format", "json", "--project", repo.root)
    assert shown.code == EXIT_OK
    assert json.loads(shown.out)["status"] == "resolved"
    listed = run_cli("list", "--archived", "--project", repo.root)
    assert task_id in listed.out
    assert "second task" in listed.out
    assert task_id not in run_cli("list", "--project", repo.root).out


def test_open_present_and_recent_tasks_stay(repo: ProjectFactory, run_cli: RunCli) -> None:
    open_id = _id_of(repo, "first task")
    closed_id = _close_and_commit(repo, run_cli)
    # Closed just now: not a week ago.
    assert "would archive 0 task(s)" in run_cli("archive", "--dry-run", "--project", repo.root).out
    out = run_cli("archive", "--older-than", "0", "--project", repo.root).out
    assert closed_id in out
    assert open_id not in out
    assert open_id in _tasks(repo)


def test_a_closed_task_still_annotated_in_source_stays(repo: ProjectFactory, run_cli: RunCli) -> None:
    task_id = _id_of(repo, "second task")
    assert run_cli("resolve", task_id, "--project", repo.root).code == EXIT_OK  # no --sync-source
    git(repo.root.parent, "add", "-A")
    git(repo.root.parent, "commit", "-qm", "resolve")
    assert "would archive 0 task(s)" in run_cli("archive", "--older-than", "0", "--dry-run", "--project", repo.root).out


def test_uncommitted_records_wait_for_a_commit(repo: ProjectFactory, run_cli: RunCli) -> None:
    task_id = _id_of(repo, "second task")
    assert run_cli("resolve", task_id, "--sync-source", "--project", repo.root).code == EXIT_OK
    assert run_cli("scan", "--project", repo.root).code == EXIT_OK
    result = run_cli("archive", "--older-than", "0", "--project", repo.root)
    assert "archived 0 task(s)" in result.out
    assert f"waiting for a commit (their current records aren't committed): {task_id}" in result.out
    assert task_id in _tasks(repo)


def test_evidence_moves_with_the_task(repo: ProjectFactory, run_cli: RunCli) -> None:
    task_id = _close_and_commit(repo, run_cli)
    store = repo.root / ".byteplan/verification.json"
    store.write_text(
        json.dumps({"schema_version": 1, "runs": {}, "tasks": {task_id: {"fingerprint": "x", "run": "r", "tests": {}}}})
    )
    assert run_cli("archive", "--older-than", "0", "--project", repo.root).code == EXIT_OK
    assert task_id not in json.loads(store.read_text())["tasks"]
    payload = archive.Store(repo.root / ".byteplan").get(task_id)
    assert payload is not None
    assert payload["evidence"]["fingerprint"] == "x"


def test_scan_archives_automatically(repo: ProjectFactory, run_cli: RunCli) -> None:
    task_id = _close_and_commit(repo, run_cli)
    pyproject = repo.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + "\n[tool.byteplan.archive]\nafter_days = 0\n")
    result = run_cli("scan", "--project", repo.root)
    assert result.code == EXIT_OK
    assert f"archived 1 long-closed task(s): {task_id}" in result.out
    assert task_id not in _tasks(repo)
    # A dry run never archives.
    assert "archived" not in run_cli("scan", "--dry-run", "--project", repo.root).out


def test_auto_archive_can_be_turned_off(repo: ProjectFactory, run_cli: RunCli) -> None:
    task_id = _close_and_commit(repo, run_cli)
    pyproject = repo.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + "\n[tool.byteplan.archive]\nafter_days = 0\nauto = false\n")
    assert run_cli("scan", "--project", repo.root).code == EXIT_OK
    assert task_id in _tasks(repo)


def test_another_clone_reconciles_from_git_history(repo: ProjectFactory, run_cli: RunCli, tmp_path: Path) -> None:
    task_id = _close_and_commit(repo, run_cli)
    assert run_cli("archive", "--older-than", "0", "--project", repo.root).code == EXIT_OK
    git(repo.root.parent, "add", "-A")
    git(repo.root.parent, "commit", "-qm", "archive")

    clone = tmp_path / "clone"
    git(tmp_path, "clone", "-q", str(repo.root.parent), str(clone))
    other = clone / "proj"
    assert not (other / ".byteplan/archive.sqlite").exists()
    # `show` reconciles lazily.
    shown = run_cli("show", task_id, "--format", "json", "--project", other)
    assert shown.code == EXIT_OK
    assert json.loads(shown.out)["title"] == "second task"
    assert (other / ".byteplan/archive.sqlite").exists()

    fresh = tmp_path / "fresh"
    git(tmp_path, "clone", "-q", str(repo.root.parent), str(fresh))
    result = run_cli("archive", "--reconcile", "--project", fresh / "proj")
    assert result.code == EXIT_OK
    assert "recovered 1 from Git history" in result.out
    again = run_cli("archive", "--reconcile", "--format", "json", "--project", fresh / "proj")
    assert json.loads(again.out) == {"recovered": [], "missing": [], "present": 1}


def test_reconcile_reports_records_missing_from_history(repo: ProjectFactory, run_cli: RunCli) -> None:
    index = repo.root / ".byteplan/archive.json"
    entry = {
        "archived_at": "x",
        "closed_at": "x",
        "kind": "TODO",
        "sha256": "0" * 64,
        "status": "resolved",
        "title": "t",
    }
    index.write_text(json.dumps({"schema_version": 1, "tasks": {"beef": entry}}))
    result = run_cli("archive", "--reconcile", "--project", repo.root)
    assert result.code == EXIT_FINDINGS
    assert "not in this clone's history (fetch, then retry): beef" in result.err
    shown = run_cli("show", "beef", "--project", repo.root)
    assert shown.code != EXIT_OK
    assert "isn't in this clone's Git history" in shown.err


def test_index_merge_is_a_union_by_id(tmp_path: Path) -> None:
    def index(**tasks: str) -> str:
        return archive.Index({t: {"sha256": sha, "title": t} for t, sha in tasks.items()}).dumps()

    base, ours, theirs = (tmp_path / name for name in ("base", "ours", "theirs"))
    base.write_text(index(aaaa="1"))
    ours.write_text(index(aaaa="1", bbbb="2"))
    theirs.write_text(index(aaaa="1", cccc="3"))
    assert archive_driver_main(str(base), str(ours), str(theirs), None) == 0
    assert sorted(archive.Index.loads(ours.read_text()).tasks) == ["aaaa", "bbbb", "cccc"]
    assert archive.merge("", "", "") == archive.Index().dumps()


def test_install_merge_driver_covers_the_index(repo: ProjectFactory, run_cli: RunCli) -> None:
    assert run_cli("git", "install-merge-driver", "--project", repo.root).code == EXIT_OK
    assert "archive.json merge=byteplan-archive" in (repo.root / ".byteplan/.gitattributes").read_text()
    driver = git(repo.root, "config", "--local", "--get", "merge.byteplan-archive.driver").stdout
    assert "merge-archive %O %A %B %P" in driver


def test_branches_archiving_different_tasks_merge(repo: ProjectFactory, run_cli: RunCli) -> None:
    top = repo.root.parent
    first = _id_of(repo, "first task")
    second = _id_of(repo, "second task")
    assert run_cli("git", "install-merge-driver", "--project", repo.root).code == EXIT_OK
    git(top, "add", "-A")
    git(top, "commit", "-qm", "drivers")
    for task_id in (first, second):
        assert run_cli("resolve", task_id, "--sync-source", "--project", repo.root).code == EXIT_OK
    assert run_cli("scan", "--project", repo.root).code == EXIT_OK
    git(top, "add", "-A")
    git(top, "commit", "-qm", "close both")

    git(top, "checkout", "-q", "-b", "other")
    assert run_cli("archive", "--older-than", "0", "--project", repo.root).code == EXIT_OK
    git(top, "add", "-A")
    git(top, "commit", "-qm", "archive on other")
    git(top, "checkout", "-q", "main")
    result = git(top, "merge", "-q", "--no-edit", "other", check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert _tasks(repo) == {}
    assert sorted(json.loads((repo.root / ".byteplan/archive.json").read_text())["tasks"]) == sorted([first, second])


def test_negative_after_days_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="after_days must not be negative"):
        parse_config(tmp_path, {"archive": {"after_days": -1}})


def test_an_archived_id_back_in_source_says_so(repo: ProjectFactory, run_cli: RunCli) -> None:
    task_id = _close_and_commit(repo, run_cli)
    assert run_cli("archive", "--older-than", "0", "--project", repo.root).code == EXIT_OK
    repo.write("src/c.py", f"# FIXME[{task_id}]: back again\n")
    result = run_cli("check", "--project", repo.root)
    assert f"ID {task_id} is in source but archived (resolved)" in result.err
    assert f"byteplan archive --restore {task_id}" in result.err

    restored = run_cli("archive", "--restore", task_id.upper(), "--project", repo.root)
    assert restored.code == EXIT_OK
    assert _tasks(repo)[task_id]["status"] == "resolved"
    assert task_id not in json.loads((repo.root / ".byteplan/archive.json").read_text())["tasks"]
    assert "STALE_ANNOTATION" in run_cli("check", "--project", repo.root).err
    assert run_cli("archive", "--restore", task_id, "--project", repo.root).code != EXIT_OK
