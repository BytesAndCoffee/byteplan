# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Phase 5: annotation modes, `byteplan sync` (decorator normalization) and the runtime shim.

Covers Addendum A §9 tests 3 (conservative conversion), 4 (refusals), 5 (behaviour and
decorator order preserved; inert runtime), 6 (stub decoration only when unowned) and 8
(byte-level safety).
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import textwrap
from typing import TYPE_CHECKING, Any

import pytest

from byteplan.api import RUNTIME_SHIM, Project, init_project, shim_module_name
from byteplan.cli import EXIT_OK
from byteplan.errors import ConfigError, EditError
from byteplan.normalize import decorator_text, ensure_equivalent_without_runtime

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory, RunCli

DECORATOR_MODE = """
[tool.byteplan.annotations]
mode = "decorator"
convert_attached_comments = true
auto_decorate_stubs = true
"""


def configure(project: ProjectFactory, extra: str = DECORATOR_MODE, *, dependency: bool = True) -> None:
    pyproject = project.root / "pyproject.toml"
    text = pyproject.read_text()
    if dependency:
        text = text.replace('version = "0.1"\n', 'version = "0.1"\ndependencies = ["byteplan-runtime>=0.1"]\n')
    pyproject.write_text(text + extra)


@pytest.fixture
def decorated(project: ProjectFactory) -> ProjectFactory:
    project.init()
    configure(project)
    return project


def scan_and_sync(project: ProjectFactory, run_cli: RunCli, *extra: str) -> str:
    assert run_cli("scan", "--project", project.root).code == EXIT_OK
    result = run_cli("sync", "--apply", "--project", project.root, *extra)
    assert result.code == EXIT_OK, result.out + result.err
    return result.out


def tasks(project: ProjectFactory) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((project.root / ".byteplan/tasks.json").read_text())["tasks"]
    return data


def ids(text: str) -> list[str]:
    """Task IDs in source, in comment (`[abcd]`) or decorator (`id="abcd"`) form."""
    return [a or b for a, b in re.findall(r'\[([0-9a-f]{4})\]|id="([0-9a-f]{4})"', text)]


# Modes and scan ------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["preserve", "decorator"])
def test_non_comment_modes_report_stubs_instead_of_annotating(
    project: ProjectFactory, run_cli: RunCli, mode: str
) -> None:
    project.init()
    configure(project, f'\n[tool.byteplan.annotations]\nmode = "{mode}"\n')
    project.write("src/a.py", "def f():\n    pass\n\n# TODO: comments still get IDs\nx = 1\n")
    result = run_cli("scan", "--project", project.root)
    assert result.code == EXIT_OK
    text = (project.root / "src/a.py").read_text()
    assert "detected stub" not in text
    assert len(ids(text)) == 1
    assert "STUB_NEEDS_REVIEW" in result.err
    assert "annotations mode is" in result.err


def test_sync_does_nothing_outside_decorator_mode(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    project.write("src/a.py", "# TODO: x\ndef f():\n    return 1\n")
    result = run_cli("sync", "--apply", "--project", project.root)
    assert result.code == EXIT_OK
    assert 'nothing to do: annotations mode is "comment"' in result.out
    project.write(
        "pyproject.toml",
        (project.root / "pyproject.toml").read_text() + '\n[tool.byteplan.annotations]\nmode = "decorator"\n',
        dedent=False,
    )
    assert "neither convert_attached_comments nor auto_decorate_stubs" in run_cli("sync", "--project", project.root).out


def test_sync_requires_a_scanned_tree(decorated: ProjectFactory, run_cli: RunCli) -> None:
    decorated.write("src/a.py", "# TODO: not scanned yet\ndef f():\n    return 1\n")
    before = decorated.snapshot()
    result = run_cli("sync", "--apply", "--project", decorated.root)
    assert result.code != EXIT_OK
    assert "run `byteplan scan` first" in result.out
    assert decorated.snapshot() == before


# Addendum A test 3: conservative adjacent-comment conversion ---------------------------------------


def test_attached_comment_becomes_a_decorator(decorated: ProjectFactory, run_cli: RunCli) -> None:
    decorated.write(
        "src/router.py",
        """\
        class Router:
            # FIXME: Withdraw routes on link loss
            #   Support split horizon
            #     and poisoned reverse.
            @staticmethod
            def withdraw():
                return None
        """,
    )
    assert run_cli("scan", "--project", decorated.root).code == EXIT_OK
    (task_id,) = ids((decorated.root / "src/router.py").read_text())
    out = scan_and_sync(decorated, run_cli)
    assert f"~ [{task_id}] FIXME src/router.py:2  comment -> @todo" in out
    assert (decorated.root / "src/router.py").read_text() == textwrap.dedent(
        f"""\
        from byteplan_runtime import todo
        class Router:
            @todo(
                "Withdraw routes on link loss",
                id="{task_id}",
                kind="FIXME",
                description="Support split horizon\\n  and poisoned reverse.",
            )
            @staticmethod
            def withdraw():
                return None
        """
    )
    task = tasks(decorated)[task_id]
    assert (task["kind"], task["title"], task["description"]) == (
        "FIXME",
        "Withdraw routes on link loss",
        "Support split horizon\n  and poisoned reverse.",
    )
    assert task["source"]["representation"] == "decorator"
    assert task["origin"] == "comment"  # discovered as a comment; only its form changed
    assert [e["event"] for e in task["history"]] == ["created"]  # same text, same symbol: no events
    before = decorated.snapshot()
    assert run_cli("scan", "--project", decorated.root).code == EXIT_OK
    again = run_cli("sync", "--apply", "--project", decorated.root)
    assert "0 comment(s) converted · 0 stub(s) decorated" in again.out
    assert decorated.snapshot() == before  # idempotent


def test_short_todo_is_one_line_and_reuses_an_existing_import(decorated: ProjectFactory, run_cli: RunCli) -> None:
    decorated.write(
        "src/a.py",
        """\
        import byteplan_runtime as br


        # TODO: Short
        def f():
            return 1
        """,
    )
    scan_and_sync(decorated, run_cli)
    text = (decorated.root / "src/a.py").read_text()
    (task_id,) = ids(text)
    assert f'@br.todo("Short", id="{task_id}")\ndef f():' in text
    assert text.count("import") == 1


def test_only_converts_the_named_tasks(decorated: ProjectFactory, run_cli: RunCli) -> None:
    decorated.write("src/a.py", "# TODO: one\ndef f():\n    return 1\n\n\n# TODO: two\ndef g():\n    return 2\n")
    assert run_cli("scan", "--project", decorated.root).code == EXIT_OK
    first, second = ids((decorated.root / "src/a.py").read_text())
    result = run_cli("sync", "--apply", "--only", second, "--only", "ffff", "--project", decorated.root)
    assert result.code == EXIT_OK
    text = (decorated.root / "src/a.py").read_text()
    assert f"# TODO[{first}]: one" in text
    assert f'@todo("two", id="{second}")' in text
    assert "task ffff was not rewritten" in result.err


# Addendum A test 4: refusals ------------------------------------------------------------------------


def test_refusals_leave_comments_exactly_as_they_were(decorated: ProjectFactory, run_cli: RunCli) -> None:
    source = """\
        # TODO: module level
        x = 1


        def f():
            # TODO: inside a body
            return 1  # TODO: trailing


        # TODO: separated by a blank line

        def g():
            return 2
        """
    decorated.write("src/a.py", source)
    assert run_cli("scan", "--project", decorated.root).code == EXIT_OK
    scanned = (decorated.root / "src/a.py").read_text()
    result = run_cli("sync", "--apply", "--project", decorated.root)
    assert result.code == EXIT_OK
    assert (decorated.root / "src/a.py").read_text() == scanned
    assert result.err.count("CONVERSION_NEEDS_REVIEW") == 4
    assert "it's module-level" in result.err
    assert "it's trailing" in result.err
    assert "not directly above a declaration" in result.err


def test_no_runtime_means_no_conversion(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    configure(project, dependency=False)
    project.write("src/a.py", "# TODO: x\ndef f():\n    return 1\n")
    assert run_cli("scan", "--project", project.root).code == EXIT_OK
    scanned = (project.root / "src/a.py").read_text()
    result = run_cli("sync", "--apply", "--project", project.root)
    assert "the runtime isn't available" in result.err
    assert (project.root / "src/a.py").read_text() == scanned


def test_taken_todo_name_refuses_conversion(decorated: ProjectFactory, run_cli: RunCli) -> None:
    decorated.write("src/a.py", "def todo():\n    return 0\n\n\n# TODO: x\ndef f():\n    return 1\n")
    assert run_cli("scan", "--project", decorated.root).code == EXIT_OK
    result = run_cli("sync", "--apply", "--project", decorated.root)
    assert "the name `todo` is already used" in result.err


def test_unsafe_import_position_refuses_conversion(decorated: ProjectFactory, run_cli: RunCli) -> None:
    decorated.write(
        "src/a.py", "from __future__ import annotations; import os\n\n\n# TODO: x\ndef f():\n    return os\n"
    )
    assert run_cli("scan", "--project", decorated.root).code == EXIT_OK
    result = run_cli("sync", "--apply", "--project", decorated.root)
    assert "can't safely insert the runtime import" in result.err


# Addendum A test 5: behaviour and decorator order preserved; inert runtime -------------------------


def test_rewritten_module_behaves_identically(decorated: ProjectFactory, run_cli: RunCli) -> None:
    decorated.write("src/byteplan_runtime/__init__.py", RUNTIME_SHIM)  # the inert runtime, importable
    decorated.write(
        "src/calc.py",
        """\
        import functools

        CALLS = []


        def trace(fn):
            @functools.wraps(fn)
            def inner(*args):
                CALLS.append(fn.__name__)
                return fn(*args)
            return inner


        class Calc:
            # TODO: Handle overflow
            @staticmethod
            @trace
            def add(a, b):
                return a + b

            # HACK: Avoid the cache
            @functools.cached_property
            def value(self):
                return 42
        """,
    )
    scan_and_sync(decorated, run_cli)
    text = (decorated.root / "src/calc.py").read_text()
    assert text.index("@todo(") < text.index("@staticmethod") < text.index("@trace")
    assert text.index('kind="HACK"') < text.index("@functools.cached_property")

    sys.path.insert(0, str(decorated.root / "src"))
    try:
        spec = importlib.util.spec_from_file_location("calc", decorated.root / "src/calc.py")
        assert spec is not None
        assert spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(decorated.root / "src"))
        sys.modules.pop("byteplan_runtime", None)
    assert module.Calc.add(2, 3) == 5
    assert module.CALLS == ["add"]
    assert module.Calc().value == 42


def test_inert_shim_returns_the_identical_object() -> None:
    namespace: dict[str, Any] = {}
    exec(compile(RUNTIME_SHIM, "shim", "exec"), namespace)

    def f() -> None: ...  # byteplan: ignore - a stand-in object, not unfinished work

    assert namespace["todo"]("x", id="abcd", kind="FIXME", description="d", tests=("t",))(f) is f
    assert namespace["verifies"]("abcd")(f) is f


def test_equivalence_guard_rejects_real_changes() -> None:
    before = "def f():\n    return 1\n"
    ensure_equivalent_without_runtime(
        "a.py",
        before,
        'from byteplan_runtime import todo\n@todo("x", id="abcd")\ndef f():\n    return 1\n',
        ["byteplan_runtime"],
    )
    with pytest.raises(EditError, match="change program structure"):
        ensure_equivalent_without_runtime("a.py", before, "@other\ndef f():\n    return 1\n", ["byteplan_runtime"])
    with pytest.raises(EditError, match="no longer parses"):
        ensure_equivalent_without_runtime("a.py", before, "@todo(\ndef f():\n", ["byteplan_runtime"])


# Addendum A test 6: stub decoration only when unowned ----------------------------------------------


def test_only_unowned_stubs_are_decorated(decorated: ProjectFactory, run_cli: RunCli) -> None:
    decorated.write(
        "src/a.py",
        """\
        import abc


        def unowned():
            raise NotImplementedError


        # TODO: Owned by a comment
        def owned_by_comment():
            pass


        def owned_inside():
            # TODO: Owned from the body
            pass


        def ignored():  # byteplan: ignore
            pass


        class Base(abc.ABC):
            @abc.abstractmethod
            def abstract(self):
                pass


        def one_liner(): pass
        """,
    )
    assert run_cli("scan", "--project", decorated.root).code == EXIT_OK
    out = scan_and_sync(decorated, run_cli)
    text = (decorated.root / "src/a.py").read_text()
    assert "+ [" in out
    assert "@todo on stub unowned" in out
    (stub_id,) = [task_id for task_id, task in tasks(decorated).items() if task["title"] == "Implement unowned"]
    assert f'@todo("Implement unowned", id="{stub_id}")\ndef unowned():' in text
    assert tasks(decorated)[stub_id]["origin"] == "stub"
    assert tasks(decorated)[stub_id]["stub"] == {"implemented": False, "symbol": "unowned"}
    for name in ("owned_inside", "ignored", "abstract", "one_liner"):
        assert f"Implement {name}" not in text
    assert text.count("@todo(") == 2  # the stub, plus the converted comment on owned_by_comment


def test_stub_decoration_off_with_only(decorated: ProjectFactory, run_cli: RunCli) -> None:
    decorated.write("src/a.py", "# TODO: x\ndef f():\n    return 1\n\n\ndef g():\n    pass\n")
    assert run_cli("scan", "--project", decorated.root).code == EXIT_OK
    (task_id,) = ids((decorated.root / "src/a.py").read_text())
    run_cli("sync", "--apply", "--only", task_id, "--project", decorated.root)
    assert "Implement g" not in (decorated.root / "src/a.py").read_text()


# Addendum A test 8: byte-level safety --------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (  # CRLF, BOM
            b'\xef\xbb\xbf"""Doc."""\r\n\r\n# TODO: crlf\r\ndef f():\r\n    return 1\r\n',
            b'\xef\xbb\xbf"""Doc."""\r\n\r\nfrom byteplan_runtime import todo\r\n@todo("crlf", id="{id}")\r\n'
            b"def f():\r\n    return 1\r\n",
        ),
        (  # shebang, coding cookie, __future__, unicode, no final newline
            "#!/usr/bin/env python\n# -*- coding: utf-8 -*-\nfrom __future__ import annotations\n"
            "# TODO: café ☃\ndef f():\n    return 'é'".encode(),
            "#!/usr/bin/env python\n# -*- coding: utf-8 -*-\nfrom __future__ import annotations\n"
            'from byteplan_runtime import todo\n@todo("café ☃", id="{id}")\n'
            "def f():\n    return 'é'".encode(),
        ),
        (  # only a docstring and the declaration; latin-1 cookie
            b"# -*- coding: latin-1 -*-\n# TODO: s\xe9\ndef f():\n    return 1\n",
            b'# -*- coding: latin-1 -*-\nfrom byteplan_runtime import todo\n@todo("s\xe9", id="{id}")\n'
            b"def f():\n    return 1\n",
        ),
    ],
)
def test_byte_level_safety(decorated: ProjectFactory, run_cli: RunCli, raw: bytes, expected: bytes) -> None:
    decorated.write("src/a.py", raw)
    assert run_cli("scan", "--project", decorated.root).code == EXIT_OK
    task_id = next(iter(tasks(decorated)))
    scan_and_sync(decorated, run_cli)
    assert (decorated.root / "src/a.py").read_bytes() == expected.replace(b"{id}", task_id.encode())


def test_import_goes_before_a_comment_attached_to_the_first_declaration(
    decorated: ProjectFactory, run_cli: RunCli
) -> None:
    decorated.write("src/a.py", "# Leading comment\n# TODO: first\ndef f():\n    return 1\n")
    scan_and_sync(decorated, run_cli)
    text = (decorated.root / "src/a.py").read_text()
    task_id = next(iter(tasks(decorated)))
    assert (
        text
        == f'from byteplan_runtime import todo\n# Leading comment\n@todo("first", id="{task_id}")\ndef f():\n    return 1\n'
    )


def test_dry_run_writes_nothing_and_json_output(decorated: ProjectFactory, run_cli: RunCli) -> None:
    decorated.write("src/a.py", "# TODO: x\ndef f():\n    return 1\n")
    assert run_cli("scan", "--project", decorated.root).code == EXIT_OK
    before = decorated.snapshot()
    result = run_cli("sync", "--format", "json", "--project", decorated.root)
    assert decorated.snapshot() == before
    data = json.loads(result.out)
    assert data["dry_run"] is True
    assert [r["action"] for r in data["rewrites"]] == ["convert"]
    assert data["imports_added"] == ["src/a.py"]


def test_decorator_text_wraps_long_titles() -> None:
    long = "x" * 90
    assert decorator_text("todo", long, "abcd", "TODO", "", "    ", "\n") == (
        f'    @todo(\n        "{long}",\n        id="abcd",\n    )\n'
    )
    assert (
        decorator_text("todo", 'say "hi"', "abcd", "XXX", "", "\t", "\n")
        == '\t@todo("say \\"hi\\"", id="abcd", kind="XXX")\n'
    )


# The runtime shim ----------------------------------------------------------------------------------


def test_init_writes_a_runtime_shim_and_registers_it(project: ProjectFactory, run_cli: RunCli) -> None:
    result = run_cli("init", "--runtime-shim", "src/demo/_byteplan.py", "--project", project.root)
    assert result.code == EXIT_OK
    assert "wrote runtime shim src/demo/_byteplan.py (module demo._byteplan)" in result.out
    assert (project.root / "src/demo/_byteplan.py").read_text() == RUNTIME_SHIM
    config = Project.open(project.root).config
    assert config.annotations.runtime_modules == ("byteplan_runtime", "demo._byteplan")
    assert Project.open(project.root).runtime_module() == "demo._byteplan"
    again = run_cli("init", "--runtime-shim", "src/demo/_byteplan.py", "--project", project.root)
    assert again.code == EXIT_OK  # identical shim: nothing to do


def test_shim_on_an_initialized_project_asks_to_register_it(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    result = run_cli("init", "--runtime-shim", "pkg/shim.py", "--project", project.root)
    assert 'add "pkg.shim" to [tool.byteplan.annotations] runtime_modules' in result.err


@pytest.mark.parametrize(
    ("path", "error"),
    [("../shim.py", "inside the project"), ("shim.txt", "inside the project"), ("my-pkg/shim.py", "isn't importable")],
)
def test_bad_shim_paths(project: ProjectFactory, path: str, error: str) -> None:
    with pytest.raises(ConfigError, match=error):
        init_project(project.root, runtime_shim=path)


def test_existing_different_file_is_not_overwritten(project: ProjectFactory) -> None:
    project.write("shim.py", "x = 1\n")
    with pytest.raises(ConfigError, match="already exists"):
        init_project(project.root, runtime_shim="shim.py")


@pytest.mark.parametrize(
    ("rel", "module"),
    [("src/pkg/_bp.py", "pkg._bp"), ("pkg/shim/__init__.py", "pkg.shim"), ("shim.py", "shim")],
)
def test_shim_module_names(rel: str, module: str) -> None:
    assert shim_module_name(rel) == module


def test_shim_end_to_end_without_the_dependency(project: ProjectFactory, run_cli: RunCli) -> None:
    run_cli("init", "--runtime-shim", "src/demo/_byteplan.py", "--project", project.root)
    pyproject = project.root / "pyproject.toml"
    settings = DECORATOR_MODE.strip().removeprefix("[tool.byteplan.annotations]\n")
    pyproject.write_text(
        pyproject.read_text().replace("[tool.byteplan.annotations]\n", f"[tool.byteplan.annotations]\n{settings}\n")
    )
    project.write("src/demo/a.py", "# TODO: via the shim\ndef f():\n    return 1\n")
    scan_and_sync(project, run_cli)
    text = (project.root / "src/demo/a.py").read_text()
    assert text.startswith("from demo._byteplan import todo\n@todo(")
    assert run_cli("check", "--project", project.root).code == EXIT_OK


# Codex review of #23 -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "from typing import TYPE_CHECKING\n\nif TYPE_CHECKING:\n    from byteplan_runtime import todo\n\n\n"
        "# TODO: x\ndef f():\n    return 1\n",
        "# TODO: x\ndef f():\n    return 1\n\n\nfrom byteplan_runtime import todo\n",
        "try:\n    import byteplan_runtime as br\nexcept ImportError:\n    br = None\n\n\n# TODO: x\ndef f():\n    return 1\n",
    ],
)
def test_conditional_or_late_imports_are_not_reused(decorated: ProjectFactory, run_cli: RunCli, source: str) -> None:
    """Reusing them could raise NameError at import time; the comment must stay."""
    decorated.write("src/a.py", source)
    assert run_cli("scan", "--project", decorated.root).code == EXIT_OK
    scanned = (decorated.root / "src/a.py").read_text()
    result = run_cli("sync", "--apply", "--project", decorated.root)
    assert result.code == EXIT_OK
    assert (decorated.root / "src/a.py").read_text() == scanned
    assert "might not exist when the decorator runs" in result.err


def test_import_above_the_declaration_is_reused(decorated: ProjectFactory, run_cli: RunCli) -> None:
    decorated.write(
        "src/a.py", "import os\nfrom byteplan_runtime import todo as mark\n\n\n# TODO: x\ndef f():\n    return os\n"
    )
    scan_and_sync(decorated, run_cli)
    text = (decorated.root / "src/a.py").read_text()
    assert '@mark("x", id="' in text
    assert text.count("import") == 2


def test_stub_ids_never_reuse_unregistered_source_ids(decorated: ProjectFactory, run_cli: RunCli) -> None:
    decorated.write("src/stub.py", "def g():\n    pass\n")
    assert run_cli("scan", "--project", decorated.root).code == EXIT_OK
    planned = json.loads(run_cli("sync", "--format", "json", "--project", decorated.root).out)
    (would_be,) = [r["id"] for r in planned["rewrites"]]
    # The same ID appears in source, unregistered (e.g. pasted from another branch).
    decorated.write("src/other.py", f"# TODO[{would_be}]: pasted\nx = 1\n")
    result = json.loads(run_cli("sync", "--apply", "--format", "json", "--project", decorated.root).out)
    (new_id,) = [r["id"] for r in result["rewrites"]]
    assert new_id != would_be
    assert "DUPLICATE_ID" not in run_cli("scan", "--project", decorated.root).err
