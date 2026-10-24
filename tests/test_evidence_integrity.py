# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Evidence provenance is preserved and incomplete records never establish verification."""

from __future__ import annotations

import copy
import json
from typing import TYPE_CHECKING, Any

import pytest

from byteplan import archive, verification
from byteplan._todo import verifies
from byteplan.api import Project
from byteplan.errors import ConfigError
from tests.gitutil import frozen, git
from tests.test_archive import _close_and_commit

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory, RunCli


def run_metadata(**values: Any) -> dict[str, Any]:
    return {
        "argv": ["pytest"],
        "python": "3.12",
        "at": "2026-10-23T00:00:00Z",
        "head": None,
        "dirty": False,
        "timed_out": False,
        **values,
    }


def linked(repo: ProjectFactory) -> tuple[Project, str, str]:
    p = Project.open(repo.root)
    task_id = next(iter(p.load_registry().tasks))
    node = "tests/test_proof.py::test_proof"
    repo.write("tests/test_proof.py", "def test_proof():\n    assert True\n")
    p.link_tests(task_id, [node])
    return p, task_id, node


def store(repo: ProjectFactory, p: Project, task_id: str, node: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "tasks": {
            task_id: {
                "fingerprint": verification.fingerprint(repo.root, verification.task_files(p.get_task(task_id))),
                "run": "proof",
                "tests": {node: {"outcome": "passed", "duration_ms": 1}},
            }
        },
        "runs": {"proof": run_metadata()},
    }


@verifies("edc2", "279e27")
@pytest.mark.parametrize(
    "missing", ["run-id", "run-record", "fingerprint", "argv", "python", "at", "head", "dirty", "timed_out"]
)
def test_incomplete_positive_evidence_is_rejected_without_writes(
    repo: ProjectFactory, run_cli: RunCli, missing: str
) -> None:
    p, task_id, node = linked(repo)
    data = store(repo, p, task_id, node)
    if missing == "run-id":
        del data["tasks"][task_id]["run"]
    elif missing == "run-record":
        data["runs"] = {}
    elif missing == "fingerprint":
        del data["tasks"][task_id]["fingerprint"]
    else:
        del data["runs"]["proof"][missing]
    # In-memory callers also cannot turn incomplete historical data into a verified claim.
    evidence = verification.Evidence(data["tasks"], data["runs"])
    ready = p.readiness(p.get_task(task_id), evidence)
    assert ready.state == "needs_review"
    assert ready.tests[node] == "stale"
    repo.write(verification.STORE, json.dumps(data))
    before = frozen(repo)
    result = run_cli("check", "--project", repo.root)
    assert result.code == 2
    assert "verification" in result.err or "provenance" in result.err
    assert frozen(repo) == before


@verifies("edc2", "279e27")
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("argv", "pytest"),
        ("argv", []),
        ("argv", [1]),
        ("python", 3),
        ("at", []),
        ("head", 42),
        ("dirty", "false"),
        ("dirty", 0),
        ("timed_out", 0),
    ],
)
def test_known_run_fields_reject_malformed_types(field: str, value: Any) -> None:
    data = {"schema_version": 1, "tasks": {}, "runs": {"proof": run_metadata(**{field: value})}}
    with pytest.raises(ConfigError, match="invalid provenance"):
        verification.Evidence.loads(json.dumps(data))


@verifies("edc2", "279e27")
def test_head_mode_also_requires_current_file_fingerprint(repo: ProjectFactory) -> None:
    p, task_id, node = linked(repo)
    data = store(repo, p, task_id, node)
    head = git(repo.root, "rev-parse", "HEAD").stdout.strip()
    data["runs"]["proof"]["head"] = head
    data["tasks"][task_id]["fingerprint"] = "different-content"
    evidence = verification.Evidence.loads(json.dumps(data))
    ready = verification.readiness(p.get_task(task_id), evidence, repo.root, stale_on="head", head=(head, False))
    assert ready.state == "needs_review"
    assert ready.tests[node] == "stale"


@verifies("edc2", "492312")
def test_verification_runs_do_not_alias_at_the_same_second(
    repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    p, task_id, node = linked(repo)
    p.clock = lambda: "2026-10-23T00:00:00Z"
    outputs = iter(["failed", "passed"])

    def execute(*_: Any, **__: Any) -> verification.RunOutput:
        return verification.RunOutput({node: verification.TestResult(next(outputs))}, 0)

    monkeypatch.setattr(verification, "run_tests", execute)
    p.verify([task_id])
    first = verification.Evidence.load(repo.root)
    first_id = first.tasks[task_id]["run"]
    # Another task's record must keep its original provenance after a subsequent run.
    other_id = next(t for t in p.load_registry().tasks if t != task_id)
    first.tasks[other_id] = copy.deepcopy(first.tasks[task_id])
    first.save(repo.root)
    p.verify([task_id])
    second = verification.Evidence.load(repo.root)
    assert second.tasks[task_id]["run"] != first_id
    assert second.tasks[other_id]["run"] == first_id
    assert second.runs[first_id] == first.runs[first_id]
    assert second.tasks[other_id]["tests"][node]["outcome"] == "failed"


@verifies("edc2", "6d434f")
def test_reverification_preserves_opaque_metadata_and_clears_old_failure(
    repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    p, task_id, node = linked(repo)
    data = store(repo, p, task_id, node)
    data["x-store"] = {"keep": [1, 2]}
    data["tasks"][task_id]["x-task"] = {"keep": True}
    data["tasks"][task_id]["tests"][node].update(
        {"outcome": "failed", "message": "old failure", "x-test": {"keep": True}}
    )
    repo.write(verification.STORE, json.dumps(data))
    monkeypatch.setattr(
        verification, "run_tests", lambda *_: verification.RunOutput({node: verification.TestResult("passed", 5)}, 0)
    )
    p.verify([task_id])
    after = json.loads((repo.root / verification.STORE).read_bytes())
    assert after["x-store"] == data["x-store"]
    assert after["tasks"][task_id]["x-task"] == data["tasks"][task_id]["x-task"]
    assert after["tasks"][task_id]["tests"][node] == {"outcome": "passed", "duration_ms": 5, "x-test": {"keep": True}}


@verifies("edc2", "492312", "6d434f")
def test_archive_restores_conflicting_runs_without_substitution(repo: ProjectFactory, run_cli: RunCli) -> None:
    task_id = _close_and_commit(repo, run_cli)
    p = Project.open(repo.root)
    old_run = run_metadata(head="old-head", dirty=True)
    entry = {
        "fingerprint": "old-files",
        "run": "same-id",
        "tests": {"tests/test_old.py::test_old": {"outcome": "passed"}},
    }
    repo.write(
        verification.STORE,
        json.dumps(
            {"schema_version": 1, "tasks": {task_id: entry}, "runs": {"same-id": old_run}, "x-store": {"keep": True}}
        ),
    )
    p.archive(older_than=0)
    assert verification.Evidence.load(repo.root).extra == {"x-store": {"keep": True}}
    other_id = next(iter(p.load_registry().tasks))
    live_run = run_metadata(head="new-head", dirty=False)
    live_entry = {**entry, "fingerprint": "new-files"}
    repo.write(
        verification.STORE,
        json.dumps(
            {
                "schema_version": 1,
                "tasks": {other_id: live_entry},
                "runs": {"same-id": live_run},
                "x-store": {"keep": True},
            }
        ),
    )
    p.restore_archived(task_id)
    after = verification.Evidence.load(repo.root)
    assert after.tasks[other_id] == live_entry
    assert after.runs["same-id"] == live_run
    restored_id = after.tasks[task_id]["run"]
    assert restored_id != "same-id"
    assert after.runs[restored_id] == old_run
    assert after.tasks[task_id] == {**entry, "run": restored_id}
    assert after.extra == {"x-store": {"keep": True}}
    assert p.readiness(p.get_task(task_id), after).state != "ready_for_review"


@verifies("edc2", "492312", "279e27")
@pytest.mark.parametrize("malformed", [[], "broken", {"run": []}])
def test_malformed_archived_evidence_is_actionable_and_atomic(
    repo: ProjectFactory, run_cli: RunCli, malformed: Any
) -> None:
    task_id = _close_and_commit(repo, run_cli)
    p = Project.open(repo.root)
    p.archive(older_than=0)
    local = archive.Store(repo.root / ".byteplan")
    payload = local.get(task_id)
    assert payload is not None
    payload["evidence"] = malformed
    payload["run"] = run_metadata()
    local.put([(task_id, payload, "2026-10-23T00:00:00Z")])
    before = frozen(repo)
    with pytest.raises(ConfigError, match="archived verification evidence"):
        p.restore_archived(task_id)
    task = p.archived_task(task_id)
    assert task is not None
    with pytest.raises(ConfigError, match="archived verification evidence"):
        p.readiness(task)
    assert frozen(repo) == before


@verifies("edc2", "279e27")
def test_completed_passes_survive_a_timed_out_multi_test_run(repo: ProjectFactory) -> None:
    p, task_id, node = linked(repo)
    data = store(repo, p, task_id, node)
    data["runs"]["proof"]["timed_out"] = True
    evidence = verification.Evidence.loads(json.dumps(data))
    assert p.readiness(p.get_task(task_id), evidence).state == "ready_for_review"


@verifies("edc2", "492312")
def test_restore_does_not_conflate_boolean_and_numeric_extension_values() -> None:
    existing = run_metadata(**{"x-provider": True})
    incoming = run_metadata(**{"x-provider": 1})
    evidence = verification.Evidence(runs={"same": existing})
    restored = evidence.add_run(incoming, preferred="same")
    assert restored != "same"
    assert evidence.runs["same"]["x-provider"] is True
    assert type(evidence.runs[restored]["x-provider"]) is int
