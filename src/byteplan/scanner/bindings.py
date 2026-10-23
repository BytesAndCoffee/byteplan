# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Bindings in a Python scope, without descending into nested namespaces."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


def module_statements(body: Sequence[ast.stmt]) -> Iterator[ast.stmt]:
    """Statements that execute in the module namespace, including control-flow suites."""
    for stmt in body:
        yield stmt
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        for child in ast.iter_child_nodes(stmt):
            if isinstance(child, ast.stmt):
                yield from module_statements([child])
            elif isinstance(child, ast.ExceptHandler | ast.match_case):
                yield from module_statements(child.body)


class _Bindings(ast.NodeVisitor):
    def __init__(self, statement: ast.stmt) -> None:
        self.statement = statement
        self.names: set[str] = set()

    def visit(self, node: ast.AST) -> None:
        # Child statements are visited separately by module_statements().
        if isinstance(node, ast.stmt) and node is not self.statement:
            return
        super().visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store | ast.Del):
            self.names.add(node.id)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Store | ast.Del):
            root: ast.expr = node.value
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                self.names.add(root.id)  # e.g. replacing runtime.todo also invalidates the import
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        self.names.update(alias.asname or alias.name.split(".")[0] for alias in node.names)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.names.update(alias.asname or alias.name for alias in node.names)

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.names.add(node.name)
        self.visit(node.args)
        for expression in [*node.decorator_list, node.returns]:
            if expression is not None:
                self.visit(expression)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.visit_FunctionDef(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.names.add(node.name)
        for expression in [*node.decorator_list, *node.bases, *(k.value for k in node.keywords)]:
            self.visit(expression)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for expression in [*node.args.defaults, *node.args.kw_defaults]:
            if expression is not None:
                self.visit(expression)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        # Comprehension iteration targets belong to their own namespace; walruses in
        # their expressions bind in the containing scope and are visited normally.
        self.visit(node.iter)
        for condition in node.ifs:
            self.visit(condition)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs | ast.MatchStar) -> None:
        if node.name:
            self.names.add(node.name)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        self.visit_MatchAs(node)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest:
            self.names.add(node.rest)
        self.generic_visit(node)


def bound_names(statement: ast.stmt) -> set[str]:
    """Names a statement may bind, delete, or mutate in its containing namespace."""
    visitor = _Bindings(statement)
    visitor.visit(statement)
    return visitor.names
