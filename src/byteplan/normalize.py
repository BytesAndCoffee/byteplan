# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""``byteplan sync``: structural rewrites to ``@todo(...)`` decorators (decorator mode).

Two rewrites, each opt-in under ``[tool.byteplan.annotations] mode = "decorator"``:

* ``convert_attached_comments``: a tagged comment block ending directly above a
  ``def``/``class`` (same column, no blank line) becomes ``@todo("title", id=...,
  kind=..., description=...)`` as the declaration's outermost decorator. Module-level,
  trailing, in-body, separated and untagged comments are left alone and reported as
  ``conversion_needs_review``.
* ``auto_decorate_stubs``: an unowned stub gets ``@todo("Implement <qualname>", id=...)``.

When the module has no usable ``todo`` binding, ``from <runtime> import todo`` is
inserted after the docstring and ``__future__`` imports. ``<runtime>`` is
``byteplan_runtime`` when ``byteplan-runtime`` is a declared dependency, otherwise a
configured shim module that exists in scope; with neither, nothing is converted.

Every rewritten file must parse to the same AST once BytePlan's ``todo`` decorators and
runtime imports are removed from both versions, and must re-scan to exactly the
expected annotations. Otherwise nothing is written.
"""

from __future__ import annotations

import ast
import json
import warnings
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from byteplan.diagnostics import Code, Diagnostic, Location, Severity
from byteplan.edits import header_end, line_offsets, physical_lines
from byteplan.errors import EditError
from byteplan.models import Annotation, AttachmentKind, Origin, Representation
from byteplan.scanner.decorators import resolve_runtime_names
from byteplan.scanner.stubs import dotted_name

if TYPE_CHECKING:
    from collections.abc import Sequence

    from byteplan.scanner.source import SourceFile
    from byteplan.scanner.symbols import Declaration, SymbolIndex

MAX_LINE = 88
_DECLARATIONS = frozenset({AttachmentKind.FUNCTION, AttachmentKind.METHOD, AttachmentKind.CLASS})


@dataclass(frozen=True)
class Rewrite:
    path: str
    line: int  # where the decorator ends up (before the edit)
    action: str  # "convert" | "decorate"
    task_id: str
    kind: str
    title: str
    symbol: str | None


@dataclass
class FilePlan:
    text: str
    rewrites: list[Rewrite] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    import_added: str | None = None  # the module imported, when an import was inserted


def literal(value: str) -> str:
    """A double-quoted Python string literal (JSON escapes are all valid Python escapes)."""
    return json.dumps(value, ensure_ascii=False)


def decorator_text(expr: str, title: str, task_id: str, kind: str, description: str, indent: str, newline: str) -> str:
    args = [literal(title), f'id="{task_id}"']
    if kind != "TODO":
        args.append(f"kind={literal(kind)}")
    unit = "\t" if "\t" in indent else "    "
    if "\n" in description:
        # One literal per source line, implicitly concatenated: still a single string constant.
        pieces = description.split("\n")
        literals = [literal(piece + "\n") for piece in pieces[:-1]] + ([literal(pieces[-1])] if pieces[-1] else [])
        inner = "".join(f"{indent}{unit}{unit}{piece}{newline}" for piece in literals)
        args.append(f"description=({newline}{inner}{indent}{unit})")
    elif description:
        args.append(f"description={literal(description)}")
    one_line = f"{indent}@{expr}({', '.join(args)})"
    if not description and len(one_line) <= MAX_LINE:
        return one_line + newline
    body = "".join(f"{indent}{unit}{arg},{newline}" for arg in args)
    return f"{indent}@{expr}({newline}{body}{indent}){newline}"


def _review(path: str, line: int, message: str, task_id: str | None = None, hint: str | None = None) -> Diagnostic:
    return Diagnostic(
        Code.CONVERSION_NEEDS_REVIEW,
        Severity.INFO,
        message,
        task_id=task_id,
        locations=(Location(path, line),),
        hint=hint,
    )


def _name_in_use(tree: ast.Module, name: str) -> bool:
    for node in ast.walk(tree):
        if (
            (isinstance(node, ast.Name) and node.id == name)
            or (isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) and node.name == name)
            or (isinstance(node, ast.arg) and node.arg == name)
            or (isinstance(node, ast.alias) and (node.asname or node.name.split(".")[0]) == name)
        ):
            return True
    return False


def _import_line(tree: ast.Module, lines: Sequence[str], before: int) -> int | None:
    """Where ``from <runtime> import todo`` can go.

    Preferably right after the module's leading import block, where first-party imports
    usually sit, as long as that's above ``before`` (the first line a new decorator touches).
    Otherwise the line of the first statement after the docstring and ``__future__`` imports
    (``len(lines) + 1`` for the end of the file). None if that isn't a clean statement start.
    """
    block_end = _leading_import_block_end(tree)
    if block_end is not None and block_end < before:
        return block_end + 1
    body = list(tree.body)
    index = 0
    first_stmt = body[0] if body else None
    if (
        isinstance(first_stmt, ast.Expr)
        and isinstance(first_stmt.value, ast.Constant)
        and isinstance(first_stmt.value.value, str)
    ):
        index = 1
    while index < len(body):
        stmt = body[index]
        if not (isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__"):
            break
        index += 1
    if index == len(body):
        previous = body[index - 1] if body else None
        if previous is not None and previous.end_lineno is not None and previous.end_lineno < len(lines):
            # Something (comments) follows the last statement; go right after the statement.
            return previous.end_lineno + 1
        return len(lines) + 1
    stmt = body[index]
    decorators: list[ast.expr] = getattr(stmt, "decorator_list", [])
    first: int = min([stmt.lineno, *(d.lineno for d in decorators)])
    if index > 0 and (body[index - 1].end_lineno or 0) >= first:
        return None  # shares a line with the previous statement (`import a; import b`)
    if stmt.col_offset != 0:
        return None
    if first > 1 and lines[first - 2].rstrip("\r\n").endswith("\\"):
        return None
    if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        # Don't separate a declaration from the comment block attached to it.
        floor = (body[index - 1].end_lineno or 0) + 1 if index > 0 else header_end(lines) + 1
        while first - 1 >= floor and lines[first - 2].lstrip().startswith("#"):
            first -= 1
    return first


def _leading_import_block_end(tree: ast.Module) -> int | None:
    """The last line of the run of top-level imports that follows the docstring, if each of
    them starts its own line at column 0 and nothing else shares the block's last line."""
    body = list(tree.body)
    index = (
        1 if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant) else 0
    )
    end: int | None = None
    while index < len(body) and isinstance(body[index], ast.Import | ast.ImportFrom):
        stmt = body[index]
        if stmt.col_offset != 0 or (end is not None and stmt.lineno <= end):
            return None
        end = stmt.end_lineno or stmt.lineno
        index += 1
    if end is None or (index < len(body) and body[index].lineno <= end):
        return None
    return end


@dataclass(frozen=True)
class _Binding:
    expr: str | None  # the decorator expression to use, e.g. "todo" or "br.todo"
    insert_from: str | None  # a module to import todo from first
    problem: str | None = None


def _unconditional_binding(tree: ast.Module, runtime_modules: Sequence[str], before: int) -> str | None:
    """A runtime ``todo`` bound by a plain module-level import that ends before line ``before``,
    so it has certainly run when the decorators do. Imports under ``if``/``try`` (such as
    ``if TYPE_CHECKING:``) or below a declaration don't qualify."""
    names = resolve_runtime_names(tree, runtime_modules)
    runtime = set(runtime_modules)
    for stmt in tree.body:
        if (stmt.end_lineno or stmt.lineno) >= before:
            break
        if isinstance(stmt, ast.ImportFrom) and stmt.level == 0 and stmt.module in runtime:
            for alias in stmt.names:
                local = alias.asname or alias.name
                if alias.name == "todo" and names.resolve(local) == "todo":
                    return local
        elif isinstance(stmt, ast.Import):
            for alias in stmt.names:
                local = alias.asname or alias.name
                if alias.name in runtime and names.resolve(f"{local}.todo") == "todo":
                    return f"{local}.todo"
    return None


def _binding(tree: ast.Module, runtime_modules: Sequence[str], available: str | None, before: int) -> _Binding:
    """How the new decorators reach ``todo``. ``before`` is the first line any of them goes on."""
    expr = _unconditional_binding(tree, runtime_modules, before)
    if expr is not None:
        return _Binding(expr, None)
    names = resolve_runtime_names(tree, runtime_modules)
    if names.direct or names.modules:
        return _Binding(
            None,
            None,
            "the module's runtime import is conditional (e.g. under `if TYPE_CHECKING:`) or comes after "
            "the declaration, so `todo` might not exist when the decorator runs; move the import to the top",
        )
    if available is None:
        return _Binding(
            None,
            None,
            "the runtime isn't available: add byteplan-runtime to [project].dependencies, "
            "or run `byteplan init --runtime-shim PATH` and list the shim in runtime_modules",
        )
    if _name_in_use(tree, "todo"):
        return _Binding(None, None, "the name `todo` is already used in this module")
    return _Binding("todo", available)


def plan_file(
    source: SourceFile,
    tree: ast.Module,
    tags: Sequence[Annotation],
    index: SymbolIndex,
    *,
    convert: bool,
    decorate_stubs: bool,
    stub_ids: dict[tuple[int, int], str],
    runtime_modules: Sequence[str],
    available: str | None,
    only: frozenset[str] | None,
) -> FilePlan:
    """The rewritten text for one file, the rewrites it contains, and review notes.

    ``stub_ids`` gives the allocated ID for each unowned stub to decorate, by its
    proposal's (line, col).
    """
    plan = FilePlan(source.text)
    lines = physical_lines(source.text)
    offsets = line_offsets(source.text)
    path = source.path
    candidates: list[tuple[Annotation, Declaration | None]] = []

    for tag in tags:
        if tag.representation is not Representation.COMMENT:
            continue
        if tag.origin is Origin.STUB and tag.task_id is None:
            if decorate_stubs and only is None and (tag.line, tag.col) in stub_ids:
                decl = next((d for d in index.all if d.start == tag.line and d.col == tag.col), None)
                candidates.append((tag, decl))
            continue
        if not convert or (only is not None and tag.task_id not in only):
            continue
        if tag.task_id is None:
            plan.diagnostics.append(
                _review(path, tag.line, f"{tag.kind}: {tag.title} has no ID yet", hint="run `byteplan scan` first")
            )
            continue
        decl = None if tag.trailing else index.attached(tag.end_line, tag.col)
        if decl is None or decl.kind not in _DECLARATIONS:
            where = (
                "trailing"
                if tag.trailing
                else (
                    "module-level"
                    if tag.attachment_kind is AttachmentKind.MODULE
                    else "not directly above a declaration"
                )
            )
            plan.diagnostics.append(
                _review(path, tag.line, f"task {tag.task_id} stays a comment: it's {where}", task_id=tag.task_id)
            )
            continue
        candidates.append((tag, decl))

    if not candidates:
        return plan
    first = min(tag.line if decl is None else min(tag.line, decl.start) for tag, decl in candidates)
    binding = _binding(tree, runtime_modules, available, first)
    if binding.expr is None:
        for tag, _ in candidates:
            plan.diagnostics.append(
                _review(path, tag.line, f"can't add @todo(...): {binding.problem}", task_id=tag.task_id)
            )
        return plan
    import_at = _import_line(tree, lines, first) if binding.insert_from else None
    if binding.insert_from and import_at is None:
        for tag, _ in candidates:
            plan.diagnostics.append(
                _review(path, tag.line, "can't safely insert the runtime import in this module", task_id=tag.task_id)
            )
        return plan

    spans: list[tuple[int, int, str]] = []
    for tag, decl in candidates:
        if decl is None:
            continue
        indent = lines[decl.start - 1][: decl.col]
        if tag.origin is Origin.STUB and tag.task_id is None:
            task_id = stub_ids[(tag.line, tag.col)]
            title = f"Implement {decl.qualname}"
            text = decorator_text(binding.expr, title, task_id, tag.kind, "", indent, source.newline)
            spans.append((offsets[decl.start - 1], offsets[decl.start - 1], text))
            plan.rewrites.append(Rewrite(path, decl.start, "decorate", task_id, tag.kind, title, decl.qualname))
        else:
            assert tag.task_id is not None  # noqa: S101 - filtered above
            text = decorator_text(
                binding.expr, tag.title, tag.task_id, tag.kind, tag.description, indent, source.newline
            )
            spans.append((offsets[tag.line - 1], offsets[decl.start - 1], text))
            plan.rewrites.append(Rewrite(path, tag.line, "convert", tag.task_id, tag.kind, tag.title, decl.qualname))
    if not spans:
        return plan
    if binding.insert_from and import_at is not None:
        statement = f"from {binding.insert_from} import todo{source.newline}"
        if import_at > len(lines):
            at = len(source.text)
            if source.text and not source.text.endswith(("\n", "\r")):
                statement = source.newline + statement
        else:
            at = offsets[import_at - 1]
        # A rewrite starting at the same place gets the import in front of its text, so
        # the import never lands between a decorator and its declaration.
        same = next((i for i, (start, _, _) in enumerate(spans) if start == at), None)
        if same is None:
            spans.append((at, at, statement))
        else:
            start, end, replacement = spans[same]
            spans[same] = (start, end, statement + replacement)
        plan.import_added = binding.insert_from

    text = source.text
    for start, end, replacement in sorted(spans, key=lambda s: (s[0], s[1]), reverse=True):
        text = text[:start] + replacement + text[end:]
    plan.text = text
    return plan


# Validation ----------------------------------------------------------------------------------


class _StripRuntime(ast.NodeTransformer):
    """Remove BytePlan's ``todo`` decorators and runtime imports of ``todo``. With ``everything``
    (release stripping), ``@verifies`` decorators and every runtime import go too."""

    def __init__(self, tree: ast.Module, runtime_modules: Sequence[str], *, everything: bool = False) -> None:
        self.names = resolve_runtime_names(tree, runtime_modules)
        self.runtime = set(runtime_modules)
        self.markers = {"todo", "verifies"} if everything else {"todo"}
        self.everything = everything

    def _is_todo(self, decorator: ast.expr) -> bool:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = dotted_name(target)
        return name is not None and self.names.resolve(name) in self.markers

    def visit_Import(self, node: ast.Import) -> ast.AST | None:
        if self.everything:
            node.names = [alias for alias in node.names if alias.name not in self.runtime]
            if not node.names:
                return None
        return node

    def _strip(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> ast.AST:
        node.decorator_list = [d for d in node.decorator_list if not self._is_todo(d)]
        self.generic_visit(node)
        return node

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _strip  # noqa: N815

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST | None:
        if node.level == 0 and node.module in self.runtime:
            node.names = [alias for alias in node.names if alias.name not in self.markers and not self.everything]
            if not node.names:
                return None
        return node


def _without_runtime(path: str, text: str, runtime_modules: Sequence[str], *, everything: bool = False) -> str:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = ast.parse(text, filename=path)
    except (SyntaxError, ValueError) as exc:
        msg = f"{path}: rewritten source no longer parses ({exc}); nothing was written"
        raise EditError(msg) from exc
    return ast.dump(_StripRuntime(tree, runtime_modules, everything=everything).visit(tree), include_attributes=False)


def ensure_equivalent_without_runtime(
    path: str, before: str, after: str, runtime_modules: Sequence[str], *, everything: bool = False
) -> None:
    """Refuse a rewrite that changes anything but BytePlan's own decorators and imports
    (``todo`` only, or with ``everything`` also ``verifies`` and every runtime import)."""
    if _without_runtime(path, before, runtime_modules, everything=everything) != _without_runtime(
        path, after, runtime_modules, everything=everything
    ):
        msg = f"{path}: rewrite would change program structure; nothing was written"
        raise EditError(msg)


def _identity(tag: Annotation) -> tuple[object, ...]:
    return (tag.task_id, tag.kind, tag.title, tag.description, tag.representation)


def ensure_round_trip(path: str, before: Sequence[Annotation], after: Sequence[Annotation], plan: FilePlan) -> None:
    """The rewritten file must scan to the same tasks, with the rewritten ones as decorators."""
    rewritten = {r.task_id: r for r in plan.rewrites}
    expected: Counter[tuple[object, ...]] = Counter()
    for tag in before:
        if tag.origin is Origin.STUB and tag.task_id is None:
            continue  # decorated stubs are counted from the rewrites
        if tag.task_id in rewritten:
            expected[(tag.task_id, tag.kind, tag.title, tag.description, Representation.DECORATOR)] += 1
        else:
            expected[_identity(tag)] += 1
    for rewrite in plan.rewrites:
        if rewrite.action == "decorate":
            expected[(rewrite.task_id, rewrite.kind, rewrite.title, "", Representation.DECORATOR)] += 1
    actual = Counter(_identity(tag) for tag in after if not (tag.origin is Origin.STUB and tag.task_id is None))
    if expected != actual:
        msg = f"{path}: rewrite did not round-trip through the scanner; nothing was written"
        raise EditError(msg)
