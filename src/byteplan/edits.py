# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
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


def physical_lines(text: str) -> list[str]:
    """Lines as Python's tokenizer and ``ast`` number them, with their endings.

    Unlike ``str.splitlines`` this doesn't split on form feeds, ``\\x1c`` or
    ``\\u2028``, which Python doesn't treat as line breaks.
    """
    offsets = line_offsets(text)
    lines = [text[start:end] for start, end in zip(offsets, [*offsets[1:], len(text)], strict=True)]
    return lines[:-1] if lines and lines[-1] == "" else lines


_CODING_RE = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+")


def header_end(lines: Sequence[str]) -> int:
    """How many leading lines must stay first: a shebang, and an encoding cookie (which Python
    only honours on line 1 or 2). Inserted code goes after them."""
    end = 1 if lines and lines[0].startswith("#!") else 0
    for number in (1, 2):
        if number <= len(lines) and _CODING_RE.match(lines[number - 1]):
            end = number
    return end


def char_col(line: str, byte_col: int) -> int:
    """Convert an ``ast`` column (UTF-8 bytes) to a character index into ``line``."""
    return len(line.encode("utf-8")[:byte_col].decode("utf-8", errors="ignore"))


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


class _DropDecoratorIds(ast.NodeTransformer):
    """Remove ``id=`` keywords from decorator calls: the one AST change annotation may make."""

    def _strip(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> ast.AST:
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                decorator.keywords = [k for k in decorator.keywords if k.arg != "id"]
        self.generic_visit(node)
        return node

    # ast.NodeTransformer dispatches on these exact names.
    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _strip  # noqa: N815


def _dump(path: str, text: str) -> str:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = _DropDecoratorIds().visit(ast.parse(text, filename=path))
            return ast.dump(tree, include_attributes=False)
    except (SyntaxError, ValueError) as exc:
        msg = f"{path}: edited source no longer parses ({exc}); nothing was written"
        raise EditError(msg) from exc


def ensure_equivalent(path: str, before: str, after: str) -> None:
    """Refuse an edit that changes the program's AST, other than adding decorator ``id=`` keywords.

    (That the added keyword is exactly the allocated ID is checked by re-scanning.)
    """
    if _dump(path, before) != _dump(path, after):
        msg = f"{path}: edit would change program structure; nothing was written"
        raise EditError(msg)


def replace_at(text: str, line: int, col: int, old: str, new: str) -> str:
    """Replace ``old`` at exactly (line, col), refusing if the text there differs."""
    offsets = line_offsets(text)
    if not 1 <= line <= len(offsets):
        msg = f"edit at line {line} is outside the file"
        raise EditError(msg)
    start = offsets[line - 1] + col
    if text[start : start + len(old)] != old:
        msg = f"expected {old!r} at {line}:{col}; the file changed"
        raise EditError(msg)
    return text[:start] + new + text[start + len(old) :]
