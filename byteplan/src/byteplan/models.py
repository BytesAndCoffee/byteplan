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


class ScopeState(StrEnum):
    IN_SCOPE = "in_scope"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class SourceRef:
    path: str
    line: int
    symbol: str | None = None


@dataclass(frozen=True)
class HistoryEvent:
    event: str
    at: str
    old: Any = None
    new: Any = None


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
class CommentTag:
    """One tagged comment block discovered in source.

    ``line`` and ``col`` locate the ``#`` of the first line (1-based line, 0-based
    column). ``insert_col`` is where ``[abcd]`` goes when annotating an untagged tag.
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
    insert_col: int

    @property
    def location(self) -> str:
        return f"{self.path}:{self.line}"
