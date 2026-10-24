# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Archival must retain a recoverable verification payload without inventing evidence."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from byteplan import archive, registry, verification
from byteplan._todo import verifies
from byteplan.api import Project
from byteplan.errors import ConcurrentModificationError, ConfigError, RegistryError
from tests.gitutil import frozen, git
from tests.test_archive import _close_and_commit

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import ProjectFactory, RunCli


def _verified_closed_task(repo: ProjectFactory, run_cli: RunCli) -> tuple[Project, str]:
    project = Project.open(repo.root)
    task_id = next(t.id for t in project.list_tasks() if t.title == "second task")
    repo.write("tests/test_archive_proof.py", "def test_proof():\n    assert True\n")
    project.link_tests(task_id, ["tests/test_archive_proof.py::test_proof"])
    _close_and_commit(repo, run_cli)
    report = project.verify([task_id])
    assert report.returncode == 0
    assert project.readiness(project.get_task(task_id)).state == "ready_for_review"
    return project, task_id


def _detach_git(repo: ProjectFactory) -> None:
    metadata = repo.root.parent / ".git"
    detached = repo.root.parent / "detached-git-metadata"
    metadata.rename(detached)
    assert not metadata.exists()
    assert detached.is_dir()


@verifies("4842", "af82fd")
def test_archive_waits_for_a_committed_copy_of_current_evidence(repo: ProjectFactory, run_cli: RunCli) -> None:
    project, task_id = _verified_closed_task(repo, run_cli)
    # The task record is committed, but this successful run has never existed in Git.
    assert git(repo.root, "show", "HEAD:./.byteplan/verification.json", check=False).returncode != 0
    before = frozen(repo)
    preview = project.archive(dry_run=True, older_than=0)
    assert preview.tasks == ()
    assert preview.uncommitted == (task_id,)
    result = project.archive(older_than=0)
    assert result.tasks == ()
    assert result.uncommitted == (task_id,)
    assert frozen(repo) == before

    diagnostic = run_cli("archive", "--older-than", "0", "--project", repo.root)
    assert "verification evidence, including run metadata" in diagnostic.out
    assert frozen(repo) == before


@verifies("4842", "af82fd")
@pytest.mark.parametrize("change", ["result", "entry-extension", "run-extension", "run-provenance"])
def test_staged_evidence_changes_wait_for_a_commit(repo: ProjectFactory, run_cli: RunCli, change: str) -> None:
    project, task_id = _verified_closed_task(repo, run_cli)
    evidence = verification.Evidence.load(repo.root)
    entry = evidence.tasks[task_id]
    run = evidence.runs[entry["run"]]
    entry["vendor"] = True
    run["vendor"] = True
    evidence.save(repo.root)
    git(repo.root.parent, "add", "-A")
    git(repo.root.parent, "commit", "-qm", "preserve original run")
    if change == "result":
        next(iter(entry["tests"].values()))["duration_ms"] += 1
    elif change == "entry-extension":
        entry["vendor"] = 1
    elif change == "run-extension":
        run["vendor"] = 1
    else:
        run["python"] = "a different Python build"
    evidence.save(repo.root)
    git(repo.root, "add", ".byteplan/verification.json")
    before = frozen(repo)
    result = project.archive(older_than=0)
    assert result.tasks == ()
    assert result.uncommitted == (task_id,)
    assert frozen(repo) == before


@verifies("4842", "af82fd")
def test_unrelated_uncommitted_evidence_does_not_block_archival(repo: ProjectFactory, run_cli: RunCli) -> None:
    project, task_id = _verified_closed_task(repo, run_cli)
    git(repo.root.parent, "add", "-A")
    git(repo.root.parent, "commit", "-qm", "preserve task and verification")
    evidence = verification.Evidence.load(repo.root)
    other_id = next(t.id for t in project.list_tasks() if t.id != task_id)
    other_entry = {"tests": {}, "vendor": {"uncommitted": True}}
    evidence.tasks[other_id] = other_entry
    evidence.save(repo.root)
    assert project.archive(older_than=0).tasks == (task_id,)
    assert verification.Evidence.load(repo.root).tasks[other_id] == other_entry


@verifies("4842", "af82fd")
def test_metadata_only_evidence_also_requires_a_committed_copy(repo: ProjectFactory, run_cli: RunCli) -> None:
    task_id = _close_and_commit(repo, run_cli)
    project = Project.open(repo.root)
    repo.write(verification.STORE, json.dumps({"schema_version": 1, "tasks": {task_id: {"tests": {}}}, "runs": {}}))
    assert project.archive(older_than=0).uncommitted == (task_id,)
    assert task_id in verification.Evidence.load(repo.root).tasks
    git(repo.root.parent, "add", "-A")
    git(repo.root.parent, "commit", "-qm", "preserve metadata-only evidence")
    assert project.archive(older_than=0).tasks == (task_id,)


@verifies("4842", "af82fd")
def test_automatic_archive_preserves_uncommitted_evidence(repo: ProjectFactory, run_cli: RunCli) -> None:
    project, task_id = _verified_closed_task(repo, run_cli)
    pyproject = repo.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + "\n[tool.byteplan.archive]\nafter_days = 0\n")
    before = verification.Evidence.load(repo.root).dumps()
    report = Project.open(repo.root).scan(dry_run=False)
    assert not report.dry_run
    assert report.archived == ()
    assert task_id in project.load_registry().tasks
    assert verification.Evidence.load(repo.root).dumps() == before


@verifies("4842", "af82fd", "c26d29")
def test_non_git_archival_remains_local_and_keeps_evidence(repo: ProjectFactory, run_cli: RunCli) -> None:
    project, task_id = _verified_closed_task(repo, run_cli)
    original = verification.Evidence.load(repo.root).tasks[task_id]
    _detach_git(repo)
    assert project.archive(older_than=0).tasks == (task_id,)
    saved = archive.Store(repo.root / ".byteplan").get(task_id)
    assert saved is not None
    assert saved["evidence"] == original
    assert project.restore_archived(task_id)
    assert verification.Evidence.load(repo.root).tasks[task_id] == original


@verifies("4842", "af82fd", "c26d29")
@pytest.mark.parametrize("marker", ["empty-directory", "malformed-directory", "gitfile", "symlink", "bare"])
def test_only_an_empty_git_directory_is_treated_as_a_standalone_marker(
    repo: ProjectFactory, run_cli: RunCli, tmp_path: Path, marker: str
) -> None:
    project, task_id = _verified_closed_task(repo, run_cli)
    _detach_git(repo)
    git_path = repo.root / ".git"
    if marker in {"empty-directory", "malformed-directory"}:
        git_path.mkdir()
        if marker == "malformed-directory":
            (git_path / "config").write_text("[broken\n")
    elif marker == "gitfile":
        git_path.write_text("gitdir: missing-worktree-metadata\n")
    elif marker == "symlink":
        target = tmp_path / "empty-git-target"
        target.mkdir()
        try:
            git_path.symlink_to(target, target_is_directory=True)
        except OSError:
            pytest.skip("creating directory symlinks is unavailable on this platform")
    else:
        (repo.root / "HEAD").write_text("ref: refs/heads/main\n")
        (repo.root / "objects").mkdir()
        (repo.root / "refs").mkdir()
    before = verification.Evidence.load(repo.root).dumps()
    if marker == "empty-directory":
        assert project.archive(older_than=0).tasks == (task_id,)
    else:
        try:
            result = project.archive(older_than=0)
        except ConfigError:
            pass
        else:
            assert result.tasks == ()
        assert task_id in project.load_registry().tasks
        assert verification.Evidence.load(repo.root).dumps() == before


@verifies("4842", "af82fd")
def test_unreadable_current_evidence_has_an_actionable_error(repo: ProjectFactory, run_cli: RunCli) -> None:
    task_id = _close_and_commit(repo, run_cli)
    project = Project.open(repo.root)
    (repo.root / verification.STORE).mkdir()
    before = frozen(repo)
    with pytest.raises(ConfigError, match=r"verification\.json is unreadable"):
        project.archive(older_than=0)
    assert task_id in project.load_registry().tasks
    assert frozen(repo) == before


@verifies("4842", "af82fd")
def test_archive_rejects_type_changes_in_unknown_task_fields(repo: ProjectFactory, run_cli: RunCli) -> None:
    task_id = _close_and_commit(repo, run_cli)
    project = Project.open(repo.root)
    tasks = project.load_registry()
    tasks.tasks[task_id].extra["vendor"] = True
    project.config.registry_path.write_text(registry.dumps(tasks), encoding="utf-8")
    git(repo.root.parent, "add", "-A")
    git(repo.root.parent, "commit", "-qm", "preserve original task extensions")
    tasks.tasks[task_id].extra["vendor"] = 1
    project.config.registry_path.write_text(registry.dumps(tasks), encoding="utf-8")
    before = frozen(repo)
    result = project.archive(older_than=0)
    assert result.tasks == ()
    assert result.uncommitted == (task_id,)
    assert frozen(repo) == before


@verifies("4842", "af82fd")
@pytest.mark.parametrize("failure", ["malformed-config", "unavailable-git"])
def test_git_errors_cannot_enable_local_only_archival(
    repo: ProjectFactory, run_cli: RunCli, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    project, task_id = _verified_closed_task(repo, run_cli)
    if failure == "malformed-config":
        config = repo.root.parent / ".git/config"
        config.write_text(config.read_text() + "\n[broken\n")
    else:
        empty_path = tmp_path / "empty-bin"
        empty_path.mkdir()
        monkeypatch.setenv("PATH", str(empty_path))
    before = frozen(repo)
    with pytest.raises(ConfigError):
        project.archive(older_than=0)
    assert task_id in project.load_registry().tasks
    assert frozen(repo) == before


@verifies("4842", "af82fd")
def test_worktree_gitfile_cannot_hide_failed_git_discovery(
    repo: ProjectFactory, run_cli: RunCli, tmp_path: Path
) -> None:
    project, task_id = _verified_closed_task(repo, run_cli)
    other = tmp_path / "linked-worktree"
    git(repo.root.parent, "worktree", "add", "-q", "-b", "linked", str(other))
    other_project = Project.open(other / "proj")
    other_evidence = other_project.root / verification.STORE
    other_evidence.write_bytes((project.root / verification.STORE).read_bytes())
    assert (other / ".git").is_file()
    config = repo.root.parent / ".git/config"
    config.write_text(config.read_text() + "\n[broken\n")
    before = other_evidence.read_bytes()
    with pytest.raises(ConfigError):
        other_project.archive(older_than=0)
    assert task_id in other_project.load_registry().tasks
    assert other_evidence.read_bytes() == before
    assert not (other_project.root / ".byteplan/archive.sqlite").exists()


@verifies("4842", "af82fd", "c26d29")
@pytest.mark.parametrize("selector", ["GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE"])
def test_explicit_git_selectors_do_not_become_a_non_git_fallback(
    repo: ProjectFactory, run_cli: RunCli, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, selector: str
) -> None:
    project, task_id = _verified_closed_task(repo, run_cli)
    _detach_git(repo)
    monkeypatch.setenv(selector, str(tmp_path / "missing-git-metadata"))
    before = repo.snapshot()
    with pytest.raises(ConfigError):
        project.archive(older_than=0)
    assert task_id in project.load_registry().tasks
    assert repo.snapshot() == before


@verifies("4842", "af82fd")
@pytest.mark.parametrize("task_container", [None, [], "invalid"])
def test_invalid_committed_registry_cannot_disable_git_guards(
    repo: ProjectFactory, run_cli: RunCli, task_container: object
) -> None:
    project, task_id = _verified_closed_task(repo, run_cli)
    registry_path = project.config.registry_path
    valid = registry_path.read_bytes()
    invalid = json.loads(valid)
    invalid["tasks"] = task_container
    registry_path.write_text(json.dumps(invalid), encoding="utf-8")
    git(repo.root, "add", ".byteplan/tasks.json")
    git(repo.root, "commit", "-qm", "invalid committed registry from an external edit")
    registry_path.write_bytes(valid)
    before = frozen(repo)
    with pytest.raises(RegistryError):
        project.archive(older_than=0)
    assert task_id in project.load_registry().tasks
    assert frozen(repo) == before


@verifies("4842", "af82fd")
def test_archive_detects_evidence_changes_during_git_reads(
    repo: ProjectFactory, run_cli: RunCli, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, task_id = _verified_closed_task(repo, run_cli)
    git(repo.root.parent, "add", "-A")
    git(repo.root.parent, "commit", "-qm", "preserve verification")
    original = project._committed_evidence  # noqa: SLF001 - inject an external edit during the Git read

    def edit_during_read() -> verification.Evidence:
        committed = original()
        current = verification.Evidence.load(repo.root)
        current.tasks[task_id]["vendor"] = {"fresh": "uncommitted evidence"}
        current.save(repo.root)
        return committed

    monkeypatch.setattr(project, "_committed_evidence", edit_during_read)
    with pytest.raises(ConcurrentModificationError):
        project.archive(older_than=0)
    assert task_id in project.load_registry().tasks
    assert verification.Evidence.load(repo.root).tasks[task_id]["vendor"] == {"fresh": "uncommitted evidence"}
    assert not (repo.root / ".byteplan/archive.json").exists()


@verifies("4842", "af82fd")
def test_archive_detects_index_changes_after_parsing(
    repo: ProjectFactory, run_cli: RunCli, monkeypatch: pytest.MonkeyPatch
) -> None:
    task_id = _close_and_commit(repo, run_cli)
    project = Project.open(repo.root)
    original = archive.Index.loads
    index_path = repo.root / ".byteplan/archive.json"
    external = archive.Index({"beef": {"sha256": "a" * 64}}).dumps().encode()

    def edit_during_parse(text: str | None) -> archive.Index:
        parsed = original(text)
        index_path.write_bytes(external)
        return parsed

    monkeypatch.setattr(archive.Index, "loads", staticmethod(edit_during_parse))
    with pytest.raises(ConcurrentModificationError):
        project.archive(older_than=0)
    assert task_id in project.load_registry().tasks
    assert index_path.read_bytes() == external


@verifies("4842", "af82fd")
def test_a_fresh_clone_can_recover_archived_records_without_claiming_missing_evidence(
    repo: ProjectFactory, run_cli: RunCli, tmp_path: Path
) -> None:
    project, task_id = _verified_closed_task(repo, run_cli)
    evidence_before = verification.Evidence.load(repo.root)
    original_entry = evidence_before.tasks[task_id]
    original_run = evidence_before.runs[original_entry["run"]]
    git(repo.root.parent, "add", "-A")
    git(repo.root.parent, "commit", "-qm", "preserve verification before archive")
    evidence_commit = git(repo.root, "rev-parse", "HEAD").stdout.strip()
    record = project.get_task(task_id)
    assert project.archive(older_than=0).tasks == (task_id,)
    git(repo.root.parent, "add", "-A")
    git(repo.root.parent, "commit", "-qm", "archive task")

    clone = tmp_path / "fresh-clone"
    git(tmp_path, "clone", "-q", str(repo.root.parent), str(clone))
    other = Project.open(clone / "proj")
    assert not (other.root / ".byteplan/archive.sqlite").exists()
    assert other.reconcile_archive().recovered == (task_id,)
    recovered = other.get_task(task_id)
    assert recovered == record
    assert other.readiness(recovered).state == "unverified"
    assert other.archive_index().tasks[task_id]["sha256"] == archive.record_hash(
        json.loads(git(other.root, "show", f"{evidence_commit}:./.byteplan/tasks.json").stdout)["tasks"][task_id]
    )
    # The local store is not required for recovery of committed evidence. Fetch full
    # history, inspect the historical payload, then rerun verification for fresh results.
    historical = verification.Evidence.loads(
        git(other.root, "show", f"{evidence_commit}:./.byteplan/verification.json").stdout
    )
    assert historical.tasks[task_id] == original_entry
    assert historical.runs[original_entry["run"]] == original_run
    assert other.restore_archived(task_id)
    assert task_id not in verification.Evidence.load(other.root).tasks
    assert other.readiness(other.get_task(task_id)).state == "unverified"
