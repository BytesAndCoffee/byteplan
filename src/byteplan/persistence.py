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

A journal records the inode of this checkout's ``.byteplan/txn/`` directory, its origin.
Recovery replays only a journal whose origin matches: a clone or an unpacked archive creates
that directory afresh, so a journal supplied with the repository is refused before any write
instead of being replayed into arbitrary (even ignored) paths.

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
import secrets
import stat
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from byteplan import jsonio
from byteplan.errors import ConcurrentModificationError, JournalConflictError, LockedError
from byteplan.writeguard import control_directory, copy_path, project_target, valid_hash

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator, Sequence
    from pathlib import Path

STATE_DIR = ".byteplan"
TXN_DIR = "txn"
JOURNAL = "journal.json"
LOCK = "scan.lock"
JOURNAL_VERSION = 2


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
    for _ in range(10):
        tmp = path.with_name(f".{path.name}.byteplan-{secrets.token_hex(8)}.tmp")
        try:
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o666)
        except FileExistsError:
            continue
        break
    else:
        msg = f"could not allocate an exclusive temporary file for {path}"
        raise FileExistsError(msg)
    try:
        with os.fdopen(fd, "wb") as handle:
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
    """Hold ``.byteplan/scan.lock`` for a read-plan-write cycle.

    Never reclaim an existing lock automatically: between inspecting a dead PID
    and unlinking its pathname, another writer could have acquired a new lock.
    Deliberate stale-lock cleanup requires stopping all writers first.
    """
    try:
        control_directory(root, STATE_DIR)
        path = project_target(root, f"{STATE_DIR}/{LOCK}", control=True)
    except ValueError as exc:
        msg = f"unsafe project lock: {exc}"
        raise JournalConflictError(msg) from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        holder = _lock_holder(path)
        who = f"process {holder}" if holder is not None else "another process"
        msg = (
            f"{who} holds {path.relative_to(root).as_posix()}; existing locks are never removed automatically. "
            "Stop all BytePlan writers and confirm none is running before deleting this lock and retrying. "
            "Preserve .byteplan/txn/ so the next authorized write can recover any interrupted transaction"
        )
        raise LockedError(msg) from None
    created = os.fstat(fd)
    with os.fdopen(fd, "w") as handle:
        handle.write(str(os.getpid()))
    try:
        yield
    finally:
        # FIXME[aaf7d7]: Release only the lock this process created
        #   The finally block unlinks whatever `scan.lock` is there. If the lock was deleted by hand
        #   while this writer still ran (the guidance invites manual cleanup) and a second writer took
        #   it, this exit removes the second writer's lock and a third can start alongside it. Compare
        #   the file's identity (st_dev/st_ino) or a per-acquisition token before unlinking.
        # Remove only the file this process created: if it was deleted by hand meanwhile and
        # another writer took the lock, that writer's lock must stay.
        with contextlib.suppress(FileNotFoundError):
            current = path.lstat()
            if (current.st_dev, current.st_ino) == (created.st_dev, created.st_ino):
                path.unlink()


def _lock_holder(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def txn_origin(root: Path) -> int:
    """The identity a journal records: the inode of this checkout's transaction directory.

    Creates the directory. A clone or an unpacked archive gets a new directory, so a journal
    that arrives with repository content can't carry a matching origin.
    """
    txn = control_directory(root, f"{STATE_DIR}/{TXN_DIR}")
    txn.mkdir(parents=True, exist_ok=True)
    return txn.stat().st_ino


def check_origin(root: Path, origin: object, journal: Path) -> None:
    """Refuse a journal this checkout didn't write, before any recovery side effect."""
    try:
        local = (root / STATE_DIR / TXN_DIR).stat().st_ino
    except OSError:
        local = 0
    if type(origin) is not int or origin == 0 or origin != local:
        rel = journal.relative_to(root).as_posix()
        msg = (
            f"{rel} was not written by BytePlan in this checkout (it may have come with the repository "
            "or from an older BytePlan), so it is not replayed; nothing was written. Inspect it, then "
            f"delete {journal.parent.relative_to(root).as_posix()}/ to discard it "
            "(and `git rm -r --cached` it if it is tracked)"
        )
        raise JournalConflictError(msg)


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
    targets: set[Path] = set()
    try:
        control_directory(root, f"{STATE_DIR}/{TXN_DIR}")
        for write in writes:
            target = project_target(root, write.path)
            canonical = target.resolve(strict=False)
            if canonical in targets:
                msg = f"unsafe write plan; duplicate write target {write.path!r}; nothing was written"
                raise JournalConflictError(msg)
            targets.add(canonical)
    except (ValueError, OSError) as exc:
        msg = f"unsafe write plan; nothing was written: {exc}"
        raise JournalConflictError(msg) from exc
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
    origin = txn_origin(root)
    _clear_staging(txn)
    entries: list[dict[str, Any]] = []
    for index, write in enumerate(changed):
        staged = f"{index}.stage"
        fd = os.open(txn / staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(fd, "wb") as handle:
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
        json.dumps(
            {"version": JOURNAL_VERSION, "origin": origin, "entries": entries}, indent=2, sort_keys=True
        ).encode(),
    )
    _fsync_dir(txn)

    _apply(root, entries)
    _finish(txn)
    return [write.path for write in changed]


# FIXME[53c751]: Refuse to recover a transaction journal that came from the repository
#   A cloned repository can commit `.byteplan/txn/journal.json` and a staged copy (force-added past
#   `.byteplan/.gitignore`). The next ordinary write command (`byteplan scan`, `resolve`, a hook with
#   write_source) then "completes" it and creates any absent file under the root, including ignored
#   paths: `.venv/lib/python3.X/site-packages/sitecustomize.py` runs on the venv's next start. That
#   breaks "scanning never executes project code". gitwrite's staged journal (index null, forward)
#   has the same shape. Recover only journals this clone wrote (e.g. a hash recorded under the Git
#   dir), refuse tracked/committed control files, and limit targets to paths BytePlan plans writes to.
def recover(root: Path, *, allowed_targets: Collection[str] | None = None) -> list[str]:
    """Roll forward an interrupted transaction. Returns the paths it completed."""
    path = journal_path(root)
    try:
        txn = control_directory(root, f"{STATE_DIR}/{TXN_DIR}")
        project_target(root, f"{STATE_DIR}/{TXN_DIR}/{JOURNAL}", control=True)
        journal = jsonio.loads(path.read_text(encoding="utf-8"))
        entries = _journal_entries(root, journal)
        check_origin(root, journal["origin"], path)
    except FileNotFoundError:
        _clear_staging(path.parent)
        return []
    except (OSError, ValueError, KeyError, TypeError) as exc:
        msg = f"unreadable journal {path.relative_to(root).as_posix()}: {exc}"
        raise JournalConflictError(msg) from exc

    if isinstance(allowed_targets, (str, bytes)):
        msg = "allowed recovery write scope must be a collection of exact target paths"
        raise JournalConflictError(msg)
    if allowed_targets is not None and any(entry["target"] not in allowed_targets for entry in entries):
        msg = (
            "pending recovery includes targets outside the allowed write scope; "
            "deliberately authorize source recovery with source-write permission and apply=true, "
            "or run `byteplan scan` through an authorized CLI before retrying"
        )
        raise JournalConflictError(msg)

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
    # Read every required payload before the first target changes. Applying this immutable
    # plan cannot accidentally use bytes swapped into a copy after validation.
    payloads: dict[str, bytes] = {}
    try:
        for entry in entries:
            staged = copy_path(txn, entry["staged"], "stage")
            if file_hash(root / entry["target"]) == entry["after"] and not staged.exists():
                continue
            data = staged.read_bytes()
            if sha256(data) != entry["after"]:
                msg = f"invalid recovery copies; staged copy of {entry['target']} is corrupt; preserve and inspect it"
                raise JournalConflictError(msg)
            payloads[entry["staged"]] = data
    except (OSError, ValueError) as exc:
        msg = f"invalid recovery copies; preserve the journal and inspect them: {exc}"
        raise JournalConflictError(msg) from exc
    completed = _apply(root, entries, payloads=payloads)
    _finish(path.parent)
    return completed


def _journal_entries(root: Path, journal: Any) -> list[dict[str, Any]]:
    if (
        not isinstance(journal, dict)
        or set(journal) != {"version", "origin", "entries"}
        or type(journal["version"]) is not int
        or journal["version"] != JOURNAL_VERSION
        or not isinstance(journal["entries"], list)
    ):
        msg = "unsupported journal version or structure; preserve it and use a compatible client"
        raise ValueError(msg)
    paths: set[Path] = set()
    copies: set[str] = set()
    entries: list[dict[str, Any]] = []
    txn = control_directory(root, f"{STATE_DIR}/{TXN_DIR}")
    for entry in journal["entries"]:
        if not isinstance(entry, dict) or set(entry) != {"target", "staged", "before", "after", "mode"}:
            msg = "invalid journal entry structure"
            raise ValueError(msg)
        target = project_target(root, entry["target"])
        canonical = target.resolve(strict=False)
        if canonical in paths:
            msg = "duplicate journal target"
            raise ValueError(msg)
        copy_path(txn, entry["staged"], "stage")
        if entry["staged"] in copies:
            msg = "duplicate journal copy"
            raise ValueError(msg)
        if not valid_hash(entry["before"], absent=True) or not valid_hash(entry["after"]):
            msg = "invalid journal fingerprint"
            raise ValueError(msg)
        mode = entry["mode"]
        if mode is not None and (type(mode) is not int or mode != stat.S_IMODE(mode)):
            msg = "invalid journal file mode"
            raise ValueError(msg)
        paths.add(canonical)
        copies.add(entry["staged"])
        entries.append(entry)
    return entries


def _apply(root: Path, entries: Sequence[dict[str, Any]], *, payloads: dict[str, bytes] | None = None) -> list[str]:
    txn = root / STATE_DIR / TXN_DIR
    completed = []
    for entry in entries:
        try:
            target = project_target(root, entry["target"])
        except (OSError, ValueError) as exc:
            msg = f"unsafe target while applying recovery: {exc}"
            raise JournalConflictError(msg) from exc
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
        data = (
            payloads[entry["staged"]] if payloads is not None else copy_path(txn, entry["staged"], "stage").read_bytes()
        )
        if sha256(data) != entry["after"]:
            msg = f"staged copy of {entry['target']} is corrupt; delete {txn.relative_to(root).as_posix()}/ and re-run"
            raise JournalConflictError(msg)
        atomic_write_bytes(target, data, entry["mode"])
        completed.append(entry["target"])
    return completed


def _finish(txn: Path) -> None:
    try:
        control_directory(txn.parent.parent, f"{STATE_DIR}/{TXN_DIR}")
    except ValueError as exc:
        msg = f"unsafe transaction cleanup: {exc}"
        raise JournalConflictError(msg) from exc
    with contextlib.suppress(FileNotFoundError):
        (txn / JOURNAL).unlink()
    _fsync_dir(txn)
    _clear_staging(txn)


def _clear_staging(txn: Path) -> None:
    """Remove staged files from a transaction that never reached its journal."""
    try:
        control_directory(txn.parent.parent, f"{STATE_DIR}/{TXN_DIR}")
    except ValueError as exc:
        msg = f"unsafe transaction cleanup: {exc}"
        raise JournalConflictError(msg) from exc
    if not txn.is_dir():
        return
    for leftover in txn.iterdir():
        if leftover.name != JOURNAL and leftover.is_file():
            leftover.unlink()
