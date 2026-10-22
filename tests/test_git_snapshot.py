# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Phase 4b: `check --staged`, `check --commit`, `scan --staged --dry-run`, hooks (Addendum C §C9).

Every test runs against a real temporary Git repository. The project lives in a
subdirectory of the repository (``proj/``), so path offsets are always exercised.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from byteplan.cli import EXIT_ERROR, EXIT_FINDINGS, EXIT_OK
from tests.gitutil import frozen, git

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory, RunCli

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def staged(run_cli: RunCli, repo: ProjectFactory, *extra: str) -> Any:
    return run_cli("check", "--staged", "--project", repo.root, *extra)


def codes(result: Any) -> list[str]:
    return sorted(d["code"] for d in json.loads(result.out)["diagnostics"])


def staged_codes(run_cli: RunCli, repo: ProjectFactory) -> tuple[int, list[str]]:
    result = staged(run_cli, repo, "--format", "json")
    return result.code, codes(result)


def tasks(repo: ProjectFactory) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((repo.root / ".byteplan/tasks.json").read_text())["tasks"]
    return data


# C9.1, C9.20 --------------------------------------------------------------------------------------


def test_clean_staged_project_passes_and_changes_nothing(repo: ProjectFactory, run_cli: RunCli) -> None:
    before = frozen(repo)
    first = staged(run_cli, repo)
    second = staged(run_cli, repo)
    assert first.code == EXIT_OK, first.err
    assert "(index)" in first.out
    assert (first.out, first.err) == (second.out, second.err)  # deterministic
    assert frozen(repo) == before


# C9.2 ----------------------------------------------------------------------------------------------


def test_untagged_staged_todo_fails(repo: ProjectFactory, run_cli: RunCli) -> None:
    repo.write("src/c.py", "# TODO: not scanned yet\n")
    git(repo.root, "add", "src/c.py")
    code, found = staged_codes(run_cli, repo)
    assert code == EXIT_FINDINGS
    assert found == ["new_unregistered"]


# C9.3 ----------------------------------------------------------------------------------------------


def test_code_staged_without_registry_is_rejected(repo: ProjectFactory, run_cli: RunCli) -> None:
    repo.write("src/c.py", "# TODO: new work\n")
    run_cli("scan", "--project", repo.root)  # the working tree is fully reconciled...
    git(repo.root, "add", "src/c.py")  # ...but only the source is staged
    code, found = staged_codes(run_cli, repo)
    assert code == EXIT_FINDINGS
    assert "registry_not_staged" in found
    assert "working_tree_changed_but_not_staged" in found
    git(repo.root, "add", ".byteplan/tasks.json")
    assert staged_codes(run_cli, repo) == (EXIT_OK, [])


# C9.4, C9.5, C9.6 ------------------------------------------------------------------------------------


def test_registry_only_status_change_is_accepted(repo: ProjectFactory, run_cli: RunCli) -> None:
    task_id = next(iter(tasks(repo)))
    run_cli("status", task_id, "in_progress", "--project", repo.root)
    git(repo.root, "add", ".byteplan/tasks.json")
    assert staged_codes(run_cli, repo) == (EXIT_OK, [])


def test_deleted_open_annotation_is_out_of_sync_not_resolved(repo: ProjectFactory, run_cli: RunCli) -> None:
    (repo.root / "src/b.py").write_text("x = 1\n")
    git(repo.root, "add", "src/b.py")
    code, found = staged_codes(run_cli, repo)
    assert code == EXIT_FINDINGS
    assert "registry_out_of_sync" in found
    assert all(task["status"] == "open" for task in tasks(repo).values())


def test_resolved_and_removed_together_is_fine(repo: ProjectFactory, run_cli: RunCli) -> None:
    task_id = next(t["id"] for t in tasks(repo).values() if t["kind"] == "FIXME")
    run_cli("resolve", task_id, "--project", repo.root)
    (repo.root / "src/b.py").write_text("x = 1\n")
    git(repo.root, "add", "-A")
    assert staged_codes(run_cli, repo) == (EXIT_OK, [])


# C9.8, position drift ------------------------------------------------------------------------------


def test_staged_rename_keeps_ids(repo: ProjectFactory, run_cli: RunCli) -> None:
    ids_before = sorted(tasks(repo))
    git(repo.root, "mv", "src/b.py", "src/renamed b.py")
    code, found = staged_codes(run_cli, repo)
    assert (code, found) == (EXIT_FINDINGS, ["registry_out_of_sync"])  # moved, not yet recorded
    run_cli("scan", "--project", repo.root)
    git(repo.root, "add", "-A")
    assert staged_codes(run_cli, repo) == (EXIT_OK, [])
    assert sorted(tasks(repo)) == ids_before


def test_line_shifts_are_informational_by_default(repo: ProjectFactory, run_cli: RunCli) -> None:
    path = repo.root / "src/b.py"
    path.write_text("import os\n\n" + path.read_text())
    git(repo.root, "add", "src/b.py")
    assert staged_codes(run_cli, repo) == (EXIT_OK, ["position_drift"])
    pyproject = repo.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + "\n[tool.byteplan.check]\nfail_on_position_drift = true\n")
    git(repo.root, "add", "pyproject.toml")
    assert staged_codes(run_cli, repo) == (EXIT_FINDINGS, ["position_drift"])


# C9.9, C9.10, C9.12 -----------------------------------------------------------------------------------


def test_judges_staged_blobs_not_the_working_tree(repo: ProjectFactory, run_cli: RunCli) -> None:
    (repo.root / "src/a.py").write_text("def f(:\n    # TODO: broken, unstaged\n")
    repo.write("src/untracked.py", "# TODO: never staged\n")
    before = frozen(repo)
    assert staged_codes(run_cli, repo) == (EXIT_OK, [])
    assert frozen(repo) == before
    assert run_cli("check", "--project", repo.root).code == EXIT_ERROR  # the working tree really is broken


def test_partially_staged_file(repo: ProjectFactory, run_cli: RunCli) -> None:
    path = repo.root / "src/b.py"
    tagged = path.read_text()
    path.write_text(tagged + "# TODO: staged addition\n")
    git(repo.root, "add", "src/b.py")
    path.write_text(tagged)  # working tree no longer has it; the index does
    code, found = staged_codes(run_cli, repo)
    assert (code, found) == (EXIT_FINDINGS, ["new_unregistered"])


def test_removed_from_index_but_present_on_disk(repo: ProjectFactory, run_cli: RunCli) -> None:
    git(repo.root, "rm", "-q", "--cached", "src/b.py")
    code, found = staged_codes(run_cli, repo)
    assert code == EXIT_FINDINGS
    assert "registry_out_of_sync" in found


# C9.11 ----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    ["src/with space/naïve module.py", "src/路由.py"]
    + ([] if sys.platform == "win32" else ['src/odd"quote.py', "src/new\nline.py"]),
)
def test_unusual_filenames(repo: ProjectFactory, run_cli: RunCli, name: str) -> None:
    repo.write(name, "# TODO: odd name\n")
    git(repo.root, "add", "-A")
    assert staged_codes(run_cli, repo) == (EXIT_FINDINGS, ["new_unregistered"])
    run_cli("scan", "--project", repo.root)
    git(repo.root, "add", "-A")
    assert staged_codes(run_cli, repo) == (EXIT_OK, [])


# C9.13, C9.14, C9.19 ----------------------------------------------------------------------------------


def test_duplicate_and_unregistered_ids_fail_without_changes(repo: ProjectFactory, run_cli: RunCli) -> None:
    task_id = next(iter(tasks(repo)))
    repo.write("src/copy.py", f"# TODO[{task_id}]: pasted\n# TODO[beef]: from elsewhere\n")
    git(repo.root, "add", "src/copy.py")
    before = frozen(repo)
    code, found = staged_codes(run_cli, repo)
    assert code == EXIT_FINDINGS
    assert {"duplicate_id", "unregistered_id"} <= set(found)
    assert frozen(repo) == before


def test_scan_staged_dry_run_only(repo: ProjectFactory, run_cli: RunCli) -> None:
    repo.write("src/c.py", "# TODO: preview me\n")
    git(repo.root, "add", "src/c.py")
    before = frozen(repo)
    preview = run_cli("scan", "--staged", "--dry-run", "--project", repo.root)
    assert "Would annotate" in preview.out
    assert "preview me" in preview.out
    assert frozen(repo) == before
    refused = run_cli("scan", "--staged", "--project", repo.root)
    assert refused.code == EXIT_ERROR
    assert "exactly one of --dry-run (preview) or --apply" in refused.err
    assert frozen(repo) == before


def test_narrowed_staged_scan_never_reports_missing(repo: ProjectFactory, run_cli: RunCli) -> None:
    (repo.root / "src/b.py").write_text("x = 1\n")
    git(repo.root, "add", "src/b.py")
    target = repo.root / "src/a.py"  # CLI paths are relative to the current directory, like any CLI
    result = run_cli("scan", "--staged", "--dry-run", "--format", "json", "--project", repo.root, target)
    payload = json.loads(result.out)
    assert payload["narrowed"]
    assert payload["missing"] == []


# C9.18: one policy for hook, CI and require_reconciled ----------------------------------------------------


def test_staged_commit_and_working_tree_checks_agree(repo: ProjectFactory, run_cli: RunCli) -> None:
    repo.write("src/c.py", "# TODO: unregistered\n")
    (repo.root / "src/b.py").write_text("x = 1\n")
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "unreconciled")  # index == HEAD == working tree

    def view(result: Any) -> list[tuple[str, str | None, str]]:
        diagnostics = json.loads(result.out)["diagnostics"]
        return sorted((d["code"], d["task_id"], json.dumps(d["locations"])) for d in diagnostics)

    staged_result = staged(run_cli, repo, "--format", "json")
    commit_result = run_cli("check", "--commit", "HEAD", "--format", "json", "--project", repo.root)
    assert staged_result.code == commit_result.code == EXIT_FINDINGS
    assert view(staged_result) == view(commit_result)

    pyproject = repo.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + "\n[tool.byteplan.check]\nrequire_reconciled = true\n")
    worktree = run_cli("check", "--format", "json", "--project", repo.root)
    assert worktree.code == EXIT_FINDINGS
    assert view(worktree) == view(commit_result)


def test_commit_check_of_an_older_revision(repo: ProjectFactory, run_cli: RunCli) -> None:
    repo.write("src/c.py", "# TODO: later work\n")
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "unreconciled")
    assert run_cli("check", "--commit", "HEAD~1", "--project", repo.root).code == EXIT_OK
    assert run_cli("check", "--commit", "HEAD", "--project", repo.root).code == EXIT_FINDINGS
    bad = run_cli("check", "--commit", "no-such-rev", "--project", repo.root)
    assert bad.code == EXIT_ERROR


# Missing registry, config mismatch, unmerged index -------------------------------------------------------


def test_registry_not_in_snapshot(project: ProjectFactory, run_cli: RunCli) -> None:
    top = project.root.parent
    git(top, "init", "-q", "-b", "main")
    project.init()
    project.write("src/a.py", "# TODO: x\n")
    git(top, "add", "proj/pyproject.toml", "proj/src/a.py")
    code, found = staged_codes(run_cli, project)
    assert (code, found) == (EXIT_FINDINGS, ["registry_not_staged"])


def test_unstaged_config_change_is_reported_and_staged_config_wins(repo: ProjectFactory, run_cli: RunCli) -> None:
    pyproject = repo.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace('include = ["**/*.py"]', 'include = ["nothing/**/*.py"]'))
    code, found = staged_codes(run_cli, repo)
    assert (code, found) == (EXIT_OK, ["staged_config_mismatch"])  # staged include still covers src/


def test_unmerged_index_is_an_error(repo: ProjectFactory, run_cli: RunCli) -> None:
    top = repo.root.parent
    git(top, "switch", "-q", "-c", "other")
    (repo.root / "src/b.py").write_text("x = 2\n")
    git(top, "commit", "-qam", "other")
    git(top, "switch", "-q", "main")
    (repo.root / "src/b.py").write_text("x = 3\n")
    git(top, "commit", "-qam", "main")
    git(top, "merge", "-q", "other", check=False)
    result = staged(run_cli, repo)
    assert result.code == EXIT_ERROR
    assert "unmerged_index" in result.err


# Hooks ----------------------------------------------------------------------------------------------------


def test_check_mode_hook_blocks_an_unreconciled_commit(repo: ProjectFactory, run_cli: RunCli) -> None:
    top = repo.root.parent
    result = run_cli("git", "install-hooks", "--mode", "check", "--project", repo.root)
    assert result.code == EXIT_OK, result.err
    hook = top / ".git/hooks/pre-commit"
    assert os.access(hook, os.X_OK)
    assert "byteplan-managed-hook" in hook.read_text()

    repo.write("src/c.py", "# TODO: sneaking in\n")
    git(top, "add", "-A")
    blocked = git(top, "commit", "-qm", "unreconciled", check=False)
    assert blocked.returncode != 0
    assert "NEW_UNREGISTERED" in blocked.stdout + blocked.stderr

    run_cli("scan", "--project", repo.root)
    git(top, "add", "-A")
    assert git(top, "commit", "-qm", "reconciled", check=False).returncode == 0


def test_install_hooks_never_overwrites_a_foreign_hook(repo: ProjectFactory, run_cli: RunCli) -> None:
    hook = repo.root.parent / ".git/hooks/pre-commit"
    hook.write_text("#!/bin/sh\necho mine\n")
    result = run_cli("git", "install-hooks", "--project", repo.root)
    assert result.code == EXIT_ERROR
    assert "leaving it alone" in result.err
    assert hook.read_text() == "#!/bin/sh\necho mine\n"


def test_install_hooks_respects_core_hookspath_and_is_idempotent(repo: ProjectFactory, run_cli: RunCli) -> None:
    top = repo.root.parent
    git(top, "config", "core.hooksPath", "githooks")
    assert run_cli("git", "install-hooks", "--mode", "scan", "--project", repo.root).code == EXIT_OK
    script = (top / "githooks/pre-commit").read_text()
    assert "scan --staged --dry-run" in script
    assert "already installed" in run_cli("git", "install-hooks", "--mode", "scan", "--project", repo.root).out


def test_hooks_status(repo: ProjectFactory, run_cli: RunCli) -> None:
    status = json.loads(run_cli("git", "hooks-status", "--format", "json", "--project", repo.root).out)
    assert status["direct_hook"] == "none"
    assert status["merge_driver"] is False
    run_cli("git", "install-hooks", "--project", repo.root)
    run_cli("git", "install-merge-driver", "--project", repo.root)
    (repo.root.parent / ".pre-commit-config.yaml").write_text("repos:\n  - hooks:\n      - id: byteplan-check\n")
    status = json.loads(run_cli("git", "hooks-status", "--format", "json", "--project", repo.root).out)
    assert status == {**status, "direct_hook": "byteplan", "merge_driver": True, "pre_commit_framework": True}


def test_pre_commit_manifest_is_valid() -> None:
    text = (Path(__file__).resolve().parents[1] / ".pre-commit-hooks.yaml").read_text()
    for needle in (
        "id: byteplan-check",
        "entry: byteplan check --staged",
        "always_run: true",
        "pass_filenames: false",
        "id: byteplan-scan-preview",
        "stages: [manual]",
    ):
        assert needle in text
    yaml_lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    assert not any(line.strip().startswith("types:") for line in yaml_lines)


# Codex review of #13 ---------------------------------------------------------------------------------


def test_project_is_found_in_the_snapshot_not_on_disk(repo: ProjectFactory, run_cli: RunCli) -> None:
    (repo.root / "pyproject.toml").unlink()  # deleted in the working tree only
    result = staged(run_cli, repo)
    assert result.code == EXIT_OK, result.err
    assert run_cli("check", "--commit", "HEAD", "--project", repo.root).code == EXIT_OK


def test_unstaged_nested_pyproject_does_not_change_the_project(repo: ProjectFactory, run_cli: RunCli) -> None:
    repo.write("src/pyproject.toml", '[project]\nname = "decoy"\n')  # untracked, never staged
    result = run_cli("check", "--staged", "--format", "json", "--project", repo.root / "src")
    assert result.code == EXIT_OK, result.err
    assert json.loads(result.out)["diagnostics"] == []


def test_writing_scan_with_require_reconciled_reports_the_result(repo: ProjectFactory, run_cli: RunCli) -> None:
    pyproject = repo.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + "\n[tool.byteplan.check]\nrequire_reconciled = true\n")
    repo.write("src/c.py", "# TODO: new work\n")
    assert run_cli("check", "--project", repo.root).code == EXIT_FINDINGS  # read-only: not reconciled yet
    scanned = run_cli("scan", "--project", repo.root)
    assert scanned.code == EXIT_OK, scanned.err
    assert "NEW_UNREGISTERED" not in scanned.err
    assert run_cli("check", "--project", repo.root).code == EXIT_OK
