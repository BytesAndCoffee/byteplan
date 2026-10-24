# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""MCP schema rejection explains upgrading and restarting a long-running server."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import anyio
import pytest

pytest.importorskip("mcp")

from mcp import Client
from mcp.server.mcpserver.exceptions import ToolError

from byteplan._todo import verifies
from byteplan.errors import ConfigError, LockedError, RegistryError
from byteplan.mcp_server import _errors_as_tool_errors, build_server
from byteplan.registry import SCHEMA_VERSION

if TYPE_CHECKING:
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
