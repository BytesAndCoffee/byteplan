# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Archiving closed tasks: a local-first SQLite store plus a committed reconciliation index.

Tasks closed (resolved or dismissed) a while ago leave ``tasks.json`` so the registry, its
diffs and its merges stay small. Their IDs stay in ``reserved_ids`` forever.

* **``.byteplan/archive.sqlite``** (local, gitignored) holds each archived task's full record
  and its verification evidence as zlib-compressed JSON.
* **``.byteplan/archive.json``** (committed) is the reconciliation artifact: per task, when it
  was closed and archived, its title, and the sha256 of its canonical record. It's small,
  deterministic, and merges by task ID (entries never change once written).
* **Reconciling** on another clone: every archived task record is in Git history (an earlier
  ``tasks.json``). Walking the registry's history finds each artifact entry's record by its
  hash and fills the local store. Verification is not automatically reconciled. Git archives
  require task evidence and its referenced run to be committed before removing them from
  ``verification.json``; inspect Git history to recover historical evidence and reverify for
  fresh results. Outside Git, back up the SQLite store: it can be the only archived copy.

Only tasks whose annotation is already gone from source (presence ``missing``, or no source)
are archived, so an archived ID never shows up in source as "unregistered".
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import sqlite3
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from byteplan import jsonio
from byteplan.ids import is_valid_id
from byteplan.merge import _ABSENT, _merge_value, _same
from byteplan.models import Presence

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from pathlib import Path

    from byteplan.models import Task

STORE = "archive.sqlite"
INDEX = "archive.json"
INDEX_VERSION = 1
_ENTRY_FIELDS = frozenset({"archived_at", "closed_at", "kind", "sha256", "status", "title"})
_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    archived_at TEXT NOT NULL,
    record BLOB NOT NULL,
    PRIMARY KEY (id, sha256)
)
"""


def canonical(record: dict[str, Any]) -> bytes:
    return json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def record_hash(record: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(record)).hexdigest()


def closed_at(task: Task) -> str | None:
    """When the task last became resolved or dismissed (from its history)."""
    for event in reversed(task.history):
        if event.event == "resolved" or (event.event == "status_changed" and event.new in {"resolved", "dismissed"}):
            return event.at
    return None


def eligible(task: Task, now: str, after_days: int) -> bool:
    """Closed at least ``after_days`` ago, and no longer annotated in source."""
    if not task.status.is_closed or task.presence is Presence.STRIPPED:
        return False
    if task.source is not None and task.presence is not Presence.MISSING:
        return False
    when = closed_at(task)
    if when is None:
        return False
    return _parse(when) <= _parse(now) - timedelta(days=after_days)


def _parse(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


# The local store -------------------------------------------------------------------------------


class Store:
    """``.byteplan/archive.sqlite``: full records, compressed."""

    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / STORE

    @contextlib.contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """A connection that commits on success and is always closed (sqlite3's own context
        manager only commits)."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with contextlib.closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(_SCHEMA)
            if _legacy_schema(connection):
                # DDL must share the copy's transaction: interruption keeps the old store intact.
                connection.execute("BEGIN IMMEDIATE")
                if _legacy_schema(connection):
                    connection.execute("ALTER TABLE tasks RENAME TO tasks_legacy")
                    connection.execute(_SCHEMA)
                    connection.execute("INSERT INTO tasks SELECT id, sha256, archived_at, record FROM tasks_legacy")
                    connection.execute("DROP TABLE tasks_legacy")
            yield connection

    def put(self, entries: Iterable[tuple[str, dict[str, Any], str]]) -> None:
        """Keep every (task ID, record hash) version. ``payload`` is
        ``{"task": record, "evidence": ..., "run": ...}`` (the evidence's run
        metadata); the row's hash is the task record's."""
        with self._connect() as connection:
            if not connection.in_transaction:
                connection.execute("BEGIN IMMEDIATE")
            for task_id, payload, archived_at in entries:
                sha = record_hash(payload["task"])
                old = connection.execute(
                    "SELECT record FROM tasks WHERE id = ? AND sha256 = ?", (task_id, sha)
                ).fetchone()
                if old is not None and payload.get("evidence") is None:
                    previous = json.loads(zlib.decompress(old[0]))
                    if previous.get("evidence") is not None:
                        saved = {**payload, "evidence": previous["evidence"], "run": previous.get("run")}
                    else:
                        saved = payload
                else:
                    saved = payload
                connection.execute(
                    "INSERT OR REPLACE INTO tasks (id, sha256, archived_at, record) VALUES (?, ?, ?, ?)",
                    (task_id, sha, archived_at, zlib.compress(canonical(saved), 9)),
                )

    def get(self, task_id: str, sha: str | None = None) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        with self._connect() as connection:
            if sha is None:
                row = connection.execute(
                    "SELECT record FROM tasks WHERE id = ? ORDER BY archived_at DESC, rowid DESC LIMIT 1", (task_id,)
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT record FROM tasks WHERE id = ? AND sha256 = ?", (task_id, sha)
                ).fetchone()
        if row is None:
            return None
        payload: dict[str, Any] = json.loads(zlib.decompress(row[0]))
        return payload

    def hashes(self) -> set[tuple[str, str]]:
        if not self.path.exists():
            return set()
        with self._connect() as connection:
            return set(connection.execute("SELECT id, sha256 FROM tasks").fetchall())


def _legacy_schema(connection: sqlite3.Connection) -> bool:
    return {row[1] for row in connection.execute("PRAGMA table_info(tasks)") if row[5]} == {"id"}


# The committed index -------------------------------------------------------------------------


@dataclass
class Index:
    """``.byteplan/archive.json``: what's archived, for every clone to reconcile against."""

    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def loads(cls, text: str | None) -> Index:
        if not text:
            return cls()
        data = jsonio.loads(text)
        if not isinstance(data, dict):
            msg = "archive index must be a JSON object; restore valid metadata from Git before retrying"
            raise TypeError(msg)
        version = data.get("schema_version")
        if type(version) is not int or version != INDEX_VERSION:
            msg = (
                f"unsupported archive index schema_version {version!r}; upgrade BytePlan or restore "
                "a supported archive index from Git; do not change its version number by hand"
            )
            raise ValueError(msg)
        tasks = data.get("tasks")
        if not isinstance(tasks, dict):
            msg = "archive index tasks must be an object; restore valid metadata from Git before retrying"
            raise TypeError(msg)
        for task_id, record in tasks.items():
            if not is_valid_id(task_id) or not isinstance(record, dict):
                msg = f"archive index has an invalid task identity or record for {task_id!r}; restore it from Git"
                raise ValueError(msg)
            sha = record.get("sha256")
            if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{64}", sha) is None:
                msg = f"archive index task {task_id} requires a SHA-256 record hash; restore valid metadata from Git"
                raise ValueError(msg)
            for key in ("archived_at", "kind", "status", "title"):
                if key in record and not isinstance(record[key], str):
                    msg = f"archive index task {task_id} has invalid {key}; restore valid metadata from Git"
                    raise ValueError(msg)
            if "closed_at" in record and record["closed_at"] is not None and not isinstance(record["closed_at"], str):
                msg = f"archive index task {task_id} has invalid closed_at; restore valid metadata from Git"
                raise ValueError(msg)
            if "status" in record and record["status"] not in {"resolved", "dismissed"}:
                msg = f"archive index task {task_id} has a non-closed status; restore valid metadata from Git"
                raise ValueError(msg)
        return cls(dict(tasks), {key: value for key, value in data.items() if key not in {"schema_version", "tasks"}})

    def dumps(self) -> str:
        data = {**self.extra, "schema_version": INDEX_VERSION, "tasks": dict(sorted(self.tasks.items()))}
        return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def entry(task: Task, record: dict[str, Any], archived_at: str) -> dict[str, Any]:
    return {
        "archived_at": archived_at,
        "closed_at": closed_at(task),
        "kind": task.kind,
        "sha256": record_hash(record),
        "status": str(task.status),
        "title": task.display_title,
    }


def merge(base: str | None, ours: str | None, theirs: str | None) -> tuple[str | None, list[str]]:
    """Three-way merge of two indexes, entry by entry against ``base``: the merged text, or
    None and the conflicting task IDs. Entries are compared by record hash, so two branches
    archiving the same record independently agree."""
    indexes = [Index.loads(text) for text in (base, ours, theirs)]
    b, o, t = (index.tasks for index in indexes)
    merged: dict[str, dict[str, Any]] = {}
    conflicts: list[str] = []
    for task_id in sorted(set(b) | set(o) | set(t)):
        old, mine, theirs_ = (_sha(side.get(task_id)) for side in (b, o, t))
        if theirs_ in {mine, old}:
            chosen = o.get(task_id)
        elif mine == old:
            chosen = t.get(task_id)
        else:
            conflicts.append(task_id)
            continue
        original = b.get(task_id, {})
        if chosen is None and (kept := o.get(task_id) or t.get(task_id)) is not None:
            # Restoration may delete the index entry, but must not silently discard
            # an independent edit to its metadata. Archive timestamps alone are incidental.
            previous = {key: value for key, value in original.items() if key != "archived_at"}
            remaining = {key: value for key, value in kept.items() if key != "archived_at"}
            if not _same(previous, remaining):
                conflicts.append(f"{task_id} was restored on one side and its index metadata changed on the other")
        if chosen is not None:
            # The hash selects authoritative task state. Extra index metadata for that
            # same record still needs an ordinary conservative three-way merge.
            if mine is not None and theirs_ is not None:
                our_entry, their_entry = o[task_id], t[task_id]
                chosen = dict(chosen)
                excluded = {"sha256", "archived_at"} if mine == theirs_ else _ENTRY_FIELDS
                for key in sorted({*original, *our_entry, *their_entry} - excluded):
                    value = _merge_value(
                        f"{task_id}.{key}",
                        original.get(key, _ABSENT),
                        our_entry.get(key, _ABSENT),
                        their_entry.get(key, _ABSENT),
                        conflicts,
                    )
                    if value is _ABSENT:
                        chosen.pop(key, None)
                    else:
                        chosen[key] = value
            merged[task_id] = chosen
    extra: dict[str, Any] = {}
    b_extra, o_extra, t_extra = (index.extra for index in indexes)
    for key in sorted({*b_extra, *o_extra, *t_extra}):
        value = _merge_value(
            key, b_extra.get(key, _ABSENT), o_extra.get(key, _ABSENT), t_extra.get(key, _ABSENT), conflicts
        )
        if value is not _ABSENT:
            extra[key] = value
    if conflicts:
        return None, conflicts
    return Index(merged, extra).dumps(), []


def _sha(entry: dict[str, Any] | None) -> str | None:
    return None if entry is None else str(entry.get("sha256"))


# Reconciling from Git history ------------------------------------------------------------------


def find_in_history(
    wanted: dict[str, str], versions: Iterable[str], parse: Callable[[str], dict[str, dict[str, Any]]]
) -> dict[str, dict[str, Any]]:
    """Records whose canonical hash matches ``wanted`` (ID -> sha256), found by walking registry
    ``versions`` (newest first) until every wanted record is found or history runs out."""
    found: dict[str, dict[str, Any]] = {}
    pending = dict(wanted)
    for text in versions:
        if not pending:
            break
        try:
            tasks = parse(text)
        except (ValueError, KeyError):
            continue
        for task_id, sha in list(pending.items()):
            record = tasks.get(task_id)
            if record is not None and record_hash(record) == sha:
                found[task_id] = record
                del pending[task_id]
    return found
