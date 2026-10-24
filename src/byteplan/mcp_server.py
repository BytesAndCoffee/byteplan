# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""``byteplan mcp``: the registry for AI agents and editors, over MCP (stdio).

Needs the ``mcp`` extra (``pip install 'byteplan[mcp]'``, the official SDK, 2.x). Every tool
goes through ``api.Project``, so the lock, the journal, determinism and conflict blocking are
the CLI's, and results use the same schemas as ``--format json``.

Read-only by default. Three separate permissions (spec Addendum A §8) add tools; a tool whose
permission is missing isn't registered at all:

* ``allow_registry_write``: ``set_status``, ``resolve``, ``edit_task``, ``add_task_test``,
  ``remove_task_test``.
* ``allow_source_write``: ``scaffold_test``, ``release``, ``restore``, and ``apply=true`` on
  ``scan`` and ``sync_source`` (and ``resolve(sync_source=true)``). Every source write still
  needs ``apply=true``; without it a call only previews.
* ``allow_test_execution``: ``verify_task``, and ``release(smoke_test=true)``, which builds and
  imports the project.

Listing, searching and scanning never run tests or project code. Findings come back as data
(``diagnostics``); a ``ToolError`` is reserved for what the CLI exits 2 on, e.g. a ``locked``
project while another BytePlan process writes. stdout carries JSON-RPC only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, TypeVar

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ResourceError, ToolError

from byteplan import reporting
from byteplan.__about__ import __version__
from byteplan.api import UNSET, Project
from byteplan.cli import add_mcp_arguments
from byteplan.diagnostics import Code
from byteplan.errors import ByteplanError, LockedError
from byteplan.models import Presence, Status

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from pathlib import Path

    from byteplan.api import ScaffoldResult
    from byteplan.models import Task

__all__ = ["Permissions", "build_server", "main"]

_T = TypeVar("_T")

INSTRUCTIONS = """\
BytePlan tracks development obligations (TODO/FIXME comments, stubs, @todo decorators) that live
in source, each with a permanent hexadecimal ID (legacy `a83f`, new `a83f21`), in a committed registry. Status
(open, in_progress, blocked, resolved, dismissed) changes only on request; presence (present,
missing, stripped) is what scans observe. Resolving is a human decision: don't resolve a task
unless the user asked you to. Tools that write source preview unless called with apply=true.
"""


@dataclass(frozen=True)
class Permissions:
    registry_write: bool = False
    source_write: bool = False
    test_execution: bool = False


def _errors_as_tool_errors(call: Callable[[], _T]) -> _T:
    # FIXME[932b36]: Tell agents to restart the MCP server when the registry schema is newer than it
    #   The server keeps the code it started with. After a checkout whose registry needs a newer
    #   schema, every tool fails with "upgrade byteplan" even though the installed byteplan is
    #   already new enough; the fix is restarting the server (or the client session that owns it).
    try:
        return call()
    except LockedError as exc:
        msg = f"locked: {exc}"
        raise ToolError(msg) from exc
    except ByteplanError as exc:
        raise ToolError(str(exc)) from exc


def _needs(allowed: bool, what: str) -> None:  # noqa: FBT001
    if not allowed:
        msg = f"{what} needs source-write permission (start the server with --allow-source-write)"
        raise ToolError(msg)


def _task_change(task: Task, *, changed: bool) -> dict[str, Any]:
    return {"changed": changed, "task": reporting.task_json(task)}


def _scaffold_payload(result: ScaffoldResult, *, full: bool) -> dict[str, Any]:
    payload = {**reporting.scaffold_json(result), "imports": list(result.imports), "test": result.function}
    return {**payload, "text": result.text} if full else payload


def build_server(root: Path, permissions: Permissions = Permissions()) -> MCPServer:  # noqa: B008
    """The MCP server for the project at ``root`` (a fresh ``Project`` per call, so config and
    registry changes made outside the server are always seen)."""
    server = MCPServer("byteplan", instructions=INSTRUCTIONS, version=__version__)

    def project() -> Project:
        return Project.open(root)

    def run(call: Callable[[Project], _T]) -> _T:
        return _errors_as_tool_errors(lambda: call(project()))

    # Read-only --------------------------------------------------------------------------------

    @server.tool()
    def list_tasks(
        status: list[Status] | None = None,
        presence: list[Presence] | None = None,
        kind: list[str] | None = None,
        label: str | None = None,
    ) -> dict[str, Any]:
        """List registry tasks, optionally filtered (like `byteplan list`)."""
        tasks = run(lambda p: p.list_tasks(status, presence, kind))
        return {"tasks": [reporting.task_json(t) for t in tasks if label is None or label in t.labels]}

    @server.tool()
    def show_task(id: str) -> dict[str, Any]:  # noqa: A002
        """One task with its history and verification readiness (archived tasks too)."""

        def show(p: Project) -> dict[str, Any]:
            task = p.get_task(id)
            state = p.readiness(task)
            return {**reporting.task_json(task), "readiness": state.state, "readiness_reasons": list(state.reasons)}

        return run(show)

    @server.tool()
    def scan(
        paths: list[str] | None = None,
        apply: bool = False,  # noqa: FBT001, FBT002
        detail: bool = False,  # noqa: FBT001, FBT002
    ) -> dict[str, Any]:
        """Discover annotations and reconcile the registry. Previews unless apply=true (which
        adds IDs to source and needs source-write permission). Returns counts and what changed;
        detail=true also lists every annotation found."""
        if apply:
            _needs(permissions.source_write, "scan(apply=true)")

        def scanned(p: Project) -> dict[str, Any]:
            payload = reporting.scan_json(p.scan(paths or None, p.root, dry_run=not apply))
            if not detail:
                payload["annotation_count"] = len(payload.pop("annotations"))
            return payload

        return run(scanned)

    @server.tool()
    def check() -> dict[str, Any]:
        """Read-only validation: diagnostics, and the exit code `byteplan check` would give."""

        def checked(p: Project) -> dict[str, Any]:
            report = p.check()
            return reporting.check_json(p.exit_code(report.diagnostics), None, report.diagnostics)

        return run(checked)

    @server.tool()
    def missing(include_closed: bool = False) -> dict[str, Any]:  # noqa: FBT001, FBT002
        """Open, in-progress and blocked tasks whose annotation is no longer found in source;
        include_closed adds resolved and dismissed ones (usually removed on purpose)."""
        statuses = None if include_closed else [s for s in Status if not s.is_closed]
        tasks = run(lambda p: p.list_tasks(statuses, presences=[Presence.MISSING]))
        return {"tasks": [reporting.task_json(t) for t in tasks]}

    @server.tool()
    def duplicates() -> dict[str, Any]:
        """The same ID on more than one annotation."""
        report = run(lambda p: p.scan(dry_run=True))
        return {"diagnostics": [d.to_dict() for d in report.diagnostics if d.code is Code.DUPLICATE_ID]}

    @server.tool()
    def report(format: Literal["json", "markdown"] = "json") -> dict[str, Any]:  # noqa: A002
        """Summary by status, presence, kind and priority, plus findings."""
        data = run(lambda p: p.report())
        return {"markdown": reporting.report_markdown(data)} if format == "markdown" else data

    @server.tool()
    def get_task_tests(id: str) -> dict[str, Any]:  # noqa: A002
        """A task's linked acceptance tests and where each link comes from."""
        task = run(lambda p: p.get_task(id))
        return {"id": task.id, "title": task.display_title, "tests": reporting.tests_json([task])}

    @server.tool()
    def get_verification(id: str) -> dict[str, Any]:  # noqa: A002
        """A task's recorded verification evidence and readiness; runs nothing."""

        def cached(p: Project) -> dict[str, Any]:
            task = p.get_task(id)
            state = p.readiness(task)
            return {
                "id": task.id,
                "title": task.display_title,
                "readiness": state.state,
                "reasons": list(state.reasons),
                "tests": dict(state.tests),
            }

        return run(cached)

    @server.tool()
    def list_ready_tasks() -> dict[str, Any]:
        """Open tasks whose linked tests all passed and are fresh (ready for a human to review)."""
        found = run(lambda p: p.ready())
        return {"tasks": [{"id": t.id, "title": t.display_title} for t, _ in found]}

    @server.tool()
    def sync_source(
        apply: bool = False,  # noqa: FBT001, FBT002
        only: list[str] | None = None,
        remove_resolved: bool | None = None,  # noqa: FBT001
    ) -> dict[str, Any]:
        """Normalize annotations (decorator mode) and, with remove_resolved (or the config's
        remove_resolved), remove closed tasks' annotations. Previews unless apply=true (which
        needs source-write permission)."""
        if apply:
            _needs(permissions.source_write, "sync_source(apply=true)")

        def synced(p: Project) -> dict[str, Any]:
            payload = reporting.sync_json(p.sync(only, dry_run=not apply))
            if remove_resolved if remove_resolved is not None else p.config.annotations.remove_resolved:
                payload["cleanup"] = reporting.cleanup_json(p.cleanup(only, dry_run=not apply))
            return payload

        return run(synced)

    @server.tool()
    def preview_test_scaffold(
        id: str,  # noqa: A002
        path: str | None = None,
        name: str | None = None,
        full: bool = False,  # noqa: FBT001, FBT002
    ) -> dict[str, Any]:
        """The deliberately failing acceptance test `scaffold_test` would write, and the imports
        it would add; writes nothing. full=true also returns the whole file after the edit."""

        def preview(p: Project) -> dict[str, Any]:
            result = p.scaffold_test(id, path=path, name=name, dry_run=True)
            return _scaffold_payload(result, full=full)

        return run(preview)

    # Registry writes --------------------------------------------------------------------------

    if permissions.registry_write:

        @server.tool()
        def set_status(id: str, status: Status, note: str | None = None) -> dict[str, Any]:  # noqa: A002
            """Change a task's lifecycle status."""
            task, changed = run(lambda p: p.set_status(id, status, note=note))
            return _task_change(task, changed=changed)

        @server.tool()
        def resolve(
            id: str,  # noqa: A002
            note: str | None = None,
            sync_source: bool = False,  # noqa: FBT001, FBT002
            apply: bool = False,  # noqa: FBT001, FBT002
        ) -> dict[str, Any]:
            """Mark a task resolved, only when the user asked. With sync_source, also preview
            removing its annotation from source; apply=true removes it (needs source-write
            permission)."""
            if sync_source and apply:
                _needs(permissions.source_write, "resolve(sync_source=true, apply=true)")

            def resolved(p: Project) -> dict[str, Any]:
                task, changed = p.set_status(id, Status.RESOLVED, note=note)
                result = _task_change(task, changed=changed)
                if sync_source:
                    result["cleanup"] = reporting.cleanup_json(p.cleanup([task.id], dry_run=not apply))
                return result

            return run(resolved)

        @server.tool()
        def edit_task(
            id: str,  # noqa: A002
            priority: str | None = None,
            assignee: str | None = None,
            unassign: bool = False,  # noqa: FBT001, FBT002
            add_labels: list[str] | None = None,
            remove_labels: list[str] | None = None,
            notes: str | None = None,
            append_note: str | None = None,
            title_override: str | None = None,
            clear_title: bool = False,  # noqa: FBT001, FBT002
        ) -> dict[str, Any]:
            """Update managed fields (scans never overwrite them)."""
            changes: dict[str, Any] = {
                "priority": priority,
                "add_labels": add_labels or (),
                "remove_labels": remove_labels or (),
                "notes": notes,
                "append_note": append_note,
                "assignee": None if unassign else (assignee if assignee is not None else UNSET),
                "title_override": None if clear_title else (title_override if title_override is not None else UNSET),
            }
            task, changed = run(lambda p: p.edit_task(id, **changes))
            return _task_change(task, changed=changed)

        @server.tool()
        def add_task_test(id: str, nodes: list[str]) -> dict[str, Any]:  # noqa: A002
            """Link pytest node IDs (e.g. tests/test_x.py::test_y) to a task."""
            task, changed = run(lambda p: p.link_tests(id, nodes))
            return _task_change(task, changed=changed)

        @server.tool()
        def remove_task_test(id: str, nodes: list[str]) -> dict[str, Any]:  # noqa: A002
            """Unlink tests that were linked with add_task_test."""
            task, changed = run(lambda p: p.unlink_tests(id, nodes))
            return _task_change(task, changed=changed)

    # Source writes ----------------------------------------------------------------------------

    if permissions.source_write:

        @server.tool()
        def scaffold_test(
            id: str,  # noqa: A002
            path: str | None = None,
            name: str | None = None,
            policy: Literal["fail", "xfail", "skip"] | None = None,
            link: Literal["verifies", "marker", "managed"] | None = None,
            force_new: bool = False,  # noqa: FBT001, FBT002
            apply: bool = False,  # noqa: FBT001, FBT002
            full: bool = False,  # noqa: FBT001, FBT002
        ) -> dict[str, Any]:
            """Write a deliberately failing acceptance test for a task and link it. Previews unless
            apply=true. Returns the test and the imports added; full=true adds the whole file."""

            def scaffolded(p: Project) -> dict[str, Any]:
                result = p.scaffold_test(
                    id, path=path, name=name, policy=policy, link_style=link, force_new=force_new, dry_run=not apply
                )
                return _scaffold_payload(result, full=full)

            return run(scaffolded)

        @server.tool()
        def release(
            version: str | None = None,
            apply: bool = False,  # noqa: FBT001, FBT002
            allow_dirty: bool = False,  # noqa: FBT001, FBT002
            smoke_test: bool = False,  # noqa: FBT001, FBT002
        ) -> dict[str, Any]:
            """Strip @todo/@verifies and runtime imports in place for a release (never commits,
            tags or builds). Previews unless apply=true. smoke_test builds and imports the wheel,
            so it also needs test-execution permission."""
            if smoke_test and not permissions.test_execution:
                msg = "release(smoke_test=true) runs project code; it needs --allow-test-execution"
                raise ToolError(msg)
            return run(
                lambda p: reporting.release_json(
                    p.release(version, dry_run=not apply, allow_dirty=allow_dirty, smoke_test=smoke_test and apply)
                )
            )

        @server.tool()
        def restore(apply: bool = False, partial: bool = False) -> dict[str, Any]:  # noqa: FBT001, FBT002
            """Put back what `release` stripped. Previews unless apply=true."""
            return run(lambda p: reporting.restore_json(p.restore(dry_run=not apply, partial=partial)))

    # Test execution ---------------------------------------------------------------------------

    if permissions.test_execution:

        @server.tool()
        def verify_task(id: str) -> dict[str, Any]:  # noqa: A002
            """Run a task's linked tests with pytest and record the evidence (runs project code)."""
            return run(lambda p: reporting.verify_json(p.verify([id])))

    # Resources and prompts --------------------------------------------------------------------

    def read(call: Callable[[Project], Any]) -> str:
        try:
            return json.dumps(call(project()), indent=2, sort_keys=True, ensure_ascii=False)
        except ByteplanError as exc:
            raise ResourceError(str(exc)) from exc

    @server.resource("byteplan://tasks", mime_type="application/json")
    def tasks_resource() -> str:
        """Every registry task, as `byteplan list --format json`."""
        return read(lambda p: [reporting.task_json(t) for t in p.list_tasks()])

    @server.resource("byteplan://tasks/{id}", mime_type="application/json")
    def task_resource(id: str) -> str:  # noqa: A002
        """One task, as `byteplan show ID --format json` without readiness."""
        return read(lambda p: reporting.task_json(p.get_task(id)))

    @server.prompt()
    def triage() -> str:
        """Summarize open, missing and stale tasks, and ask what to work on next."""
        return run(_triage_text)

    return server


def _triage_text(project: Project) -> str:
    tasks = project.list_tasks()
    open_tasks = [t for t in tasks if not t.status.is_closed]
    gone = [t for t in tasks if t.presence is Presence.MISSING and not t.status.is_closed]
    stale = [d for d in project.check().diagnostics if d.code is Code.STALE_ANNOTATION]
    by_status = Counter(str(t.status) for t in open_tasks)

    def lines(items: Sequence[Task]) -> Iterator[str]:
        for t in items:
            where = f" ({t.source.path}:{t.source.line})" if t.source else ""
            yield f"- [{t.id}] {t.kind} {t.priority}: {t.display_title}{where}"

    parts = [
        "Triage this project's BytePlan tasks.",
        "",
        f"Open tasks ({len(open_tasks)}: {', '.join(f'{n} {s}' for s, n in sorted(by_status.items())) or 'none'}):",
        *lines(open_tasks),
        "",
        f"Missing from source while still open ({len(gone)}): their annotation was removed; confirm "
        "whether the work is done (then the user can resolve them) or the comment was lost:",
        *lines(gone),
        "",
        f"Stale annotations ({len(stale)}): closed tasks whose comment is still in source:",
        *(f"- {d.message}" for d in stale),
        "",
        "Suggest what to work on next and why, by priority and dependency. Don't change any task's "
        "status unless the user asks.",
    ]
    return "\n".join(parts)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="byteplan-mcp", description="BytePlan's MCP server (stdio)")
    add_mcp_arguments(parser)
    return parser.parse_args(argv)


def serve(args: argparse.Namespace) -> int:
    try:
        root = Project.open(args.project).root
    except ByteplanError as exc:
        sys.stderr.write(f"byteplan mcp: {exc}\n")
        return 2
    permissions = Permissions(args.allow_registry_write, args.allow_source_write, args.allow_test_execution)
    build_server(root, permissions).run("stdio")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """The `byteplan-mcp` script."""
    return serve(parse_args(argv))
