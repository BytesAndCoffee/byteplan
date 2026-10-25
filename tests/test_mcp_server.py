# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""MCP recovery authority and actionable schema diagnostics."""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import TYPE_CHECKING

import anyio
import pytest

pytest.importorskip("mcp")

from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from byteplan import api, persistence, verification
from byteplan._todo import verifies
from byteplan.api import Project
from byteplan.errors import ConfigError, LockedError, RegistryError
from byteplan.mcp_server import Permissions, _errors_as_tool_errors, build_server
from byteplan.models import Status
from byteplan.registry import SCHEMA_VERSION

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from tests.conftest import ProjectFactory


@verifies("932b36")
def test_future_schema_tool_errors_include_upgrade_and_restart(project: ProjectFactory) -> None:
    project.init()
    project.write(
        ".byteplan/tasks.json",
        json.dumps({"schema_version": SCHEMA_VERSION + 1, "tasks": {}, "reserved_ids": []}),
    )
    before = project.snapshot()

    async def call() -> None:
        async with Client(build_server(project.root)) as client:
            result = await client.call_tool("list_tasks", {})
            assert result.is_error
            content = result.content[0]
            assert content.type == "text"
            assert "upgrade BytePlan if needed" in content.text
            assert "restart this MCP server or its owning client session" in content.text
            assert f"supports ({SCHEMA_VERSION})" in content.text

    anyio.run(call)
    assert project.snapshot() == before


@verifies("932b36")
@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (RegistryError("registry is not valid JSON"), "registry is not valid JSON"),
        (ConfigError("unknown option"), "unknown option"),
        (LockedError("busy"), "locked: busy"),
    ],
)
def test_unrelated_tool_errors_keep_existing_messages(exc: Exception, expected: str) -> None:
    def fail() -> None:
        raise exc

    with pytest.raises(ToolError) as result:
        _errors_as_tool_errors(fail)
    assert str(result.value) == expected


def _tracked(project: ProjectFactory) -> tuple[Project, str]:
    settings = project.root / "pyproject.toml"
    settings.write_text(settings.read_text() + '\n[tool.byteplan.tests.scaffold]\nlink_style = "managed"\n')
    project.init()
    project.write("a.py", "# TODO: preserve source recovery authority\nvalue = 1\n")
    facade = Project.open(project.root)
    facade.scan(dry_run=False)
    (task,) = facade.list_tasks()
    return facade, task.id


def _interrupt_write(
    project: ProjectFactory,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    data: bytes,
    *,
    extra_writes: tuple[persistence.FileWrite, ...] = (),
) -> None:
    """Leave recovery material produced by an ordinary interrupted production write."""
    destination = project.root / target
    original = persistence.file_hash(destination)
    atomic = persistence.atomic_write_bytes

    def interrupted(path: Path, content: bytes, mode: int | None = None) -> bool:
        if path == destination:
            msg = "simulated interrupted replacement"
            raise OSError(msg)
        return atomic(path, content, mode)

    with monkeypatch.context() as scoped:
        scoped.setattr(persistence, "atomic_write_bytes", interrupted)
        with pytest.raises(OSError, match="simulated interrupted"):
            persistence.commit(project.root, [persistence.FileWrite(target, original, data), *extra_writes])
    assert persistence.journal_path(project.root).is_file()


@verifies("81cc04")
@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("set_status", {"status": "resolved"}),
        ("set_status", {"status": "open"}),
        ("resolve", {}),
        ("resolve", {"apply": True}),
        ("resolve", {"sync_source": True}),
        ("edit_task", {"notes": "requested metadata edit"}),
        ("edit_task", {}),
        ("add_task_test", {"nodes": ["tests/test_ok.py::test_ok"]}),
        ("remove_task_test", {"nodes": ["tests/test_ok.py::test_ok"]}),
    ],
)
@pytest.mark.parametrize("source_permission", [False, True])
def test_registry_requests_preserve_pending_source_transaction(
    project: ProjectFactory,
    monkeypatch: pytest.MonkeyPatch,
    tool: str,
    arguments: dict[str, object],
    *,
    source_permission: bool,
) -> None:
    _, task_id = _tracked(project)
    project.write("tests/test_ok.py", "def test_ok():\n    assert True\n")
    source = project.root / "a.py"
    _interrupt_write(project, monkeypatch, "a.py", source.read_bytes() + b"# recovered source\n")
    before = project.snapshot()

    async def call() -> None:
        permissions = Permissions(registry_write=True, source_write=source_permission)
        async with Client(build_server(project.root, permissions)) as client:
            result = await client.call_tool(tool, {"id": task_id, **arguments})
            assert result.is_error
            content = result.content[0]
            assert content.type == "text"
            assert "recovery" in content.text
            assert "source" in content.text

    anyio.run(call)
    assert project.snapshot() == before


@verifies("81cc04")
@pytest.mark.parametrize(
    "tool", ["scan", "sync_source", "preview_test_scaffold", "scaffold_test", "release", "restore"]
)
def test_source_previews_do_not_recover_pending_source(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch, tool: str
) -> None:
    facade, task_id = _tracked(project)
    if tool == "restore":
        facade.release("1.0.0", allow_dirty=True)
    source = project.root / "a.py"
    _interrupt_write(project, monkeypatch, "a.py", source.read_bytes() + b"# recovered source\n")
    before = project.snapshot()

    async def call() -> None:
        async with Client(build_server(project.root, Permissions(source_write=True))) as client:
            arguments = {"id": task_id} if tool in {"preview_test_scaffold", "scaffold_test"} else {}
            result = await client.call_tool(tool, arguments)
            # Release deliberately refuses even a preview while recovery is pending.
            assert result.is_error is (tool == "release"), result.content

    anyio.run(call)
    assert project.snapshot() == before


@verifies("81cc04")
@pytest.mark.parametrize("tool", ["scan", "resolve"])
def test_explicit_authorized_source_apply_can_complete_pending_recovery(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch, tool: str
) -> None:
    _, task_id = _tracked(project)
    source = project.root / "a.py"
    recovered = source.read_bytes() + b"# recovered source\n"
    _interrupt_write(project, monkeypatch, "a.py", recovered)

    async def call() -> None:
        permissions = Permissions(registry_write=True, source_write=True)
        async with Client(build_server(project.root, permissions)) as client:
            arguments: dict[str, object] = {"apply": True}
            if tool == "resolve":
                arguments.update({"id": task_id, "sync_source": True})
            result = await client.call_tool(tool, arguments)
            assert not result.is_error, result.content

    anyio.run(call)
    assert b"# recovered source\n" in source.read_bytes()
    assert not persistence.pending_journal(project.root)
    if tool == "scan":
        assert source.read_bytes() == recovered
    else:
        assert b"TODO" not in source.read_bytes()
        assert Project.open(project.root).get_task(task_id).status is Status.RESOLVED


@verifies("81cc04")
def test_source_apply_without_source_permission_preserves_pending_recovery(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _tracked(project)
    source = project.root / "a.py"
    _interrupt_write(project, monkeypatch, "a.py", source.read_bytes() + b"# recovered source\n")
    before = project.snapshot()

    async def call() -> None:
        async with Client(build_server(project.root, Permissions(registry_write=True))) as client:
            result = await client.call_tool("scan", {"apply": True})
            assert result.is_error

    anyio.run(call)
    assert project.snapshot() == before


@verifies("81cc04")
@pytest.mark.parametrize("target", ["registry", "evidence", "archive", "report"])
def test_registry_permission_recovers_only_canonical_metadata(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    if target == "report":
        settings = project.root / "pyproject.toml"
        settings.write_text(settings.read_text() + '\n[tool.byteplan]\nreport_file = "byteplan.md"\n')
    facade, task_id = _tracked(project)
    source = (project.root / "a.py").read_bytes()
    if target == "registry":
        destination = facade.registry_rel
        payload = json.loads(facade.config.registry_path.read_bytes())
        payload["recovered_extension"] = True
    elif target == "evidence":
        destination = verification.STORE
        payload = {"schema_version": 1, "tasks": {}, "runs": {}, "recovered_extension": True}
    elif target == "archive":
        destination = facade.archive_index_rel
        payload = {"schema_version": 1, "tasks": {}, "recovered_extension": True}
    else:
        assert facade.report_rel is not None
        destination = facade.report_rel
        payload = None
    data = json.dumps(payload).encode() if payload is not None else b"interrupted generated task report\n"
    _interrupt_write(project, monkeypatch, destination, data)

    async def call() -> None:
        async with Client(build_server(project.root, Permissions(registry_write=True))) as client:
            result = await client.call_tool("set_status", {"id": task_id, "status": "resolved"})
            assert not result.is_error, result.content

    anyio.run(call)
    assert (project.root / "a.py").read_bytes() == source
    assert Project.open(project.root).get_task(task_id).status is Status.RESOLVED
    assert not persistence.pending_journal(project.root)
    if payload is not None:
        assert json.loads((project.root / destination).read_bytes())["recovered_extension"] is True


@verifies("81cc04")
def test_mixed_metadata_and_source_recovery_is_rejected_before_any_target_changes(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    facade, task_id = _tracked(project)
    payload = json.loads(facade.config.registry_path.read_bytes())
    payload["recovered_extension"] = True
    source = project.root / "a.py"
    _interrupt_write(
        project,
        monkeypatch,
        facade.registry_rel,
        json.dumps(payload).encode(),
        extra_writes=(
            persistence.FileWrite("a.py", persistence.file_hash(source), source.read_bytes() + b"# recovered source\n"),
        ),
    )
    before = project.snapshot()

    async def call() -> None:
        async with Client(build_server(project.root, Permissions(registry_write=True))) as client:
            result = await client.call_tool("set_status", {"id": task_id, "status": "resolved"})
            assert result.is_error

    anyio.run(call)
    assert project.snapshot() == before


@verifies("81cc04")
@pytest.mark.parametrize("target", ["registry", "evidence"])
def test_execution_only_verify_can_recover_metadata_and_record_results(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch, target: str
) -> None:
    facade, task_id = _tracked(project)
    project.write("tests/test_ok.py", "def test_ok():\n    assert True\n")
    facade.link_tests(task_id, ["tests/test_ok.py::test_ok"])
    source = (project.root / "a.py").read_bytes()
    if target == "registry":
        destination = facade.registry_rel
        payload = json.loads(facade.config.registry_path.read_bytes())
        payload["recovered_extension"] = True
    else:
        destination = verification.STORE
        payload = {"schema_version": 1, "tasks": {}, "runs": {}, "recovered_extension": True}
    _interrupt_write(project, monkeypatch, destination, json.dumps(payload).encode())

    async def call() -> None:
        async with Client(build_server(project.root, Permissions(test_execution=True))) as client:
            result = await client.call_tool("verify_task", {"id": task_id})
            assert not result.is_error, result.content

    anyio.run(call)
    assert (project.root / "a.py").read_bytes() == source
    assert Project.open(project.root).get_task(task_id).status is Status.OPEN
    assert not persistence.pending_journal(project.root)
    assert json.loads((project.root / destination).read_bytes())["recovered_extension"] is True
    recorded = verification.Evidence.load(project.root)
    assert recorded.tasks[task_id]["tests"]["tests/test_ok.py::test_ok"]["outcome"] == "passed"


@verifies("81cc04")
def test_execution_permission_cannot_recover_source_when_recording_results(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    facade, task_id = _tracked(project)
    project.write("tests/test_ok.py", "def test_ok():\n    assert True\n")
    facade.link_tests(task_id, ["tests/test_ok.py::test_ok"])
    source = project.root / "a.py"
    original = source.read_bytes()
    _interrupt_write(project, monkeypatch, "a.py", original + b"# recovered source\n")
    journal = persistence.journal_path(project.root).read_bytes()
    registry = facade.config.registry_path.read_bytes()
    evidence_path = project.root / verification.STORE
    evidence = evidence_path.read_bytes() if evidence_path.exists() else None

    async def call() -> None:
        async with Client(build_server(project.root, Permissions(test_execution=True))) as client:
            result = await client.call_tool("verify_task", {"id": task_id})
            assert result.is_error

    anyio.run(call)
    assert source.read_bytes() == original
    assert persistence.journal_path(project.root).read_bytes() == journal
    assert facade.config.registry_path.read_bytes() == registry
    assert (evidence_path.read_bytes() if evidence_path.exists() else None) == evidence


@verifies("81cc04")
def test_recovery_policy_is_enforced_after_the_project_lock_is_acquired(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    facade, task_id = _tracked(project)
    source = project.root / "a.py"
    original = source.read_bytes()
    registry = facade.config.registry_path.read_bytes()
    lock = persistence.project_lock
    observed: list[bytes] = []

    @contextmanager
    def transaction_arrives_at_lock(root: Path) -> Iterator[None]:
        with lock(root):
            _interrupt_write(project, monkeypatch, "a.py", original + b"# recovered source\n")
            observed.append(persistence.journal_path(root).read_bytes())
            yield

    monkeypatch.setattr(api, "project_lock", transaction_arrives_at_lock)

    async def call() -> None:
        async with Client(build_server(project.root, Permissions(registry_write=True))) as client:
            result = await client.call_tool("set_status", {"id": task_id, "status": "resolved"})
            assert result.is_error

    anyio.run(call)
    assert source.read_bytes() == original
    assert facade.config.registry_path.read_bytes() == registry
    assert persistence.journal_path(project.root).read_bytes() == observed[0]


@verifies("81cc04")
def test_ordinary_python_api_keeps_existing_automatic_recovery(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    facade, task_id = _tracked(project)
    source = project.root / "a.py"
    recovered = source.read_bytes() + b"# recovered source\n"
    _interrupt_write(project, monkeypatch, "a.py", recovered)
    calls: list[Path] = []

    def recover(root: Path) -> list[str]:
        calls.append(root)
        return persistence.recover(root)

    monkeypatch.setattr(api, "recover", recover)
    facade.set_status(task_id, Status.RESOLVED)
    assert calls == [project.root]
    assert source.read_bytes() == recovered
    assert not persistence.pending_journal(project.root)


@verifies("81cc04")
def test_source_apply_authority_does_not_leak_into_later_registry_call(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, task_id = _tracked(project)
    source = project.root / "a.py"

    async def call() -> None:
        permissions = Permissions(registry_write=True, source_write=True)
        async with Client(build_server(project.root, permissions)) as client:
            applied = await client.call_tool("scan", {"apply": True})
            assert not applied.is_error, applied.content
            _interrupt_write(project, monkeypatch, "a.py", source.read_bytes() + b"# later recovery\n")
            before = project.snapshot()
            result = await client.call_tool("set_status", {"id": task_id, "status": "resolved"})
            assert result.is_error
            assert project.snapshot() == before

    anyio.run(call)
