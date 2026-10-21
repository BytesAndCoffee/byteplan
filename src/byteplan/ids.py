# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Four-hex-digit task IDs.

SHAKE128 is used for convenient deterministic output, not for any security
property. IDs are unique only within one project's reservation ledger.
"""

from __future__ import annotations

import re
from hashlib import shake_128
from typing import TYPE_CHECKING

from byteplan.errors import IdExhaustedError

if TYPE_CHECKING:
    from collections.abc import Collection

ID_RE = re.compile(r"[0-9a-f]{4}")
ID_SPACE = 1 << 16
# Hash retries before falling back to a deterministic linear probe, which
# guarantees termination even when the hash sequence keeps hitting used IDs.
MAX_HASH_ATTEMPTS = 1024


def is_valid_id(value: str) -> bool:
    return ID_RE.fullmatch(value) is not None


def candidate(seed: str, attempt: int) -> str:
    return shake_128(f"{seed}\0{attempt}".encode()).hexdigest(2)


def allocate(seed: str, used: Collection[str]) -> str:
    """Return the first ID derived from ``seed`` that is not in ``used``.

    ``used`` must contain every reserved ID and every ID currently in source.
    """
    exhausted = "all 65,536 task IDs are used or reserved"
    if len(used) >= ID_SPACE:
        raise IdExhaustedError(exhausted)
    for attempt in range(MAX_HASH_ATTEMPTS):
        proposal = candidate(seed, attempt)
        if proposal not in used:
            return proposal
    start = int(candidate(seed, MAX_HASH_ATTEMPTS), 16)
    for offset in range(ID_SPACE):
        proposal = f"{(start + offset) % ID_SPACE:04x}"
        if proposal not in used:
            return proposal
    raise IdExhaustedError(exhausted)  # no cov
