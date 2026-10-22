# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Static @todo / @verifies discovery and decorator ID allocation (Addendum A 1, 2, 7, 19)."""

from __future__ import annotations

import ast
import json
import textwrap
from typing import TYPE_CHECKING, Any

import pytest

from byteplan.api import Project
from byteplan.config import DetectConfig
from byteplan.diagnostics import Code
from byteplan.models import AttachmentKind, Origin, Representation
from byteplan.scanner import FileScan, scan_file
from byteplan.scanner.source import decode_source

if TYPE_CHECKING:
    from tests.conftest import FakeClock, ProjectFactory

NO_STUBS = DetectConfig(pass_stubs=False, ellipsis_stubs=False, not_implemented_stubs=False, empty_classes=False)


def scan(code: str, runtime_modules: tuple[str, ...] = ("byteplan_runtime",)) -> FileScan:
    return scan_file(decode_source("mod.py", textwrap.dedent(code).encode()), NO_STUBS, runtime_modules)


def titles(code: str, **kwargs: Any) -> list[str]:
    return [a.title for a in scan(code, **kwargs).tags if a.representation is Representation.DECORATOR]


# Name resolution -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "from byteplan_runtime import todo\n@todo('t')\ndef f(): return 1\n",
        "from byteplan_runtime import todo as plan\n@plan('t')\ndef f(): return 1\n",
        "import byteplan_runtime\n@byteplan_runtime.todo('t')\ndef f(): return 1\n",
        "import byteplan_runtime as br\n@br.todo('t')\nclass C: x = 1\n",
        "try:\n    from byteplan_runtime import todo\nexcept ImportError:\n    pass\n@todo('t')\ndef f(): return 1\n",
        "from byteplan_runtime import todo\nclass C:\n    @todo('t')\n    async def m(self): return 1\n",
    ],
    ids=["direct", "alias", "module", "module-alias-class", "in-try", "async-method"],
)
def test_recognized(code: str) -> None:
    assert titles(code) == ["t"]


@pytest.mark.parametrize(
    "code",
    [
        "def todo(x):\n    return lambda f: f\n@todo('t')\ndef f(): return 1\n",
        "from somewhere import todo\n@todo('t')\ndef f(): return 1\n",
        "@todo('t')\ndef f(): return 1\n",
    ],
    ids=["local-function", "other-module", "unbound"],
)
def test_unrelated_todo_is_ignored(code: str) -> None:
    result = scan(code)
    assert result.tags == []
    assert result.diagnostics == []


@pytest.mark.parametrize(
    "code",
    [
        "from byteplan_runtime import todo\ntodo = None\n@todo('t')\ndef f(): return 1\n",
        "from byteplan_runtime import todo\nfrom other import todo\n@todo('t')\ndef f(): return 1\n",
        "from byteplan_runtime import *\n@todo('t')\ndef f(): return 1\n",
    ],
    ids=["rebound", "imported-twice", "star-import"],
)
def test_ambiguous_names_are_reported_not_tracked(code: str) -> None:
    result = scan(code)
    assert result.tags == []
    assert [d.code for d in result.diagnostics] == [Code.UNRESOLVED_TODO_DECORATOR]


def test_project_shim_module() -> None:
    code = "import myproj._plan as p\n@p.todo('t')\ndef f(): return 1\n"
    assert titles(code) == []
    assert titles(code, runtime_modules=("myproj._plan",)) == ["t"]


# Arguments --------------------------------------------------------------------------------


def test_fields_and_attachment() -> None:
    code = """
    from byteplan_runtime import todo

    class Router:
        @staticmethod
        @todo("Implement routes", id="a83f", kind="fixme", description="Split horizon.", tests=("t.py::t",))
        def advertise(): return 1
    """
    (annotation,) = scan(code).tags
    assert (annotation.task_id, annotation.kind, annotation.title) == ("a83f", "FIXME", "Implement routes")
    assert annotation.description == "Split horizon."
    assert (annotation.symbol, annotation.attachment_kind) == ("Router.advertise", AttachmentKind.METHOD)
    assert (annotation.origin, annotation.id_slot) == (Origin.DECORATOR, None)
    assert annotation.decl_line == 7


def test_stacked_todos_are_independent_tasks() -> None:
    code = "from byteplan_runtime import todo\n@todo('one')\n@todo('two')\ndef f(): return 1\n"
    assert titles(code) == ["one", "two"]


@pytest.mark.parametrize(
    ("call", "code"),
    [
        ("@todo", Code.INVALID_TODO_DECORATOR),
        ("@todo()", Code.INVALID_TODO_DECORATOR),
        ("@todo('t', 'extra')", Code.INVALID_TODO_DECORATOR),
        ("@todo('t', owner='me')", Code.INVALID_TODO_DECORATOR),
        ("@todo(TITLE)", Code.DYNAMIC_TODO_ARGUMENT),
        ("@todo('t', id=make_id())", Code.DYNAMIC_TODO_ARGUMENT),
        ("@todo('t', id='XYZ1')", Code.MALFORMED_ID),
        ("@todo('t', id='a83f', test='a::b', tests=('c::d',))", Code.CONFLICTING_TEST_ARGUMENTS),
        ("@todo('t', kind='NOTE')", Code.INVALID_TODO_DECORATOR),
    ],
)
def test_argument_diagnostics(call: str, code: Code) -> None:
    result = scan(f"from byteplan_runtime import todo\n{call}\ndef f(): return 1\n")
    assert code in [d.code for d in result.diagnostics]


def test_dynamic_title_with_literal_id_stays_tracked() -> None:
    result = scan("from byteplan_runtime import todo\n@todo(TITLE, id='a83f')\ndef f(): return 1\n")
    assert [a.task_id for a in result.tags] == ["a83f"]
    assert [d.code for d in result.diagnostics] == [Code.DYNAMIC_TODO_ARGUMENT]


def test_verifies_links() -> None:
    code = """
    from byteplan_runtime import verifies

    @verifies("a83f", "beef")
    def test_a(): pass

    class TestRouting:
        @verifies("a83f")
        def test_b(self): pass

    @verifies("NOPE")
    def test_c(): pass
    """
    result = scan_file(decode_source("tests/test_r.py", textwrap.dedent(code).encode()), NO_STUBS)
    assert [(link.task_ids, link.node_id) for link in result.links] == [
        (("a83f", "beef"), "tests/test_r.py::test_a"),
        (("a83f",), "tests/test_r.py::TestRouting::test_b"),
    ]
    assert [d.code for d in result.diagnostics] == [Code.MALFORMED_ID]


# ID allocation into decorators (end to end) -----------------------------------------------


def write_scan(project: ProjectFactory, clock: FakeClock) -> Any:
    return Project.open(project.root, clock=clock).scan(dry_run=False)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ('@todo("Plan")\n', '@todo("Plan", id="{id}")\n'),
        ('@todo("Plan",)\n', '@todo("Plan", id="{id}",)\n'),
        ('@todo("Plan", kind="FIXME")  # why\n', '@todo("Plan", kind="FIXME", id="{id}")  # why\n'),
        ('@todo(\n    "Plan"\n)\n', '@todo(\n    "Plan",\n    id="{id}"\n)\n'),
        (
            '@todo(\n    "Plan",\n    tests=("t::t",),\n)\n',
            '@todo(\n    "Plan",\n    tests=("t::t",),\n    id="{id}",\n)\n',
        ),
        ('@todo("Implicit "\n      "concat")\n', '@todo("Implicit "\n      "concat", id="{id}")\n'),
    ],
    ids=["simple", "trailing-comma", "comment-after", "multiline", "multiline-trailing-comma", "implicit-concat"],
)
def test_id_is_written_into_the_decorator(project: ProjectFactory, clock: FakeClock, before: str, after: str) -> None:
    project.init()
    header = "from byteplan_runtime import todo\n\n\n"
    body = "def f():\n    return 1\n"
    path = project.write("a.py", header + before + body, dedent=False)
    report = write_scan(project, clock)
    (task_id,) = [p.task_id for p in report.proposals]
    assert path.read_text() == header + after.replace("{id}", task_id) + body
    ast.parse(path.read_text())
    assert write_scan(project, clock).written == ()


def test_parenthesized_title_is_refused_not_turned_into_a_tuple(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    code = 'from byteplan_runtime import todo\n@todo(("Plan"))\ndef f():\n    return 1\n'
    path = project.write("a.py", code, dedent=False)
    report = write_scan(project, clock)
    assert [d.code for d in report.diagnostics] == [Code.DECORATOR_NEEDS_REVIEW]
    assert path.read_text() == code


def test_decorator_task_keeps_id_across_rename_and_move(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    path = project.write("src/a.py", "from byteplan_runtime import todo\n@todo('Plan')\ndef f():\n    return 1\n")
    write_scan(project, clock)
    tagged = path.read_text()
    path.unlink()
    project.write("src/b.py", "import os\n" + tagged.replace("def f", "def g"), dedent=False)
    write_scan(project, clock)
    tasks = json.loads((project.root / ".byteplan/tasks.json").read_text())["tasks"]
    (task,) = tasks.values()
    assert (task["source"]["path"], task["source"]["symbol"]) == ("src/b.py", "g")
    assert task["source"]["representation"] == "decorator"
    assert task["origin"] == "decorator"
    assert task["history"][-1]["event"] == "moved"


def test_mixed_comment_and_decorator_duplicate_is_detected(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    path = project.write("a.py", "from byteplan_runtime import todo\n@todo('Plan')\ndef f():\n    return 1\n")
    write_scan(project, clock)
    task_id = json.loads((project.root / ".byteplan/tasks.json").read_text())["reserved_ids"][0]
    project.write("b.py", f"# TODO[{task_id}]: copy\n")
    report = Project.open(project.root, clock=clock).scan(dry_run=True)
    assert Code.DUPLICATE_ID in [d.code for d in report.diagnostics]
    assert path.exists()


# Stubs end to end (spec 4; Addendum A 6, 7) --------------------------------------------------


def test_stub_annotation_and_implementation_advisory(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    path = project.write(
        "src/r.py",
        """\
        class Router:
            # keep this comment
            @property
            def table(self):
                raise NotImplementedError
        """,
    )
    report = write_scan(project, clock)
    (task_id,) = [p.task_id for p in report.proposals]
    assert path.read_text() == textwrap.dedent(f"""\
        class Router:
            # keep this comment
            # TODO[{task_id}]: Implement Router.table (detected stub)
            @property
            def table(self):
                raise NotImplementedError
        """)
    registry = json.loads((project.root / ".byteplan/tasks.json").read_text())
    task = registry["tasks"][task_id]
    assert task["origin"] == "stub"
    assert task["stub"] == {"symbol": "Router.table", "implemented": False}
    assert task["source"]["line"] == 3
    assert write_scan(project, clock).written == ()  # idempotent after the inserted line

    path.write_text(path.read_text().replace("raise NotImplementedError", "return {}"))
    report = write_scan(project, clock)
    assert [d.code for d in report.diagnostics] == [Code.IMPLEMENTATION_CHANGED]
    task = json.loads((project.root / ".byteplan/tasks.json").read_text())["tasks"][task_id]
    assert (task["status"], task["presence"]) == ("open", "present")  # never auto-resolved
    assert task["stub"]["implemented"] is True
    assert [e["event"] for e in task["history"]] == ["created", "implementation_changed"]
    assert [d.code for d in write_scan(project, clock).diagnostics] == []  # advisory only once


def test_stub_scan_is_annotated_once_per_obligation(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    project.write("a.py", "# TODO: write f\ndef f():\n    pass\n\ndef g():\n    pass\n")
    report = write_scan(project, clock)
    assert sorted(p.tag.title for p in report.proposals) == ["Implement g (detected stub)", "write f"]
    assert write_scan(project, clock).proposals == ()


def test_unknown_verifies_reference_is_reported(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    project.write(
        "tests/test_a.py", "from byteplan_runtime import verifies\n@verifies('beef')\ndef test_a():\n    assert 1\n"
    )
    report = write_scan(project, clock)
    assert [d.code for d in report.diagnostics] == [Code.UNKNOWN_TASK_REFERENCE]


# Codex review of PR #6 ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "inner",
    [
        "def outer(todo):\n    @todo('x')\n    def inner():\n        return 1\n    return inner\n",
        "def outer():\n    todo = make()\n    @todo('x')\n    def inner():\n        return 1\n",
        "class C:\n    todo = staticmethod(make)\n    @todo('x')\n    def m(self):\n        return 1\n",
        "def outer():\n    from elsewhere import todo\n    @todo('x')\n    def inner():\n        return 1\n",
    ],
    ids=["parameter", "local", "class-attribute", "local-import"],
)
def test_shadowed_runtime_name_is_not_ours(project: ProjectFactory, clock: FakeClock, inner: str) -> None:
    project.init()
    code = "from byteplan_runtime import todo\n\n\n" + inner
    path = project.write("a.py", code, dedent=False)
    report = write_scan(project, clock)
    assert path.read_text() == code
    assert report.proposals == ()
    assert [d.code for d in report.diagnostics] == [Code.UNRESOLVED_TODO_DECORATOR]


def test_shadowed_decorator_still_works_after_scan(project: ProjectFactory, clock: FakeClock) -> None:
    """The reproduction from the review: the caller's decorator must not get an id= keyword."""
    project.init()
    code = (
        "try:\n    from byteplan_runtime import todo\nexcept ImportError:\n    pass\n\n\n"
        "def outer(todo):\n    @todo('x')\n    def inner():\n        return 1\n    return inner\n"
    )
    path = project.write("a.py", code, dedent=False)
    write_scan(project, clock)
    namespace: dict[str, Any] = {}
    exec(compile(path.read_text(), "a.py", "exec"), namespace)
    assert namespace["outer"](lambda _title: lambda fn: fn)() == 1


def test_keyword_unpacking_is_never_given_an_id(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    code = "from byteplan_runtime import todo\n\nOPTIONS = {'id': 'beef'}\n\n\n@todo('x', **OPTIONS)\ndef f():\n    return 1\n"
    path = project.write("a.py", code, dedent=False)
    report = write_scan(project, clock)
    assert path.read_text() == code
    assert report.proposals == ()
    assert [d.code for d in report.diagnostics] == [Code.DYNAMIC_TODO_ARGUMENT]


def test_keyword_unpacking_with_explicit_id_is_tracked() -> None:
    result = scan("from byteplan_runtime import todo\n@todo('x', id='a83f', **extra)\ndef f(): return 1\n")
    assert [a.task_id for a in result.tags] == ["a83f"]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ('@todo("café")\n', '@todo("café", id="{id}")\n'),
        ('@todo("路由 détail", kind="FIXME")\n', '@todo("路由 détail", kind="FIXME", id="{id}")\n'),
        ('@todo(\n    "naïve résumé"\n)\n', '@todo(\n    "naïve résumé",\n    id="{id}"\n)\n'),
        ('x = "é"; y = 1\n@todo("ascii")\n', 'x = "é"; y = 1\n@todo("ascii", id="{id}")\n'),
    ],
    ids=["accented", "cjk-and-kind", "multiline", "non-ascii-earlier-line"],
)
def test_non_ascii_decorator_arguments(project: ProjectFactory, clock: FakeClock, before: str, after: str) -> None:
    project.init()
    header, body = "from byteplan_runtime import todo\n\n\n", "def f():\n    return 1\n"
    path = project.write("a.py", header + before + body, dedent=False)
    (task_id,) = [p.task_id for p in write_scan(project, clock).proposals]
    assert path.read_text(encoding="utf-8") == header + after.replace("{id}", task_id) + body
    assert write_scan(project, clock).written == ()


def test_unicode_line_separator_in_a_string_does_not_shift_lines(project: ProjectFactory, clock: FakeClock) -> None:
    project.init()
    code = 'from byteplan_runtime import todo\n\nS = "a\u2028b\x0cc"\n\n\n@todo("x")\ndef f():\n    return 1\n'
    path = project.write("a.py", code, dedent=False)
    (task_id,) = [p.task_id for p in write_scan(project, clock).proposals]
    assert path.read_text(encoding="utf-8") == code.replace('@todo("x")', f'@todo("x", id="{task_id}")')
