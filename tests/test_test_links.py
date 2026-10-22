# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Phase 6a (part 1): acceptance-test links, their provenance, and `byteplan tests`.

Addendum A §9 test 9: source-declared and registry-managed links, several tests per task,
tests shared between tasks, and provenance kept per link.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from byteplan.api import is_node_id
from byteplan.cli import EXIT_ERROR, EXIT_FINDINGS, EXIT_OK
from byteplan.errors import RegistryError
from byteplan.merge import merge_registries
from byteplan.registry import dumps, loads

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory, RunCli

ROUTER = """\
from byteplan_runtime import todo


@todo("Route poisoning", id="a83f", tests=("tests/test_r.py::test_poison", "tests/test_r.py::TestR::test_split"))
def poison():
    return 1


@todo("Withdraw", id="b001", test="tests/test_r.py::test_poison")
def withdraw():
    return 2


@todo("Nothing linked", id="c002")
def other():
    return 3
"""

TESTS = """\
from byteplan_runtime import verifies


@verifies("a83f")
def test_poison():
    assert True


class TestR:
    @verifies("a83f", "b001")
    def test_split(self):
        assert True
"""


def registry_of(project: ProjectFactory) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((project.root / ".byteplan/tasks.json").read_text())
    return data


def register(project: ProjectFactory, run_cli: RunCli) -> None:
    """Import the hand-written IDs (they're in source, not yet registered)."""
    for task_id in ("a83f", "b001", "c002"):
        assert run_cli("repair", "--import", task_id, "--project", project.root).code == EXIT_OK
    assert run_cli("scan", "--project", project.root).code == EXIT_OK


@pytest.fixture
def linked(project: ProjectFactory, run_cli: RunCli) -> ProjectFactory:
    project.init()
    project.write("src/r.py", ROUTER)
    project.write("tests/test_r.py", TESTS)
    register(project, run_cli)
    return project


def test_links_from_source_with_provenance(linked: ProjectFactory, run_cli: RunCli) -> None:
    tasks = registry_of(linked)["tasks"]
    assert tasks["a83f"]["tests"] == {
        "managed": [],
        "discovered": [
            {"line": 4, "node": "tests/test_r.py::TestR::test_split", "path": "src/r.py", "provenance": "decorator"},
            {
                "line": 10,
                "node": "tests/test_r.py::TestR::test_split",
                "path": "tests/test_r.py",
                "provenance": "verifies",
            },
            {"line": 4, "node": "tests/test_r.py::test_poison", "path": "src/r.py", "provenance": "decorator"},
            {"line": 4, "node": "tests/test_r.py::test_poison", "path": "tests/test_r.py", "provenance": "verifies"},
        ],
    }
    # A shared test: test_split verifies two tasks, test_poison is linked to both by decorators.
    assert [e["node"] for e in tasks["b001"]["tests"]["discovered"]] == [
        "tests/test_r.py::TestR::test_split",
        "tests/test_r.py::test_poison",
    ]
    assert "tests" not in tasks["c002"]  # omitted when empty: no churn for test-less tasks

    out = run_cli("tests", "list", "a83f", "--project", linked.root).out
    assert "tests/test_r.py::TestR::test_split  decorator, verifies" in out
    rows = json.loads(run_cli("tests", "list", "--format", "json", "--project", linked.root).out)
    assert {(r["id"], r["node"]) for r in rows} == {
        ("a83f", "tests/test_r.py::TestR::test_split"),
        ("a83f", "tests/test_r.py::test_poison"),
        ("b001", "tests/test_r.py::TestR::test_split"),
        ("b001", "tests/test_r.py::test_poison"),
    }
    shown = run_cli("show", "a83f", "--project", linked.root).out
    assert "  tests:\n    tests/test_r.py::TestR::test_split  (decorator, verifies)" in shown


def test_removing_a_link_from_source_drops_it(linked: ProjectFactory, run_cli: RunCli) -> None:
    linked.write("tests/test_r.py", TESTS.replace('@verifies("a83f", "b001")', '@verifies("a83f")'))
    assert run_cli("scan", "--project", linked.root).code == EXIT_OK
    provenances = {(e["node"], e["provenance"]) for e in registry_of(linked)["tasks"]["b001"]["tests"]["discovered"]}
    assert ("tests/test_r.py::TestR::test_split", "verifies") not in provenances
    assert ("tests/test_r.py::test_poison", "decorator") in provenances


def test_narrowed_scan_keeps_links_from_other_paths(linked: ProjectFactory, run_cli: RunCli) -> None:
    before = registry_of(linked)["tasks"]["a83f"]["tests"]
    assert run_cli("scan", linked.root / "src", "--project", linked.root).code == EXIT_OK
    assert registry_of(linked)["tasks"]["a83f"]["tests"] == before  # the @verifies entries survive


def test_managed_links(linked: ProjectFactory, run_cli: RunCli) -> None:
    root = linked.root
    result = run_cli(
        "tests", "add", "c002", "tests/test_r.py::test_poison", "tests/test_r.py::test_extra", "--project", root
    )
    assert result.code == EXIT_OK
    assert "[c002] linked" in result.out
    assert (
        run_cli("tests", "add", "c002", "tests/test_r.py::test_extra", "--project", root)
        .out.strip()
        .endswith("unchanged")
    )
    task = registry_of(linked)["tasks"]["c002"]
    assert task["tests"]["managed"] == ["tests/test_r.py::test_extra", "tests/test_r.py::test_poison"]
    assert [(e["event"], e["new"]) for e in task["history"][-2:]] == [
        ("test_linked", "tests/test_r.py::test_poison"),
        ("test_linked", "tests/test_r.py::test_extra"),
    ]
    assert run_cli("scan", "--project", root).code == EXIT_OK
    assert registry_of(linked)["tasks"]["c002"]["tests"]["managed"] == task["tests"]["managed"]  # scans never touch it

    assert run_cli("tests", "remove", "c002", "tests/test_r.py::test_extra", "--project", root).code == EXIT_OK
    task = registry_of(linked)["tasks"]["c002"]
    assert task["tests"]["managed"] == ["tests/test_r.py::test_poison"]
    assert task["history"][-1]["event"] == "test_unlinked"


def test_managed_and_discovered_combine(linked: ProjectFactory, run_cli: RunCli) -> None:
    assert run_cli("tests", "add", "a83f", "tests/test_r.py::test_poison", "--project", linked.root).code == EXIT_OK
    out = run_cli("tests", "list", "a83f", "--project", linked.root).out
    assert "tests/test_r.py::test_poison        decorator, managed, verifies" in out


def test_source_links_can_only_be_removed_in_source(linked: ProjectFactory, run_cli: RunCli) -> None:
    result = run_cli("tests", "remove", "a83f", "tests/test_r.py::test_poison", "--project", linked.root)
    assert result.code == EXIT_ERROR
    assert "declared in source, so remove it there" in result.err


@pytest.mark.parametrize(
    "node", ["test_poison", "tests/test_r.py", "tests/test_r.py::", "tests/t.txt::test_x", "a b.py::"]
)
def test_add_rejects_malformed_node_ids(linked: ProjectFactory, run_cli: RunCli, node: str) -> None:
    result = run_cli("tests", "add", "c002", node, "--project", linked.root)
    assert result.code == EXIT_ERROR
    assert "not a pytest node ID" in result.err


@pytest.mark.parametrize(
    ("node", "valid"),
    [
        ("tests/test_x.py::test_a", True),
        ("tests/test_x.py::TestA::test_b", True),
        ("tests/test_x.py::test_a[1-2]", True),
        ("test_x.py::test_a[a::b]", True),
        ("tests/test_x.py", False),
        ("test_a", False),
        ("tests/test_x.py::1bad", False),
        ("tests/test_x.py::test_a[1]::x", False),
    ],
)
def test_node_id_grammar(node: str, valid: bool) -> None:  # noqa: FBT001 - pytest parameter
    assert is_node_id(node) is valid


def test_malformed_and_dynamic_decorator_tests(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    project.write(
        "src/a.py",
        """\
        from byteplan_runtime import todo

        NODES = ("tests/t.py::t",)


        @todo("Bad", tests=("not a node",))
        def f():
            return 1


        @todo("Dynamic", tests=NODES)
        def g():
            return 2
        """,
    )
    result = run_cli("scan", "--project", project.root)
    assert result.code == EXIT_OK
    assert "MALFORMED_TEST_ID" in result.err
    assert "tests on g are not string literals; they aren't linked" in result.err
    assert all("tests" not in task for task in registry_of(project)["tasks"].values())


def test_test_not_in_scope(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    pyproject = project.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace('include = ["**/*.py"]', 'include = ["src/**/*.py"]'))
    project.write("src/a.py", ROUTER.replace("tests/test_r.py::TestR::test_split", "tests/gone.py::test_x"))
    project.write("tests/test_r.py", TESTS)
    for task_id in ("a83f", "b001", "c002"):
        run_cli("repair", "--import", task_id, "--project", project.root)
    err = run_cli("scan", "--project", project.root).err
    assert "task a83f links tests/gone.py::test_x, but tests/gone.py doesn't exist" in err
    assert "task a83f links tests/test_r.py::test_poison, but tests/test_r.py isn't in the scan scope" in err


def test_pytest_marker_links_are_opt_in(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    project.write("src/r.py", ROUTER)
    project.write(
        "tests/test_m.py",
        """\
        import pytest
        from pytest import mark as m


        @pytest.mark.byteplan("c002")
        def test_one():
            assert True


        @m.byteplan("c002", "nope")
        def test_two():
            assert True
        """,
    )
    register(project, run_cli)
    assert "tests" not in registry_of(project)["tasks"]["c002"]
    pyproject = project.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + "\n[tool.byteplan.tests]\npytest_marker = true\n")
    assert run_cli("scan", "--project", project.root).code == EXIT_OK
    entries = registry_of(project)["tasks"]["c002"]["tests"]["discovered"]
    assert {(e["node"], e["provenance"]) for e in entries} == {
        ("tests/test_m.py::test_one", "marker"),
        ("tests/test_m.py::test_two", "marker"),
    }


def test_unscanned_link_changes_are_out_of_sync(linked: ProjectFactory, run_cli: RunCli) -> None:
    pyproject = linked.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + "\n[tool.byteplan.check]\nrequire_reconciled = true\n")
    assert run_cli("check", "--project", linked.root).code == EXIT_OK
    linked.write("tests/test_r.py", TESTS + '\n\n@verifies("c002")\ndef test_new():\n    assert True\n')
    result = run_cli("check", "--format", "json", "--project", linked.root)
    assert result.code == EXIT_FINDINGS
    (diag,) = [d for d in json.loads(result.out)["diagnostics"] if d["code"] == "registry_out_of_sync"]
    assert "test links" in diag["message"]


def test_registry_round_trip_and_validation() -> None:
    task = {
        "id": "a83f",
        "kind": "TODO",
        "title": "t",
        "tests": {
            "managed": ["t.py::a"],
            "discovered": [{"node": "t.py::b", "provenance": "verifies", "path": "t.py", "line": 3}],
        },
    }
    text = json.dumps({"schema_version": 1, "reserved_ids": ["a83f"], "tasks": {"a83f": task}})
    assert dumps(loads(dumps(loads(text)))) == dumps(loads(text))
    assert json.loads(dumps(loads(text)))["tasks"]["a83f"]["tests"] == task["tests"]
    bad_values: list[Any] = [{"managed": "x"}, {"discovered": [{"node": "x"}]}, []]
    for bad in bad_values:
        broken = json.dumps({"schema_version": 1, "reserved_ids": ["a83f"], "tasks": {"a83f": {**task, "tests": bad}}})
        with pytest.raises(RegistryError, match="tests"):
            loads(broken)


def _merge_task(base: Any, ours: Any, theirs: Any) -> Any:
    def reg(tests: Any) -> dict[str, Any]:
        task: dict[str, Any] = {"id": "a83f", "kind": "TODO", "title": "t", "history": []}
        if tests is not None:
            task["tests"] = tests
        return {"schema_version": 1, "reserved_ids": ["a83f"], "tasks": {"a83f": task}}

    return merge_registries(reg(base), reg(ours), reg(theirs))


def test_merge_managed_links_as_a_set() -> None:
    base = {"managed": ["t.py::a", "t.py::b"], "discovered": []}
    ours = {"managed": ["t.py::a", "t.py::c"], "discovered": []}
    theirs = {"managed": ["t.py::a", "t.py::b", "t.py::d"], "discovered": []}
    result = _merge_task(base, ours, theirs)
    assert result.data is not None
    assert result.data["tasks"]["a83f"]["tests"] == {"managed": ["t.py::a", "t.py::c", "t.py::d"], "discovered": []}


def test_merge_discovered_links_flags_a_rescan() -> None:
    entry = {"node": "t.py::x", "provenance": "verifies", "path": "t.py", "line": 1}
    result = _merge_task(
        None,
        {"managed": [], "discovered": [entry]},
        {"managed": [], "discovered": [{**entry, "line": 9}]},
    )
    assert result.data is not None
    assert result.data["tasks"]["a83f"]["tests"]["discovered"] == [entry]
    assert result.rescan_needed == ["a83f"]
    emptied = _merge_task({"managed": ["t.py::a"], "discovered": []}, None, {"managed": ["t.py::a"], "discovered": []})
    assert emptied.data is not None
    assert "tests" not in emptied.data["tasks"]["a83f"]
