# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""`[tool.byteplan] report_file`: a Markdown view of the registry, kept current at commit time."""

from __future__ import annotations

import json
import re
import shutil
import sys
from typing import TYPE_CHECKING

import pytest

from byteplan.api import Project
from byteplan.cli import EXIT_FINDINGS, EXIT_OK
from byteplan.errors import ConfigError
from byteplan.files import collect_files
from tests.gitutil import git

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory, RunCli


def configure(project: ProjectFactory, extra: str = 'report_file = "byteplan.md"') -> None:
    pyproject = project.root / "pyproject.toml"
    text = pyproject.read_text().replace('include = ["**/*.py"]', 'include = ["**/*.py", "**/*.md"]\n' + extra)
    pyproject.write_text(text)


@pytest.fixture
def reported(project: ProjectFactory) -> ProjectFactory:
    project.init()
    configure(project)
    return project


def report(project: ProjectFactory, name: str = "byteplan.md") -> str:
    return (project.root / name).read_text(encoding="utf-8")


def ids(text: str) -> list[str]:
    return re.findall(r"\[([0-9a-f]{4})\]", text)


def test_scan_writes_the_report(reported: ProjectFactory, run_cli: RunCli) -> None:
    reported.write("src/a.py", "def f():\n    # TODO: First | piped task\n    return 1\n")
    reported.write("README.md", "# Usage\n\n<!-- FIXME: Docs task -->\n")
    assert run_cli("scan", "--project", reported.root).code == EXIT_OK
    (code_id,) = ids((reported.root / "src/a.py").read_text())
    (docs_id,) = ids((reported.root / "README.md").read_text())

    text = report(reported)
    assert text.startswith("# BytePlan\n\n<!-- Generated from .byteplan/tasks.json by BytePlan; don't edit.")
    assert "**2 open** · 0 closed\n" in text
    assert f"| `{code_id}` | open | TODO | normal | - | [`src/a.py:2`](src/a.py#L2) | First \\| piped task |" in text
    assert f"| `{docs_id}` | open | FIXME | normal | - | [`README.md:3`](README.md#L3) | Docs task |" in text
    assert "Nothing closed yet." in text

    before = reported.snapshot()
    assert run_cli("scan", "--project", reported.root).code == EXIT_OK
    assert reported.snapshot() == before  # deterministic: nothing rewritten


def test_registry_commands_regenerate_the_report(reported: ProjectFactory, run_cli: RunCli) -> None:
    reported.write("src/a.py", "# TODO: one\n# TODO: two\nx = 1\n")
    assert run_cli("scan", "--project", reported.root).code == EXIT_OK
    first, second = ids((reported.root / "src/a.py").read_text())

    assert run_cli("resolve", first, "--project", reported.root).code == EXIT_OK
    assert run_cli("status", second, "in_progress", "--project", reported.root).code == EXIT_OK
    assert (
        run_cli("edit", second, "--assignee", "sam", "--priority", "high", "--project", reported.root).code == EXIT_OK
    )
    text = report(reported)
    assert "**1 open** · 1 closed (resolved 1)" in text
    assert f"| `{second}` | in_progress | TODO | high | sam |" in text
    assert f"| `{first}` | resolved | TODO | one |" in text
    assert text.encode() == Project.open(reported.root).render_report(Project.open(reported.root).load_registry())


def test_missing_tasks_are_struck_through(reported: ProjectFactory, run_cli: RunCli) -> None:
    reported.write("src/a.py", "# TODO: going away\nx = 1\n")
    assert run_cli("scan", "--project", reported.root).code == EXIT_OK
    reported.write("src/a.py", "x = 1\n")
    run_cli("scan", "--project", reported.root)
    assert "~~[`src/a.py:1`](src/a.py#L1)~~ (missing)" in report(reported)


def test_links_are_relative_to_the_report(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    configure(project, 'report_file = "docs/plan.md"')
    project.write("src/a.py", "# TODO: x\n")
    assert run_cli("scan", "--project", project.root).code == EXIT_OK
    assert "[`src/a.py:1`](../src/a.py#L1)" in report(project, "docs/plan.md")


def test_the_report_is_never_scanned(reported: ProjectFactory, run_cli: RunCli) -> None:
    reported.write("src/a.py", "# TODO: x\n")
    assert run_cli("scan", "--project", reported.root).code == EXIT_OK
    assert "byteplan.md" not in collect_files(Project.open(reported.root).config).files


def test_no_report_file_by_default(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    project.write("src/a.py", "# TODO: x\n")
    assert run_cli("scan", "--project", project.root).code == EXIT_OK
    assert not (project.root / "byteplan.md").exists()


@pytest.mark.parametrize(
    ("value", "error"),
    [
        ('"../byteplan.md"', "outside the project root"),
        ('"byteplan.txt"', "must be a .md file"),
        ('"."', "outside the project root"),
    ],
)
def test_report_file_validation(project: ProjectFactory, value: str, error: str) -> None:
    project.init()
    configure(project, f"report_file = {value}")
    with pytest.raises(ConfigError, match=error):
        Project.open(project.root)


def test_crlf_copy_is_left_alone(reported: ProjectFactory, run_cli: RunCli) -> None:
    reported.write("src/a.py", "# TODO: x\n")
    assert run_cli("scan", "--project", reported.root).code == EXIT_OK
    path = reported.root / "byteplan.md"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))  # e.g. core.autocrlf on Windows
    crlf = path.read_bytes()
    assert run_cli("scan", "--project", reported.root).code == EXIT_OK
    assert path.read_bytes() == crlf


def test_stale_report_is_a_warning_unless_configured(reported: ProjectFactory, run_cli: RunCli) -> None:
    pyproject = reported.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + "\n[tool.byteplan.check]\nrequire_reconciled = true\n")
    reported.write("src/a.py", "# TODO: x\n")
    assert run_cli("scan", "--project", reported.root).code == EXIT_OK
    (reported.root / "byteplan.md").write_text("hand edited\n")

    result = run_cli("check", "--format", "json", "--project", reported.root)
    assert result.code == EXIT_OK
    (stale,) = [d for d in json.loads(result.out)["diagnostics"] if d["code"] == "report_out_of_sync"]
    assert stale["severity"] == "warning"
    assert "byteplan.md is out of date" in stale["message"]

    pyproject.write_text(pyproject.read_text() + "fail_on_stale_report = true\n")
    assert run_cli("check", "--project", reported.root).code == EXIT_FINDINGS
    (reported.root / "byteplan.md").unlink()
    assert "byteplan.md is missing" in run_cli("check", "--project", reported.root).err
    assert run_cli("scan", "--project", reported.root).code == EXIT_OK
    assert run_cli("check", "--project", reported.root).code == EXIT_OK


# Git: commit-time regeneration and merges ----------------------------------------------------------


@pytest.fixture
def hooked(repo: ProjectFactory, run_cli: RunCli) -> ProjectFactory:
    configure(repo)
    assert run_cli("scan", "--project", repo.root).code == EXIT_OK  # writes byteplan.md
    assert run_cli("git", "install-hooks", "--project", repo.root).code == EXIT_OK
    assert run_cli("git", "install-merge-driver", "--project", repo.root).code == EXIT_OK
    git(repo.root.parent, "add", "-A")
    git(repo.root.parent, "commit", "-qm", "report file")
    return repo


def head(repo: ProjectFactory, rel: str) -> str:
    return git(repo.root.parent, "show", f"HEAD:proj/{rel}").stdout


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_commit_regenerates_and_stages_the_report(hooked: ProjectFactory, run_cli: RunCli) -> None:
    top = hooked.root.parent
    hooked.write("src/c.py", "# HACK: committed task\n")
    git(top, "add", "proj/src/c.py")
    result = git(top, "commit", "-qm", "new task", check=False)
    assert result.returncode == 0, result.stdout + result.stderr

    (task_id,) = ids(head(hooked, "src/c.py"))
    committed = head(hooked, "byteplan.md")
    assert f"| `{task_id}` | open | HACK |" in committed
    assert committed == report(hooked)
    assert git(top, "status", "--porcelain").stdout == ""
    assert run_cli("check", "--commit", "HEAD", "--project", hooked.root).code == EXIT_OK
    assert "REPORT_OUT_OF_SYNC" not in run_cli("check", "--commit", "HEAD", "--project", hooked.root).err


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_staged_check_flags_an_unstaged_report(hooked: ProjectFactory, run_cli: RunCli) -> None:
    top = hooked.root.parent
    tasks = json.loads((hooked.root / ".byteplan/tasks.json").read_text())["tasks"]
    task_id = next(iter(tasks))
    assert run_cli("resolve", task_id, "--project", hooked.root).code == EXIT_OK
    git(top, "add", "proj/.byteplan/tasks.json")  # but not byteplan.md
    err = run_cli("check", "--staged", "--project", hooked.root).err
    assert "byteplan.md is out of date: it doesn't match the staged registry" in err
    assert "git add byteplan.md" in err


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_merging_branches_never_conflicts_on_the_report(hooked: ProjectFactory, run_cli: RunCli) -> None:
    top = hooked.root.parent
    git(top, "switch", "-qc", "feature")
    hooked.write("src/feature.py", "# TODO: feature work\n")
    git(top, "add", "-A")
    assert git(top, "commit", "-qm", "feature", check=False).returncode == 0
    git(top, "switch", "-q", "main")
    hooked.write("src/main.py", "# TODO: main work\n")
    git(top, "add", "-A")
    assert git(top, "commit", "-qm", "main", check=False).returncode == 0

    merged = git(top, "merge", "-q", "--no-edit", "feature", check=False)
    assert merged.returncode == 0, merged.stdout + merged.stderr
    # Ours was kept, so it lacks the feature task until the next scan or hooked commit.
    assert "feature work" not in report(hooked)
    assert "byteplan.md is out of date" in run_cli("check", "--commit", "HEAD", "--project", hooked.root).err
    assert run_cli("scan", "--project", hooked.root).code == EXIT_OK
    assert "feature work" in report(hooked)
    assert "main work" in report(hooked)


def test_link_targets_are_percent_encoded(reported: ProjectFactory, run_cli: RunCli) -> None:
    """Codex review of #21: '#', spaces and '|' in a path must not break the link or the table."""
    reported.write("src/issue#1.py", "# TODO: hash\n")
    reported.write("src/my file.py", "# TODO: space\n")
    if sys.platform != "win32":  # '|' can't be in a Windows filename
        reported.write("src/my file|x.py", "# TODO: space and pipe\n")
    assert run_cli("scan", "--project", reported.root).code == EXIT_OK
    text = report(reported)
    assert "[`src/issue#1.py:1`](src/issue%231.py#L1)" in text
    assert "[`src/my file.py:1`](src/my%20file.py#L1)" in text
    if sys.platform != "win32":
        assert "[`src/my file\\|x.py:1`](src/my%20file%7Cx.py#L1)" in text


def test_open_tasks_are_in_source_order(reported: ProjectFactory, run_cli: RunCli) -> None:
    reported.write("notes.md", "".join(f"<!-- TODO: step {n} -->\n" for n in range(1, 6)))
    assert run_cli("scan", "--project", reported.root).code == EXIT_OK
    steps = re.findall(r"\| step (\d) \|", report(reported))
    assert steps == ["1", "2", "3", "4", "5"]


def test_report_branch_needs_a_report_file(project: ProjectFactory) -> None:
    project.init()
    configure(project, 'report_branch = "main"')
    with pytest.raises(ConfigError, match="report_branch needs a report_file"):
        Project.open(project.root)


@pytest.fixture
def on_main(hooked: ProjectFactory) -> ProjectFactory:
    pyproject = hooked.root / "pyproject.toml"
    text = pyproject.read_text().replace(
        'report_file = "byteplan.md"', 'report_file = "byteplan.md"\nreport_branch = "main"'
    )
    pyproject.write_text(text)
    git(hooked.root.parent, "commit", "-qam", "report on main only")
    return hooked


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_report_branch_leaves_the_report_alone_elsewhere(on_main: ProjectFactory, run_cli: RunCli) -> None:
    top = on_main.root.parent
    before = report(on_main)
    git(top, "switch", "-qc", "feature")
    on_main.write("src/feature.py", "# TODO: feature work\n")
    git(top, "add", "-A")
    assert git(top, "commit", "-qm", "feature", check=False).returncode == 0
    assert "feature work" in head(on_main, ".byteplan/tasks.json")
    assert head(on_main, "byteplan.md") == before  # the hook didn't regenerate it
    assert run_cli("scan", "--project", on_main.root).code == EXIT_OK
    assert report(on_main) == before
    # Not stale here: only the report branch checks it.
    assert (
        "report_out_of_sync"
        not in run_cli("check", "--commit", "HEAD", "--format", "json", "--project", on_main.root).out
    )
    git(top, "switch", "-q", "--detach")  # how CI checks out a pull request
    assert (
        "report_out_of_sync"
        not in run_cli("check", "--commit", "HEAD", "--format", "json", "--project", on_main.root).out
    )

    # Merged into main, it's stale until `report --write` (the post-merge CI job) catches up.
    git(top, "switch", "-q", "main")
    assert git(top, "merge", "-q", "--no-ff", "--no-edit", "feature", check=False).returncode == 0
    assert "byteplan.md is out of date" in run_cli("check", "--commit", "HEAD", "--project", on_main.root).err
    result = run_cli("report", "--write", "--project", on_main.root)
    assert result.code == EXIT_OK
    assert result.out == "byteplan: updated byteplan.md\n"
    assert "feature work" in report(on_main)
    assert run_cli("report", "--write", "--project", on_main.root).out == "byteplan: unchanged byteplan.md\n"
    assert run_cli("check", "--project", on_main.root).code == EXIT_OK


def test_report_write_needs_a_report_file(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    result = run_cli("report", "--write", "--project", project.root)
    assert result.code != EXIT_OK
    assert "no report_file is configured" in result.err
