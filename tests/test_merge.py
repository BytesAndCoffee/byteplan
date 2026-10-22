# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Registry merge by task ID, and the Git merge driver end to end."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from byteplan.merge import merge_registries

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory, RunCli


def task(task_id: str, **fields: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": task_id,
        "kind": "TODO",
        "title": f"task {task_id}",
        "status": "open",
        "priority": "normal",
        "labels": [],
        "notes": "",
        "presence": "present",
        "source": {"path": "a.py", "line": 1, "symbol": None},
        "first_seen": "2026-10-21T00:00:01Z",
        "last_seen": "2026-10-21T00:00:01Z",
        "history": [{"event": "created", "at": "2026-10-21T00:00:01Z", "old": None, "new": None}],
    }
    data.update(fields)
    return data


def registry(*tasks: dict[str, Any], reserved: tuple[str, ...] = ()) -> dict[str, Any]:
    ids = {t["id"] for t in tasks} | set(reserved)
    return {"schema_version": 1, "reserved_ids": sorted(ids), "tasks": {t["id"]: t for t in tasks}}


BASE = registry(task("aaaa"))


def changed(base: dict[str, Any], task_id: str, **fields: Any) -> dict[str, Any]:
    result = copy.deepcopy(base)
    result["tasks"][task_id].update(fields)
    return result


def test_tasks_added_on_both_sides_are_unioned() -> None:
    ours = registry(task("aaaa"), task("bbbb"))
    theirs = registry(task("aaaa"), task("cccc"), reserved=("dddd",))
    merged = merge_registries(BASE, ours, theirs)
    assert merged.conflicts == []
    assert merged.data is not None
    assert sorted(merged.data["tasks"]) == ["aaaa", "bbbb", "cccc"]
    assert merged.data["reserved_ids"] == ["aaaa", "bbbb", "cccc", "dddd"]


def test_identical_addition_on_both_sides_is_fine() -> None:
    both = registry(task("aaaa"), task("bbbb"))
    assert merge_registries(BASE, both, both).conflicts == []


def test_id_collision_is_a_conflict() -> None:
    ours = registry(task("aaaa"), task("bbbb", title="ours"))
    theirs = registry(task("aaaa"), task("bbbb", title="theirs"))
    merged = merge_registries(BASE, ours, theirs)
    assert merged.data is None
    assert any("ID collision" in c for c in merged.conflicts)


def test_managed_fields_merge_per_field() -> None:
    ours = changed(BASE, "aaaa", status="in_progress")
    theirs = changed(BASE, "aaaa", priority="high", assignee="sam")
    merged = merge_registries(BASE, ours, theirs)
    assert merged.data is not None
    result = merged.data["tasks"]["aaaa"]
    assert (result["status"], result["priority"], result["assignee"]) == ("in_progress", "high", "sam")


def test_same_managed_field_changed_differently_is_a_conflict() -> None:
    merged = merge_registries(BASE, changed(BASE, "aaaa", status="blocked"), changed(BASE, "aaaa", status="resolved"))
    assert merged.data is None
    assert merged.conflicts == ["task aaaa: status changed on both sides ('blocked' vs 'resolved')"]


def test_same_change_on_both_sides_is_not_a_conflict() -> None:
    side = changed(BASE, "aaaa", status="resolved")
    assert merge_registries(BASE, side, side).conflicts == []


def test_history_is_append_only_and_ordered() -> None:
    created = BASE["tasks"]["aaaa"]["history"]
    ours_event = {"event": "status_changed", "at": "2026-10-22T00:00:05Z", "old": "open", "new": "in_progress"}
    their_event = {"event": "edited", "at": "2026-10-22T00:00:02Z", "old": {}, "new": {}}
    merged = merge_registries(
        BASE,
        changed(BASE, "aaaa", history=[*created, ours_event]),
        changed(BASE, "aaaa", history=[*created, their_event]),
    )
    assert merged.data is not None
    assert merged.data["tasks"]["aaaa"]["history"] == [*created, their_event, ours_event]


def test_rewritten_history_is_a_conflict() -> None:
    merged = merge_registries(BASE, changed(BASE, "aaaa", history=[]), BASE)
    assert merged.data is None


def test_labels_merge_as_a_set() -> None:
    base = changed(BASE, "aaaa", labels=["keep", "drop"])
    ours = changed(base, "aaaa", labels=["keep", "ours"])
    theirs = changed(base, "aaaa", labels=["keep", "drop", "theirs"])
    merged = merge_registries(base, ours, theirs)
    assert merged.data is not None
    assert merged.data["tasks"]["aaaa"]["labels"] == ["keep", "ours", "theirs"]


def test_discovered_fields_prefer_ours_and_ask_for_a_scan() -> None:
    ours = changed(BASE, "aaaa", source={"path": "a.py", "line": 9, "symbol": None}, last_seen="2026-10-22T00:00:09Z")
    theirs = changed(
        BASE, "aaaa", source={"path": "b.py", "line": 1, "symbol": None}, first_seen="2026-10-20T00:00:00Z"
    )
    merged = merge_registries(BASE, ours, theirs)
    assert merged.conflicts == []
    assert merged.rescan_needed == ["aaaa"]
    assert merged.data is not None
    result = merged.data["tasks"]["aaaa"]
    assert result["source"]["line"] == 9
    assert (result["first_seen"], result["last_seen"]) == ("2026-10-20T00:00:00Z", "2026-10-22T00:00:09Z")


def test_removal_rules() -> None:
    removed = registry(reserved=("aaaa",))
    assert merge_registries(BASE, removed, BASE).data == removed  # removed vs untouched
    merged = merge_registries(BASE, removed, changed(BASE, "aaaa", status="resolved"))
    assert merged.data is None  # removed vs changed


def test_schema_mismatch_is_a_conflict() -> None:
    newer = {**BASE, "schema_version": 2}
    assert merge_registries(BASE, BASE, newer).data is None


# Git end to end -----------------------------------------------------------------------------------


# Git runs BytePlan (merge driver) in subprocesses; keep their coverage data with ours.
COVERAGE_ENV = {**os.environ, "COVERAGE_FILE": str(Path(__file__).resolve().parents[1] / ".coverage")}


def git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=check, env=COVERAGE_ENV)


def tasks_of(root: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((root / ".byteplan/tasks.json").read_text())["tasks"]
    return data


@pytest.fixture
def repo(project: ProjectFactory, run_cli: RunCli) -> ProjectFactory:
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    root = project.root
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "test@example.com")
    git(root, "config", "user.name", "Test")
    git(root, "config", "commit.gpgsign", "false")
    project.init()
    project.write("src/base.py", "# TODO: shared task\n")
    assert run_cli("scan", "--project", root).code == 0
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    return project


def branch_with_task(repo: ProjectFactory, run_cli: RunCli, branch: str, path: str) -> None:
    git(repo.root, "switch", "-q", "-c", branch, "main")
    repo.write(path, f"# TODO: work on {branch}\n")
    assert run_cli("scan", "--project", repo.root).code == 0
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", branch)


def test_without_the_driver_parallel_tasks_conflict(repo: ProjectFactory, run_cli: RunCli) -> None:
    """Control: plain text merge of two branches that each added a task."""
    branch_with_task(repo, run_cli, "feature-a", "src/a.py")
    branch_with_task(repo, run_cli, "feature-b", "src/b.py")
    result = git(repo.root, "merge", "-q", "feature-a", check=False)
    assert result.returncode != 0
    assert "CONFLICT" in result.stdout + result.stderr


def test_driver_merges_parallel_tasks(repo: ProjectFactory, run_cli: RunCli) -> None:
    result = run_cli("git", "install-merge-driver", "--project", repo.root)
    assert result.code == 0, result.err
    assert "tasks.json merge=byteplan" in (repo.root / ".byteplan/.gitattributes").read_text()
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "install driver")
    branch_with_task(repo, run_cli, "feature-a", "src/a.py")
    branch_with_task(repo, run_cli, "feature-b", "src/b.py")

    merge = git(repo.root, "merge", "--no-edit", "feature-a", check=False)
    assert merge.returncode == 0, merge.stdout + merge.stderr
    titles = sorted(t["title"] for t in tasks_of(repo.root).values())
    assert titles == ["shared task", "work on feature-a", "work on feature-b"]
    check = run_cli("check", "--project", repo.root)
    assert check.code == 0, check.err
    assert run_cli("scan", "--project", repo.root).out.count("+0 added") == 1  # already reconciled


def test_driver_merges_independent_field_edits(repo: ProjectFactory, run_cli: RunCli) -> None:
    run_cli("git", "install-merge-driver", "--project", repo.root)
    (task_id,) = tasks_of(repo.root)
    git(repo.root, "switch", "-q", "-c", "side", "main")
    run_cli("status", task_id, "in_progress", "--project", repo.root)
    git(repo.root, "commit", "-qam", "start")
    git(repo.root, "switch", "-q", "main")
    run_cli("edit", task_id, "--priority", "high", "--project", repo.root)
    git(repo.root, "commit", "-qam", "prioritize")

    assert git(repo.root, "merge", "--no-edit", "side", check=False).returncode == 0
    merged = tasks_of(repo.root)[task_id]
    assert (merged["status"], merged["priority"]) == ("in_progress", "high")
    history = merged["history"]
    assert sorted(e["event"] for e in history) == ["created", "edited", "status_changed"]
    assert history[1:] == sorted(history[1:], key=lambda e: (e["at"], e["event"]))  # both sides, in order


def test_driver_leaves_real_conflicts_to_the_user(repo: ProjectFactory, run_cli: RunCli) -> None:
    run_cli("git", "install-merge-driver", "--project", repo.root)
    (task_id,) = tasks_of(repo.root)
    git(repo.root, "switch", "-q", "-c", "side", "main")
    run_cli("status", task_id, "blocked", "--project", repo.root)
    git(repo.root, "commit", "-qam", "block")
    git(repo.root, "switch", "-q", "main")
    run_cli("status", task_id, "dismissed", "--project", repo.root)
    git(repo.root, "commit", "-qam", "dismiss")

    merge = git(repo.root, "merge", "--no-edit", "side", check=False)
    assert merge.returncode != 0
    output = merge.stdout + merge.stderr
    assert "needs a manual merge" in output
    assert "status changed on both sides" in output
    assert "<<<<<<< ours" in (repo.root / ".byteplan/tasks.json").read_text()


def test_install_is_idempotent_and_uses_an_absolute_interpreter(repo: ProjectFactory, run_cli: RunCli) -> None:
    first = run_cli("git", "install-merge-driver", "--project", repo.root)
    second = run_cli("git", "install-merge-driver", "--project", repo.root)
    assert "already installed" in second.out
    assert first.out != second.out
    driver = git(repo.root, "config", "--get", "merge.byteplan.driver").stdout
    assert sys.executable in driver
    assert "-m byteplan merge-registry %O %A %B %P" in driver


def test_install_outside_git_fails_cleanly(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    result = run_cli("git", "install-merge-driver", "--project", project.root)
    assert result.code == 2
    assert "rev-parse" in result.err


# Codex review of #11: absent keys vs explicit nulls ----------------------------------------------


def test_deleted_extension_field_stays_deleted() -> None:
    base = changed(BASE, "aaaa", extension={"enabled": True})
    ours = copy.deepcopy(base)
    del ours["tasks"]["aaaa"]["extension"]
    theirs = changed(base, "aaaa", priority="high")
    merged = merge_registries(base, ours, theirs)
    assert merged.data is not None
    result = merged.data["tasks"]["aaaa"]
    assert "extension" not in result
    assert result["priority"] == "high"


def test_explicit_null_is_kept_and_distinct_from_absent() -> None:
    base = changed(BASE, "aaaa", extension={"enabled": True})
    ours = changed(base, "aaaa", extension=None)
    merged = merge_registries(base, ours, base)
    assert merged.data is not None
    assert "extension" in merged.data["tasks"]["aaaa"]
    assert merged.data["tasks"]["aaaa"]["extension"] is None


def test_deleted_on_one_side_changed_on_the_other_is_a_conflict() -> None:
    base = changed(BASE, "aaaa", extension={"enabled": True})
    ours = copy.deepcopy(base)
    del ours["tasks"]["aaaa"]["extension"]
    theirs = changed(base, "aaaa", extension={"enabled": False})
    merged = merge_registries(base, ours, theirs)
    assert merged.data is None
    assert merged.conflicts == ["task aaaa: extension changed on both sides (<absent> vs {'enabled': False})"]


def test_field_added_on_one_side_is_kept() -> None:
    merged = merge_registries(BASE, changed(BASE, "aaaa", extension={"new": 1}), BASE)
    assert merged.data is not None
    assert merged.data["tasks"]["aaaa"]["extension"] == {"new": 1}
