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
* **Reconciling** on another clone: every archived record is in Git history (an earlier
  ``tasks.json``). Walking the registry's history finds each artifact entry's record by its
  hash and fills the local store. Nothing is lost by the store being local.

Only tasks whose annotation is already gone from source (presence ``missing``, or no source)
are archived, so an archived ID never shows up in source as "unregistered".
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
import zlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from byteplan.models import Presence

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from pathlib import Path

    from byteplan.models import Task

STORE = "archive.sqlite"
INDEX = "archive.json"
INDEX_VERSION = 1
_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL,
    archived_at TEXT NOT NULL,
    record BLOB NOT NULL
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
            yield connection

    def put(self, entries: Iterable[tuple[str, dict[str, Any], str]]) -> None:
        """Insert or replace (task ID, payload, archived_at) rows. ``payload`` is
        ``{"task": record, "evidence": ..., "run": ...}`` (the evidence's run
        metadata); the row's hash is the task record's."""
        with self._connect() as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO tasks (id, sha256, archived_at, record) VALUES (?, ?, ?, ?)",
                [
                    (task_id, record_hash(payload["task"]), archived_at, zlib.compress(canonical(payload), 9))
                    for task_id, payload, archived_at in entries
                ],
            )

    def get(self, task_id: str) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        with self._connect() as connection:
            row = connection.execute("SELECT record FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if row is None:
            return None
        payload: dict[str, Any] = json.loads(zlib.decompress(row[0]))
        return payload

    def hashes(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        with self._connect() as connection:
            return dict(connection.execute("SELECT id, sha256 FROM tasks").fetchall())


# The committed index -------------------------------------------------------------------------


@dataclass
class Index:
    """``.byteplan/archive.json``: what's archived, for every clone to reconcile against."""

    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def loads(cls, text: str | None) -> Index:
        if not text:
            return cls()
        data = json.loads(text)
        return cls(dict(data.get("tasks", {})))

    def dumps(self) -> str:
        data = {"schema_version": INDEX_VERSION, "tasks": dict(sorted(self.tasks.items()))}
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


def merge(base: str | None, ours: str | None, theirs: str | None) -> str:
    """Union of two indexes by task ID (entries never change once written; on a clash, ours)."""
    merged = Index.loads(base)
    for side in (theirs, ours):
        merged.tasks.update(Index.loads(side).tasks)
    return merged.dumps()


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
