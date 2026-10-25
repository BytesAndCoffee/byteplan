# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Internal scan orchestration delegated by Project."""

from __future__ import annotations

import contextlib
import dataclasses
import json
import os
import posixpath
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from byteplan import registry as registry_io
from byteplan import verification
from byteplan.annotate import annotate
from byteplan.diagnostics import Code, Diagnostic, Location, Severity
from byteplan.errors import (
    ByteplanError,
    ConfigError,
    ScanError,
    SourceError,
)
from byteplan.files import Scope, ScopeMatcher, collect_files, resolve_targets, scope_from_paths
from byteplan.ids import LEGACY_ID_LENGTH
from byteplan.languages import Language, language_for
from byteplan.models import Origin, Presence, ScopeState, Status
from byteplan.persistence import (
    FileWrite,
    pending_journal,
    sha256,
)
from byteplan.reconcile import Observation, Summary, reconcile
from byteplan.registry import Registry
from byteplan.scanner import FileScan, scan_file
from byteplan.scanner.hierarchy import ClassHierarchy, classes_in
from byteplan.scanner.source import decode_source, read_source
from byteplan.scanner.symbols import parse_module

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterable, Mapping, Sequence

    from byteplan.config import (
        AnnotationsConfig,
    )
    from byteplan.models import Annotation, Task
    from byteplan.scanner.decorators import VerifiesLink
    from byteplan.scanner.source import SourceFile

from byteplan._api_types import Proposal, ScanReport
from byteplan.operations.common import _read_bytes, is_node_id

if TYPE_CHECKING:
    from byteplan.api import Project


def scan(
    self: Project,
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
        report = self._scan(targets, cwd, dry_run=dry_run, recovered=recovered)
    if dry_run or self.snapshot is not None or report.blocked:
        return report
    if self.config.tests.scaffold.auto and report.summary.added:
        report = self._auto_scaffold(report)
    if self.config.archive.auto:
        report = dataclasses.replace(report, archived=self.archive().tasks)
    return report


def auto_scaffold(self: Project, report: ScanReport) -> ScanReport:
    """Scaffold tests for the open tasks ``report`` added in Python files outside the test directory."""
    if self.stripped_release() is not None:
        return report
    tests_dir = PurePosixPath(posixpath.normpath(self.config.tests.scaffold.directory.replace("\\", "/")))
    registry = self.load_registry()
    scaffolded, failures = [], []
    for task_id in report.summary.added:
        task = registry.get(task_id)
        if task is None or task.status is not Status.OPEN or task.linked_tests():
            continue
        if task.source is None or not task.source.path.endswith(".py"):
            continue
        if PurePosixPath(task.source.path).is_relative_to(tests_dir):
            continue
        try:
            result = self.scaffold_test(task_id)
        # e.g. scaffold_needs_path, an undecodable test file, a title its encoding can't hold,
        # or a file where the test directory should be.
        except (ByteplanError, UnicodeError, OSError) as exc:
            failures.append((task_id, str(exc)))
        else:
            scaffolded.append((task_id, result.node))
    return dataclasses.replace(
        report,
        written=tuple(dict.fromkeys([*report.written, *(node.split("::", 1)[0] for _, node in scaffolded)])),
        scaffolded=tuple(scaffolded),
        scaffold_failures=tuple(failures),
    )


def scan_core(
    self: Project,
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

    # Validate the same evidence snapshot as the source/registry, even when no
    # implementation candidate needs readiness. Merged evidence is never optional.
    if snapshot is None:
        verification.Evidence.load(self.root)
    else:
        evidence_data = snapshot.read(verification.STORE)
        if evidence_data is not None:
            verification.Evidence.loads(evidence_data)

    if dry_run and snapshot is None and pending_journal(self.root):
        diagnostics.append(
            Diagnostic(
                Code.PENDING_JOURNAL,
                Severity.WARNING,
                "an earlier write was interrupted; files may be partly updated",
                hint="run `byteplan scan` (without --dry-run) to complete it",
            )
        )
    stripped_block = self.stripped_release(registry)
    if stripped_block is not None:
        on_record = {
            (path, entry["qualname"])
            for path, record in stripped_block.get("files", {}).items()
            for entry in record.get("decorators", [])
            if entry["kind"] == "todo"
        }
        tags = [
            t for t in tags if not (t.origin is Origin.STUB and t.task_id is None and (t.path, t.symbol) in on_record)
        ]
    if self.config.annotations.mode != "comment":
        tags, stub_notes = _stubs_reported_only(tags, self.config.annotations)
        diagnostics.extend(stub_notes)
    diagnostics.extend(_id_diagnostics(tags, registry, self.archive_index().tasks))
    duplicated = {d.task_id for d in diagnostics if d.code is Code.DUPLICATE_ID}
    # FIXME[3d5bb4]: Reserve unregistered embedded IDs outside narrowed targets before allocation.
    proposals = self._plan_allocations(tags, registry) if self.config.auto_annotate else []

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
        if self.snapshot is None:  # release warnings read the working tree (sdist file list)
            diagnostics.extend(self._release_warnings())
    diagnostics.extend(self._test_link_diagnostics(new_registry, observed, scope_matcher))
    diagnostics.extend(self._missing_diagnostics(new_registry))
    diagnostics.extend(_link_diagnostics(links, new_registry, self.archive_index().tasks))
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
        if tag.decl_is_stub and tag.task_id in new_registry.tasks and new_registry.tasks[tag.task_id].status.is_closed
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
        written = self._commit(writes)
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
        links=tuple(links),
        runtime_decorated_files=tuple(path for path, scan in scans.items() if scan.runtime_decorated),
    )


def read_source_view(self: Project, path: str) -> SourceFile:
    if self.snapshot is None:
        return read_source(self.root, path)
    return decode_source(path, self.snapshot.read(path) or b"")


def hierarchy(self: Project, loaded: dict[str, SourceFile], *, narrowed: bool) -> ClassHierarchy | None:
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


def consistency(
    self: Project,
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
                    f"task {task_id}: the {where} registry doesn't reflect the {where} code ({', '.join(relevant)})",
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

    if self.report_rel is not None and self.maintains_report:
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


def test_link_diagnostics(
    self: Project, registry: Registry, observed: Sequence[Annotation], matcher: ScopeMatcher
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


def complete_candidates(self: Project, found: list[Diagnostic], registry: Registry) -> list[Diagnostic]:
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


def missing_diagnostics(self: Project, registry: Registry) -> list[Diagnostic]:
    if self.config.missing_policy == "ignore":
        return []
    found = []
    for task_id, task in sorted(registry.tasks.items()):
        # Resolved or dismissed tasks whose annotation is gone are simply finished.
        if task.presence is not Presence.MISSING or task.scope_state is ScopeState.EXCLUDED or task.status.is_closed:
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


def check(self: Project) -> ScanReport:
    """A read-only scan; ``exit_code(report.diagnostics)`` applies the check policy."""
    return self.scan(dry_run=True)


def report(self: Project) -> dict[str, Any]:
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


def scan_sources(
    self: Project,
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


def _link_diagnostics(
    links: Sequence[VerifiesLink], registry: Registry, archived: Mapping[str, Mapping[str, Any]]
) -> list[Diagnostic]:
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
        if task_id not in registry.tasks and task_id not in archived  # a test kept after archiving is fine
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


def _id_diagnostics(
    tags: Sequence[Annotation], registry: Registry, archived: Mapping[str, Mapping[str, Any]]
) -> list[Diagnostic]:
    by_id: defaultdict[str, list[Annotation]] = defaultdict(list)
    for tag in tags:
        if tag.task_id is not None:
            if len(tag.task_id) != LEGACY_ID_LENGTH:
                registry.require_expanded_ids()
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
        if task is None and task_id in archived:
            diagnostics.append(
                Diagnostic(
                    Code.UNREGISTERED_ID,
                    Severity.WARNING,
                    f"ID {task_id} is in source but archived ({archived[task_id].get('status', 'closed')})",
                    task_id=task_id,
                    locations=locations,
                    hint=f"delete the comment if it came back by mistake (e.g. a revert), or "
                    f"`byteplan archive --restore {task_id}` to bring the task back and reopen it",
                )
            )
        elif task is None:
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


def plan_allocations(
    tags: Sequence[Annotation],
    registry: Registry,
    also_used: Iterable[str] = (),
    *,
    allocator: Callable[[str, Collection[str]], str],
) -> list[Proposal]:
    """Assign IDs to untagged tags in scan order (sorted files, then line).

    Reserved IDs, IDs on ``tags`` and ``also_used`` (e.g. IDs elsewhere in source) are never reused.
    """
    used = (
        set(registry.reserved_ids)
        | registry.tasks.keys()
        | {tag.task_id for tag in tags if tag.task_id is not None}
        | set(also_used)
    )
    occurrences: Counter[tuple[str, str, str, str]] = Counter()
    proposals: list[Proposal] = []
    for tag in tags:
        if tag.task_id is not None:
            continue
        registry.require_expanded_ids()
        key = (tag.path, tag.symbol or "", tag.kind.upper(), tag.title)
        seed = "\0".join([*key, str(occurrences[key])])
        occurrences[key] += 1
        task_id = allocator(seed, used)
        used.add(task_id)
        proposals.append(Proposal(tag, task_id))
    return proposals
