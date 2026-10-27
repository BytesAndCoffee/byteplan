# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Exclusive writer authority, including deliberate recovery after a stale lock."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from typing import TYPE_CHECKING

import pytest

from byteplan import persistence, registry
from byteplan._todo import verifies
from byteplan.errors import LockedError
from byteplan.models import Task

if TYPE_CHECKING:
    from pathlib import Path


def _record(ids: list[str]) -> bytes:
    stored = registry.Registry(tasks={ident: Task(ident, "TODO", ident) for ident in ids}, reserved_ids=set(ids))
    return registry.dumps(stored).encode()


@verifies("c6bc7c")
@pytest.mark.parametrize("marker", [b"999999999", b"0", b"-1", b"unreadable PID", b""])
def test_existing_lock_never_authorizes_automatic_removal(tmp_path: Path, marker: bytes) -> None:
    state = tmp_path / ".byteplan"
    state.mkdir()
    lock = state / "scan.lock"
    lock.write_bytes(marker)
    with pytest.raises(LockedError, match="Stop all BytePlan writers"), persistence.project_lock(tmp_path):
        pytest.fail("an existing lock must not grant writer authority")
    assert lock.read_bytes() == marker
    assert sorted(path.name for path in state.iterdir()) == ["scan.lock"]


@verifies("c6bc7c")
def test_competing_stale_lock_checks_cannot_publish_losing_transactions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The old implementation let both real commits succeed, silently losing bbbb.

    Only scheduling is instrumented: the first stale-owner read waits for the
    second attempt, which on old code holds its live replacement lock and has
    passed its real target hash check. No write/hash/lock result is fabricated.
    """
    state = tmp_path / ".byteplan"
    state.mkdir()
    target = state / "tasks.json"
    before = _record(["aaaa"])
    target.write_bytes(before)
    lock = state / "scan.lock"
    lock.write_bytes(b"999999999")
    stale_read = threading.Event()
    second_settled = threading.Event()
    first_finished = threading.Event()
    original_holder = persistence._lock_holder  # noqa: SLF001 - schedule the actual owner read
    original_write = persistence.atomic_write_bytes
    outcomes: dict[str, str] = {}

    def holder(path: Path) -> int | None:
        owner = original_holder(path)
        if threading.current_thread().name == "first-lock-writer":
            stale_read.set()
            assert second_settled.wait(15)
        return owner

    def write(path: Path, data: bytes, mode: int | None = None) -> bool:
        if threading.current_thread().name == "second-lock-writer" and path == target:
            second_settled.set()
            assert first_finished.wait(15)
        return original_write(path, data, mode)

    def writer(name: str, ident: str) -> None:
        try:
            if name == "second":
                assert stale_read.wait(15)
            with persistence.project_lock(tmp_path):
                persistence.commit(
                    tmp_path,
                    [
                        persistence.FileWrite(
                            ".byteplan/tasks.json", persistence.sha256(before), _record(["aaaa", ident])
                        )
                    ],
                )
            outcomes[name] = "committed"
        except LockedError:
            outcomes[name] = "locked"
        except Exception as exc:  # noqa: BLE001 - surface worker errors in the parent assertion
            outcomes[name] = repr(exc)
        finally:
            (first_finished if name == "first" else second_settled).set()

    monkeypatch.setattr(persistence, "_lock_holder", holder)
    monkeypatch.setattr(persistence, "atomic_write_bytes", write)
    first = threading.Thread(target=writer, args=("first", "bbbb"), name="first-lock-writer")
    second = threading.Thread(target=writer, args=("second", "cccc"), name="second-lock-writer")
    first.start()
    second.start()
    first.join(30)
    second.join(30)
    assert not first.is_alive()
    assert not second.is_alive()
    assert outcomes == {"first": "locked", "second": "locked"}, outcomes
    assert target.read_bytes() == before
    assert lock.read_bytes() == b"999999999"
    assert not persistence.pending_journal(tmp_path)
    assert not (state / "txn").exists()


@verifies("c6bc7c")
def test_manual_stale_lock_cleanup_retains_and_recovers_the_journal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "keep.txt"
    target.write_bytes(b"before\r\n")

    def interrupted(*_args: object, **_kwargs: object) -> list[str]:
        message = "simulated interruption after journal publication"
        raise RuntimeError(message)

    with monkeypatch.context() as fault:
        fault.setattr(persistence, "_apply", interrupted)
        with persistence.project_lock(tmp_path), pytest.raises(RuntimeError, match="simulated interruption"):
            persistence.commit(
                tmp_path, [persistence.FileWrite("keep.txt", persistence.sha256(b"before\r\n"), b"after\r\n")]
            )
    state = tmp_path / ".byteplan"
    lock = state / "scan.lock"
    lock.write_bytes(b"999999999")
    evidence = {path.name: path.read_bytes() for path in (state / "txn").iterdir()}
    assert "journal.json" in evidence
    with pytest.raises(LockedError), persistence.project_lock(tmp_path):
        persistence.recover(tmp_path)
    assert target.read_bytes() == b"before\r\n"
    assert {path.name: path.read_bytes() for path in (state / "txn").iterdir()} == evidence
    assert lock.read_bytes() == b"999999999"
    # Explicit owner action after all writers have stopped; never delete txn/.
    lock.unlink()
    with persistence.project_lock(tmp_path):
        assert persistence.recover(tmp_path) == ["keep.txt"]
        assert persistence.recover(tmp_path) == []
    assert target.read_bytes() == b"after\r\n"
    assert not lock.exists()
    assert not persistence.pending_journal(tmp_path)


_CHILD_WRITE = """\
import sys
from pathlib import Path
from byteplan import persistence, registry
from byteplan.errors import LockedError
from byteplan.models import Task
root = Path(sys.argv[1])
try:
    with persistence.project_lock(root):
        path = root / '.byteplan/tasks.json'
        before = path.read_bytes()
        stored = registry.loads(before.decode())
        stored.tasks['cccc'] = Task('cccc', 'TODO', 'child task')
        stored.reserved_ids.add('cccc')
        persistence.commit(root, [persistence.FileWrite('.byteplan/tasks.json', persistence.sha256(before), registry.dumps(stored).encode())])
except LockedError:
    sys.exit(2)
"""


@verifies("c6bc7c")
def test_real_process_writer_is_excluded_then_preserves_prior_successful_work(tmp_path: Path) -> None:
    state = tmp_path / ".byteplan"
    state.mkdir()
    target = state / "tasks.json"
    target.write_bytes(_record(["aaaa"]))
    command = [sys.executable, "-c", _CHILD_WRITE, str(tmp_path)]
    with persistence.project_lock(tmp_path):
        lock = state / "scan.lock"
        owned = lock.read_bytes()
        assert int(owned) == os.getpid()
        refused = subprocess.run(command, capture_output=True, check=False, timeout=30)
        assert refused.returncode == 2, refused.stderr.decode(errors="replace")
        assert lock.read_bytes() == owned
        before = target.read_bytes()
        persistence.commit(
            tmp_path,
            [persistence.FileWrite(".byteplan/tasks.json", persistence.sha256(before), _record(["aaaa", "bbbb"]))],
        )
    completed = subprocess.run(command, capture_output=True, check=False, timeout=30)
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    assert set(registry.loads(target.read_text(encoding="utf-8")).tasks) == {"aaaa", "bbbb", "cccc"}
    assert set(json.loads(target.read_bytes())["reserved_ids"]) == {"aaaa", "bbbb", "cccc"}
    assert not (state / "scan.lock").exists()
    assert not persistence.pending_journal(tmp_path)
