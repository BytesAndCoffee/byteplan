# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Static detection of unfinished implementations.

A declaration is a stub when, after an optional docstring, its body is:

* ``pass`` and/or ``...`` only (or nothing but the docstring), for functions,
  methods and classes; or
* a single ``raise NotImplementedError`` / ``raise NotImplementedError(...)``,
  for functions and methods.

Never stubs: ``@abstractmethod`` (and any ``abstract*`` decorator), ``@overload``,
``Protocol`` classes and their methods, empty classes whose bases mark them as
intentionally empty (exceptions, enums, ``TypedDict``, ``NamedTuple``), and any
declaration with ``# byteplan: ignore`` on its decorator or header lines. Each
heuristic can be disabled in ``[tool.byteplan.detect]``.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

    from byteplan.config import DetectConfig
    from byteplan.scanner.symbols import Declaration

_INTENTIONALLY_EMPTY_BASES = frozenset({
    "Exception", "BaseException", "Enum", "IntEnum", "StrEnum", "Flag", "IntFlag", "TypedDict", "NamedTuple",
})  # fmt: skip
_EXCEPTION_NAME = re.compile(r"(Error|Exception|Warning)$")


@dataclass(frozen=True)
class Stub:
    decl: Declaration
    reason: str  # "empty", "pass", "ellipsis", "not_implemented", "empty_class"


def dotted_name(node: ast.expr) -> str | None:
    """``a.b.c`` for Name/Attribute chains; the callee's name for calls; else None."""
    if isinstance(node, ast.Call):
        return dotted_name(node.func)
    if isinstance(node, ast.Subscript):
        return dotted_name(node.value)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = dotted_name(node.value)
        return None if base is None else f"{base}.{node.attr}"
    return None


def _last(node: ast.expr) -> str | None:
    name = dotted_name(node)
    return None if name is None else name.rsplit(".", 1)[-1]


def _effective_body(body: list[ast.stmt]) -> list[ast.stmt]:
    first = body[0] if body else None
    if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
        return body[1:]
    return body


def _is_pass(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Pass)


def _is_ellipsis(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis


def _is_not_implemented(stmt: ast.stmt) -> bool:
    return isinstance(stmt, ast.Raise) and stmt.exc is not None and _last(stmt.exc) == "NotImplementedError"


def _trivial_reason(body: list[ast.stmt], detect: DetectConfig) -> str | None:
    effective = _effective_body(body)
    if not effective:
        return "empty" if detect.pass_stubs or detect.ellipsis_stubs else None
    if all(_is_pass(s) or _is_ellipsis(s) for s in effective):
        has_pass = any(_is_pass(s) for s in effective)
        has_ellipsis = any(_is_ellipsis(s) for s in effective)
        if (has_pass and not detect.pass_stubs) or (has_ellipsis and not detect.ellipsis_stubs):
            return None
        return "pass" if has_pass else "ellipsis"
    return None


def _excluded_by_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> bool:
    for decorator in node.decorator_list:
        name = _last(decorator)
        if name is not None and (name.startswith("abstract") or name == "overload"):
            return True
    return False


def _is_protocol(node: ast.ClassDef) -> bool:
    return any(_last(base) == "Protocol" for base in node.bases)


def _intentionally_empty(node: ast.ClassDef) -> bool:
    for base in node.bases:
        name = _last(base)
        if name is not None and (name in _INTENTIONALLY_EMPTY_BASES or _EXCEPTION_NAME.search(name)):
            return True
    return False


def stub_reason(decl: Declaration, detect: DetectConfig) -> str | None:
    """Why ``decl`` is a stub, or None. Ignores suppression comments (see ``find_stubs``)."""
    node = decl.node
    if _excluded_by_decorator(node):
        return None
    if isinstance(node, ast.ClassDef):
        if not detect.empty_classes or _is_protocol(node) or _intentionally_empty(node):
            return None
        return "empty_class" if _trivial_reason(node.body, detect) else None
    if decl.parent is not None and _is_protocol(decl.parent):
        return None
    effective = _effective_body(node.body)
    if len(effective) == 1 and _is_not_implemented(effective[0]):
        return "not_implemented" if detect.not_implemented_stubs else None
    return _trivial_reason(node.body, detect)


def find_stubs(
    decls: list[Declaration],
    detect: DetectConfig,
    ignore_lines: Collection[int],
    intentional: Callable[[Declaration], bool] | None = None,
) -> list[Stub]:
    """Stubs among ``decls``, minus suppressed ones and (when given) intentional ones."""
    stubs = []
    for decl in decls:
        if any(decl.start <= line <= decl.header_end for line in ignore_lines):
            continue
        if intentional is not None and intentional(decl):
            continue
        reason = stub_reason(decl, detect)
        if reason is not None:
            stubs.append(Stub(decl, reason))
    return stubs
