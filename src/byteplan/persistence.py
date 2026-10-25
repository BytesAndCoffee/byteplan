# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""The only module that writes project files.

A multi-file write is a transaction:

1. The caller holds the project lock (``.byteplan/scan.lock``).
2. Every target is re-read and compared with the hash the caller planned
   against; any difference aborts with ``ConcurrentModificationError`` and
   nothing is written.
3. New contents are staged under ``.byteplan/txn/`` and fsynced.
4. A journal listing (target, staged file, hash before, hash after) is written
   atomically and fsynced. From here on the transaction is committed.
5. Each target is replaced atomically (temp file in the target's directory,
   ``os.replace``, then an fsync of that directory so the rename is durable),
   keeping its permissions. The registry is always last. Immediately before
   each replacement the target's hash is checked again; content that matches
   neither the planned "before" nor the staged "after" (an editor saved it
   meanwhile) stops the write with ``JournalConflictError`` instead of being
   overwritten. A residual race between that check and ``os.replace`` remains;
   no portable compare-and-swap rename exists.
6. The journal and staged files are deleted.

There is no filesystem-wide atomic rename, so a crash during step 5 can leave
some targets old and some new. Recovery rolls forward: any later write command
finds the journal and finishes the replacements (idempotent, by hash). A target
whose hash is neither "before" nor "after" stops recovery with
``JournalConflictError`` and leaves the journal for manual repair.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import stat
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from byteplan.errors import ConcurrentModificationError, JournalConflictError, LockedError

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

STATE_DIR = ".byteplan"
TXN_DIR = "txn"
JOURNAL = "journal.json"
LOCK = "scan.lock"
JOURNAL_VERSION = 1


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str | None:
    try:
        return sha256(path.read_bytes())
    except (FileNotFoundError, NotADirectoryError):  # a file where a directory should be: absent too
        return None


@dataclass(frozen=True)
class FileWrite:
    path: str  # POSIX, relative to the project root
    before: str | None  # sha256 the caller planned against; None = must not exist
    data: bytes


def _fsync_dir(path: Path) -> None:
    if sys.platform == "win32":  # no directory handles to fsync
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, data: bytes, mode: int | None = None) -> bool:
    """Atomically replace ``path`` with ``data``, keeping its permissions.

    Returns ``False`` without touching the file when it already holds ``data``.
    """
    try:
        if path.read_bytes() == data:
            return False
        if mode is None:
            mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        pass

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.byteplan-{os.getpid()}.tmp")
    try:
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            tmp.chmod(mode)
        os.replace(tmp, path)
        # Persist the rename itself; callers delete the recovery journal only
        # after every replacement is durable.
        _fsync_dir(path.parent)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise
    return True


@contextlib.contextmanager
def project_lock(root: Path) -> Iterator[None]:
    """Hold ``.byteplan/scan.lock`` for the duration of a read-plan-write cycle."""
    path = root / STATE_DIR / LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            holder = _lock_holder(path)
            if attempt == 0 and holder is not None and not _pid_alive(holder):
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
                continue
            who = f"process {holder}" if holder is not None else "another process"
            msg = f"{who} holds {path.relative_to(root).as_posix()}; if no byteplan is running, delete it"
            raise LockedError(msg) from None
        with os.fdopen(fd, "w") as handle:
            handle.write(str(os.getpid()))
        break
    try:
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def _lock_holder(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":  # os.kill(pid, 0) is not a probe on Windows
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def staged_dir(root: Path) -> Path:
    """Working directory of an in-progress staged (Git index) reconciliation (Phase 4c).

    A subdirectory, so the regular transaction's cleanup of plain files in ``txn/``
    never touches it.
    """
    return root / STATE_DIR / TXN_DIR / "staged"


def journal_path(root: Path) -> Path:
    return root / STATE_DIR / TXN_DIR / JOURNAL


def pending_journal(root: Path) -> bool:
    return journal_path(root).exists()


def commit(root: Path, writes: Sequence[FileWrite]) -> list[str]:
    """Apply ``writes`` as one journaled transaction. Returns the paths that changed.

    The caller must hold ``project_lock``. Writes whose data equals the current
    content are skipped; the registry should be passed last.
    """
    changed: list[FileWrite] = []
    conflicts: list[str] = []
    for write in writes:
        current = file_hash(root / write.path)
        if current != write.before:
            conflicts.append(write.path)
        elif current != sha256(write.data):
            changed.append(write)
    if conflicts:
        raise ConcurrentModificationError(conflicts)
    if not changed:
        return []

    txn = root / STATE_DIR / TXN_DIR
    txn.mkdir(parents=True, exist_ok=True)
    _clear_staging(txn)
    entries: list[dict[str, Any]] = []
    for index, write in enumerate(changed):
        staged = f"{index}.stage"
        with (txn / staged).open("wb") as handle:
            handle.write(write.data)
            handle.flush()
            os.fsync(handle.fileno())
        target = root / write.path
        # Before the journal exists, so a directory that can't be created (a file in the way)
        # fails this commit cleanly instead of leaving a journal no recovery can complete.
        target.parent.mkdir(parents=True, exist_ok=True)
        mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
        entries.append(
            {
                "target": write.path,
                "staged": staged,
                "before": write.before,
                "after": sha256(write.data),
                "mode": mode,
            }
        )
    atomic_write_bytes(
        journal_path(root),
        json.dumps({"version": JOURNAL_VERSION, "entries": entries}, indent=2, sort_keys=True).encode(),
    )
    _fsync_dir(txn)

    _apply(root, entries)
    _finish(txn)
    return [write.path for write in changed]


# FIXME[62edd5]: Confine serialized transaction and restore targets before filesystem side effects.
def recover(root: Path) -> list[str]:
    """Roll forward an interrupted transaction. Returns the paths it completed."""
    path = journal_path(root)
    try:
        journal = json.loads(path.read_text(encoding="utf-8"))
        entries = journal["entries"]
    except FileNotFoundError:
        _clear_staging(path.parent)
        return []
    except (OSError, ValueError, KeyError, TypeError) as exc:
        msg = f"unreadable journal {path.relative_to(root).as_posix()}: {exc}"
        raise JournalConflictError(msg) from exc

    conflicts = []
    for entry in entries:
        current = file_hash(root / entry["target"])
        if current not in {entry["before"], entry["after"]}:
            conflicts.append(entry["target"])
    if conflicts:
        msg = (
            "an interrupted write cannot be completed because these files changed since: "
            + ", ".join(conflicts)
            + f". Inspect them, then delete {path.parent.relative_to(root).as_posix()}/ to discard the rest"
        )
        raise JournalConflictError(msg)
    completed = _apply(root, entries)
    _finish(path.parent)
    return completed


def _apply(root: Path, entries: Sequence[dict[str, Any]]) -> list[str]:
    txn = root / STATE_DIR / TXN_DIR
    completed = []
    for entry in entries:
        target = root / entry["target"]
        current = file_hash(target)
        if current == entry["after"]:
            continue
        if current != entry["before"]:
            # Changed by something outside BytePlan (an editor) after planning.
            # Keep the journal so nothing is lost; the user decides.
            msg = (
                f"{entry['target']} changed while byteplan was writing; it was not overwritten. "
                f"Inspect it, then re-run `byteplan scan` (or delete {txn.relative_to(root).as_posix()}/ "
                "to discard the rest of the interrupted write)"
            )
            raise JournalConflictError(msg)
        data = (txn / entry["staged"]).read_bytes()
        if sha256(data) != entry["after"]:
            msg = f"staged copy of {entry['target']} is corrupt; delete {txn.relative_to(root).as_posix()}/ and re-run"
            raise JournalConflictError(msg)
        atomic_write_bytes(target, data, entry["mode"])
        completed.append(entry["target"])
    return completed


def _finish(txn: Path) -> None:
    with contextlib.suppress(FileNotFoundError):
        (txn / JOURNAL).unlink()
    _fsync_dir(txn)
    _clear_staging(txn)


def _clear_staging(txn: Path) -> None:
    """Remove staged files from a transaction that never reached its journal."""
    if not txn.is_dir():
        return
    for leftover in txn.iterdir():
        if leftover.name != JOURNAL and leftover.is_file():
            leftover.unlink()
