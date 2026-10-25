# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Internal tasks orchestration delegated by Project."""

from __future__ import annotations

import ast
import contextlib
import dataclasses
import json
from typing import TYPE_CHECKING, Any

from byteplan import collisions, gitio, normalize, verification
from byteplan import registry as registry_io
from byteplan.edits import char_col, physical_lines, replace_at
from byteplan.errors import (
    ConfigError,
    EditError,
)
from byteplan.ids import resolve_id
from byteplan.models import HistoryEvent, Presence, Representation, Status
from byteplan.persistence import (
    FileWrite,
    pending_journal,
    sha256,
    staged_dir,
)
from byteplan.reconcile import Observation, reconcile
from byteplan.registry import Registry
from byteplan.scanner import FileScan, ensure_unchanged, scan_file
from byteplan.snapshot import GitSnapshot

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from pathlib import Path

    from byteplan.models import Annotation, Task

from byteplan._api_types import UNSET, RepairResult
from byteplan.operations.common import _not_found, _read_bytes, is_node_id
from byteplan.operations.scan import _apply_discovered_tests

if TYPE_CHECKING:
    from byteplan.api import Project


def list_tasks(
    self: Project,
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


def resolve_task_id(self: Project, query: str, registry: Registry | None = None, *, missing_ok: bool = False) -> str:
    registry = self.load_registry() if registry is None else registry
    identities = registry.tasks.keys() | self.archive_index().tasks.keys()
    task_id = resolve_id(query, identities)
    if task_id is None:
        if missing_ok:
            return query.lower()
        raise _not_found(query)
    return task_id


def get_task(self: Project, task_id: str) -> Task:
    registry = self.load_registry()
    task_id = self._resolve_task_id(task_id, registry)
    task = registry.get(task_id)
    if task is None:
        archived = self.archived_task(task_id)
        if archived is not None:
            return archived
        raise _not_found(task_id)
    return task


def import_task(self: Project, task_id: str) -> RepairResult:
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
        written = self._commit(self._registry_writes(registry_hash, new_registry))
        return RepairResult(task, tuple(written))


def reassign(self: Project, path: str, line: int, *, against: str | None = None, dry_run: bool = False) -> RepairResult:
    """Reassign a duplicate copy, or preserve/rekey an independent branch collision via ``against``."""
    self._require_working_tree()
    if against is not None:
        return self._reassign_branch(path, line, against, dry_run=dry_run)
    context = contextlib.nullcontext(()) if dry_run else self._writing()
    with context:
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
        registry.require_expanded_ids()
        used = set(registry.reserved_ids) | registry.tasks.keys() | {a.task_id for a in annotations if a.task_id}
        new_id = self._allocate(f"{path}\0{line}\0reassign\0{old_id}", used)

        source, before = sources[path]
        if target.representation is Representation.DECORATOR:
            text, line_no, col = _find_decorator_id(source.text, target, old_id)
            old_text, new_text = text, normalize.literal(new_id)
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

        new_registry, _ = reconcile(registry, [Observation(new_id, moved, new=True)], self.clock(), absence_check=None)
        task = new_registry.tasks[new_id]
        task.history[-1] = dataclasses.replace(
            task.history[-1], note=f"reassigned from duplicate {old_id} by `byteplan repair --reassign`"
        )
        writes = [FileWrite(path, before, edited.encode()), *self._registry_writes(registry_hash, new_registry)]
        written = () if dry_run else tuple(self._commit(writes))
        return RepairResult(task, written, old_id=old_id, planned=tuple(w.path for w in writes), dry_run=dry_run)


def reassign_branch(
    self: Project,
    path: str,
    line: int,
    against: str,
    *,
    dry_run: bool,
    open_snapshot_factory: Callable[[Path, str], Project],
) -> RepairResult:
    """Rekey an independently created task before merging, preserving its full record."""
    if self.snapshot is not None:
        msg = "branch collision repair requires the working tree"
        raise ConfigError(msg)
    guard = contextlib.nullcontext() if dry_run else collisions.index_guard(self.root)
    writing = contextlib.nullcontext(()) if dry_run else self._writing(recover_pending=False)
    with guard, writing, contextlib.ExitStack() as readers:
        collisions.ensure_no_operation(self.root)
        if pending_journal(self.root) or (staged_dir(self.root) / "journal.json").exists():
            msg = "finish the pending BytePlan transaction before branch collision repair"
            raise ConfigError(msg)
        index = readers.enter_context(GitSnapshot(self.root))  # also rejects an unresolved Git merge
        if index.root != self.root:
            msg = "collision repair cannot change project roots"
            raise ConfigError(msg)
        registry_hash, registry = self._read_registry()
        registry.require_expanded_ids()
        self._refuse_while_stripped("repair --against")
        preview = self._scan(None, None, dry_run=True, recovered=())
        collisions.ensure_static(preview.diagnostics)
        planned_registry = next(w.data for w in preview.planned if w.path == self.registry_rel)
        if preview.blocked or preview.proposals or planned_registry != registry_io.dumps(registry).encode():
            msg = "source and registry must be fully reconciled; run `byteplan scan` before collision repair"
            raise ConfigError(msg)
        annotations, sources, hierarchy = self._scan_sources()
        target = next((a for a in annotations if a.path == path and a.line == line and a.task_id), None)
        if target is None or target.task_id is None:
            msg = f"no registered task annotation at {path}:{line}"
            raise ConfigError(msg)
        old_id = target.task_id
        if sum(a.task_id == old_id for a in annotations) != 1 or old_id not in registry.tasks:
            msg = "--against requires one unique registered annotation on the original branch"
            raise ConfigError(msg)
        if old_id in self.archive_index().tasks:
            msg = "restore/reconcile the archived identity before branch collision repair"
            raise ConfigError(msg)
        collisions.ensure_supported_metadata(registry, old_id)
        for node in registry.tasks[old_id].linked_tests():
            if node.split("::", 1)[0] not in sources:
                msg = f"linked test {node} is outside the editable source scope; review its references first"
                raise ConfigError(msg)

        def state(rev: str, *, required: bool = True) -> tuple[Project, Registry, set[str]]:
            project = open_snapshot_factory(self.root, rev)
            readers.callback(project.close)
            if project.root != self.root or project.registry_rel != self.registry_rel:
                msg = f"{rev}: project root/registry path differs; cannot prove a task collision"
                raise ConfigError(msg)
            snapshot = project.snapshot
            assert snapshot is not None  # noqa: S101 - open_snapshot always provides one
            data = snapshot.read(self.registry_rel)
            if data is None and required:
                msg = f"{rev}: no registry for this project"
                raise ConfigError(msg)
            stored = Registry() if data is None else registry_io.loads(data.decode("utf-8"), snapshot.label)
            project.config = dataclasses.replace(project.config, auto_annotate=False)
            report = project.scan(dry_run=True)
            collisions.ensure_static(report.diagnostics)
            evidence_bytes = snapshot.read(verification.STORE)
            evidence_ids = set() if evidence_bytes is None else verification.Evidence.loads(evidence_bytes).tasks.keys()
            identities = (
                evidence_ids
                | stored.reserved_ids
                | stored.tasks.keys()
                | project.archive_index().tasks.keys()
                | {tag.task_id for tag in report.tags if tag.task_id is not None}
                | {value for link in report.links for value in link.task_ids}
            )
            return project, stored, identities

        head_project, head_registry, head_ids = state("HEAD")
        other_project, other_registry, other_ids = state(against)
        assert head_project.snapshot is not None  # noqa: S101
        assert other_project.snapshot is not None  # noqa: S101
        head = head_project.snapshot.commit
        other = other_project.snapshot.commit
        if old_id not in head_registry.tasks or old_id not in other_registry.tasks:
            msg = "both pinned branches must contain the colliding active task; it may already be reassigned"
            raise ConfigError(msg)
        head_task = head_registry.tasks[old_id]
        if registry.tasks[old_id].history[: len(head_task.history)] != head_task.history:
            msg = "working task history differs from its pinned branch; restore/reconcile the original lineage before repair"
            raise ConfigError(msg)
        if collisions.creation_binding(head_task) == collisions.creation_binding(other_registry.tasks[old_id]):
            msg = "branches share creation provenance; preserve the canonical task identity instead of reassigning"
            raise ConfigError(msg)
        if old_id in other_project.archive_index().tasks:
            msg = "the other branch also archives this identity; reconcile its state before repair"
            raise ConfigError(msg)
        if registry_io.task_to_dict(head_registry.tasks[old_id]) == registry_io.task_to_dict(
            other_registry.tasks[old_id]
        ):
            msg = "the pinned branches contain an identical record; no independent collision was demonstrated"
            raise ConfigError(msg)
        try:
            bases = gitio.git(["merge-base", "--all", head, other], self.root).split()
        except ConfigError as exc:
            msg = "branches have no common history; cannot prove independent task creation"
            raise ConfigError(msg) from exc
        if not bases:
            msg = "branches have no merge base; cannot prove independent task creation"
            raise ConfigError(msg)
        used = registry.reserved_ids | registry.tasks.keys() | head_ids | other_ids | self.archive_index().tasks.keys()
        for base in bases:
            _, _, base_ids = state(base, required=False)
            if old_id in base_ids:
                msg = f"task {old_id} already existed in merge base {base}; preserve its identity"
                raise ConfigError(msg)
            used |= base_ids
        used |= {tag.task_id for tag in annotations if tag.task_id is not None}
        used |= {value for link in preview.links for value in link.task_ids}
        evidence_before = _read_bytes(self.root / verification.STORE)
        if evidence_before is not None:
            used |= verification.Evidence.loads(evidence_before).tasks.keys()
        new_id = self._allocate(f"{path}\0{line}\0branch-collision\0{old_id}\0{head}\0{other}", used)
        writes: list[FileWrite] = []
        final_scans: dict[str, FileScan] = {}
        for rel, (source, before) in sources.items():
            scan = scan_file(
                source,
                self.config.detect,
                self.config.annotations.runtime_modules,
                hierarchy,
                pytest_marker=self.config.tests.pytest_marker,
            )
            edited, final_scans[rel] = collisions.rewrite_source(
                source,
                scan,
                target if rel == path else None,
                old_id,
                new_id,
                self.config.detect,
                self.config.annotations.runtime_modules,
                hierarchy,
                pytest_marker=self.config.tests.pytest_marker,
            )
            if edited.text != source.text:
                writes.append(FileWrite(rel, before, edited.encode()))
        task = registry.tasks.pop(old_id)
        task.id = new_id
        registry.tasks[new_id] = task
        registry.reserved_ids.add(new_id)  # old identity remains permanently reserved
        task.history.append(
            HistoryEvent(
                "identity_reassigned",
                self.clock(),
                old=old_id,
                new={"id": new_id, "head": head, "against": other, "merge_bases": bases},
                note="explicit pre-merge collision repair; preserved evidence requires fresh verification",
            )
        )
        observed = [tag for scan in final_scans.values() for tag in scan.tags]
        updated, _ = reconcile(
            registry,
            [Observation(tag.task_id, tag, new=False) for tag in observed if tag.task_id],
            self.clock(),
            absence_check=None,
        )
        links = [link for scan in final_scans.values() for link in scan.links]
        _apply_discovered_tests(updated, observed, links, preview.scope)
        if evidence_before is not None:
            evidence_data = json.loads(evidence_before)
            if old_id in evidence_data.get("tasks", {}):
                evidence_data["tasks"][new_id] = evidence_data["tasks"].pop(old_id)
                # Retain provenance/results and the OLD fingerprint; source edits make it stale.
                encoded = (json.dumps(evidence_data, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
                writes.append(FileWrite(verification.STORE, sha256(evidence_before), encoded))
        writes.extend(self._registry_writes(registry_hash, updated))
        collisions.ensure_no_operation(self.root)
        current_head = gitio.git(["rev-parse", "--verify", "HEAD"], self.root).strip()
        if current_head != head:
            msg = "HEAD changed during collision planning; nothing was written, retry on the original branch"
            raise ConfigError(msg)
        written = () if dry_run else tuple(self._commit(writes))
        return RepairResult(
            updated.tasks[new_id], written, old_id=old_id, planned=tuple(w.path for w in writes), dry_run=dry_run
        )


def mutate(self: Project, task_id: str, change: Callable[[Task, str], list[HistoryEvent]]) -> tuple[Task, bool]:
    with self._writing():
        registry_hash, registry = self._read_registry()
        task = registry.get(self._resolve_task_id(task_id, registry))
        if task is None:
            raise _not_found(task_id)
        events = change(task, self.clock())
        if events:
            task.history.extend(events)
            self._commit(self._registry_writes(registry_hash, registry))
        return task, bool(events)


def link_tests(self: Project, task_id: str, nodes: Sequence[str]) -> tuple[Task, bool]:
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


def unlink_tests(self: Project, task_id: str, nodes: Sequence[str]) -> tuple[Task, bool]:
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


def set_status(self: Project, task_id: str, status: Status, note: str | None = None) -> tuple[Task, bool]:
    """Change lifecycle status. Returns the task and whether anything changed."""

    def change(task: Task, now: str) -> list[HistoryEvent]:
        if task.status is status:
            return []
        event = "resolved" if status is Status.RESOLVED else "status_changed"
        old, task.status = task.status, status
        return [HistoryEvent(event, now, old=str(old), new=str(status), note=note)]

    return self._mutate(task_id, change)


def edit_task(
    self: Project,
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
        return [HistoryEvent("edited", now, old={k: before[k] for k in changed}, new={k: after[k] for k in changed})]

    return self._mutate(task_id, change)


def _managed(task: Task) -> dict[str, Any]:
    return {
        "priority": task.priority,
        "assignee": task.assignee,
        "title_override": task.title_override,
        "labels": list(task.labels),
        "notes": task.notes,
    }


def _find_decorator_id(text: str, annotation: Annotation, task_id: str) -> tuple[str, int, int]:
    """The ID value's source span, independent of whitespace and literal spelling."""
    lines = physical_lines(text)
    for call in ast.walk(ast.parse(text)):
        if not isinstance(call, ast.Call) or (call.lineno, call.end_lineno) != (annotation.line, annotation.end_line):
            continue
        for keyword in call.keywords:
            value = keyword.value
            if keyword.arg == "id" and isinstance(value, ast.Constant) and value.value == task_id:
                segment = ast.get_source_segment(text, value)
                if segment is not None:
                    return segment, value.lineno, char_col(lines[value.lineno - 1], value.col_offset)
    msg = f"{annotation.location}: can't find id={task_id!r} in the decorator; edit it by hand"
    raise EditError(msg)
