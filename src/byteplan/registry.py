# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""The JSON task registry: validation on load and deterministic serialization.

Serialization is byte-stable: sorted keys, 2-space indentation, LF newlines,
and a trailing newline, so an unchanged registry always re-serializes to the
same bytes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, NoReturn

from byteplan.errors import RegistryError
from byteplan.ids import is_valid_id
from byteplan.models import (
    AttachmentKind,
    HistoryEvent,
    Origin,
    Presence,
    Representation,
    ScopeState,
    SourceRef,
    Status,
    Task,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from enum import StrEnum
    from pathlib import Path

    _Fail = Callable[[str], NoReturn]

SCHEMA_VERSION = 1

_TASK_KEYS = frozenset({
    "id", "kind", "title", "description", "status", "priority", "assignee", "labels", "notes",
    "title_override", "presence", "origin", "scope_state", "source", "stub", "first_seen",
    "last_seen", "history",
})  # fmt: skip


@dataclass
class Registry:
    reserved_ids: set[str] = field(default_factory=set)
    tasks: dict[str, Task] = field(default_factory=dict)

    def get(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)


def load_registry(path: Path) -> Registry:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        msg = f"registry {path} does not exist; run `byteplan init` first"
        raise RegistryError(msg) from None
    except (OSError, UnicodeDecodeError) as exc:
        msg = f"cannot read registry {path}: {exc}"
        raise RegistryError(msg) from exc
    return loads(text, str(path))


def loads(text: str, name: str = "registry") -> Registry:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        msg = f"{name} is not valid JSON (line {exc.lineno}, column {exc.colno}): {exc.msg}"
        raise RegistryError(msg) from exc
    return from_dict(data, name)


def from_dict(data: Any, name: str = "registry") -> Registry:
    def fail(problem: str) -> NoReturn:
        msg = f"{name}: {problem}"
        raise RegistryError(msg)

    if not isinstance(data, dict):
        fail("top level must be an object")
    version = data.get("schema_version")
    if not isinstance(version, int) or isinstance(version, bool):
        fail("missing or invalid schema_version")
    if version > SCHEMA_VERSION:
        fail(f"schema_version {version} is newer than this byteplan supports ({SCHEMA_VERSION}); upgrade byteplan")
    if version < 1:
        fail(f"unsupported schema_version {version}")

    reserved = data.get("reserved_ids", [])
    if not isinstance(reserved, list) or not all(isinstance(i, str) and is_valid_id(i) for i in reserved):
        fail("reserved_ids must be a list of four-hex-digit IDs")
    tasks_data = data.get("tasks", {})
    if not isinstance(tasks_data, dict):
        fail("tasks must be an object")

    registry = Registry(reserved_ids=set(reserved))
    for key, raw in tasks_data.items():
        task = _task_from_dict(key, raw, fail)
        if key not in registry.reserved_ids:
            fail(f"task {key} is not in reserved_ids")
        registry.tasks[key] = task
    return registry


def _task_from_dict(key: str, raw: Any, fail: _Fail) -> Task:
    where = f"task {key!r}"
    if not is_valid_id(key):
        fail(f"{where}: key is not a four-hex-digit ID")
    if not isinstance(raw, dict):
        fail(f"{where} must be an object")
    if raw.get("id") != key:
        fail(f"{where}: id field {raw.get('id')!r} does not match its key")

    def text(name: str, *, default: str | None = "", optional: bool = False) -> Any:
        value = raw.get(name, default)
        if value is None and optional:
            return None
        if not isinstance(value, str):
            fail(f"{where}: {name} must be a string")
        return value

    def enum(name: str, cls: type[StrEnum], default: StrEnum) -> Any:
        value = raw.get(name, str(default))
        try:
            return cls(value)
        except ValueError:
            allowed = ", ".join(member.value for member in cls)
            fail(f"{where}: {name} {value!r} is not one of {allowed}")

    labels = raw.get("labels", [])
    if not isinstance(labels, list) or not all(isinstance(label, str) for label in labels):
        fail(f"{where}: labels must be a list of strings")
    stub = raw.get("stub")
    if stub is not None and not isinstance(stub, dict):
        fail(f"{where}: stub must be an object or null")

    return Task(
        id=key,
        kind=text("kind", default=None),
        title=text("title", default=None),
        description=text("description"),
        status=enum("status", Status, Status.OPEN),
        priority=text("priority", default="normal"),
        assignee=text("assignee", default=None, optional=True),
        labels=list(labels),
        notes=text("notes"),
        title_override=text("title_override", default=None, optional=True),
        presence=enum("presence", Presence, Presence.UNKNOWN),
        origin=enum("origin", Origin, Origin.COMMENT),
        scope_state=enum("scope_state", ScopeState, ScopeState.IN_SCOPE),
        source=_source_from_dict(raw.get("source"), where, fail),
        stub=stub,
        first_seen=text("first_seen", default=None, optional=True),
        last_seen=text("last_seen", default=None, optional=True),
        history=_history_from_list(raw.get("history", []), where, fail),
        extra={k: v for k, v in raw.items() if k not in _TASK_KEYS},
    )


def _source_from_dict(raw: Any, where: str, fail: _Fail) -> SourceRef | None:
    if raw is None:
        return None
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("path"), str)
        or not isinstance(raw.get("line"), int)
        or not isinstance(raw.get("symbol"), str | None)
        or not isinstance(raw.get("decl_line"), int | None)
    ):
        fail(f"{where}: source must be an object with path, line and symbol")

    def optional_enum(name: str, cls: type[StrEnum]) -> Any:
        value = raw.get(name)
        if value is None:
            return None
        try:
            return cls(value)
        except ValueError:
            fail(f"{where}: source.{name} {value!r} is not one of {', '.join(m.value for m in cls)}")

    return SourceRef(
        raw["path"],
        raw["line"],
        raw.get("symbol"),
        raw.get("decl_line"),
        optional_enum("attachment_kind", AttachmentKind),
        optional_enum("representation", Representation),
    )


def _history_from_list(raw: Any, where: str, fail: _Fail) -> list[HistoryEvent]:
    if not isinstance(raw, list):
        fail(f"{where}: history must be a list")
    events = []
    for entry in raw:
        if (
            not isinstance(entry, dict)
            or not isinstance(entry.get("event"), str)
            or not isinstance(entry.get("at"), str)
        ):
            fail(f"{where}: history entries need string event and at fields")
        note = entry.get("note")
        if note is not None and not isinstance(note, str):
            fail(f"{where}: history note must be a string")
        events.append(HistoryEvent(entry["event"], entry["at"], entry.get("old"), entry.get("new"), note))
    return events


def task_to_dict(task: Task) -> dict[str, Any]:
    data: dict[str, Any] = dict(task.extra)
    data.update(
        {
            "id": task.id,
            "kind": task.kind,
            "title": task.title,
            "title_override": task.title_override,
            "description": task.description,
            "status": str(task.status),
            "priority": task.priority,
            "assignee": task.assignee,
            "labels": list(task.labels),
            "notes": task.notes,
            "presence": str(task.presence),
            "origin": str(task.origin),
            "scope_state": str(task.scope_state),
            "source": None if task.source is None else _source_to_dict(task.source),
            "stub": task.stub,
            "first_seen": task.first_seen,
            "last_seen": task.last_seen,
            "history": [_event_to_dict(e) for e in task.history],
        }
    )
    return data


def _source_to_dict(source: SourceRef) -> dict[str, Any]:
    return {
        "path": source.path,
        "line": source.line,
        "symbol": source.symbol,
        "decl_line": source.decl_line,
        "attachment_kind": None if source.attachment_kind is None else str(source.attachment_kind),
        "representation": None if source.representation is None else str(source.representation),
    }


def _event_to_dict(event: HistoryEvent) -> dict[str, Any]:
    data: dict[str, Any] = {"event": event.event, "at": event.at, "old": event.old, "new": event.new}
    if event.note is not None:
        data["note"] = event.note
    return data


def to_dict(registry: Registry) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "reserved_ids": sorted(registry.reserved_ids),
        "tasks": {task_id: task_to_dict(registry.tasks[task_id]) for task_id in sorted(registry.tasks)},
    }


def dumps(registry: Registry) -> str:
    return json.dumps(to_dict(registry), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
