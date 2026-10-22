# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Phase 6a (part 2): `byteplan verify`, evidence, freshness and readiness.

Addendum A §9 tests 11 (every pytest outcome, collection errors, timeouts and missing tests,
with no false passes) and 12 (revision-aware evidence and stale results). These run real
pytest subprocesses against small projects.
"""

from __future__ import annotations

import json
import shutil
import sys
from typing import TYPE_CHECKING, Any

import pytest

from byteplan.api import Project
from byteplan.cli import EXIT_FINDINGS, EXIT_OK
from byteplan.verification import _aggregate, _item_result
from tests.gitutil import git

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory, RunCli

CODE = """\
from byteplan_runtime import todo


@todo("Feature", id="a83f", tests=({tests}))
def feature():
    return 1
"""

OUTCOMES = """\
import time

import pytest


def test_pass():
    assert True


def test_fail():
    assert 1 == 2, "one is not two"


def test_skip():
    pytest.skip("not today")


@pytest.mark.xfail(reason="known")
def test_xfail():
    assert False


@pytest.mark.xfail(reason="known")
def test_xpass():
    assert True


@pytest.fixture
def broken():
    raise RuntimeError("fixture exploded")


def test_setup_error(broken):
    assert True


@pytest.mark.parametrize("n", [1, 2])
def test_param(n):
    assert n == 1


@pytest.mark.parametrize("n", [1, 2])
def test_param_ok(n):
    assert n


def test_slow():
    time.sleep(30)


class TestGroup:
    def test_a(self):
        assert True

    def test_b(self):
        assert True
"""


def make(project: ProjectFactory, run_cli: RunCli, nodes: list[str], tests: str = OUTCOMES, extra: str = "") -> None:
    project.init()
    pyproject = project.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + extra)
    project.write("src/feature.py", CODE.format(tests=", ".join(json.dumps(n) for n in nodes) + ","))
    project.write("tests/test_feature.py", tests)
    assert run_cli("repair", "--import", "a83f", "--project", project.root).code == EXIT_OK
    assert run_cli("scan", "--project", project.root).code == EXIT_OK


def verify(project: ProjectFactory, run_cli: RunCli, *args: str) -> tuple[int, dict[str, Any]]:
    result = run_cli("verify", *args, "--format", "json", "--project", project.root)
    return result.code, json.loads(result.out)


def outcomes(data: dict[str, Any]) -> dict[str, str]:
    (task,) = data["tasks"]
    return {node: r["outcome"] for node, r in task["tests"].items()}


F = "tests/test_feature.py"


def test_every_outcome_with_no_false_passes(project: ProjectFactory, run_cli: RunCli) -> None:
    nodes = [
        f"{F}::test_pass",
        f"{F}::test_fail",
        f"{F}::test_skip",
        f"{F}::test_xfail",
        f"{F}::test_xpass",
        f"{F}::test_setup_error",
        f"{F}::test_param",  # one parametrization fails -> failed
        f"{F}::test_param_ok",  # all pass -> passed
        f"{F}::test_param_ok[1]",  # a single parametrization
        f"{F}::TestGroup",  # a class covers its methods
        f"{F}::test_missing",
        "tests/test_gone.py::test_x",
    ]
    make(project, run_cli, nodes)
    code, data = verify(project, run_cli)
    assert code == EXIT_FINDINGS
    assert outcomes(data) == {
        f"{F}::test_pass": "passed",
        f"{F}::test_fail": "failed",
        f"{F}::test_skip": "skipped",
        f"{F}::test_xfail": "xfailed",
        f"{F}::test_xpass": "xpassed",
        f"{F}::test_setup_error": "error",
        f"{F}::test_param": "failed",
        f"{F}::test_param_ok": "passed",
        f"{F}::test_param_ok[1]": "passed",
        f"{F}::TestGroup": "passed",
        f"{F}::test_missing": "not_found",
        "tests/test_gone.py::test_x": "not_found",
    }
    (task,) = data["tasks"]
    assert task["readiness"] == "failing"
    assert "one is not two" in task["tests"][f"{F}::test_fail"]["message"]
    assert "fixture exploded" in task["tests"][f"{F}::test_setup_error"]["message"]
    # Nothing else in the file ran: test_slow (30 s) was deselected.
    assert task["tests"][f"{F}::test_pass"]["duration_ms"] < 10_000


def test_all_passing_is_ready_for_review_and_never_resolves(project: ProjectFactory, run_cli: RunCli) -> None:
    make(project, run_cli, [f"{F}::test_pass", f"{F}::TestGroup::test_a"])
    code, data = verify(project, run_cli)
    assert code == EXIT_OK
    assert data["tasks"][0]["readiness"] == "ready_for_review"
    assert run_cli("verify", "--ready", "--project", project.root).out.splitlines()[1].startswith("  [a83f] TODO")
    task = json.loads((project.root / ".byteplan/tasks.json").read_text())["tasks"]["a83f"]
    assert task["status"] == "open"  # readiness is advice; only a human resolves
    shown = run_cli("show", "a83f", "--project", project.root).out
    assert "readiness: ready_for_review" in shown
    assert f"{F}::test_pass  (decorator)  passed" in shown


def test_skips_and_xfails_need_review(project: ProjectFactory, run_cli: RunCli) -> None:
    make(project, run_cli, [f"{F}::test_pass", f"{F}::test_skip", f"{F}::test_xfail"])
    code, data = verify(project, run_cli)
    assert code == EXIT_OK  # nothing failed...
    task = data["tasks"][0]
    assert task["readiness"] == "needs_review"  # ...but nothing proves the work either
    assert f"{F}::test_skip: skipped" in task["reasons"]


def test_collection_error_is_an_error(project: ProjectFactory, run_cli: RunCli) -> None:
    make(project, run_cli, [f"{F}::test_pass"], tests="import not_a_module\n\n\ndef test_pass():\n    assert True\n")
    code, data = verify(project, run_cli)
    assert code == EXIT_FINDINGS
    (result,) = data["tasks"][0]["tests"].values()
    assert result["outcome"] == "error"
    assert "not_a_module" in result["message"]


def test_timeout_kills_the_run(project: ProjectFactory, run_cli: RunCli) -> None:
    # Fixed order (no pytest-randomly), so test_pass finishes before test_slow is killed.
    runner = json.dumps([sys.executable, "-m", "pytest", "-p", "no:randomly"])
    make(
        project,
        run_cli,
        [f"{F}::test_pass", f"{F}::test_slow"],
        extra=f"\n[tool.byteplan.tests]\ntimeout = 8\nrunner = {runner}\n",
    )
    code, data = verify(project, run_cli)
    assert code == EXIT_FINDINGS
    assert data["timed_out"] is True
    assert outcomes(data) == {f"{F}::test_pass": "passed", f"{F}::test_slow": "timeout"}
    assert data["tasks"][0]["readiness"] == "failing"


def test_broken_runner_is_not_run_not_passed(project: ProjectFactory, run_cli: RunCli) -> None:
    runner = json.dumps([sys.executable, "-c", "raise SystemExit(3)"])
    make(project, run_cli, [f"{F}::test_pass"], extra=f"\n[tool.byteplan.tests]\nrunner = {runner}\n")
    code, data = verify(project, run_cli)
    assert code == EXIT_FINDINGS
    assert outcomes(data) == {f"{F}::test_pass": "not_run"}


def test_missing_runner_is_an_error(project: ProjectFactory, run_cli: RunCli) -> None:
    make(project, run_cli, [f"{F}::test_pass"], extra='\n[tool.byteplan.tests]\nrunner = ["no-such-runner-xyz"]\n')
    result = run_cli("verify", "--project", project.root)
    assert result.code != EXIT_OK
    assert "can't start the test runner 'no-such-runner-xyz'" in result.err


def test_evidence_store_and_staleness(project: ProjectFactory, run_cli: RunCli) -> None:
    make(project, run_cli, [f"{F}::test_pass"])
    assert verify(project, run_cli)[0] == EXIT_OK
    store = json.loads((project.root / ".byteplan/verification.json").read_text())
    entry = store["tasks"]["a83f"]
    assert entry["tests"] == {
        f"{F}::test_pass": {"outcome": "passed", "duration_ms": entry["tests"][f"{F}::test_pass"]["duration_ms"]}
    }
    run = store["runs"][entry["run"]]
    assert run["argv"][-2:] == ["-p", "_byteplan_verify_plugin"]
    assert run["python"]
    assert run["at"]

    project_obj = Project.open(project.root)
    task = project_obj.get_task("a83f")
    assert project_obj.readiness(task).state == "ready_for_review"
    # Editing the task's source or a linked test file makes the evidence stale.
    path = project.root / "tests/test_feature.py"
    path.write_text(path.read_text() + "\n# touched\n")
    state = project_obj.readiness(task)
    assert state.state == "needs_review"
    assert state.tests == {f"{F}::test_pass": "stale"}
    assert any("stale" in reason for reason in state.reasons)
    # An unrelated file doesn't.
    path.write_text(path.read_text().replace("\n# touched\n", ""))
    project.write("src/other.py", "x = 1\n")
    assert project_obj.readiness(task).state == "ready_for_review"


def test_stale_on_head(project: ProjectFactory, run_cli: RunCli) -> None:
    if shutil.which("git") is None:
        pytest.skip("git not installed")
    make(project, run_cli, [f"{F}::test_pass"], extra='\n[tool.byteplan.tests]\nstale_on = "head"\n')
    root = project.root
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "T")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    assert verify(project, run_cli)[0] == EXIT_OK
    git(root, "add", "-A")
    git(root, "commit", "-qm", "evidence")  # HEAD moves after the run
    assert Project.open(root).readiness(Project.open(root).get_task("a83f")).state == "needs_review"


def test_stub_declaration_needs_review(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    project.write("tests/test_feature.py", "def test_pass():\n    assert True\n")
    project.write(
        "src/feature.py", "def feature():\n    # TODO: Implement\n    #   linked\n    raise NotImplementedError\n"
    )
    assert run_cli("scan", "--project", project.root).code == EXIT_OK
    task_id = next(iter(json.loads((project.root / ".byteplan/tasks.json").read_text())["tasks"]))
    assert run_cli("tests", "add", task_id, f"{F}::test_pass", "--project", project.root).code == EXIT_OK
    code, data = verify(project, run_cli)
    assert code == EXIT_OK
    assert data["tasks"][0]["readiness"] == "needs_review"
    assert "the declaration is still a stub" in data["tasks"][0]["reasons"]

    # Implementing the stub with passing tests is a completion candidate, still not resolved.
    source = project.root / "src/feature.py"
    source.write_text(source.read_text().replace("raise NotImplementedError", "return 1"))
    assert run_cli("verify", "--project", project.root).code == EXIT_OK  # fresh evidence for the new file
    result = run_cli("scan", "--project", project.root)
    assert "IMPLEMENTATION_COMPLETE_CANDIDATE" in result.err
    assert json.loads((project.root / ".byteplan/tasks.json").read_text())["tasks"][task_id]["status"] == "open"


def test_unverified_and_nothing_to_run(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    project.write("src/a.py", "# TODO: no tests\nx = 1\n")
    assert run_cli("scan", "--project", project.root).code == EXIT_OK
    result = run_cli("verify", "--project", project.root)
    assert result.code == EXIT_OK
    assert "no linked tests to run" in result.out
    task_id = next(iter(json.loads((project.root / ".byteplan/tasks.json").read_text())["tasks"]))
    assert "readiness: unverified" in run_cli("show", task_id, "--project", project.root).out
    assert run_cli("verify", "--ready", "--project", project.root).out.strip() == "No tasks are ready for review."


def test_only_named_tasks_run(project: ProjectFactory, run_cli: RunCli) -> None:
    make(project, run_cli, [f"{F}::test_pass"])
    project.write("src/other.py", "# TODO: other\n#   x\nx = 1\n")
    assert run_cli("scan", "--project", project.root).code == EXIT_OK
    _, data = verify(project, run_cli, "a83f")
    assert [t["id"] for t in data["tasks"]] == ["a83f"]


# Aggregation units -----------------------------------------------------------------------------


def test_item_result_phases() -> None:
    def rec(when: str, outcome: str, **extra: Any) -> dict[str, Any]:
        return {"node": "n", "when": when, "outcome": outcome, "duration": 0.001, **extra}

    assert (
        _item_result([rec("setup", "passed"), rec("call", "passed"), rec("teardown", "failed", message="td")]).outcome
        == "error"
    )
    assert _item_result([rec("setup", "passed")]).outcome == "not_run"
    assert (
        _item_result([rec("setup", "passed"), rec("call", "passed", xfail=True), rec("teardown", "passed")]).outcome
        == "xpassed"
    )


def test_partial_results_after_a_crash() -> None:
    records: list[dict[str, Any]] = [{"matched": {"f.py::a": ["f.py::a"], "f.py::b": ["f.py::b"]}}]
    records += [
        {"node": "f.py::a", "when": w, "outcome": "passed", "duration": 0} for w in ("setup", "call", "teardown")
    ]
    results = _aggregate(["f.py::a", "f.py::b"], records, timed_out=False, returncode=-9)
    assert results["f.py::a"].outcome == "passed"
    assert results["f.py::b"].outcome == "not_run"  # never a pass by omission
