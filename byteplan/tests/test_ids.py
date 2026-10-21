# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from byteplan.errors import IdExhaustedError
from byteplan.ids import ID_SPACE, allocate, candidate, is_valid_id

ALL_IDS = {f"{n:04x}" for n in range(ID_SPACE)}


def test_candidate_is_four_lowercase_hex_and_deterministic() -> None:
    first = candidate("src/a.py\0f\0TODO\0x\x000", 0)
    assert is_valid_id(first)
    assert first == candidate("src/a.py\0f\0TODO\0x\x000", 0)
    assert first != candidate("src/a.py\0f\0TODO\0x\x000", 1)


@pytest.mark.parametrize("value", ["7fa2", "0000", "ffff"])
def test_valid_ids(value: str) -> None:
    assert is_valid_id(value)


@pytest.mark.parametrize("value", ["7FA2", "7fa", "7fa21", "zz12", "", " 7fa"])
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


def test_last_free_id_is_found() -> None:
    used = ALL_IDS - {"beef"}
    assert allocate("anything", used) == "beef"


def test_exhaustion_raises_instead_of_returning_invalid_id() -> None:
    with pytest.raises(IdExhaustedError):
        allocate("seed", ALL_IDS)
