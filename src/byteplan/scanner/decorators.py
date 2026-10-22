# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Static discovery of ``@todo(...)`` and ``@verifies(...)`` decorators.

Nothing is imported or executed. A decorator counts only if its name provably
refers to ``todo``/``verifies`` from one of the configured runtime modules
(``byteplan_runtime`` by default), through a module-level import:

* ``from byteplan_runtime import todo`` / ``... import todo as t`` -> ``@todo`` / ``@t``
* ``import byteplan_runtime as br`` -> ``@br.todo``; ``import pkg.shim`` -> ``@pkg.shim.todo``

Imports inside module-level ``if``/``try`` blocks count. A name that is also
bound some other way at module level (a ``def``, an assignment, a different
import) is ambiguous, and a ``*`` import from a runtime module makes ``todo`` and
``verifies`` ambiguous; decorators using an ambiguous name are reported as
``unresolved_todo_decorator`` and not tracked. An unrelated function that just
happens to be called ``todo`` is ignored.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from byteplan.diagnostics import Code, Diagnostic, Location, Severity
from byteplan.edits import char_col, physical_lines
from byteplan.ids import is_valid_id
from byteplan.models import Annotation, IdSlot, Origin, Representation
from byteplan.scanner.stubs import dotted_name

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence

    from byteplan.scanner.source import SourceFile
    from byteplan.scanner.symbols import Declaration

TODO_KEYWORDS = frozenset({"id", "kind", "description", "test", "tests"})
_MARKERS = ("todo", "verifies")


@dataclass
class RuntimeNames:
    """How the runtime's ``todo``/``verifies`` are reachable in one module."""

    direct: dict[str, str] = field(default_factory=dict)  # local name -> "todo" | "verifies"
    modules: dict[str, str] = field(default_factory=dict)  # local dotted prefix -> runtime module
    ambiguous: set[str] = field(default_factory=set)

    def resolve(self, name: str) -> str | None:
        """``"todo"``, ``"verifies"``, ``"ambiguous"`` or None for a decorator's dotted name."""
        if name in self.ambiguous:
            return "ambiguous"
        if name in self.direct:
            return self.direct[name]
        prefix, _, attr = name.rpartition(".")
        if prefix and attr in _MARKERS and prefix in self.modules:
            return "ambiguous" if prefix.split(".")[0] in self.ambiguous else attr
        return None


def _module_statements(body: Sequence[ast.stmt]) -> Iterator[ast.stmt]:
    for stmt in body:
        yield stmt
        if isinstance(stmt, ast.If):
            yield from _module_statements(stmt.body)
            yield from _module_statements(stmt.orelse)
        elif isinstance(stmt, ast.Try | ast.TryStar):
            yield from _module_statements(stmt.body)
            for handler in stmt.handlers:
                yield from _module_statements(handler.body)
            yield from _module_statements(stmt.orelse)
            yield from _module_statements(stmt.finalbody)


def _bound_names(stmt: ast.stmt) -> list[str]:
    if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return [stmt.name]
    targets: list[ast.expr] = []
    if isinstance(stmt, ast.Assign):
        targets = stmt.targets
    elif isinstance(stmt, ast.AnnAssign | ast.AugAssign):
        targets = [stmt.target]
    names: list[str] = []
    for target in targets:
        names.extend(node.id for node in ast.walk(target) if isinstance(node, ast.Name))
    return names


def resolve_runtime_names(tree: ast.Module, runtime_modules: Sequence[str]) -> RuntimeNames:
    names = RuntimeNames()
    runtime = set(runtime_modules)
    origins: dict[str, set[str]] = {}  # local name -> distinct sources that bind it

    def bind(local: str, origin: str) -> None:
        origins.setdefault(local, set()).add(origin)

    star_from_runtime = False
    for stmt in _module_statements(tree.body):
        if isinstance(stmt, ast.ImportFrom):
            from_runtime = stmt.level == 0 and stmt.module in runtime
            for alias in stmt.names:
                if alias.name == "*":
                    star_from_runtime = star_from_runtime or from_runtime
                    continue
                local = alias.asname or alias.name
                if from_runtime and alias.name in _MARKERS:
                    names.direct[local] = alias.name
                    bind(local, f"runtime:{alias.name}")
                else:
                    bind(local, f"import:{stmt.module}:{alias.name}")
        elif isinstance(stmt, ast.Import):
            for alias in stmt.names:
                if alias.asname:
                    local, target = alias.asname, alias.name
                else:
                    local = target = alias.name  # `import a.b` makes `a.b.x` reachable
                if target in runtime:
                    names.modules[local] = target
                    bind(local.split(".")[0], f"module:{target}" if alias.asname else f"package:{target.split('.')[0]}")
                else:
                    bind(
                        local.split(".")[0],
                        f"package:{alias.name.split('.')[0]}" if not alias.asname else f"module:{target}",
                    )
        else:
            for local in _bound_names(stmt):
                bind(local, f"other:{stmt.lineno}")

    for local, sources in origins.items():
        if len(sources) > 1:
            names.ambiguous.add(local)
    if star_from_runtime:
        names.ambiguous.update(_MARKERS)
    return names


_Scope = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef


def _enclosing_scopes(tree: ast.Module) -> dict[ast.AST, list[_Scope]]:
    """For each def/class, the scopes Python searches when evaluating its decorators.

    Decorators run in the immediately enclosing scope. From there, lookup goes
    through enclosing *function* scopes only: a class namespace is visible to
    code directly in the class body, never to code inside its methods.
    """
    found: dict[ast.AST, list[_Scope]] = {}

    def visit(node: ast.AST, stack: list[_Scope]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, _Scope):
                found[child] = [
                    scope
                    for depth, scope in enumerate(stack)
                    if not isinstance(scope, ast.ClassDef) or depth == len(stack) - 1
                ]
                visit(child, [*stack, child])
            else:
                visit(child, stack)

    visit(tree, [])
    return found


def _binds(scope: _Scope, name: str) -> bool:
    """Whether ``name`` is bound anywhere directly in ``scope`` (conservatively)."""
    if not isinstance(scope, ast.ClassDef):
        args = scope.args
        params = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
        if any(param is not None and param.arg == name for param in params):
            return True
    pending: list[ast.AST] = list(scope.body)
    while pending:
        node = pending.pop()
        if isinstance(node, _Scope | ast.Lambda):
            if not isinstance(node, ast.Lambda) and node.name == name:
                return True
            continue  # its body is its own scope
        if isinstance(node, ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp):
            # Iteration targets are local to the comprehension. Only the first
            # iterable is evaluated in this scope, and a walrus (:=) inside the
            # comprehension binds here too.
            if any(
                isinstance(sub, ast.NamedExpr) and isinstance(sub.target, ast.Name) and sub.target.id == name
                for sub in ast.walk(node)
            ):
                return True
            pending.append(node.generators[0].iter)
            continue
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del) and node.id == name:
            return True
        if isinstance(node, ast.Import | ast.ImportFrom):
            if any((alias.asname or alias.name.split(".")[0]) == name for alias in node.names):
                return True
        elif isinstance(node, ast.Global | ast.Nonlocal):
            if name in node.names:
                return True
        elif isinstance(node, ast.ExceptHandler | ast.MatchAs | ast.MatchStar):
            if node.name == name:
                return True
        elif isinstance(node, ast.MatchMapping) and node.rest == name:
            return True
        pending.extend(ast.iter_child_nodes(node))
    return False


@dataclass(frozen=True)
class VerifiesLink:
    task_ids: tuple[str, ...]
    node_id: str  # pytest node ID: path::Class::test
    path: str
    line: int


@dataclass
class DecoratorScan:
    annotations: list[Annotation] = field(default_factory=list)
    links: list[VerifiesLink] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


def _literal_str(node: ast.expr) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _id_slot(source: SourceFile, call: ast.Call, lines: list[str]) -> IdSlot | None:
    """Where ``id="abcd"`` goes: right after the last argument, if that's unambiguous."""
    arguments: list[ast.expr | ast.keyword] = [*call.args, *call.keywords]
    if not arguments:
        return None
    last = max(arguments, key=lambda node: (node.end_lineno or 0, node.end_col_offset or 0))
    if last.end_lineno is None or last.end_col_offset is None or call.end_lineno is None:
        return None
    # ast columns are UTF-8 byte offsets; edits use character indices.
    end_line = last.end_lineno
    end_col = char_col(lines[end_line - 1], last.end_col_offset)
    # Between the last argument and the call's own ")" there may only be
    # whitespace, comments and one trailing comma. Anything else (e.g. the
    # argument was wrapped in parentheses) means inserting there is unsafe.
    close_line = call.end_lineno
    close_col = char_col(lines[close_line - 1], call.end_col_offset or 0) - 1
    between = []
    for line_no in range(end_line, close_line + 1):
        text = lines[line_no - 1].rstrip("\r\n")
        start_col = end_col if line_no == end_line else 0
        stop_col = close_col if line_no == close_line else len(text)
        between.append(text[start_col:stop_col].split("#", 1)[0])
    if "".join(between).replace(" ", "").replace("\t", "").replace("\\", "") not in {"", ","}:
        return None

    multiline = (call.end_lineno or call.lineno) > call.lineno
    last_start_line = lines[last.lineno - 1]
    indent = last_start_line[: len(last_start_line) - len(last_start_line.lstrip())]
    starts_its_line = last_start_line[: char_col(last_start_line, last.col_offset)].strip() == ""
    if multiline and starts_its_line and last.lineno == end_line:
        return IdSlot(end_line, end_col, f',{source.newline}{indent}id="{{id}}"')
    return IdSlot(end_line, end_col, ', id="{id}"')


def scan_decorators(
    source: SourceFile,
    tree: ast.Module,
    decls: Sequence[Declaration],
    runtime_modules: Sequence[str],
    tags: Sequence[str],
) -> DecoratorScan:
    names = resolve_runtime_names(tree, runtime_modules)
    result = DecoratorScan()
    if not names.direct and not names.modules and not names.ambiguous:
        return result
    lines = physical_lines(source.text)
    scopes = _enclosing_scopes(tree)
    canonical = {tag.upper(): tag for tag in tags}

    def report(code: Code, severity: Severity, message: str, line: int, hint: str | None = None) -> None:
        result.diagnostics.append(
            Diagnostic(code, severity, message, locations=(Location(source.path, line),), hint=hint)
        )

    for decl in decls:
        for decorator in decl.node.decorator_list:
            name = dotted_name(decorator)
            marker = names.resolve(name) if name else None
            if marker is None:
                continue
            base = (name or "").split(".")[0]
            if any(_binds(scope, base) for scope in scopes.get(decl.node, ())):
                marker = "ambiguous"  # shadowed by a local, parameter or class attribute
            line = decorator.lineno
            if marker == "ambiguous":
                report(
                    Code.UNRESOLVED_TODO_DECORATOR,
                    Severity.WARNING,
                    f"@{name} on {decl.qualname} may not be byteplan_runtime's (the name is rebound or shadowed); not tracked",
                    line,
                    "import it once, e.g. `from byteplan_runtime import todo`, and don't rebind the name",
                )
                continue
            if not isinstance(decorator, ast.Call):
                report(Code.INVALID_TODO_DECORATOR, Severity.ERROR, f"@{name} must be called, e.g. @{name}(...)", line)
                continue
            if marker == "verifies":
                _verifies(source, decl, decorator, name or "verifies", result, report)
            else:
                annotation = _todo(source, decl, decorator, name or "todo", lines, canonical, report)
                if annotation is not None:
                    result.annotations.append(annotation)
    return result


def _todo(
    source: SourceFile,
    decl: Declaration,
    call: ast.Call,
    name: str,
    lines: list[str],
    canonical: dict[str, str],
    report: Callable[..., None],
) -> Annotation | None:
    line = call.lineno
    if len(call.args) != 1 or any(isinstance(arg, ast.Starred) for arg in call.args):
        report(Code.INVALID_TODO_DECORATOR, Severity.ERROR, f"@{name}(...) takes exactly one positional title", line)
        return None
    values: dict[str, ast.expr] = {}
    unpacked = False
    for keyword in call.keywords:
        if keyword.arg is None:
            unpacked = True
            continue
        if keyword.arg not in TODO_KEYWORDS:
            report(
                Code.INVALID_TODO_DECORATOR,
                Severity.ERROR,
                f"@{name}() has no keyword {keyword.arg!r} (allowed: {', '.join(sorted(TODO_KEYWORDS))})",
                line,
                "this raises TypeError when the module is imported",
            )
            return None
        values[keyword.arg] = keyword.value

    if unpacked and "id" not in values:
        # The mapping might already supply id=; adding one could make the module
        # fail to import ("got multiple values for keyword argument 'id'").
        report(
            Code.DYNAMIC_TODO_ARGUMENT,
            Severity.WARNING,
            f"@{name}(..., **...) on {decl.qualname} can't be read statically; not tracked",
            line,
            'write id="..." explicitly (or drop the ** unpacking) to track it',
        )
        return None
    task_id: str | None = None
    if "id" in values:
        raw_id = _literal_str(values["id"])
        if raw_id is None:
            report(
                Code.DYNAMIC_TODO_ARGUMENT,
                Severity.WARNING,
                f"@{name}(id=...) on {decl.qualname} is not a string literal; not tracked",
                line,
            )
            return None
        if not is_valid_id(raw_id):
            report(
                Code.MALFORMED_ID,
                Severity.WARNING,
                f'id="{raw_id}" is not four lowercase hex digits; the task is not tracked',
                line,
                "remove id= to get a new ID on the next scan, or fix it to a registered ID",
            )
            return None
        task_id = raw_id

    title = _literal_str(call.args[0])
    description = _literal_str(values["description"]) if "description" in values else ""
    kind_value = _literal_str(values["kind"]) if "kind" in values else "TODO"
    for field_name, value in (("title", title), ("description", description), ("kind", kind_value)):
        if value is None:
            report(
                Code.DYNAMIC_TODO_ARGUMENT,
                Severity.WARNING,
                f"@{name}() {field_name} on {decl.qualname} is not a string literal",
                line,
                "use literals; BytePlan never evaluates code",
            )
            if task_id is None:
                return None
    kind = canonical.get((kind_value or "TODO").upper())
    if kind is None:
        report(
            Code.INVALID_TODO_DECORATOR,
            Severity.WARNING,
            f"@{name}(kind={kind_value!r}) is not one of the configured tags ({', '.join(canonical.values())})",
            line,
        )
        kind = "TODO"
    if "test" in values and "tests" in values:
        report(
            Code.CONFLICTING_TEST_ARGUMENTS,
            Severity.ERROR,
            f"@{name}() on {decl.qualname} has both test= and tests=",
            line,
            "use tests=(...) for several tests",
        )

    id_slot = None
    if task_id is None:
        id_slot = _id_slot(source, call, lines)
        if id_slot is None:
            report(
                Code.DECORATOR_NEEDS_REVIEW,
                Severity.WARNING,
                f"can't safely add id= to @{name}(...) on {decl.qualname}; add it by hand or simplify the call",
                line,
            )
            return None
    return Annotation(
        path=source.path,
        line=line,
        end_line=call.end_lineno or line,
        col=char_col(lines[line - 1], call.col_offset) - 1,  # the "@"
        kind=kind,
        tag_text=name,
        task_id=task_id,
        title=title or "",
        description=description or "",
        symbol=decl.qualname,
        trailing=False,
        id_slot=id_slot,
        representation=Representation.DECORATOR,
        origin=Origin.DECORATOR,
        decl_line=decl.node.lineno,
        attachment_kind=decl.kind,
    )


def _verifies(
    source: SourceFile,
    decl: Declaration,
    call: ast.Call,
    name: str,
    result: DecoratorScan,
    report: Callable[..., None],
) -> None:
    ids = []
    for arg in call.args:
        value = _literal_str(arg)
        if value is None:
            report(
                Code.DYNAMIC_TODO_ARGUMENT,
                Severity.WARNING,
                f"@{name}() arguments must be string literals",
                call.lineno,
            )
        elif not is_valid_id(value):
            report(
                Code.MALFORMED_ID, Severity.WARNING, f'@{name}("{value}"): not a four-hex-digit task ID', call.lineno
            )
        else:
            ids.append(value)
    if ids and "<locals>" not in decl.qualname:
        node_id = "::".join([source.path, *decl.qualname.split(".")])
        result.links.append(VerifiesLink(tuple(ids), node_id, source.path, call.lineno))
