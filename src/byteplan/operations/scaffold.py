# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Internal scaffold orchestration delegated by Project."""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from byteplan import scaffold
from byteplan.errors import (
    EditError,
    SourceError,
)
from byteplan.files import Scope, ScopeMatcher, collect_files
from byteplan.languages import Language, language_for
from byteplan.models import AttachmentKind, HistoryEvent
from byteplan.persistence import (
    FileWrite,
    sha256,
)
from byteplan.scanner import scan_file
from byteplan.scanner.source import decode_source
from byteplan.scanner.symbols import parse_module

if TYPE_CHECKING:
    from byteplan.models import Task

from byteplan._api_types import ScaffoldResult
from byteplan.operations.common import _not_found, _read_bytes

if TYPE_CHECKING:
    from byteplan.api import Project


def scaffold_test(
    self: Project,
    task_id: str,
    *,
    path: str | None = None,
    name: str | None = None,
    policy: str | None = None,
    link_style: str | None = None,
    force_new: bool = False,
    dry_run: bool = False,
) -> ScaffoldResult:
    """Write a deliberately failing acceptance test for a task and link it.

    If the task already has linked tests, nothing is written (unless ``force_new``).
    Raises ``ScaffoldError`` when it can't be done safely.
    """
    self._require_working_tree()
    if not dry_run:
        self._refuse_while_stripped("tests scaffold")
    settings = self.config.tests.scaffold
    policy = policy or settings.policy
    link_style = link_style or settings.link_style
    context = contextlib.nullcontext(()) if dry_run else self._writing()
    with context:
        registry_hash, registry = self._read_registry()
        task = registry.get(self._resolve_task_id(task_id, registry))
        if task is None:
            raise _not_found(task_id)
        existing_links = tuple(task.linked_tests())
        if existing_links and not force_new:
            first = existing_links[0]
            return ScaffoldResult(task, first, first.split("::", 1)[0], existing=existing_links, dry_run=dry_run)
        if link_style == "marker" and not self.config.tests.pytest_marker:
            raise scaffold.ScaffoldError(
                scaffold.MARKER_NOT_ENABLED,
                "--link marker needs [tool.byteplan.tests] pytest_marker = true",
                "enable it, or use --link verifies or --link managed",
            )
        scope = collect_files(self.config)
        target_rel = self._scaffold_path(task, path, scope)
        target = self._scaffold_target(task)
        before = _read_bytes(self.root / target_rel)
        plan = scaffold.plan(
            task,
            target,
            target_rel,
            None if before is None else decode_source(target_rel, before).text,
            name=name,
            policy=policy,
            link_style=link_style,
            runtime=self.runtime_module(development=True) if link_style == "verifies" else None,
            async_tests=settings.async_tests,
        )
        new_source = dataclasses.replace(decode_source(target_rel, before or b""), path=target_rel, text=plan.text)
        # The new test must be found again: as a placeholder, and through its link.
        if plan.node not in scaffold.placeholder_nodes(target_rel, plan.text):
            msg = f"{target_rel}: the scaffold didn't round-trip; nothing was written"
            raise EditError(msg)
        entry: dict[str, Any] | None = None
        if link_style != "managed":
            rescan = scan_file(
                new_source,
                self.config.detect,
                self.config.annotations.runtime_modules,
                pytest_marker=link_style == "marker",
            )
            link = next((ln for ln in rescan.links if ln.node_id == plan.node and task.id in ln.task_ids), None)
            if link is None:
                msg = f"{target_rel}: the scaffold's @{'verifies' if link_style == 'verifies' else 'pytest.mark.byteplan'} wasn't recognized; nothing was written"
                raise EditError(msg)
            entry = {"node": plan.node, "provenance": link.provenance, "path": link.path, "line": link.line}
        if dry_run:
            return ScaffoldResult(
                task,
                plan.node,
                target_rel,
                plan.created,
                dry_run=True,
                text=plan.text,
                imports=plan.imports,
                function=plan.function,
            )

        now = self.clock()
        if entry is not None:
            task.tests_discovered = sorted(
                [*task.tests_discovered, entry], key=lambda e: (e["node"], e["provenance"], e["path"], e["line"])
            )
        else:
            task.tests_managed = sorted({*task.tests_managed, plan.node})
        task.history.append(
            HistoryEvent("test_scaffolded", now, new={"path": target_rel, "node": plan.node, "policy": policy})
        )
        writes = [
            FileWrite(target_rel, None if before is None else sha256(before), new_source.encode()),
            *self._registry_writes(registry_hash, registry),
        ]
        written = tuple(self._commit(writes))
        return ScaffoldResult(
            task,
            plan.node,
            target_rel,
            plan.created,
            text=plan.text,
            written=written,
            imports=plan.imports,
            function=plan.function,
        )


def scaffold_path(self: Project, task: Task, override: str | None, scope: Scope) -> str:
    matcher = ScopeMatcher(self.config)
    if override is not None:
        path = Path(os.path.normpath(self.root / override))
    else:
        python = [p for p in scope.files if language_for(p) is Language.PYTHON]
        path = self.root / scaffold.target_path(task, self.config.tests.scaffold, python)
    # The same rules for the default path as for --path: inside the project, a .py file,
    # and reachable by scans, which never follow symlinks.
    where = f"--path {override!r}" if override is not None else Path(os.path.relpath(path, self.root)).as_posix()
    if not path.is_relative_to(self.root) or path.suffix != ".py":
        raise scaffold.ScaffoldError(scaffold.NEEDS_PATH, f"{where} must be a .py file inside the project")
    rel = path.relative_to(self.root).as_posix()
    current = self.root
    for part in rel.split("/"):
        current /= part
        if current.is_symlink():
            raise scaffold.ScaffoldError(
                scaffold.NEEDS_PATH,
                f"{rel} goes through the symlink {current.relative_to(self.root).as_posix()}, which scans don't follow",
                "pass --path to a real directory in the project",
            )
    if not (self.root / rel).resolve().is_relative_to(self.root.resolve()):
        raise scaffold.ScaffoldError(scaffold.NEEDS_PATH, f"{rel} resolves outside the project")
    if not matcher.contains(rel):
        raise scaffold.ScaffoldError(
            scaffold.NEEDS_PATH,
            f"{rel} isn't in the scan scope, so the new test's link and placeholder state couldn't be seen",
            "add the test files to [tool.byteplan] include, or pass --path",
        )
    return rel


def scaffold_target(self: Project, task: Task) -> scaffold.Target:
    source = task.source
    if source is None or source.attachment_kind not in {
        AttachmentKind.FUNCTION,
        AttachmentKind.METHOD,
        AttachmentKind.CLASS,
    }:
        return scaffold.Target(source.attachment_kind if source else None, None)
    is_async = False
    data = _read_bytes(self.root / source.path)
    if data is not None and language_for(source.path) is Language.PYTHON:
        with contextlib.suppress(SourceError):
            tree = parse_module(decode_source(source.path, data))
            is_async = any(
                isinstance(node, ast.AsyncFunctionDef) and node.lineno == source.decl_line for node in ast.walk(tree)
            )
    return scaffold.Target(source.attachment_kind, source.symbol, is_async)
