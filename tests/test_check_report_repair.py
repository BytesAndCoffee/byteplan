# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""`check`, `report` and `repair` (spec 12, 13, 17)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from byteplan.cli import EXIT_ERROR, EXIT_FINDINGS, EXIT_OK, main

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory, RunCli


def tasks(project: ProjectFactory) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((project.root / ".byteplan/tasks.json").read_text())["tasks"]
    return data


@pytest.fixture
def scanned(project: ProjectFactory, run_cli: RunCli) -> ProjectFactory:
    project.init()
    project.write("src/a.py", "# TODO: first | piped\n# FIXME: second\n")
    run_cli("scan", "--project", project.root)
    return project


def test_check_is_read_only_and_passes(scanned: ProjectFactory, run_cli: RunCli) -> None:
    before = scanned.snapshot()
    result = run_cli("check", "--project", scanned.root)
    assert result.code == EXIT_OK
    assert "· OK" in result.out
    assert scanned.snapshot() == before


def test_check_fails_on_duplicates_and_policy(scanned: ProjectFactory, run_cli: RunCli) -> None:
    task_id = next(iter(tasks(scanned)))
    scanned.write("src/b.py", f"# TODO[{task_id}]: copy\n")
    before = scanned.snapshot()
    result = run_cli("check", "--format", "json", "--project", scanned.root)
    assert result.code == EXIT_FINDINGS
    payload = json.loads(result.out)
    assert payload["exit_code"] == EXIT_FINDINGS
    assert "duplicate_id" in [d["code"] for d in payload["diagnostics"]]
    assert scanned.snapshot() == before


def test_check_missing_is_policy_controlled(scanned: ProjectFactory, run_cli: RunCli) -> None:
    (scanned.root / "src/a.py").write_text("")
    assert run_cli("check", "--project", scanned.root).code == EXIT_OK  # warning only by default
    pyproject = (scanned.root / "pyproject.toml").read_text()
    scanned.write("pyproject.toml", pyproject + "\n[tool.byteplan.check]\nfail_on_missing = true\n", dedent=False)
    assert run_cli("check", "--project", scanned.root).code == EXIT_FINDINGS


def test_report_formats(scanned: ProjectFactory, run_cli: RunCli) -> None:
    text = run_cli("report", "--project", scanned.root).out
    assert "BytePlan report: 2 tasks" in text
    assert "status    open 2" in text
    data = json.loads(run_cli("report", "--format", "json", "--project", scanned.root).out)
    assert data["summary"]["by_kind"] == {"FIXME": 1, "TODO": 1}
    assert len(data["tasks"]) == 2
    markdown = run_cli("report", "--format", "markdown", "--project", scanned.root).out
    assert markdown.startswith("# BytePlan report\n")
    assert "first \\| piped" in markdown  # table cells are escaped
    assert "## Findings\n\nNone." in markdown


def test_repair_reassign_comment_duplicate(scanned: ProjectFactory, run_cli: RunCli) -> None:
    original = next(t for t in tasks(scanned).values() if t["kind"] == "TODO")
    copy = scanned.write("src/b.py", f"x = 1\n# TODO[{original['id']}]: pasted copy\n")
    assert run_cli("repair", "--reassign", "src/b.py:1", "--project", scanned.root).code == EXIT_ERROR
    result = run_cli("repair", "--reassign", "src/b.py:2", "--project", scanned.root)
    assert result.code == EXIT_OK, result.err
    new_id = copy.read_text().split("[")[1][:4]
    assert new_id != original["id"]
    assert copy.read_text() == f"x = 1\n# TODO[{new_id}]: pasted copy\n"
    registered = tasks(scanned)
    assert registered[new_id]["title"] == "pasted copy"
    assert "reassigned from duplicate" in registered[new_id]["history"][0]["note"]
    assert f"# TODO[{original['id']}]: first" in (scanned.root / "src/a.py").read_text()  # original untouched
    assert run_cli("check", "--project", scanned.root).code == EXIT_OK


def test_repair_reassign_decorator_duplicate(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    project.write("a.py", "# TODO: original\n")
    run_cli("scan", "--project", project.root)
    task_id = next(iter(tasks(project)))
    path = project.write(
        "b.py", f"from byteplan_runtime import todo\n\n\n@todo('copy', id='{task_id}')\ndef f():\n    return 1\n"
    )
    result = run_cli("repair", "--reassign", "b.py:4", "--project", project.root)
    assert result.code == EXIT_OK, result.err
    assert f"id='{task_id}'" not in path.read_text()
    assert len(tasks(project)) == 2


def test_repair_reassign_refuses_unique_ids(scanned: ProjectFactory, run_cli: RunCli) -> None:
    before = scanned.snapshot()
    result = run_cli("repair", "--reassign", "src/a.py:1", "--project", scanned.root)
    assert result.code == EXIT_ERROR
    assert "not duplicated" in result.err
    assert scanned.snapshot() == before


def test_repair_import(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    path = project.write("a.py", "# TODO[beef]: restored from history\n")
    result = run_cli("repair", "--import", "beef", "--project", project.root)
    assert result.code == EXIT_OK, result.err
    task = tasks(project)["beef"]
    assert (task["title"], task["presence"]) == ("restored from history", "present")
    assert "imported" in task["history"][0]["note"]
    assert path.read_text() == "# TODO[beef]: restored from history\n"
    assert run_cli("repair", "--import", "beef", "--project", project.root).code == EXIT_ERROR  # already there
    assert run_cli("repair", "--import", "ffff", "--project", project.root).code == EXIT_ERROR  # not in source


def test_repair_requires_an_action(project: ProjectFactory, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["repair", "--project", str(project.root)])
    assert "required" in capsys.readouterr().err
