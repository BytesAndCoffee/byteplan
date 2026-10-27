# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""byteplan and byteplan-runtime are released together, with the same version."""

from __future__ import annotations

import re
from pathlib import Path

from byteplan.__about__ import __version__

RUNTIME_INIT = Path(__file__).resolve().parents[1] / "byteplan-runtime/src/byteplan_runtime/__init__.py"


def test_runtime_is_versioned_in_lockstep() -> None:
    # Read the source rather than importing: the installed byteplan_runtime may be another release.
    match = re.search(r'^__version__ = "([^"]+)"', RUNTIME_INIT.read_text(encoding="utf-8"), re.MULTILINE)
    assert match is not None
    assert match.group(1) == __version__
