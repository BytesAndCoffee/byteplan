# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Strict JSON parsing for authoritative records and verification evidence."""

from __future__ import annotations

import json
import re
from typing import Any


def loads(text: str) -> Any:
    """Reject unresolved merge markers and duplicate keys rather than choosing a value."""
    if re.search(r"(?m)^(?:<{7}|={7}|>{7})(?: |$)", text):
        msg = "unresolved Git conflict markers; resolve the merge or restore the file from Git before retrying"
        raise ValueError(msg)

    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                msg = f"duplicate JSON key {key!r}; resolve competing records explicitly without discarding history or evidence"
                raise ValueError(msg)
            result[key] = value
        return result

    return json.loads(text, object_pairs_hook=unique)
