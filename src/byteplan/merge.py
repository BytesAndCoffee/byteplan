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
* ``tests``: ``managed`` links merge as a set; ``discovered`` links are a
  discovered field (ours kept, rescan flagged if both sides changed them).
* Unknown top-level keys (from a newer BytePlan) merge three-way and
  structurally: objects key by key, lists that both sides only appended to as
  the base plus both sides' additions, anything else changed differently on
  both sides is a conflict.

Anything that can't be merged this way is reported and left to a normal text
merge with conflict markers. Nothing is ever chosen silently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from byteplan.registry import SCHEMA_VERSION

_DISCOVERED = frozenset({"kind", "title", "description", "presence", "origin", "scope_state", "source", "stub"})
_SET_LIKE = frozenset({"labels"})
_TOP_LEVEL_KEYS = frozenset({"schema_version", "reserved_ids", "tasks"})
# Discovery can rebuild only these fields. Unknown siblings retain managed merge semantics.
_DISCOVERED_MAPPING_KEYS = {
    "source": frozenset({"path", "line", "symbol", "decl_line", "attachment_kind", "representation"}),
    "stub": frozenset({"symbol", "implemented"}),
}


@dataclass
class MergeResult:
    data: dict[str, Any] | None  # None when there are conflicts
    conflicts: list[str] = field(default_factory=list)
    rescan_needed: list[str] = field(default_factory=list)


def _same(a: Any, b: Any) -> bool:
    """JSON equality: like ``==`` but a boolean never equals a number (``true`` vs ``1``),
    and the absent marker equals only itself."""
    if a is b:
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, _Absent) or isinstance(b, _Absent):
        return False
    return bool(a == b)


def _merge_history(
    task_id: str, base: list[Any], ours: list[Any], theirs: list[Any], conflicts: list[str]
) -> list[Any]:
    if not _same(ours[: len(base)], base) or not _same(theirs[: len(base)], base):
        conflicts.append(f"task {task_id}: history was rewritten (not only appended) on one side")
        return ours
    added: list[Any] = []
    for event in [*ours[len(base) :], *theirs[len(base) :]]:
        if not any(_same(event, seen) for seen in added):
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
        if key == "tests":
            value = _merge_tests(task_id, b, o, t, result)
        elif key in _DISCOVERED_MAPPING_KEYS:
            value = _merge_discovered_mapping(task_id, key, b, o, t, result)
        elif key == "history":
            value = _merge_history(task_id, _list(b), _list(o), _list(t), result.conflicts)
        elif key in _SET_LIKE:
            value = _merge_set(_list(b), _list(o), _list(t))
        elif key in {"first_seen", "last_seen"}:
            present = [v for v in (o, t) if v is not _ABSENT and v is not None]
            earliest_or_latest = min if key == "first_seen" else max
            fallback = o if o is not _ABSENT else t
            value = earliest_or_latest(present) if present else fallback
        elif _same(t, o) or _same(t, b):
            value = o
        elif _same(o, b):
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


def _merge_value(where: str, base: Any, ours: Any, theirs: Any, conflicts: list[str]) -> Any:
    """Generic three-way merge of a JSON value. Returns ``_ABSENT`` for a deleted key."""
    if _same(theirs, ours) or _same(theirs, base):
        return ours
    if _same(ours, base):
        return theirs
    if isinstance(ours, dict) and isinstance(theirs, dict) and isinstance(base, dict | _Absent):
        old_map: dict[str, Any] = base if isinstance(base, dict) else {}
        merged = {}
        for key in sorted({*old_map, *ours, *theirs}):
            value = _merge_value(
                f"{where}.{key}", old_map.get(key, _ABSENT), ours.get(key, _ABSENT), theirs.get(key, _ABSENT), conflicts
            )
            if value is not _ABSENT:
                merged[key] = value
        return merged
    if isinstance(ours, list) and isinstance(theirs, list) and isinstance(base, list | _Absent):
        old_list: list[Any] = base if isinstance(base, list) else []
        if _same(ours[: len(old_list)], old_list) and _same(theirs[: len(old_list)], old_list):  # only appended
            added: list[Any] = []
            for item in [*ours[len(old_list) :], *theirs[len(old_list) :]]:
                if not any(_same(item, seen) for seen in added):
                    added.append(item)
            return [*old_list, *added]
    conflicts.append(f"{where} changed on both sides ({ours!r} vs {theirs!r})")
    return ours


def _merge_discovered_mapping(task_id: str, key: str, base: Any, ours: Any, theirs: Any, result: MergeResult) -> Any:
    """Refreshable source/stub details must never choose unknown metadata arbitrarily."""
    known = _DISCOVERED_MAPPING_KEYS[key]
    b, o, t = (
        {name: value for name, value in mapping.items() if name in known} if isinstance(mapping, dict) else mapping
        for mapping in (base, ours, theirs)
    )
    if _same(t, o) or _same(t, b):
        chosen = o
    elif _same(o, b):
        chosen = t
    else:
        chosen = o
        if task_id not in result.rescan_needed:
            result.rescan_needed.append(task_id)
    extensions = [
        {name: value for name, value in mapping.items() if name not in known} if isinstance(mapping, dict) else _ABSENT
        for mapping in (base, ours, theirs)
    ]
    extra = _merge_value(f"task {task_id}: {key}", extensions[0], extensions[1], extensions[2], result.conflicts)
    if isinstance(chosen, dict):
        return {
            **{name: value for name, value in chosen.items() if name in known},
            **({} if extra is _ABSENT else extra),
        }
    if extra is not _ABSENT and extra:
        result.conflicts.append(
            f"task {task_id}: {key} was removed while its metadata changed; reconcile it explicitly"
        )
    return chosen


def _merge_tests(task_id: str, base: Any, ours: Any, theirs: Any, result: MergeResult) -> Any:
    """``managed`` links merge as a set; ``discovered`` ones are rescanned from merged source."""
    parts = [{} if v is _ABSENT or v is None else v for v in (base, ours, theirs)]
    managed = _merge_set(*(_list(p.get("managed")) for p in parts))
    b, o, t = (_list(p.get("discovered")) for p in parts)
    if _same(t, o) or _same(t, b):
        discovered = o
    elif _same(o, b):
        discovered = t
    else:
        discovered = o
        if task_id not in result.rescan_needed:
            result.rescan_needed.append(task_id)
    extensions = [{key: value for key, value in part.items() if key not in {"managed", "discovered"}} for part in parts]
    extra = _merge_value(f"task {task_id}: tests", extensions[0], extensions[1], extensions[2], result.conflicts)
    if not managed and not discovered and not extra:
        return _ABSENT
    return {**extra, "managed": managed, "discovered": discovered}


def _list(value: Any) -> list[Any]:
    return [] if value is _ABSENT or value is None else list(value)


def merge_registries(base: dict[str, Any], ours: dict[str, Any], theirs: dict[str, Any]) -> MergeResult:
    """Merge three registry dicts (as produced by ``registry.to_dict``)."""
    result = MergeResult(data=None)
    versions = {base.get("schema_version"), ours.get("schema_version"), theirs.get("schema_version")}
    # A migration only raises schema_version, so a branch forked before it (a v1 merge base) still
    # merges; the result takes the newest version. Unknown or future versions remain conflicts.
    if any(type(v) is not int or not 1 <= v <= SCHEMA_VERSION for v in versions):
        result.conflicts.append(f"unsupported schema_version in merge ({sorted(map(str, versions))})")
        return result
    version = max(v for v in versions if isinstance(v, int))

    reserved = sorted({*base.get("reserved_ids", []), *ours.get("reserved_ids", []), *theirs.get("reserved_ids", [])})
    base_tasks, our_tasks, their_tasks = base.get("tasks", {}), ours.get("tasks", {}), theirs.get("tasks", {})
    tasks: dict[str, Any] = {}
    for task_id in sorted({*base_tasks, *our_tasks, *their_tasks}):
        b, o, t = base_tasks.get(task_id), our_tasks.get(task_id), their_tasks.get(task_id)
        if o is not None and t is not None:
            if b is None and not _same(o, t):
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
            elif not _same(kept, b):
                result.conflicts.append(f"task {task_id} was removed on one side and changed on the other")
                tasks[task_id] = kept
            # else: removed on one side, untouched on the other -> stays removed
        # Removed on both sides: stays removed. The ID remains reserved either way.

    extra: dict[str, Any] = {}
    for key in sorted({*base, *ours, *theirs} - _TOP_LEVEL_KEYS):
        value = _merge_value(
            key, base.get(key, _ABSENT), ours.get(key, _ABSENT), theirs.get(key, _ABSENT), result.conflicts
        )
        if value is not _ABSENT:
            extra[key] = value

    if not result.conflicts:
        result.data = {**extra, "schema_version": version, "reserved_ids": reserved, "tasks": tasks}
    return result
