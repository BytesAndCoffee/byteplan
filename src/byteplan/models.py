# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Domain models shared by the scanner, registry, and front ends."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"

    @property
    def is_closed(self) -> bool:
        return self in {Status.RESOLVED, Status.DISMISSED}


class Presence(StrEnum):
    PRESENT = "present"
    MISSING = "missing"
    UNKNOWN = "unknown"


class Origin(StrEnum):
    COMMENT = "comment"
    STUB = "stub"
    DECORATOR = "decorator"


class Representation(StrEnum):
    COMMENT = "comment"
    DECORATOR = "decorator"


class AttachmentKind(StrEnum):
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    # Inside a function or class body, not attached to a declaration.
    STATEMENT = "statement"
    MODULE = "module"


class ScopeState(StrEnum):
    IN_SCOPE = "in_scope"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class SourceRef:
    path: str
    line: int  # the annotation's line
    symbol: str | None = None
    decl_line: int | None = None  # the attached declaration's def/class line
    attachment_kind: AttachmentKind | None = None
    representation: Representation | None = None


@dataclass(frozen=True)
class HistoryEvent:
    event: str
    at: str
    old: Any = None
    new: Any = None
    note: str | None = None


@dataclass
class Task:
    """A registry entry. Discovered fields are refreshed by scans; managed fields never are."""

    id: str
    kind: str
    title: str
    description: str = ""
    # Managed fields.
    status: Status = Status.OPEN
    priority: str = "normal"
    assignee: str | None = None
    labels: list[str] = field(default_factory=list)
    notes: str = ""
    title_override: str | None = None
    # Discovery and bookkeeping.
    presence: Presence = Presence.UNKNOWN
    origin: Origin = Origin.COMMENT
    scope_state: ScopeState = ScopeState.IN_SCOPE
    source: SourceRef | None = None
    stub: dict[str, Any] | None = None
    first_seen: str | None = None
    last_seen: str | None = None
    history: list[HistoryEvent] = field(default_factory=list)
    # Unknown keys from newer tools, carried through unchanged.
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def display_title(self) -> str:
        return self.title_override or self.title


@dataclass(frozen=True)
class IdSlot:
    """Where an allocated ID is written: insert ``template`` (``{id}`` replaced) at line/col."""

    line: int  # 1-based
    col: int  # 0-based, in characters
    template: str

    def text(self, task_id: str) -> str:
        return self.template.replace("{id}", task_id)


@dataclass(frozen=True)
class Annotation:
    """One task declaration found in source: a tag comment, a ``@todo`` decorator, or a
    proposed comment for an unowned stub.

    ``line``/``col`` locate the annotation (the ``#`` or the ``@``). ``id_slot`` is set
    when the annotation has no ID yet and says where one would be written.
    """

    path: str
    line: int
    end_line: int
    col: int
    kind: str
    tag_text: str
    task_id: str | None
    title: str
    description: str
    symbol: str | None
    trailing: bool
    id_slot: IdSlot | None = None
    representation: Representation = Representation.COMMENT
    origin: Origin = Origin.COMMENT
    decl_line: int | None = None
    attachment_kind: AttachmentKind | None = None
    # Whether the declaration this annotation owns is currently a stub (None: owns none).
    decl_is_stub: bool | None = None

    @property
    def location(self) -> str:
        return f"{self.path}:{self.line}"
