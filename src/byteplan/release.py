# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""``byteplan release`` / ``byteplan restore``: strip BytePlan's runtime decorators for a
release, in place, and put them back.

Stripping removes every recognized ``@todo(...)`` / ``@verifies(...)`` decorator and every
runtime import left unused by that, as whole lines, and records each one's exact original
text and position. Tagged ``# TODO[id]`` comments stay: they cost nothing at runtime. The
stripped file must parse to the same AST once BytePlan's decorators and imports are removed
from both versions, and must contain no remaining reference to a runtime module.

Restoring re-inserts the recorded lines:

* **Fast path.** If the file still hashes to what stripping wrote, every recorded block goes
  back at its recorded line, giving the pre-release file byte for byte.
* **Anchored path.** If the file changed since (a hotfix, a version bump), each decorator is
  placed by its declaration's qualname and its index in the decorator stack, and each import
  after its recorded anchor statement. A symbol that's gone or ambiguous is a conflict.

This module only plans text; the caller validates and writes through the journal.
"""

from __future__ import annotations

import ast
import re
import warnings
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from byteplan.cleanup import _exported
from byteplan.edits import header_end
from byteplan.errors import ByteplanError
from byteplan.scanner.decorators import _binds, _enclosing_scopes, resolve_runtime_names
from byteplan.scanner.stubs import dotted_name
from byteplan.scanner.symbols import declarations

if TYPE_CHECKING:
    from collections.abc import Sequence

    from byteplan.scanner.symbols import Declaration

UNTAGGED = "untagged_decorator"
NEEDS_REVIEW = "release_needs_review"
STRIPPED = "release_stripped"
CONFLICT = "restore_conflict"


class ReleaseError(ByteplanError):
    """The release or restore can't be done safely; nothing was written."""

    def __init__(self, code: str, problems: Sequence[str], hint: str | None = None) -> None:
        lines = "\n".join(f"  {problem}" for problem in problems)
        super().__init__(f"{code}: nothing was written\n{lines}" + (f"\n  hint: {hint}" if hint else ""))
        self.code = code
        self.problems = list(problems)
        self.hint = hint


@dataclass
class FileStrip:
    path: str
    text: str  # after stripping
    decorators: list[dict[str, Any]] = field(default_factory=list)
    imports: list[dict[str, Any]] = field(default_factory=list)


def _parse(path: str, text: str) -> ast.Module:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(text, filename=path)


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def _block(lines: Sequence[str], first: int, last: int) -> str:
    return "".join(lines[first - 1 : last])


# Stripping -------------------------------------------------------------------------------------


def strip_file(
    path: str, text: str, runtime_modules: Sequence[str], consumers: dict[str, set[str]] | None = None
) -> FileStrip | None:
    """Plan stripping one file, or None if it has nothing of BytePlan's. Raises ``ReleaseError``.

    ``consumers`` maps names other modules import from this one (``"*"`` for a star import)
    to the importing files: a runtime binding they use isn't removable.
    """
    consumers = consumers or {}
    tree = _parse(path, text)
    names = resolve_runtime_names(tree, runtime_modules)
    # FIXME[aedf]: Check every runtime import, not just decorator bindings, before skipping a file
    #   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4352850109
    #   `from byteplan_runtime import __version__` or an import inside a function survived a release.
    runtime = set(runtime_modules)
    package = package_of(path)
    if not names.direct and not names.modules and not names.ambiguous and not _runtime_imports(tree, runtime, package):
        return None
    lines = _lines(text)
    problems: list[str] = []
    decorators: list[dict[str, Any]] = []
    scopes = _enclosing_scopes(tree)
    for decl in declarations(tree):
        for index, decorator in enumerate(decl.node.decorator_list):
            # FIXME[34da]: Respect enclosing scopes before stripping a decorator
            #   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4352659114
            #   A class or function scope that rebinds `todo` makes the decorator not BytePlan's.
            name = dotted_name(decorator)
            marker = names.resolve(name) if name else None
            if marker is None:
                continue
            base = (name or "").split(".")[0]
            if any(_binds(scope, base) for scope in scopes.get(decl.node, ())):
                problems.append(
                    f"{path}:{decorator.lineno}: @{name} on {decl.qualname} is shadowed by a local definition"
                )
                continue
            if marker == "ambiguous":
                problems.append(f"{path}:{decorator.lineno}: @{name} may not be BytePlan's (the name is rebound)")
                continue
            if "<locals>" in decl.qualname:
                problems.append(f"{path}:{decorator.lineno}: @{name} on a nested {decl.qualname} can't be anchored")
                continue
            first, last = decorator.lineno, decorator.end_lineno or decorator.lineno
            prefix = lines[first - 1][: decorator.col_offset].strip()
            suffix = lines[last - 1].rstrip("\r\n").encode()[decorator.end_col_offset or 0 :].decode(errors="replace")
            if prefix != "@" or (suffix.strip() and not suffix.strip().startswith("#")):
                problems.append(f"{path}:{first}: @{name} shares its line with other code")
                continue
            untagged = isinstance(decorator, ast.Call) and not any(k.arg == "id" for k in decorator.keywords)
            if marker == "todo" and untagged:
                raise ReleaseError(UNTAGGED, [f"{path}:{first}: @{name}(...) has no id="], "run `byteplan scan` first")
            # FIXME[0591]: Refuse decorator arguments whose evaluation stripping would skip
            #   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4353302171
            #   `tests=EVENTS.append(...)` ran before release and not after; only literals are safe.
            if isinstance(decorator, ast.Call):
                values = [*decorator.args, *(k.value for k in decorator.keywords)]
                if any(k.arg is None for k in decorator.keywords) or not all(_is_literal(v) for v in values):
                    problems.append(
                        f"{path}:{first}: an argument of @{name} isn't a literal; stripping would skip evaluating it"
                    )
                    continue
            decorators.append(
                {
                    "kind": marker,
                    "task_ids": _task_ids(decorator, marker),
                    "line": first,
                    "end_line": last,
                    "decl_line": decl.node.lineno,
                    "qualname": decl.qualname,
                    "index": index,
                    "text": _block(lines, first, last),
                }
            )
    if problems:
        raise ReleaseError(NEEDS_REVIEW, problems, "put each decorator on its own lines")
    if not decorators and not _runtime_imports(tree, runtime, package):
        return None

    removed_lines = {n for d in decorators for n in range(d["line"], d["end_line"] + 1)}
    intermediate = "".join(line for number, line in enumerate(lines, start=1) if number not in removed_lines)
    used = _used_names(_parse(path, intermediate))
    imports: list[dict[str, Any]] = []
    previous: ast.stmt | None = None
    for stmt in tree.body:
        # FIXME[c8db]: Keep runtime imports that other modules consume through re-exports
        #   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4352941942
        #   `from a import todo` in b.py broke once a.py's runtime import was stripped.
        locals_ = _runtime_locals(stmt, runtime, package)
        if "*" in locals_:
            raise ReleaseError(
                NEEDS_REVIEW,
                [f"{path}:{stmt.lineno}: wildcard import from the runtime; its names can't be proven unused"],
                "import the names you need explicitly",
            )
        consumed = sorted({c for name in locals_ for c in consumers.get(name, set()) | consumers.get("*", set())})
        if locals_ and consumed:
            raise ReleaseError(
                NEEDS_REVIEW,
                [f"{path}:{stmt.lineno}: `{', '.join(locals_)}` is imported from this module by {', '.join(consumed)}"],
                "import it from the runtime where it's used, or drop the re-export",
            )
        if locals_ and "*" not in used and not (set(locals_) & used):
            first, last = stmt.lineno, stmt.end_lineno or stmt.lineno
            if stmt.col_offset != 0 or lines[last - 1].rstrip("\r\n")[stmt.end_col_offset or 0 :].strip():
                raise ReleaseError(
                    NEEDS_REVIEW, [f"{path}:{first}: the runtime import shares its line with other code"]
                )
            anchor = lines[previous.lineno - 1].rstrip("\r\n") if previous is not None else None
            # At the top of the file (or after a blank line), the blank lines below the import
            # go with it, so the stripped file doesn't start with (or gain) a gap. They're in the
            # recorded text, so restoring stays exact.
            preceded_by_blank = first == 1 or not lines[first - 2].strip() or previous is None
            while (
                preceded_by_blank and last < len(lines) and not lines[last].strip() and (last + 1) not in removed_lines
            ):
                last += 1
            imports.append({"line": first, "end_line": last, "anchor": anchor, "text": _block(lines, first, last)})
            removed_lines.update(range(first, last + 1))
        else:
            previous = stmt

    stripped = "".join(line for number, line in enumerate(lines, start=1) if number not in removed_lines)
    leftover = _runtime_imports(_parse(path, stripped), runtime, package)
    if leftover:
        where = sorted({f"line {node.lineno}" for node in leftover})
        raise ReleaseError(
            NEEDS_REVIEW,
            [f"{path}: the runtime is still used outside decorators ({', '.join(where)})"],
            "production code would fail to import without byteplan-runtime",
        )
    return FileStrip(path, stripped, decorators, imports)


def package_of(path: str) -> str:
    """The package a file's relative imports resolve against."""
    here = module_name(path)
    return here if path.endswith("__init__.py") else here.rpartition(".")[0]


def resolve_from(node: ast.ImportFrom, package: str) -> str:
    """The absolute module a ``from ... import`` names (relative ones resolved against ``package``)."""
    base = node.module or ""
    if not node.level:
        return base
    parts = package.split(".") if package else []
    parent = ".".join(parts[: len(parts) - (node.level - 1)]) if node.level > 1 else package
    return f"{parent}.{base}".strip(".") if base else parent


def module_name(path: str) -> str:
    """The import name of a project-relative Python file (``src/`` layouts supported)."""
    stem = path.removesuffix(".py").removeprefix("src/")
    return stem.removesuffix("/__init__").replace("/", ".")


def project_consumers(sources: dict[str, str]) -> dict[str, dict[str, set[str]]]:
    """For each module, the names other files import from it, with the importing files:
    ``from m import x``, ``import m`` + ``m.x``, ``from pkg import m`` + ``m.x``, relative
    imports, and ``from m import *`` (recorded as ``"*"``)."""
    found: dict[str, dict[str, set[str]]] = {}

    def record(module: str, name: str, path: str) -> None:
        found.setdefault(module, {}).setdefault(name, set()).add(path)

    for path, text in sources.items():
        try:
            tree = _parse(path, text)
        except SyntaxError:
            continue
        package = package_of(path)
        # FIXME[2533]: Keep every module an import alias may refer to, across scopes
        #   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4353183658
        #   A function-local `import os as util` overwrote a module-level `import pkg.reexport as util`.
        # local name -> every module it may refer to (scopes aren't tracked, so keep them all)
        modules: dict[str, set[str]] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                base = resolve_from(node, package)
                for alias in node.names:
                    record(base, alias.name, path)
                    if alias.name != "*":
                        modules.setdefault(alias.asname or alias.name, set()).add(f"{base}.{alias.name}".strip("."))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    # FIXME[4518]: An escaping package exposes every submodule imported under it
                    #   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4353601498
                    #   `import pkg.reexport; alias = pkg` reached pkg.reexport.todo unseen.
                    local = alias.asname or alias.name.split(".")[0]
                    modules.setdefault(local, set()).add(alias.name if alias.asname else local)
        # FIXME[8b28]: Treat an imported module that escapes attribute access as consuming all its names
        #   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4353374785
        #   `alias = markers; alias.todo` hid a use of a runtime re-export from the index.
        # A module used any way but `module.name` (assigned, passed, getattr, vars) may reach
        # every name it exports: count them all as consumed.
        attribute_roots = {id(node.value) for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in modules and id(node) not in attribute_roots:
                for target in modules[node.id]:
                    record(target, "*", path)
        # FIXME[fb9c]: Track escapes of dotted module expressions like `alias = pkg.reexport`
        #   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4353523681
        #   Only plain names counted as escapes; `pkg.reexport` assigned elsewhere hid its re-exports.
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                dotted = dotted_name(node)
                root = (dotted or "").split(".")[0]
                if not dotted:
                    continue
                for target in modules.get(root, set()):
                    full = target + dotted[len(root) :]
                    module, _, name = full.rpartition(".")
                    record(module, name, path)
                    if id(node) not in attribute_roots:  # the whole expression escapes (assigned, passed, ...)
                        record(full, "*", path)
    return found


# FIXME[cc54]: Detect a runtime module imported through its parent package
#   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4353302177
#   `from byteplan import _todo` imports runtime module byteplan._todo but wasn't recognized.
def consumers_of(index: dict[str, dict[str, set[str]]], module: str) -> dict[str, set[str]]:
    """Who consumes which names of ``module``: direct imports and accesses, plus every escape
    (``"*"``) of ``module`` or of a package above it, since an escaped package reaches any
    submodule imported under it."""
    found = {name: set(users) for name, users in index.get(module, {}).items()}
    parts = module.split(".")
    for depth in range(1, len(parts)):
        escaped = index.get(".".join(parts[:depth]), {}).get("*", set())
        if escaped:
            found.setdefault("*", set()).update(escaped)
    return found


def _runtime_imports(tree: ast.Module, runtime: set[str], package: str) -> list[ast.Import | ast.ImportFrom]:
    """Every import of a runtime module, at any depth, whatever it imports, including a
    runtime module imported through its parent package (``from pkg import _bp``)."""
    return [
        node
        for node in ast.walk(tree)
        if (isinstance(node, ast.ImportFrom) and _from_runtime(node, runtime, package))
        or (isinstance(node, ast.Import) and any(alias.name in runtime for alias in node.names))
    ]


def _from_runtime(node: ast.ImportFrom, runtime: set[str], package: str) -> bool:
    # FIXME[478d]: Resolve relative imports before deciding whether they import the runtime
    #   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4353523672
    #   `from ._todo import todo` in pkg/m.py (runtime pkg._todo) survived a release.
    base = resolve_from(node, package)
    if not base and not node.level:
        return False
    return base in runtime or any(f"{base}.{alias.name}".strip(".") in runtime for alias in node.names)


def _is_literal(node: ast.expr) -> bool:
    """A constant, or a tuple/list of them: safe to drop without skipping any evaluation."""
    if isinstance(node, ast.Constant):
        return True
    return isinstance(node, ast.Tuple | ast.List) and all(_is_literal(e) for e in node.elts)


def _task_ids(decorator: ast.expr, marker: str) -> list[str]:
    if not isinstance(decorator, ast.Call):
        return []
    if marker == "todo":
        return [
            k.value.value
            for k in decorator.keywords
            if k.arg == "id" and isinstance(k.value, ast.Constant) and isinstance(k.value.value, str)
        ]
    return [a.value for a in decorator.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]


# FIXME[a703]: Refuse wildcard runtime imports, whose bindings can't be proven unused
#   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4352941930
#   `from byteplan_runtime import *` was stripped even when its names were used.
def _runtime_locals(stmt: ast.stmt, runtime: set[str], package: str) -> list[str]:
    """Local names bound by a top-level import of a runtime module (empty if it isn't one)."""
    if isinstance(stmt, ast.ImportFrom) and _from_runtime(stmt, runtime, package):
        return [alias.asname or alias.name for alias in stmt.names]
    if isinstance(stmt, ast.Import) and stmt.names and all(alias.name in runtime for alias in stmt.names):
        return [(alias.asname or alias.name).split(".")[0] for alias in stmt.names]
    return []


# FIXME[baeb]: Count every __all__ assignment form as an export
#   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4353108715
#   `__all__: list[str] = [...]` and `__all__ += [...]` were ignored, so exported names were stripped.
def _used_names(tree: ast.Module) -> set[str]:
    # FIXME[c449]: Treat __all__ mutations the export collector can't resolve as exporting everything
    #   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4353676759
    #   `__all__.append("todo")` exported the runtime name without being recognized.
    # Names exported through __all__ (=, +=, annotated) are used by importers.
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} | _exported(tree)


def ensure_compiles(path: str, text: str) -> str | None:
    """Why ``text`` doesn't compile, or None. ``ast.parse`` accepts a misplaced
    ``from __future__`` import; only compiling catches it."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            compile(text, path, "exec", dont_inherit=True)
    except (SyntaxError, ValueError) as exc:
        return str(exc)
    return None


# Restoring -------------------------------------------------------------------------------------


def restore_fast(stripped: str, record: dict[str, Any]) -> str:
    """Re-insert every recorded block at its recorded line: the exact pre-release text."""
    blocks = sorted(
        [(d["line"], d["text"]) for d in record.get("decorators", [])]
        + [(i["line"], i["text"]) for i in record.get("imports", [])]
    )
    lines = _lines(stripped)
    for line, block in blocks:  # ascending: each block's own lines restore the original numbering
        lines[line - 1 : line - 1] = _lines(block)
    return "".join(lines)


def restore_anchored(path: str, text: str, record: dict[str, Any]) -> tuple[str, list[str], dict[str, Any]]:
    """Place each recorded block through the AST. Returns the new text, the conflicts, and
    the record entries that couldn't be placed (empty when everything went back)."""
    conflicts: list[str] = []
    left_decorators: list[dict[str, Any]] = []
    left_imports: list[dict[str, Any]] = []

    # Imports first: decorators without their import wouldn't be BytePlan's (or would break the
    # module), so if any import can't be placed, the whole file stays on record.
    probe = text
    for entry in sorted(record.get("imports", []), key=lambda e: e["line"]):
        placed = _insert_import(path, probe, entry)
        if placed is None:
            conflicts.append(f"{path}: the statement before `{entry['text'].strip()}` is gone; can't place it")
            return text, conflicts, dict(record)
        probe = placed

    by_decl: dict[str, list[dict[str, Any]]] = {}
    for entry in record.get("decorators", []):
        by_decl.setdefault(entry["qualname"], []).append(entry)
    for qualname, entries in by_decl.items():
        for entry in sorted(entries, key=lambda e: e["index"]):
            tree = _parse(path, text)
            matches = [d for d in declarations(tree) if d.qualname == qualname]
            if len(matches) != 1:
                why = "no longer exists" if not matches else "is ambiguous"
                conflicts.append(
                    f"{path}: {qualname} {why}; can't place @{entry['kind']} (line {entry['line']} before)"
                )
                left_decorators.append(entry)
                continue
            name = re.match(r"\s*@\s*([A-Za-z_][\w.]*)", entry["text"])
            base = name.group(1).split(".")[0] if name else entry["kind"]
            if any(_binds(scope, base) for scope in _enclosing_scopes(tree).get(matches[0].node, ())):
                conflicts.append(
                    f"{path}: `{base}` is shadowed in {qualname}'s scope now; can't restore @{entry['kind']}"
                )
                left_decorators.append(entry)
                continue
            text = _insert_decorator(text, matches[0], entry)

    for entry in sorted(record.get("imports", []), key=lambda e: e["line"]):
        placed = _insert_import(path, text, entry)
        if placed is None:
            conflicts.append(f"{path}: the statement before `{entry['text'].strip()}` is gone; can't place it")
            left_imports.append(entry)
        else:
            text = placed
    text = _hoist_late_imports(path, text, [e for e in record.get("imports", []) if e not in left_imports])
    # FIXME[fb23]: Keep a restored runtime import above every use of its names
    #   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4353449049
    #   A declaration moved above the import's anchor got its decorator before the import (NameError).
    remaining = {"decorators": left_decorators, "imports": left_imports} if left_decorators or left_imports else {}
    return text, conflicts, remaining


# FIXME[c242]: Check the current binding before restoring a decorator
#   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4352850126
#   A class-local `todo` added while stripped would take over the restored decorator.
def _hoist_late_imports(path: str, text: str, entries: Sequence[dict[str, Any]]) -> str:
    """Move a restored import that ends up after a use of its names up to the header (after the
    docstring and ``__future__`` imports): its anchor may now sit below the code using it."""
    for entry in entries:
        lines = _lines(text)
        tree = _parse(path, text)
        block = _lines(entry["text"])
        first = block[0].rstrip("\r\n")
        found = [
            s
            for s in tree.body
            if isinstance(s, ast.Import | ast.ImportFrom) and lines[s.lineno - 1].rstrip("\r\n") == first
        ]
        if len(found) != 1:
            continue
        stmt = found[0]
        bound = {(a.asname or a.name).split(".")[0] for a in stmt.names}
        uses = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id in bound]
        if not uses or min(uses) > (stmt.end_lineno or stmt.lineno):
            continue
        start = stmt.lineno - 1
        if lines[start : start + len(block)] != block:
            continue
        del lines[start : start + len(block)]
        at = max(header_end(lines), _header_statements_end(_parse(path, "".join(lines))))
        lines[at:at] = block
        text = "".join(lines)
    return text


def _insert_decorator(text: str, decl: Declaration, entry: dict[str, Any]) -> str:
    lines = _lines(text)
    stack = decl.node.decorator_list
    line = stack[entry["index"]].lineno if entry["index"] < len(stack) else decl.node.lineno
    if entry["index"] >= len(stack) and stack:
        line = decl.node.lineno  # after every remaining decorator, right above the def
    block = entry["text"]
    old_indent = block[: len(block) - len(block.lstrip(" \t"))]
    new_indent = lines[decl.node.lineno - 1][: decl.col]
    if old_indent != new_indent:  # the declaration moved in or out: re-indent the block
        block = "".join(
            new_indent + part[len(old_indent) :] if part.startswith(old_indent) else part for part in _lines(block)
        )
    lines[line - 1 : line - 1] = [block]
    return "".join(lines)


def _header_statements_end(tree: ast.Module) -> int:
    """The last line of the module docstring and ``from __future__`` imports (0 if none)."""
    end = 0
    for index, stmt in enumerate(tree.body):
        docstring = index == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
        future = isinstance(stmt, ast.ImportFrom) and stmt.module == "__future__"
        if not (docstring or future):
            break
        end = stmt.end_lineno or stmt.lineno
    return end


def _insert_import(path: str, text: str, entry: dict[str, Any]) -> str | None:
    lines = _lines(text)
    tree = _parse(path, text)
    # FIXME[b68c]: Restore an unanchored import below the current docstring and __future__ imports
    #   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4352659119
    #   A hotfix that adds either would otherwise get the import above it (SyntaxError for __future__).
    if entry["anchor"] is None:
        at = max(header_end(lines), _header_statements_end(tree))
    else:
        anchors = [s for s in tree.body if lines[s.lineno - 1].rstrip("\r\n") == entry["anchor"]]
        if len(anchors) != 1:
            return None
        # FIXME[fd44]: Keep anchored imports below a __future__ import added since the release
        #   Codex review of #32: https://github.com/BytesAndCoffee/byteplan/pull/32#discussion_r4353108706
        #   An anchor before a new `from __future__` line put the import above it (SyntaxError).
        at = max(anchors[0].end_lineno or anchors[0].lineno, _header_statements_end(tree))
    lines[at:at] = [entry["text"]]
    return "".join(lines)
