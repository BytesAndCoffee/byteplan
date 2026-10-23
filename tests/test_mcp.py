# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Phase 9: the MCP server, in process through the SDK's client, and over real stdio."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from typing import TYPE_CHECKING, Any

import anyio
import pytest

pytest.importorskip("mcp")

from mcp import Client, StdioServerParameters
from mcp_types.version import LATEST_HANDSHAKE_VERSION

from byteplan.cli import EXIT_ERROR, EXIT_OK
from byteplan.mcp_server import Permissions, build_server
from byteplan.persistence import project_lock
from tests.gitutil import COVERAGE_FILE

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mcp_types import CallToolResult

    from tests.conftest import ProjectFactory, RunCli

READ_TOOLS = {
    "check",
    "duplicates",
    "get_task_tests",
    "get_verification",
    "list_ready_tasks",
    "list_tasks",
    "missing",
    "preview_test_scaffold",
    "report",
    "scan",
    "show_task",
    "sync_source",
}
REGISTRY_TOOLS = {"add_task_test", "edit_task", "remove_task_test", "resolve", "set_status"}
SOURCE_TOOLS = {"release", "restore", "scaffold_test"}
EXECUTION_TOOLS = {"verify_task"}
ALL = Permissions(registry_write=True, source_write=True, test_execution=True)


@pytest.fixture
def tracked(project: ProjectFactory, run_cli: RunCli) -> ProjectFactory:
    project.init()
    pyproject = project.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + '\n[tool.byteplan.tests.scaffold]\nlink_style = "managed"\n')
    project.write("src/a.py", "def f():\n    # TODO: first task\n    return 1\n")
    project.write("src/b.py", "# FIXME: second task\nx = 1\n")
    assert run_cli("scan", "--project", project.root).code == EXIT_OK
    return project


def _registry(project: ProjectFactory) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((project.root / ".byteplan/tasks.json").read_text())
    return data


def _id_of(project: ProjectFactory, title: str) -> str:
    return next(str(t) for t, task in _registry(project)["tasks"].items() if task["title"] == title)


def session(project: ProjectFactory, permissions: Permissions, body: Callable[[Client], Awaitable[None]]) -> None:
    async def main() -> None:
        async with Client(build_server(project.root, permissions)) as client:
            await body(client)

    anyio.run(main)


def data(result: CallToolResult) -> dict[str, Any]:
    assert not result.is_error, result.content
    content: dict[str, Any] | None = result.structured_content
    assert content is not None
    return content


def error(result: CallToolResult) -> str:
    assert result.is_error
    text: str = result.content[0].text  # type: ignore[union-attr]
    return text


# Permissions -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("permissions", "expected"),
    [
        (Permissions(), READ_TOOLS),
        (Permissions(registry_write=True), READ_TOOLS | REGISTRY_TOOLS),
        (Permissions(source_write=True), READ_TOOLS | SOURCE_TOOLS),
        (Permissions(test_execution=True), READ_TOOLS | EXECUTION_TOOLS),
        (ALL, READ_TOOLS | REGISTRY_TOOLS | SOURCE_TOOLS | EXECUTION_TOOLS),
    ],
)
def test_a_tool_without_its_permission_is_not_registered(
    tracked: ProjectFactory, permissions: Permissions, expected: set[str]
) -> None:
    async def body(client: Client) -> None:
        assert {t.name for t in (await client.list_tools()).tools} == expected
        if not permissions.registry_write:
            assert "Unknown tool" in error(await client.call_tool("set_status", {"id": "abcd", "status": "resolved"}))

    session(tracked, permissions, body)


def test_read_only_tools_change_nothing(tracked: ProjectFactory) -> None:
    tracked.write("src/c.py", "# TODO: not yet tracked\n")
    task_id = _id_of(tracked, "first task")
    before = tracked.snapshot()

    async def body(client: Client) -> None:
        listed = data(await client.call_tool("list_tasks", {}))
        assert {t["id"] for t in listed["tasks"]} == set(_registry(tracked)["tasks"])
        assert data(await client.call_tool("list_tasks", {"status": ["resolved"]}))["tasks"] == []
        shown = data(await client.call_tool("show_task", {"id": task_id}))
        assert shown["title"] == "first task"
        assert shown["readiness"] == "unverified"
        preview = data(await client.call_tool("scan", {}))
        assert preview["dry_run"] is True
        assert [p["title"] for p in preview["annotated"]] == ["not yet tracked"]
        assert data(await client.call_tool("check", {}))["exit_code"] == 0
        assert data(await client.call_tool("missing", {}))["tasks"] == []
        assert data(await client.call_tool("duplicates", {}))["diagnostics"] == []
        assert data(await client.call_tool("report", {}))["summary"]["total"] == 2
        assert "first task" in data(await client.call_tool("report", {"format": "markdown"}))["markdown"]
        assert data(await client.call_tool("get_task_tests", {"id": task_id}))["id"] == task_id
        assert data(await client.call_tool("get_verification", {"id": task_id}))["readiness"] == "unverified"
        assert data(await client.call_tool("list_ready_tasks", {}))["tasks"] == []
        assert data(await client.call_tool("sync_source", {}))["dry_run"] is True
        scaffold = data(await client.call_tool("preview_test_scaffold", {"id": task_id}))
        assert scaffold["dry_run"] is True
        assert "def test_" in scaffold["text"]

    session(tracked, Permissions(), body)
    assert tracked.snapshot() == before


def test_source_writes_need_permission_and_apply(tracked: ProjectFactory) -> None:
    tracked.write("src/c.py", "# TODO: not yet tracked\n")
    before = tracked.snapshot()

    async def denied(client: Client) -> None:
        assert "needs source-write permission" in error(await client.call_tool("scan", {"apply": True}))
        assert "needs source-write permission" in error(await client.call_tool("sync_source", {"apply": True}))

    session(tracked, Permissions(registry_write=True), denied)
    assert tracked.snapshot() == before

    async def allowed(client: Client) -> None:
        assert data(await client.call_tool("scan", {}))["dry_run"] is True  # still a preview without apply
        assert data(await client.call_tool("scan", {"apply": True}))["written"]

    session(tracked, Permissions(source_write=True), allowed)
    assert "TODO[" in (tracked.root / "src/c.py").read_text()


def test_registry_writes_and_managed_fields_survive_a_rescan(tracked: ProjectFactory) -> None:
    task_id = _id_of(tracked, "first task")

    async def body(client: Client) -> None:
        edited = data(
            await client.call_tool(
                "edit_task",
                {"id": task_id, "priority": "high", "assignee": "alice", "add_labels": ["mcp"], "title_override": "T"},
            )
        )
        assert edited["changed"] is True
        assert data(await client.call_tool("scan", {"apply": True}))["dry_run"] is False
        shown = data(await client.call_tool("show_task", {"id": task_id}))
        managed = (shown["priority"], shown["assignee"], shown["labels"], shown["title_override"])
        assert managed == ("high", "alice", ["mcp"], "T")
        assert [t["id"] for t in data(await client.call_tool("list_tasks", {"label": "mcp"}))["tasks"]] == [task_id]
        status = data(await client.call_tool("set_status", {"id": task_id, "status": "in_progress", "note": "on it"}))
        assert status["task"]["status"] == "in_progress"
        linked = data(await client.call_tool("add_task_test", {"id": task_id, "nodes": ["tests/test_a.py::test_a"]}))
        assert linked["changed"] is True
        tests = data(await client.call_tool("get_task_tests", {"id": task_id}))
        assert [t["node"] for t in tests["tests"]] == ["tests/test_a.py::test_a"]
        unlinked = data(
            await client.call_tool("remove_task_test", {"id": task_id, "nodes": ["tests/test_a.py::test_a"]})
        )
        assert unlinked["changed"] is True
        cleared = data(await client.call_tool("edit_task", {"id": task_id, "unassign": True, "clear_title": True}))
        assert (cleared["task"]["assignee"], cleared["task"]["title_override"]) == (None, None)

    session(tracked, ALL, body)


def test_resolve_with_sync_source_needs_source_write(tracked: ProjectFactory) -> None:
    task_id = _id_of(tracked, "second task")

    async def denied(client: Client) -> None:
        message = error(await client.call_tool("resolve", {"id": task_id, "sync_source": True, "apply": True}))
        assert "needs source-write permission" in message

    session(tracked, Permissions(registry_write=True), denied)
    assert _registry(tracked)["tasks"][task_id]["status"] == "open"

    async def allowed(client: Client) -> None:
        args = {"id": task_id, "note": "done", "sync_source": True, "apply": True}
        resolved = data(await client.call_tool("resolve", args))
        assert resolved["task"]["status"] == "resolved"
        assert resolved["cleanup"]["removed"]

    session(tracked, Permissions(registry_write=True, source_write=True), allowed)
    assert "FIXME" not in (tracked.root / "src/b.py").read_text()


def test_scaffold_release_and_restore_preview_unless_applied(tracked: ProjectFactory) -> None:
    task_id = _id_of(tracked, "first task")
    before = tracked.snapshot()

    async def previews(client: Client) -> None:
        assert data(await client.call_tool("scaffold_test", {"id": task_id}))["dry_run"] is True
        message = error(await client.call_tool("release", {"apply": True, "smoke_test": True}))
        assert "needs --allow-test-execution" in message

    session(tracked, Permissions(source_write=True), previews)
    assert tracked.snapshot() == before

    async def applied(client: Client) -> None:
        result = data(await client.call_tool("scaffold_test", {"id": task_id, "apply": True}))
        assert result["written"]

    session(tracked, Permissions(source_write=True), applied)
    assert (tracked.root / "tests").exists()


def test_errors_are_tool_errors_with_the_message(tracked: ProjectFactory) -> None:
    async def body(client: Client) -> None:
        assert "no task with ID 'beef'" in error(await client.call_tool("show_task", {"id": "beef"}))

    session(tracked, Permissions(), body)


def test_a_concurrent_writer_makes_writes_fail_cleanly(tracked: ProjectFactory) -> None:
    task_id = _id_of(tracked, "first task")
    before = tracked.snapshot()

    async def body(client: Client) -> None:
        message = error(await client.call_tool("set_status", {"id": task_id, "status": "blocked"}))
        assert message.startswith("Error executing tool set_status: locked:")
        assert data(await client.call_tool("list_tasks", {}))["tasks"]  # reads still work

    with project_lock(tracked.root):
        session(tracked, ALL, body)
    assert tracked.snapshot() == before


def test_verify_task_needs_test_execution(tracked: ProjectFactory) -> None:
    task_id = _id_of(tracked, "first task")

    async def body(client: Client) -> None:
        verified = data(await client.call_tool("verify_task", {"id": task_id}))
        assert verified["tasks"] == []  # nothing linked: nothing runs

    session(tracked, Permissions(test_execution=True), body)


def test_resources_and_triage_prompt(tracked: ProjectFactory) -> None:
    task_id = _id_of(tracked, "first task")

    async def body(client: Client) -> None:
        listed = await client.read_resource("byteplan://tasks")
        assert {t["id"] for t in json.loads(listed.contents[0].text)} == set(_registry(tracked)["tasks"])  # type: ignore[union-attr]
        one = await client.read_resource(f"byteplan://tasks/{task_id}")
        assert json.loads(one.contents[0].text)["title"] == "first task"  # type: ignore[union-attr]
        prompt = await client.get_prompt("triage")
        text = prompt.messages[0].content.text  # type: ignore[union-attr]
        assert "Open tasks (2: 2 open)" in text
        assert f"[{task_id}]" in text

    session(tracked, Permissions(), body)


# The command ------------------------------------------------------------------------------------


def test_stdio_stdout_carries_json_rpc_only(tracked: ProjectFactory) -> None:
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": LATEST_HANDSHAKE_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "scan", "arguments": {}}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "show_task", "arguments": {"id": "beef"}},
        },
    ]
    with subprocess.Popen(
        [sys.executable, "-m", "byteplan", "mcp", "--project", str(tracked.root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env={**os.environ, "COVERAGE_FILE": COVERAGE_FILE},
    ) as proc:
        watchdog = threading.Timer(60, proc.kill)
        watchdog.start()
        try:
            assert proc.stdin is not None
            assert proc.stdout is not None
            proc.stdin.write("".join(json.dumps(r) + "\n" for r in requests))
            proc.stdin.flush()
            messages: list[dict[str, Any]] = []
            while {m.get("id") for m in messages} < {1, 2, 3}:
                line = proc.stdout.readline()
                assert line, "the server exited early"
                messages.append(json.loads(line))  # every stdout line is a JSON-RPC message
            proc.stdin.close()
            rest = proc.stdout.read()
            proc.wait(timeout=30)
        finally:
            watchdog.cancel()
    assert all(m.get("jsonrpc") == "2.0" for m in messages)
    assert all(json.loads(line).get("jsonrpc") == "2.0" for line in rest.splitlines() if line.strip())
    results = {m["id"]: m for m in messages if "id" in m}
    assert results[2]["result"]["structuredContent"]["dry_run"] is True
    assert results[3]["result"]["isError"] is True


def test_stdio_client_end_to_end(tracked: ProjectFactory) -> None:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "byteplan", "mcp", "--project", str(tracked.root)]
    )

    async def main() -> None:
        async with Client(params) as client:
            assert {t.name for t in (await client.list_tools()).tools} == READ_TOOLS
            assert len(data(await client.call_tool("list_tasks", {}))["tasks"]) == 2

    anyio.run(main)


def test_missing_extra_says_how_to_install(
    tracked: ProjectFactory, run_cli: RunCli, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "byteplan.mcp_server", None)
    result = run_cli("mcp", "--project", tracked.root)
    assert result.code == EXIT_ERROR
    assert "pip install 'byteplan[mcp]'" in result.err
    assert result.out == ""


def test_outside_a_project_exits_2(tmp_path: Any, run_cli: RunCli) -> None:
    result = run_cli("mcp", "--project", tmp_path)
    assert result.code == EXIT_ERROR
    assert result.out == ""


def test_scan_paths_are_relative_to_the_served_project(
    tracked: ProjectFactory, tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    tracked.write("src/c.py", "# TODO: not yet tracked\n")
    monkeypatch.chdir(tmp_path)  # the server's cwd is elsewhere

    async def body(client: Client) -> None:
        preview = data(await client.call_tool("scan", {"paths": ["src/c.py"]}))
        assert [p["title"] for p in preview["annotated"]] == ["not yet tracked"]

    session(tracked, Permissions(), body)


def test_resolve_with_sync_source_previews_unless_applied(tracked: ProjectFactory) -> None:
    task_id = _id_of(tracked, "second task")

    async def body(client: Client) -> None:
        resolved = data(await client.call_tool("resolve", {"id": task_id, "sync_source": True}))
        assert resolved["task"]["status"] == "resolved"
        assert resolved["cleanup"]["dry_run"] is True

    session(tracked, Permissions(registry_write=True, source_write=True), body)
    assert "FIXME" in (tracked.root / "src/b.py").read_text()
