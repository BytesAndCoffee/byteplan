# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Programmatic surface shared by the CLI, the Hatch hook, and the MCP server."""

from __future__ import annotations

import contextlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from byteplan import archive, gitio, reporting, scaffold, verification
from byteplan import registry as registry_io
from byteplan.config import (
    PYPROJECT,
    Config,
    config_from_text,
    find_project_root,
    load_config,
    parse_pyproject_text,
)
from byteplan.diagnostics import Code, Diagnostic, Location, Severity, exit_code
from byteplan.errors import (
    ConfigError,
    RegistryError,
)
from byteplan.ids import allocate
from byteplan.models import HistoryEvent, Presence, Status
from byteplan.persistence import (
    STATE_DIR,
    FileWrite,
    commit,
    pending_journal,
    project_lock,
    recover,
    sha256,
    staged_dir,
)
from byteplan.registry import Registry, load_registry
from byteplan.snapshot import GitSnapshot

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Iterator, Sequence

    from byteplan.files import Scope, ScopeMatcher
    from byteplan.models import Annotation, Task
    from byteplan.scanner.hierarchy import ClassHierarchy
    from byteplan.scanner.source import SourceFile

from byteplan._api_types import (
    UNSET,
    ArchiveReport,
    CleanupReport,
    InitResult,
    Proposal,
    ReconcileReport,
    ReleaseReport,
    RepairResult,
    RestoreReport,
    ScaffoldResult,
    ScanReport,
    SyncReport,
    TaskVerification,
    VerifyReport,
    _Unset,
)
from byteplan.operations import archive as archive_ops
from byteplan.operations import common as common_ops
from byteplan.operations import initialize as initialize_ops
from byteplan.operations import release as release_ops
from byteplan.operations import scaffold as scaffold_ops
from byteplan.operations import scan as scan_ops
from byteplan.operations import sync as sync_ops
from byteplan.operations import tasks as tasks_ops
from byteplan.operations import verify as verify_ops
from byteplan.operations.common import _read_bytes
from byteplan.operations.initialize import BYTEPLAN_GITIGNORE, RUNTIME_SHIM

__all__ = (
    "BYTEPLAN_GITIGNORE",
    "RUNTIME_SHIM",
    "UNSET",
    "ArchiveReport",
    "CleanupReport",
    "Config",
    "InitResult",
    "Presence",
    "Project",
    "Proposal",
    "ReconcileReport",
    "Registry",
    "ReleaseReport",
    "RepairResult",
    "RestoreReport",
    "ScaffoldResult",
    "ScanReport",
    "Status",
    "SyncReport",
    "TaskVerification",
    "VerifyReport",
    "init_project",
    "is_node_id",
    "normalize_review",
    "sdist_files",
    "shim_module_name",
    "utc_now",
)

# Keep the sentinel class available at its historical pickle lookup path.
_Unset.__module__ = __name__


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Project:
    def __init__(
        self,
        config: Config,
        clock: Callable[[], str] = utc_now,
        snapshot: GitSnapshot | None = None,
        notices: Sequence[Diagnostic] = (),
    ) -> None:
        self.config = config
        self.clock = clock
        # None: the working tree. Otherwise a read-only Git index or commit snapshot.
        self.snapshot = snapshot
        self._notices = list(notices)
        # Adapters may narrow automatic recovery to their requested write authority.
        # None preserves ordinary CLI/API recovery; source writers still stay confined.
        self._recovery_allowed_targets: frozenset[str] | None = None

    @classmethod
    def open(cls, start: Path | None = None, clock: Callable[[], str] = utc_now) -> Project:
        return cls(load_config(find_project_root(start or Path.cwd())), clock)

    @classmethod
    def open_snapshot(
        cls, start: Path | None = None, rev: str | None = None, clock: Callable[[], str] = utc_now
    ) -> Project:
        """A read-only project over the Git index (``rev=None``) or a commit.

        Configuration, ``.gitignore`` files, the registry and all sources come from
        the snapshot, never from the working tree.
        """
        snapshot = GitSnapshot(start or Path.cwd(), rev)  # finds the project in the snapshot
        root = snapshot.root
        try:
            config, notices = _snapshot_config(root, snapshot)
        except BaseException:
            snapshot.close()  # stop the cat-file process before propagating
            raise
        return cls(config, clock, snapshot, notices)

    def close(self) -> None:
        if self.snapshot is not None:
            self.snapshot.close()

    @property
    def enforce_consistency(self) -> bool:
        return self.snapshot is not None or self.config.check.require_reconciled

    @property
    def root(self) -> Path:
        return self.config.root

    @property
    def registry_rel(self) -> str:
        return self.config.registry_path.relative_to(self.root).as_posix()

    @property
    def report_rel(self) -> str | None:
        if not self.config.report_file:
            return None
        return (self.root / self.config.report_file).resolve().relative_to(self.root.resolve()).as_posix()

    def load_registry(self) -> Registry:
        if self.snapshot is not None:
            return self._read_registry()[1]
        return load_registry(self.config.registry_path)

    def render_report(self, registry: Registry) -> bytes:
        """The ``report_file`` content for ``registry``."""
        report_rel = self.report_rel or "byteplan.md"
        return reporting.plan_markdown(registry, registry_rel=self.registry_rel, report_rel=report_rel).encode()

    def _current_report(self) -> bytes | None:
        if self.report_rel is None:
            return None
        if self.snapshot is not None:
            return self.snapshot.read(self.report_rel)
        return _read_bytes(self.root / self.report_rel)

    @property
    def maintains_report(self) -> bool:
        """Whether this checkout writes and checks ``report_file``: always, unless
        ``report_branch`` names another branch than the one checked out. A detached HEAD
        (e.g. CI checking out a pull request) isn't on the report branch."""
        if self.report_rel is None:
            return False
        if not self.config.report_branch:
            return True
        try:
            branch = gitio.git(["symbolic-ref", "--quiet", "--short", "HEAD"], self.root).strip()
        except ConfigError:
            return False
        return branch == self.config.report_branch

    def _report_write(self, report_rel: str, registry: Registry) -> FileWrite:
        current = self._current_report()
        data = self.render_report(registry)
        if current is not None and current.replace(b"\r\n", b"\n") == data:
            data = current  # only the line endings differ (e.g. core.autocrlf): leave it
        return FileWrite(report_rel, None if current is None else sha256(current), data)

    def _registry_writes(self, registry_hash: str | None, registry: Registry) -> list[FileWrite]:
        """The registry write, preceded by the report file's when this checkout maintains one."""
        writes = []
        if self.report_rel is not None and self.maintains_report:
            writes.append(self._report_write(self.report_rel, registry))
        writes.append(FileWrite(self.registry_rel, registry_hash, registry_io.dumps(registry).encode()))
        return writes

    def write_report(self) -> bool:
        """Regenerate ``report_file`` from the registry on any branch (``report --write``):
        how ``report_branch`` gets its copy updated after a merge. True if it changed."""
        self._require_working_tree()
        if self.report_rel is None:
            msg = "no report_file is configured in [tool.byteplan]"
            raise ConfigError(msg)
        with self._writing():
            write = self._report_write(self.report_rel, self.load_registry())
            if self._current_report() == write.data:
                return False
            commit(self.root, [write])
        return True

    def _read_registry(self) -> tuple[str, Registry]:
        """The registry plus the hash of the exact bytes it was parsed from."""
        path = self.config.registry_path
        if self.snapshot is not None:
            data = self.snapshot.read(self.registry_rel)
            if data is None:
                msg = f"registry {self.registry_rel} does not exist in the {self.snapshot.label}"
                raise RegistryError(msg)
            try:
                return sha256(data), registry_io.loads(
                    data.decode("utf-8"), f"{self.snapshot.label}:{self.registry_rel}"
                )
            except UnicodeDecodeError as exc:
                msg = f"cannot read registry in the {self.snapshot.label}: {exc}"
                raise RegistryError(msg) from exc
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            msg = f"registry {path} does not exist; run `byteplan init` first"
            raise RegistryError(msg) from None
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            msg = f"cannot read registry {path}: {exc}"
            raise RegistryError(msg) from exc
        return sha256(data), registry_io.loads(text, str(path))

    def migrate(self, *, dry_run: bool = False) -> tuple[str, ...]:
        """Explicitly upgrade registry metadata through the journal; never edit source."""
        if self.snapshot is not None:
            msg = "registry migration requires the working tree"
            raise ConfigError(msg)
        context = contextlib.nullcontext(()) if dry_run else self._writing()
        with context:
            before, registry = self._read_registry()
            if registry.schema_version == registry_io.SCHEMA_VERSION:
                return ()
            # Change only the schema boundary: preserve even nested extension metadata
            # that the current domain model does not interpret.
            data = json.loads(self.config.registry_path.read_bytes())
            data["schema_version"] = registry_io.SCHEMA_VERSION
            encoded = (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
            writes = [FileWrite(self.registry_rel, before, encoded)]
            return tuple(w.path for w in writes) if dry_run else tuple(commit(self.root, writes))

    @contextlib.contextmanager
    def _writing(self, *, recover_pending: bool = True) -> Iterator[tuple[str, ...]]:
        """Hold the project lock and finish any interrupted write first."""
        self._require_working_tree()
        if (staged_dir(self.root) / "journal.json").exists():
            msg = (
                "an interrupted staged reconciliation is pending; run `byteplan scan --staged --apply` "
                "to finish or undo it first"
            )
            raise ConfigError(msg)
        with project_lock(self.root):
            if not recover_pending and pending_journal(self.root):
                msg = "an ordinary transaction is pending; run `byteplan scan` to recover it before collision repair"
                raise ConfigError(msg)
            recovered: tuple[str, ...] = ()
            if recover_pending:
                if self._recovery_allowed_targets is None:
                    recovered = tuple(recover(self.root))
                else:
                    recovered = tuple(recover(self.root, allowed_targets=self._recovery_allowed_targets))
            yield recovered

    def _require_working_tree(self) -> None:
        if self.snapshot is not None:
            msg = f"the {self.snapshot.label} is read-only; open the working-tree project for mutation or execution"
            raise ConfigError(msg)

    def exit_code(self, diagnostics: Iterable[Diagnostic]) -> int:
        return exit_code(diagnostics, self.config.check, enforce_consistency=self.enforce_consistency)

    def scan(
        self,
        targets: Sequence[str | Path] | None = None,
        cwd: Path | None = None,
        *,
        dry_run: bool = True,
    ) -> ScanReport:
        """Discover tags, allocate IDs, and reconcile the registry.

        With ``dry_run`` (the default) nothing is written; the report shows the
        plan. Raises ``ScanError`` if any in-scope file fails to read, decode,
        or parse, in which case nothing is reconciled or written.
        """
        return scan_ops.scan(self, targets, cwd, dry_run=dry_run)

    def _auto_scaffold(self, report: ScanReport) -> ScanReport:
        """Scaffold tests for the open tasks ``report`` added in Python files outside the test directory."""
        return scan_ops.auto_scaffold(self, report)

    def _scan(
        self,
        targets: Sequence[str | Path] | None,
        cwd: Path | None,
        *,
        dry_run: bool,
        recovered: tuple[str, ...],
    ) -> ScanReport:
        return scan_ops.scan_core(self, targets, cwd, dry_run=dry_run, recovered=recovered)

    def _read(self, path: str) -> SourceFile:
        return scan_ops.read_source_view(self, path)

    def _hierarchy(self, loaded: dict[str, SourceFile], *, narrowed: bool) -> ClassHierarchy | None:
        """The class index over the *whole* scope, even for a narrowed scan: whether a base
        class's method is an interface depends on subclasses that may live elsewhere."""
        return scan_ops.hierarchy(self, loaded, narrowed=narrowed)

    def _consistency(
        self,
        old: Registry,
        new: Registry,
        proposals: Sequence[Proposal],
        diagnostics: Sequence[Diagnostic],
        *,
        registry_absent: bool,
    ) -> list[Diagnostic]:
        """Is this snapshot's code already reconciled with this snapshot's registry?"""
        return scan_ops.consistency(self, old, new, proposals, diagnostics, registry_absent=registry_absent)

    def _test_link_diagnostics(
        self, registry: Registry, observed: Sequence[Annotation], matcher: ScopeMatcher
    ) -> list[Diagnostic]:
        """``malformed_test_id`` for bad node IDs in source; ``test_not_in_scope`` for linked tests
        whose file isn't scanned (so their @verifies and freshness can't be seen)."""
        return scan_ops.test_link_diagnostics(self, registry, observed, matcher)

    def _complete_candidates(self, found: list[Diagnostic], registry: Registry) -> list[Diagnostic]:
        """``implementation_changed`` becomes ``implementation_complete_candidate`` when the task's
        linked tests are fresh and passing. Advisory only: nothing is resolved."""
        return scan_ops.complete_candidates(self, found, registry)

    def _missing_diagnostics(self, registry: Registry) -> list[Diagnostic]:
        return scan_ops.missing_diagnostics(self, registry)

    def list_tasks(
        self,
        statuses: Iterable[Status] | None = None,
        presences: Iterable[Presence] | None = None,
        kinds: Iterable[str] | None = None,
    ) -> list[Task]:
        return tasks_ops.list_tasks(self, statuses, presences, kinds)

    def _resolve_task_id(self, query: str, registry: Registry | None = None, *, missing_ok: bool = False) -> str:
        return tasks_ops.resolve_task_id(self, query, registry, missing_ok=missing_ok)

    def get_task(self, task_id: str) -> Task:
        return tasks_ops.get_task(self, task_id)

    @property
    def archive_index_rel(self) -> str:
        return f"{STATE_DIR}/{archive.INDEX}"

    def archive_index(self) -> archive.Index:
        return archive_ops.archive_index(self)

    def archived_task(self, task_id: str) -> Task | None:
        """An archived task, from the local store (reconciled from Git history if needed)."""
        return archive_ops.archived_task(self, task_id)

    def archive(self, *, dry_run: bool = False, older_than: int | None = None) -> ArchiveReport:
        """Move tasks closed at least ``older_than`` (default ``after_days``) days ago, whose
        annotation is gone, out of ``tasks.json`` into the local store and the committed index.
        Their IDs stay reserved; their evidence moves with them. In a Git repository only
        records and current evidence already committed as they are are moved, preserving a
        recoverable copy. Automatic reconciliation recovers task records, not verification."""
        return archive_ops.archive(self, dry_run=dry_run, older_than=older_than)

    def _archived_evidence(self, task_id: str) -> verification.Evidence:
        """The evidence (and its run) archived with a task, as an ``Evidence`` of its own."""
        return archive_ops.archived_evidence(self, task_id)

    def _committed_records(self) -> dict[str, Any] | None:
        """Task records in ``HEAD``'s registry; None outside Git (no other clones to serve)."""
        return archive_ops.committed_records(self)

    def _committed_evidence(self) -> verification.Evidence:
        """HEAD's verification payload; staged or local-only evidence is not a durable copy."""
        return archive_ops.committed_evidence(self)

    def _ignore_archive_store(self) -> None:
        return archive_ops.ignore_archive_store(self)

    def restore_archived(self, task_id: str) -> tuple[str, ...]:
        """Put an archived task back into ``tasks.json`` (with its evidence, if this clone has it)."""
        return archive_ops.restore_archived(self, task_id)

    def reconcile_archive(self) -> ReconcileReport:
        """Fill the local store with every archived record it lacks, found by hash in the
        registry's Git history. Verification payloads are stored separately and are not
        automatically recovered by this traversal; reconciled records come without them."""
        return archive_ops.reconcile_archive(self)

    def check(self) -> ScanReport:
        """A read-only scan; ``exit_code(report.diagnostics)`` applies the check policy."""
        return scan_ops.check(self)

    def report(self) -> dict[str, Any]:
        """Registry summary plus current diagnostics, for text/JSON/Markdown output."""
        return scan_ops.report(self)

    def runner(self) -> list[str]:
        return verify_ops.runner(self)

    def _evidence(self) -> verification.Evidence:
        return verify_ops.evidence(self)

    def readiness(self, task: Task, evidence: verification.Evidence | None = None) -> verification.Readiness:
        """Derived, never stored: ``unverified``, ``failing``, ``needs_review`` or ``ready_for_review``."""
        return verify_ops.readiness(self, task, evidence)

    def _placeholders(self, nodes: Iterable[str]) -> frozenset[str]:
        """Which of these node IDs are still scaffold placeholders (read statically from the
        working tree, or from the snapshot)."""
        return verify_ops.placeholders(self, nodes)

    def verify(self, task_ids: Sequence[str] | None = None) -> VerifyReport:
        """Run the linked tests of ``task_ids`` (default: every open task with links) and record
        the evidence in ``.byteplan/verification.json``. Never changes a task's status."""
        return verify_ops.verify(self, task_ids)

    def scaffold_test(
        self,
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
        return scaffold_ops.scaffold_test(
            self,
            task_id,
            path=path,
            name=name,
            policy=policy,
            link_style=link_style,
            force_new=force_new,
            dry_run=dry_run,
        )

    def _scaffold_path(self, task: Task, override: str | None, scope: Scope) -> str:
        return scaffold_ops.scaffold_path(self, task, override, scope)

    def _scaffold_target(self, task: Task) -> scaffold.Target:
        return scaffold_ops.scaffold_target(self, task)

    def ready(self) -> list[tuple[Task, verification.Readiness]]:
        """Open tasks whose evidence makes them ready for a human to review and resolve."""
        return verify_ops.ready(self)

    def stripped_release(self, registry: Registry | None = None) -> dict[str, Any] | None:
        """The registry's ``release`` block while the tree is stripped for a release."""
        return release_ops.stripped_release(self, registry)

    def _refuse_while_stripped(self, command: str) -> None:
        return release_ops.refuse_while_stripped(self, command)

    def release_version(self, override: str | None) -> str:
        return release_ops.release_version(self, override)

    def release(
        self,
        version: str | None = None,
        *,
        dry_run: bool = False,
        allow_dirty: bool = False,
        smoke_test: bool = False,
        offline: bool = False,
    ) -> ReleaseReport:
        """Strip for a release (see ``_strip_for_release``), then optionally smoke-test it.

        ``smoke_test`` builds a wheel from the stripped tree, installs it in isolation and
        imports it without ``byteplan_runtime``. If that fails, the strip is restored
        automatically, so a release is all-or-nothing, and ``ReleaseError`` reports why.
        """
        return release_ops.release(
            self, version, dry_run=dry_run, allow_dirty=allow_dirty, smoke_test=smoke_test, offline=offline
        )

    def _release_warnings(self) -> list[Diagnostic]:
        """``runtime_dependency_in_release`` and ``unfinished_scaffold_in_sdist``, for a stripped tree."""
        return release_ops.release_warnings(self)

    def _strip_for_release(
        self, version: str | None = None, *, dry_run: bool = False, allow_dirty: bool = False
    ) -> ReleaseReport:
        """Strip BytePlan's runtime decorators and imports in place, recording each one.

        Never commits, tags, builds or resets, and never changes a task's status. Refuses (with
        nothing written) on a dirty tree, a pending journal, a blocked scan, an untagged
        ``@todo``, a decorator sharing a line, leftover runtime references, or an
        already-stripped tree.
        """
        return release_ops.strip_for_release(self, version, dry_run=dry_run, allow_dirty=allow_dirty)

    def _default_branch_warning(self) -> Diagnostic | None:
        return release_ops.default_branch_warning(self)

    def restore(self, *, dry_run: bool = False, partial: bool = False) -> RestoreReport:
        """Put every recorded decorator and import back (see ``release``).

        A file that still hashes to its stripped content is restored byte for byte; a changed
        one by AST anchors. Unplaceable entries are ``restore_conflict``: nothing is written,
        unless ``partial``, which restores the rest and keeps those on record.
        """
        return release_ops.restore(self, dry_run=dry_run, partial=partial)

    def cleanup(
        self, only: Sequence[str] | None = None, *, dry_run: bool = True, suppress_stubs: bool = False
    ) -> CleanupReport:
        """Remove the source annotations of resolved and dismissed tasks (only ``only``, if given).

        Open tasks are never touched. Each edit must keep Python's AST equal apart from
        BytePlan's own decorators and imports, and every edited file must re-scan to its old
        tasks minus the removed ones. The registry keeps the ID, the last source reference and
        the history, and logs ``cleaned`` (or ``suppressed``).
        """
        return sync_ops.cleanup(self, only, dry_run=dry_run, suppress_stubs=suppress_stubs)

    def runtime_module(self, *, development: bool = False) -> str | None:
        """The module to import ``todo``/``verifies`` from: ``byteplan_runtime`` when
        ``byteplan-runtime`` is a declared dependency, else a configured shim module present in
        scope, else None. ``development`` also counts dev dependencies (optional dependencies,
        dependency groups, Hatch environments), which is enough for test code."""
        return sync_ops.runtime_module(self, development=development)

    def sync(self, only: Sequence[str] | None = None, *, dry_run: bool = True) -> SyncReport:
        """Rewrite attached comments and unowned stubs to ``@todo(...)`` (decorator mode).

        Nothing happens unless ``[tool.byteplan.annotations] mode = "decorator"`` and at least
        one of ``convert_attached_comments`` / ``auto_decorate_stubs`` is on. The tree must be
        scanned first (no untagged annotations, no duplicate IDs).
        """
        return sync_ops.sync(self, only, dry_run=dry_run)

    def _scan_sources(
        self,
    ) -> tuple[list[Annotation], dict[str, tuple[SourceFile, str]], ClassHierarchy | None]:
        """Scan the whole scope as a normal scan would, including the class index, so repaired
        registry entries agree with what the next scan or check sees."""
        return scan_ops.scan_sources(self)

    def import_task(self, task_id: str) -> RepairResult:
        """Register an ID that is in source but not in the registry (``unregistered_id``)."""
        return tasks_ops.import_task(self, task_id)

    def reassign(self, path: str, line: int, *, against: str | None = None, dry_run: bool = False) -> RepairResult:
        """Reassign a duplicate copy, or preserve/rekey an independent branch collision via ``against``."""
        return tasks_ops.reassign(self, path, line, against=against, dry_run=dry_run)

    def _reassign_branch(self, path: str, line: int, against: str, *, dry_run: bool) -> RepairResult:
        """Rekey an independently created task before merging, preserving its full record."""
        return tasks_ops.reassign_branch(
            self, path, line, against, dry_run=dry_run, open_snapshot_factory=Project.open_snapshot
        )

    def _mutate(self, task_id: str, change: Callable[[Task, str], list[HistoryEvent]]) -> tuple[Task, bool]:
        return tasks_ops.mutate(self, task_id, change)

    def link_tests(self, task_id: str, nodes: Sequence[str]) -> tuple[Task, bool]:
        """Add managed test links (``byteplan tests add``). Node IDs are validated first."""
        return tasks_ops.link_tests(self, task_id, nodes)

    def unlink_tests(self, task_id: str, nodes: Sequence[str]) -> tuple[Task, bool]:
        """Remove managed test links (``byteplan tests remove``). Links declared in source can
        only be removed there."""
        return tasks_ops.unlink_tests(self, task_id, nodes)

    def set_status(self, task_id: str, status: Status, note: str | None = None) -> tuple[Task, bool]:
        """Change lifecycle status. Returns the task and whether anything changed."""
        return tasks_ops.set_status(self, task_id, status, note)

    def edit_task(
        self,
        task_id: str,
        *,
        priority: str | None = None,
        assignee: str | None = UNSET,
        title_override: str | None = UNSET,
        add_labels: Sequence[str] = (),
        remove_labels: Sequence[str] = (),
        notes: str | None = None,
        append_note: str | None = None,
    ) -> tuple[Task, bool]:
        """Update managed fields. Scans never overwrite any of these."""
        return tasks_ops.edit_task(
            self,
            task_id,
            priority=priority,
            assignee=assignee,
            title_override=title_override,
            add_labels=add_labels,
            remove_labels=remove_labels,
            notes=notes,
            append_note=append_note,
        )

    def _commit(self, writes: Sequence[FileWrite]) -> list[str]:
        """Late lookup keeps the existing api.commit patch boundary."""
        return commit(self.root, writes)

    @staticmethod
    def _allocate(seed: str, used: Collection[str]) -> str:
        """Late lookup keeps scanner and repair allocation patch targets."""
        return allocate(seed, used)

    @staticmethod
    def _plan_allocations(
        tags: Sequence[Annotation], registry: Registry, also_used: Iterable[str] = ()
    ) -> list[Proposal]:
        return _plan_allocations(tags, registry, also_used)


def _snapshot_config(root: Path, snapshot: GitSnapshot) -> tuple[Config, list[Diagnostic]]:
    data = snapshot.read(PYPROJECT)
    if data is None:
        msg = f"{PYPROJECT} is not in the {snapshot.label}"
        raise ConfigError(msg)
    text = data.decode("utf-8", "replace")
    config = config_from_text(root, text, f"{snapshot.label}:{PYPROJECT}")
    return config, (_config_mismatch(root, text) if snapshot.kind == "index" else [])


def _config_mismatch(root: Path, staged_text: str) -> list[Diagnostic]:
    """Warn when the working-tree [tool.byteplan] differs from the staged one (the staged one is used)."""
    disk = _read_bytes(root / PYPROJECT)
    if disk is None:
        return []
    try:
        on_disk = parse_pyproject_text(disk.decode("utf-8", "replace"), PYPROJECT).get("tool", {}).get("byteplan")
        staged = parse_pyproject_text(staged_text, PYPROJECT).get("tool", {}).get("byteplan")
    except ConfigError:
        return []
    if on_disk == staged:
        return []
    return [
        Diagnostic(
            Code.STAGED_CONFIG_MISMATCH,
            Severity.WARNING,
            "[tool.byteplan] in the working tree differs from the staged pyproject.toml; using the staged one",
            locations=(Location(PYPROJECT),),
            hint="stage pyproject.toml if the new settings belong in this commit",
        )
    ]


def is_node_id(node: str) -> bool:
    """A pytest node ID: ``path/to/test_x.py::name[::name...][param]``."""
    return common_ops.is_node_id(node)


def normalize_review(task_id: str, message: str) -> Diagnostic:
    return common_ops.normalize_review(task_id, message)


def sdist_files(root: Path) -> list[str]:
    """Project-relative paths a Hatch sdist would include: Hatchling's own file selection when
    it's importable, otherwise (conservatively) every file under ``tests/``."""
    return release_ops.sdist_files(root)


def shim_module_name(rel: str) -> str:
    """The import name of a shim at a project-relative path (``src/`` layouts supported)."""
    return initialize_ops.shim_module_name(rel)


def init_project(start: Path | None = None, *, runtime_shim: str | None = None) -> InitResult:
    """Create configuration and an empty registry. Safe to run repeatedly.

    ``runtime_shim`` writes an inert ``todo``/``verifies`` module at that project-relative
    path, for projects that won't depend on ``byteplan-runtime``, and registers it in
    ``runtime_modules``.
    """
    return initialize_ops.init_project(start, runtime_shim=runtime_shim)


def _plan_allocations(tags: Sequence[Annotation], registry: Registry, also_used: Iterable[str] = ()) -> list[Proposal]:
    """Assign IDs to untagged tags in scan order (sorted files, then line).

    Reserved IDs, IDs on ``tags`` and ``also_used`` (e.g. IDs elsewhere in source) are never reused.
    """
    return scan_ops.plan_allocations(tags, registry, also_used, allocator=allocate)
