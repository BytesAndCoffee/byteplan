# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Project-wide class index, so stub detection can recognize intentional trivial methods.

Two common patterns look like stubs but aren't unfinished work:

* **Interface by convention:** a base class declares ``def dispatch(self): raise
  NotImplementedError`` and subclasses (at any depth) implement it.
* **Deliberate no-op override:** a subclass overrides an inherited method with
  ``pass`` (a headless runner ignoring ``refresh_sidebar``, say).

A trivial method is therefore *intentional* when a project subclass of its class
defines a method of the same name, or when one of its class's project ancestors
does. Classes are matched by simple name across the whole scope, which is a
heuristic: two unrelated classes sharing a name can mask a stub, never invent
one. Disable with ``[tool.byteplan.detect] respect_overrides = false``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

from byteplan.models import AttachmentKind
from byteplan.scanner.stubs import dotted_name

if TYPE_CHECKING:
    from collections.abc import Iterable

    from byteplan.scanner.symbols import Declaration


@dataclass(frozen=True)
class ClassInfo:
    name: str
    bases: tuple[str, ...]  # simple names (last dotted component)
    methods: frozenset[str]


def classes_in(tree: ast.Module) -> list[ClassInfo]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = tuple(name.rsplit(".", 1)[-1] for b in node.bases if (name := dotted_name(b)) is not None)
            methods = frozenset(
                stmt.name for stmt in node.body if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef)
            )
            found.append(ClassInfo(node.name, bases, methods))
    return found


class ClassHierarchy:
    def __init__(self, classes: Iterable[ClassInfo]) -> None:
        self._by_name: dict[str, list[ClassInfo]] = {}
        self._children: dict[str, set[str]] = {}
        self._parents: dict[str, set[str]] = {}
        for info in classes:
            self._by_name.setdefault(info.name, []).append(info)
            self._parents.setdefault(info.name, set()).update(info.bases)
            for base in info.bases:
                self._children.setdefault(base, set()).add(info.name)
        self._closures: dict[tuple[str, bool], set[str]] = {}

    def _closure(self, start: str, *, down: bool) -> set[str]:
        key = (start, down)
        if key not in self._closures:
            step = self._children if down else self._parents
            seen: set[str] = set()
            pending = list(step.get(start, ()))
            while pending:
                name = pending.pop()
                if name not in seen:
                    seen.add(name)
                    pending.extend(step.get(name, ()))
            self._closures[key] = seen
        return self._closures[key]

    def defines(self, class_names: Iterable[str], method: str) -> bool:
        return any(method in info.methods for name in class_names for info in self._by_name.get(name, ()))

    def intentional(self, decl: Declaration) -> bool:
        """Whether a trivial method is an interface declaration or a deliberate override."""
        if decl.kind is not AttachmentKind.METHOD or decl.parent is None:
            return False
        owner, method = decl.parent.name, decl.node.name
        return self.defines(self._closure(owner, down=True), method) or self.defines(
            self._closure(owner, down=False), method
        )
