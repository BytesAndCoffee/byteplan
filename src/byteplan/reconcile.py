# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Pure reconciliation of scan observations with the registry.

Rules:

* Identity is the task ID. Path, line and symbol are metadata.
* Discovered fields (kind, title, description, source, presence) are refreshed;
  managed fields (status, priority, assignee, labels, notes, title override)
  are never touched.
* Events are appended only for real changes: ``created``, ``moved`` (path or
  symbol changed; line-only shifts are not events), ``text_changed``,
  ``missing``, ``reappeared`` and ``implementation_changed`` (a declaration the
  task owns stopped or started looking like a stub; advisory only). ``last_seen`` is set only when a task seen in
  source gets an event, so an unchanged scan changes nothing.
* Missing detection runs only for complete, un-narrowed scans, and only for
  tasks whose last known path is inside the configured scope. Tasks outside it
  get ``scope_state = "excluded"`` and keep their presence. Status never
  changes here.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from byteplan.models import HistoryEvent, Presence, ScopeState, SourceRef, Task

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from byteplan.models import Annotation
    from byteplan.registry import Registry


@dataclass(frozen=True)
class Observation:
    task_id: str
    tag: Annotation
    new: bool  # True when the ID is being allocated by this scan


@dataclass
class Summary:
    added: list[str] = field(default_factory=list)
    relocated: list[str] = field(default_factory=list)
    text_changed: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    reappeared: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    implementation_changed: list[str] = field(default_factory=list)


def reconcile(
    registry: Registry,
    observations: Sequence[Observation],
    now: str,
    *,
    absence_check: Callable[[str], bool] | None,
) -> tuple[Registry, Summary]:
    """Return an updated copy of ``registry`` and a summary of what changed.

    ``absence_check`` is ``None`` for scans that must not perform missing
    detection (narrowed scans). Otherwise it says whether a path is inside the
    configured scope, i.e. whether a task last seen there would have been found.
    """
    result = copy.deepcopy(registry)
    summary = Summary()
    seen: set[str] = set()

    for obs in observations:
        seen.add(obs.task_id)
        tag = obs.tag
        task = result.tasks.get(obs.task_id)
        source = SourceRef(
            tag.path,
            tag.line,
            tag.symbol,
            tag.decl_line,
            tag.attachment_kind,
            tag.representation,
            extra=task.source.extra if task is not None and task.source is not None else {},
        )
        if task is None:
            if not obs.new:
                continue  # unregistered IDs are diagnosed, never imported implicitly
            result.reserved_ids.add(obs.task_id)
            result.tasks[obs.task_id] = Task(
                id=obs.task_id,
                kind=tag.kind,
                title=tag.title,
                description=tag.description,
                presence=Presence.PRESENT,
                origin=tag.origin,
                source=source,
                stub={"symbol": tag.symbol, "implemented": False} if tag.decl_is_stub else None,
                first_seen=now,
                last_seen=now,
                history=[HistoryEvent("created", now, new={"path": tag.path, "line": tag.line})],
            )
            summary.added.append(obs.task_id)
            continue

        events: list[HistoryEvent] = []
        old_source = task.source
        if old_source is None or (old_source.path, old_source.symbol) != (source.path, source.symbol):
            if old_source is not None:
                events.append(
                    HistoryEvent(
                        "moved",
                        now,
                        old={"path": old_source.path, "symbol": old_source.symbol},
                        new={"path": source.path, "symbol": source.symbol},
                    )
                )
            summary.relocated.append(obs.task_id)
        elif old_source.line != source.line:
            summary.relocated.append(obs.task_id)
        task.source = source

        old_text = {"kind": task.kind, "title": task.title, "description": task.description}
        new_text = {"kind": tag.kind, "title": tag.title, "description": tag.description}
        if old_text != new_text:
            changed = [key for key in old_text if old_text[key] != new_text[key]]
            events.append(
                HistoryEvent(
                    "text_changed",
                    now,
                    old={key: old_text[key] for key in changed},
                    new={key: new_text[key] for key in changed},
                )
            )
            task.kind, task.title, task.description = tag.kind, tag.title, tag.description
            summary.text_changed.append(obs.task_id)

        if tag.decl_is_stub is not None:
            implemented = not tag.decl_is_stub
            if task.stub is None:
                if tag.decl_is_stub:  # first time this task is seen owning a stub
                    task.stub = {"symbol": tag.symbol, "implemented": False}
            elif task.stub.get("implemented") != implemented:
                events.append(
                    HistoryEvent(
                        "implementation_changed",
                        now,
                        old={"implemented": task.stub.get("implemented")},
                        new={"implemented": implemented},
                    )
                )
                task.stub = {**task.stub, "symbol": tag.symbol, "implemented": implemented}
                summary.implementation_changed.append(obs.task_id)

        if task.presence is Presence.MISSING:
            events.append(HistoryEvent("reappeared", now, old=str(Presence.MISSING), new=str(Presence.PRESENT)))
            summary.reappeared.append(obs.task_id)
        task.presence = Presence.PRESENT
        task.scope_state = ScopeState.IN_SCOPE
        if task.first_seen is None:
            task.first_seen = now
        if events:
            task.history.extend(events)
            task.last_seen = now

    if absence_check is not None:
        for task_id, task in sorted(result.tasks.items()):
            if task_id in seen or task.source is None or task.presence is Presence.STRIPPED:
                continue  # a stripped task is away for a release, on record: never missing
            if not absence_check(task.source.path):
                if task.scope_state is not ScopeState.EXCLUDED:
                    task.scope_state = ScopeState.EXCLUDED
                    summary.excluded.append(task_id)
                continue
            task.scope_state = ScopeState.IN_SCOPE
            if task.presence is not Presence.MISSING:
                task.history.append(HistoryEvent("missing", now, old=str(task.presence), new=str(Presence.MISSING)))
                task.presence = Presence.MISSING
                summary.missing.append(task_id)

    return result, summary
