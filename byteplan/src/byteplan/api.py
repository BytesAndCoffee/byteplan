# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Programmatic surface shared by the CLI, the Hatch hook, and the MCP server."""

from __future__ import annotations

import tomllib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from byteplan import registry as registry_io
from byteplan.config import PYPROJECT, Config, find_project_root, load_config, read_pyproject
from byteplan.diagnostics import Code, Diagnostic, Location, Severity, exit_code
from byteplan.errors import ConfigError, ScanError, SourceError, TaskNotFoundError
from byteplan.files import Scope, collect_files, resolve_targets
from byteplan.ids import allocate
from byteplan.persistence import atomic_write_bytes
from byteplan.registry import Registry, load_registry
from byteplan.scanner import scan_file
from byteplan.scanner.source import decode_source, read_source

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from byteplan.models import CommentTag, Presence, Status, Task

# Working files (journal, staged writes, lock) always live here, wherever the registry is.
STATE_DIR = ".byteplan"
BYTEPLAN_GITIGNORE = "txn/\nscan.lock\n"


@dataclass(frozen=True)
class Proposal:
    """An untagged discovery and the ID it would be annotated with."""

    tag: CommentTag
    task_id: str


@dataclass(frozen=True)
class ScanReport:
    scope: Scope
    tags: tuple[CommentTag, ...]
    proposals: tuple[Proposal, ...]
    diagnostics: tuple[Diagnostic, ...]

    @property
    def files_scanned(self) -> int:
        return len(self.scope.files)

    @property
    def tagged(self) -> tuple[CommentTag, ...]:
        return tuple(tag for tag in self.tags if tag.task_id is not None)


class Project:
    def __init__(self, config: Config) -> None:
        self.config = config

    @classmethod
    def open(cls, start: Path | None = None) -> Project:
        return cls(load_config(find_project_root(start or Path.cwd())))

    @property
    def root(self) -> Path:
        return self.config.root

    def load_registry(self) -> Registry:
        return load_registry(self.config.registry_path)

    def exit_code(self, diagnostics: Iterable[Diagnostic]) -> int:
        return exit_code(diagnostics, self.config.check)

    def scan(self, targets: Sequence[str | Path] | None = None, cwd: Path | None = None) -> ScanReport:
        """Discover tags and plan ID allocation. Read-only.

        Raises ``ScanError`` if any in-scope file fails to read, decode, or parse.
        """
        registry = self.load_registry()
        rel_targets = None if targets is None else resolve_targets(self.root, targets, cwd)
        scope = collect_files(self.config, rel_targets)

        tags: list[CommentTag] = []
        diagnostics: list[Diagnostic] = []
        failures: list[SourceError] = []
        for path in scope.files:
            try:
                result = scan_file(read_source(self.root, path), self.config.detect)
            except SourceError as exc:
                failures.append(exc)
                continue
            tags.extend(result.tags)
            diagnostics.extend(result.diagnostics)
        if failures:
            raise ScanError(failures)

        diagnostics.extend(_id_diagnostics(tags, registry))
        proposals = _plan_allocations(tags, registry)
        return ScanReport(scope, tuple(tags), tuple(proposals), tuple(diagnostics))

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
            msg = f"no task with ID {task_id!r}"
            raise TaskNotFoundError(msg)
        return task


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
