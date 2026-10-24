# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Persistent hexadecimal task identities and user-facing abbreviations.

SHAKE128 is used for convenient deterministic output, not for any security
property. IDs are unique only within one project's reservation ledger.
"""

from __future__ import annotations

import re
from hashlib import shake_128
from typing import TYPE_CHECKING

from byteplan.errors import ConfigError, IdExhaustedError

if TYPE_CHECKING:
    from collections.abc import Collection

LEGACY_ID_LENGTH = 4
ID_RE = re.compile(rf"[0-9a-f]{{{LEGACY_ID_LENGTH},}}")
NEW_ID_LENGTH = 6
ID_SPACE = 16**NEW_ID_LENGTH
MAX_PREFIX_MATCHES = 20
# Hash retries before falling back to a deterministic linear probe, which
# guarantees termination even when the hash sequence keeps hitting used IDs.
MAX_HASH_ATTEMPTS = 1024


def is_valid_id(value: str) -> bool:
    return ID_RE.fullmatch(value) is not None


def candidate(seed: str, attempt: int) -> str:
    return shake_128(f"{seed}\0{attempt}".encode()).hexdigest(NEW_ID_LENGTH // 2)


def allocate(seed: str, used: Collection[str]) -> str:
    """Return the first ID derived from ``seed`` that is not in ``used``.

    ``used`` must contain every reserved ID and every ID currently in source.
    """
    exhausted = f"all {ID_SPACE:,} newly allocated task IDs are used or reserved"
    if len(used) >= ID_SPACE and sum(len(value) == NEW_ID_LENGTH for value in used) >= ID_SPACE:
        raise IdExhaustedError(exhausted)
    for attempt in range(MAX_HASH_ATTEMPTS):
        proposal = candidate(seed, attempt)
        if proposal not in used:
            return proposal
    start = int(candidate(seed, MAX_HASH_ATTEMPTS), 16)
    for offset in range(ID_SPACE):
        proposal = f"{(start + offset) % ID_SPACE:0{NEW_ID_LENGTH}x}"
        if proposal not in used:
            return proposal
    raise IdExhaustedError(exhausted)  # no cov


def resolve_id(query: str, identities: Collection[str]) -> str | None:
    """Resolve a UI abbreviation; persisted references must use exact dictionary lookup."""
    query = query.lower()
    if query in identities:
        return query
    if not query or re.fullmatch(r"[0-9a-f]+", query) is None:
        return None
    matches = sorted(value for value in identities if value.startswith(query))
    if len(matches) > 1:
        candidates = ", ".join(matches[:MAX_PREFIX_MATCHES])
        if len(matches) > MAX_PREFIX_MATCHES:
            candidates += f", … ({len(matches)} matches)"
        msg = f"ambiguous task prefix {query!r}: {candidates}; use an exact task ID or a longer unique prefix"
        raise ConfigError(msg)
    return matches[0] if matches else None
