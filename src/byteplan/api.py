# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Programmatic surface shared by the CLI, the Hatch hook, and the MCP server."""

from __future__ import annotations

import contextlib
import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from byteplan import registry as registry_io
from byteplan.annotate import annotate
from byteplan.config import PYPROJECT, Config, find_project_root, load_config, read_pyproject
from byteplan.diagnostics import Code, Diagnostic, Location, Severity, exit_code
from byteplan.errors import ConfigError, RegistryError, ScanError, SourceError, TaskNotFoundError
from byteplan.files import Scope, ScopeMatcher, collect_files, resolve_targets
from byteplan.ids import allocate
from byteplan.models import HistoryEvent, Presence, ScopeState, Status
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
from byteplan.scanner import scan_file
from byteplan.scanner.source import decode_source, read_source

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence

    from byteplan.models import CommentTag, Task
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

    tag: CommentTag
    task_id: str


@dataclass(frozen=True)
class ScanReport:
    scope: Scope
    tags: tuple[CommentTag, ...]
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
    def tagged(self) -> tuple[CommentTag, ...]:
        return tuple(tag for tag in self.tags if tag.task_id is not None)

    @property
    def annotated_files(self) -> tuple[str, ...]:
        return tuple(sorted({p.tag.path for p in self.proposals}))


class Project:
    def __init__(self, config: Config, clock: Callable[[], str] = utc_now) -> None:
        self.config = config
        self.clock = clock

    @classmethod
    def open(cls, start: Path | None = None, clock: Callable[[], str] = utc_now) -> Project:
        return cls(load_config(find_project_root(start or Path.cwd())), clock)

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
        return exit_code(diagnostics, self.config.check)

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
        registry_hash, registry = self._read_registry()
        rel_targets = None if targets is None else resolve_targets(self.root, targets, cwd)
        scope = collect_files(self.config, rel_targets)

        sources: dict[str, tuple[SourceFile, str]] = {}
        tags: list[CommentTag] = []
        diagnostics: list[Diagnostic] = []
        failures: list[SourceError] = []
        for path in scope.files:
            try:
                source = read_source(self.root, path)
                result = scan_file(source, self.config.detect)
            except SourceError as exc:
                failures.append(exc)
                continue
            sources[path] = (source, sha256(source.encode()))
            tags.extend(result.tags)
            diagnostics.extend(result.diagnostics)
        if failures:
            raise ScanError(failures)

        if dry_run and pending_journal(self.root):
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

        observations = [
            Observation(tag.task_id, tag, new=False)
            for tag in tags
            if tag.task_id is not None and tag.task_id not in duplicated
        ]
        observations += [Observation(p.task_id, p.tag, new=True) for p in proposals]
        observations.sort(key=lambda obs: (obs.tag.path, obs.tag.line))
        absence_check = None if scope.narrowed else ScopeMatcher(self.config).contains
        new_registry, summary = reconcile(registry, observations, self.clock(), absence_check=absence_check)
        diagnostics.extend(self._missing_diagnostics(new_registry))

        writes: list[FileWrite] = []
        by_file: defaultdict[str, list[Proposal]] = defaultdict(list)
        for proposal in proposals:
            by_file[proposal.tag.path].append(proposal)
        for path, file_proposals in sorted(by_file.items()):
            source, before = sources[path]
            writes.append(FileWrite(path, before, annotate(source, file_proposals, self.config.detect).encode()))
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


def _managed(task: Task) -> dict[str, Any]:
    return {
        "priority": task.priority,
        "assignee": task.assignee,
        "title_override": task.title_override,
        "labels": list(task.labels),
        "notes": task.notes,
    }


def _not_found(task_id: str) -> TaskNotFoundError:
    return TaskNotFoundError(f"no task with ID {task_id!r}")


def _id_diagnostics(tags: Sequence[CommentTag], registry: Registry) -> list[Diagnostic]:
    by_id: defaultdict[str, list[CommentTag]] = defaultdict(list)
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


def _plan_allocations(tags: Sequence[CommentTag], registry: Registry) -> list[Proposal]:
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
