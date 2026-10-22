# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Three-way merge of registries, used as a Git merge driver.

IDs are never reused, so registries from two branches combine by task ID:

* ``reserved_ids``: the union of all three versions.
* A task added on one side is kept. The same ID added on both sides is kept
  if identical, and is otherwise a conflict (two branches allocated the same
  ID for different work).
* ``history`` is append-only: the base events, then each side's new events,
  ordered by time (then event name) and de-duplicated.
* ``labels`` merge as a set (additions and removals from both sides).
* Other managed fields (status, priority, assignee, notes, title override,
  unknown extra keys) merge three-way per field; both sides changing a field
  to different values is a conflict.
* Discovered fields (title, description, kind, source, presence, ...) are
  recomputed by the next scan from the merged source. If both sides changed
  one differently, ours is kept and the result is flagged as needing a scan.
  ``first_seen`` takes the earlier value and ``last_seen`` the later.

Anything that can't be merged this way is reported and left to a normal text
merge with conflict markers. Nothing is ever chosen silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from byteplan.registry import SCHEMA_VERSION

_DISCOVERED = frozenset({"kind", "title", "description", "presence", "origin", "scope_state", "source", "stub"})
_SET_LIKE = frozenset({"labels"})


@dataclass
class MergeResult:
    data: dict[str, Any] | None  # None when there are conflicts
    conflicts: list[str] = field(default_factory=list)
    rescan_needed: list[str] = field(default_factory=list)


def _merge_history(
    task_id: str, base: list[Any], ours: list[Any], theirs: list[Any], conflicts: list[str]
) -> list[Any]:
    if ours[: len(base)] != base or theirs[: len(base)] != base:
        conflicts.append(f"task {task_id}: history was rewritten (not only appended) on one side")
        return ours
    added: list[Any] = []
    for event in [*ours[len(base) :], *theirs[len(base) :]]:
        if event not in added:
            added.append(event)
    added.sort(key=lambda event: (str(event.get("at", "")), str(event.get("event", ""))))
    return [*base, *added]


def _merge_set(base: list[Any], ours: list[Any], theirs: list[Any]) -> list[Any]:
    removed = [x for x in base if x not in ours or x not in theirs]
    result: list[Any] = []
    for item in [*base, *ours, *theirs]:
        if item not in removed and item not in result:
            result.append(item)
    return result


class _Absent:
    """A key that isn't present at all, as opposed to one explicitly set to JSON null."""

    def __repr__(self) -> str:
        return "<absent>"


_ABSENT: Any = _Absent()


def _merge_task(
    task_id: str, base: dict[str, Any], ours: dict[str, Any], theirs: dict[str, Any], result: MergeResult
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key in sorted({*base, *ours, *theirs}):
        b, o, t = base.get(key, _ABSENT), ours.get(key, _ABSENT), theirs.get(key, _ABSENT)
        value: Any
        if key == "history":
            value = _merge_history(task_id, _list(b), _list(o), _list(t), result.conflicts)
        elif key in _SET_LIKE:
            value = _merge_set(_list(b), _list(o), _list(t))
        elif key in {"first_seen", "last_seen"}:
            present = [v for v in (o, t) if v is not _ABSENT and v is not None]
            earliest_or_latest = min if key == "first_seen" else max
            fallback = o if o is not _ABSENT else t
            value = earliest_or_latest(present) if present else fallback
        elif t in (o, b):  # `in` compares by identity first, so the absent marker works too
            value = o
        elif o == b:
            value = t
        elif key in _DISCOVERED:
            value = o
            if task_id not in result.rescan_needed:
                result.rescan_needed.append(task_id)
        else:
            result.conflicts.append(f"task {task_id}: {key} changed on both sides ({o!r} vs {t!r})")
            value = o
        if value is not _ABSENT:  # a key deleted on one side (and untouched on the other) stays deleted
            merged[key] = value
    return merged


def _list(value: Any) -> list[Any]:
    return [] if value is _ABSENT or value is None else list(value)


def merge_registries(base: dict[str, Any], ours: dict[str, Any], theirs: dict[str, Any]) -> MergeResult:
    """Merge three registry dicts (as produced by ``registry.to_dict``)."""
    result = MergeResult(data=None)
    versions = {base.get("schema_version"), ours.get("schema_version"), theirs.get("schema_version")}
    if versions != {SCHEMA_VERSION}:
        result.conflicts.append(f"schema_version differs between versions ({sorted(map(str, versions))})")
        return result

    reserved = sorted({*base.get("reserved_ids", []), *ours.get("reserved_ids", []), *theirs.get("reserved_ids", [])})
    base_tasks, our_tasks, their_tasks = base.get("tasks", {}), ours.get("tasks", {}), theirs.get("tasks", {})
    tasks: dict[str, Any] = {}
    for task_id in sorted({*base_tasks, *our_tasks, *their_tasks}):
        b, o, t = base_tasks.get(task_id), our_tasks.get(task_id), their_tasks.get(task_id)
        if o is not None and t is not None:
            if b is None and o != t:
                result.conflicts.append(
                    f"task {task_id} was created on both branches for different work (ID collision)"
                )
                tasks[task_id] = o
            else:
                tasks[task_id] = _merge_task(task_id, b or {}, o, t, result)
        elif o is not None or t is not None:
            kept = o if o is not None else t
            if b is None:
                tasks[task_id] = kept  # added on one side
            elif kept != b:
                result.conflicts.append(f"task {task_id} was removed on one side and changed on the other")
                tasks[task_id] = kept
            # else: removed on one side, untouched on the other -> stays removed
        # Removed on both sides: stays removed. The ID remains reserved either way.

    if not result.conflicts:
        result.data = {"schema_version": SCHEMA_VERSION, "reserved_ids": reserved, "tasks": tasks}
    return result
