# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Conservative source planning and Git exclusion for explicit branch collision repair."""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import os
import re
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from byteplan import gitio, normalize
from byteplan.diagnostics import Code
from byteplan.edits import char_col, physical_lines, replace_at
from byteplan.errors import ConfigError, EditError, LockedError
from byteplan.languages import Language, language_for
from byteplan.models import Representation
from byteplan.scanner import ensure_unchanged, scan_file
from byteplan.scanner.decorators import resolve_runtime_names
from byteplan.scanner.stubs import dotted_name

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

    from byteplan.config import DetectConfig
    from byteplan.diagnostics import Diagnostic
    from byteplan.models import Annotation, Task
    from byteplan.registry import Registry
    from byteplan.scanner import FileScan
    from byteplan.scanner.hierarchy import ClassHierarchy
    from byteplan.scanner.source import SourceFile


@contextlib.contextmanager
def index_guard(root: Path) -> Iterator[None]:
    """Exclude ordinary checkout/add/merge while source and registry are being rekeyed."""
    if os.environ.get("GIT_INDEX_FILE"):
        msg = "branch collision repair requires the ordinary working-tree index; unset GIT_INDEX_FILE first"
        raise ConfigError(msg)
    index = Path(gitio.git(["rev-parse", "--git-path", "index"], root).strip())
    if not index.is_absolute():
        index = root / index
    lock = index.with_name(index.name + ".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        msg = "Git's index is locked; finish the active Git operation before branch collision repair"
        raise LockedError(msg) from exc
    try:
        yield
    finally:
        os.close(descriptor)
        lock.unlink()


def ensure_no_operation(root: Path) -> None:
    """A stage-zero index can still belong to a resolved, uncommitted merge."""
    for name in (
        "MERGE_HEAD",
        "CHERRY_PICK_HEAD",
        "REVERT_HEAD",
        "REBASE_HEAD",
        "rebase-merge",
        "rebase-apply",
        "sequencer",
    ):
        path = Path(gitio.git(["rev-parse", "--git-path", name], root).strip())
        if not path.is_absolute():
            path = root / path
        if path.exists():
            msg = f"Git operation {name} is active; finish or abort it before repairing an original branch"
            raise ConfigError(msg)


def ensure_static(diagnostics: Iterable[Diagnostic]) -> None:
    uncertain = {
        Code.MALFORMED_ID,
        Code.UNRESOLVED_TODO_DECORATOR,
        Code.INVALID_TODO_DECORATOR,
        Code.DYNAMIC_TODO_ARGUMENT,
        Code.DECORATOR_NEEDS_REVIEW,
        Code.MALFORMED_TEST_ID,
    }
    for diagnostic in diagnostics:
        if diagnostic.code in uncertain:
            msg = f"cannot prove complete identity references: {diagnostic.format_text()}; resolve it before collision repair"
            raise ConfigError(msg)


def _contains_identity(value: Any, old_id: str) -> bool:
    if isinstance(value, str):
        return value == old_id
    if isinstance(value, dict):
        return any(key == old_id or _contains_identity(item, old_id) for key, item in value.items())
    return isinstance(value, list | tuple) and any(_contains_identity(item, old_id) for item in value)


def creation_binding(task: Task) -> tuple[str, int]:
    """Compare the known creation binding, independent of extension metadata spelling."""
    events = [event for event in task.history if event.event == "created"]
    if len(events) == 1 and isinstance(events[0].new, dict):
        path, line = events[0].new.get("path"), events[0].new.get("line")
        if isinstance(path, str) and path and type(line) is int and line > 0:
            return path, line
    msg = f"task {task.id} lacks supported creation provenance; cannot prove independent creation"
    raise ConfigError(msg)


def ensure_supported_metadata(registry: Registry, old_id: str) -> None:
    """Unknown current reference semantics require a capable client, never a blind replacement."""
    checks: list[tuple[str, Any]] = [
        ("registry extensions", {k: v for k, v in registry.extra.items() if k != "releases"})
    ]
    for task_id, task in registry.tasks.items():
        checks.extend(
            [
                (f"task {task_id} extensions", task.extra),
                (f"task {task_id} test-link extensions", task.tests_extra),
                (f"task {task_id} source extensions", task.source.extra if task.source else {}),
            ]
        )
    for where, value in checks:
        if _contains_identity(value, old_id):
            msg = f"{where} may reference {old_id}; use a client that understands these mappings before reassigning"
            raise ConfigError(msg)


def _tags(scan: FileScan, old_id: str, new_id: str) -> Counter[tuple[object, ...]]:
    return Counter(
        (
            tag.task_id if tag.task_id != old_id else new_id,
            tag.kind,
            tag.title,
            tag.description,
            tag.symbol,
            tag.representation,
            tag.decl_is_stub,
            tag.tests,
        )
        for tag in scan.tags
    )


def _links(scan: FileScan, old_id: str, new_id: str) -> Counter[tuple[object, ...]]:
    return Counter(
        (tuple(new_id if value == old_id else value for value in link.task_ids), link.node_id, link.provenance)
        for link in scan.links
    )


def rewrite_source(
    source: SourceFile,
    before: FileScan,
    target: Annotation | None,
    old_id: str,
    new_id: str,
    detect: DetectConfig,
    runtime_modules: Sequence[str],
    hierarchy: ClassHierarchy | None,
    *,
    pytest_marker: bool,
) -> tuple[SourceFile, FileScan]:
    """Edit only the selected annotation and scanner-confirmed exact verification references."""
    ensure_static(before.diagnostics)
    changes: list[tuple[int, int, str, str]] = []
    expected = ast.parse(source.text, filename=source.path) if language_for(source.path) is Language.PYTHON else None
    literal_identity = expected is not None and any(
        isinstance(node, ast.Constant) and node.value == old_id for node in ast.walk(expected)
    )
    if (old_id in source.text or literal_identity) and re.search(
        r"byteplan:\s*ignore(?:-file)?\b", source.text, re.IGNORECASE
    ):
        msg = f"{source.path} contains ignored identity context; review its references before collision repair"
        raise ConfigError(msg)
    if expected is not None:
        names = resolve_runtime_names(expected, runtime_modules)
        reference_lines = {link.line for link in before.links if old_id in link.task_ids}
        for node in ast.walk(expected):
            if not isinstance(node, ast.Call):
                continue
            if names.resolve(dotted_name(node.func) or "") == "verifies" and node.keywords:
                msg = (
                    f"{source.path}:{node.lineno}: keyword verification references are unsupported; nothing was written"
                )
                raise ConfigError(msg)
            values: list[ast.expr] = []
            if node.lineno in reference_lines:
                if node.keywords:
                    msg = f"{source.path}:{node.lineno}: cannot rewrite verification keywords safely"
                    raise ConfigError(msg)
                values.extend(node.args)
            if (
                target is not None
                and target.representation is Representation.DECORATOR
                and (node.lineno, node.end_lineno) == (target.line, target.end_line)
            ):
                values.extend(keyword.value for keyword in node.keywords if keyword.arg == "id")
            for value in values:
                if isinstance(value, ast.Constant) and value.value == old_id:
                    segment = ast.get_source_segment(source.text, value)
                    if segment is None:
                        msg = f"{source.path}:{value.lineno}: cannot locate the exact identity literal"
                        raise EditError(msg)
                    col = char_col(physical_lines(source.text)[value.lineno - 1], value.col_offset)
                    changes.append((value.lineno, col, segment, normalize.literal(new_id)))
                    value.value = new_id
    if target is not None and target.representation is not Representation.DECORATOR:
        col = physical_lines(source.text)[target.line - 1].find(f"[{old_id}]", target.col)
        if col < 0:
            msg = f"{target.location}: cannot locate the exact annotation ID"
            raise EditError(msg)
        changes.append((target.line, col, f"[{old_id}]", f"[{new_id}]"))
    text = source.text
    for line, col, old, new in sorted(set(changes), reverse=True):
        text = replace_at(text, line, col, old, new)
    edited = dataclasses.replace(source, text=text)
    if expected is None:
        ensure_unchanged(source.path, source.text, text, detect.todo_tags)
    elif ast.dump(expected, include_attributes=False) != ast.dump(ast.parse(text), include_attributes=False):
        msg = f"{source.path}: reassignment changed program structure; nothing was written"
        raise EditError(msg)
    after = scan_file(edited, detect, runtime_modules, hierarchy, pytest_marker=pytest_marker)
    ensure_static(after.diagnostics)
    if _tags(before, old_id, new_id) != _tags(after, "", "") or _links(before, old_id, new_id) != _links(after, "", ""):
        msg = f"{source.path}: identity reassignment did not round-trip; nothing was written"
        raise EditError(msg)
    return edited, after
