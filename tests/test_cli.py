# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
import tomllib
from typing import TYPE_CHECKING

import pytest

from byteplan import __version__
from byteplan.cli import EXIT_ERROR, EXIT_FINDINGS, EXIT_OK, main

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory, RunCli

REGISTRY = {
    "schema_version": 1,
    "reserved_ids": ["0001", "7fa2", "a491"],
    "tasks": {
        "7fa2": {
            "id": "7fa2",
            "kind": "TODO",
            "title": "Implement route poisoning",
            "description": "Support split horizon.",
            "status": "in_progress",
            "presence": "present",
            "priority": "high",
            "source": {"path": "src/rip.py", "line": 84, "symbol": "Router.send"},
            "history": [{"event": "created", "at": "2026-10-21T00:00:00Z"}],
        },
        "a491": {"id": "a491", "kind": "FIXME", "title": "ARP entries outlive interfaces", "presence": "missing"},
    },
}


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == f"byteplan {__version__}"


def test_no_command_prints_help(run_cli: RunCli) -> None:
    result = run_cli()
    assert result.code == EXIT_OK
    assert "usage: byteplan" in result.out


def test_init_creates_config_registry_and_sdist_exclude(project: ProjectFactory, run_cli: RunCli) -> None:
    result = run_cli("init", "--project", project.root)
    assert result.code == EXIT_OK
    pyproject = tomllib.loads((project.root / "pyproject.toml").read_text())
    assert pyproject["tool"]["byteplan"]["registry"] == ".byteplan/tasks.json"
    assert pyproject["tool"]["hatch"]["build"]["targets"]["sdist"]["exclude"] == [".byteplan"]
    assert json.loads((project.root / ".byteplan/tasks.json").read_text()) == {
        "schema_version": 1,
        "reserved_ids": [],
        "tasks": {},
    }
    assert "txn/" in (project.root / ".byteplan/.gitignore").read_text()


def test_init_is_idempotent(project: ProjectFactory, run_cli: RunCli) -> None:
    run_cli("init", "--project", project.root)
    before = project.snapshot()
    result = run_cli("init", "--project", project.root)
    assert result.code == EXIT_OK
    assert "already initialized" in result.out
    assert project.snapshot() == before


def test_init_preserves_crlf_pyproject(project: ProjectFactory, run_cli: RunCli) -> None:
    project.write("pyproject.toml", (project.root / "pyproject.toml").read_text().replace("\n", "\r\n"), dedent=False)
    run_cli("init", "--project", project.root)
    data = (project.root / "pyproject.toml").read_bytes()
    assert b"[tool.byteplan]\r\n" in data
    assert b"\n" not in data.replace(b"\r\n", b"")


def test_init_warns_when_existing_sdist_config_ships_registry(project: ProjectFactory, run_cli: RunCli) -> None:
    text = (project.root / "pyproject.toml").read_text() + '\n[tool.hatch.build.targets.sdist]\nexclude = ["docs"]\n'
    project.write("pyproject.toml", text, dedent=False)
    result = run_cli("init", "--project", project.root)
    assert result.code == EXIT_OK
    assert "warning" in result.err
    assert ".byteplan" in result.err


def test_init_on_corrupt_registry_fails(project: ProjectFactory, run_cli: RunCli) -> None:
    project.write(".byteplan/tasks.json", "{oops")
    result = run_cli("init", "--project", project.root)
    assert result.code == EXIT_ERROR
    assert "not valid JSON" in result.err


def test_scan_text_and_dry_run_do_not_write(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    project.write("src/rip.py", "# TODO: Implement route poisoning\n")
    before = project.snapshot()
    result = run_cli("scan", "--dry-run", "--project", project.root)
    assert result.code == EXIT_OK
    assert "1 file scanned" in result.out
    assert "Implement route poisoning" in result.out
    assert project.snapshot() == before


def test_scan_json_stdout_is_pure_json(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    project.write("a.py", "# TODO[beef]: unregistered\n# TODO: new\n")
    result = run_cli("scan", "--format", "json", "--project", project.root)
    payload = json.loads(result.out)
    assert payload["files_scanned"] == 1
    assert [p["title"] for p in payload["annotated"]] == ["new"]
    assert payload["diagnostics"][0]["code"] == "unregistered_id"
    assert "UNREGISTERED_ID" in result.err


def test_scan_duplicate_exit_code(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    project.write("a.py", "# TODO[beef]: one\n")
    project.write("b.py", "# TODO[beef]: two\n")
    result = run_cli("scan", "--project", project.root)
    assert result.code == EXIT_FINDINGS
    assert "DUPLICATE_ID" in result.err


def test_scan_parse_error_exit_code(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    project.write("bad.py", "def f(:\n")
    result = run_cli("scan", "--project", project.root)
    assert result.code == EXIT_ERROR
    assert "bad.py" in result.err
    assert result.out == ""


def test_scan_without_registry(project: ProjectFactory, run_cli: RunCli) -> None:
    result = run_cli("scan", "--project", project.root)
    assert result.code == EXIT_ERROR
    assert "byteplan init" in result.err


@pytest.fixture
def populated(project: ProjectFactory) -> ProjectFactory:
    project.init()
    project.write(".byteplan/tasks.json", json.dumps(REGISTRY))
    return project


def test_list(populated: ProjectFactory, run_cli: RunCli) -> None:
    result = run_cli("list", "--project", populated.root)
    lines = result.out.splitlines()
    assert lines[0].split() == ["ID", "STATUS", "PRESENCE", "KIND", "PRIORITY", "LOCATION", "TITLE"]
    assert lines[1].startswith("7fa2")
    assert "src/rip.py:84" in lines[1]
    assert lines[2].startswith("a491")


@pytest.mark.parametrize(
    ("args", "ids"),
    [
        (["--status", "in_progress"], ["7fa2"]),
        (["--status", "open"], ["a491"]),
        (["--presence", "missing"], ["a491"]),
        (["--kind", "fixme"], ["a491"]),
        (["--status", "open", "--status", "in_progress"], ["7fa2", "a491"]),
        (["--status", "blocked"], []),
    ],
)
def test_list_filters_json(populated: ProjectFactory, run_cli: RunCli, args: list[str], ids: list[str]) -> None:
    result = run_cli("list", "--format", "json", "--project", populated.root, *args)
    assert [task["id"] for task in json.loads(result.out)] == ids


def test_list_rejects_unknown_status(populated: ProjectFactory, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["list", "--status", "done", "--project", str(populated.root)])
    assert exc.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_show(populated: ProjectFactory, run_cli: RunCli) -> None:
    result = run_cli("show", "7FA2", "--project", populated.root)
    assert result.code == EXIT_OK
    assert "[7fa2] TODO: Implement route poisoning" in result.out
    assert "src/rip.py:84  (Router.send)" in result.out
    assert "created" in result.out


def test_show_json(populated: ProjectFactory, run_cli: RunCli) -> None:
    result = run_cli("show", "a491", "--format", "json", "--project", populated.root)
    assert json.loads(result.out)["title"] == "ARP entries outlive interfaces"


def test_show_unknown(populated: ProjectFactory, run_cli: RunCli) -> None:
    result = run_cli("show", "ffff", "--project", populated.root)
    assert result.code == EXIT_ERROR
    assert "no task with ID 'ffff'" in result.err
