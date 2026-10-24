# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""RC1 persistent identities, migration boundaries and explicit collision recovery."""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any

import pytest

from byteplan import api, persistence
from byteplan._todo import verifies
from byteplan.api import Project
from byteplan.errors import ConfigError, RegistryError, TaskNotFoundError
from byteplan.ids import candidate, resolve_id
from byteplan.models import Status
from byteplan.registry import dumps, loads
from tests.gitutil import frozen, git
from tests.test_formats import include_all
from tests.test_normalize import configure
from tests.test_persistence import CrashError, crash_on_replace

if TYPE_CHECKING:
    from collections.abc import Iterator

    from tests.conftest import ProjectFactory, RunCli


def legacy_registry(project: ProjectFactory) -> dict[str, Any]:
    """A schema-1 fixture with extension metadata and a real legacy task."""
    project.init()
    project.write("a.py", "# TODO[abcd]: legacy\n")
    p = Project.open(project.root)
    p.import_task("abcd")
    path = project.root / ".byteplan/tasks.json"
    data: dict[str, Any] = json.loads(path.read_text())
    data["schema_version"] = 1
    data["x-extension"] = {"keep": [1, 2]}
    data["tasks"]["abcd"]["x-task"] = {"keep": True}
    data["tasks"]["abcd"]["history"][0]["x-provenance"] = {"keep": "unknown historical metadata"}
    data["tasks"]["abcd"]["source"]["x-source"] = {"keep": True}
    data["tasks"]["abcd"]["tests"] = {"managed": [], "discovered": [], "x-links": {"keep": True}}
    path.write_text(json.dumps(data))
    return data


@verifies("8756")
def test_migration_is_explicit_lossless_and_idempotent(project: ProjectFactory, run_cli: RunCli) -> None:
    original = legacy_registry(project)
    evidence = b'{"schema_version":1,"tasks":{},"runs":{}}\n'
    project.write(".byteplan/verification.json", evidence)
    before = project.snapshot()
    assert run_cli("migrate", "--dry-run", "--project", project.root).code == 0
    assert project.snapshot() == before
    assert run_cli("migrate", "--project", project.root).code == 0
    after = json.loads((project.root / ".byteplan/tasks.json").read_text())
    assert after == {**original, "schema_version": 2}
    assert (project.root / "a.py").read_bytes() == b"# TODO[abcd]: legacy\n"
    assert (project.root / ".byteplan/verification.json").read_bytes() == evidence
    migrated = project.snapshot()
    assert run_cli("migrate", "--project", project.root).code == 0
    assert project.snapshot() == migrated


@verifies("8756")
def test_extension_metadata_survives_post_migration_writes(project: ProjectFactory) -> None:
    original = legacy_registry(project)
    p = Project.open(project.root)
    p.migrate()
    p.edit_task("abcd", notes="ordinary post-upgrade edit")
    p.scan(dry_run=False)
    current = json.loads((project.root / ".byteplan/tasks.json").read_text())
    old, new = original["tasks"]["abcd"], current["tasks"]["abcd"]
    assert current["x-extension"] == original["x-extension"]
    assert new["x-task"] == old["x-task"]
    assert new["history"][0] == old["history"][0]
    assert new["source"]["x-source"] == old["source"]["x-source"]
    assert new["tests"]["x-links"] == old["tests"]["x-links"]


@verifies("8756")
@pytest.mark.parametrize("after_replace", [False, True])
def test_interrupted_migration_recovers_before_source_allocation(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch, *, after_replace: bool
) -> None:
    original = legacy_registry(project)
    project.write("new.py", "# TODO: next task\n")
    p = Project.open(project.root)
    if after_replace:

        def fail_finish(*_: Any) -> None:
            raise CrashError

        monkeypatch.setattr(persistence, "_finish", fail_finish)
    else:
        crash_on_replace(monkeypatch, 1)
    with pytest.raises(CrashError):
        p.migrate()
    monkeypatch.undo()
    assert persistence.pending_journal(project.root)
    assert (project.root / "new.py").read_text() == "# TODO: next task\n"
    p.migrate()
    current = json.loads((project.root / ".byteplan/tasks.json").read_text())
    assert current == {**original, "schema_version": 2}
    assert not persistence.pending_journal(project.root)
    p.scan(dry_run=False)
    assert len(p.list_tasks()) == 2


@verifies("8756")
@pytest.mark.parametrize("dry_run", [False, True])
def test_legacy_allocation_requires_migration_without_source_changes(project: ProjectFactory, *, dry_run: bool) -> None:
    legacy_registry(project)
    project.write("new.py", "# TODO: new\n")
    before = project.snapshot()
    with pytest.raises(RegistryError, match="byteplan migrate"):
        Project.open(project.root).scan(dry_run=dry_run)
    # A writing attempt may create its normal lock directory, but no file changes.
    assert project.snapshot() == before


@verifies("8756")
def test_schema_one_metadata_writes_preserve_the_version(project: ProjectFactory) -> None:
    legacy_registry(project)
    p = Project.open(project.root)
    p.edit_task("abcd", notes="legacy edits remain supported")
    assert p.load_registry().schema_version == 1
    with pytest.raises(RegistryError, match="schema version 1"):
        loads('{"schema_version":1,"reserved_ids":["abcdef"],"tasks":{}}')


@verifies("c978")
@pytest.mark.parametrize("task_id", ["abcd", "abcdef", "abcdef0123456789"])
@pytest.mark.parametrize("format_", ["python", "markdown", "json", "jsonc", "decorator"])
def test_supported_id_lengths_round_trip_across_scanners(project: ProjectFactory, task_id: str, format_: str) -> None:
    project.init()
    include_all(project)
    formats = {
        "python": ("a.py", f"# TODO[{task_id}]: retained\n"),
        "markdown": ("a.md", f"<!-- TODO[{task_id}]: retained -->\n"),
        "json": ("a.json", f'{{"task": "TODO[{task_id}]: retained"}}\n'),
        "jsonc": ("a.jsonc", f"// TODO[{task_id}]: retained\n{{}}\n"),
        "decorator": (
            "a.py",
            f'from byteplan_runtime import todo\n@todo("retained", id="{task_id}")\ndef f():\n    return 1\n',
        ),
    }
    rel, text = formats[format_]
    source = project.write(rel, b"\xef\xbb\xbf" + text.replace("\n", "\r\n").encode())
    original = source.read_bytes()
    p = Project.open(project.root)
    p.import_task(task_id)
    p.scan(dry_run=False)
    assert p.get_task(task_id).id == task_id
    assert source.read_bytes() == original
    assert p.scan(dry_run=False).written == ()


@verifies("c978")
@pytest.mark.parametrize("suffix", ["py", "md", "json", "jsonc"])
def test_new_ids_use_six_characters_and_preserve_source_encoding(project: ProjectFactory, suffix: str) -> None:
    project.init()
    include_all(project)
    content = {
        "py": "# TODO: new\r\nx = 1\r\n",
        "md": "<!-- TODO: new -->\r\n",
        "json": '{"x": "TODO: new"}\r\n',
        "jsonc": "// TODO: new\r\n{}\r\n",
    }[suffix]
    source = project.write(f"a.{suffix}", b"\xef\xbb\xbf" + content.encode())
    p = Project.open(project.root)
    report = p.scan(dry_run=False)
    task_id = report.summary.added[0]
    assert len(task_id) == 6
    after = source.read_bytes()
    assert after.startswith(b"\xef\xbb\xbf")
    assert b"\n" not in after.replace(b"\r\n", b"")
    assert after.replace(f"[{task_id}]".encode(), b"") == b"\xef\xbb\xbf" + content.encode()


@verifies("c978")
def test_exact_identity_precedes_prefix_and_ambiguity_is_actionable(project: ProjectFactory) -> None:
    project.init()
    project.write("a.py", "# TODO[abcd]: legacy\n# TODO[abcdef]: first\n# TODO[abcdff01]: second\n")
    p = Project.open(project.root)
    for identity in ("abcd", "abcdef", "abcdff01"):
        p.import_task(identity)
    assert p.get_task("ABCD").id == "abcd"
    assert p.get_task("abcde").id == "abcdef"
    p.set_status("abcde", Status.IN_PROGRESS)
    assert p.get_task("abcdef").status is Status.IN_PROGRESS
    with pytest.raises(ConfigError, match=r"ambiguous.*abcd.*abcdef.*abcdff01.*exact task ID"):
        p.set_status("abc", Status.RESOLVED)
    assert p.get_task("abcd").status is Status.OPEN
    for query in ("", "xyz", "abcdfe"):
        with pytest.raises(TaskNotFoundError):
            p.get_task(query)
    assert resolve_id("abcde", {"abcdef", "abcdff01"}) == "abcdef"


@verifies("c978")
def test_persisted_verification_references_do_not_resolve_prefixes(project: ProjectFactory) -> None:
    project.init()
    project.write("a.py", "# TODO[abcdef]: task\n")
    project.write(
        "tests/test_a.py", 'from byteplan_runtime import verifies\n@verifies("abcde")\ndef test_a():\n    assert True\n'
    )
    p = Project.open(project.root)
    p.import_task("abcdef")
    report = p.scan(dry_run=False)
    assert any(str(d.code) == "unknown_task_reference" and d.task_id == "abcde" for d in report.diagnostics)
    assert not p.get_task("abcdef").linked_tests()


@verifies("c978", "8756")
def test_staged_legacy_allocation_refuses_without_index_or_source_changes(
    repo: ProjectFactory, run_cli: RunCli
) -> None:
    path = repo.root / ".byteplan/tasks.json"
    data = json.loads(path.read_text())
    # Use the fixture's legacy copy from an actual legacy task instead of relabelling six-ID records.
    data["schema_version"] = 1
    data["reserved_ids"] = []
    data["tasks"] = {}
    path.write_text(json.dumps(data))
    repo.write("src/a.py", "# TODO: new legacy task\n")
    repo.write("src/b.py", "x = 1\n")
    git(repo.root, "add", "-A")
    index_before = git(repo.root, "write-tree").stdout
    source_before = (repo.root / "src/a.py").read_bytes()
    result = run_cli("scan", "--staged", "--apply", "--project", repo.root)
    assert result.code == 2
    assert "byteplan migrate" in result.err
    assert git(repo.root, "write-tree").stdout == index_before
    assert (repo.root / "src/a.py").read_bytes() == source_before


@verifies("c978")
def test_expanded_registry_round_trip() -> None:
    text = '{"schema_version":2,"reserved_ids":["abcd","abcdef","abcdef0123456789"],"tasks":{}}'
    assert json.loads(dumps(loads(text))) == json.loads(text)


@verifies("1b81", "8756")
def test_init_rejects_future_schema_before_writing_any_source(project: ProjectFactory, run_cli: RunCli) -> None:
    project.write(".byteplan/tasks.json", '{"schema_version":99,"tasks":{}}\n')
    before = project.snapshot()
    result = run_cli("init", "--runtime-shim", "src/shim.py", "--project", project.root)
    assert result.code == 2
    assert "newer than" in result.err
    assert project.snapshot() == before


@verifies("c978")
def test_archived_exact_identity_precedes_active_prefix(repo: ProjectFactory) -> None:
    repo.write("legacy.py", "# TODO[abcd]: archive this\n")
    repo.write("long.py", "# TODO[abcdef]: active\n")
    p = Project.open(repo.root)
    p.import_task("abcd")
    p.import_task("abcdef")
    p.set_status("abcd", Status.RESOLVED)
    p.cleanup(["abcd"], dry_run=False)
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "archive legacy identity")
    assert "abcd" in p.archive(older_than=0).tasks
    assert p.get_task("abcd").title == "archive this"
    with pytest.raises(ConfigError, match="ambiguous"):
        p.get_task("abc")
    assert p.get_task("abcde").id == "abcdef"
    p.restore_archived("abcd")
    assert "abcd" in p.load_registry().tasks


@verifies("c978")
def test_malformed_pytest_marker_is_diagnosed(project: ProjectFactory) -> None:
    project.init()
    config = project.root / "pyproject.toml"
    config.write_text(config.read_text() + "\n[tool.byteplan.tests]\npytest_marker = true\n")
    project.write(
        "test_a.py", 'import pytest\n@pytest.mark.byteplan("not-hex", "abcdef")\ndef test_a():\n    assert True\n'
    )
    report = Project.open(project.root).scan()
    assert any(str(d.code) == "malformed_id" for d in report.diagnostics)
    assert report.links[0].task_ids == ("abcdef",)


@verifies("edc2")
@pytest.mark.parametrize("filename", [".byteplan/tasks.json", ".byteplan/verification.json", ".byteplan/archive.json"])
@pytest.mark.parametrize("damage", ["markers", "duplicate", "partial"])
def test_check_rejects_inconsistent_merge_records_without_writes(
    project: ProjectFactory, run_cli: RunCli, filename: str, damage: str
) -> None:
    project.init()
    contents = {
        "markers": "<<<<<<< ours\n{}\n=======\n{}\n>>>>>>> theirs\n",
        "duplicate": '{"schema_version":2,"tasks":{},"tasks":{}}\n',
        "partial": '{"schema_version":',
    }
    project.write(filename, contents[damage])
    before = project.snapshot()
    result = run_cli("check", "--project", project.root)
    assert result.code == 2, result.out + result.err
    assert "conflict" in result.err or "JSON" in result.err or "unreadable" in result.err
    assert project.snapshot() == before


@verifies("edc2")
def test_staged_check_validates_staged_evidence_not_worktree(repo: ProjectFactory, run_cli: RunCli) -> None:
    path = repo.write(".byteplan/verification.json", '{"schema_version":1,"tasks":{},"tasks":{}}\n')
    git(repo.root, "add", ".byteplan/verification.json")
    path.write_text('{"schema_version":1,"tasks":{},"runs":{}}\n')
    before = frozen(repo)
    assert run_cli("check", "--project", repo.root).code == 0
    result = run_cli("check", "--staged", "--project", repo.root)
    assert result.code == 2
    assert "duplicate JSON key" in result.err
    assert frozen(repo) == before


@verifies("c978", "edc2")
@pytest.mark.parametrize("driver", [False, True])
def test_divergent_branch_identity_collisions_fail_explicitly(
    repo: ProjectFactory, run_cli: RunCli, monkeypatch: pytest.MonkeyPatch, *, driver: bool
) -> None:
    if driver:
        assert run_cli("git", "install-merge-driver", "--project", repo.root).code == 0
        git(repo.root, "add", "-A")
        git(repo.root, "commit", "-qm", "driver")
    base = git(repo.root, "rev-parse", "HEAD").stdout.strip()
    collision = candidate("independently developed branch collision", 0)
    assert collision not in Project.open(repo.root).load_registry().reserved_ids
    monkeypatch.setattr(api, "allocate", lambda *_: collision)
    for branch in ("left", "right"):
        git(repo.root, "switch", "-q", "-c", branch, base)
        repo.write(f"src/{branch}.py", f"# TODO: work on {branch}\n")
        p = Project.open(repo.root)
        assert p.scan(dry_run=False).summary.added == [collision]
        p.edit_task(collision, notes=f"preserve {branch} branch metadata")
        git(repo.root, "add", "-A")
        git(repo.root, "commit", "-qm", branch)
    result = git(repo.root, "merge", "--no-edit", "left", check=False)
    assert result.returncode != 0
    before = frozen(repo)
    assert run_cli("check", "--project", repo.root).code == 2
    assert frozen(repo) == before
    assert (repo.root / "src/left.py").exists()
    assert (repo.root / "src/right.py").exists()
    # Neither branch's canonical record/evidence history is silently selected or erased.
    for branch in ("left", "right"):
        records = json.loads(git(repo.root, "show", f"{branch}:proj/.byteplan/tasks.json").stdout)
        assert records["tasks"][collision]["notes"] == f"preserve {branch} branch metadata"


@verifies("edc2")
@pytest.mark.parametrize(
    "tests",
    [
        [],
        {"a.py::test_a": []},
        {"a.py::test_a": {"outcome": "invented"}},
        {"a.py::test_a": {"outcome": "passed", "duration_ms": -1}},
    ],
)
def test_check_rejects_malformed_nested_evidence(project: ProjectFactory, run_cli: RunCli, tests: Any) -> None:
    project.init()
    project.write(
        ".byteplan/verification.json",
        json.dumps({"schema_version": 1, "tasks": {"abcdef": {"tests": tests}}, "runs": {}}),
    )
    before = project.snapshot()
    result = run_cli("check", "--project", project.root)
    assert result.code == 2
    assert "malformed test evidence" in result.err
    assert project.snapshot() == before


@verifies("c978")
def test_sync_rechecks_prefix_after_acquiring_write_context(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project.init()
    configure(project)
    project.write("a.py", "# TODO[abcdef]: first\ndef a():\n    return 1\n")
    p = Project.open(project.root)
    p.import_task("abcdef")
    before = (project.root / "a.py").read_bytes()
    original_writing = p._writing  # noqa: SLF001 - inject a writer at the transaction boundary

    @contextlib.contextmanager
    def concurrent_creation() -> Iterator[tuple[str, ...]]:
        project.write("b.py", "# TODO[abcfff]: concurrent\ndef b():\n    return 2\n")
        Project.open(project.root).import_task("abcfff")
        with original_writing() as recovered:
            yield recovered

    monkeypatch.setattr(p, "_writing", concurrent_creation)
    with pytest.raises(ConfigError, match="ambiguous"):
        p.sync(["abc"], dry_run=False)
    assert (project.root / "a.py").read_bytes() == before
