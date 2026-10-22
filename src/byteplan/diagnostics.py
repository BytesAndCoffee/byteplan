# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
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
    IMPLEMENTATION_COMPLETE_CANDIDATE = "implementation_complete_candidate"
    UNKNOWN_TASK_REFERENCE = "unknown_task_reference"
    # Snapshot consistency (check --staged / --commit, or require_reconciled)
    NEW_UNREGISTERED = "new_unregistered"
    REGISTRY_NOT_STAGED = "registry_not_staged"
    REGISTRY_OUT_OF_SYNC = "registry_out_of_sync"
    POSITION_DRIFT = "position_drift"
    STAGED_CONFIG_MISMATCH = "staged_config_mismatch"
    WORKING_TREE_CHANGED_BUT_NOT_STAGED = "working_tree_changed_but_not_staged"
    REPORT_OUT_OF_SYNC = "report_out_of_sync"
    # Acceptance-test links
    MALFORMED_TEST_ID = "malformed_test_id"
    TEST_NOT_IN_SCOPE = "test_not_in_scope"
    SCAFFOLD_PLACEHOLDER = "scaffold_placeholder"
    # byteplan sync
    CONVERSION_NEEDS_REVIEW = "conversion_needs_review"
    # byteplan release / restore
    RELEASE_STRIPPED = "release_stripped"
    RELEASE_ON_DEFAULT_BRANCH = "release_on_default_branch"
    RUNTIME_DEPENDENCY_IN_RELEASE = "runtime_dependency_in_release"
    UNFINISHED_SCAFFOLD_IN_SDIST = "unfinished_scaffold_in_sdist"
    # byteplan sync --remove-resolved
    RESOLVED_BUT_STUBBED = "resolved_but_stubbed"
    CLEANUP_NEEDS_REVIEW = "cleanup_needs_review"


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


_CONSISTENCY_FAILURES = frozenset({
    Code.NEW_UNREGISTERED, Code.REGISTRY_NOT_STAGED, Code.REGISTRY_OUT_OF_SYNC, Code.UNREGISTERED_ID,
})  # fmt: skip


def is_failure(diagnostic: Diagnostic, policy: CheckConfig, *, enforce_consistency: bool = False) -> bool:
    """Whether ``diagnostic`` makes ``check``/``scan`` exit with ``EXIT_FINDINGS``.

    ``enforce_consistency`` is set for snapshot checks (``--staged``, ``--commit``) and
    for the working-tree check when ``require_reconciled`` is configured.
    """
    if diagnostic.code in _CONSISTENCY_FAILURES:
        return enforce_consistency
    match diagnostic.code:
        case Code.DUPLICATE_ID:
            return policy.fail_on_duplicate_ids
        case Code.MISSING:
            return policy.fail_on_missing
        case Code.STALE_ANNOTATION:
            return policy.fail_on_stale_annotations
        case Code.POSITION_DRIFT:
            return policy.fail_on_position_drift
        case Code.REPORT_OUT_OF_SYNC:
            return policy.fail_on_stale_report
        case _:
            return False


def exit_code(diagnostics: Iterable[Diagnostic], policy: CheckConfig, *, enforce_consistency: bool = False) -> int:
    failing = any(is_failure(d, policy, enforce_consistency=enforce_consistency) for d in diagnostics)
    return EXIT_FINDINGS if failing else EXIT_OK
