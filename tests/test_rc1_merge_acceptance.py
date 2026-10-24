# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Mixed-schema migration through real merge drivers and ordinary divergent Git."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from byteplan import verification
from byteplan._todo import verifies
from byteplan.api import Project
from byteplan.gitio import merge_driver
from byteplan.models import Status
from byteplan.registry import dumps, loads, task_to_dict
from tests.gitutil import frozen, git
from tests.test_compatibility import legacy_registry

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory, RunCli


def _commit(project: ProjectFactory, message: str) -> str:
    git(project.root, "add", "-A")
    git(project.root, "commit", "-qm", message)
    return git(project.root, "rev-parse", "HEAD").stdout.strip()


@verifies("edc2", "ee606e", "8756")
@pytest.mark.parametrize("driver", [False, True])
@pytest.mark.parametrize("migrated_side", ["left", "right"])
@pytest.mark.parametrize("both_migrate", [False, True])
def test_divergent_git_merge_across_schema_migration(
    project: ProjectFactory,
    run_cli: RunCli,
    monkeypatch: pytest.MonkeyPatch,
    *,
    driver: bool,
    migrated_side: str,
    both_migrate: bool,
) -> None:
    git(project.root.parent, "init", "-q", "-b", "main")
    git(project.root, "config", "user.email", "test@example.com")
    git(project.root, "config", "user.name", "Test")
    git(project.root, "config", "commit.gpgsign", "false")
    legacy_registry(project)
    p = Project.open(project.root)
    p.link_tests("abcd", ["tests/test_proof.py::test_proof"])
    project.write("tests/test_proof.py", "def test_proof():\n    assert True\n")

    def execute(_root: Any, nodes: Any, *_args: Any) -> verification.RunOutput:
        return verification.RunOutput({node: verification.TestResult("passed") for node in nodes}, 0)

    monkeypatch.setattr(verification, "run_tests", execute)
    p.verify(["abcd"])
    base_evidence = json.loads((project.root / verification.STORE).read_bytes())
    if driver:
        assert run_cli("git", "install-merge-driver", "--project", project.root).code == 0
    base = _commit(project, "legacy base with evidence")
    initial = task_to_dict(p.get_task("abcd"))
    records = {}
    reserved = set()
    new_id = ""
    for branch in ("left", "right"):
        git(project.root, "switch", "-q", "-c", branch, base)
        if branch == migrated_side or both_migrate:
            p.migrate()
        if branch == migrated_side:
            project.write("new.py", "# TODO: six-character task\n")
            additions = p.scan(dry_run=False).summary.added
            assert len(additions) == 1
            new_id = additions[0]
            assert len(new_id) == 6
        else:
            project.write("legacy.py", "# TODO[ef01]: independent legacy task\n")
            p.import_task("ef01")
            p.scan(dry_run=False)
        if branch == "left":
            p.set_status("abcd", Status.IN_PROGRESS)
        else:
            p.edit_task("abcd", priority="high")
        stored = p.load_registry()
        records[branch] = {key: task_to_dict(value) for key, value in stored.tasks.items()}
        reserved |= stored.reserved_ids
        _commit(project, branch)
    outcome = git(project.root, "merge", "--no-edit", "left", check=False)
    if driver:
        assert outcome.returncode == 0, outcome.stdout + outcome.stderr
    if outcome.returncode:
        # Plain Git may explicitly conflict. Neither original branch's records are lost.
        before = frozen(project)
        checked = run_cli("check", "--project", project.root)
        assert checked.code == 2, checked.out + checked.err
        assert frozen(project) == before
        for branch in ("left", "right"):
            data = json.loads(git(project.root, "show", f"{branch}:proj/.byteplan/tasks.json").stdout)
            assert data["tasks"] == records[branch]
        assert json.loads((project.root / verification.STORE).read_bytes()) == base_evidence
        return
    merged = p.load_registry()
    assert merged.schema_version == 2
    assert set(merged.tasks) == {"abcd", "ef01", new_id}
    assert merged.reserved_ids == reserved
    shared = task_to_dict(merged.tasks["abcd"])
    assert shared["status"] == "in_progress"
    assert shared["priority"] == "high"
    assert shared["history"][: len(initial["history"])] == initial["history"]
    for branch in ("left", "right"):
        for key, record in records[branch].items():
            if key == "abcd":
                assert all(event in shared["history"] for event in record["history"])
            else:
                assert task_to_dict(merged.tasks[key]) == record
    assert json.loads((project.root / verification.STORE).read_bytes()) == base_evidence
    assert (project.root / "a.py").read_bytes().replace(b"\r\n", b"\n") == b"# TODO[abcd]: legacy\n"
    assert run_cli("check", "--project", project.root).code == 0
    p.scan(dry_run=False)
    assert p.scan(dry_run=False).written == ()
    assert json.loads((project.root / verification.STORE).read_bytes()) == base_evidence


@verifies("edc2", "ee606e")
@pytest.mark.parametrize("damage", ["future", "malformed", "markers", "duplicate", "expanded_v1"])
@pytest.mark.parametrize("damaged_side", ["base", "ours", "theirs"])
def test_driver_rejects_invalid_migration_inputs(
    project: ProjectFactory, run_cli: RunCli, damage: str, damaged_side: str
) -> None:
    legacy_registry(project)
    canonical = dumps(loads((project.root / ".byteplan/tasks.json").read_text()))
    data = json.loads(canonical)
    if damage == "future":
        data["schema_version"] = 999
        invalid = json.dumps(data)
    elif damage == "malformed":
        invalid = '{"schema_version":'
    elif damage == "markers":
        invalid = "<<<<<<< ours\n" + canonical + "=======\n" + canonical + ">>>>>>> theirs\n"
    elif damage == "duplicate":
        invalid = canonical.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 2')
    else:
        data["reserved_ids"].append("abcdef")
        invalid = json.dumps(data)
    paths = {
        side: project.write(side + ".json", invalid if side == damaged_side else canonical)
        for side in ("base", "ours", "theirs")
    }
    originals = {side: path.read_bytes() for side, path in paths.items()}
    outcome = merge_driver(paths["base"], paths["ours"], paths["theirs"])
    assert outcome.code == 1
    assert any("cannot merge by task ID" in message for message in outcome.messages)
    assert paths["base"].read_bytes() == originals["base"]
    assert paths["theirs"].read_bytes() == originals["theirs"]
    # The driver's deliberate text-conflict fallback may write ours; it never reports success.
    assert any("manual merge" in message for message in outcome.messages)
    project.write(".byteplan/tasks.json", invalid)
    before = project.snapshot()
    result = run_cli("check", "--project", project.root)
    assert result.code == 2
    assert result.err
    assert project.snapshot() == before


@verifies("edc2")
def test_valid_json_partial_resolution_reports_discarded_task(repo: ProjectFactory, run_cli: RunCli) -> None:
    path = repo.root / ".byteplan/tasks.json"
    data = json.loads(path.read_bytes())
    discarded = sorted(data["tasks"])[0]
    original = data["tasks"].pop(discarded)
    repo.write(".byteplan/tasks.json", json.dumps(data))
    # Model a manual resolution that selected valid JSON but discarded a source task.
    # Working-tree policy reports it; staged/commit consistency makes it a failing check.
    before = frozen(repo)
    ordinary = run_cli("check", "--project", repo.root)
    assert "UNREGISTERED_ID" in ordinary.err
    assert discarded in ordinary.err
    assert "restore the registry entry from version control" in ordinary.err
    assert frozen(repo) == before
    git(repo.root, "add", "-A")
    before = frozen(repo)
    staged = run_cli("check", "--staged", "--project", repo.root)
    assert staged.code == 1
    assert "UNREGISTERED_ID" in staged.err
    assert frozen(repo) == before
    git(repo.root, "commit", "-qm", "partially resolved registry")
    before = frozen(repo)
    committed = run_cli("check", "--commit", "HEAD", "--project", repo.root)
    assert committed.code == 1
    assert "UNREGISTERED_ID" in committed.err
    assert frozen(repo) == before
    # The original complete task remains recoverable in Git, including history.
    previous = json.loads(git(repo.root, "show", "HEAD^:proj/.byteplan/tasks.json").stdout)
    assert previous["tasks"][discarded] == original
