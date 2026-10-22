# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Programmatic surface shared by the CLI, the Hatch hook, and the MCP server."""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import hashlib
import json
import os
import platform
import re
import sys
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pathspec

from byteplan import cleanup, gitio, normalize, release, reporting, scaffold, verification
from byteplan import registry as registry_io
from byteplan.annotate import annotate
from byteplan.config import (
    DEFAULT_REGISTRY,
    PYPROJECT,
    AnnotationsConfig,
    Config,
    config_from_text,
    find_project_root,
    load_config,
    parse_pyproject_text,
    read_pyproject,
)
from byteplan.diagnostics import Code, Diagnostic, Location, Severity, exit_code
from byteplan.edits import physical_lines, replace_at
from byteplan.errors import ConfigError, EditError, RegistryError, ScanError, SourceError, TaskNotFoundError
from byteplan.files import Scope, ScopeMatcher, collect_files, resolve_targets, scope_from_paths
from byteplan.ids import allocate
from byteplan.languages import Language, language_for
from byteplan.models import AttachmentKind, HistoryEvent, Origin, Presence, Representation, ScopeState, Status
from byteplan.persistence import (
    STATE_DIR,
    FileWrite,
    atomic_write_bytes,
    commit,
    pending_journal,
    project_lock,
    recover,
    sha256,
    staged_dir,
)
from byteplan.reconcile import Observation, Summary, reconcile
from byteplan.registry import Registry, load_registry
from byteplan.scanner import FileScan, ensure_unchanged, scan_file
from byteplan.scanner.hierarchy import ClassHierarchy, classes_in
from byteplan.scanner.source import decode_source, read_source
from byteplan.scanner.symbols import SymbolIndex, declarations, parse_module
from byteplan.snapshot import GitSnapshot

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence

    from byteplan.models import Annotation, Task
    from byteplan.normalize import Rewrite
    from byteplan.scanner.decorators import VerifiesLink
    from byteplan.scanner.source import SourceFile

BYTEPLAN_GITIGNORE = "txn/\nscan.lock\n"


class _Unset:  # byteplan: ignore - a sentinel is meant to be empty
    """Sentinel for "leave this field alone" where ``None`` means "clear it"."""


UNSET: Any = _Unset()


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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

    @property
    def files_scanned(self) -> int:
        return len(self.scope.files)

    @property
    def tagged(self) -> tuple[Annotation, ...]:
        return tuple(tag for tag in self.tags if tag.task_id is not None)

    @property
    def annotated_files(self) -> tuple[str, ...]:
        return tuple(sorted({p.tag.path for p in self.proposals}))


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

    def _registry_writes(self, registry_hash: str | None, registry: Registry) -> list[FileWrite]:
        """The registry write, preceded by the report file's when one is configured."""
        writes = []
        if self.report_rel is not None:
            current = self._current_report()
            data = self.render_report(registry)
            if current is not None and current.replace(b"\r\n", b"\n") == data:
                data = current  # only the line endings differ (e.g. core.autocrlf): leave it
            writes.append(FileWrite(self.report_rel, None if current is None else sha256(current), data))
        writes.append(FileWrite(self.registry_rel, registry_hash, registry_io.dumps(registry).encode()))
        return writes

    def _read_registry(self) -> tuple[str, Registry]:
        """The registry plus the hash of the exact bytes it was parsed from."""
        path = self.config.registry_path
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

    @contextlib.contextmanager
    def _writing(self) -> Iterator[tuple[str, ...]]:
        """Hold the project lock and finish any interrupted write first."""
        if (staged_dir(self.root) / "journal.json").exists():
            msg = (
                "an interrupted staged reconciliation is pending; run `byteplan scan --staged --apply` "
                "to finish or undo it first"
            )
            raise ConfigError(msg)
        with project_lock(self.root):
            yield tuple(recover(self.root))

    def exit_code(self, diagnostics: Iterable[Diagnostic]) -> int:
        return exit_code(diagnostics, self.config.check, enforce_consistency=self.enforce_consistency)

    # Scanning -----------------------------------------------------------------

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
        context = contextlib.nullcontext(()) if dry_run else self._writing()
        with context as recovered:
            return self._scan(targets, cwd, dry_run=dry_run, recovered=recovered)

    def _scan(
        self,
        targets: Sequence[str | Path] | None,
        cwd: Path | None,
        *,
        dry_run: bool,
        recovered: tuple[str, ...],
    ) -> ScanReport:
        snapshot = self.snapshot
        if snapshot is not None and not dry_run:
            msg = f"scans of the {snapshot.label} are read-only; use --dry-run (staged --apply isn't implemented)"
            raise ConfigError(msg)
        registry_absent = False
        if snapshot is None:
            registry_hash, registry = self._read_registry()
            rel_targets = None if targets is None else resolve_targets(self.root, targets, cwd)
            scope = collect_files(self.config, rel_targets)
            matcher: ScopeMatcher | None = None
        else:
            data = snapshot.read(self.registry_rel)
            registry_absent = data is None
            registry_hash = "" if data is None else sha256(data)
            label = f"{snapshot.label}:{self.registry_rel}"
            registry = Registry() if data is None else registry_io.loads(data.decode("utf-8", "replace"), label)
            rel_targets = None if targets is None else _snapshot_targets(self.root, targets, cwd)
            scope, matcher = scope_from_paths(self.config, list(snapshot.files()), snapshot, rel_targets)

        runtime_modules = self.config.annotations.runtime_modules
        sources: dict[str, tuple[SourceFile, str]] = {}
        scans: dict[str, FileScan] = {}
        tags: list[Annotation] = []
        links: list[VerifiesLink] = []
        diagnostics: list[Diagnostic] = []
        failures: list[SourceError] = []
        loaded: dict[str, SourceFile] = {}
        for path in scope.files:
            try:
                loaded[path] = self._read(path)
            except SourceError as exc:
                failures.append(exc)  # reported together with parse failures below
        hierarchy = self._hierarchy(loaded, narrowed=scope.narrowed)
        for path, source in loaded.items():
            try:
                result = scan_file(
                    source,
                    self.config.detect,
                    runtime_modules,
                    hierarchy,
                    pytest_marker=self.config.tests.pytest_marker,
                )
            except SourceError as exc:
                failures.append(exc)
                continue
            sources[path] = (source, sha256(source.encode()))
            scans[path] = result
            tags.extend(result.tags)
            links.extend(result.links)
            diagnostics.extend(result.diagnostics)
        if failures:
            raise ScanError(failures)

        if dry_run and snapshot is None and pending_journal(self.root):
            diagnostics.append(
                Diagnostic(
                    Code.PENDING_JOURNAL,
                    Severity.WARNING,
                    "an earlier write was interrupted; files may be partly updated",
                    hint="run `byteplan scan` (without --dry-run) to complete it",
                )
            )
        # FIXME[90c6]: Don't propose stub tasks for declarations whose @todo is stripped for a release
        #   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4352850135
        #   A stripped stub looks unowned, so a writing scan added a duplicate task and comment.
        stripped_block = self.stripped_release(registry)
        if stripped_block is not None:
            on_record = {
                (path, entry["qualname"])
                for path, record in stripped_block.get("files", {}).items()
                for entry in record.get("decorators", [])
                if entry["kind"] == "todo"
            }
            tags = [
                t
                for t in tags
                if not (t.origin is Origin.STUB and t.task_id is None and (t.path, t.symbol) in on_record)
            ]
        if self.config.annotations.mode != "comment":
            tags, stub_notes = _stubs_reported_only(tags, self.config.annotations)
            diagnostics.extend(stub_notes)
        diagnostics.extend(_id_diagnostics(tags, registry))
        duplicated = {d.task_id for d in diagnostics if d.code is Code.DUPLICATE_ID}
        proposals = _plan_allocations(tags, registry) if self.config.auto_annotate else []

        # Write IDs first (in memory), then observe the edited files: registry
        # positions must describe the source as it will be, or the next scan
        # would see every inserted line as a relocation.
        writes: list[FileWrite] = []
        by_file: defaultdict[str, list[Proposal]] = defaultdict(list)
        for proposal in proposals:
            by_file[proposal.tag.path].append(proposal)
        for path, file_proposals in sorted(by_file.items()):
            source, before = sources[path]
            edited, scans[path] = annotate(
                source,
                file_proposals,
                self.config.detect,
                runtime_modules,
                hierarchy,
                pytest_marker=self.config.tests.pytest_marker,
            )
            writes.append(FileWrite(path, before, edited.encode()))
        # A new task's origin is what it was discovered as (e.g. a stub), not what
        # the edited file shows (the comment BytePlan just wrote for it).
        new_origins = {p.task_id: p.tag.origin for p in proposals}
        observed = [tag for path in scope.files for tag in scans[path].tags]
        observations = [
            Observation(
                tag.task_id,
                dataclasses.replace(tag, origin=new_origins[tag.task_id]) if tag.task_id in new_origins else tag,
                new=tag.task_id in new_origins,
            )
            for tag in observed
            if tag.task_id is not None and tag.task_id not in duplicated
        ]
        absence_check = None if scope.narrowed else (matcher or ScopeMatcher(self.config)).contains
        new_registry, summary = reconcile(registry, observations, self.clock(), absence_check=absence_check)
        scope_matcher = matcher or ScopeMatcher(self.config)
        # Links from the final (annotated) scans: inserted lines move the decorators below them.
        links = [link for path in scope.files for link in scans[path].links]
        stripped = self.stripped_release(registry)
        if stripped is None:
            _apply_discovered_tests(new_registry, observed, links, scope)
        else:  # the @todo(tests=)/@verifies links are on record, not in source: keep them as they were
            diagnostics.append(
                Diagnostic(
                    Code.RELEASE_STRIPPED,
                    Severity.INFO,
                    f"the tree is stripped for release {stripped.get('version')}: "
                    f"{sum(1 for t in new_registry.tasks.values() if t.presence is Presence.STRIPPED)} task(s) on record",
                    hint="`byteplan restore` puts the decorators back",
                )
            )
        diagnostics.extend(self._test_link_diagnostics(new_registry, observed, scope_matcher))
        diagnostics.extend(self._missing_diagnostics(new_registry))
        diagnostics.extend(_link_diagnostics(links, new_registry))
        implementation = _implementation_diagnostics(summary, new_registry)
        if self.snapshot is None and implementation:
            implementation = self._complete_candidates(implementation, new_registry)
        diagnostics.extend(implementation)
        diagnostics.extend(
            Diagnostic(
                Code.RESOLVED_BUT_STUBBED,
                Severity.INFO,
                f"task {tag.task_id} is {new_registry.tasks[tag.task_id].status} but {tag.symbol} still looks unfinished",
                task_id=tag.task_id,
                locations=(Location(tag.path, tag.decl_line or tag.line),),
                hint="implement it, or `byteplan sync --remove-resolved --suppress-stubs` if it's an intentional no-op",
            )
            for tag in observed
            if tag.decl_is_stub
            and tag.task_id in new_registry.tasks
            and new_registry.tasks[tag.task_id].status.is_closed
        )
        # Consistency describes a read-only view ("is this already reconciled?"). After a
        # successful writing scan the state *is* reconciled, so it doesn't apply.
        if self.enforce_consistency and dry_run:
            diagnostics.extend(
                self._consistency(registry, new_registry, proposals, diagnostics, registry_absent=registry_absent)
            )
        writes.extend(self._registry_writes(registry_hash, new_registry))

        blocked = bool(duplicated)
        written: list[str] = []
        if not dry_run and not blocked:
            written = commit(self.root, writes)
        return ScanReport(
            scope=scope,
            tags=tuple(tags),
            proposals=tuple(proposals),
            diagnostics=tuple(diagnostics),
            summary=summary,
            tracked=len(new_registry.tasks),
            dry_run=dry_run,
            blocked=blocked,
            written=tuple(written),
            recovered=recovered,
            planned=tuple(writes),
        )

    def _read(self, path: str) -> SourceFile:
        if self.snapshot is None:
            return read_source(self.root, path)
        return decode_source(path, self.snapshot.read(path) or b"")

    def _hierarchy(self, loaded: dict[str, SourceFile], *, narrowed: bool) -> ClassHierarchy | None:
        """The class index over the *whole* scope, even for a narrowed scan: whether a base
        class's method is an interface depends on subclasses that may live elsewhere."""
        if not self.config.detect.respect_overrides:
            return None
        sources = dict(loaded)
        if narrowed:
            if self.snapshot is None:
                everything = collect_files(self.config).files
            else:
                everything = scope_from_paths(self.config, list(self.snapshot.files()), self.snapshot)[0].files
            for path in everything:
                if path not in sources:
                    with contextlib.suppress(SourceError):  # out of the narrowed scan: best effort
                        sources[path] = self._read(path)
        classes = []
        for path, source in sources.items():
            if language_for(path) is not Language.PYTHON:
                continue
            with contextlib.suppress(SourceError):  # unparseable files are reported by the scan itself
                classes.extend(classes_in(parse_module(source)))
        return ClassHierarchy(classes)

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
        snapshot = self.snapshot
        staged = snapshot is not None and snapshot.kind == "index"
        where = "staged" if staged else ("committed" if snapshot is not None else "on disk")
        fix = (
            f"run `byteplan scan`, review, then `git add` the changed source and {self.registry_rel}"
            if staged
            else f"run `byteplan scan` and commit the updated {self.registry_rel}"
        )
        found: list[Diagnostic] = list(self._notices)
        worktree_registry = _read_bytes(self.config.registry_path) if snapshot is not None else None

        if registry_absent:
            found.append(
                Diagnostic(
                    Code.REGISTRY_NOT_STAGED,
                    Severity.ERROR,
                    f"{self.registry_rel} is not {where}",
                    locations=(Location(self.registry_rel),),
                    hint=f"`git add {self.registry_rel}`" if staged else f"commit {self.registry_rel}",
                )
            )
            return found

        for proposal in proposals:
            tag = proposal.tag
            found.append(
                Diagnostic(
                    Code.NEW_UNREGISTERED,
                    Severity.ERROR,
                    f"{tag.kind}: {tag.title}" if tag.title else f"untagged {tag.kind}",
                    locations=(Location(tag.path, tag.line),),
                    hint=fix,
                )
            )

        if worktree_registry is not None and staged:
            unregistered = [d.task_id for d in diagnostics if d.code is Code.UNREGISTERED_ID and d.task_id]
            in_worktree = registry_io.loads(worktree_registry.decode("utf-8", "replace")).tasks if unregistered else {}
            found.extend(
                Diagnostic(
                    Code.REGISTRY_NOT_STAGED,
                    Severity.ERROR,
                    f"task {task_id} is registered in the working tree but not in the staged registry",
                    task_id=task_id,
                    locations=(Location(self.registry_rel),),
                    hint=f"`git add {self.registry_rel}`",
                )
                for task_id in unregistered
                if task_id in in_worktree
            )

        out_of_sync = {"moved", "text_changed", "reappeared", "implementation_changed"}
        for task_id, task in sorted(new.tasks.items()):
            before = old.tasks.get(task_id)
            if before is None:
                continue  # created by this scan: reported as new_unregistered
            events = [e.event for e in task.history[len(before.history) :]]
            closed_and_gone = task.status.is_closed and events == ["missing"]
            relevant = [e for e in events if e in out_of_sync or (e == "missing" and not task.status.is_closed)]
            if _link_keys(before) != _link_keys(task):  # line-only moves are position drift
                relevant.append("test links")
            location = (Location(task.source.path, task.source.line),) if task.source else ()
            if relevant:
                found.append(
                    Diagnostic(
                        Code.REGISTRY_OUT_OF_SYNC,
                        Severity.ERROR,
                        f"task {task_id}: the {where} registry doesn't reflect the {where} code "
                        f"({', '.join(relevant)})",
                        task_id=task_id,
                        locations=location,
                        hint=fix,
                    )
                )
            elif not closed_and_gone and registry_io.task_to_dict(before) != registry_io.task_to_dict(task):
                found.append(
                    Diagnostic(
                        Code.POSITION_DRIFT,
                        Severity.INFO,
                        f"task {task_id}: only line positions differ from the {where} registry",
                        task_id=task_id,
                        locations=location,
                        hint="harmless; the next `byteplan scan` updates them",
                    )
                )

        if self.report_rel is not None:
            current = self._current_report()
            if current is None or current.replace(b"\r\n", b"\n") != self.render_report(old):
                state = "missing" if current is None else "out of date"
                found.append(
                    Diagnostic(
                        Code.REPORT_OUT_OF_SYNC,
                        Severity.WARNING,
                        f"{self.report_rel} is {state}: it doesn't match the {where} registry",
                        locations=(Location(self.report_rel),),
                        hint="run `byteplan scan` to regenerate it"
                        + (f", then `git add {self.report_rel}`" if staged else ""),
                    )
                )

        if staged and snapshot is not None and worktree_registry not in {None, snapshot.read(self.registry_rel)}:
            found.append(
                Diagnostic(
                    Code.WORKING_TREE_CHANGED_BUT_NOT_STAGED,
                    Severity.INFO,
                    f"{self.registry_rel} in the working tree differs from the staged copy",
                    locations=(Location(self.registry_rel),),
                    hint=f"if those changes belong in this commit, `git add {self.registry_rel}`",
                )
            )
        return found

    def _test_link_diagnostics(
        self, registry: Registry, observed: Sequence[Annotation], matcher: ScopeMatcher
    ) -> list[Diagnostic]:
        """``malformed_test_id`` for bad node IDs in source; ``test_not_in_scope`` for linked tests
        whose file isn't scanned (so their @verifies and freshness can't be seen)."""
        found = [
            _malformed_test(node, tag.task_id, Location(tag.path, tag.line))
            for tag in observed
            for node in tag.tests
            if not is_node_id(node)
        ]
        # Snapshot file lists are project-relative, like node ID paths.
        files = set(self.snapshot.files()) if self.snapshot is not None else None
        for task_id, task in sorted(registry.tasks.items()):
            if task.status.is_closed:
                continue
            for node, provenances in task.linked_tests().items():
                if not is_node_id(node) or not set(provenances) & {"managed", "decorator"}:
                    continue
                path = node.split("::", 1)[0]
                exists = (self.root / path).is_file() if files is None else path in files
                if exists and matcher.contains(path):
                    continue
                found.append(
                    Diagnostic(
                        Code.TEST_NOT_IN_SCOPE,
                        Severity.WARNING,
                        f"task {task_id} links {node}, but {path} "
                        + ("doesn't exist" if not exists else "isn't in the scan scope"),
                        task_id=task_id,
                        locations=(Location(task.source.path, task.source.line),) if task.source else (),
                        hint="fix the node ID, or add the test files to [tool.byteplan] include",
                    )
                )
        open_links = {
            node: task_id
            for task_id, task in sorted(registry.tasks.items())
            if not task.status.is_closed
            for node in task.linked_tests()
        }
        found.extend(
            Diagnostic(
                Code.SCAFFOLD_PLACEHOLDER,
                Severity.INFO,
                f"{node} is still a scaffold placeholder for task {open_links[node]} (it fails on purpose)",
                task_id=open_links[node],
                locations=(Location(node.split("::", 1)[0]),),
                hint="write the real test; replacing the pytest.fail(...) body is all it takes",
            )
            for node in sorted(self._placeholders(open_links) & open_links.keys())
        )
        return found

    def _complete_candidates(self, found: list[Diagnostic], registry: Registry) -> list[Diagnostic]:
        """``implementation_changed`` becomes ``implementation_complete_candidate`` when the task's
        linked tests are fresh and passing. Advisory only: nothing is resolved."""
        evidence = verification.Evidence.load(self.root)
        upgraded = []
        for diagnostic in found:
            task = registry.tasks.get(diagnostic.task_id or "")
            if task is not None and self.readiness(task, evidence).state == "ready_for_review":
                upgraded.append(
                    dataclasses.replace(
                        diagnostic,
                        code=Code.IMPLEMENTATION_COMPLETE_CANDIDATE,
                        message=f"{diagnostic.message}, and its linked tests pass",
                        hint=f"review it, then `byteplan resolve {task.id}` (BytePlan never resolves tasks itself)",
                    )
                )
            else:
                upgraded.append(diagnostic)
        return upgraded

    def _missing_diagnostics(self, registry: Registry) -> list[Diagnostic]:
        if self.config.missing_policy == "ignore":
            return []
        found = []
        for task_id, task in sorted(registry.tasks.items()):
            # Resolved or dismissed tasks whose annotation is gone are simply finished.
            if (
                task.presence is not Presence.MISSING
                or task.scope_state is ScopeState.EXCLUDED
                or task.status.is_closed
            ):
                continue
            where = f" (previously line {task.source.line})" if task.source else ""
            found.append(
                Diagnostic(
                    Code.MISSING,
                    Severity.WARNING,
                    f"task {task_id} is no longer in source{where}; its status is still {task.status}",
                    task_id=task_id,
                    locations=(Location(task.source.path),) if task.source else (),
                    hint=f"if the work is done, run `byteplan resolve {task_id}`; "
                    "if the annotation was removed by mistake, restore it",
                )
            )
        return found

    # Queries -------------------------------------------------------------------

    def list_tasks(
        self,
        statuses: Iterable[Status] | None = None,
        presences: Iterable[Presence] | None = None,
        kinds: Iterable[str] | None = None,
    ) -> list[Task]:
        status_set = set(statuses or ())
        presence_set = set(presences or ())
        kind_set = {kind.upper() for kind in kinds or ()}
        return [
            task
            for _, task in sorted(self.load_registry().tasks.items())
            if (not status_set or task.status in status_set)
            and (not presence_set or task.presence in presence_set)
            and (not kind_set or task.kind.upper() in kind_set)
        ]

    def get_task(self, task_id: str) -> Task:
        task = self.load_registry().get(task_id.lower())
        if task is None:
            raise _not_found(task_id)
        return task

    # Checks and reports --------------------------------------------------------------

    def check(self) -> ScanReport:
        """A read-only scan; ``exit_code(report.diagnostics)`` applies the check policy."""
        return self.scan(dry_run=True)

    def report(self) -> dict[str, Any]:
        """Registry summary plus current diagnostics, for text/JSON/Markdown output."""
        diagnostics = self.check().diagnostics
        tasks = [task for _, task in sorted(self.load_registry().tasks.items())]

        def count(values: Iterable[str]) -> dict[str, int]:
            return dict(sorted(Counter(values).items()))

        return {
            "summary": {
                "total": len(tasks),
                "by_status": count(str(t.status) for t in tasks),
                "by_presence": count(str(t.presence) for t in tasks),
                "by_kind": count(t.kind for t in tasks),
                "by_priority": count(t.priority for t in tasks),
            },
            "tasks": [registry_io.task_to_dict(t) for t in tasks],
            "diagnostics": [d.to_dict() for d in diagnostics],
        }

    # Acceptance tests (`byteplan verify`) --------------------------------------------------

    def runner(self) -> list[str]:
        return list(self.config.tests.runner) or [sys.executable, "-m", "pytest"]

    def readiness(self, task: Task, evidence: verification.Evidence | None = None) -> verification.Readiness:
        """Derived, never stored: ``unverified``, ``failing``, ``needs_review`` or ``ready_for_review``."""
        evidence = evidence if evidence is not None else verification.Evidence.load(self.root)
        head = verification.git_state(self.root) if self.config.tests.stale_on == "head" else (None, False)
        return verification.readiness(
            task,
            evidence,
            self.root,
            stale_on=self.config.tests.stale_on,
            head=head,
            placeholders=self._placeholders(task.linked_tests()),
        )

    def _placeholders(self, nodes: Iterable[str]) -> frozenset[str]:
        """Which of these node IDs are still scaffold placeholders (read statically from the
        working tree, or from the snapshot)."""
        found: set[str] = set()
        for path in sorted({node.split("::", 1)[0] for node in nodes}):
            data = self.snapshot.read(path) if self.snapshot is not None else _read_bytes(self.root / path)
            if data is not None:
                found |= scaffold.placeholder_nodes(path, data.decode("utf-8", "replace"))
        return frozenset(found)

    def verify(self, task_ids: Sequence[str] | None = None) -> VerifyReport:
        """Run the linked tests of ``task_ids`` (default: every open task with links) and record
        the evidence in ``.byteplan/verification.json``. Never changes a task's status."""
        registry = self.load_registry()
        if task_ids:
            tasks = [self.get_task(task_id) for task_id in task_ids]
        else:
            tasks = [t for _, t in sorted(registry.tasks.items()) if not t.status.is_closed and t.linked_tests()]
        tasks = [t for t in tasks if t.linked_tests()]
        argv = (*self.runner(), "-p", verification.PLUGIN_MODULE)
        if not tasks:
            return VerifyReport((), argv, 0)
        fingerprints = {t.id: verification.fingerprint(self.root, verification.task_files(t)) for t in tasks}
        head, dirty = verification.git_state(self.root)
        nodes = list(dict.fromkeys(node for t in tasks for node in t.linked_tests()))
        started = self.clock()
        run = verification.run_tests(self.root, nodes, self.runner(), self.config.tests.timeout)

        run_id = hashlib.sha256(f"{started}\0{' '.join(argv)}".encode()).hexdigest()[:12]
        with self._writing():  # brief: the tests ran without holding the project lock
            evidence = verification.Evidence.load(self.root)
            evidence.runs[run_id] = {
                "argv": list(argv),
                "python": platform.python_version(),
                "at": started,
                "head": head,
                "dirty": dirty,
                "timed_out": run.timed_out,
            }
            for task in tasks:
                evidence.tasks[task.id] = {
                    "fingerprint": fingerprints[task.id],
                    "run": run_id,
                    "tests": {node: run.results[node].to_dict() for node in task.linked_tests()},
                }
            evidence.save(self.root)
        verified = tuple(
            TaskVerification(
                task, self.readiness(task, evidence), {node: run.results[node] for node in task.linked_tests()}
            )
            for task in tasks
        )
        return VerifyReport(verified, argv, run.returncode, run.timed_out, run.output)

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
        if not dry_run:
            self._refuse_while_stripped("tests scaffold")
        settings = self.config.tests.scaffold
        policy = policy or settings.policy
        link_style = link_style or settings.link_style
        context = contextlib.nullcontext(()) if dry_run else self._writing()
        with context:
            registry_hash, registry = self._read_registry()
            task = registry.get(task_id.lower())
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
                return ScaffoldResult(task, plan.node, target_rel, plan.created, dry_run=True, text=plan.text)

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
            written = tuple(commit(self.root, writes))
            return ScaffoldResult(task, plan.node, target_rel, plan.created, text=plan.text, written=written)

    def _scaffold_path(self, task: Task, override: str | None, scope: Scope) -> str:
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

    def _scaffold_target(self, task: Task) -> scaffold.Target:
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
                    isinstance(node, ast.AsyncFunctionDef) and node.lineno == source.decl_line
                    for node in ast.walk(tree)
                )
        return scaffold.Target(source.attachment_kind, source.symbol, is_async)

    def ready(self) -> list[tuple[Task, verification.Readiness]]:
        """Open tasks whose evidence makes them ready for a human to review and resolve."""
        evidence = verification.Evidence.load(self.root)
        found = []
        for _, task in sorted(self.load_registry().tasks.items()):
            if task.status.is_closed:
                continue
            state = self.readiness(task, evidence)
            if state.state == "ready_for_review":
                found.append((task, state))
        return found

    # Release stripping (`byteplan release` / `byteplan restore`) ---------------------------

    def stripped_release(self, registry: Registry | None = None) -> dict[str, Any] | None:
        """The registry's ``release`` block while the tree is stripped for a release."""
        block = (registry or self.load_registry()).extra.get("release")
        return block if isinstance(block, dict) and block.get("state") == "stripped" else None

    def _refuse_while_stripped(self, command: str) -> None:
        block = self.stripped_release()
        if block is not None:
            raise release.ReleaseError(
                release.STRIPPED,
                [f"the tree is stripped for release {block.get('version')}; `{command}` would edit stripped source"],
                "run `byteplan restore` first (or switch back to your development branch)",
            )

    def release_version(self, override: str | None) -> str:
        if override:
            return override
        pyproject = read_pyproject(self.root)
        project = pyproject.get("project", {})
        if isinstance(project.get("version"), str):
            return str(project["version"])
        source = pyproject.get("tool", {}).get("hatch", {}).get("version", {}).get("path")
        if "version" in project.get("dynamic", []) and isinstance(source, str):
            text = (_read_bytes(self.root / source) or b"").decode("utf-8", "replace")
            match = re.search(r"""__version__\s*=\s*["']([^"']+)["']""", text)
            if match:
                return match.group(1)
        msg = "can't tell the version; pass --version"
        raise ConfigError(msg)

    def release(self, version: str | None = None, *, dry_run: bool = False, allow_dirty: bool = False) -> ReleaseReport:
        """Strip BytePlan's runtime decorators and imports in place, recording each one.

        Never commits, tags, builds or resets, and never changes a task's status. Refuses (with
        nothing written) on a dirty tree, a pending journal, a blocked scan, an untagged
        ``@todo``, a decorator sharing a line, leftover runtime references, or an
        already-stripped tree.
        """
        version = self.release_version(version)
        # FIXME[205d]: Check for a pending journal before the write context recovers it
        #   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4353030073
        #   _writing() rolls an interrupted write forward first, so release changed files instead of refusing.
        if pending_journal(self.root) or (staged_dir(self.root) / "journal.json").exists():
            raise release.ReleaseError(
                release.NEEDS_REVIEW,
                ["an interrupted write is pending"],
                "finish it deliberately with `byteplan scan` (or `scan --staged --apply`), then release",
            )
        context = contextlib.nullcontext(()) if dry_run else self._writing()
        with context:
            registry_hash, registry = self._read_registry()
            block = self.stripped_release(registry)
            if block is not None:
                raise release.ReleaseError(release.STRIPPED, [f"already stripped for release {block.get('version')}"])
            head, dirty = verification.git_state(self.root)
            if dirty and not allow_dirty:
                raise release.ReleaseError(
                    release.NEEDS_REVIEW,
                    ["the Git tree has uncommitted changes"],
                    "commit or stash them so the strip is the only change, or pass --allow-dirty",
                )
            preview = self._scan(None, None, dry_run=True, recovered=())
            untagged = [p.tag for p in preview.proposals if p.tag.representation is Representation.DECORATOR]
            if preview.blocked or untagged:
                problems = [f"{t.location}: @todo(...) has no id=" for t in untagged] or [
                    "the scan has blocking diagnostics"
                ]
                raise release.ReleaseError(
                    release.UNTAGGED if untagged else release.NEEDS_REVIEW, problems, "run `byteplan scan` first"
                )

            runtime_modules = self.config.annotations.runtime_modules
            files: dict[str, Any] = {}
            writes: list[FileWrite] = []
            stripped_tasks: dict[str, list[dict[str, Any]]] = defaultdict(list)
            python = [p for p in preview.scope.files if language_for(p) is Language.PYTHON]
            sources = {path: read_source(self.root, path) for path in python}
            consumers = release.project_consumers({path: s.text for path, s in sources.items()})
            for path in python:
                source = sources[path]
                imported_here = {
                    name: users - {path}
                    for name, users in release.consumers_of(consumers, release.module_name(path)).items()
                }
                plan = release.strip_file(
                    path, source.text, runtime_modules, {n: u for n, u in imported_here.items() if u}
                )
                if plan is None or (not plan.decorators and not plan.imports):
                    continue
                normalize.ensure_equivalent_without_runtime(
                    path, source.text, plan.text, runtime_modules, everything=True
                )
                problem = release.ensure_compiles(path, plan.text)
                if problem is not None:
                    raise release.ReleaseError(
                        release.NEEDS_REVIEW, [f"{path}: the stripped file wouldn't compile ({problem})"]
                    )
                data = dataclasses.replace(source, text=plan.text).encode()
                files[path] = {"sha256": sha256(data), "decorators": plan.decorators, "imports": plan.imports}
                writes.append(FileWrite(path, sha256(source.encode()), data))
                for entry in plan.decorators:
                    if entry["kind"] == "todo":
                        for task_id in entry["task_ids"]:
                            stripped_tasks[task_id].append(
                                {k: entry[k] for k in ("line", "decl_line", "qualname", "index")} | {"path": path}
                            )

            now = self.clock()
            for task_id, entries in stripped_tasks.items():
                task = registry.tasks.get(task_id)
                if task is None:
                    continue
                task.extra["stripped"] = entries
                task.history.append(HistoryEvent("stripped_for_release", now, old=str(task.presence), new=version))
                task.presence = Presence.STRIPPED
            registry.extra["release"] = {"state": "stripped", "version": version, "stripped_at": now, "files": files}
            writes.extend(self._registry_writes(registry_hash, registry))
            warnings = [self._default_branch_warning()] if head is not None else []
            written = () if dry_run else tuple(commit(self.root, writes))
            return ReleaseReport(
                version,
                tuple(sorted(files)),
                sum(len(f["decorators"]) for f in files.values()),
                sum(len(f["imports"]) for f in files.values()),
                tuple(sorted(stripped_tasks)),
                dry_run,
                tuple(w for w in warnings if w is not None),
                written,
            )

    def _default_branch_warning(self) -> Diagnostic | None:
        try:
            branch = gitio.git(["symbolic-ref", "--quiet", "--short", "HEAD"], self.root).strip()
        except ConfigError:
            return None
        try:
            default = gitio.git(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], self.root).strip()
            default = default.removeprefix("origin/")
        except ConfigError:
            default = ""
        if branch not in {default, "main", "master"} - {""}:
            return None
        return Diagnostic(
            Code.RELEASE_ON_DEFAULT_BRANCH,
            Severity.WARNING,
            f"releasing on {branch}: the strip will sit on your development branch",
            hint="release from a short-lived branch (`git switch -c release/<version>`) and switch back after",
        )

    def restore(self, *, dry_run: bool = False, partial: bool = False) -> RestoreReport:
        """Put every recorded decorator and import back (see ``release``).

        A file that still hashes to its stripped content is restored byte for byte; a changed
        one by AST anchors. Unplaceable entries are ``restore_conflict``: nothing is written,
        unless ``partial``, which restores the rest and keeps those on record.
        """
        context = contextlib.nullcontext(()) if dry_run else self._writing()
        with context:
            registry_hash, registry = self._read_registry()
            block = self.stripped_release(registry)
            if block is None:
                raise release.ReleaseError(release.STRIPPED, ["the tree isn't stripped for a release"])
            runtime_modules = self.config.annotations.runtime_modules
            conflicts: list[str] = []
            writes: list[FileWrite] = []
            remaining: dict[str, Any] = {}
            restored_decorators: list[dict[str, Any]] = []
            restored_imports = 0
            for path, record in sorted(block.get("files", {}).items()):
                current = _read_bytes(self.root / path)
                if current is None:
                    conflicts.append(f"{path} no longer exists")
                    remaining[path] = record
                    continue
                source = decode_source(path, current)
                left: dict[str, Any] = {}
                if sha256(current) == record.get("sha256"):
                    text = release.restore_fast(source.text, record)
                else:
                    text, file_conflicts, left = release.restore_anchored(path, source.text, record)
                    conflicts += file_conflicts
                # FIXME[4d48]: Keep decorators pending when their runtime import can't be restored
                #   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4352659130
                #   Otherwise the equivalence check aborts the whole restore, even with --partial.
                normalize.ensure_equivalent_without_runtime(path, source.text, text, runtime_modules, everything=True)
                problem = release.ensure_compiles(path, text)
                if problem is not None:
                    conflicts.append(f"{path}: the restored file wouldn't compile ({problem})")
                    remaining[path] = record
                    continue
                if left:
                    remaining[path] = {**record, **left}
                placed = [d for d in record.get("decorators", []) if d not in left.get("decorators", [])]
                restored_decorators += placed
                restored_imports += len(record.get("imports", [])) - len(left.get("imports", []))
                writes.append(FileWrite(path, sha256(current), dataclasses.replace(source, text=text).encode()))
            if conflicts and not partial:
                raise release.ReleaseError(release.CONFLICT, conflicts, "fix the code, or `byteplan restore --partial`")

            now = self.clock()
            back = sorted({task_id for d in restored_decorators if d["kind"] == "todo" for task_id in d["task_ids"]})
            still = {
                task_id
                for r in remaining.values()
                for d in r.get("decorators", [])
                if d["kind"] == "todo"
                for task_id in d["task_ids"]
            }
            for task_id in back:
                task = registry.tasks.get(task_id)
                if task is None or task_id in still:
                    continue
                task.extra.pop("stripped", None)
                task.presence = Presence.PRESENT
                task.history.append(HistoryEvent("restored", now, new=block.get("version")))
            if remaining:
                registry.extra["release"] = {**block, "files": remaining}
            else:
                history = list(registry.extra.get("releases", []))
                history.append(
                    {
                        "version": block.get("version"),
                        "stripped_at": block.get("stripped_at"),
                        "restored_at": now,
                        "decorators": sum(len(f.get("decorators", [])) for f in block.get("files", {}).values()),
                        "imports": sum(len(f.get("imports", [])) for f in block.get("files", {}).values()),
                    }
                )
                registry.extra["releases"] = history[-20:]
                registry.extra.pop("release", None)
            writes.extend(self._registry_writes(registry_hash, registry))
            written = () if dry_run else tuple(commit(self.root, writes))
            return RestoreReport(
                tuple(sorted({w.path for w in writes if w.path not in {self.registry_rel, self.report_rel}})),
                len(restored_decorators),
                restored_imports,
                tuple(back),
                tuple(conflicts),
                bool(remaining),
                dry_run,
                written,
            )

    # Cleanup (`byteplan sync --remove-resolved`, `resolve --sync-source`) -----------------

    def cleanup(
        self, only: Sequence[str] | None = None, *, dry_run: bool = True, suppress_stubs: bool = False
    ) -> CleanupReport:
        """Remove the source annotations of resolved and dismissed tasks (only ``only``, if given).

        Open tasks are never touched. Each edit must keep Python's AST equal apart from
        BytePlan's own decorators and imports, and every edited file must re-scan to its old
        tasks minus the removed ones. The registry keeps the ID, the last source reference and
        the history, and logs ``cleaned`` (or ``suppressed``).
        """
        if not dry_run:
            self._refuse_while_stripped("sync --remove-resolved")
        context = contextlib.nullcontext(()) if dry_run else self._writing()
        with context:
            preview = self._scan(None, None, dry_run=True, recovered=())
            if preview.blocked:
                return CleanupReport((), (), preview.diagnostics, dry_run, blocked="duplicate IDs; fix them first")
            registry_hash, registry = self._read_registry()
            wanted = None if only is None else {task_id.lower() for task_id in only}
            diagnostics: list[Diagnostic] = []
            for task_id in sorted(wanted or ()):
                task = registry.get(task_id)
                if task is None:
                    raise _not_found(task_id)
                if not task.status.is_closed:
                    diagnostics.append(
                        Diagnostic(
                            Code.CLEANUP_NEEDS_REVIEW,
                            Severity.WARNING,
                            f"task {task_id} is {task.status}; only resolved or dismissed tasks are cleaned up",
                            task_id=task_id,
                            hint=f"`byteplan resolve {task_id}` first",
                        )
                    )
            annotations, sources, hierarchy = self._scan_sources()
            closed = {task_id for task_id, task in registry.tasks.items() if task.status.is_closed}
            targets: defaultdict[str, list[Annotation]] = defaultdict(list)
            for tag in annotations:
                if tag.task_id in closed and (wanted is None or tag.task_id in wanted):
                    targets[tag.path].append(tag)

            runtime_modules = self.config.annotations.runtime_modules
            removed: list[tuple[str, str]] = []
            suppressed: list[tuple[str, str]] = []
            imports: list[str] = []
            writes: list[FileWrite] = []
            rescanned: dict[str, list[Annotation]] = {}
            for path, remove in sorted(targets.items()):
                source, before = sources[path]
                plan = cleanup.plan_file(source, remove, runtime_modules=runtime_modules, suppress_stubs=suppress_stubs)
                diagnostics.extend(plan.diagnostics)
                if plan.text == source.text:
                    continue
                edited = dataclasses.replace(source, text=plan.text)
                language = language_for(path)
                if language is Language.PYTHON:
                    normalize.ensure_equivalent_without_runtime(path, source.text, edited.text, runtime_modules)
                elif language is Language.JSON:
                    ensure_unchanged(path, source.text, edited.text, self.config.detect.todo_tags)
                after = scan_file(edited, self.config.detect, runtime_modules, hierarchy).tags
                gone = set(plan.removed) | set(plan.suppressed)
                expected = Counter(
                    _cleanup_identity(t) for t in annotations if t.path == path and t.task_id not in gone
                )
                if expected != Counter(_cleanup_identity(t) for t in after):
                    msg = f"{path}: cleanup didn't round-trip through the scanner; nothing was written"
                    raise EditError(msg)
                rescanned[path] = after
                removed += [(task_id, path) for task_id in plan.removed]
                suppressed += [(task_id, path) for task_id in plan.suppressed]
                if plan.imports_removed:
                    imports.append(path)
                writes.append(FileWrite(path, before, edited.encode()))

            if not writes:
                return CleanupReport((), (), tuple(diagnostics), dry_run)
            observed = [
                tag
                for path in sorted(sources)
                for tag in rescanned.get(path, [a for a in annotations if a.path == path])
            ]
            observations = [Observation(tag.task_id, tag, new=False) for tag in observed if tag.task_id is not None]
            new_registry, _ = reconcile(
                registry, observations, self.clock(), absence_check=ScopeMatcher(self.config).contains
            )
            now = self.clock()
            for event, entries in (("cleaned", removed), ("suppressed", suppressed)):
                for task_id, path in entries:
                    new_registry.tasks[task_id].history.append(
                        HistoryEvent(event, now, old={"path": path}, note="annotation removed by byteplan cleanup")
                    )
            writes.extend(self._registry_writes(registry_hash, new_registry))
            written = () if dry_run else tuple(commit(self.root, writes))
            return CleanupReport(
                tuple(removed),
                tuple(suppressed),
                tuple(diagnostics),
                dry_run,
                written=written,
                imports_removed=tuple(imports),
            )

    # Normalization (decorator mode, `byteplan sync`) ---------------------------------------

    def runtime_module(self, *, development: bool = False) -> str | None:
        """The module to import ``todo``/``verifies`` from: ``byteplan_runtime`` when
        ``byteplan-runtime`` is a declared dependency, else a configured shim module present in
        scope, else None. ``development`` also counts dev dependencies (optional dependencies,
        dependency groups, Hatch environments), which is enough for test code."""
        modules = self.config.annotations.runtime_modules
        pyproject = read_pyproject(self.root)
        dependencies = list(pyproject.get("project", {}).get("dependencies", []))
        if development:
            dependencies += _development_dependencies(pyproject)
        names = {_requirement_name(dep) for dep in dependencies if isinstance(dep, str)}
        if "byteplan-runtime" in names and "byteplan_runtime" in modules:
            return "byteplan_runtime"
        files = set(collect_files(self.config).files)
        for module in modules:
            if module == "byteplan_runtime":
                continue
            stem = module.replace(".", "/")
            for prefix in ("", "src/"):
                if f"{prefix}{stem}.py" in files or f"{prefix}{stem}/__init__.py" in files:
                    return module
        return None

    def sync(self, only: Sequence[str] | None = None, *, dry_run: bool = True) -> SyncReport:
        """Rewrite attached comments and unowned stubs to ``@todo(...)`` (decorator mode).

        Nothing happens unless ``[tool.byteplan.annotations] mode = "decorator"`` and at least
        one of ``convert_attached_comments`` / ``auto_decorate_stubs`` is on. The tree must be
        scanned first (no untagged annotations, no duplicate IDs).
        """
        if not dry_run:
            self._refuse_while_stripped("sync")
        settings = self.config.annotations
        if settings.mode != "decorator" or not (settings.convert_attached_comments or settings.auto_decorate_stubs):
            reason = (
                f'annotations mode is "{settings.mode}"; sync only rewrites in "decorator" mode'
                if settings.mode != "decorator"
                else "neither convert_attached_comments nor auto_decorate_stubs is enabled"
            )
            return SyncReport((), (), dry_run=dry_run, blocked=f"nothing to do: {reason}")
        only_ids = None if only is None else frozenset(task_id.lower() for task_id in only)
        context = contextlib.nullcontext(()) if dry_run else self._writing()
        with context:
            preview = self._scan(None, None, dry_run=True, recovered=())
            if preview.blocked or preview.proposals:
                return SyncReport(
                    (),
                    preview.diagnostics,
                    dry_run=dry_run,
                    blocked="the tree isn't fully scanned (untagged annotations or duplicate IDs); run `byteplan scan` first",
                )
            registry_hash, registry = self._read_registry()
            # Classes are unchanged by rewrites (only decorators move), so the index stays valid.
            annotations, sources, hierarchy = self._scan_sources()
            available = self.runtime_module()
            runtime_modules = settings.runtime_modules

            stubs = [a for a in annotations if a.origin is Origin.STUB and a.task_id is None]
            stub_ids: dict[tuple[str, int, int], str] = {}
            if settings.auto_decorate_stubs and only_ids is None:
                # Every ID already in source is taken, registered or not.
                in_source = {a.task_id for a in annotations if a.task_id is not None}
                stub_ids = {
                    (p.tag.path, p.tag.line, p.tag.col): p.task_id
                    for p in _plan_allocations(stubs, registry, also_used=in_source)
                }

            by_file: defaultdict[str, list[Annotation]] = defaultdict(list)
            for annotation in annotations:
                by_file[annotation.path].append(annotation)
            rewrites: list[Rewrite] = []
            diagnostics: list[Diagnostic] = []
            writes: list[FileWrite] = []
            imports: list[str] = []
            rescanned: dict[str, list[Annotation]] = {}
            for path, (source, before) in sorted(sources.items()):
                tags = by_file.get(path, [])
                if language_for(path) is not Language.PYTHON or not tags:
                    continue
                tree = parse_module(source)
                plan = normalize.plan_file(
                    source,
                    tree,
                    tags,
                    SymbolIndex(declarations(tree)),
                    convert=settings.convert_attached_comments,
                    decorate_stubs=settings.auto_decorate_stubs,
                    stub_ids={(line, col): i for (p, line, col), i in stub_ids.items() if p == path},
                    runtime_modules=runtime_modules,
                    available=available,
                    only=only_ids,
                )
                diagnostics.extend(plan.diagnostics)
                if not plan.rewrites:
                    continue
                edited = dataclasses.replace(source, text=plan.text)
                normalize.ensure_equivalent_without_runtime(path, source.text, edited.text, runtime_modules)
                after = scan_file(edited, self.config.detect, runtime_modules, hierarchy).tags
                normalize.ensure_round_trip(path, tags, after, plan)
                rescanned[path] = after
                rewrites.extend(plan.rewrites)
                writes.append(FileWrite(path, before, edited.encode()))
                if plan.import_added:
                    imports.append(path)

            if only_ids is not None:
                missing = sorted(only_ids - {r.task_id for r in rewrites})
                diagnostics.extend(
                    normalize_review(task_id, "was not rewritten (not an attached comment, or not found)")
                    for task_id in missing
                )
            if not rewrites:
                return SyncReport((), tuple(diagnostics), dry_run=dry_run)

            new_stubs = {r.task_id for r in rewrites if r.action == "decorate"}
            observed = [tag for path in sorted(sources) for tag in rescanned.get(path, by_file.get(path, []))]
            observations = [
                Observation(
                    tag.task_id,
                    dataclasses.replace(tag, origin=Origin.STUB) if tag.task_id in new_stubs else tag,
                    new=tag.task_id in new_stubs,
                )
                for tag in observed
                if tag.task_id is not None
            ]
            new_registry, _ = reconcile(
                registry, observations, self.clock(), absence_check=ScopeMatcher(self.config).contains
            )
            writes.extend(self._registry_writes(registry_hash, new_registry))
            written = () if dry_run else tuple(commit(self.root, writes))
            return SyncReport(
                tuple(rewrites), tuple(diagnostics), dry_run=dry_run, written=written, imports_added=tuple(imports)
            )

    # Repair (explicit, never automatic) ------------------------------------------------

    def _scan_sources(
        self,
    ) -> tuple[list[Annotation], dict[str, tuple[SourceFile, str]], ClassHierarchy | None]:
        """Scan the whole scope as a normal scan would, including the class index, so repaired
        registry entries agree with what the next scan or check sees."""
        scope = collect_files(self.config)
        loaded: dict[str, SourceFile] = {}
        failures: list[SourceError] = []
        for path in scope.files:
            try:
                loaded[path] = read_source(self.root, path)
            except SourceError as exc:
                failures.append(exc)
        hierarchy = self._hierarchy(loaded, narrowed=False)
        sources: dict[str, tuple[SourceFile, str]] = {}
        annotations: list[Annotation] = []
        for path, source in loaded.items():
            try:
                annotations.extend(
                    scan_file(source, self.config.detect, self.config.annotations.runtime_modules, hierarchy).tags
                )
            except SourceError as exc:
                failures.append(exc)
                continue
            sources[path] = (source, sha256(source.encode()))
        if failures:
            raise ScanError(failures)
        return annotations, sources, hierarchy

    def import_task(self, task_id: str) -> RepairResult:
        """Register an ID that is in source but not in the registry (``unregistered_id``)."""
        task_id = task_id.lower()
        with self._writing():
            registry_hash, registry = self._read_registry()
            if task_id in registry.tasks:
                msg = f"task {task_id} is already registered"
                raise ConfigError(msg)
            annotations, _, _ = self._scan_sources()
            found = [a for a in annotations if a.task_id == task_id]
            if len(found) != 1:
                where = "is not in source" if not found else f"appears {len(found)} times; reassign the copies first"
                msg = f"cannot import {task_id}: it {where}"
                raise ConfigError(msg)
            new_registry, _ = reconcile(
                registry, [Observation(task_id, found[0], new=True)], self.clock(), absence_check=None
            )
            task = new_registry.tasks[task_id]
            task.history[-1] = dataclasses.replace(task.history[-1], note="imported by `byteplan repair --import`")
            written = commit(self.root, self._registry_writes(registry_hash, new_registry))
            return RepairResult(task, tuple(written))

    def reassign(self, path: str, line: int) -> RepairResult:
        """Give the duplicate-ID annotation at ``path:line`` a fresh ID, in source and registry."""
        with self._writing():
            registry_hash, registry = self._read_registry()
            annotations, sources, hierarchy = self._scan_sources()
            target = next((a for a in annotations if a.path == path and a.line == line and a.task_id), None)
            if target is None or target.task_id is None:
                msg = f"no tagged annotation at {path}:{line}"
                raise ConfigError(msg)
            old_id = target.task_id
            copies = [a for a in annotations if a.task_id == old_id]
            if len(copies) == 1:  # only the annotation itself
                msg = (
                    f"{old_id} at {path}:{line} is not duplicated; reassigning it would orphan its task. "
                    "Only duplicate copies can be reassigned"
                )
                raise ConfigError(msg)
            used = set(registry.reserved_ids) | {a.task_id for a in annotations if a.task_id}
            new_id = allocate(f"{path}\0{line}\0reassign\0{old_id}", used)

            source, before = sources[path]
            if target.representation is Representation.DECORATOR:
                text, line_no, col = _find_decorator_id(source.text, target, old_id)
                old_text, new_text = text, text.replace(old_id, new_id)
            else:
                line_no = target.line
                col = physical_lines(source.text)[line_no - 1].find(f"[{old_id}]", target.col)
                old_text, new_text = f"[{old_id}]", f"[{new_id}]"
            edited = dataclasses.replace(source, text=replace_at(source.text, line_no, col, old_text, new_text))
            ensure_unchanged(path, source.text, edited.text, self.config.detect.todo_tags)
            rescanned = scan_file(edited, self.config.detect, self.config.annotations.runtime_modules, hierarchy).tags
            moved = next((a for a in rescanned if a.line == line and a.task_id == new_id), None)
            if moved is None:
                msg = f"{path}:{line}: reassignment did not round-trip through the scanner; nothing was written"
                raise EditError(msg)

            new_registry, _ = reconcile(
                registry, [Observation(new_id, moved, new=True)], self.clock(), absence_check=None
            )
            task = new_registry.tasks[new_id]
            task.history[-1] = dataclasses.replace(
                task.history[-1], note=f"reassigned from duplicate {old_id} by `byteplan repair --reassign`"
            )
            written = commit(
                self.root,
                [FileWrite(path, before, edited.encode()), *self._registry_writes(registry_hash, new_registry)],
            )
            return RepairResult(task, tuple(written), old_id=old_id)

    # Registry mutations (never touch source) -------------------------------------

    def _mutate(self, task_id: str, change: Callable[[Task, str], list[HistoryEvent]]) -> tuple[Task, bool]:
        with self._writing():
            registry_hash, registry = self._read_registry()
            task = registry.get(task_id.lower())
            if task is None:
                raise _not_found(task_id)
            events = change(task, self.clock())
            if events:
                task.history.extend(events)
                commit(self.root, self._registry_writes(registry_hash, registry))
            return task, bool(events)

    def link_tests(self, task_id: str, nodes: Sequence[str]) -> tuple[Task, bool]:
        """Add managed test links (``byteplan tests add``). Node IDs are validated first."""
        bad = [node for node in nodes if not is_node_id(node)]
        if bad:
            msg = f"not a pytest node ID: {', '.join(bad)} (expected path/to/test_file.py::test_name)"
            raise ConfigError(msg)

        def change(task: Task, now: str) -> list[HistoryEvent]:
            added = [node for node in dict.fromkeys(nodes) if node not in task.tests_managed]
            task.tests_managed = sorted([*task.tests_managed, *added])
            return [HistoryEvent("test_linked", now, new=node) for node in added]

        return self._mutate(task_id, change)

    def unlink_tests(self, task_id: str, nodes: Sequence[str]) -> tuple[Task, bool]:
        """Remove managed test links (``byteplan tests remove``). Links declared in source can
        only be removed there."""
        task = self.get_task(task_id)
        from_source = {entry["node"]: entry for entry in task.tests_discovered}
        stuck = [node for node in nodes if node not in task.tests_managed and node in from_source]
        if stuck:
            where = ", ".join(
                f"{node} ({from_source[node]['provenance']} at {from_source[node]['path']}:{from_source[node]['line']})"
                for node in stuck
            )
            msg = f"declared in source, so remove it there: {where}"
            raise ConfigError(msg)

        def change(task: Task, now: str) -> list[HistoryEvent]:
            removed = [node for node in dict.fromkeys(nodes) if node in task.tests_managed]
            task.tests_managed = [node for node in task.tests_managed if node not in removed]
            return [HistoryEvent("test_unlinked", now, old=node) for node in removed]

        return self._mutate(task_id, change)

    def set_status(self, task_id: str, status: Status, note: str | None = None) -> tuple[Task, bool]:
        """Change lifecycle status. Returns the task and whether anything changed."""

        def change(task: Task, now: str) -> list[HistoryEvent]:
            if task.status is status:
                return []
            event = "resolved" if status is Status.RESOLVED else "status_changed"
            old, task.status = task.status, status
            return [HistoryEvent(event, now, old=str(old), new=str(status), note=note)]

        return self._mutate(task_id, change)

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

        def change(task: Task, now: str) -> list[HistoryEvent]:
            before = _managed(task)
            if priority is not None:
                task.priority = priority
            if assignee is not UNSET:
                task.assignee = assignee
            if title_override is not UNSET:
                task.title_override = title_override
            labels = [label for label in task.labels if label not in remove_labels]
            labels += [label for label in add_labels if label not in labels]
            task.labels = labels
            if notes is not None:
                task.notes = notes
            if append_note:
                task.notes = f"{task.notes}\n\n{append_note}" if task.notes else append_note
            after = _managed(task)
            changed = [key for key in before if before[key] != after[key]]
            if not changed:
                return []
            return [
                HistoryEvent("edited", now, old={k: before[k] for k in changed}, new={k: after[k] for k in changed})
            ]

        return self._mutate(task_id, change)


@dataclass(frozen=True)
class RepairResult:
    task: Task
    written: tuple[str, ...]
    old_id: str | None = None


def _managed(task: Task) -> dict[str, Any]:
    return {
        "priority": task.priority,
        "assignee": task.assignee,
        "title_override": task.title_override,
        "labels": list(task.labels),
        "notes": task.notes,
    }


def _find_decorator_id(text: str, annotation: Annotation, task_id: str) -> tuple[str, int, int]:
    """The exact ``id="..."`` text of a decorator, and where it starts."""
    lines = physical_lines(text)
    for line_no in range(annotation.line, annotation.end_line + 1):
        for quote in ('"', "'"):
            needle = f"id={quote}{task_id}{quote}"
            col = lines[line_no - 1].find(needle)
            if col != -1:
                return needle, line_no, col
    msg = f"{annotation.location}: can't find id={task_id!r} in the decorator; edit it by hand"
    raise EditError(msg)


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _snapshot_targets(root: Path, targets: Sequence[str | Path], cwd: Path | None) -> tuple[str, ...]:
    """Like ``resolve_targets`` but without requiring the paths to exist on disk."""
    base = (cwd or Path.cwd()).resolve()
    resolved = []
    for target in targets:
        path = Path(os.path.abspath(base / target))
        if not path.is_relative_to(root):
            msg = f"{target} is outside the project root {root}"
            raise ConfigError(msg)
        rel = path.relative_to(root).as_posix()
        resolved.append("" if rel == "." else rel)
    return tuple(sorted(set(resolved)))


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


def _not_found(task_id: str) -> TaskNotFoundError:
    return TaskNotFoundError(f"no task with ID {task_id!r}")


def _link_diagnostics(links: Sequence[VerifiesLink], registry: Registry) -> list[Diagnostic]:
    return [
        Diagnostic(
            Code.UNKNOWN_TASK_REFERENCE,
            Severity.WARNING,
            f"{link.node_id} verifies task {task_id}, which is not in the registry",
            task_id=task_id,
            locations=(Location(link.path, link.line),),
            hint="check the ID with `byteplan list`; IDs are never reused, so a typo can't hit another task",
        )
        for link in links
        for task_id in link.task_ids
        if task_id not in registry.tasks
    ]


def _implementation_diagnostics(summary: Summary, registry: Registry) -> list[Diagnostic]:
    found = []
    for task_id in summary.implementation_changed:
        task = registry.tasks[task_id]
        if task.stub is None or not task.stub.get("implemented") or task.status.is_closed:
            continue
        where = (Location(task.source.path, task.source.line),) if task.source else ()
        found.append(
            Diagnostic(
                Code.IMPLEMENTATION_CHANGED,
                Severity.INFO,
                f"{task.stub.get('symbol')} no longer looks like a stub; task {task_id} is still {task.status}",
                task_id=task_id,
                locations=where,
                hint=f"if the work is done, run `byteplan resolve {task_id}` (BytePlan never resolves tasks itself)",
            )
        )
    return found


def _id_diagnostics(tags: Sequence[Annotation], registry: Registry) -> list[Diagnostic]:
    by_id: defaultdict[str, list[Annotation]] = defaultdict(list)
    for tag in tags:
        if tag.task_id is not None:
            by_id[tag.task_id].append(tag)

    diagnostics: list[Diagnostic] = []
    for task_id, occurrences in sorted(by_id.items()):
        locations = tuple(Location(t.path, t.line) for t in occurrences)
        if len(occurrences) > 1:
            diagnostics.append(
                Diagnostic(
                    Code.DUPLICATE_ID,
                    Severity.ERROR,
                    f"ID {task_id} appears on {len(occurrences)} separate annotations",
                    task_id=task_id,
                    locations=locations,
                    hint="keep the ID on the original task and delete the [id] from each copy; copies get new IDs on the next scan",
                )
            )
        task = registry.get(task_id)
        if task is None:
            diagnostics.append(
                Diagnostic(
                    Code.UNREGISTERED_ID,
                    Severity.WARNING,
                    f"ID {task_id} is in source but not in the registry",
                    task_id=task_id,
                    locations=locations,
                    hint="restore the registry entry from version control, or delete the [id] if the comment was copied from another project",
                )
            )
        elif task.status.is_closed:
            diagnostics.append(
                Diagnostic(
                    Code.STALE_ANNOTATION,
                    Severity.WARNING,
                    f"task {task_id} is {task.status} but its annotation is still in source",
                    task_id=task_id,
                    locations=locations,
                    hint="remove the comment from source, or reopen the task",
                )
            )
    return diagnostics


_NODE_ID_RE = re.compile(r"[^:\s][^:]*\.py(?:::[A-Za-z_][A-Za-z0-9_]*)+(?:\[[^\n]*\])?")


def is_node_id(node: str) -> bool:
    """A pytest node ID: ``path/to/test_x.py::name[::name...][param]``."""
    return _NODE_ID_RE.fullmatch(node) is not None


def _malformed_test(node: str, task_id: str | None, location: Location) -> Diagnostic:
    return Diagnostic(
        Code.MALFORMED_TEST_ID,
        Severity.WARNING,
        f"{node!r} is not a pytest node ID (path/to/test_file.py::test_name)",
        task_id=task_id,
        locations=(location,),
        hint="it isn't linked until it's fixed",
    )


def _link_keys(task: Task) -> list[tuple[str, str, str]]:
    """A task's discovered test links without their line numbers."""
    return sorted({(e["node"], e["provenance"], e["path"]) for e in task.tests_discovered})


def _apply_discovered_tests(
    registry: Registry, observed: Sequence[Annotation], links: Sequence[VerifiesLink], scope: Scope
) -> None:
    """Recompute ``tests.discovered`` from source. A narrowed scan only replaces the entries
    from paths it covered."""
    found: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for tag in observed:
        if tag.task_id is None:
            continue
        for node in tag.tests:
            if is_node_id(node):
                found[tag.task_id].append({"node": node, "provenance": "decorator", "path": tag.path, "line": tag.line})
    for link in links:
        for task_id in link.task_ids:
            found[task_id].append(
                {"node": link.node_id, "provenance": link.provenance, "path": link.path, "line": link.line}
            )
    for task_id, task in registry.tasks.items():
        kept = [entry for entry in task.tests_discovered if not scope.covers(entry["path"])]
        entries = kept + found.get(task_id, [])
        unique = {json.dumps(e, sort_keys=True): e for e in entries}
        task.tests_discovered = sorted(
            unique.values(), key=lambda e: (e["node"], e["provenance"], e["path"], e["line"])
        )


def _cleanup_identity(tag: Annotation) -> tuple[object, ...]:
    return (tag.task_id, tag.kind, tag.title, tag.description, tag.representation)


def normalize_review(task_id: str, message: str) -> Diagnostic:
    return Diagnostic(Code.CONVERSION_NEEDS_REVIEW, Severity.INFO, f"task {task_id} {message}", task_id=task_id)


def _development_dependencies(pyproject: dict[str, Any]) -> list[Any]:
    """Requirement strings from optional dependencies, dependency groups and Hatch environments."""
    found: list[Any] = []
    for extra in pyproject.get("project", {}).get("optional-dependencies", {}).values():
        found += list(extra) if isinstance(extra, list) else []
    for group in pyproject.get("dependency-groups", {}).values():
        found += list(group) if isinstance(group, list) else []
    for env in pyproject.get("tool", {}).get("hatch", {}).get("envs", {}).values():
        if isinstance(env, dict):
            for key in ("dependencies", "extra-dependencies"):
                found += list(env.get(key, [])) if isinstance(env.get(key), list) else []
    return found


def _requirement_name(requirement: str) -> str:
    """The normalized project name of a PEP 508 requirement string."""
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    return re.sub(r"[-_.]+", "-", match.group(1)).lower() if match else ""


def _stubs_reported_only(
    tags: Sequence[Annotation], annotations: AnnotationsConfig
) -> tuple[list[Annotation], list[Diagnostic]]:
    """In ``preserve`` and ``decorator`` modes ``scan`` doesn't write stub comments: unowned
    stubs are reported (and, with ``auto_decorate_stubs``, left for ``byteplan sync``)."""
    if annotations.mode == "decorator" and annotations.auto_decorate_stubs:
        hint = "run `byteplan sync --apply` to add @todo(...), or add `# byteplan: ignore` if it's intentional"
    else:
        hint = "add a TODO comment or @todo(...), or `# byteplan: ignore` if it's intentional"
    kept: list[Annotation] = []
    notes: list[Diagnostic] = []
    for tag in tags:
        if tag.origin is Origin.STUB and tag.task_id is None:
            notes.append(
                Diagnostic(
                    Code.STUB_NEEDS_REVIEW,
                    Severity.INFO,
                    f"{tag.symbol} looks unfinished (annotations mode is {annotations.mode!r}, so scan doesn't annotate it)",
                    locations=(Location(tag.path, tag.decl_line or tag.line),),
                    hint=hint,
                )
            )
        else:
            kept.append(tag)
    return kept, notes


def _plan_allocations(tags: Sequence[Annotation], registry: Registry, also_used: Iterable[str] = ()) -> list[Proposal]:
    """Assign IDs to untagged tags in scan order (sorted files, then line).

    Reserved IDs, IDs on ``tags`` and ``also_used`` (e.g. IDs elsewhere in source) are never reused.
    """
    used = set(registry.reserved_ids) | {tag.task_id for tag in tags if tag.task_id is not None} | set(also_used)
    occurrences: Counter[tuple[str, str, str, str]] = Counter()
    proposals: list[Proposal] = []
    for tag in tags:
        if tag.task_id is not None:
            continue
        key = (tag.path, tag.symbol or "", tag.kind.upper(), tag.title)
        seed = "\0".join([*key, str(occurrences[key])])
        occurrences[key] += 1
        task_id = allocate(seed, used)
        used.add(task_id)
        proposals.append(Proposal(tag, task_id))
    return proposals


@dataclass
class InitResult:
    root: Path
    actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


_CONFIG_BLOCK = """\
[tool.byteplan]
registry = ".byteplan/tasks.json"
include = ["**/*.py"]
"""

_SDIST_BLOCK = """\
[tool.hatch.build.targets.sdist]
exclude = [".byteplan"]
"""


RUNTIME_SHIM = '''"""BytePlan task markers, inert at runtime (written by `byteplan init --runtime-shim`).

BytePlan reads @todo/@verifies statically; at runtime they return the object unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_T = TypeVar("_T")


def _identity(obj: _T) -> _T:
    return obj


def todo(
    title: str,
    /,
    *,
    id: str | None = None,  # noqa: A002 - BytePlan's documented keyword
    kind: str = "TODO",
    description: str = "",
    test: str | None = None,
    tests: Sequence[str] = (),
) -> Callable[[_T], _T]:
    del title, id, kind, description, test, tests
    return _identity


def verifies(*ids: str) -> Callable[[_T], _T]:
    del ids
    return _identity
'''


def shim_module_name(rel: str) -> str:
    """The import name of a shim at a project-relative path (``src/`` layouts supported)."""
    stem = rel.removesuffix(".py").removesuffix("/__init__").removeprefix("src/")
    return stem.replace("/", ".")


def _write_shim(root: Path, rel: str, result: InitResult) -> str:
    path = (root / rel).resolve()
    if not path.is_relative_to(root.resolve()) or path.suffix != ".py":
        msg = f"--runtime-shim {rel!r} must be a .py file inside the project"
        raise ConfigError(msg)
    rel = path.relative_to(root.resolve()).as_posix()
    module = shim_module_name(rel)
    if not all(part.isidentifier() for part in module.split(".")):
        msg = f"--runtime-shim {rel!r} isn't importable as a module ({module!r})"
        raise ConfigError(msg)
    if path.exists():
        if path.read_text(encoding="utf-8") != RUNTIME_SHIM:
            msg = f"{rel} already exists; remove it or choose another path for the shim"
            raise ConfigError(msg)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(path, RUNTIME_SHIM.encode())
        result.actions.append(f"wrote runtime shim {rel} (module {module})")
    return module


def init_project(start: Path | None = None, *, runtime_shim: str | None = None) -> InitResult:
    """Create configuration and an empty registry. Safe to run repeatedly.

    ``runtime_shim`` writes an inert ``todo``/``verifies`` module at that project-relative
    path, for projects that won't depend on ``byteplan-runtime``, and registers it in
    ``runtime_modules``.
    """
    root = find_project_root(start or Path.cwd())
    result = InitResult(root)
    pyproject = read_pyproject(root)
    shim = _write_shim(root, runtime_shim, result) if runtime_shim else None

    additions: list[str] = []
    if "byteplan" not in pyproject.get("tool", {}):
        block = _CONFIG_BLOCK
        if shim:
            block += f'\n[tool.byteplan.annotations]\nruntime_modules = ["byteplan_runtime", "{shim}"]\n'
        additions.append(block)
        result.actions.append(f"added [tool.byteplan] to {PYPROJECT}")
    elif shim:
        configured = pyproject["tool"]["byteplan"].get("annotations", {}).get("runtime_modules", ["byteplan_runtime"])
        if shim not in configured:
            result.warnings.append(
                f'add "{shim}" to [tool.byteplan.annotations] runtime_modules in {PYPROJECT} '
                "so BytePlan recognizes the shim's decorators"
            )
    if pyproject.get("build-system", {}).get("build-backend") == "hatchling.build":
        sdist = pyproject.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {}).get("sdist")
        if sdist is None:
            additions.append(_SDIST_BLOCK)
            result.actions.append(f"excluded .byteplan from Hatch sdists in {PYPROJECT}")
        elif _sdist_ships(sdist, pyproject.get("tool", {}).get("byteplan", {}).get("registry", DEFAULT_REGISTRY)):
            result.warnings.append(
                f'add ".byteplan" to [tool.hatch.build.targets.sdist] exclude in {PYPROJECT} '
                "so the registry is not shipped in source distributions"
            )
    if additions:
        _append_to_pyproject(root / PYPROJECT, additions)

    config = load_config(root)
    registry_path = config.registry_path
    if registry_path.exists():
        load_registry(registry_path)  # validate; raises on corruption
    else:
        atomic_write_bytes(registry_path, registry_io.dumps(Registry()).encode())
        result.actions.append(f"created {registry_path.relative_to(root).as_posix()}")
    gitignore = root / STATE_DIR / ".gitignore"
    if not gitignore.exists():
        atomic_write_bytes(gitignore, BYTEPLAN_GITIGNORE.encode())
        result.actions.append(f"created {gitignore.relative_to(root).as_posix()}")
    return result


def _sdist_ships(sdist: dict[str, Any], registry: str) -> bool:
    """Whether a Hatch sdist with this target config would include the registry file.

    Follows Hatch's selection rules: ``only-include`` (paths) restricts to those paths,
    ``include`` (gitignore-style patterns) restricts to matches, and ``exclude`` removes
    matches. The build hook re-checks with Hatchling's own ``include_path`` at build time.
    """
    rel = registry.removeprefix("./")
    only = sdist.get("only-include")
    if only and not any(rel == p.strip("/") or rel.startswith(p.strip("/") + "/") for p in only):
        return False
    include = sdist.get("include")
    if include and not pathspec.PathSpec.from_lines("gitignore", include).match_file(rel):
        return False
    exclude = sdist.get("exclude")
    return not (exclude and pathspec.PathSpec.from_lines("gitignore", exclude).match_file(rel))


def _append_to_pyproject(path: Path, blocks: Sequence[str]) -> None:
    source = decode_source(PYPROJECT, path.read_bytes())
    nl = source.newline
    text = source.text
    if text and not text.endswith(("\n", "\r")):
        text += nl
    for block in blocks:
        text += nl + block.replace("\n", nl)
    try:
        tomllib.loads(text)  # never write a pyproject we can't read back
    except tomllib.TOMLDecodeError as exc:
        msg = f"cannot add BytePlan settings to {PYPROJECT} automatically ({exc}); add them by hand"
        raise ConfigError(msg) from exc
    atomic_write_bytes(path, text.encode(source.encoding))
