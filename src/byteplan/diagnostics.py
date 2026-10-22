# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Diagnostic codes, severities, and the exit-code policy."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from byteplan.config import CheckConfig

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Code(StrEnum):
    DUPLICATE_ID = "duplicate_id"
    UNREGISTERED_ID = "unregistered_id"
    MALFORMED_ID = "malformed_id"
    STALE_ANNOTATION = "stale_annotation"
    MISSING = "missing"
    PENDING_JOURNAL = "pending_journal"
    UNRESOLVED_TODO_DECORATOR = "unresolved_todo_decorator"
    INVALID_TODO_DECORATOR = "invalid_todo_decorator"
    DYNAMIC_TODO_ARGUMENT = "dynamic_todo_argument"
    CONFLICTING_TEST_ARGUMENTS = "conflicting_test_arguments"
    DECORATOR_NEEDS_REVIEW = "decorator_needs_review"
    STUB_NEEDS_REVIEW = "stub_needs_review"
    IMPLEMENTATION_CHANGED = "implementation_changed"
    UNKNOWN_TASK_REFERENCE = "unknown_task_reference"


@dataclass(frozen=True)
class Location:
    path: str
    line: int | None = None

    def __str__(self) -> str:
        return self.path if self.line is None else f"{self.path}:{self.line}"


@dataclass(frozen=True)
class Diagnostic:
    code: Code
    severity: Severity
    message: str
    task_id: str | None = None
    locations: tuple[Location, ...] = ()
    hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": str(self.code),
            "severity": str(self.severity),
            "message": self.message,
            "task_id": self.task_id,
            "locations": [{"path": loc.path, "line": loc.line} for loc in self.locations],
            "hint": self.hint,
        }

    def format_text(self) -> str:
        marker = {Severity.ERROR: "!", Severity.WARNING: "!", Severity.INFO: "·"}[self.severity]
        ident = f"[{self.task_id}]" if self.task_id else "[----]"
        where = " and ".join(str(loc) for loc in self.locations)
        text = f"{marker} {ident} {self.code.upper():<17} {where}".rstrip()
        text += f"\n    {self.message}"
        if self.hint:
            text += f"\n    hint: {self.hint}"
        return text


def is_failure(diagnostic: Diagnostic, policy: CheckConfig) -> bool:
    """Whether ``diagnostic`` makes ``check``/``scan`` exit with ``EXIT_FINDINGS``."""
    match diagnostic.code:
        case Code.DUPLICATE_ID:
            return policy.fail_on_duplicate_ids
        case Code.MISSING:
            return policy.fail_on_missing
        case Code.STALE_ANNOTATION:
            return policy.fail_on_stale_annotations
        case _:
            return False


def exit_code(diagnostics: Iterable[Diagnostic], policy: CheckConfig) -> int:
    return EXIT_FINDINGS if any(is_failure(d, policy) for d in diagnostics) else EXIT_OK
