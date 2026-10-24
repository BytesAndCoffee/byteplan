# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Restoration plans must not overwrite evidence or index edits they did not read."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import TYPE_CHECKING, Any

import pytest

from byteplan import archive, verification
from byteplan._todo import verifies
from byteplan.errors import ConcurrentModificationError, ConfigError
from tests.gitutil import frozen, git
from tests.test_archive import _close_and_commit
from tests.test_rc1_storage import _verified_closed_task

if TYPE_CHECKING:
    from byteplan.api import Project
    from byteplan.models import Task
    from tests.conftest import ProjectFactory, RunCli


def _archived_task(repo: ProjectFactory, run_cli: RunCli) -> tuple[Project, str]:
    project, task_id = _verified_closed_task(repo, run_cli)
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "preserve task and evidence before archive")
    assert project.archive(older_than=0).tasks == (task_id,)
    return project, task_id


@verifies("50ad66")
def test_restore_preserves_evidence_edited_after_parsing(
    repo: ProjectFactory, run_cli: RunCli, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, task_id = _archived_task(repo, run_cli)
    evidence_path = repo.root / verification.STORE
    before = frozen(repo)
    original = verification.Evidence.loads
    external: bytes | None = None

    def parse_then_edit(text: str | bytes) -> verification.Evidence:
        nonlocal external
        parsed = original(text)
        current = json.loads(evidence_path.read_bytes())
        current["authored-after-read"] = {"preserve": True}
        external = json.dumps(current, sort_keys=True).encode()
        evidence_path.write_bytes(external)
        return parsed

    monkeypatch.setattr(verification.Evidence, "loads", staticmethod(parse_then_edit))
    with pytest.raises(ConcurrentModificationError):
        project.restore_archived(task_id)
    assert external is not None
    assert evidence_path.read_bytes() == external
    assert task_id not in project.load_registry().tasks
    after = frozen(repo)
    assert before.keys() == after.keys()
    assert {path for path in before if before[path] != after[path]} == {"proj/.byteplan/verification.json"}


@verifies("50ad66")
def test_restore_preserves_other_index_entries_edited_after_parsing(
    repo: ProjectFactory, run_cli: RunCli, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, task_id = _verified_closed_task(repo, run_cli)
    other_id = _close_and_commit(repo, run_cli, "first task")
    assert set(project.archive(older_than=0).tasks) == {task_id, other_id}
    index_path = repo.root / ".byteplan/archive.json"
    before = frozen(repo)
    original = archive.Index.loads
    sequence = 0
    external: bytes | None = None

    def parse_then_edit(text: str | None) -> archive.Index:
        nonlocal sequence, external
        parsed = original(text)
        sequence += 1
        current = json.loads(index_path.read_bytes())
        current["tasks"][other_id]["authored-after-read"] = {"sequence": sequence}
        external = json.dumps(current, sort_keys=True).encode()
        index_path.write_bytes(external)
        return parsed

    monkeypatch.setattr(archive.Index, "loads", staticmethod(parse_then_edit))
    with pytest.raises(ConcurrentModificationError):
        project.restore_archived(task_id)
    assert external is not None
    assert index_path.read_bytes() == external
    assert task_id not in project.load_registry().tasks
    after = frozen(repo)
    assert before.keys() == after.keys()
    assert {path for path in before if before[path] != after[path]} == {"proj/.byteplan/archive.json"}


@verifies("50ad66")
@pytest.mark.parametrize("artifact", [".byteplan/archive.json", verification.STORE])
def test_restore_reports_unreadable_inputs_without_writes(repo: ProjectFactory, run_cli: RunCli, artifact: str) -> None:
    project, task_id = _archived_task(repo, run_cli)
    path = repo.root / artifact
    path.unlink()
    path.mkdir()
    before = frozen(repo)
    with pytest.raises(ConfigError, match="unreadable"):
        project.restore_archived(task_id)
    assert frozen(repo) == before


@verifies("50ad66")
def test_restore_keeps_lifecycle_opaque_fields_and_conflicting_run_provenance(
    repo: ProjectFactory, run_cli: RunCli
) -> None:
    project, task_id = _verified_closed_task(repo, run_cli)
    original = verification.Evidence.load(repo.root)
    entry = original.tasks[task_id]
    run_id = entry["run"]
    entry["vendor-entry"] = {"preserve": True}
    next(iter(entry["tests"].values()))["vendor-result"] = [1, True]
    original.runs[run_id]["vendor-run"] = True
    original.extra["vendor-root"] = {"preserve": True}
    original.save(repo.root)
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "preserve opaque evidence before archive")
    task = project.get_task(task_id)
    assert project.archive(older_than=0).tasks == (task_id,)
    current = verification.Evidence.load(repo.root)
    other_id = next(iter(project.load_registry().tasks))
    other_entry: dict[str, Any] = {"tests": {}, "run": run_id, "vendor-other": "preserve"}
    current.tasks[other_id] = other_entry
    current.runs[run_id] = {**original.runs[run_id], "vendor-run": 1}
    current.save(repo.root)
    test_path = repo.root / "tests/test_archive_proof.py"
    test_path.write_bytes(test_path.read_bytes() + b"\n# external test edit\n")

    assert project.restore_archived(task_id)
    restored = verification.Evidence.load(repo.root)
    restored_run_id = restored.tasks[task_id]["run"]
    assert restored_run_id != run_id
    assert restored.runs[restored_run_id] == original.runs[run_id]
    assert restored.runs[run_id] == current.runs[run_id]
    assert restored.tasks[task_id] == {**entry, "run": restored_run_id}
    assert restored.tasks[other_id] == other_entry
    assert restored.extra == original.extra
    assert project.get_task(task_id) == task
    assert project.readiness(project.get_task(task_id)).state == "needs_review"


@verifies("50ad66")
def test_restore_keeps_lazy_record_reconciliation_when_the_local_cache_is_missing(
    repo: ProjectFactory, run_cli: RunCli
) -> None:
    project, task_id = _archived_task(repo, run_cli)
    task = project.get_task(task_id)
    (repo.root / ".byteplan/archive.sqlite").unlink()
    assert project.restore_archived(task_id)
    assert project.get_task(task_id) == task
    assert task_id not in verification.Evidence.load(repo.root).tasks
    assert project.readiness(project.get_task(task_id)).state == "unverified"


@verifies("50ad66")
def test_restore_preserves_an_evidence_file_created_during_the_plan(
    repo: ProjectFactory, run_cli: RunCli, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, task_id = _archived_task(repo, run_cli)
    evidence_path = repo.root / verification.STORE
    evidence_path.unlink()
    original = verification.Evidence.restore_task
    external = json.dumps({"schema_version": 1, "tasks": {}, "runs": {}, "authored-while-absent": True}).encode()

    def create_during_restore(
        evidence: verification.Evidence, identity: str, entry: dict[str, Any], run: dict[str, Any] | None
    ) -> None:
        evidence_path.write_bytes(external)
        original(evidence, identity, entry, run)

    monkeypatch.setattr(verification.Evidence, "restore_task", create_during_restore)
    with pytest.raises(ConcurrentModificationError):
        project.restore_archived(task_id)
    assert evidence_path.read_bytes() == external
    assert task_id not in project.load_registry().tasks


@verifies("50ad66")
def test_restore_does_not_combine_one_archived_record_with_another_versions_evidence(
    repo: ProjectFactory, run_cli: RunCli, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, task_id = _archived_task(repo, run_cli)
    local = archive.Store(repo.root / ".byteplan")
    payload = local.get(task_id)
    assert payload is not None
    original_payload = deepcopy(payload)
    payload["task"]["notes"] = "a different archived version of the same identity"
    local.put([(task_id, payload, "2026-10-24T00:00:00Z")])
    index_path = repo.root / ".byteplan/archive.json"
    original_index = index_path.read_bytes()
    original = project.archived_task

    def lookup_while_another_version_is_selected(identity: str) -> Task | None:
        changed = json.loads(original_index)
        changed["tasks"][task_id]["sha256"] = archive.record_hash(payload["task"])
        index_path.write_text(json.dumps(changed), encoding="utf-8")
        try:
            return original(identity)
        finally:
            # A second checkout can restore the original bytes before commit. The
            # selected record/evidence pairing must remain consistent despite that.
            index_path.write_bytes(original_index)

    monkeypatch.setattr(project, "archived_task", lookup_while_another_version_is_selected)
    before = frozen(repo)
    with pytest.raises(ConcurrentModificationError):
        project.restore_archived(task_id)
    assert task_id not in project.load_registry().tasks
    assert frozen(repo) == before
    assert local.get(task_id, archive.record_hash(original_payload["task"])) == original_payload


@verifies("50ad66")
@pytest.mark.parametrize("outcome", ["failed", "passed"])
def test_restore_preserves_verification_recorded_for_the_archived_identity(
    repo: ProjectFactory, run_cli: RunCli, outcome: str
) -> None:
    project, task_id = _archived_task(repo, run_cli)
    archived = project.get_task(task_id)
    cached = archive.Store(repo.root / ".byteplan").get(task_id)
    test_path = repo.root / "tests/test_archive_proof.py"
    test_path.write_text(f"def test_proof():\n    assert {outcome == 'passed'}\n", encoding="utf-8")
    report = project.verify([task_id])
    assert (report.returncode == 0) == (outcome == "passed")
    before = (repo.root / verification.STORE).read_bytes()
    current = verification.Evidence.loads(before)
    assert next(iter(current.tasks[task_id]["tests"].values()))["outcome"] == outcome

    assert project.restore_archived(task_id)
    assert (repo.root / verification.STORE).read_bytes() == before
    assert project.get_task(task_id) == archived
    assert archive.Store(repo.root / ".byteplan").get(task_id) == cached
    assert project.readiness(project.get_task(task_id)).state == (
        "failing" if outcome == "failed" else "ready_for_review"
    )


@verifies("50ad66")
def test_restore_does_not_reinstate_a_pass_after_failure_with_unchanged_source(
    repo: ProjectFactory, run_cli: RunCli, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, task_id = _verified_closed_task(repo, run_cli)
    test_path = repo.root / "tests/test_archive_proof.py"
    test_path.write_text(
        'import os\n\ndef test_proof():\n    assert os.environ.get("BYTEPLAN_RESTORE_RUN_OUTCOME") == "pass"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("BYTEPLAN_RESTORE_RUN_OUTCOME", "pass")
    assert project.verify([task_id]).returncode == 0
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "preserve environment-sensitive verification")
    assert project.archive(older_than=0).tasks == (task_id,)
    source_before = test_path.read_bytes()

    monkeypatch.setenv("BYTEPLAN_RESTORE_RUN_OUTCOME", "fail")
    assert project.verify([task_id]).returncode != 0
    assert project.readiness(project.get_task(task_id)).state == "failing"
    evidence_before = (repo.root / verification.STORE).read_bytes()
    assert project.restore_archived(task_id)
    assert test_path.read_bytes() == source_before
    assert (repo.root / verification.STORE).read_bytes() == evidence_before
    assert project.readiness(project.get_task(task_id)).state == "failing"


@verifies("50ad66")
@pytest.mark.parametrize("case", ["metadata-only", "empty-entry", "same-entry", "different-run-provenance"])
def test_restore_leaves_existing_canonical_evidence_bytes_and_runs_untouched(
    repo: ProjectFactory, run_cli: RunCli, case: str
) -> None:
    project, task_id = _archived_task(repo, run_cli)
    cached = archive.Store(repo.root / ".byteplan").get(task_id)
    assert cached is not None
    current_entry = deepcopy(cached["evidence"])
    current_run = deepcopy(cached["run"])
    if case == "metadata-only":
        current_entry = {"tests": {}, "authored-current-entry": {"preserve": [True, 1]}}
    elif case == "empty-entry":
        current_entry = {}
    elif case == "different-run-provenance":
        current_run["python"] = "a different recorded Python build"
    raw = {
        "schema_version": 1,
        "tasks": {task_id: current_entry},
        "runs": {
            cached["evidence"]["run"]: current_run,
            "unreferenced-historical-run": {"authored-orphan": {"preserve": True}},
        },
        "authored-root": {"preserve": [1, True]},
    }
    before = json.dumps(raw, separators=(",", ":")).encode() + b"\r\n"
    repo.write(verification.STORE, before)
    assert verification.Evidence.load(repo.root).tasks[task_id] == current_entry

    assert project.restore_archived(task_id)
    assert (repo.root / verification.STORE).read_bytes() == before
    assert archive.Store(repo.root / ".byteplan").get(task_id) == cached


@verifies("50ad66")
def test_restore_does_not_overwrite_external_edits_when_canonical_evidence_already_exists(
    repo: ProjectFactory, run_cli: RunCli, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, task_id = _archived_task(repo, run_cli)
    evidence_path = repo.root / verification.STORE
    current = verification.Evidence.load(repo.root)
    current.tasks[task_id] = {"tests": {}, "authored-current": True}
    current.save(repo.root)
    original = verification.Evidence.loads
    external: bytes | None = None

    def edit_after_parse(text: str | bytes) -> verification.Evidence:
        nonlocal external
        parsed = original(text)
        raw = json.loads(evidence_path.read_bytes())
        raw["authored-concurrently"] = {"preserve": True}
        external = json.dumps(raw).encode()
        evidence_path.write_bytes(external)
        return parsed

    monkeypatch.setattr(verification.Evidence, "loads", staticmethod(edit_after_parse))
    assert project.restore_archived(task_id)
    assert external is not None
    assert evidence_path.read_bytes() == external
    assert task_id in project.load_registry().tasks
