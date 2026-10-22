# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Programmatic surface shared by the CLI, the Hatch hook, and the MCP server."""

from __future__ import annotations

import contextlib
import dataclasses
import os
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from byteplan import registry as registry_io
from byteplan.annotate import annotate
from byteplan.config import (
    PYPROJECT,
    Config,
    config_from_text,
    find_project_root,
    load_config,
    parse_pyproject_text,
    read_pyproject,
)
from byteplan.diagnostics import Code, Diagnostic, Location, Severity, exit_code
from byteplan.edits import ensure_equivalent, physical_lines, replace_at
from byteplan.errors import ConfigError, EditError, RegistryError, ScanError, SourceError, TaskNotFoundError
from byteplan.files import Scope, ScopeMatcher, collect_files, resolve_targets, scope_from_paths
from byteplan.ids import allocate
from byteplan.models import HistoryEvent, Presence, Representation, ScopeState, Status
from byteplan.persistence import (
    STATE_DIR,
    FileWrite,
    atomic_write_bytes,
    commit,
    pending_journal,
    project_lock,
    recover,
    sha256,
)
from byteplan.reconcile import Observation, Summary, reconcile
from byteplan.registry import Registry, load_registry
from byteplan.scanner import FileScan, scan_file
from byteplan.scanner.source import decode_source, read_source
from byteplan.snapshot import GitSnapshot

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence

    from byteplan.models import Annotation, Task
    from byteplan.scanner.decorators import VerifiesLink
    from byteplan.scanner.source import SourceFile

BYTEPLAN_GITIGNORE = "txn/\nscan.lock\n"


class _Unset:
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
        root = find_project_root(start or Path.cwd())
        snapshot = GitSnapshot(root, rev)
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

    def load_registry(self) -> Registry:
        return load_registry(self.config.registry_path)

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
        for path in scope.files:
            try:
                if snapshot is None:
                    source = read_source(self.root, path)
                else:
                    source = decode_source(path, snapshot.read(path) or b"")
                result = scan_file(source, self.config.detect, runtime_modules)
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
            edited, scans[path] = annotate(source, file_proposals, self.config.detect, runtime_modules)
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
        diagnostics.extend(self._missing_diagnostics(new_registry))
        diagnostics.extend(_link_diagnostics(links, new_registry))
        diagnostics.extend(_implementation_diagnostics(summary, new_registry))
        if self.enforce_consistency:
            diagnostics.extend(
                self._consistency(registry, new_registry, proposals, diagnostics, registry_absent=registry_absent)
            )
        writes.append(FileWrite(self.registry_rel, registry_hash, registry_io.dumps(new_registry).encode()))

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
        )

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

    # Repair (explicit, never automatic) ------------------------------------------------

    def _scan_sources(self) -> tuple[list[Annotation], dict[str, tuple[SourceFile, str]]]:
        scope = collect_files(self.config)
        sources: dict[str, tuple[SourceFile, str]] = {}
        annotations: list[Annotation] = []
        failures: list[SourceError] = []
        for path in scope.files:
            try:
                source = read_source(self.root, path)
                annotations.extend(scan_file(source, self.config.detect, self.config.annotations.runtime_modules).tags)
            except SourceError as exc:
                failures.append(exc)
                continue
            sources[path] = (source, sha256(source.encode()))
        if failures:
            raise ScanError(failures)
        return annotations, sources

    def import_task(self, task_id: str) -> RepairResult:
        """Register an ID that is in source but not in the registry (``unregistered_id``)."""
        task_id = task_id.lower()
        with self._writing():
            registry_hash, registry = self._read_registry()
            if task_id in registry.tasks:
                msg = f"task {task_id} is already registered"
                raise ConfigError(msg)
            annotations, _ = self._scan_sources()
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
            written = commit(
                self.root,
                [FileWrite(self.registry_rel, registry_hash, registry_io.dumps(new_registry).encode())],
            )
            return RepairResult(task, tuple(written))

    def reassign(self, path: str, line: int) -> RepairResult:
        """Give the duplicate-ID annotation at ``path:line`` a fresh ID, in source and registry."""
        with self._writing():
            registry_hash, registry = self._read_registry()
            annotations, sources = self._scan_sources()
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
            ensure_equivalent(path, source.text, edited.text)
            rescanned = scan_file(edited, self.config.detect, self.config.annotations.runtime_modules).tags
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
                [
                    FileWrite(path, before, edited.encode()),
                    FileWrite(self.registry_rel, registry_hash, registry_io.dumps(new_registry).encode()),
                ],
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
                data = registry_io.dumps(registry).encode()
                commit(self.root, [FileWrite(self.registry_rel, registry_hash, data)])
            return task, bool(events)

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


def _plan_allocations(tags: Sequence[Annotation], registry: Registry) -> list[Proposal]:
    """Assign IDs to untagged tags in scan order (sorted files, then line)."""
    used = set(registry.reserved_ids) | {tag.task_id for tag in tags if tag.task_id is not None}
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


def init_project(start: Path | None = None) -> InitResult:
    """Create configuration and an empty registry. Safe to run repeatedly."""
    root = find_project_root(start or Path.cwd())
    result = InitResult(root)
    pyproject = read_pyproject(root)

    additions: list[str] = []
    if "byteplan" not in pyproject.get("tool", {}):
        additions.append(_CONFIG_BLOCK)
        result.actions.append(f"added [tool.byteplan] to {PYPROJECT}")
    if pyproject.get("build-system", {}).get("build-backend") == "hatchling.build":
        sdist = pyproject.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {}).get("sdist")
        if sdist is None:
            additions.append(_SDIST_BLOCK)
            result.actions.append(f"excluded .byteplan from Hatch sdists in {PYPROJECT}")
        elif not any(".byteplan" in str(pattern) for pattern in sdist.get("exclude", [])):
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
