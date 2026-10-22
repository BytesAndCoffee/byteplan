# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Phase 6b: `byteplan tests scaffold`. Addendum B §B8 tests 1-9, 11 (CLI) and 12."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from typing import TYPE_CHECKING, Any

import pytest

from byteplan import persistence
from byteplan.api import Project
from byteplan.cli import EXIT_ERROR, EXIT_OK
from byteplan.config import ScaffoldConfig
from byteplan.errors import EditError
from byteplan.models import AttachmentKind, SourceRef, Task
from byteplan.scaffold import (
    ScaffoldError,
    Target,
    default_name,
    ensure_only_added,
    is_placeholder,
    placeholder_nodes,
    snake,
    target_path,
)

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory, RunCli

PYPROJECT_DEV = (
    '[project]\nname = "demo"\nversion = "0.1"\n\n[project.optional-dependencies]\ndev = ["byteplan-runtime"]\n'
)

ROUTING = """\
import asyncio


class Router:
    # TODO: Implement poisoned reverse
    def advertise_routes(self):
        raise NotImplementedError

    # FIXME: Cache the table
    @property
    def table(self):
        return {}


# TODO: Async fetch
async def fetch():
    await asyncio.sleep(0)


# HACK: Plain function
def compute():
    return 1


# XXX: Whole class
class Empty:
    pass


# TODO: Module level work
VALUE = 1
"""


@pytest.fixture
def routed(project: ProjectFactory, run_cli: RunCli) -> ProjectFactory:
    project.write("pyproject.toml", PYPROJECT_DEV, dedent=False)
    project.init()
    project.write("src/pkg/routing.py", ROUTING)
    assert run_cli("scan", "--project", project.root).code == EXIT_OK
    return project


def task_by_title(project: ProjectFactory, title: str) -> dict[str, Any]:
    tasks = json.loads((project.root / ".byteplan/tasks.json").read_text())["tasks"]
    return next(t for t in tasks.values() if t["title"] == title)


def scaffold(project: ProjectFactory, run_cli: RunCli, task_id: str, *extra: str) -> dict[str, Any]:
    result = run_cli("tests", "scaffold", task_id, "--format", "json", "--project", project.root, *extra)
    assert result.code == EXIT_OK, result.err
    data: dict[str, Any] = json.loads(result.out)
    return data


def pytest_outcome(project: ProjectFactory, node: str) -> tuple[int, str]:
    """Run one node in a real pytest, with the inert runtime importable."""
    runtime = project.root / "rt/byteplan_runtime/__init__.py"
    runtime.parent.mkdir(parents=True, exist_ok=True)
    runtime.write_text("def verifies(*ids):\n    return lambda f: f\n\ndef todo(*a, **k):\n    return lambda f: f\n")
    env = {**os.environ, "PYTHONPATH": str(project.root / "rt")}
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:randomly", "-p", "no:cacheprovider", "-rA", node],
        cwd=project.root,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return done.returncode, done.stdout


# B1, B2: one discoverable, deliberately failing test, correctly bound ---------------------------


def test_scaffold_creates_a_failing_bound_test(routed: ProjectFactory, run_cli: RunCli) -> None:
    task = task_by_title(routed, "Implement poisoned reverse")
    data = scaffold(routed, run_cli, task["id"])
    node = "tests/test_routing.py::test_router_advertise_routes"
    assert data == {
        "id": task["id"],
        "node": node,
        "path": "tests/test_routing.py",
        "created_file": True,
        "existing": [],
        "dry_run": False,
        "written": ["tests/test_routing.py", ".byteplan/tasks.json"],
    }
    text = (routed.root / "tests/test_routing.py").read_text()
    assert text.startswith("import pytest\nfrom byteplan_runtime import verifies\n\n\n@verifies(")
    assert text.rstrip().endswith(f'pytest.fail("BytePlan {task["id"]}: acceptance test not implemented")')
    assert "# WHEN: TODO - exercise Router.advertise_routes (needs a Router instance; none is assumed)" in text

    registry = task_by_title(routed, "Implement poisoned reverse")
    assert registry["tests"]["discovered"] == [
        {"line": 5, "node": node, "path": "tests/test_routing.py", "provenance": "verifies"}
    ]
    assert registry["history"][-1]["event"] == "test_scaffolded"
    assert registry["history"][-1]["new"] == {"node": node, "path": "tests/test_routing.py", "policy": "fail"}

    # B8: the link is static and already reconciled; GIVEN/WHEN/THEN comments are not tasks.
    before = routed.snapshot()
    result = run_cli("scan", "--project", routed.root)
    assert "+0 added" in result.out
    assert routed.snapshot() == before
    pyproject = routed.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + "\n[tool.byteplan.check]\nrequire_reconciled = true\n")
    assert run_cli("check", "--project", routed.root).code == EXIT_OK

    code, out = pytest_outcome(routed, node)
    assert code == 1
    assert f"FAILED {node}" in out
    assert f"Failed: BytePlan {task['id']}: acceptance test not implemented" in out


@pytest.mark.parametrize(("policy", "expected"), [("xfail", "XFAIL"), ("skip", "SKIPPED")])
def test_policies_never_pass(routed: ProjectFactory, run_cli: RunCli, policy: str, expected: str) -> None:
    task = task_by_title(routed, "Plain function")
    data = scaffold(routed, run_cli, task["id"], "--policy", policy)
    _, out = pytest_outcome(routed, data["node"])
    assert expected in out
    assert "PASSED" not in out
    assert "XPASS" not in out


# B3: idempotent ---------------------------------------------------------------------------------


def test_rerun_reports_the_existing_test(routed: ProjectFactory, run_cli: RunCli) -> None:
    task = task_by_title(routed, "Plain function")
    first = scaffold(routed, run_cli, task["id"])
    before = routed.snapshot()
    again = run_cli("tests", "scaffold", task["id"], "--project", routed.root)
    assert again.code == EXIT_OK
    assert "already has linked tests; nothing written" in again.out
    assert first["node"] in again.out
    assert routed.snapshot() == before  # no file, link, event or timestamp

    forced = scaffold(routed, run_cli, task["id"], "--force-new")
    assert forced["node"] == f"tests/test_routing.py::test_compute_{task['id']}"


# B4: existing files are preserved ----------------------------------------------------------------


def test_appends_without_touching_existing_code(routed: ProjectFactory, run_cli: RunCli) -> None:
    existing = '"""Routing tests."""\r\n\r\nimport os\r\nimport pytest\r\n\r\n\r\ndef test_compute():\r\n    assert os'
    routed.write("tests/test_routing.py", existing.encode())
    task = task_by_title(routed, "Plain function")
    data = scaffold(routed, run_cli, task["id"])
    assert data["node"] == f"tests/test_routing.py::test_compute_{task['id']}"  # name collision avoided
    raw = (routed.root / "tests/test_routing.py").read_bytes()
    assert b"\n" not in raw.replace(b"\r\n", b"")  # CRLF kept
    text = raw.decode()
    assert text.startswith(
        '"""Routing tests."""\r\n\r\nimport os\r\nimport pytest\r\nfrom byteplan_runtime import verifies\r\n'
    )
    assert text.count("import pytest") == 1  # not duplicated
    assert "def test_compute():\r\n    assert os\r\n\r\n\r\n@verifies(" in text


def test_ast_guard_refuses_changes_to_existing_code() -> None:
    before = "import os\n\n\ndef test_a():\n    assert os\n"
    after = "import os\nimport pytest\n\n\ndef test_a():\n    assert True\n\n\ndef test_new():\n    pytest.fail('x')\n"
    with pytest.raises(EditError, match="would change existing code"):
        ensure_only_added("t.py", before, after, "test_new", ["import pytest"])


# B5, B6: safe templates per target kind -----------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "name", "comment"),
    [
        ("Implement poisoned reverse", "test_router_advertise_routes", "(needs a Router instance; none is assumed)"),
        ("Cache the table", "test_router_table", "(needs a Router instance; none is assumed)"),
        ("Plain function", "test_compute", "# WHEN: TODO - call compute"),
        ("Whole class", "test_empty", "# WHEN: TODO - exercise Empty's behaviour (constructing it isn't assumed)"),
        ("Module level work", "test_task_{id}", "# WHEN: TODO - exercise the code task {id} is about"),
        ("Async fetch", "test_fetch", "# WHEN: TODO - call fetch"),
    ],
)
def test_templates_by_target_kind(routed: ProjectFactory, run_cli: RunCli, title: str, name: str, comment: str) -> None:
    task = task_by_title(routed, title)
    data = scaffold(routed, run_cli, task["id"])
    text = (routed.root / "tests/test_routing.py").read_text()
    assert data["node"].endswith("::" + name.format(id=task["id"]))
    assert comment.format(id=task["id"]) in text
    assert f"def {name.format(id=task['id'])}():" in text  # synchronous, no invented fixtures or arguments
    assert "async def" not in text  # B6: no async plugin configured, so no async test that could skip
    tree = ast.parse(text)
    (function,) = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    assert is_placeholder(function)


def test_async_tests_only_with_a_plugin(project: ProjectFactory, run_cli: RunCli) -> None:
    project.write(
        "pyproject.toml", PYPROJECT_DEV + '\n[tool.byteplan.tests.scaffold]\nasync_tests = "anyio"\n', dedent=False
    )
    project.init()
    project.write("src/pkg/routing.py", ROUTING)
    assert run_cli("scan", "--project", project.root).code == EXIT_OK
    scaffold(project, run_cli, task_by_title(project, "Async fetch")["id"])
    text = (project.root / "tests/test_routing.py").read_text()
    assert "@pytest.mark.anyio\nasync def test_fetch():" in text
    assert "# WHEN: TODO - await fetch" in text


# B7: moves don't duplicate ----------------------------------------------------------------------


def test_line_shift_keeps_one_link(routed: ProjectFactory, run_cli: RunCli) -> None:
    task = task_by_title(routed, "Plain function")
    scaffold(routed, run_cli, task["id"])
    path = routed.root / "src/pkg/routing.py"
    path.write_text("\n\n\n" + path.read_text())
    test = routed.root / "tests/test_routing.py"
    test.write_text("\n\n" + test.read_text())
    assert run_cli("scan", "--project", routed.root).code == EXIT_OK
    after = task_by_title(routed, "Plain function")
    assert after["id"] == task["id"]
    assert len(after["tests"]["discovered"]) == 1
    assert run_cli("tests", "scaffold", task["id"], "--project", routed.root).out.count("already has linked tests") == 1


# B9: a placeholder is never ready ----------------------------------------------------------------


def test_placeholder_is_never_ready_until_implemented(routed: ProjectFactory, run_cli: RunCli) -> None:
    task = task_by_title(routed, "Plain function")
    node = scaffold(routed, run_cli, task["id"])["node"]
    check = run_cli("check", "--project", routed.root)
    assert "SCAFFOLD_PLACEHOLDER" in check.err
    project = Project.open(routed.root)
    state = project.readiness(project.get_task(task["id"]))
    assert state.state == "unverified"
    assert state.reasons == ("never verified",)

    # Implementing the body is all it takes to stop being a placeholder.
    test = routed.root / "tests/test_routing.py"
    test.write_text(
        test.read_text().replace(
            f'pytest.fail("BytePlan {task["id"]}: acceptance test not implemented")', "assert True"
        )
    )
    assert "SCAFFOLD_PLACEHOLDER" not in run_cli("check", "--project", routed.root).err
    assert node not in placeholder_nodes("tests/test_routing.py", test.read_text())


def test_verify_never_counts_a_placeholder(routed: ProjectFactory, run_cli: RunCli) -> None:
    task = task_by_title(routed, "Plain function")
    scaffold(routed, run_cli, task["id"], "--link", "managed", "--policy", "xfail")
    pyproject = routed.root / "pyproject.toml"
    runner = json.dumps([sys.executable, "-m", "pytest", "-p", "no:randomly"])
    pyproject.write_text(pyproject.read_text() + f"\n[tool.byteplan.tests]\nrunner = {runner}\n")
    result = run_cli("verify", task["id"], "--format", "json", "--project", routed.root)
    (verified,) = json.loads(result.out)["tasks"]
    assert verified["readiness"] == "needs_review"
    assert any("still a scaffold placeholder" in reason for reason in verified["reasons"])
    assert result.code == EXIT_OK  # xfailed isn't a failure... and isn't evidence either


# Paths, names, link styles -----------------------------------------------------------------------


def test_paths_and_ambiguity() -> None:
    config = ScaffoldConfig()
    task = Task(id="a83f", kind="TODO", title="t")
    assert target_path(task, config, []) == "tests/test_byteplan_tasks.py"
    task.source = SourceRef("src/pkg/routing.py", 3)
    assert target_path(task, config, ["src/pkg/routing.py"]) == "tests/test_routing.py"
    assert target_path(task, ScaffoldConfig(mirror=True), []) == "tests/pkg/test_routing.py"
    with pytest.raises(ScaffoldError, match="scaffold_needs_path"):
        target_path(task, config, ["src/pkg/routing.py", "src/other/routing.py"])
    task.source = SourceRef("src/pkg/__init__.py", 1)
    assert target_path(task, config, []) == "tests/test_pkg.py"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("advertise_routes", "advertise_routes"),
        ("HTTPServer", "http_server"),
        ("Router", "router"),
        ("getURL2", "get_url2"),
    ],
)
def test_snake_case(name: str, expected: str) -> None:
    assert snake(name) == expected


def test_default_names_skip_locals() -> None:
    task = Task(id="a83f", kind="TODO", title="t")
    assert default_name(task, Target(AttachmentKind.FUNCTION, "outer.<locals>.inner"), set()) == "test_outer_inner"
    assert default_name(task, Target(AttachmentKind.METHOD, "HTTPServer.get"), set()) == "test_http_server_get"
    assert default_name(task, Target(None, None), set()) == "test_task_a83f"


def test_name_collisions() -> None:
    task = Task(id="a83f", kind="TODO", title="t")
    target = Target(AttachmentKind.FUNCTION, "compute")
    assert default_name(task, target, set()) == "test_compute"
    assert default_name(task, target, {"test_compute"}) == "test_compute_a83f"
    assert default_name(task, target, {"test_compute", "test_compute_a83f"}) == "test_compute_a83f_2"


def test_explicit_path_and_name(routed: ProjectFactory, run_cli: RunCli) -> None:
    task = task_by_title(routed, "Plain function")
    data = scaffold(routed, run_cli, task["id"], "--path", "tests/acceptance.py", "--name", "test_it_computes")
    assert data["node"] == "tests/acceptance.py::test_it_computes"
    for bad in (["--name", "check_it"], ["--path", "../out.py"], ["--path", "notes.txt"]):
        result = run_cli("tests", "scaffold", task["id"], "--force-new", "--project", routed.root, *bad)
        assert result.code == EXIT_ERROR


def test_link_styles(routed: ProjectFactory, run_cli: RunCli) -> None:
    managed = task_by_title(routed, "Plain function")
    data = scaffold(routed, run_cli, managed["id"], "--link", "managed")
    assert task_by_title(routed, "Plain function")["tests"]["managed"] == [data["node"]]
    assert "@verifies" not in (routed.root / "tests/test_routing.py").read_text()

    marker = task_by_title(routed, "Whole class")
    result = run_cli("tests", "scaffold", marker["id"], "--link", "marker", "--project", routed.root)
    assert result.code == EXIT_ERROR
    assert "pytest_marker = true" in result.err
    pyproject = routed.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + "\n[tool.byteplan.tests]\npytest_marker = true\n")
    scaffold(routed, run_cli, marker["id"], "--link", "marker")
    assert f'@pytest.mark.byteplan("{marker["id"]}")' in (routed.root / "tests/test_routing.py").read_text()
    assert task_by_title(routed, "Whole class")["tests"]["discovered"][0]["provenance"] == "marker"


def test_runtime_unavailable(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    project.write("src/a.py", "# TODO: x\ndef f():\n    return 1\n")
    assert run_cli("scan", "--project", project.root).code == EXIT_OK
    task_id = next(iter(json.loads((project.root / ".byteplan/tasks.json").read_text())["tasks"]))
    result = run_cli("tests", "scaffold", task_id, "--project", project.root)
    assert result.code == EXIT_ERROR
    assert "runtime_unavailable" in result.err
    assert "--link managed" in result.err


def test_scaffold_path_must_be_in_scope(routed: ProjectFactory, run_cli: RunCli) -> None:
    pyproject = routed.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace('include = ["**/*.py"]', 'include = ["src/**/*.py"]'))
    result = run_cli("tests", "scaffold", task_by_title(routed, "Plain function")["id"], "--project", routed.root)
    assert result.code == EXIT_ERROR
    assert "isn't in the scan scope" in result.err


# B11: dry run changes nothing --------------------------------------------------------------------


def test_dry_run_writes_nothing(routed: ProjectFactory, run_cli: RunCli) -> None:
    before = routed.snapshot()
    result = run_cli(
        "tests", "scaffold", task_by_title(routed, "Plain function")["id"], "--dry-run", "--project", routed.root
    )
    assert result.code == EXIT_OK
    assert "would create tests/test_routing.py: tests/test_routing.py::test_compute" in result.out
    assert "pytest.fail(" in result.out
    assert routed.snapshot() == before


# B12: crash between the test file and the registry -----------------------------------------------


@pytest.mark.parametrize("nth", [1, 2])  # the test file, then the registry
def test_crash_recovers_through_the_journal(routed: ProjectFactory, monkeypatch: pytest.MonkeyPatch, nth: int) -> None:
    class CrashError(Exception):
        pass

    real_replace = os.replace
    calls = {"n": 0}

    def replace(src: Any, dst: Any) -> None:
        if not str(dst).endswith("journal.json"):
            calls["n"] += 1
            if calls["n"] == nth:
                raise CrashError
        real_replace(src, dst)

    task_id = task_by_title(routed, "Plain function")["id"]
    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(CrashError):
        Project.open(routed.root).scaffold_test(task_id)
    monkeypatch.undo()
    assert persistence.pending_journal(routed.root)

    # The next write command rolls the transaction forward: file and registry agree.
    Project.open(routed.root).scan(dry_run=False)
    assert not persistence.pending_journal(routed.root)
    assert "def test_compute():" in (routed.root / "tests/test_routing.py").read_text()
    task = task_by_title(routed, "Plain function")
    assert [e["node"] for e in task["tests"]["discovered"]] == ["tests/test_routing.py::test_compute"]
    assert task["history"][-1]["event"] == "test_scaffolded"


def test_placeholder_detection() -> None:
    text = (
        'import pytest\n\n\ndef test_a():\n    """doc"""\n    # comment\n    pytest.fail(\'x\')\n\n\n'
        "def test_b():\n    assert 1\n    pytest.fail('x')\n\n\nclass TestC:\n    def test_d(self):\n        pytest.fail('y')\n"
    )
    assert placeholder_nodes("t.py", text) == {"t.py::test_a", "t.py::TestC::test_d"}
    assert placeholder_nodes("t.py", "def broken(:\n") == set()
