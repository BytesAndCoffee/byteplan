# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Explicit pre-merge identity repair preserves the original branch's work."""

from __future__ import annotations

import codecs
import json
from typing import TYPE_CHECKING, Any

import pytest

from byteplan import api, gitio, persistence, verification
from byteplan._todo import verifies
from byteplan.api import Project
from byteplan.errors import ConfigError, LockedError
from byteplan.ids import allocate, candidate
from byteplan.models import Status
from tests.gitutil import frozen, git
from tests.test_formats import include_all
from tests.test_persistence import CrashError, crash_on_replace

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory, RunCli


def divergent(repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch, *, legacy: bool = False) -> str:
    """Force the allocator's rare cross-branch collision, then restore real allocation."""
    base = git(repo.root, "rev-parse", "HEAD").stdout.strip()
    collision = candidate("independent collision repair", 0)
    if legacy:
        collision = collision[:4]
    for branch in ("left", "right"):
        git(repo.root, "switch", "-q", "-c", branch, base)
        repo.write(f"src/{branch}.py", f"# TODO: work on {branch}\n")
        p = Project.open(repo.root)
        with monkeypatch.context() as allocator:
            allocator.setattr(api, "allocate", lambda *_: collision)
            assert p.scan(dry_run=False).summary.added == [collision]
        p.edit_task(collision, notes=f"preserve {branch}", priority="high", assignee=branch, add_labels=["release:1.0"])
        p.set_status(collision, Status.IN_PROGRESS)
        git(repo.root, "add", "-A")
        git(repo.root, "commit", "-qm", branch)
    return collision


def references(repo: ProjectFactory, old: str) -> None:
    """Escaped, concatenated and multiline references alongside an unrelated equal string."""
    config = repo.root / "pyproject.toml"
    config.write_text(config.read_text() + "\n[tool.byteplan.tests]\npytest_marker = true\n")
    escaped = "".join(f"\\x{ord(c):02x}" for c in old)
    shared = next(t for t in Project.open(repo.root).load_registry().tasks if t != old)
    source = (
        "from byteplan_runtime import verifies as checks\nfrom pytest import mark as m\n"
        f"unrelated = '{old}'\n"
        f"@checks(\n    '{escaped}', '{shared}',\n)\ndef test_reference():\n    assert True\n"
        f"@m.byteplan(('{old[:3]}'\n             '{old[3:]}'))\ndef test_marker():\n    assert True\n"
        "# TODO: following task\n"
    )
    repo.write("tests/test_right.py", codecs.BOM_UTF8 + source.replace("\n", "\r\n").encode())
    p = Project.open(repo.root)
    p.scan(dry_run=False)
    task = p.get_task(old)
    entry = {
        "fingerprint": verification.fingerprint(repo.root, verification.task_files(task)),
        "run": "original",
        "tests": {node: {"outcome": "passed", "duration_ms": 7} for node in task.linked_tests()},
        "x-provenance": {"keep": old},
    }
    shared_task = p.get_task(shared)
    shared_entry = {**entry, "fingerprint": verification.fingerprint(repo.root, verification.task_files(shared_task))}
    head = git(repo.root, "rev-parse", "HEAD").stdout.strip()
    repo.write(
        verification.STORE,
        json.dumps(
            {
                "schema_version": 1,
                "tasks": {old: entry, shared: shared_entry},
                "runs": {
                    "original": {
                        "head": head,
                        "dirty": False,
                        "argv": ["pytest"],
                        "at": "original",
                        "python": "3",
                        "timed_out": False,
                    },
                    "orphaned": {"keep": True},
                },
                "x-store": old,
            }
        ),
    )
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "references and evidence")


@verifies("c978", "edc2", "2650ec")
@pytest.mark.parametrize("driver", [False, True])
@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("autocrlf", [False, True])
def test_premerge_rekey_preserves_both_original_records(
    repo: ProjectFactory,
    run_cli: RunCli,
    monkeypatch: pytest.MonkeyPatch,
    *,
    driver: bool,
    legacy: bool,
    autocrlf: bool,
) -> None:
    git(repo.root, "config", "core.autocrlf", str(autocrlf).lower())
    if driver:
        assert run_cli("git", "install-merge-driver", "--project", repo.root).code == 0
        git(repo.root, "add", "-A")
        git(repo.root, "commit", "-qm", "driver")
    old = divergent(repo, monkeypatch, legacy=legacy)
    p = Project.open(repo.root)
    original = p.get_task(old)
    before = frozen(repo)
    preview = p.reassign("src/right.py", 1, against="left", dry_run=True)
    assert preview.dry_run
    assert preview.written == ()
    assert frozen(repo) == before
    result = p.reassign("src/right.py", 1, against="left")
    assert result.task.id == preview.task.id
    new = result.task.id
    assert new != old
    assert len(new) == 6
    assert result.task.notes == original.notes
    assert result.task.status == original.status
    assert result.task.priority == original.priority
    assert result.task.assignee == original.assignee
    assert result.task.labels == original.labels
    assert result.task.history[: len(original.history)] == original.history
    assert {old, new} <= p.load_registry().reserved_ids
    event = next(e for e in result.task.history if e.event == "identity_reassigned")
    assert event.old == old
    assert event.new["against"] == git(repo.root, "rev-parse", "left").stdout.strip()
    assert not (repo.root.parent / ".git/index.lock").exists()
    assert git(repo.root, "diff", "--cached", "--name-only").stdout == ""
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "rekey independent right task")
    merge = git(repo.root, "merge", "--no-edit", "left", check=False)
    if driver:
        assert merge.returncode == 0, merge.stdout + merge.stderr
    if merge.returncode == 0:
        registry = Project.open(repo.root).load_registry()
        assert registry.tasks[old].notes == "preserve left"
        assert registry.tasks[new].notes == "preserve right"
        registry_path = repo.root / ".byteplan/tasks.json"
        merged_bytes = registry_path.read_bytes()
        merged_files = frozen(repo)
        first_scan = Project.open(repo.root).scan(dry_run=False)
        normalized_bytes = registry_path.read_bytes()
        assert json.loads(normalized_bytes) == json.loads(merged_bytes)
        assert normalized_bytes == merged_bytes.replace(b"\r\n", b"\n")
        expected_written = () if normalized_bytes == merged_bytes else (".byteplan/tasks.json",)
        assert first_scan.written == expected_written
        after_files = frozen(repo)
        assert {key: value for key, value in after_files.items() if key != "proj/.byteplan/tasks.json"} == {
            key: value for key, value in merged_files.items() if key != "proj/.byteplan/tasks.json"
        }
        assert Project.open(repo.root).scan(dry_run=False).written == ()
    else:
        # Ordinary Git is allowed to conflict; both independent records must remain available.
        before = frozen(repo)
        assert run_cli("check", "--project", repo.root).code == 2
        assert frozen(repo) == before
        for branch, task_id in (("left", old), ("right", new)):
            stored = json.loads(git(repo.root, "show", f"{branch}:proj/.byteplan/tasks.json").stdout)
            assert stored["tasks"][task_id]["notes"] == f"preserve {branch}"


@verifies("c978")
@pytest.mark.parametrize("stale_on", ["files", "head"])
def test_rekey_rewrites_exact_references_and_retains_stale_evidence(
    repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch, stale_on: str
) -> None:
    old = divergent(repo, monkeypatch)
    references(repo, old)
    p = Project.open(repo.root)
    before = json.loads((repo.root / verification.STORE).read_bytes())
    result = p.reassign("src/right.py", 1, against="left")
    new = result.task.id
    after = json.loads((repo.root / verification.STORE).read_bytes())
    assert after == {**before, "tasks": {new if key == old else key: value for key, value in before["tasks"].items()}}
    source = (repo.root / "tests/test_right.py").read_bytes()
    assert source.startswith(codecs.BOM_UTF8)
    assert source.count(b"\n") == source.count(b"\r\n")
    assert f"unrelated = '{old}'".encode() in source
    assert source.count(new.encode()) == 2
    assert Project.open(repo.root).scan(dry_run=False).written == ()
    registry = p.load_registry()
    following = next(t for t in registry.tasks.values() if t.title == "following task")
    assert following.source is not None
    assert (
        following.source.line
        == source.decode("utf-8-sig")
        .splitlines()
        .index(next(line for line in source.decode("utf-8-sig").splitlines() if "following task" in line))
        + 1
    )
    ready = verification.readiness(
        result.task,
        verification.Evidence.load(repo.root),
        repo.root,
        stale_on=stale_on,
        head=verification.git_state(repo.root),
    )
    assert set(ready.tests.values()) == {"stale"}
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "rekey")
    ready = verification.readiness(
        result.task,
        verification.Evidence.load(repo.root),
        repo.root,
        stale_on=stale_on,
        head=verification.git_state(repo.root),
    )
    assert set(ready.tests.values()) == {"stale"}


@verifies("c978")
@pytest.mark.parametrize("nth", [1, 2, 3, 4])
def test_interrupted_rekey_recovers_all_source_evidence_and_registry(
    repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch, nth: int
) -> None:
    old = divergent(repo, monkeypatch)
    references(repo, old)
    p = Project.open(repo.root)
    planned = p.reassign("src/right.py", 1, against="left", dry_run=True)
    original = verification.Evidence.load(repo.root).tasks[old]
    crash_on_replace(monkeypatch, nth)
    with pytest.raises(CrashError):
        p.reassign("src/right.py", 1, against="left")
    monkeypatch.undo()
    assert not (repo.root.parent / ".git/index.lock").exists()
    assert persistence.pending_journal(repo.root)
    p.scan(dry_run=False)
    assert not persistence.pending_journal(repo.root)
    assert p.get_task(planned.task.id).notes == "preserve right"
    assert verification.Evidence.load(repo.root).tasks[planned.task.id] == original
    assert p.scan(dry_run=False).written == ()


@verifies("c978")
def test_rekey_refuses_inherited_identity(repo: ProjectFactory) -> None:
    p = Project.open(repo.root)
    task = next(iter(p.load_registry().tasks.values()))
    assert task.source is not None
    git(repo.root, "branch", "left")
    p.edit_task(task.id, notes="different metadata is not independent creation")
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "metadata")
    before = frozen(repo)
    with pytest.raises(ConfigError, match=r"already existed in merge base|creation provenance"):
        p.reassign(task.source.path, task.source.line, against="left")
    assert frozen(repo) == before


@verifies("c978")
@pytest.mark.parametrize(
    "problem", ["index-lock", "alternate-index", "pending", "unknown-mapping", "ignored", "dynamic", "head-change"]
)
def test_rekey_refuses_unsafe_context_without_changes(
    repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch, problem: str
) -> None:
    old = divergent(repo, monkeypatch)
    p = Project.open(repo.root)
    if problem == "index-lock":
        (repo.root.parent / ".git/index.lock").write_text("another Git process")
    elif problem == "alternate-index":
        monkeypatch.setenv("GIT_INDEX_FILE", str(repo.root.parent / ".git/index"))
    elif problem == "pending":
        pending = repo.root / ".byteplan/txn/journal.json"
        pending.parent.mkdir(exist_ok=True)
        pending.write_text("{}")
    elif problem == "unknown-mapping":
        path = repo.root / ".byteplan/tasks.json"
        data = json.loads(path.read_bytes())
        data["tasks"][old]["x-mapping"] = {"task_id": old}
        path.write_text(json.dumps(data))
    elif problem == "ignored":
        repo.write(
            "ignored.py",
            f"# byteplan: ignore-file\nfrom byteplan_runtime import verifies\n@verifies('{old}')\ndef test_hidden():\n    pass\n",
        )
    elif problem == "dynamic":
        repo.write(
            "dynamic.py", "from byteplan_runtime import verifies\n@verifies(make_id())\ndef test_dynamic():\n    pass\n"
        )
    elif problem == "marker-keyword":
        config = repo.root / "pyproject.toml"
        config.write_text(config.read_text() + "\n[tool.byteplan.tests]\npytest_marker = true\n")
        repo.write(
            "keyword.py", f"import pytest\n@pytest.mark.byteplan(task_id='{old}')\ndef test_keyword():\n    return 1\n"
        )
    else:
        original_git = gitio.git
        calls = {"heads": 0}

        def changed_head(args: list[str], *pos: Any, **kw: Any) -> str:
            if args == ["rev-parse", "--verify", "HEAD"]:
                calls["heads"] += 1
                return "0" * 40
            return original_git(args, *pos, **kw)

        monkeypatch.setattr(gitio, "git", changed_head)
    before = frozen(repo)
    with pytest.raises((ConfigError, LockedError)):
        p.reassign("src/right.py", 1, against="left")
    assert frozen(repo) == before


@verifies("c978")
def test_collision_cli_preview_and_apply(
    repo: ProjectFactory, run_cli: RunCli, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = divergent(repo, monkeypatch)
    before = frozen(repo)
    preview = run_cli(
        "repair", "--reassign", "src/right.py:1", "--against", "left", "--dry-run", "--project", repo.root
    )
    assert preview.code == 0, preview.err
    assert f"would reassign [{old}]" in preview.out
    assert "pinned HEAD" in preview.out
    assert frozen(repo) == before
    actual = run_cli("repair", "--reassign", "src/right.py:1", "--against", "left", "--project", repo.root)
    assert actual.code == 0, actual.err
    assert "Historical evidence is retained" in actual.out


@verifies("c978")
def test_rekey_preserves_unknown_fields_and_historical_old_identity(
    repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    old = divergent(repo, monkeypatch)
    path = repo.root / ".byteplan/tasks.json"
    data = json.loads(path.read_bytes())
    record = data["tasks"][old]
    record["x-task"] = {"future": ["keep"]}
    record["source"]["x-source"] = [1, 2]
    record.setdefault("tests", {"managed": [], "discovered": []})["x-links"] = {"keep": True}
    record["history"][0]["x-history"] = {"identity": old}
    path.write_text(json.dumps(data))
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "preserved extension provenance")
    p = Project.open(repo.root)
    task = p.reassign("src/right.py", 1, against="left").task
    after = json.loads(path.read_bytes())["tasks"][task.id]
    assert after["x-task"] == record["x-task"]
    assert after["source"]["x-source"] == record["source"]["x-source"]
    assert after["tests"]["x-links"] == record["tests"]["x-links"]
    assert after["history"][: len(record["history"])] == record["history"]
    assert p.scan(dry_run=False).written == ()


@verifies("c978")
@pytest.mark.parametrize("representation", ["decorator", "markdown", "jsonc"])
def test_rekey_preserves_supported_primary_annotation_formats(
    repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch, representation: str
) -> None:
    include_all(repo)
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "include supported files")
    old = divergent(repo, monkeypatch)
    (repo.root / "src/right.py").unlink()
    if representation == "decorator":
        path, line = "src/right.py", 2
        text = f'from byteplan_runtime import todo\n@todo("café work on right", id=("{old[:3]}"\n "{old[3:]}"))\ndef work():\n    return 1\n'
    elif representation == "markdown":
        path, line = "right.md", 2
        text = f"# Work\n<!-- TODO[{old}]: work on right -->\n"
    else:
        path, line = "right.jsonc", 2
        text = f'{{\n  // TODO[{old}]: work on right\n  "keep": "{old}"\n}}\n'
    repo.write(path, codecs.BOM_UTF8 + text.replace("\n", "\r\n").encode())
    p = Project.open(repo.root)
    p.scan(dry_run=False)
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "primary format")
    result = p.reassign(path, line, against="left")
    after = (repo.root / path).read_bytes()
    assert result.task.notes == "preserve right"
    assert result.task.id.encode() in after
    assert after.startswith(codecs.BOM_UTF8)
    assert after.count(b"\n") == after.count(b"\r\n")
    if representation == "jsonc":
        assert f'"keep": "{old}"'.encode() in after
    assert p.scan(dry_run=False).written == ()


@verifies("c978")
def test_rekey_refuses_identity_reserved_in_merge_base(repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    path = repo.root / ".byteplan/tasks.json"
    original = json.loads(path.read_bytes())
    old = candidate("independent collision repair", 0)
    original["reserved_ids"].append(old)
    path.write_text(json.dumps(original))
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "old historical reservation")
    divergent(repo, monkeypatch)
    before = frozen(repo)
    with pytest.raises(ConfigError, match="already existed in merge base"):
        Project.open(repo.root).reassign("src/right.py", 1, against="left")
    assert frozen(repo) == before


@verifies("c978")
def test_rekey_refuses_unresolved_merge(repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    divergent(repo, monkeypatch)
    assert git(repo.root, "merge", "--no-edit", "left", check=False).returncode != 0
    before = frozen(repo)
    with pytest.raises(ConfigError, match=r"unmerged|conflict|Git operation"):
        Project.open(repo.root).reassign("src/right.py", 1, against="left")
    assert frozen(repo) == before


@verifies("c978")
def test_rekey_accepts_empty_valid_evidence_store(repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    divergent(repo, monkeypatch)
    original = b'{"schema_version": 1, "runs": {"retained": {}}}\n'
    repo.write(verification.STORE, original)
    Project.open(repo.root).reassign("src/right.py", 1, against="left")
    assert (repo.root / verification.STORE).read_bytes() == original


@verifies("c978")
@pytest.mark.parametrize("dry_run", [False, True])
def test_rekey_refuses_resolved_but_uncommitted_merge(
    repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch, *, dry_run: bool
) -> None:
    divergent(repo, monkeypatch)
    assert git(repo.root, "merge", "--no-edit", "left", check=False).returncode != 0
    git(repo.root, "checkout", "--theirs", ".byteplan/tasks.json")
    git(repo.root, "add", ".byteplan/tasks.json")
    assert git(repo.root, "ls-files", "--unmerged").stdout == ""
    before = frozen(repo)
    with pytest.raises(ConfigError, match="Git operation MERGE_HEAD"):
        Project.open(repo.root).reassign("src/right.py", 1, against="left", dry_run=dry_run)
    assert frozen(repo) == before


@verifies("c978")
@pytest.mark.parametrize(
    "operation", ["CHERRY_PICK_HEAD", "REVERT_HEAD", "REBASE_HEAD", "rebase-merge", "rebase-apply", "sequencer"]
)
def test_rekey_refuses_other_pending_git_operations(
    repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    divergent(repo, monkeypatch)
    path = repo.root.parent / ".git" / operation
    if operation.isupper():
        path.write_text(git(repo.root, "rev-parse", "HEAD").stdout)
    else:
        path.mkdir()
    before = frozen(repo)
    with pytest.raises(ConfigError, match=f"Git operation {operation}"):
        Project.open(repo.root).reassign("src/right.py", 1, against="left")
    assert frozen(repo) == before


@verifies("c978")
@pytest.mark.parametrize("spelling", ["escaped", "concatenated"])
def test_rekey_refuses_ignored_encoded_identity_references(
    repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch, spelling: str
) -> None:
    old = divergent(repo, monkeypatch)
    literal = (
        repr(old[:3]) + " " + repr(old[3:])
        if spelling == "concatenated"
        else "'" + "".join(f"\\x{ord(c):02x}" for c in old) + "'"
    )
    repo.write(
        "hidden.py",
        f"# BytePlan: ignore-file\nfrom byteplan_runtime import verifies\n@verifies({literal})\ndef test_hidden():\n    return 1\n",
    )
    before = frozen(repo)
    with pytest.raises(ConfigError, match="ignored identity context"):
        Project.open(repo.root).reassign("src/right.py", 1, against="left")
    assert frozen(repo) == before


@verifies("c978")
def test_rekey_refuses_cherry_picked_shared_task_identity(
    repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = git(repo.root, "rev-parse", "HEAD").stdout.strip()
    old = divergent(repo, monkeypatch)
    git(repo.root, "reset", "--hard", base)
    git(repo.root, "cherry-pick", "left")
    p = Project.open(repo.root)
    p.edit_task(old, notes="same task, new notes on cherry-picked branch")
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "shared task metadata")
    before = frozen(repo)
    with pytest.raises(ConfigError, match="creation provenance"):
        p.reassign("src/left.py", 1, against="left")
    assert frozen(repo) == before


@verifies("c978")
def test_rekey_refuses_rewritten_local_lineage(repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    old = divergent(repo, monkeypatch)
    path = repo.root / ".byteplan/tasks.json"
    data = json.loads(path.read_bytes())
    data["tasks"][old]["history"][0]["new"]["path"] = "src/wrong.py"
    path.write_text(json.dumps(data))
    before = frozen(repo)
    with pytest.raises(ConfigError, match="original lineage"):
        Project.open(repo.root).reassign("src/right.py", 1, against="left")
    assert frozen(repo) == before


@verifies("c978", "edc2")
@pytest.mark.parametrize("driver", [False, True])
def test_rekey_then_merge_preserves_both_branches_evidence(
    repo: ProjectFactory, run_cli: RunCli, monkeypatch: pytest.MonkeyPatch, *, driver: bool
) -> None:
    if driver:
        assert run_cli("git", "install-merge-driver", "--project", repo.root).code == 0
        git(repo.root, "add", "-A")
        git(repo.root, "commit", "-qm", "driver")
    old = divergent(repo, monkeypatch)
    references(repo, old)
    right_evidence = json.loads((repo.root / verification.STORE).read_bytes())
    git(repo.root, "switch", "-q", "left")
    repo.write(
        "tests/test_left.py",
        f"from byteplan_runtime import verifies\n@verifies('{old}')\ndef test_left():\n    return 1\n",
    )
    p = Project.open(repo.root)
    p.scan(dry_run=False)
    task = p.get_task(old)
    left_evidence: dict[str, Any] = {
        "schema_version": 1,
        "tasks": {
            old: {
                "fingerprint": verification.fingerprint(repo.root, verification.task_files(task)),
                "run": "left-run",
                "tests": {"tests/test_left.py::test_left": {"outcome": "passed", "duration_ms": 11}},
            }
        },
        "runs": {
            "left-run": {
                "keep": "left provenance",
                "head": None,
                "dirty": False,
                "argv": ["pytest"],
                "at": "left",
                "python": "3",
                "timed_out": False,
            }
        },
    }
    repo.write(verification.STORE, json.dumps(left_evidence, indent=2, sort_keys=True) + "\n")
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "left evidence")
    git(repo.root, "switch", "-q", "right")
    result = Project.open(repo.root).reassign("src/right.py", 1, against="left")
    new = result.task.id
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "right rekey with preserved evidence")
    merge = git(repo.root, "merge", "--no-edit", "left", check=False)
    if merge.returncode == 0:
        evidence = verification.Evidence.load(repo.root)
        assert evidence.tasks[old] == left_evidence["tasks"][old]
        assert evidence.tasks[new] == right_evidence["tasks"][old]
        assert evidence.runs["left-run"] == left_evidence["runs"]["left-run"]
        assert evidence.runs["original"] == right_evidence["runs"]["original"]
        registry = Project.open(repo.root).load_registry()
        assert registry.tasks[old].notes == "preserve left"
        assert registry.tasks[new].notes == "preserve right"
    else:
        before = frozen(repo)
        assert run_cli("check", "--project", repo.root).code == 2
        assert frozen(repo) == before
        for branch, task_id, entry in (
            ("left", old, left_evidence["tasks"][old]),
            ("right", new, right_evidence["tasks"][old]),
        ):
            data = json.loads(git(repo.root, "show", f"{branch}:proj/{verification.STORE}").stdout)
            assert data["tasks"][task_id] == entry


@verifies("c978")
def test_rekey_allocator_avoids_peer_evidence_only_identities(
    repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    divergent(repo, monkeypatch)
    git(repo.root, "switch", "-q", "left")
    orphan = candidate("peer orphaned evidence", 0)
    repo.write(verification.STORE, json.dumps({"schema_version": 1, "tasks": {orphan: {}}, "runs": {}}))
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "peer retained evidence")
    git(repo.root, "switch", "-q", "right")
    original_allocate = allocate

    def checked_allocate(seed: str, used: set[str]) -> str:
        assert orphan in used
        return original_allocate(seed, used)

    monkeypatch.setattr(api, "allocate", checked_allocate)
    Project.open(repo.root).reassign("src/right.py", 1, against="left")


@verifies("c978")
@pytest.mark.parametrize("kind", ["verifies", "marker"])
def test_keyword_identity_references_are_diagnosed(repo: ProjectFactory, run_cli: RunCli, kind: str) -> None:
    old = next(iter(Project.open(repo.root).load_registry().tasks))
    if kind == "marker":
        config = repo.root / "pyproject.toml"
        config.write_text(config.read_text() + "\n[tool.byteplan.tests]\npytest_marker = true\n")
        declaration = "import pytest\n@pytest.mark.byteplan"
    else:
        declaration = "from byteplan_runtime import verifies\n@verifies"
    repo.write("tests/test_keyword.py", f"{declaration}(task_id='{old}')\ndef test_keyword():\n    return 1\n")
    before = frozen(repo)
    result = run_cli("check", "--project", repo.root)
    assert "keyword arguments are unsupported" in result.out + result.err
    assert frozen(repo) == before


@verifies("c978")
@pytest.mark.parametrize("extra", [True, False])
def test_creation_extension_cannot_disguise_shared_binding(
    repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch, *, extra: bool
) -> None:
    base = git(repo.root, "rev-parse", "HEAD").stdout.strip()
    old = divergent(repo, monkeypatch)
    git(repo.root, "reset", "--hard", base)
    git(repo.root, "cherry-pick", "left")
    path = repo.root / ".byteplan/tasks.json"
    data = json.loads(path.read_bytes())
    created = data["tasks"][old]["history"][0]["new"]
    if extra:
        created["x-provenance"] = "extension information"
    else:
        created["path"] = 42
    path.write_text(json.dumps(data))
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "creation metadata enrichment")
    before = frozen(repo)
    with pytest.raises(ConfigError, match="creation provenance"):
        Project.open(repo.root).reassign("src/left.py", 1, against="left")
    assert frozen(repo) == before


@verifies("c978")
def test_rekey_uses_linked_worktree_index_lock(repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    divergent(repo, monkeypatch)
    location = repo.root.parent / "linked"
    git(repo.root, "worktree", "add", "-q", "-b", "repair-linked", str(location), "right")
    linked = type(repo)(location / "proj")
    index = (linked.root / git(linked.root, "rev-parse", "--git-path", "index").stdout.strip()).resolve()
    lock = index.with_name(index.name + ".lock")
    lock.write_text("other Git writer")
    before = frozen(repo)
    with pytest.raises(LockedError, match="index is locked"):
        Project.open(linked.root).reassign("src/right.py", 1, against="left")
    assert lock.read_text() == "other Git writer"
    assert frozen(repo) == before
    lock.unlink()
    result = Project.open(linked.root).reassign("src/right.py", 1, against="left")
    assert result.task.notes == "preserve right"
    assert not lock.exists()
    assert Project.open(repo.root).get_task(str(result.old_id)).notes == "preserve right"


@verifies("c978")
def test_rekey_checks_every_crisscross_merge_base(repo: ProjectFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    base = git(repo.root, "rev-parse", "HEAD").stdout.strip()
    old = divergent(repo, monkeypatch)
    left = git(repo.root, "rev-parse", "left").stdout.strip()
    right_tree = git(repo.root, "rev-parse", "right^{tree}").stdout.strip()
    left_tree = git(repo.root, "rev-parse", "left^{tree}").stdout.strip()
    empty_tree = git(repo.root, "rev-parse", f"{base}^{{tree}}").stdout.strip()
    empty_base = git(repo.root, "commit-tree", empty_tree, "-p", base, "-m", "independent base").stdout.strip()
    left_tip = git(
        repo.root, "commit-tree", left_tree, "-p", left, "-p", empty_base, "-m", "left crisscross"
    ).stdout.strip()
    right_tip = git(
        repo.root, "commit-tree", right_tree, "-p", empty_base, "-p", left, "-m", "right crisscross"
    ).stdout.strip()
    git(repo.root, "update-ref", "refs/heads/left", left_tip)
    git(repo.root, "update-ref", "refs/heads/right", right_tip)
    assert set(git(repo.root, "merge-base", "--all", "left", "right").stdout.split()) == {left, empty_base}
    before = frozen(repo)
    with pytest.raises(ConfigError, match=f"task {old} already existed in merge base"):
        Project.open(repo.root).reassign("src/right.py", 1, against="left")
    assert frozen(repo) == before
