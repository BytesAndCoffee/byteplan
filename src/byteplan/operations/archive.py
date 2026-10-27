# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Internal archive orchestration delegated by Project."""

from __future__ import annotations

import contextlib
import json
import os
from typing import TYPE_CHECKING, Any

from byteplan import archive as archive_store
from byteplan import gitio, verification
from byteplan import registry as registry_io
from byteplan.errors import (
    ConcurrentModificationError,
    ConfigError,
)
from byteplan.persistence import (
    STATE_DIR,
    FileWrite,
    atomic_write_bytes,
    sha256,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from byteplan.models import Task

from byteplan._api_types import ArchiveReport, ReconcileReport
from byteplan.operations.common import _read_bytes

if TYPE_CHECKING:
    from byteplan.api import Project


def _load_index(data: bytes | None, rel: str) -> archive_store.Index:
    if data == b"":
        msg = f"{rel} is unreadable (archive index is empty); restore valid metadata from Git before retrying"
        raise ConfigError(msg)
    try:
        return archive_store.Index.loads(data.decode("utf-8") if data is not None else None)
    except (ValueError, AttributeError, TypeError) as exc:
        msg = f"{rel} is unreadable ({exc}); restore it from Git"
        raise ConfigError(msg) from exc


def archive_index(self: Project) -> archive_store.Index:
    rel = self.archive_index_rel
    try:
        data = self.snapshot.read(rel) if self.snapshot is not None else (self.root / rel).read_bytes()
    except FileNotFoundError:
        data = None
    except OSError as exc:
        msg = f"{rel} is unreadable ({exc}); restore it from Git or repair repository access"
        raise ConfigError(msg) from exc
    return _load_index(data, rel)


def archived_task(self: Project, task_id: str) -> Task | None:
    """An archived task, from the local store (reconciled from Git history if needed)."""
    if self.snapshot is not None:
        msg = (
            "archived task lookup requires the working-tree project; snapshots do not use or reconcile its local cache"
        )
        raise ConfigError(msg)
    entry = self.archive_index().tasks.get(task_id)
    if entry is None:
        return None
    store = archive_store.Store(self.root / STATE_DIR, project_root=self.root)
    payload = store.get(task_id, entry["sha256"])
    if payload is None or archive_store.record_hash(payload["task"]) != entry["sha256"]:
        self.reconcile_archive()  # a row from another archive of this task counts as a miss
        payload = store.get(task_id, entry["sha256"])
    if payload is None or archive_store.record_hash(payload["task"]) != entry["sha256"]:
        msg = f"task {task_id} is archived, but its record isn't in this clone's Git history"
        raise ConfigError(msg)
    wrapper = {
        "schema_version": registry_io.SCHEMA_VERSION,
        "reserved_ids": [task_id],
        "tasks": {task_id: payload["task"]},
    }
    return registry_io.from_dict(wrapper, f"archive:{task_id}").tasks[task_id]


def archive(self: Project, *, dry_run: bool = False, older_than: int | None = None) -> ArchiveReport:
    """Move tasks closed at least ``older_than`` (default ``after_days``) days ago, whose
    annotation is gone, out of ``tasks.json`` into the local store and the committed index.
    Their IDs stay reserved; their evidence moves with them. In a Git repository only
    records and current evidence already committed as they are are moved, preserving a
    recoverable copy. Automatic reconciliation recovers task records, not verification."""
    self._require_working_tree()
    days = self.config.archive.after_days if older_than is None else older_than
    context = contextlib.nullcontext(()) if dry_run else self._writing()
    with context:
        registry_hash, registry = self._read_registry()
        index_before = None
        try:
            index_before = (
                self.snapshot.read(self.archive_index_rel)
                if self.snapshot is not None
                else (self.root / self.archive_index_rel).read_bytes()
            )
        except FileNotFoundError:
            pass
        except OSError as exc:
            msg = f"{self.archive_index_rel} is unreadable ({exc}); restore it from Git"
            raise ConfigError(msg) from exc
        index = _load_index(index_before, self.archive_index_rel)
        if self.stripped_release(registry) is not None:
            return ArchiveReport((), dry_run)  # tasks stay put while a release is on record
        now = self.clock()
        eligible = sorted(t for t, task in registry.tasks.items() if archive_store.eligible(task, now, days))
        committed = self._committed_records() if eligible else None
        evidence_before = None
        if eligible:
            try:
                evidence_before = (
                    self.snapshot.read(verification.STORE)
                    if self.snapshot is not None
                    else (self.root / verification.STORE).read_bytes()
                )
            except FileNotFoundError:
                pass
            except OSError as exc:
                msg = f"{verification.STORE} is unreadable ({exc}); restore it from Git or resolve the conflict before retrying"
                raise ConfigError(msg) from exc
        evidence = (
            verification.Evidence.loads(evidence_before) if evidence_before is not None else verification.Evidence()
        )
        committed_evidence = (
            self._committed_evidence()
            if committed is not None and any(task_id in evidence.tasks for task_id in eligible)
            else verification.Evidence()
        )
        chosen: list[str] = []
        uncommitted: list[str] = []
        for task_id in eligible:
            record = registry_io.task_to_dict(registry.tasks[task_id])
            ok = committed is None or (
                task_id in committed and archive_store.canonical(committed[task_id]) == archive_store.canonical(record)
            )
            if ok and committed is not None and task_id in evidence.tasks:
                current = evidence.tasks[task_id]
                previous = committed_evidence.tasks.get(task_id)
                # Canonical JSON compares opaque extensions without conflating True with 1.
                ok = archive_store.canonical(
                    {
                        "entry": current,
                        "run": evidence.runs.get(str(current.get("run"))),
                    }
                ) == archive_store.canonical(
                    {
                        "entry": previous,
                        "run": committed_evidence.runs.get(str(previous.get("run"))) if previous else None,
                    }
                )
            (chosen if ok else uncommitted).append(task_id)
        if dry_run or not chosen:
            return ArchiveReport(tuple(chosen), dry_run, uncommitted=tuple(uncommitted))
        rows = []
        for task_id in chosen:
            task = registry.tasks.pop(task_id)
            record = registry_io.task_to_dict(task)
            kept = evidence.tasks.pop(task_id, None)
            run = evidence.runs.get(str(kept.get("run"))) if kept else None
            rows.append((task_id, {"task": record, "evidence": kept, "run": run}, now))
            index.tasks[task_id] = archive_store.entry(task, record, now)
        # The local store first: if the JSON writes are interrupted, it just holds extra rows.
        archive_store.Store(self.root / STATE_DIR, project_root=self.root).put(rows)
        self._ignore_archive_store()
        before = None if index_before is None else sha256(index_before)
        writes = [FileWrite(self.archive_index_rel, before, index.dumps().encode())]
        if evidence_before is not None:
            writes.append(FileWrite(verification.STORE, sha256(evidence_before), evidence.dumps()))
        writes.extend(self._registry_writes(registry_hash, registry))
        written = self._commit(writes)
        return ArchiveReport(tuple(chosen), dry_run, tuple(written), tuple(uncommitted))


def archived_evidence(self: Project, task_id: str) -> verification.Evidence:
    """The evidence (and its run) archived with a task, as an ``Evidence`` of its own."""
    entry = self.archive_index().tasks.get(task_id)
    payload = (
        archive_store.Store(self.root / STATE_DIR, project_root=self.root).get(task_id, entry["sha256"])
        if entry
        else None
    ) or {}
    kept, run = payload.get("evidence"), payload.get("run")
    if kept is None:
        return verification.Evidence()
    if not isinstance(kept, dict) or (run is not None and not isinstance(kept.get("run"), str)):
        msg = f"task {task_id}: archived verification evidence has an invalid entry/run identity; preserve and repair its payload"
        raise ConfigError(msg)
    runs = {str(kept.get("run")): run} if run is not None else {}
    return verification.Evidence.loads(
        json.dumps({"schema_version": verification.STORE_VERSION, "tasks": {task_id: kept}, "runs": runs})
    )


def committed_records(self: Project) -> dict[str, Any] | None:
    """Task records in ``HEAD``'s registry; None outside Git (no other clones to serve)."""
    try:
        gitio.git(["rev-parse", "--git-dir"], self.root)
    except ConfigError:
        # A failed Git command is not proof this is a standalone project. Broken
        # config, unavailable Git, worktree gitfiles and explicit selectors must
        # fail closed instead of bypassing the committed-evidence requirement.
        if any(name in os.environ for name in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE")):
            raise
        for directory in (self.root, *self.root.parents):
            try:
                (directory / ".git").lstat()
            except FileNotFoundError:
                pass
            except OSError as exc:
                msg = f"cannot inspect Git metadata before archiving ({exc}); repair repository access and retry"
                raise ConfigError(msg) from exc
            else:
                marker = directory / ".git"
                try:
                    # Empty directories are not Git repositories (some execution
                    # sandboxes place an empty .git marker in a shared ancestor).
                    if marker.is_symlink() or not marker.is_dir() or next(marker.iterdir(), None) is not None:
                        raise
                except OSError as exc:
                    msg = f"cannot inspect Git metadata before archiving ({exc}); repair repository access and retry"
                    raise ConfigError(msg) from exc
            try:
                # Bare repositories have no .git entry. lstat also fails closed
                # when filesystem permissions prevent inspecting a candidate.
                for component in ("HEAD", "objects", "refs"):
                    (directory / component).lstat()
            except FileNotFoundError:
                pass
            except OSError as exc:
                msg = f"cannot inspect Git metadata before archiving ({exc}); repair repository access and retry"
                raise ConfigError(msg) from exc
            else:
                raise
        return None
    try:
        text = gitio.git(["show", f"HEAD:./{self.registry_rel}"], self.root)
    except ConfigError:
        return {}
    # Validate shape/schema before returning raw records: tasks:null must never
    # masquerade as the outside-Git sentinel, and normalization could make the
    # archived record's hash differ from every version recoverable from Git.
    registry_io.loads(text, f"HEAD:{self.registry_rel}")
    tasks: dict[str, Any] = json.loads(text).get("tasks", {})
    return tasks


def committed_evidence(self: Project) -> verification.Evidence:
    """HEAD's verification payload; staged or local-only evidence is not a durable copy."""
    try:
        text = gitio.git(["show", f"HEAD:./{verification.STORE}"], self.root)
    except ConfigError:
        return verification.Evidence()
    return verification.Evidence.loads(text)


def ignore_archive_store(self: Project) -> None:
    gitignore = self.root / STATE_DIR / ".gitignore"
    current = (_read_bytes(gitignore) or b"").decode()
    # Only a rule line counts (a comment mentioning the name doesn't), and the last matching
    # rule wins, as in Git: a later `!archive.sqlite` un-ignores it.
    rules = [line.strip() for line in current.splitlines()]
    positive = {archive_store.STORE, f"/{archive_store.STORE}"}
    last = next((rule for rule in reversed(rules) if rule.removeprefix("!") in positive), None)
    if last is None or last.startswith("!"):
        atomic_write_bytes(gitignore, (current.rstrip("\n") + f"\n{archive_store.STORE}\n").lstrip("\n").encode())


def restore_archived(self: Project, task_id: str) -> tuple[str, ...]:
    """Put an archived task back into ``tasks.json`` (with its evidence, if this clone has it)."""
    with self._writing():
        registry_hash, registry = self._read_registry()
        index_before = None
        try:
            index_before = (self.root / self.archive_index_rel).read_bytes()
        except FileNotFoundError:
            pass
        except OSError as exc:
            msg = f"{self.archive_index_rel} is unreadable ({exc}); restore it from Git"
            raise ConfigError(msg) from exc
        index = _load_index(index_before, self.archive_index_rel)
        task_id = self._resolve_task_id(task_id, registry)
        if task_id in registry.tasks:
            msg = f"task {task_id} is already in the registry"
            raise ConfigError(msg)
        task = self.archived_task(task_id)
        if task is None:
            msg = f"task {task_id} isn't archived"
            raise ConfigError(msg)
        entry = index.tasks.get(task_id)
        if entry is None:
            raise ConcurrentModificationError([self.archive_index_rel])
        payload = archive_store.Store(self.root / STATE_DIR, project_root=self.root).get(task_id, entry["sha256"])
        if payload is None or archive_store.record_hash(payload["task"]) != entry["sha256"]:
            raise ConcurrentModificationError([self.archive_index_rel])
        # Lazy reconciliation may have consulted a newer index. The restored task
        # and its evidence must still refer to the record selected by this plan.
        selected = registry_io.from_dict(
            {
                "schema_version": registry_io.SCHEMA_VERSION,
                "reserved_ids": [task_id],
                "tasks": {task_id: payload["task"]},
            },
            f"archive:{task_id}",
        ).tasks[task_id]
        if archive_store.canonical(registry_io.task_to_dict(task)) != archive_store.canonical(
            registry_io.task_to_dict(selected)
        ):
            raise ConcurrentModificationError([self.archive_index_rel])
        registry.tasks[task_id] = task
        del index.tasks[task_id]
        writes = [
            FileWrite(
                self.archive_index_rel,
                None if index_before is None else sha256(index_before),
                index.dumps().encode(),
            )
        ]
        if payload.get("evidence") is not None:
            evidence_before = None
            try:
                evidence_before = (self.root / verification.STORE).read_bytes()
            except FileNotFoundError:
                pass
            except OSError as exc:
                msg = f"{verification.STORE} is unreadable ({exc}); restore it from Git or resolve the conflict before retrying"
                raise ConfigError(msg) from exc
            evidence = (
                verification.Evidence.loads(evidence_before) if evidence_before is not None else verification.Evidence()
            )
            # An archived identity can be verified again before restoring its
            # task record. Current canonical evidence remains authoritative,
            # even when empty, stale or failing; its cached history stays local.
            if task_id not in evidence.tasks:
                evidence.restore_task(task_id, payload["evidence"], payload.get("run"))
                before = None if evidence_before is None else sha256(evidence_before)
                writes.append(FileWrite(verification.STORE, before, evidence.dumps()))
        writes.extend(self._registry_writes(registry_hash, registry))
        return tuple(self._commit(writes))


def reconcile_archive(self: Project) -> ReconcileReport:
    """Fill the local store with every archived record it lacks, found by hash in the
    registry's Git history. Verification payloads are stored separately and are not
    automatically recovered by this traversal; reconciled records come without them."""
    self._require_working_tree()
    index = self.archive_index()
    store = archive_store.Store(self.root / STATE_DIR, project_root=self.root)
    have = store.hashes()
    wanted = {t: e["sha256"] for t, e in index.tasks.items() if (t, e["sha256"]) not in have}
    if not wanted:
        return ReconcileReport((), (), len(index.tasks))
    try:
        # --full-history: a merge whose registry matches one parent must not hide the other's.
        log = ["log", "--full-history", "--format=%H", "--", self.registry_rel]
        commits = gitio.git(log, self.root).split()
    except ConfigError:
        commits = []

    def versions() -> Iterator[str]:
        for rev in commits:
            with contextlib.suppress(ConfigError):
                yield gitio.git(["show", f"{rev}:./{self.registry_rel}"], self.root)

    found = archive_store.find_in_history(wanted, versions(), lambda text: json.loads(text)["tasks"])
    store.put((t, {"task": record, "evidence": None}, index.tasks[t]["archived_at"]) for t, record in found.items())
    missing = sorted(set(wanted) - set(found))
    return ReconcileReport(tuple(sorted(found)), tuple(missing), len(index.tasks) - len(wanted))
