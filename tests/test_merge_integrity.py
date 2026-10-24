# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Track A4: valid merge work survives; ambiguous records remain explicit conflicts."""

from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING, Any

import pytest

from byteplan import verification
from byteplan._todo import verifies
from byteplan.api import Project
from byteplan.gitio import merge_driver
from byteplan.merge import merge_registries
from byteplan.models import Status
from byteplan.registry import task_to_dict
from tests.gitutil import frozen, git
from tests.test_merge import changed, registry, task

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import ProjectFactory, RunCli


@verifies("edc2", "237cb5")
@pytest.mark.parametrize("schema", [1, 2])
@pytest.mark.parametrize("has_links", [False, True])
def test_merge_preserves_test_container_extensions(schema: int, *, has_links: bool) -> None:
    links = ["tests/test_a.py::test_a"] if has_links else []
    base = registry(task("aaaa", tests={"managed": links, "discovered": [], "x-provider": {"key": "keep"}}))
    base["schema_version"] = schema
    ours = changed(base, "aaaa", notes="left notes")
    theirs = changed(base, "aaaa", priority="high")
    result = merge_registries(base, ours, theirs)
    assert result.conflicts == []
    assert result.data is not None
    assert result.data["tasks"]["aaaa"]["tests"]["x-provider"] == {"key": "keep"}


@verifies("edc2", "237cb5")
@pytest.mark.parametrize("field", ["tests", "source", "stub"])
def test_merge_keeps_independent_nested_extensions(field: str) -> None:
    values: dict[str, Any] = {
        "tests": {"managed": [], "discovered": []},
        "source": {"path": "a.py", "line": 1, "symbol": None},
        "stub": {"symbol": "a", "implemented": False},
    }
    base = registry(task("aaaa", **{field: {**values[field], "x-data": {"keep": True}}}))
    ours = copy.deepcopy(base)
    theirs = copy.deepcopy(base)
    ours["tasks"]["aaaa"][field]["x-data"]["left"] = [1]
    theirs["tasks"]["aaaa"][field]["x-data"]["right"] = [2]
    if field == "source":
        ours["tasks"]["aaaa"][field]["line"] = 2
        theirs["tasks"]["aaaa"][field]["line"] = 3
    result = merge_registries(base, ours, theirs)
    assert result.conflicts == []
    assert result.data is not None
    assert result.data["tasks"]["aaaa"][field]["x-data"] == {"keep": True, "left": [1], "right": [2]}


@verifies("edc2", "237cb5")
@pytest.mark.parametrize("field", ["tests", "source", "stub"])
def test_merge_refuses_competing_nested_extension_values(field: str) -> None:
    values: dict[str, Any] = {
        "tests": {"managed": [], "discovered": []},
        "source": {"path": "a.py", "line": 1, "symbol": None},
        "stub": {"symbol": "a", "implemented": False},
    }
    base = registry(task("aaaa", **{field: {**values[field], "x-provider": "base"}}))
    ours = changed(base, "aaaa", **{field: {**values[field], "x-provider": "left"}})
    theirs = changed(base, "aaaa", **{field: {**values[field], "x-provider": "right"}})
    result = merge_registries(base, ours, theirs)
    assert result.data is None
    assert any(f"{field}.x-provider" in problem for problem in result.conflicts)


@verifies("edc2", "237cb5")
@pytest.mark.parametrize("field", ["tests", "source", "stub"])
def test_merge_respects_nested_extension_deletion(field: str) -> None:
    values: dict[str, Any] = {
        "tests": {"managed": [], "discovered": []},
        "source": {"path": "a.py", "line": 1, "symbol": None},
        "stub": {"symbol": "a", "implemented": False},
    }
    base = registry(task("aaaa", **{field: {**values[field], "x-provider": "remove"}}))
    ours = changed(base, "aaaa", **{field: values[field]})
    result = merge_registries(base, ours, base)
    assert result.conflicts == []
    assert result.data is not None
    assert "x-provider" not in result.data["tasks"]["aaaa"].get(field, {})


@verifies("edc2", "237cb5")
@pytest.mark.parametrize("driver", [False, True])
@pytest.mark.parametrize("competing_states", [False, True])
@pytest.mark.parametrize("autocrlf", [False, True])
def test_real_git_histories_and_lifecycle_states(
    repo: ProjectFactory, run_cli: RunCli, *, driver: bool, competing_states: bool, autocrlf: bool
) -> None:
    git(repo.root, "config", "core.autocrlf", str(autocrlf).lower())
    if driver:
        assert run_cli("git", "install-merge-driver", "--project", repo.root).code == 0
        git(repo.root, "add", "-A")
        git(repo.root, "commit", "-qm", "driver")
    p = Project.open(repo.root)
    task_id = next(iter(p.load_registry().tasks))
    original = p.get_task(task_id)
    base = git(repo.root, "rev-parse", "HEAD").stdout.strip()
    histories = []
    for branch in ("left", "right"):
        git(repo.root, "switch", "-q", "-c", branch, base)
        if branch == "left":
            p.set_status(task_id, Status.BLOCKED if competing_states else Status.IN_PROGRESS)
        elif competing_states:
            p.set_status(task_id, Status.RESOLVED)
        else:
            p.edit_task(task_id, priority="high")
        histories.extend(p.get_task(task_id).history[len(original.history) :])
        git(repo.root, "add", "-A")
        git(repo.root, "commit", "-qm", branch)
    result = git(repo.root, "merge", "--no-edit", "left", check=False)
    if competing_states:
        assert result.returncode != 0
    elif driver:
        assert result.returncode == 0, result.stdout + result.stderr
    if result.returncode:
        before = frozen(repo)
        assert run_cli("check", "--project", repo.root).code == 2
        assert frozen(repo) == before
        for branch in ("left", "right"):
            recorded = json.loads(git(repo.root, "show", f"{branch}:proj/.byteplan/tasks.json").stdout)
            assert recorded["tasks"][task_id]["history"][: len(original.history)] == task_to_dict(original)["history"]
    else:
        merged = p.get_task(task_id)
        assert merged.status is Status.IN_PROGRESS
        assert merged.priority == "high"
        assert merged.history[: len(original.history)] == original.history
        assert all(event in merged.history for event in histories)
        p.scan(dry_run=False)
        assert p.scan(dry_run=False).written == ()


@verifies("edc2", "279e27", "492312")
@pytest.mark.parametrize("driver", [False, True])
@pytest.mark.parametrize("same_task", [False, True])
def test_real_git_verification_evidence_merge(
    repo: ProjectFactory, run_cli: RunCli, monkeypatch: pytest.MonkeyPatch, *, driver: bool, same_task: bool
) -> None:
    if driver:
        assert run_cli("git", "install-merge-driver", "--project", repo.root).code == 0
    p = Project.open(repo.root)
    ids = list(p.load_registry().tasks)
    for number, task_id in enumerate(ids):
        node = f"tests/test_proof.py::test_{number}"
        p.link_tests(task_id, [node])
    repo.write("tests/test_proof.py", "def test_0():\n    return 1\ndef test_1():\n    return 1\n")
    repo.write(verification.STORE, '{"schema_version":1,"tasks":{},"runs":{}}\n')
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "verification base")
    base = git(repo.root, "rev-parse", "HEAD").stdout.strip()
    records = {}
    for number, branch in enumerate(("left", "right")):
        git(repo.root, "switch", "-q", "-c", branch, base)
        selected = ids[0] if same_task else ids[number]
        outcome = "passed" if number == 0 else "failed"

        def execute(
            _root: Any, nodes: Any, *_args: Any, result: str = outcome, code: int = number
        ) -> verification.RunOutput:
            return verification.RunOutput({node: verification.TestResult(result) for node in nodes}, code)

        monkeypatch.setattr(verification, "run_tests", execute)
        p.verify([selected])
        records[branch] = json.loads((repo.root / verification.STORE).read_bytes())
        git(repo.root, "add", "-A")
        git(repo.root, "commit", "-qm", branch)
    result = git(repo.root, "merge", "--no-edit", "left", check=False)
    if same_task:
        assert result.returncode != 0
    if result.returncode:
        before = frozen(repo)
        checked = run_cli("check", "--project", repo.root)
        assert checked.code == 2
        assert "verification.json" in checked.err
        assert frozen(repo) == before
        for branch in ("left", "right"):
            assert json.loads(git(repo.root, "show", f"{branch}:proj/{verification.STORE}").stdout) == records[branch]
    else:
        merged = verification.Evidence.load(repo.root)
        for data in records.values():
            for task_id, entry in data["tasks"].items():
                assert merged.tasks[task_id] == entry
                assert merged.runs[entry["run"]] == data["runs"][entry["run"]]


@verifies("edc2", "237cb5")
@pytest.mark.parametrize("field", ["tests", "source", "stub"])
@pytest.mark.parametrize("null", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_removed_container_cannot_discard_competing_metadata(field: str, *, null: bool, reverse: bool) -> None:
    values: dict[str, Any] = {
        "tests": {"managed": [], "discovered": []},
        "source": {"path": "a.py", "line": 1},
        "stub": {"symbol": "a", "implemented": False},
    }
    base = registry(task("aaaa", **{field: {**values[field], "x-provider": "base"}}))
    removed = copy.deepcopy(base)
    if null:
        removed["tasks"]["aaaa"][field] = None
    else:
        del removed["tasks"]["aaaa"][field]
    edited = changed(base, "aaaa", **{field: {**values[field], "x-provider": "updated"}})
    ours, theirs = (edited, removed) if reverse else (removed, edited)
    result = merge_registries(base, ours, theirs)
    assert result.data is None
    assert any(field in conflict for conflict in result.conflicts)


@verifies("edc2", "237cb5")
@pytest.mark.parametrize("schema", [1, 2])
def test_merge_driver_serialization_preserves_nested_metadata(tmp_path: Path, schema: int) -> None:
    original = task(
        "aaaa",
        tests={"x-tests": {"keep": True}},
        source={"path": "a.py", "line": 1, "x-source": {"keep": True}},
        stub={"symbol": "a", "implemented": False, "x-stub": {"keep": True}},
    )
    base = registry(original)
    base["schema_version"] = schema
    ours, theirs = changed(base, "aaaa", notes="left"), changed(base, "aaaa", priority="high")
    paths = [tmp_path / name for name in ("base", "ours", "theirs")]
    for path, data in zip(paths, (base, ours, theirs), strict=True):
        path.write_text(json.dumps(data), encoding="utf-8")
    outcome = merge_driver(paths[0], paths[1], paths[2])
    assert outcome.code == 0
    data = json.loads(paths[1].read_bytes())
    assert data["schema_version"] == schema
    for field in ("tests", "source", "stub"):
        assert data["tasks"]["aaaa"][field][f"x-{field}"] == {"keep": True}
