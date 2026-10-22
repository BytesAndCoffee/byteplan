# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Phase 8 (part 1): `byteplan release` / `byteplan restore` against real Git repositories.

The plan's release tests: only decorator/import lines and the registry change; no commit, tag
or reset; byte-identical round trips; no status changes and nothing missing while stripped;
anchored restore after hotfixes, conflicts and `--partial`; refusals; crash recovery; dry runs.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from typing import TYPE_CHECKING, Any

import pytest

from byteplan import persistence
from byteplan.api import Project
from byteplan.cli import EXIT_ERROR, EXIT_FINDINGS, EXIT_OK
from tests.gitutil import git

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory, RunCli

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")

ROUTES = '''\
"""Routes."""

from __future__ import annotations

import os

from byteplan_runtime import todo


class Router:
    @staticmethod
    @todo(
        "Advertise routes",
        id="a83f",
        tests=("tests/test_routes.py::test_advertise",),
    )
    @staticmethod
    def advertise():
        return os.sep

    @todo("Withdraw", id="b001")  # keep this note
    def withdraw(self):
        return 2


# TODO[c002]: comments stay through a release
def plain():
    return 3
'''

TESTS = """\
from byteplan_runtime import verifies


@verifies("a83f")
def test_advertise():
    assert True
"""


def tasks(project: ProjectFactory) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((project.root / ".byteplan/tasks.json").read_text())
    return data


@pytest.fixture
def released_repo(project: ProjectFactory, run_cli: RunCli) -> ProjectFactory:
    project.write("pyproject.toml", '[project]\nname = "demo"\nversion = "1.2.0"\n', dedent=False)
    project.init()
    project.write("src/pkg/routes.py", ROUTES, dedent=False)
    project.write("tests/test_routes.py", TESTS, dedent=False)
    for task_id in ("a83f", "b001", "c002"):
        assert run_cli("repair", "--import", task_id, "--project", project.root).code == EXIT_OK
    assert run_cli("scan", "--project", project.root).code == EXIT_OK
    root = project.root
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "T")
    git(root, "config", "commit.gpgsign", "false")
    git(root, "add", "-A")
    git(root, "commit", "-qm", "base")
    git(root, "switch", "-qc", "release/1.2.0")
    return project


def release(project: ProjectFactory, run_cli: RunCli, *extra: str) -> Any:
    return run_cli("release", "--project", project.root, *extra)


def test_release_strips_only_decorators_imports_and_the_registry(
    released_repo: ProjectFactory, run_cli: RunCli
) -> None:
    root = released_repo.root
    head = git(root, "rev-parse", "HEAD").stdout
    result = release(released_repo, run_cli)
    assert result.code == EXIT_OK, result.err
    assert "stripped 3 decorator(s) and 2 import(s) from 2 file(s) for release 1.2.0" in result.out
    assert "RELEASE_ON_DEFAULT_BRANCH" not in result.err  # on a release branch
    assert git(root, "rev-parse", "HEAD").stdout == head  # never commits, tags or resets
    assert git(root, "tag").stdout == ""
    changed = sorted(line[3:] for line in git(root, "status", "--porcelain").stdout.splitlines())
    assert changed == [".byteplan/tasks.json", "src/pkg/routes.py", "tests/test_routes.py"]

    stripped = (root / "src/pkg/routes.py").read_text()
    assert stripped == textwrap.dedent(
        '''\
        """Routes."""

        from __future__ import annotations

        import os

        class Router:
            @staticmethod
            @staticmethod
            def advertise():
                return os.sep

            def withdraw(self):
                return 2


        # TODO[c002]: comments stay through a release
        def plain():
            return 3
        '''
    )
    assert (root / "tests/test_routes.py").read_text() == "def test_advertise():\n    assert True\n"

    data = tasks(released_repo)
    assert data["release"]["state"] == "stripped"
    assert data["release"]["version"] == "1.2.0"
    for task_id in ("a83f", "b001"):
        task = data["tasks"][task_id]
        assert task["status"] == "open"  # stripping isn't resolution
        assert task["presence"] == "stripped"
        assert task["history"][-1]["event"] == "stripped_for_release"
    assert data["tasks"]["c002"]["presence"] == "present"  # comments stay
    assert data["tasks"]["a83f"]["stripped"] == [
        {"decl_line": 18, "index": 1, "line": 12, "path": "src/pkg/routes.py", "qualname": "Router.advertise"}
    ]


def test_stripped_tree_imports_without_the_runtime(released_repo: ProjectFactory, run_cli: RunCli) -> None:
    assert release(released_repo, run_cli).code == EXIT_OK
    root = released_repo.root
    for path in ("src/pkg/routes.py", "tests/test_routes.py"):
        assert "byteplan_runtime" not in (root / path).read_text()
    # A clean interpreter with no byteplan-runtime on the path can import it.
    code = "import sys; sys.path.insert(0, 'src'); import pkg.routes as r; assert r.Router.advertise() == __import__('os').sep"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    done = subprocess.run(
        [sys.executable, "-I", "-c", code], cwd=root, capture_output=True, text=True, env=env, check=False
    )
    assert done.returncode == 0, done.stderr


def test_while_stripped_nothing_goes_missing_and_links_are_frozen(
    released_repo: ProjectFactory, run_cli: RunCli
) -> None:
    before = tasks(released_repo)["tasks"]["a83f"]["tests"]
    assert release(released_repo, run_cli).code == EXIT_OK
    scan = run_cli("scan", "--project", released_repo.root)
    assert "!0 missing" in scan.out
    assert "RELEASE_STRIPPED" in scan.err
    data = tasks(released_repo)["tasks"]
    assert data["a83f"]["presence"] == "stripped"
    assert data["a83f"]["tests"] == before  # @todo(tests=) and @verifies links kept on record
    assert data["a83f"]["title"] == "Advertise routes"
    shown = run_cli("show", "a83f", "--project", released_repo.root).out
    assert "stripped:  @todo at src/pkg/routes.py:12 on Router.advertise" in shown
    pyproject = released_repo.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + "\n[tool.byteplan.check]\nrequire_reconciled = true\n")
    assert run_cli("check", "--project", released_repo.root).code == EXIT_OK


def test_writing_commands_refuse_while_stripped(released_repo: ProjectFactory, run_cli: RunCli) -> None:
    assert release(released_repo, run_cli).code == EXIT_OK
    for args in (
        ["sync", "--apply"],
        ["sync", "--remove-resolved", "--apply"],
        ["tests", "scaffold", "c002"],
        ["release"],
    ):
        result = run_cli(*args, "--project", released_repo.root)
        assert result.code == EXIT_ERROR, args
        assert "release_stripped" in result.err, args


@pytest.mark.parametrize(
    "header",
    [
        "#!/usr/bin/env python\n# -*- coding: utf-8 -*-\n",
        "﻿",
        "",
    ],
)
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("final_newline", [True, False])
def test_release_then_restore_is_byte_identical(
    released_repo: ProjectFactory,
    run_cli: RunCli,
    header: str,
    newline: str,
    final_newline: bool,  # noqa: FBT001 - pytest parameter
) -> None:
    text = (header + ROUTES).replace("\n", newline)
    if not final_newline:
        text = text.rstrip("\r\n")
    data = text.encode("utf-8")
    path = released_repo.root / "src/pkg/routes.py"
    path.write_bytes(data)
    git(released_repo.root, "commit", "-qam", "variant", "--allow-empty")
    assert release(released_repo, run_cli).code == EXIT_OK
    assert path.read_bytes() != data
    result = run_cli("restore", "--project", released_repo.root)
    assert result.code == EXIT_OK, result.err
    assert path.read_bytes() == data
    assert (released_repo.root / "tests/test_routes.py").read_text() == TESTS
    data_after = tasks(released_repo)
    assert "release" not in data_after
    assert data_after["releases"][-1]["version"] == "1.2.0"
    for task_id in ("a83f", "b001"):
        task = data_after["tasks"][task_id]
        assert task["presence"] == "present"
        assert "stripped" not in task
        assert task["history"][-1]["event"] == "restored"
        assert task["status"] == "open"


def test_restore_after_a_hotfix_uses_the_ast(released_repo: ProjectFactory, run_cli: RunCli) -> None:
    assert release(released_repo, run_cli).code == EXIT_OK
    path = released_repo.root / "src/pkg/routes.py"
    path.write_text(path.read_text().replace("class Router:", "VERSION = 2\n\n\nclass Router:\n    '''Docs.'''\n"))
    assert run_cli("restore", "--project", released_repo.root).code == EXIT_OK
    restored = path.read_text()
    assert "VERSION = 2" in restored
    assert "from byteplan_runtime import todo" in restored
    assert restored.index('@todo(\n        "Advertise routes"') < restored.index("def advertise")
    assert restored.count("@staticmethod") == 2
    assert '    @todo("Withdraw", id="b001")  # keep this note\n    def withdraw' in restored
    assert "+0 added" in run_cli("scan", "--project", released_repo.root).out


def test_renamed_symbol_is_a_conflict_and_partial_keeps_it_on_record(
    released_repo: ProjectFactory, run_cli: RunCli
) -> None:
    assert release(released_repo, run_cli).code == EXIT_OK
    path = released_repo.root / "src/pkg/routes.py"
    path.write_text(path.read_text().replace("def withdraw", "def retract"))
    before = released_repo.snapshot()
    refused = run_cli("restore", "--project", released_repo.root)
    assert refused.code == EXIT_ERROR
    assert "restore_conflict" in refused.err
    assert "Router.withdraw no longer exists" in refused.err
    assert released_repo.snapshot() == before

    partial = run_cli("restore", "--partial", "--project", released_repo.root)
    assert partial.code == EXIT_FINDINGS
    data = tasks(released_repo)
    assert data["release"]["state"] == "stripped"  # the unplaced entry is still on record
    left = data["release"]["files"]["src/pkg/routes.py"]["decorators"]
    assert [d["qualname"] for d in left] == ["Router.withdraw"]
    assert data["tasks"]["a83f"]["presence"] == "present"
    assert data["tasks"]["b001"]["presence"] == "stripped"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda p: p.write("src/pkg/extra.py", "x = 1\n"), "uncommitted changes"),
        (
            lambda p: p.write(
                "src/pkg/routes.py", ROUTES.replace('    @todo("Withdraw", id="b001")', '    @todo("Withdraw")')
            ),
            "has no id=",
        ),
        (
            lambda p: p.write("src/pkg/other.py", "import byteplan_runtime\n\nMARK = byteplan_runtime.todo\n"),
            "still used outside decorators",
        ),
    ],
)
def test_refusals_write_nothing(released_repo: ProjectFactory, run_cli: RunCli, change: Any, message: str) -> None:
    change(released_repo)
    if message != "uncommitted changes":
        git(released_repo.root, "add", "-A")
        git(released_repo.root, "commit", "-qm", "change")
    before = released_repo.snapshot()
    result = release(released_repo, run_cli)
    assert result.code == EXIT_ERROR
    assert message in result.err
    assert released_repo.snapshot() == before


def test_allow_dirty_and_dry_run(released_repo: ProjectFactory, run_cli: RunCli) -> None:
    released_repo.write("notes.txt", "wip\n")
    before = released_repo.snapshot()
    result = release(released_repo, run_cli, "--allow-dirty", "--dry-run", "--version", "9.9")
    assert result.code == EXIT_OK
    assert "would strip 3 decorator(s)" in result.out
    assert released_repo.snapshot() == before


def test_default_branch_warning(released_repo: ProjectFactory, run_cli: RunCli) -> None:
    git(released_repo.root, "switch", "-q", "main")
    result = release(released_repo, run_cli)
    assert result.code == EXIT_OK  # a warning, not a refusal
    assert "RELEASE_ON_DEFAULT_BRANCH" in result.err


def test_version_comes_from_hatch_dynamic_metadata(released_repo: ProjectFactory, run_cli: RunCli) -> None:
    pyproject = released_repo.root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text().replace('version = "1.2.0"', 'dynamic = ["version"]')
        + '\n[tool.hatch.version]\npath = "src/pkg/__about__.py"\n'
    )
    released_repo.write("src/pkg/__about__.py", '__version__ = "3.1.4"\n')
    git(released_repo.root, "add", "-A")
    git(released_repo.root, "commit", "-qm", "dynamic")
    assert "for release 3.1.4" in release(released_repo, run_cli).out


@pytest.mark.parametrize("nth", [1, 2, 3])
def test_crash_mid_release_rolls_forward(
    released_repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch, nth: int
) -> None:
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

    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(CrashError):
        Project.open(released_repo.root).release(allow_dirty=True)
    monkeypatch.undo()
    assert persistence.pending_journal(released_repo.root)
    Project.open(released_repo.root).scan(dry_run=False)  # rolls the transaction forward
    assert not persistence.pending_journal(released_repo.root)
    assert "byteplan_runtime" not in (released_repo.root / "src/pkg/routes.py").read_text()
    assert tasks(released_repo)["release"]["state"] == "stripped"


# Codex review of #32 (tracked as 34da, b68c, 4d48) ----------------------------------------------


def test_shadowed_todo_is_not_stripped(released_repo: ProjectFactory, run_cli: RunCli) -> None:
    """34da: a class scope that rebinds `todo` makes its decorator not BytePlan's."""
    shadow = (
        "from byteplan_runtime import todo\n\n\nclass Local:\n    def todo(*args, **kwargs):\n"
        '        return lambda f: f\n\n    @todo("x", id="a123")\n    def method(self):\n        return 1\n'
    )
    released_repo.write("src/pkg/shadow.py", shadow, dedent=False)
    git(released_repo.root, "add", "-A")
    git(released_repo.root, "commit", "-qm", "shadow")
    before = released_repo.snapshot()
    result = release(released_repo, run_cli)
    assert result.code == EXIT_ERROR
    assert "release_needs_review" in result.err
    assert "@todo on Local.method is shadowed by a local definition" in result.err
    assert released_repo.snapshot() == before  # the class's own decorator is never deleted


def test_unanchored_import_goes_below_a_new_docstring_and_future_import(
    released_repo: ProjectFactory, run_cli: RunCli
) -> None:
    """b68c: the import had nothing above it; a hotfix adds a docstring and __future__."""
    released_repo.write(
        "src/pkg/top.py",
        'from byteplan_runtime import todo\n\n\n@todo("t", id="b234")\ndef f():\n    return 1\n',
        dedent=False,
    )
    git(released_repo.root, "add", "-A")
    git(released_repo.root, "commit", "-qm", "top")
    assert release(released_repo, run_cli).code == EXIT_OK
    path = released_repo.root / "src/pkg/top.py"
    path.write_text('"""Top."""\n\nfrom __future__ import annotations\n\n' + path.read_text())
    assert run_cli("restore", "--project", released_repo.root).code == EXIT_OK
    restored = path.read_text()
    assert restored.startswith('"""Top."""\n\nfrom __future__ import annotations\n')
    assert restored.index("from __future__") < restored.index("from byteplan_runtime import todo")
    compile(restored, "top.py", "exec")  # a __future__ import after other code would be a SyntaxError


def test_partial_restore_keeps_decorators_whose_import_is_unplaced(
    released_repo: ProjectFactory, run_cli: RunCli
) -> None:
    """4d48: an unplaceable import leaves its decorators pending; other files still restore."""
    assert release(released_repo, run_cli).code == EXIT_OK
    routes = released_repo.root / "src/pkg/routes.py"
    routes.write_text(routes.read_text().replace("import os\n", "import os  # changed anchor\n"))
    result = run_cli("restore", "--partial", "--project", released_repo.root)
    assert result.code == EXIT_FINDINGS, result.err
    assert "byteplan_runtime" not in routes.read_text()  # decorators stay pending with their import
    assert "@verifies" in (released_repo.root / "tests/test_routes.py").read_text()  # the other file restored
    data = tasks(released_repo)
    pending = data["release"]["files"]["src/pkg/routes.py"]
    assert len(pending["imports"]) == 1
    assert len(pending["decorators"]) == 2
    assert "src/pkg/routes.py" in data["release"]["files"]
    assert "tests/test_routes.py" not in data["release"]["files"]


# Codex review of #32, round 2 (tracked as aedf, c242, 90c6) --------------------------------------


@pytest.mark.parametrize(
    "module",
    [
        "from byteplan_runtime import __version__\n\nprint(__version__)\n",
        "def f():\n    import byteplan_runtime\n    return byteplan_runtime\n",
    ],
)
def test_other_runtime_imports_refuse_the_release(released_repo: ProjectFactory, run_cli: RunCli, module: str) -> None:
    """aedf: a runtime dependency that isn't a decorator must not survive into a release."""
    released_repo.write("src/pkg/uses_runtime.py", module, dedent=False)
    git(released_repo.root, "add", "-A")
    git(released_repo.root, "commit", "-qm", "uses runtime")
    before = released_repo.snapshot()
    result = release(released_repo, run_cli)
    assert result.code == EXIT_ERROR
    assert "src/pkg/uses_runtime.py" in result.err
    assert "still used outside decorators" in result.err
    assert released_repo.snapshot() == before


def test_unused_other_runtime_import_is_stripped(released_repo: ProjectFactory, run_cli: RunCli) -> None:
    released_repo.write("src/pkg/unused.py", "from byteplan_runtime import __version__\n\nVALUE = 1\n", dedent=False)
    git(released_repo.root, "add", "-A")
    git(released_repo.root, "commit", "-qm", "unused import")
    assert release(released_repo, run_cli).code == EXIT_OK
    assert (released_repo.root / "src/pkg/unused.py").read_text() == "VALUE = 1\n"
    assert run_cli("restore", "--project", released_repo.root).code == EXIT_OK
    assert (
        (released_repo.root / "src/pkg/unused.py").read_text().startswith("from byteplan_runtime import __version__\n")
    )


def test_restore_refuses_a_decorator_shadowed_since_the_release(released_repo: ProjectFactory, run_cli: RunCli) -> None:
    """c242: a class-local `todo` added while stripped would take over the restored decorator."""
    assert release(released_repo, run_cli).code == EXIT_OK
    path = released_repo.root / "src/pkg/routes.py"
    path.write_text(
        path.read_text().replace(
            "class Router:\n", "class Router:\n    def todo(*a, **k):\n        raise RuntimeError\n\n"
        )
    )
    before = released_repo.snapshot()
    result = run_cli("restore", "--project", released_repo.root)
    assert result.code == EXIT_ERROR
    assert "restore_conflict" in result.err
    assert "shadowed" in result.err
    assert released_repo.snapshot() == before


def test_stripped_stub_gets_no_duplicate_task(project: ProjectFactory, run_cli: RunCli) -> None:
    """90c6: in comment mode, a stub whose @todo is stripped must not look unowned to scan."""
    project.write("pyproject.toml", '[project]\nname = "demo"\nversion = "1.0"\n', dedent=False)
    project.init()
    project.write(
        "src/stub.py",
        'from byteplan_runtime import todo\n\n\n@todo("Implement", id="abcd")\ndef unfinished():\n    pass\n',
        dedent=False,
    )
    assert run_cli("repair", "--import", "abcd", "--project", project.root).code == EXIT_OK
    assert run_cli("release", "--allow-dirty", "--project", project.root).code == EXIT_OK
    stripped = (project.root / "src/stub.py").read_text()
    result = run_cli("scan", "--project", project.root)
    assert "+0 added" in result.out
    assert (project.root / "src/stub.py").read_text() == stripped  # no new TODO comment
    assert sorted(tasks(project)["tasks"]) == ["abcd"]


# Codex review of #32, round 3 (tracked as a703, c8db) -------------------------------------------


def test_wildcard_runtime_import_refuses_the_release(released_repo: ProjectFactory, run_cli: RunCli) -> None:
    """a703: `import *` binds names the module may use; it can't be proven unused."""
    released_repo.write("src/pkg/star.py", "from byteplan_runtime import *\n\nMARK = todo\n", dedent=False)
    git(released_repo.root, "add", "-A")
    git(released_repo.root, "commit", "-qm", "star")
    before = released_repo.snapshot()
    result = release(released_repo, run_cli)
    assert result.code == EXIT_ERROR
    assert "src/pkg/star.py" in result.err
    assert "wildcard" in result.err
    assert released_repo.snapshot() == before


@pytest.mark.parametrize(
    "consumer",
    [
        "from pkg.reexport import todo\n\nMARK = todo\n",
        "import pkg.reexport\n\nMARK = pkg.reexport.todo\n",
        "from pkg import reexport\n\nMARK = reexport.todo\n",
        "from .reexport import todo\n\nMARK = todo\n",
    ],
)
def test_runtime_reexported_to_another_module_refuses_the_release(
    released_repo: ProjectFactory, run_cli: RunCli, consumer: str
) -> None:
    """c8db: another module importing the runtime binding from this one keeps it in use."""
    released_repo.write("src/pkg/__init__.py", "", dedent=False)
    released_repo.write("src/pkg/reexport.py", "from byteplan_runtime import todo as todo\n", dedent=False)
    released_repo.write("src/pkg/consumer.py", consumer, dedent=False)
    git(released_repo.root, "add", "-A")
    git(released_repo.root, "commit", "-qm", "re-export")
    before = released_repo.snapshot()
    result = release(released_repo, run_cli)
    assert result.code == EXIT_ERROR
    assert "src/pkg/reexport.py" in result.err
    assert "imported from this module by src/pkg/consumer.py" in result.err
    assert released_repo.snapshot() == before


# Codex review of #32, round 4 (tracked as 205d) -------------------------------------------------


def test_release_refuses_a_pending_journal_without_recovering_it(
    released_repo: ProjectFactory, run_cli: RunCli, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An interrupted write must be finished deliberately (`byteplan scan`), not by release."""
    real_replace = os.replace
    calls = {"n": 0}

    class CrashError(Exception):
        pass

    def replace(src: Any, dst: Any) -> None:
        if not str(dst).endswith("journal.json"):
            calls["n"] += 1
            if calls["n"] == 1:
                raise CrashError
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    with pytest.raises(CrashError):
        Project.open(released_repo.root).release(allow_dirty=True)
    monkeypatch.undo()
    assert persistence.pending_journal(released_repo.root)
    before = released_repo.snapshot()
    result = release(released_repo, run_cli, "--allow-dirty")
    assert result.code == EXIT_ERROR
    assert "an interrupted write is pending" in result.err
    assert released_repo.snapshot() == before  # nothing rolled forward or written
    assert persistence.pending_journal(released_repo.root)
