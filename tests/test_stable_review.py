# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Regressions for the full-scope review, prioritized for the 1.0 release."""

from __future__ import annotations

import os
import runpy
import sqlite3
import sys
import zlib
from contextlib import closing
from typing import TYPE_CHECKING

import pytest

from byteplan import archive, persistence, verification
from byteplan._todo import verifies
from byteplan.api import Project
from byteplan.config import DetectConfig, load_config
from byteplan.diagnostics import Code
from byteplan.errors import ConfigError
from byteplan.files import collect_files
from byteplan.gitwrite import reconcile_staged
from byteplan.models import Representation, Status
from byteplan.scanner import scan_file
from byteplan.scanner.source import decode_source
from tests.gitutil import git
from tests.test_hatch_hook import build
from tests.test_release_guards import HOOKED

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import ProjectFactory


@verifies("8c7f")
@pytest.mark.parametrize(
    "binding",
    [
        "for todo in []:\n    pass",
        "with context() as todo:\n    pass",
        "match value:\n    case {'x': todo}:\n        pass",
        "match value:\n    case [*todo]:\n        pass",
        "match value:\n    case {**todo}:\n        pass",
        "if (todo := replacement):\n    pass",
        "[(todo := replacement) for item in items]",
        "try:\n    pass\nexcept Exception as todo:\n    pass",
        "while condition:\n    todo = replacement\n    break",
        "del todo",
        "def other(arg=(todo := replacement)):\n    return arg",
        "def other(arg: (todo := replacement)):\n    return arg",
        "def other() -> (todo := replacement):\n    return 1",
    ],
)
def test_module_bindings_prevent_decorator_edits(binding: str) -> None:
    text = f"from byteplan_runtime import todo\n{binding}\n@todo('custom')\ndef f():\n    return 1\n"
    result = scan_file(decode_source("mod.py", text.encode()), DetectConfig())
    assert not [tag for tag in result.tags if tag.representation is Representation.DECORATOR]
    assert Code.UNRESOLVED_TODO_DECORATOR in {diagnostic.code for diagnostic in result.diagnostics}


@verifies("8c7f")
@pytest.mark.parametrize("local", ["[todo for todo in items]", "lambda: (todo := 1)", "def other():\n    todo = 1"])
def test_nested_namespaces_do_not_shadow_the_runtime(local: str) -> None:
    text = f"from byteplan_runtime import todo\n{local}\n@todo('real')\ndef f():\n    return 1\n"
    result = scan_file(decode_source("mod.py", text.encode()), DetectConfig())
    assert [tag.title for tag in result.tags] == ["real"]


@verifies("8c7f")
def test_writing_scan_preserves_a_custom_decorator(project: ProjectFactory) -> None:
    project.init()
    project.write("pyproject.toml", '[tool.byteplan.annotations]\nruntime_modules = ["byteplan._todo"]\n')
    text = (
        "from byteplan._todo import todo\n"
        "for todo in [lambda title: lambda fn: fn]:\n    pass\n"
        "@todo('custom')\ndef f():\n    return 1\n"
    )
    path = project.write("module.py", text)
    Project.open(project.root).scan(dry_run=False)
    assert path.read_text() == text
    assert runpy.run_path(str(path))["f"]() == 1


@verifies("5aae")
def test_scaffold_preserves_a_conditional_test(project: ProjectFactory) -> None:
    project.init()
    project.write("a.py", "# TODO: implement f\ndef f():\n    return 1\n")
    target = project.write(
        "tests/test_a.py",
        'import sys\nif sys.version_info >= (3, 8):\n    def test_f():\n        assert False, "original coverage"\n',
    )
    project_api = Project.open(project.root)
    project_api.scan(dry_run=False)
    task_id = next(iter(project_api.load_registry().tasks))
    result = project_api.scaffold_test(task_id, link_style="managed")
    assert result.node == f"tests/test_a.py::test_f_{task_id}"
    namespace = runpy.run_path(str(target))
    with pytest.raises(AssertionError, match="original coverage"):
        namespace["test_f"]()
    assert f"test_f_{task_id}" in namespace


@verifies("ff20")
def test_archive_evidence_survives_branch_round_trip(repo: ProjectFactory) -> None:
    project = Project.open(repo.root)
    task_id = next(task.id for task in project.load_registry().tasks.values() if task.title == "second task")
    project.set_status(task_id, Status.RESOLVED)
    project.cleanup(dry_run=False)
    project.scan(dry_run=False)
    top = repo.root.parent
    git(top, "add", "-A")
    git(top, "commit", "-qm", "closed")
    project.archive(older_than=0)
    git(top, "add", "-A")
    git(top, "commit", "-qm", "old archive")
    git(top, "branch", "old")
    project.restore_archived(task_id)
    project.edit_task(task_id, priority="high")
    evidence = {"run": "proof", "fingerprint": "local-only", "tests": {}}
    verification.Evidence({task_id: evidence}, {"proof": {"head": "recorded"}}).save(repo.root)
    git(top, "add", "-A")
    git(top, "commit", "-qm", "new record")
    project.archive(older_than=0)
    git(top, "add", "-A")
    git(top, "commit", "-qm", "new archive")
    git(top, "checkout", "-q", "old")
    assert project.get_task(task_id).priority == "normal"
    git(top, "checkout", "-q", "main")
    assert project.get_task(task_id).priority == "high"
    sha = project.archive_index().tasks[task_id]["sha256"]
    payload = archive.Store(repo.root / ".byteplan").get(task_id, sha)
    assert payload is not None
    assert payload["evidence"] == evidence
    project.restore_archived(task_id)
    assert verification.Evidence.load(repo.root).tasks[task_id] == evidence


@verifies("ff20")
def test_legacy_archive_migration_preserves_all_versions_and_evidence(tmp_path: Path) -> None:
    state = tmp_path / ".byteplan"
    state.mkdir()
    old = {"task": {"id": "beef", "title": "old"}, "evidence": {"run": "proof"}, "run": {"head": "old"}}
    old_sha = archive.record_hash(old["task"])
    with closing(sqlite3.connect(state / archive.STORE)) as connection, connection:
        connection.execute(
            "CREATE TABLE tasks (id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, archived_at TEXT NOT NULL, record BLOB NOT NULL)"
        )
        connection.execute(
            "INSERT INTO tasks VALUES (?, ?, ?, ?)",
            ("beef", old_sha, "2026-10-21T00:00:00Z", zlib.compress(archive.canonical(old))),
        )
    store = archive.Store(state)
    assert store.get("beef", old_sha) == old
    new = {"task": {"id": "beef", "title": "new"}, "evidence": {"run": "new-proof"}}
    new_sha = archive.record_hash(new["task"])
    store.put([("beef", new, "2026-10-22T00:00:00Z")])
    store.put([("beef", {"task": old["task"], "evidence": None}, "2026-10-23T00:00:00Z")])
    assert store.get("beef", old_sha) == old
    assert store.get("beef", new_sha) == new
    assert store.hashes() == {("beef", old_sha), ("beef", new_sha)}


@verifies("ecf4")
@pytest.mark.parametrize(
    "consumer", ["from pkg.m import todo", "from .m import todo", "from pkg.m import *", "import pkg.m\nf = pkg.m.todo"]
)
def test_cleanup_preserves_consumed_runtime_imports(project: ProjectFactory, consumer: str) -> None:
    project.init()
    source = project.write(
        "pkg/m.py", 'from byteplan_runtime import todo\n@todo("done", id="beef")\ndef f():\n    return 1\n'
    )
    project.write("pkg/consumer.py", consumer + "\n")
    project_api = Project.open(project.root)
    project_api.import_task("beef")
    project_api.set_status("beef", Status.RESOLVED)
    project_api.cleanup(dry_run=False)
    assert "from byteplan_runtime import todo" in source.read_text()
    assert "@todo" not in source.read_text()


@verifies("ed2b")
@pytest.mark.parametrize("framework", [False, True])
def test_staged_apply_refuses_an_ordinary_pending_transaction(
    repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch, *, framework: bool
) -> None:
    source = repo.write("src/new.py", "# TODO: added\n")

    def crash(*_args: object) -> None:
        message = "interrupted"
        raise RuntimeError(message)

    with monkeypatch.context() as patch:
        patch.setattr(persistence, "_apply", crash)
        with pytest.raises(RuntimeError, match="interrupted"):
            Project.open(repo.root).scan(dry_run=False)
    git(repo.root.parent, "add", "proj/src/new.py")
    before = repo.snapshot()
    staged = git(repo.root.parent, "ls-files", "--stage").stdout
    monkeypatch.setenv("PRE_COMMIT", "1" if framework else "0")
    with pytest.raises(ConfigError, match="interrupted ordinary write"):
        reconcile_staged(repo.root)
    assert repo.snapshot() == before
    assert git(repo.root.parent, "ls-files", "--stage").stdout == staged
    Project.open(repo.root).scan(dry_run=False)
    assert not persistence.pending_journal(repo.root)
    assert "TODO[" in source.read_text()


@verifies("98d6")
@pytest.mark.parametrize(("action", "expected"), [("skip", "skipped"), ("xfail", "xfailed")])
def test_verification_rejects_skipped_teardown(project: ProjectFactory, action: str, expected: str) -> None:
    project.write(
        "test_feature.py",
        f'import pytest\n@pytest.fixture\ndef resource():\n    yield\n    pytest.{action}("cleanup unavailable")\ndef test_feature(resource):\n    assert True\n',
    )
    node = "test_feature.py::test_feature"
    result = verification.run_tests(project.root, [node], [sys.executable, "-m", "pytest"], 30)
    assert result.results[node].outcome == expected, result.output


@verifies("ac9d")
@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("def test_feature():\n    assert True\n", "passed"),
        ("import definitely_missing_module\ndef test_feature():\n    assert True\n", "error"),
    ],
)
def test_verification_with_an_ancestor_pytest_root(project: ProjectFactory, content: str, expected: str) -> None:
    (project.root.parent / "pytest.ini").write_text("[pytest]\n")
    project.write("tests/test_feature.py", content)
    node = "tests/test_feature.py::test_feature"
    result = verification.run_tests(project.root, [node], [sys.executable, "-m", "pytest"], 30)
    assert result.results[node].outcome == expected, result.output


@verifies("1e7f")
@pytest.mark.parametrize("decorator", ["todo('later', id=TASK_ID)", "verifies(*IDS)"])
@pytest.mark.parametrize("target", ["wheel", "sdist"])
def test_release_guard_rejects_dynamic_runtime_decorators(
    project: ProjectFactory, tmp_path: Path, decorator: str, target: str
) -> None:
    project.write("pyproject.toml", HOOKED)
    project.write(
        "src/demo/__init__.py",
        f'from byteplan_runtime import todo, verifies\nTASK_ID = "beef"\nIDS = ("beef",)\n@{decorator}\ndef f():\n    return 1\n',
    )
    project.init()
    result = build(project.root, tmp_path / "dist", target)
    assert result.returncode != 0
    assert "require_stripped: 1 file(s) still carry @todo/@verifies" in result.output


@verifies("ae7a")
def test_gitignore_negations_agree_in_worktree_and_snapshot(repo: ProjectFactory) -> None:
    repo.write(".gitignore", "*.py\n")
    repo.write("src/.gitignore", "!a.py\n")
    config = load_config(repo.root)
    assert collect_files(config).files == ("src/a.py",)
    git(repo.root.parent, "add", "proj/.gitignore", "proj/src/.gitignore")
    snapshot = Project.open_snapshot(repo.root)
    try:
        assert snapshot.check().scope.files == ("src/a.py",)
    finally:
        snapshot.close()
    # A directory excluded as a whole still cannot be reopened by a child ignore file.
    repo.write(".gitignore", "src/\n")
    assert not collect_files(load_config(repo.root)).files


@verifies("a740")
@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="named pipes unavailable")
def test_scan_ignores_named_pipes_without_blocking(project: ProjectFactory) -> None:
    project.init()
    project.write("a.py", "x = 1\n")
    os.mkfifo(project.root / "pipe.py")
    assert collect_files(load_config(project.root)).files == ("a.py",)
    assert Project.open(project.root).check().files_scanned == 1


@verifies("30c3")
@pytest.mark.parametrize("keyword", ['id = "beef"', 'id = (\n    "be"\n    "ef"\n)', r'id="\x62eef"'])
def test_duplicate_repair_uses_the_id_value_span(project: ProjectFactory, keyword: str) -> None:
    project.init()
    project.write("a.py", "# TODO[beef]: original\n")
    project_api = Project.open(project.root)
    project_api.import_task("beef")
    source = project.write(
        "b.py", f"from byteplan_runtime import todo\n@todo('copy id=\"beef\"', {keyword})\ndef f():\n    return 1\n"
    )
    result = project_api.reassign("b.py", 2)
    assert result.task.id != "beef"
    assert 'copy id="beef"' in source.read_text()
    assert result.task.title == 'copy id="beef"'
    assert len(project_api.load_registry().tasks) == 2
