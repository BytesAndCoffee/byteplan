# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Phase 4c: reconcile the staged snapshot before a commit is finalized.

The first committed appearance of an obligation should already carry its ID.
``byteplan scan --staged --apply`` (run by the pre-commit hook) plans the same
edits as a dry-run scan of the index, then writes them to **both** the index and
the working tree, so nothing is left behind as a phantom unstaged diff.

Safety, in order:

* Only *fully staged* targets are written: working-tree bytes must equal the
  staged blob. Anything else is ``partial_stage_conflict`` and nothing is
  written. The registry must be unchanged between index and working tree too.
* New blobs are written first (objects only), then a journal, then the index
  is replaced under Git's own lock: ``<index>.lock`` is created exclusively,
  entries are re-verified, a scratch copy is updated with
  ``update-index -z --index-info`` and verified, and the lock is renamed over
  the index. Inside ``git commit -a``/``--include`` the hook's index *is*
  ``.git/index.lock`` (``$GIT_INDEX_FILE``), and the same protocol applies to it.
* Working-tree files are then replaced (sources first, registry last), each
  only if it still holds its staged bytes. Any failure rolls everything back:
  files still holding BytePlan's bytes are restored, then the index entries.
  A file someone else changed meanwhile is never overwritten
  (``rollback_conflict``, journal kept).
* A crash leaves the journal; the next run picks one direction for every
  target (forward if nothing foreign is present, otherwise back), records it,
  and finishes it.

``git commit <paths>`` builds a temporary ``next-index-*`` while Git separately
stages the paths into the real index; annotating only the temporary index
would leave the real one behind, so that mode falls back to the read-only
check. Under the pre-commit framework (``PRE_COMMIT=1``), which stashes unstaged
changes and fails hooks that modify files, the index is left alone and only the
working tree is annotated, like a formatter.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from byteplan.api import Project, utc_now
from byteplan.diagnostics import EXIT_FINDINGS, EXIT_OK, Code
from byteplan.errors import ByteplanError, ConfigError
from byteplan.gitio import git, toplevel
from byteplan.persistence import atomic_write_bytes, project_lock, sha256, staged_dir

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

STAGED_JOURNAL = "journal.json"  # in persistence.staged_dir()
ZERO_OID = "0" * 40
NEW_FILE_MODE = "100644"


class IndexLockedError(ByteplanError):
    """Another Git process holds the index lock."""


class RollbackConflictError(ByteplanError):
    """A file or index entry changed after BytePlan wrote it; it was left alone."""


class _AbortError(Exception):
    """Internal: a guarded write found something unexpected; roll back."""


@dataclass
class JournalEntry:
    path: str  # project-relative
    top_path: str  # repository-relative (index path)
    mode: str
    before_oid: str | None  # None: not in the index before
    after_oid: str
    # Working-tree bytes, which may differ from the blobs (e.g. CRLF with core.autocrlf).
    # Exact copies live next to the journal, so rollback restores the original bytes.
    before_hash: str | None  # None: the file didn't exist
    after_hash: str
    before_copy: str | None
    after_copy: str
    written: bool = False


@dataclass
class StagedJournal:
    index: str | None  # None: working tree only (pre-commit framework)
    direction: str = "forward"
    entries: list[JournalEntry] = field(default_factory=list)

    @staticmethod
    def path(root: Path) -> Path:
        return staged_dir(root) / STAGED_JOURNAL

    def save(self, root: Path) -> None:
        data = {
            "version": 1,
            "index": self.index,
            "direction": self.direction,
            "entries": [asdict(e) for e in self.entries],
        }
        atomic_write_bytes(self.path(root), json.dumps(data, indent=2, sort_keys=True).encode())

    @classmethod
    def load(cls, root: Path) -> StagedJournal | None:
        try:
            data = json.loads(cls.path(root).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            msg = f"unreadable {STAGED_JOURNAL}: {exc}; inspect it, then delete it to discard"
            raise RollbackConflictError(msg) from exc
        return cls(data["index"], data["direction"], [JournalEntry(**e) for e in data["entries"]])

    def delete(self, root: Path) -> None:
        with contextlib.suppress(FileNotFoundError):
            self.path(root).unlink()
        shutil.rmtree(staged_dir(root), ignore_errors=True)


def pending(root: Path) -> bool:
    return StagedJournal.path(root).exists()


@dataclass
class StagedOutcome:
    code: int
    messages: list[str] = field(default_factory=list)
    annotated: list[str] = field(default_factory=list)  # "[id] KIND path:line title"
    wrote_index: bool = False


# Index plumbing ------------------------------------------------------------------------------------


def index_path(top: Path) -> Path:
    """The index this process would commit: ``$GIT_INDEX_FILE`` inside a commit, else the default."""
    env = os.environ.get("GIT_INDEX_FILE")
    raw = env if env else git(["rev-parse", "--git-path", "index"], top).strip()
    path = Path(raw)
    return path if path.is_absolute() else (Path.cwd() if env else top) / path


def _truthy_config(top: Path, key: str) -> bool:
    try:
        return git(["config", "--type=bool", "--get", key], top).strip() == "true"
    except ConfigError:
        return False


def _index_entries(top: Path, index: Path, paths: Sequence[str]) -> dict[str, tuple[str, str]]:
    env = {**os.environ, "GIT_INDEX_FILE": str(index), "GIT_OPTIONAL_LOCKS": "0", "GIT_LITERAL_PATHSPECS": "1"}
    out = subprocess.run(
        ["git", "--no-optional-locks", "ls-files", "--stage", "-z", "--full-name", "--", *paths],  # noqa: S607
        cwd=top,
        capture_output=True,
        env=env,
        check=True,
    ).stdout
    entries: dict[str, tuple[str, str]] = {}
    for record in out.split(b"\0"):
        if record:
            meta, _, path = record.partition(b"\t")
            mode, oid, _stage = meta.decode().split(" ")
            entries[path.decode("utf-8", "surrogateescape")] = (mode, oid)
    return entries


def _hash_object(top: Path, data: bytes) -> str:
    return (
        subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],  # noqa: S607 - git from PATH, like every Git call here
            cwd=top,
            input=data,
            capture_output=True,
            check=True,
        )
        .stdout.decode()
        .strip()
    )


def _swap_index(
    top: Path,
    index: Path,
    expected: Mapping[str, tuple[str, str] | None],
    wanted: Mapping[str, tuple[str, str] | None],
    precheck: Callable[[], None] | None = None,
) -> None:
    """Replace index entries under ``<index>.lock``, verifying ``expected`` while holding it."""
    lock = index.with_name(index.name + ".lock")
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        msg = f"{lock} exists: another Git process is using the index; try again when it finishes"
        raise IndexLockedError(msg) from None
    scratch = index.with_name(index.name + ".byteplan-scratch")
    committed = False
    try:
        current = _index_entries(top, index, list(expected))
        for path, entry in expected.items():
            if current.get(path) != entry:
                raise _AbortError(path)
        if precheck is not None:
            precheck()
        shutil.copyfile(index, scratch)
        lines = []
        for path, entry in wanted.items():
            mode, oid = entry if entry is not None else ("0", ZERO_OID)
            lines.append(f"{mode} {oid}\t{path}\0")
        env = {**os.environ, "GIT_INDEX_FILE": str(scratch)}
        subprocess.run(
            ["git", "update-index", "-z", "--index-info"],  # noqa: S607
            cwd=top,
            input="".join(lines).encode("utf-8", "surrogateescape"),
            env=env,
            capture_output=True,
            check=True,
        )
        if {p: _index_entries(top, scratch, [p]).get(p) for p in wanted} != wanted:
            msg = "index verification"
            raise _AbortError(msg)
        os.write(fd, scratch.read_bytes())
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(lock, index)
        committed = True
    finally:
        if fd >= 0:
            os.close(fd)
        if not committed:
            with contextlib.suppress(FileNotFoundError):
                lock.unlink()
        with contextlib.suppress(FileNotFoundError):
            scratch.unlink()


# Working tree ----------------------------------------------------------------------------------------


def _disk_hash(path: Path) -> str | None:
    try:
        return sha256(path.read_bytes())
    except FileNotFoundError:
        return None


def _git_out(top: Path, args: list[str], data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", *args],  # noqa: S607 - git from PATH, like every Git call here
        cwd=top,
        input=data,
        capture_output=True,
        check=True,
    ).stdout


def _normalized_oid(top: Path, top_path: str, data: bytes) -> str:
    """The blob ID Git would store for ``data`` at ``top_path`` (eol/clean filters applied)."""
    return _git_out(top, ["hash-object", "--stdin", f"--path={top_path}"], data).decode().strip()


def _worktree_form(top: Path, top_path: str, oid: str) -> bytes:
    """A blob as Git would check it out at ``top_path`` (eol/smudge filters applied)."""
    return _git_out(top, ["cat-file", "--filters", f"--path={top_path}", oid])


def _read_copy(root: Path, name: str) -> bytes:
    return (staged_dir(root) / name).read_bytes()


def _restore_file(root: Path, path: Path, copy: str | None) -> None:
    if copy is None:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
    else:
        atomic_write_bytes(path, _read_copy(root, copy))


def _rollback(root: Path, top: Path, journal: StagedJournal) -> None:
    """Undo everything the journal shows as done; never overwrite foreign changes."""
    journal.direction = "rollback"
    journal.save(root)
    conflicts = []
    for entry in journal.entries:
        if not entry.written:
            continue
        path = root / entry.path
        current = _disk_hash(path)
        if current == entry.after_hash:
            _restore_file(root, path, entry.before_copy)
        elif current != entry.before_hash:
            conflicts.append(entry.path)
    if journal.index is not None:
        index = Path(journal.index)
        if index.exists():
            after = {e.top_path: (e.mode, e.after_oid) for e in journal.entries}
            in_index = _index_entries(top, index, list(after))
            to_restore = {p: v for p, v in after.items() if in_index.get(p) == v}
            foreign = [p for p, v in after.items() if in_index.get(p) not in {v, _before(journal, p)}]
            conflicts += [f"{p} (index)" for p in foreign]
            if to_restore:
                _swap_index(top, index, to_restore, {p: _before(journal, p) for p in to_restore})
    if conflicts:
        msg = (
            "rollback_conflict: these changed after BytePlan wrote them and were left alone: "
            + ", ".join(conflicts)
            + f". Resolve them by hand, then delete {StagedJournal.path(root).relative_to(root).as_posix()}"
        )
        raise RollbackConflictError(msg)
    journal.delete(root)


def _before(journal: StagedJournal, top_path: str) -> tuple[str, str] | None:
    entry = next(e for e in journal.entries if e.top_path == top_path)
    return None if entry.before_oid is None else (entry.mode, entry.before_oid)


def _write_worktree(root: Path, journal: StagedJournal) -> None:
    # Sources first, registry last: a partial run never leaves IDs without registry entries.
    for entry in sorted(journal.entries, key=lambda e: e.path.endswith(".json")):
        if entry.written:
            continue
        path = root / entry.path
        if _disk_hash(path) != entry.before_hash:
            raise _AbortError(entry.path)
        atomic_write_bytes(path, _read_copy(root, entry.after_copy))
        entry.written = True
        journal.save(root)


def recover(root: Path) -> list[str]:
    """Finish or undo an interrupted staged reconciliation, under the project lock."""
    with project_lock(root):
        return _recover_locked(root)


def _recover_locked(root: Path) -> list[str]:
    journal = StagedJournal.load(root)
    if journal is None:
        return []
    top = toplevel(root)
    index_gone = journal.index is not None and not Path(journal.index).exists()
    for entry in journal.entries:  # anything already at BytePlan's bytes counts as written
        entry.written = entry.written or _disk_hash(root / entry.path) == entry.after_hash
    if journal.direction == "forward" and not index_gone and _all_known(root, top, journal):
        if journal.index is not None:
            index = Path(journal.index)
            after = {e.top_path: (e.mode, e.after_oid) for e in journal.entries}
            current = _index_entries(top, index, list(after))
            pending_swap = {p: _before(journal, p) for p, v in after.items() if current.get(p) != v}
            if pending_swap:
                _swap_index(top, index, pending_swap, {p: after[p] for p in pending_swap})
        _write_worktree(root, journal)
        journal.delete(root)
        return ["byteplan: completed an interrupted staged reconciliation"]
    # Backward. If the recorded index is gone (e.g. the temporary index of an aborted
    # `git commit -a`), the real index never received the change: undoing the working
    # tree is what makes everything consistent again.
    _rollback(root, top, journal)
    reason = "its index no longer exists" if index_gone else "something changed since"
    return [f"byteplan: undid an interrupted staged reconciliation ({reason})"]


def _all_known(root: Path, top: Path, journal: StagedJournal) -> bool:
    for entry in journal.entries:
        if _disk_hash(root / entry.path) not in {entry.before_hash, entry.after_hash}:
            return False
    if journal.index is not None and Path(journal.index).exists():
        current = _index_entries(top, Path(journal.index), [e.top_path for e in journal.entries])
        for entry in journal.entries:
            if current.get(entry.top_path) not in {(entry.mode, entry.after_oid), _before(journal, entry.top_path)}:
                return False
    return True


# Entry point ---------------------------------------------------------------------------------------


def reconcile_staged(start: Path | None = None, clock: Callable[[], str] = utc_now) -> StagedOutcome:
    start = (start or Path.cwd()).resolve()
    top = toplevel(start)
    index = index_path(top)
    framework = os.environ.get("PRE_COMMIT") == "1"

    if index.name.startswith("next-index-"):
        return _check_only(
            start,
            "`git commit <paths>` stages through a temporary index BytePlan can't safely update; "
            "checking instead. To get IDs added automatically, `git add` the files and run `git commit` "
            "without paths (or run `byteplan scan` first).",
        )
    if not framework:
        for key in ("core.splitIndex", "index.sparse"):
            if _truthy_config(top, key):
                msg = f"unsupported_index_format: {key} is enabled; use `byteplan scan` and stage manually"
                raise ConfigError(msg)

    probe = Project.open_snapshot(start, clock=clock)
    root = probe.root
    probe.close()
    # One reconciliation at a time: without the lock, a second run would mistake the first
    # one's live journal for a crash and "recover" it.
    with project_lock(root):
        messages = _recover_locked(root)
        planned = _plan(start, top, index, clock, framework=framework)
        if isinstance(planned, StagedOutcome):
            planned.messages[:0] = messages
            return planned
        journal, annotated, on_reconcile = planned
        outcome = _apply(root, top, journal, messages)
        if outcome is not None:
            return outcome

        summary = f"byteplan: annotated {len(journal.entries)} staged file(s)"
        lines = [*messages, summary, *(f"  {line}" for line in annotated)]
        if framework:
            lines.append("byteplan: `git add` the annotated files and commit again")
            return StagedOutcome(EXIT_FINDINGS, lines, annotated)
        check = _check_only(start, None)
    result = StagedOutcome(check.code, [*lines, *check.messages], annotated, wrote_index=True)
    if result.code == EXIT_OK and on_reconcile == "stop":
        result.code = EXIT_FINDINGS
        result.messages.append('byteplan: on_reconcile = "stop": review the annotations, then commit again')
    return result


def _plan(
    start: Path, top: Path, index: Path, clock: Callable[[], str], *, framework: bool
) -> StagedOutcome | tuple[StagedJournal, list[str], str]:
    """Build the journal for this reconciliation, or an outcome explaining why there's none."""
    project = Project.open_snapshot(start, clock=clock)
    try:
        snapshot = project.snapshot
        assert snapshot is not None  # noqa: S101 - open_snapshot always sets it
        root = project.root
        report = project.scan(dry_run=True)
        if report.blocked:
            return StagedOutcome(project.exit_code(report.diagnostics), [d.format_text() for d in report.diagnostics])
        changes = [w for w in report.planned if snapshot.read(w.path) != w.data]
        if not changes:
            return _check_only(start, None)

        journal = StagedJournal(None if framework else str(index))
        copies: dict[str, bytes] = {}
        conflicts = []
        for number, write in enumerate(changes):
            top_path = f"{snapshot.offset}/{write.path}" if snapshot.offset else write.path
            entry = snapshot.entries.get(top_path)
            disk_path = root / write.path
            on_disk = disk_path.read_bytes() if disk_path.exists() else None
            # "Fully staged" is judged through Git's own normalization (eol conversion, clean
            # filters): a CRLF file with core.autocrlf matches its LF blob.
            if entry is None:
                fully_staged = on_disk is None
            else:
                fully_staged = on_disk is not None and _normalized_oid(top, top_path, on_disk) == entry.oid
            if not fully_staged:
                code = (
                    "registry_partial_stage_conflict"
                    if write.path == project.registry_rel
                    else "partial_stage_conflict"
                )
                conflicts.append(f"{code}: {write.path} has unstaged changes")
                continue
            after_oid = _hash_object(top, write.data)
            after_disk = _worktree_form(top, top_path, after_oid)
            if _normalized_oid(top, top_path, after_disk) != after_oid:
                conflicts.append(f"partial_stage_conflict: {write.path} can't be mapped between index and working tree")
                continue
            before_copy = None if on_disk is None else f"{number}.before"
            if on_disk is not None:
                copies[f"{number}.before"] = on_disk
            copies[f"{number}.after"] = after_disk
            journal.entries.append(
                JournalEntry(
                    path=write.path,
                    top_path=top_path,
                    mode=entry.mode if entry else NEW_FILE_MODE,
                    before_oid=entry.oid if entry else None,
                    after_oid=after_oid,
                    before_hash=None if on_disk is None else sha256(on_disk),
                    after_hash=sha256(after_disk),
                    before_copy=before_copy,
                    after_copy=f"{number}.after",
                )
            )
        if conflicts:
            return StagedOutcome(
                EXIT_FINDINGS,
                [
                    *conflicts,
                    "byteplan: nothing was written. Stage the whole file(s) (or run `byteplan scan` "
                    "and re-stage), then commit again. Preview: `byteplan scan --staged --dry-run`",
                ],
            )
        annotated = [f"[{p.task_id}] {p.tag.kind} {p.tag.location}  {p.tag.title}" for p in report.proposals]
    finally:
        project.close()

    for name, data in copies.items():  # exact working-tree bytes, before the journal exists
        atomic_write_bytes(staged_dir(root) / name, data)
    journal.save(root)
    return journal, annotated, project.config.git.on_reconcile


def _apply(root: Path, top: Path, journal: StagedJournal, messages: list[str]) -> StagedOutcome | None:
    """Index swap then working tree; on failure roll everything back. None means success."""

    def worktree_unchanged() -> None:
        for entry in journal.entries:
            if _disk_hash(root / entry.path) != entry.before_hash:
                raise _AbortError(entry.path)

    try:
        if journal.index is not None:
            _swap_index(
                top,
                Path(journal.index),
                {e.top_path: None if e.before_oid is None else (e.mode, e.before_oid) for e in journal.entries},
                {e.top_path: (e.mode, e.after_oid) for e in journal.entries},
                precheck=worktree_unchanged,
            )
        _write_worktree(root, journal)
    except _AbortError as exc:
        _rollback(root, top, journal)
        return StagedOutcome(
            EXIT_FINDINGS,
            [*messages, f"concurrent_modification: {exc} changed while BytePlan was reconciling; nothing was changed"],
        )
    except BaseException:
        if StagedJournal.path(root).exists():
            with contextlib.suppress(Exception):
                _rollback(root, top, journal)
        raise
    journal.delete(root)
    return None


def _check_only(start: Path, note: str | None, messages: Sequence[str] = ()) -> StagedOutcome:
    project = Project.open_snapshot(start)
    try:
        report = project.check()
    finally:
        project.close()
    code = project.exit_code(report.diagnostics)
    lines = [*messages, *([f"byteplan: {note}"] if note else [])]
    lines += [d.format_text() for d in report.diagnostics if d.code is not Code.POSITION_DRIFT or code]
    return StagedOutcome(code, lines)


__all__ = ["IndexLockedError", "RollbackConflictError", "StagedOutcome", "pending", "reconcile_staged", "recover"]
