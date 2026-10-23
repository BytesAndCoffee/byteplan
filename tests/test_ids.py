# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from byteplan import ids
from byteplan.errors import IdExhaustedError
from byteplan.ids import allocate, candidate, is_valid_id


def test_candidate_is_six_lowercase_hex_and_deterministic() -> None:
    first = candidate("src/a.py\0f\0TODO\0x\x000", 0)
    assert is_valid_id(first)
    assert len(first) == 6
    assert first == candidate("src/a.py\0f\0TODO\0x\x000", 0)
    assert first != candidate("src/a.py\0f\0TODO\0x\x000", 1)


@pytest.mark.parametrize("value", ["7fa2", "0000", "ffff", "7fa21", "123456", "0123456789abcdef"])
def test_valid_ids(value: str) -> None:
    assert is_valid_id(value)


@pytest.mark.parametrize("value", ["7FA2", "7fa", "zz12", "", " 7fa", "123456\n"])
def test_invalid_ids(value: str) -> None:
    assert not is_valid_id(value)


def test_allocate_uses_first_candidate_when_free() -> None:
    assert allocate("seed", set()) == candidate("seed", 0)


def test_collision_retries_with_next_attempt() -> None:
    used = {candidate("seed", 0), candidate("seed", 1)}
    assert allocate("seed", used) == candidate("seed", 2)


def test_reserved_historic_ids_are_never_reused() -> None:
    historic = candidate("seed", 0)
    assert allocate("seed", {historic}) != historic


def test_last_free_id_is_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ids, "ID_SPACE", 16)
    monkeypatch.setattr(ids, "MAX_HASH_ATTEMPTS", 2)
    monkeypatch.setattr(ids, "candidate", lambda *_: "000000")
    used = {f"{n:06x}" for n in range(16)} - {"00000f"}
    assert allocate("anything", used) == "00000f"


def test_exhaustion_raises_instead_of_returning_invalid_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ids, "ID_SPACE", 16)
    with pytest.raises(IdExhaustedError):
        allocate("seed", {f"{n:06x}" for n in range(16)})


def test_legacy_and_long_ids_do_not_exhaust_allocation_space(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ids, "ID_SPACE", 2)
    used = {"abcd", "abcd01ff", "0000", "000000ff"}
    assert len(allocate("seed", used)) == 6
