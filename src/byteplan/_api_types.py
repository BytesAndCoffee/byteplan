# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Canonical result types and sentinel shared by the facade and internal operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from byteplan.diagnostics import Diagnostic
from byteplan.reconcile import Summary

if TYPE_CHECKING:
    from byteplan import verification
    from byteplan.files import Scope
    from byteplan.models import Annotation, Task
    from byteplan.normalize import Rewrite
    from byteplan.persistence import (
        FileWrite,
    )
    from byteplan.scanner.decorators import VerifiesLink

# Path and Diagnostic stay available at runtime: generated constructors resolve
# their annotations in this module, even with the public class identity retained.
__all__ = (
    "UNSET",
    "ArchiveReport",
    "CleanupReport",
    "Diagnostic",
    "InitResult",
    "Path",
    "Proposal",
    "ReconcileReport",
    "ReleaseReport",
    "RepairResult",
    "RestoreReport",
    "ScaffoldResult",
    "ScanReport",
    "SyncReport",
    "TaskVerification",
    "VerifyReport",
    "_Unset",
)


class _Unset:  # byteplan: ignore - a sentinel is meant to be empty
    """Sentinel for "leave this field alone" where ``None`` means "clear it"."""


UNSET: Any = _Unset()


@dataclass(frozen=True)
class Proposal:
    """An untagged discovery and the ID it is annotated with."""

    tag: Annotation
    task_id: str


@dataclass(frozen=True)
class TaskVerification:
    task: Task
    readiness: verification.Readiness
    results: dict[str, verification.TestResult]  # this run's results for the task's tests


@dataclass(frozen=True)
class VerifyReport:
    tasks: tuple[TaskVerification, ...]
    argv: tuple[str, ...]
    returncode: int | None
    timed_out: bool = False
    output: str = ""

    @property
    def failed(self) -> bool:
        """Any requested test that didn't pass or skip as expected: no false passes."""
        bad = {"failed", "error", "timeout", "not_found", "not_run"}
        return self.timed_out or any(r.outcome in bad for t in self.tasks for r in t.results.values())


@dataclass(frozen=True)
class ScaffoldResult:
    task: Task
    node: str  # the new test, or the existing one when nothing was written
    path: str
    created_file: bool = False
    existing: tuple[str, ...] = ()  # already-linked tests (then nothing was written)
    dry_run: bool = False
    text: str = ""  # the planned file text
    written: tuple[str, ...] = ()
    imports: tuple[str, ...] = ()  # import lines the scaffold adds
    function: str = ""  # the test function the scaffold adds


@dataclass(frozen=True)
class ReleaseReport:
    version: str
    files: tuple[str, ...]
    decorators: int
    imports: int
    tasks: tuple[str, ...]  # task IDs now `stripped`
    dry_run: bool = False
    warnings: tuple[Diagnostic, ...] = ()
    written: tuple[str, ...] = ()
    smoke_test: str = "not_run"  # or "passed" (a failure raises after restoring)
    smoke_imports: tuple[str, ...] = ()


@dataclass(frozen=True)
class RestoreReport:
    files: tuple[str, ...]
    decorators: int
    imports: int
    tasks: tuple[str, ...]  # task IDs back to `present`
    conflicts: tuple[str, ...] = ()
    partial: bool = False  # some entries stay on record
    dry_run: bool = False
    written: tuple[str, ...] = ()


@dataclass(frozen=True)
class CleanupReport:
    removed: tuple[tuple[str, str], ...]  # (task ID, path) whose annotation was removed
    suppressed: tuple[tuple[str, str], ...] = ()  # replaced by `# byteplan: ignore` (--suppress-stubs)
    diagnostics: tuple[Diagnostic, ...] = ()
    dry_run: bool = True
    blocked: str | None = None
    written: tuple[str, ...] = ()
    imports_removed: tuple[str, ...] = ()  # files that lost an unused runtime import


@dataclass(frozen=True)
class SyncReport:
    rewrites: tuple[Rewrite, ...]
    diagnostics: tuple[Diagnostic, ...]
    dry_run: bool = True
    # Why nothing could be planned (e.g. the tree needs a `byteplan scan` first).
    blocked: str | None = None
    written: tuple[str, ...] = ()
    imports_added: tuple[str, ...] = ()  # files that got a runtime import


@dataclass(frozen=True)
class ScanReport:
    scope: Scope
    tags: tuple[Annotation, ...]
    proposals: tuple[Proposal, ...]
    diagnostics: tuple[Diagnostic, ...]
    summary: Summary = field(default_factory=Summary)
    tracked: int = 0
    dry_run: bool = True
    # Writes were withheld because of blocking diagnostics (duplicate IDs).
    blocked: bool = False
    # Paths actually changed on disk (empty for dry runs).
    written: tuple[str, ...] = ()
    # Paths an interrupted earlier write was completed for before this scan.
    recovered: tuple[str, ...] = ()
    # Every file this scan would write (source edits, then the registry), with the hash of
    # the bytes it planned against. Populated for dry runs too.
    planned: tuple[FileWrite, ...] = ()
    # @verifies / marker links found in source.
    links: tuple[VerifiesLink, ...] = ()
    # Closed tasks moved to the archive after this (writing) scan.
    archived: tuple[str, ...] = ()
    # `tests.scaffold.auto`: (task ID, test node) scaffolded for tasks this scan added, and
    # (task ID, reason) for those it couldn't scaffold.
    scaffolded: tuple[tuple[str, str], ...] = ()
    scaffold_failures: tuple[tuple[str, str], ...] = ()
    runtime_decorated_files: tuple[str, ...] = ()

    @property
    def files_scanned(self) -> int:
        return len(self.scope.files)

    @property
    def tagged(self) -> tuple[Annotation, ...]:
        return tuple(tag for tag in self.tags if tag.task_id is not None)

    @property
    def annotated_files(self) -> tuple[str, ...]:
        return tuple(sorted({p.tag.path for p in self.proposals}))


@dataclass(frozen=True)
class ArchiveReport:
    tasks: tuple[str, ...]  # archived (or, for a dry run, archivable) task IDs
    dry_run: bool = False
    written: tuple[str, ...] = ()
    # Eligible, but their current task/evidence isn't committed yet (another clone needs a durable copy).
    uncommitted: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReconcileReport:
    recovered: tuple[str, ...]  # restored into the local store from Git history
    missing: tuple[str, ...]  # in the index, but not found in this clone's history
    present: int  # already in the local store


@dataclass(frozen=True)
class RepairResult:
    task: Task
    written: tuple[str, ...]
    old_id: str | None = None
    planned: tuple[str, ...] = ()
    dry_run: bool = False


@dataclass
class InitResult:
    root: Path
    actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# Retain the public identity and pickle lookup paths after moving definitions.
for _public_type in (
    _Unset,
    Proposal,
    TaskVerification,
    VerifyReport,
    ScaffoldResult,
    ReleaseReport,
    RestoreReport,
    CleanupReport,
    SyncReport,
    ScanReport,
    ArchiveReport,
    ReconcileReport,
    RepairResult,
    InitResult,
):
    _public_type.__module__ = "byteplan.api"
