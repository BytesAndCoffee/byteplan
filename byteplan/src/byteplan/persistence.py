# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""The only module that writes project files.

Phase 1 provides single-file atomic replacement. The multi-file journal and
roll-forward recovery are built on top of it in Phase 2.
"""

from __future__ import annotations

import contextlib
import os
import stat
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def atomic_write_bytes(path: Path, data: bytes) -> bool:
    """Atomically replace ``path`` with ``data``, keeping its permissions.

    Returns ``False`` without touching the file when it already holds ``data``.
    """
    try:
        if path.read_bytes() == data:
            return False
        mode: int | None = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        mode = None

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
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise
    return True
