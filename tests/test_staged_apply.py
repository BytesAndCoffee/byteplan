# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Phase 4c: `scan --staged --apply` and the reconcile pre-commit hook.

Design principle under test: the first committed appearance of an obligation
already carries its permanent ID. Every test runs against a real Git
repository (project nested in ``proj/``), as in Phase 4b.
"""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING, Any

import pytest

from byteplan import gitwrite
from byteplan.cli import EXIT_ERROR, EXIT_FINDINGS, EXIT_OK
from byteplan.gitwrite import RollbackConflictError, StagedJournal, reconcile_staged
from byteplan.persistence import atomic_write_bytes as real_write
from tests.gitutil import frozen, git

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import ProjectFactory, RunCli

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


class CrashError(Exception):
    """Simulates the process dying: nothing after it runs."""


def head(repo: ProjectFactory, rel: str) -> str:
    return git(repo.root.parent, "show", f"HEAD:proj/{rel}").stdout


def head_tasks(repo: ProjectFactory) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(head(repo, ".byteplan/tasks.json"))["tasks"]
    return data


def entries_and_files(repo: ProjectFactory) -> tuple[str, dict[str, str]]:
    """Index *entries* plus working-tree files. `git commit` refreshes .git/index stat data even
    when a hook stops it, so raw index bytes aren't a fair "nothing changed" test there."""
    files = {k: v for k, v in frozen(repo).items() if k != ".git/index"}
    return git(repo.root.parent, "ls-files", "--stage").stdout, files


def status(repo: ProjectFactory) -> str:
    return git(repo.root.parent, "status", "--porcelain", "--untracked-files=all").stdout


def index_oid(repo: ProjectFactory, rel: str) -> str:
    return git(repo.root.parent, "ls-files", "--stage", f"proj/{rel}").stdout.split(" ")[1]


@pytest.fixture
def hooked(repo: ProjectFactory, run_cli: RunCli) -> ProjectFactory:
    assert run_cli("git", "install-hooks", "--project", repo.root).code == EXIT_OK  # default: reconcile
    return repo


# The design principle, end to end ------------------------------------------------------------------


def test_commit_carries_the_id(hooked: ProjectFactory) -> None:
    top = hooked.root.parent
    hooked.write("src/rip.py", "def withdraw():\n    # FIXME: Handle withdrawn routes\n    return None\n")
    git(top, "add", ".")
    result = git(top, "commit", "-qm", "Document route withdrawal bug", check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "annotated" in result.stdout + result.stderr

    committed = head(hooked, "src/rip.py")
    (task_id,) = [t for t, task in head_tasks(hooked).items() if task["title"] == "Handle withdrawn routes"]
    assert f"# FIXME[{task_id}]: Handle withdrawn routes" in committed
    assert status(hooked) == ""  # working tree == index == HEAD: no phantom diff
    assert (hooked.root / "src/rip.py").read_text() == committed
    assert git(top, "log", "--oneline").stdout.count("\n") == 2  # exactly one new commit


@pytest.mark.parametrize("mode", ["-a", "--include", "--amend"])
def test_every_commit_mode(hooked: ProjectFactory, mode: str) -> None:
    top = hooked.root.parent
    path = hooked.root / "src/b.py"
    path.write_text(path.read_text() + "# TODO: added in " + mode + "\n")
    if mode == "-a":
        command = ["commit", "-qam", "msg"]
    elif mode == "--include":
        command = ["commit", "-q", "--include", "proj/src/b.py", "-m", "msg"]
    else:
        git(top, "add", "proj/src/b.py")
        command = ["commit", "-q", "--amend", "-m", "amended"]
    result = git(top, *command, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    added = [t for t, task in head_tasks(hooked).items() if task["title"] == f"added in {mode}"]
    assert len(added) == 1
    assert f"# TODO[{added[0]}]: added in {mode}" in head(hooked, "src/b.py")
    assert status(hooked) == ""


def test_commit_with_paths_falls_back_to_the_check(hooked: ProjectFactory) -> None:
    top = hooked.root.parent
    path = hooked.root / "src/b.py"
    path.write_text(path.read_text() + "# TODO: via paths\n")
    before = frozen(hooked)
    result = git(top, "commit", "-qm", "msg", "proj/src/b.py", check=False)
    assert result.returncode != 0
    assert "temporary index" in result.stdout + result.stderr
    after = frozen(hooked)
    assert {k: v for k, v in after.items() if k != ".git/index"} == {
        k: v for k, v in before.items() if k != ".git/index"
    }


# Refusals: nothing is written -------------------------------------------------------------------------


def test_partially_staged_file_is_refused(hooked: ProjectFactory) -> None:
    top = hooked.root.parent
    path = hooked.root / "src/b.py"
    path.write_text(path.read_text() + "# TODO: staged part\n")
    git(top, "add", "proj/src/b.py")
    path.write_text(path.read_text() + "y = 2  # unstaged part\n")
    before = entries_and_files(hooked)
    result = git(top, "commit", "-qm", "msg", check=False)
    assert result.returncode != 0
    assert "partial_stage_conflict: src/b.py" in result.stdout + result.stderr
    assert entries_and_files(hooked) == before


def test_unstaged_registry_edits_are_refused(hooked: ProjectFactory, run_cli: RunCli) -> None:
    top = hooked.root.parent
    task_id = next(iter(json.loads((hooked.root / ".byteplan/tasks.json").read_text())["tasks"]))
    run_cli("edit", task_id, "--priority", "high", "--project", hooked.root)  # not staged
    hooked.write("src/c.py", "# TODO: new\n")
    git(top, "add", "proj/src/c.py")
    before = entries_and_files(hooked)
    result = git(top, "commit", "-qm", "msg", check=False)
    assert result.returncode != 0
    assert "registry_partial_stage_conflict" in result.stdout + result.stderr
    assert entries_and_files(hooked) == before


def test_unstaged_and_untracked_files_stay_out_of_the_commit(hooked: ProjectFactory) -> None:
    top = hooked.root.parent
    b = hooked.root / "src/b.py"
    b_before = b.read_text()
    b.write_text(b_before + "# TODO: unstaged, other file\n")
    hooked.write("src/untracked.py", "# TODO: never added\n")
    hooked.write("src/c.py", "# TODO: staged\n")
    git(top, "add", "proj/src/c.py")
    assert git(top, "commit", "-qm", "msg", check=False).returncode == 0
    assert head(hooked, "src/b.py") == b_before
    assert b.read_text() == b_before + "# TODO: unstaged, other file\n"  # untouched
    assert (hooked.root / "src/untracked.py").read_text() == "# TODO: never added\n"
    assert "untracked.py" not in git(top, "ls-files").stdout
    assert [t["title"] for t in head_tasks(hooked).values() if t["source"]["path"] == "src/untracked.py"] == []
    assert status(hooked) == " M proj/src/b.py\n?? proj/src/untracked.py\n"


def test_split_index_is_refused(repo: ProjectFactory, run_cli: RunCli) -> None:
    top = repo.root.parent
    git(top, "config", "core.splitIndex", "true")
    repo.write("src/c.py", "# TODO: new\n")
    git(top, "add", "proj/src/c.py")
    result = run_cli("scan", "--staged", "--apply", "--project", repo.root)
    assert result.code == EXIT_ERROR
    assert "unsupported_index_format" in result.err


# Retries, policy, framework mode ------------------------------------------------------------------------


def test_apply_is_idempotent(repo: ProjectFactory, run_cli: RunCli) -> None:
    repo.write("src/c.py", "# TODO: once\n")
    git(repo.root.parent, "add", "proj/src/c.py")
    first = run_cli("scan", "--staged", "--apply", "--project", repo.root)
    assert first.code == EXIT_OK, first.out + first.err
    after_first = frozen(repo)
    second = run_cli("scan", "--staged", "--apply", "--project", repo.root)
    assert second.code == EXIT_OK
    assert "annotated" not in second.out
    assert frozen(repo) == after_first


def test_on_reconcile_stop_writes_then_stops(repo: ProjectFactory, run_cli: RunCli) -> None:
    top = repo.root.parent
    pyproject = repo.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + '\n[tool.byteplan.git]\non_reconcile = "stop"\n')
    repo.write("src/c.py", "# TODO: review me\n")
    git(top, "add", "-A")
    result = run_cli("scan", "--staged", "--apply", "--project", repo.root)
    assert result.code == EXIT_FINDINGS
    assert "on_reconcile" in result.out
    assert "TODO[" in (repo.root / "src/c.py").read_text()
    assert sorted(status(repo).splitlines()) == [
        "A  proj/src/c.py",
        "M  proj/.byteplan/tasks.json",
        "M  proj/pyproject.toml",
    ]


def test_pre_commit_framework_mode_is_a_working_tree_fixer(
    repo: ProjectFactory, run_cli: RunCli, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo.write("src/c.py", "# TODO: framework\n")
    git(repo.root.parent, "add", "proj/src/c.py")
    staged_oid = index_oid(repo, "src/c.py")
    monkeypatch.setenv("PRE_COMMIT", "1")
    result = run_cli("scan", "--staged", "--apply", "--project", repo.root)
    assert result.code == EXIT_FINDINGS
    assert "commit again" in result.out
    assert index_oid(repo, "src/c.py") == staged_oid  # the index is left alone
    assert "TODO[" in (repo.root / "src/c.py").read_text()


def test_apply_argument_errors(repo: ProjectFactory, run_cli: RunCli) -> None:
    assert "for --staged" in run_cli("scan", "--apply", "--project", repo.root).err
    both = run_cli("scan", "--staged", "--apply", "--dry-run", "--project", repo.root)
    assert both.code == EXIT_ERROR
    paths = run_cli("scan", "--staged", "--apply", "--project", repo.root, repo.root / "src")
    assert "doesn't take paths" in paths.err


def test_decorator_and_stub_edits_through_the_index(hooked: ProjectFactory) -> None:
    top = hooked.root.parent
    hooked.write(
        "src/d.py",
        'from byteplan_runtime import todo\n\n\n@todo("Plan")\ndef planned():\n    return 1\n\n\ndef stub():\n    pass\n',
    )
    git(top, "add", ".")
    assert git(top, "commit", "-qm", "msg", check=False).returncode == 0
    committed = head(hooked, "src/d.py")
    assert '@todo("Plan", id="' in committed
    assert "# TODO[" in committed
    assert "Implement stub (detected stub)" in committed
    assert status(hooked) == ""


# Failure injection: rollback and crash recovery -------------------------------------------------------


def _three_targets(repo: ProjectFactory) -> None:
    repo.write("src/c.py", "# TODO: first\n")
    repo.write("src/d.py", "# TODO: second\n")
    git(repo.root.parent, "add", "proj/src/c.py", "proj/src/d.py")


def test_concurrent_edit_rolls_everything_back(repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    _three_targets(repo)
    oids = {rel: index_oid(repo, rel) for rel in ("src/c.py", "src/d.py", ".byteplan/tasks.json")}

    def write_then_editor_saves_d(path: Path, data: bytes, mode: int | None = None) -> bool:
        written = real_write(path, data, mode)
        if path.name == "c.py":
            (repo.root / "src/d.py").write_text("# TODO: second\nedited = True\n")  # editor save
        return written

    monkeypatch.setattr(gitwrite, "atomic_write_bytes", write_then_editor_saves_d)
    outcome = reconcile_staged(repo.root)
    monkeypatch.undo()
    assert outcome.code == EXIT_FINDINGS
    assert any("concurrent_modification" in m for m in outcome.messages)
    assert (repo.root / "src/c.py").read_text() == "# TODO: first\n"  # BytePlan's write undone
    assert (repo.root / "src/d.py").read_text() == "# TODO: second\nedited = True\n"  # editor's kept
    assert {rel: index_oid(repo, rel) for rel in oids} == oids  # index restored
    assert not StagedJournal.path(repo.root).exists()
    assert "registry" not in status(repo)  # registry untouched


def _crash_after(monkeypatch: pytest.MonkeyPatch, *, writes_before_crash: int) -> None:
    """Die after N working-tree writes (N=0: right after the index swap); no rollback runs."""
    calls = {"n": 0}

    def write(path: Path, data: bytes, mode: int | None = None) -> bool:
        if path.name != gitwrite.STAGED_JOURNAL:
            if calls["n"] == writes_before_crash:
                raise CrashError
            calls["n"] += 1
        return real_write(path, data, mode)

    def no_rollback(*_: Any) -> None:
        raise CrashError

    monkeypatch.setattr(gitwrite, "atomic_write_bytes", write)
    monkeypatch.setattr(gitwrite, "_rollback", no_rollback)


@pytest.mark.parametrize("writes_before_crash", [0, 1, 2])
def test_crash_recovers_forward(
    repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch, writes_before_crash: int
) -> None:
    _three_targets(repo)
    _crash_after(monkeypatch, writes_before_crash=writes_before_crash)
    with pytest.raises(CrashError):
        reconcile_staged(repo.root)
    monkeypatch.undo()
    assert StagedJournal.path(repo.root).exists()
    outcome = reconcile_staged(repo.root)  # next run finishes the interrupted one
    assert any("completed an interrupted staged reconciliation" in m for m in outcome.messages)
    assert outcome.code == EXIT_OK
    assert not StagedJournal.path(repo.root).exists()
    for rel in ("src/c.py", "src/d.py"):
        assert "TODO[" in (repo.root / rel).read_text()
    assert sorted(status(repo).splitlines()) == ["A  proj/src/c.py", "A  proj/src/d.py", "M  proj/.byteplan/tasks.json"]


def test_crash_then_foreign_edit_recovers_backward(repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    _three_targets(repo)
    oids = {rel: index_oid(repo, rel) for rel in ("src/c.py", "src/d.py", ".byteplan/tasks.json")}
    _crash_after(monkeypatch, writes_before_crash=1)  # c.py written; d.py and the registry not yet
    with pytest.raises(CrashError):
        reconcile_staged(repo.root)
    monkeypatch.undo()
    (repo.root / "src/d.py").write_text("# TODO: second\nforeign = 1\n")  # someone else edits d.py
    messages = gitwrite.recover(repo.root)
    assert any("undid" in m for m in messages)
    assert (repo.root / "src/c.py").read_text() == "# TODO: first\n"  # BytePlan's write undone
    assert (repo.root / "src/d.py").read_text() == "# TODO: second\nforeign = 1\n"  # foreign edit kept
    assert {rel: index_oid(repo, rel) for rel in oids} == oids  # index fully restored
    assert not StagedJournal.path(repo.root).exists()


def test_rollback_never_overwrites_an_edit_to_a_file_byteplan_wrote(
    repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _three_targets(repo)
    _crash_after(monkeypatch, writes_before_crash=1)  # c.py written by BytePlan
    with pytest.raises(CrashError):
        reconcile_staged(repo.root)
    monkeypatch.undo()
    (repo.root / "src/d.py").write_text("# TODO: second\nforeign = 1\n")  # forces the backward direction
    edited_c = (repo.root / "src/c.py").read_text() + "also_edited = True\n"
    (repo.root / "src/c.py").write_text(edited_c)  # ...and the file BytePlan wrote is edited too
    with pytest.raises(RollbackConflictError, match=r"src/c\.py"):
        gitwrite.recover(repo.root)
    assert (repo.root / "src/c.py").read_text() == edited_c  # left alone
    assert StagedJournal.path(repo.root).exists()  # kept for manual resolution


def test_pending_staged_journal_blocks_other_writes(
    repo: ProjectFactory, run_cli: RunCli, monkeypatch: pytest.MonkeyPatch
) -> None:
    _three_targets(repo)
    _crash_after(monkeypatch, writes_before_crash=0)
    with pytest.raises(CrashError):
        reconcile_staged(repo.root)
    monkeypatch.undo()
    result = run_cli("scan", "--project", repo.root)
    assert result.code == EXIT_ERROR
    assert "interrupted staged reconciliation" in result.err
    assert run_cli("scan", "--staged", "--apply", "--project", repo.root).code == EXIT_OK
    assert run_cli("scan", "--project", repo.root).code == EXIT_OK
