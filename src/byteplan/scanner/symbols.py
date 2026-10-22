# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Map source lines to qualified symbol names using ``ast``."""

from __future__ import annotations

import ast
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING

from byteplan.errors import SourceError
from byteplan.models import AttachmentKind

if TYPE_CHECKING:
    from byteplan.scanner.source import SourceFile

_Def = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


@dataclass(frozen=True)
class Declaration:
    qualname: str
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    # First line of the declaration, including decorators.
    start: int
    end: int
    col: int
    kind: AttachmentKind
    parent: ast.ClassDef | None = None  # the enclosing class, for methods

    @property
    def header_end(self) -> int:
        """Last line of the ``def``/``class`` header (before the body)."""
        first = self.node.body[0].lineno
        return first - 1 if first > self.node.lineno else self.node.lineno


def parse_module(source: SourceFile) -> ast.Module:
    try:
        with warnings.catch_warnings():
            # Invalid escape sequences etc. are the project's business, not ours.
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.parse(source.text, filename=source.path, type_comments=False)
    except SyntaxError as exc:
        where = f"line {exc.lineno}: " if exc.lineno else ""
        raise SourceError(source.path, f"syntax error, {where}{exc.msg}") from exc
    except ValueError as exc:  # e.g. null bytes
        raise SourceError(source.path, f"cannot parse: {exc}") from exc


def declarations(tree: ast.Module) -> list[Declaration]:
    """All function and class declarations, with Python ``__qualname__``-style names."""
    found: list[Declaration] = []

    def visit(node: ast.AST, prefix: str, owner: ast.ClassDef | None) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _Def):
                qualname = f"{prefix}{child.name}"
                start = min([child.lineno, *(d.lineno for d in child.decorator_list)])
                if isinstance(child, ast.ClassDef):
                    kind = AttachmentKind.CLASS
                else:
                    kind = AttachmentKind.METHOD if owner is not None else AttachmentKind.FUNCTION
                end = child.end_lineno or child.lineno
                found.append(Declaration(qualname, child, start, end, child.col_offset, kind, owner))
                if isinstance(child, ast.ClassDef):
                    visit(child, f"{qualname}.", child)
                else:
                    visit(child, f"{qualname}.<locals>.", None)
            else:
                visit(child, prefix, owner)

    visit(tree, "", None)
    return found


class SymbolIndex:
    def __init__(self, decls: list[Declaration]) -> None:
        self._decls = decls
        self._by_start: dict[tuple[int, int], Declaration] = {(d.start, d.col): d for d in decls}

    def attached(self, block_end: int, col: int) -> Declaration | None:
        """The declaration starting on the line right after a comment block at the same column."""
        return self._by_start.get((block_end + 1, col))

    def enclosing(self, line: int) -> Declaration | None:
        inner: Declaration | None = None
        for decl in self._decls:
            if decl.start <= line <= decl.end and (inner is None or decl.start >= inner.start):
                inner = decl
        return inner

    @property
    def all(self) -> list[Declaration]:
        return list(self._decls)

    def symbol_for(self, line: int, end_line: int, col: int) -> str | None:
        decl = self.attached(end_line, col) or self.enclosing(line)
        return decl.qualname if decl else None
