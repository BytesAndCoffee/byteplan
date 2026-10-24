# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Internal sync orchestration delegated by Project."""

from __future__ import annotations

import contextlib
import dataclasses
from collections import Counter, defaultdict
from typing import TYPE_CHECKING

from byteplan import cleanup as cleanup_lib
from byteplan import normalize, release
from byteplan.config import (
    PYPROJECT,
    parse_pyproject_text,
    read_pyproject,
)
from byteplan.diagnostics import Code, Diagnostic, Severity
from byteplan.errors import (
    EditError,
)
from byteplan.files import ScopeMatcher, collect_files, scope_from_paths
from byteplan.languages import Language, language_for
from byteplan.models import HistoryEvent, Origin
from byteplan.persistence import (
    FileWrite,
)
from byteplan.reconcile import Observation, reconcile
from byteplan.scanner import ensure_unchanged, scan_file
from byteplan.scanner.symbols import SymbolIndex, declarations, parse_module

if TYPE_CHECKING:
    from collections.abc import Sequence

    from byteplan.models import Annotation
    from byteplan.normalize import Rewrite

from byteplan._api_types import CleanupReport, SyncReport
from byteplan.operations.common import _development_dependencies, _not_found, _requirement_name, normalize_review

if TYPE_CHECKING:
    from byteplan.api import Project


def cleanup(
    self: Project, only: Sequence[str] | None = None, *, dry_run: bool = True, suppress_stubs: bool = False
) -> CleanupReport:
    """Remove the source annotations of resolved and dismissed tasks (only ``only``, if given).

    Open tasks are never touched. Each edit must keep Python's AST equal apart from
    BytePlan's own decorators and imports, and every edited file must re-scan to its old
    tasks minus the removed ones. The registry keeps the ID, the last source reference and
    the history, and logs ``cleaned`` (or ``suppressed``).
    """
    self._require_working_tree()
    if not dry_run:
        self._refuse_while_stripped("sync --remove-resolved")
    context = contextlib.nullcontext(()) if dry_run else self._writing()
    with context:
        preview = self._scan(None, None, dry_run=True, recovered=())
        if preview.blocked:
            return CleanupReport((), (), preview.diagnostics, dry_run, blocked="duplicate IDs; fix them first")
        registry_hash, registry = self._read_registry()
        wanted = None if only is None else {self._resolve_task_id(task_id, registry) for task_id in only}
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
        consumers = release.project_consumers(
            {path: source.text for path, (source, _) in sources.items() if language_for(path) is Language.PYTHON}
        )
        for path, remove in sorted(targets.items()):
            source, before = sources[path]
            imported = release.consumers_of(consumers, release.module_name(path))
            plan = cleanup_lib.plan_file(
                source,
                remove,
                runtime_modules=runtime_modules,
                suppress_stubs=suppress_stubs,
                consumers=frozenset(name for name, users in imported.items() if users - {path}),
            )
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
            expected = Counter(_cleanup_identity(t) for t in annotations if t.path == path and t.task_id not in gone)
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
            tag for path in sorted(sources) for tag in rescanned.get(path, [a for a in annotations if a.path == path])
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
        written = () if dry_run else tuple(self._commit(writes))
        return CleanupReport(
            tuple(removed),
            tuple(suppressed),
            tuple(diagnostics),
            dry_run,
            written=written,
            imports_removed=tuple(imports),
        )


def runtime_module(self: Project, *, development: bool = False) -> str | None:
    """The module to import ``todo``/``verifies`` from: ``byteplan_runtime`` when
    ``byteplan-runtime`` is a declared dependency, else a configured shim module present in
    scope, else None. ``development`` also counts dev dependencies (optional dependencies,
    dependency groups, Hatch environments), which is enough for test code."""
    modules = self.config.annotations.runtime_modules
    pyproject = (
        read_pyproject(self.root)
        if self.snapshot is None
        else parse_pyproject_text(
            (self.snapshot.read(PYPROJECT) or b"").decode("utf-8"), f"{self.snapshot.label}:{PYPROJECT}"
        )
    )
    dependencies = list(pyproject.get("project", {}).get("dependencies", []))
    if development:
        dependencies += _development_dependencies(pyproject)
    names = {_requirement_name(dep) for dep in dependencies if isinstance(dep, str)}
    if "byteplan-runtime" in names and "byteplan_runtime" in modules:
        return "byteplan_runtime"
    files = set(
        collect_files(self.config).files
        if self.snapshot is None
        else scope_from_paths(self.config, list(self.snapshot.files()), self.snapshot)[0].files
    )
    for module in modules:
        if module == "byteplan_runtime":
            continue
        stem = module.replace(".", "/")
        for prefix in ("", "src/"):
            if f"{prefix}{stem}.py" in files or f"{prefix}{stem}/__init__.py" in files:
                return module
    return None


def sync(self: Project, only: Sequence[str] | None = None, *, dry_run: bool = True) -> SyncReport:
    """Rewrite attached comments and unowned stubs to ``@todo(...)`` (decorator mode).

    Nothing happens unless ``[tool.byteplan.annotations] mode = "decorator"`` and at least
    one of ``convert_attached_comments`` / ``auto_decorate_stubs`` is on. The tree must be
    scanned first (no untagged annotations, no duplicate IDs).
    """
    self._require_working_tree()
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
        only_ids = (
            None
            if only is None
            else frozenset(self._resolve_task_id(task_id, registry, missing_ok=True) for task_id in only)
        )
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
                for p in self._plan_allocations(stubs, registry, also_used=in_source)
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
        written = () if dry_run else tuple(self._commit(writes))
        return SyncReport(
            tuple(rewrites), tuple(diagnostics), dry_run=dry_run, written=written, imports_added=tuple(imports)
        )


def _cleanup_identity(tag: Annotation) -> tuple[object, ...]:
    return (tag.task_id, tag.kind, tag.title, tag.description, tag.representation)
