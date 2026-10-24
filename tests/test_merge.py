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

from byteplan._todo import verifies
from byteplan.merge import merge_registries
from byteplan.registry import SCHEMA_VERSION

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


@pytest.mark.parametrize("version", [SCHEMA_VERSION + 1, 0, "2", None])
def test_unsupported_schema_is_a_conflict(version: object) -> None:
    other = {**BASE, "schema_version": version}
    result = merge_registries(BASE, BASE, other)
    assert result.data is None
    assert "unsupported schema_version" in result.conflicts[0]


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


# Phase 4d: unknown top-level keys ----------------------------------------------------------------


def with_extra(base: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {**copy.deepcopy(base), **extra}


def test_top_level_keys_added_on_one_side_are_kept() -> None:
    result = merge_registries(BASE, with_extra(BASE, release={"version": "1.0"}), BASE)
    assert result.data is not None
    assert result.data["release"] == {"version": "1.0"}


def test_top_level_objects_merge_key_by_key() -> None:
    base = with_extra(BASE, settings={"a": 1, "b": 1, "gone": 1})
    ours = with_extra(BASE, settings={"a": 2, "b": 1, "new": "ours"})
    theirs = with_extra(BASE, settings={"a": 1, "b": 3, "gone": 1, "also": "theirs"})
    result = merge_registries(base, ours, theirs)
    assert result.data is not None
    assert result.data["settings"] == {"a": 2, "b": 3, "new": "ours", "also": "theirs"}


def test_top_level_lists_appended_on_both_sides_combine() -> None:
    base = with_extra(BASE, releases=[{"v": "1.0"}])
    ours = with_extra(BASE, releases=[{"v": "1.0"}, {"v": "1.1"}])
    theirs = with_extra(BASE, releases=[{"v": "1.0"}, {"v": "2.0"}, {"v": "1.1"}])
    result = merge_registries(base, ours, theirs)
    assert result.data is not None
    assert result.data["releases"] == [{"v": "1.0"}, {"v": "1.1"}, {"v": "2.0"}]
    # Added on both sides from nothing: also a combination.
    both = merge_registries(BASE, with_extra(BASE, log=["a"]), with_extra(BASE, log=["b"]))
    assert both.data is not None
    assert both.data["log"] == ["a", "b"]


@pytest.mark.parametrize(
    ("base", "ours", "theirs", "conflict"),
    [
        ({"mode": "x"}, {"mode": "y"}, {"mode": "z"}, "mode changed on both sides"),
        ({"cfg": {"k": 1}}, {"cfg": {"k": 2}}, {"cfg": {"k": 3}}, "cfg.k changed on both sides"),
        ({"log": ["a", "b"]}, {"log": ["a"]}, {"log": ["a", "b", "c"]}, "log changed on both sides"),
        ({"gone": 1}, {}, {"gone": 2}, "gone changed on both sides"),
    ],
)
def test_top_level_conflicts(base: dict[str, Any], ours: dict[str, Any], theirs: dict[str, Any], conflict: str) -> None:
    result = merge_registries(with_extra(BASE, **base), with_extra(BASE, **ours), with_extra(BASE, **theirs))
    assert result.data is None
    assert any(conflict in c for c in result.conflicts)


def test_top_level_key_deleted_on_one_side_stays_deleted() -> None:
    result = merge_registries(with_extra(BASE, old=1), BASE, with_extra(BASE, old=1))
    assert result.data is not None
    assert "old" not in result.data


def test_driver_keeps_top_level_keys_end_to_end(repo: ProjectFactory, run_cli: RunCli) -> None:
    root = repo.root
    assert run_cli("git", "install-merge-driver", "--project", root).code == 0
    git(root, "add", "-A")
    git(root, "commit", "-qm", "driver")
    path = root / ".byteplan/tasks.json"

    def commit_extra(branch: str, key: str, value: Any) -> None:
        git(root, "switch", "-q", *(["-c"] if branch != "main" else []), branch)
        data = json.loads(path.read_text())
        data[key] = value
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
        git(root, "commit", "-qam", key)

    commit_extra("feature", "release", {"version": "1.0"})
    commit_extra("main", "releases", [{"v": "0.9"}])
    merged = git(root, "merge", "-q", "--no-edit", "feature", check=False)
    assert merged.returncode == 0, merged.stdout + merged.stderr
    data = json.loads(path.read_text())
    assert data["release"] == {"version": "1.0"}
    assert data["releases"] == [{"v": "0.9"}]


# Booleans are not numbers ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("base", "ours", "theirs"),
    [(True, False, 1), (1, 2, True), (0, 5, False), (False, True, 0)],
)
def test_true_and_1_are_different_values(base: Any, ours: Any, theirs: Any) -> None:
    """Python says True == 1; JSON doesn't. Both sides changed the value, so it's a conflict,
    not a silent keep-ours (top-level extras and task extension fields alike)."""
    top = merge_registries(with_extra(BASE, flag=base), with_extra(BASE, flag=ours), with_extra(BASE, flag=theirs))
    assert top.data is None
    assert any("flag changed on both sides" in c for c in top.conflicts)
    in_task = merge_registries(
        changed(BASE, "aaaa", x=base), changed(BASE, "aaaa", x=ours), changed(BASE, "aaaa", x=theirs)
    )
    assert in_task.data is None
    assert any("x changed on both sides" in c for c in in_task.conflicts)


def test_bool_change_on_one_side_still_merges() -> None:
    result = merge_registries(with_extra(BASE, flag=1), with_extra(BASE, flag=1), with_extra(BASE, flag=True))
    assert result.data is not None
    assert result.data["flag"] is True
    nested = merge_registries(
        with_extra(BASE, cfg={"on": 1}), with_extra(BASE, cfg={"on": 1, "x": 2}), with_extra(BASE, cfg={"on": True})
    )
    assert nested.data is not None
    assert nested.data["cfg"] == {"on": True, "x": 2}
    assert nested.data["cfg"]["on"] is True


@verifies("ee606e")
@pytest.mark.parametrize(
    ("base", "ours", "theirs"),
    [
        pytest.param(1, 2, 2, id="both branches migrated after forking"),
        pytest.param(1, 1, 2, id="the other side migrated"),
        pytest.param(1, 2, 1, id="this side migrated"),
    ],
)
def test_merges_across_the_schema_migration(base: int, ours: int, theirs: int) -> None:
    def registry(version: int, status: str) -> dict[str, Any]:
        task = {"id": "abcd", "kind": "TODO", "title": "t", "status": status, "notes": "", "history": []}
        return {"schema_version": version, "reserved_ids": ["abcd"], "tasks": {"abcd": task}}

    # Our side's status change must survive; a conflict forces taking one side and losing it.
    result = merge_registries(registry(base, "open"), registry(ours, "in_progress"), registry(theirs, "open"))
    assert result.conflicts == []
    assert result.data is not None
    assert result.data["schema_version"] == 2
    assert result.data["tasks"]["abcd"]["status"] == "in_progress"
