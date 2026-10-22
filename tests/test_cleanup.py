# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Phase 7: registry-driven cleanup (`sync --remove-resolved`, `resolve --sync-source`).

Addendum A §9 tests 13 (authorized cleanup removes only the target annotation) and 14
(`resolved_but_stubbed` prevents a rediscovery loop), across Python, Markdown and JSON.
"""

from __future__ import annotations

import json
import os
import re
import textwrap
from typing import TYPE_CHECKING, Any

import pytest

from byteplan import persistence
from byteplan.api import Project
from byteplan.cli import EXIT_FINDINGS, EXIT_OK

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory, RunCli

PY = """\
from byteplan_runtime import todo, verifies


# A regular comment that stays
# TODO[aaaa]: Finished work
#   with a description line
def finished():
    return 1


@todo("Decorated and finished", id="bbbb")
@staticmethod
def decorated():
    return 2


# TODO[cccc]: Still open
def open_work():
    return 3


x = 1  # HACK[dddd]: trailing and finished
"""


def registry(project: ProjectFactory) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((project.root / ".byteplan/tasks.json").read_text())["tasks"]
    return data


def setup(project: ProjectFactory, run_cli: RunCli, files: dict[str, str], *, include: str = '["**/*.py"]') -> None:
    project.init()
    pyproject = project.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace('include = ["**/*.py"]', f"include = {include}"))
    for path, text in files.items():
        project.write(path, text)
    ids = {m for text in files.values() for m in re.findall(r"[\[\"]([0-9a-f]{4})[\]\"]", text)}
    for task_id in sorted(ids):
        assert run_cli("repair", "--import", task_id, "--project", project.root).code == EXIT_OK
    assert run_cli("scan", "--project", project.root).code == EXIT_OK


def resolve(project: ProjectFactory, run_cli: RunCli, *ids: str) -> None:
    for task_id in ids:
        assert run_cli("resolve", task_id, "--project", project.root).code == EXIT_OK


# Addendum A test 13: only the target annotation goes ----------------------------------------------


def test_removes_only_the_closed_tasks_annotations(project: ProjectFactory, run_cli: RunCli) -> None:
    setup(project, run_cli, {"src/a.py": PY})
    resolve(project, run_cli, "aaaa", "bbbb", "dddd")
    before = project.snapshot()
    preview = run_cli("sync", "--remove-resolved", "--project", project.root)
    assert preview.code == EXIT_OK
    assert "3 annotation(s) removed" in preview.out
    assert project.snapshot() == before  # dry run by default

    result = run_cli("sync", "--remove-resolved", "--apply", "--project", project.root)
    assert result.code == EXIT_OK, result.err
    assert (project.root / "src/a.py").read_text() == textwrap.dedent(
        """\
        # A regular comment that stays
        def finished():
            return 1


        @staticmethod
        def decorated():
            return 2


        # TODO[cccc]: Still open
        def open_work():
            return 3


        x = 1
        """
    ).replace("# A regular", "from byteplan_runtime import verifies\n\n\n# A regular")
    tasks = registry(project)
    for task_id in ("aaaa", "bbbb", "dddd"):
        assert tasks[task_id]["status"] == "resolved"  # unchanged
        assert tasks[task_id]["presence"] == "missing"
        assert tasks[task_id]["source"]["path"] == "src/a.py"  # last reference kept
        assert tasks[task_id]["history"][-1]["event"] == "cleaned"
    assert tasks["cccc"]["presence"] == "present"
    # The registry already matches the edited source.
    pyproject = project.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + "\n[tool.byteplan.check]\nrequire_reconciled = true\n")
    assert run_cli("check", "--project", project.root).code == EXIT_OK
    # Idempotent: nothing left to remove; the reserved IDs are never reissued.
    again = run_cli("sync", "--remove-resolved", "--apply", "--project", project.root)
    assert "0 annotation(s) removed" in again.out
    assert set(json.loads((project.root / ".byteplan/tasks.json").read_text())["reserved_ids"]) >= {
        "aaaa",
        "bbbb",
        "dddd",
    }


def test_runtime_import_stays_while_used(project: ProjectFactory, run_cli: RunCli) -> None:
    text = 'from byteplan_runtime import todo\n\n\n@todo("one", id="aaaa")\ndef f():\n    return 1\n\n\n@todo("two", id="bbbb")\ndef g():\n    return 2\n'
    setup(project, run_cli, {"src/a.py": text})
    resolve(project, run_cli, "aaaa")
    assert run_cli("sync", "--remove-resolved", "--apply", "--project", project.root).code == EXIT_OK
    after = (project.root / "src/a.py").read_text()
    assert after.startswith("from byteplan_runtime import todo\n")
    assert '@todo("two", id="bbbb")' in after
    resolve(project, run_cli, "bbbb")
    assert run_cli("sync", "--remove-resolved", "--apply", "--project", project.root).code == EXIT_OK
    assert (project.root / "src/a.py").read_text() == "def f():\n    return 1\n\n\ndef g():\n    return 2\n"


def test_decorator_with_a_trailing_comment_is_left_for_review(project: ProjectFactory, run_cli: RunCli) -> None:
    text = 'from byteplan_runtime import todo\n\n\n@todo("x", id="aaaa")  # keep this note\ndef f():\n    return 1\n'
    setup(project, run_cli, {"src/a.py": text})
    resolve(project, run_cli, "aaaa")
    result = run_cli("sync", "--remove-resolved", "--apply", "--project", project.root)
    assert "shares its lines with other code; remove it by hand" in result.err
    assert (project.root / "src/a.py").read_text() == text


def test_only_and_open_tasks(project: ProjectFactory, run_cli: RunCli) -> None:
    setup(project, run_cli, {"src/a.py": PY})
    resolve(project, run_cli, "aaaa", "dddd")
    result = run_cli(
        "sync", "--remove-resolved", "--apply", "--only", "aaaa", "--only", "cccc", "--project", project.root
    )
    assert result.code == EXIT_OK
    text = (project.root / "src/a.py").read_text()
    assert "TODO[aaaa]" not in text
    assert "HACK[dddd]" in text  # not selected
    assert "TODO[cccc]" in text  # open: refused
    assert "task cccc is open; only resolved or dismissed tasks are cleaned up" in result.err


def test_resolve_sync_source(project: ProjectFactory, run_cli: RunCli) -> None:
    setup(project, run_cli, {"src/a.py": PY})
    result = run_cli("resolve", "aaaa", "--sync-source", "--note", "done", "--project", project.root)
    assert result.code == EXIT_OK
    assert "[aaaa] resolved" in result.out
    assert "1 annotation(s) removed" in result.out
    assert "TODO[aaaa]" not in (project.root / "src/a.py").read_text()
    assert [e["event"] for e in registry(project)["aaaa"]["history"]][-3:] == ["resolved", "missing", "cleaned"]


def test_dismissed_tasks_are_cleaned_too(project: ProjectFactory, run_cli: RunCli) -> None:
    setup(project, run_cli, {"src/a.py": PY})
    assert run_cli("status", "cccc", "dismissed", "--project", project.root).code == EXIT_OK
    assert run_cli("sync", "--remove-resolved", "--apply", "--project", project.root).code == EXIT_OK
    assert "TODO[cccc]" not in (project.root / "src/a.py").read_text()


def test_config_turns_it_on(project: ProjectFactory, run_cli: RunCli) -> None:
    setup(project, run_cli, {"src/a.py": PY})
    pyproject = project.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + "\n[tool.byteplan.annotations]\nremove_resolved = true\n")
    resolve(project, run_cli, "aaaa")
    data = json.loads(run_cli("sync", "--apply", "--format", "json", "--project", project.root).out)
    assert data["cleanup"]["removed"] == [{"id": "aaaa", "path": "src/a.py"}]


# Addendum A test 14: resolved_but_stubbed --------------------------------------------------------


STUB = "def unfinished():\n    # FIXME[aaaa]: still a stub\n    raise NotImplementedError\n"


def test_resolved_stub_is_not_cleaned(project: ProjectFactory, run_cli: RunCli) -> None:
    setup(project, run_cli, {"src/a.py": STUB})
    resolve(project, run_cli, "aaaa")
    scan = run_cli("scan", "--project", project.root)
    assert "RESOLVED_BUT_STUBBED" in scan.err
    result = run_cli("sync", "--remove-resolved", "--apply", "--project", project.root)
    assert result.code == EXIT_FINDINGS
    assert "task aaaa is closed but unfinished still looks unfinished; its annotation stays" in result.err
    assert (project.root / "src/a.py").read_text() == STUB
    # Without the guard the next scan would create a new task for the same stub.
    assert "+0 added" in run_cli("scan", "--project", project.root).out


def test_suppress_stubs_leaves_a_visible_ignore(project: ProjectFactory, run_cli: RunCli) -> None:
    setup(project, run_cli, {"src/a.py": STUB})
    resolve(project, run_cli, "aaaa")
    result = run_cli("sync", "--remove-resolved", "--suppress-stubs", "--apply", "--project", project.root)
    assert result.code == EXIT_OK
    assert "1 suppressed" in result.out
    assert (
        project.root / "src/a.py"
    ).read_text() == "def unfinished():  # byteplan: ignore\n    raise NotImplementedError\n"
    assert registry(project)["aaaa"]["history"][-1]["event"] == "suppressed"
    assert "+0 added" in run_cli("scan", "--project", project.root).out  # no rediscovery loop


def test_implemented_stub_is_cleaned(project: ProjectFactory, run_cli: RunCli) -> None:
    setup(project, run_cli, {"src/a.py": STUB})
    project.write("src/a.py", STUB.replace("raise NotImplementedError", "return 42"))
    assert run_cli("scan", "--project", project.root).code == EXIT_OK
    resolve(project, run_cli, "aaaa")
    assert run_cli("sync", "--remove-resolved", "--apply", "--project", project.root).code == EXIT_OK
    assert (project.root / "src/a.py").read_text() == "def unfinished():\n    return 42\n"


# Markdown and JSON -------------------------------------------------------------------------------


def test_markdown_and_json(project: ProjectFactory, run_cli: RunCli) -> None:
    files = {
        "README.md": "# Doc\n\n<!-- TODO[aaaa]: a whole-line comment\n     with detail -->\n\n"
        "Prose <!-- TODO[bbbb]: inline --> continues.\n\n[//]: # (TODO[cccc]: hidden)\n[//]: # (  more)\n\nEnd.\n",
        "c.json": '{\n  // TODO[dddd]: a line comment\n  "a": 1, /* FIXME[eeee]: block */\n  "b": "TODO[ffff]: a value"\n}\n',
    }
    setup(project, run_cli, files, include='["**/*.md", "**/*.json"]')
    resolve(project, run_cli, "aaaa", "bbbb", "cccc", "dddd", "eeee", "ffff")
    result = run_cli("sync", "--remove-resolved", "--apply", "--project", project.root)
    assert (project.root / "README.md").read_text() == "# Doc\n\n\nProse continues.\n\n\nEnd.\n"
    assert (project.root / "c.json").read_text() == '{\n  "a": 1,\n  "b": "TODO[ffff]: a value"\n}\n'
    assert "task ffff is a JSON string value, which is data; remove it by hand" in result.err


def test_crlf_and_bom_survive(project: ProjectFactory, run_cli: RunCli) -> None:
    setup(project, run_cli, {})
    project.write("src/a.py", b"\xef\xbb\xbf# TODO[aaaa]: x\r\ndef f():\r\n    return 1\r\n")
    run_cli("repair", "--import", "aaaa", "--project", project.root)
    resolve(project, run_cli, "aaaa")
    assert run_cli("sync", "--remove-resolved", "--apply", "--project", project.root).code == EXIT_OK
    assert (project.root / "src/a.py").read_bytes() == b"\xef\xbb\xbfdef f():\r\n    return 1\r\n"


@pytest.mark.parametrize("nth", [1, 2])
def test_crash_recovers_through_the_journal(
    project: ProjectFactory, run_cli: RunCli, monkeypatch: pytest.MonkeyPatch, nth: int
) -> None:
    setup(project, run_cli, {"src/a.py": PY})
    resolve(project, run_cli, "aaaa")

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
        Project.open(project.root).cleanup(dry_run=False)
    monkeypatch.undo()
    assert persistence.pending_journal(project.root)
    Project.open(project.root).scan(dry_run=False)  # rolls forward
    assert "TODO[aaaa]" not in (project.root / "src/a.py").read_text()
    assert registry(project)["aaaa"]["history"][-1]["event"] == "cleaned"
