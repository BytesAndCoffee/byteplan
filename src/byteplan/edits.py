# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""In-memory source edits with structural validation.

Edits are character insertions at (line, column) positions taken from
``tokenize``/``ast``, never whole-file regex replacement. Every edited text must
re-parse to the same AST as the original (for comment-only edits, exactly the
same), or the edit is refused before anything is written.
"""

from __future__ import annotations

import ast
import re
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING

from byteplan.errors import EditError

if TYPE_CHECKING:
    from collections.abc import Sequence

_NEWLINE_RE = re.compile(r"\r\n|\n|\r")


@dataclass(frozen=True, order=True)
class Insertion:
    line: int  # 1-based
    col: int  # 0-based, in characters
    text: str


def line_offsets(text: str) -> list[int]:
    """Character offset of the start of each physical line (index 0 is line 1).

    Lines are split the way ``tokenize`` sees them: on ``\\r\\n``, ``\\n`` and ``\\r``.
    """
    return [0, *(match.end() for match in _NEWLINE_RE.finditer(text))]


def apply_insertions(text: str, insertions: Sequence[Insertion]) -> str:
    offsets = line_offsets(text)
    positions: list[tuple[int, str]] = []
    for insertion in insertions:
        if not 1 <= insertion.line <= len(offsets):
            msg = f"edit at line {insertion.line} is outside the file"
            raise EditError(msg)
        start = offsets[insertion.line - 1]
        end = offsets[insertion.line] if insertion.line < len(offsets) else len(text)
        if not 0 <= insertion.col <= end - start:
            msg = f"edit at {insertion.line}:{insertion.col} is outside the line"
            raise EditError(msg)
        positions.append((start + insertion.col, insertion.text))
    if len({offset for offset, _ in positions}) != len(positions):
        msg = "two edits target the same position"
        raise EditError(msg)
    for offset, inserted in sorted(positions, reverse=True):
        text = text[:offset] + inserted + text[offset:]
    return text


def _dump(path: str, text: str) -> str:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.dump(ast.parse(text, filename=path), include_attributes=False)
    except (SyntaxError, ValueError) as exc:
        msg = f"{path}: edited source no longer parses ({exc}); nothing was written"
        raise EditError(msg) from exc


def ensure_equivalent(path: str, before: str, after: str) -> None:
    """Refuse an edit that changes the program's AST."""
    if _dump(path, before) != _dump(path, after):
        msg = f"{path}: edit would change program structure; nothing was written"
        raise EditError(msg)
