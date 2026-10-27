# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Registry-driven cleanup: remove the source annotations of resolved and dismissed tasks.

Only the exact managed annotation goes, in whichever format it lives:

* **Python comments:** the tag line and its continuation lines, as whole lines; a trailing tag
  is cut from its ``#`` (and the spaces before it) to the end of the line.
* **Python decorators:** ``@todo(..., id="...")`` when it occupies whole lines by itself. The
  runtime import goes too, but only when nothing references the imported name any more.
* **Markdown:** the HTML comment (its whole lines when it stands alone) or the ``[//]: # (...)``
  link-comment lines.
* **JSON:** line and block comments, like Python comments. A tagged *string value* is data, so
  it's left alone (``cleanup_needs_review``).

The cycle guard: a resolved task whose declaration still looks like a stub isn't cleaned
(``resolved_but_stubbed``), since the next scan would just rediscover it. With
``suppress_stubs`` the annotation is replaced by a visible ``# byteplan: ignore`` on the
declaration line instead.

This module plans text edits; the caller validates them (AST equivalence for Python, a
round-trip scan for every format) and writes them through the journal.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from byteplan.diagnostics import Code, Diagnostic, Location, Severity
from byteplan.edits import line_offsets, physical_lines
from byteplan.languages import Language, language_for
from byteplan.models import Representation
from byteplan.scanner.decorators import resolve_runtime_names
from byteplan.scanner.jsonc import tokenize_json
from byteplan.scanner.markdown import parse_markdown

if TYPE_CHECKING:
    from collections.abc import Sequence

    from byteplan.models import Annotation
    from byteplan.scanner.source import SourceFile

IGNORE_MARKER = "# byteplan: ignore"


@dataclass
class FileCleanup:
    text: str
    removed: list[str] = field(default_factory=list)  # task IDs
    suppressed: list[str] = field(default_factory=list)  # task IDs replaced by an ignore marker
    diagnostics: list[Diagnostic] = field(default_factory=list)
    imports_removed: list[str] = field(default_factory=list)


def _review(code: Code, tag: Annotation, message: str, hint: str | None = None) -> Diagnostic:
    return Diagnostic(
        code, Severity.WARNING, message, task_id=tag.task_id, locations=(Location(tag.path, tag.line),), hint=hint
    )


def _whole_lines(offsets: Sequence[int], text: str, first: int, last: int) -> tuple[int, int]:
    end = offsets[last] if last < len(offsets) else len(text)
    return offsets[first - 1], end


def _block_lines(lines: Sequence[str], offsets: Sequence[int], text: str, first: int, last: int) -> tuple[int, int]:
    """Whole lines of a Markdown block, plus one of the blank lines around it when it sits
    between two, so removing it doesn't leave a double blank line."""
    start, end = _whole_lines(offsets, text, first, last)
    before_blank = first > 1 and not lines[first - 2].strip()
    after_blank = last < len(lines) and not lines[last].strip()
    if before_blank and after_blank:
        end = offsets[last + 1] if last + 1 < len(offsets) else len(text)
    return start, end


def _trailing(lines: Sequence[str], offsets: Sequence[int], line: int, col: int) -> tuple[int, int]:
    """From the spaces before a trailing comment to the end of the line (the newline stays)."""
    content = lines[line - 1].rstrip("\r\n")
    start = len(content[:col].rstrip(" \t"))
    return offsets[line - 1] + start, offsets[line - 1] + len(content)


def plan_file(
    source: SourceFile,
    remove: Sequence[Annotation],
    *,
    runtime_modules: Sequence[str],
    suppress_stubs: bool,
    consumers: frozenset[str] = frozenset(),
) -> FileCleanup:
    """Plan removing ``remove`` (this file's annotations of closed tasks) from ``source``."""
    plan = FileCleanup(source.text)
    text = source.text
    lines = physical_lines(text)
    offsets = line_offsets(text)
    language = language_for(source.path) or Language.PYTHON
    spans: list[tuple[int, int, str]] = []
    markers: set[int] = set()  # declaration lines that get "# byteplan: ignore"

    for tag in remove:
        assert tag.task_id is not None  # noqa: S101 - callers pass tagged annotations
        if tag.decl_is_stub:
            if not suppress_stubs:
                plan.diagnostics.append(
                    _review(
                        Code.RESOLVED_BUT_STUBBED,
                        tag,
                        f"task {tag.task_id} is closed but {tag.symbol} still looks unfinished; its annotation stays",
                        "implement it, or rerun with --suppress-stubs to mark it `# byteplan: ignore` instead",
                    )
                )
                continue
            decl_line = tag.decl_line or tag.line
            if "#" in lines[decl_line - 1]:
                plan.diagnostics.append(
                    _review(
                        Code.CLEANUP_NEEDS_REVIEW,
                        tag,
                        f"line {decl_line} already has a comment, so `# byteplan: ignore` can't be added safely",
                    )
                )
                continue
            markers.add(decl_line)
        span = _span(source, tag, language, lines, offsets, plan)
        if span is None:
            markers.discard(tag.decl_line or tag.line)
            continue
        spans.append(span)
        (plan.suppressed if tag.decl_is_stub else plan.removed).append(tag.task_id)

    for line in markers:
        content = lines[line - 1].rstrip("\r\n")
        at = offsets[line - 1] + len(content)
        spans.append((at, at, f"  {IGNORE_MARKER}"))

    if not spans:
        return plan
    for start, end, replacement in sorted(spans, reverse=True):
        text = text[:start] + replacement + text[end:]
    if language is Language.PYTHON and any(t.representation is Representation.DECORATOR for t in remove):
        text, plan.imports_removed = _drop_unused_runtime_imports(source.path, text, runtime_modules, consumers)
    plan.text = text
    return plan


def _span(
    source: SourceFile,
    tag: Annotation,
    language: Language,
    lines: Sequence[str],
    offsets: Sequence[int],
    plan: FileCleanup,
) -> tuple[int, int, str] | None:
    text = source.text
    if language is Language.MARKDOWN:
        structure = parse_markdown(text)
        comment = next((c for c in structure.comments if (c.line, c.col) == (tag.line, tag.col)), None)
        if comment is None:  # a [//]: # (...) link comment, whole lines
            return (*_block_lines(lines, offsets, text, tag.line, tag.end_line), "")
        rest = text[comment.end : offsets[comment.end_line] if comment.end_line < len(offsets) else len(text)]
        if comment.standalone and not rest.strip():
            return (*_block_lines(lines, offsets, text, comment.line, comment.end_line), "")
        start = comment.start
        line_end = offsets[comment.end_line] if comment.end_line < len(offsets) else len(text)
        following = text[comment.end : line_end]
        # The space before the comment separates words unless the comment ends the line or is
        # itself followed by a space (which then does the separating).
        if not following.strip() or following[:1] in {" ", "\t"}:
            while start > offsets[comment.line - 1] and text[start - 1] in " \t":
                start -= 1
        return start, comment.end, ""
    if language is Language.JSON:
        token = next((t for t in tokenize_json(source.path, text) if (t.line, t.col) == (tag.line, tag.col)), None)
        if token is None or token.kind == "string":
            plan.diagnostics.append(
                _review(
                    Code.CLEANUP_NEEDS_REVIEW,
                    tag,
                    f"task {tag.task_id} is a JSON string value, which is data; remove it by hand",
                )
            )
            return None
        if token.kind == "block_comment" and token.standalone:
            end = token.offset + len(token.text)
            rest = text[end : offsets[tag.end_line] if tag.end_line < len(offsets) else len(text)]
            if not rest.strip():
                start, stop = _whole_lines(offsets, text, tag.line, tag.end_line)
                return start, stop, ""
        if token.standalone and token.kind == "line_comment":
            start, end = _whole_lines(offsets, text, tag.line, tag.end_line)
            return start, end, ""
        start, end = _trailing(lines, offsets, tag.line, tag.col)
        return start, (token.offset + len(token.text)) if token.kind == "block_comment" else end, ""
    # Python
    if tag.representation is Representation.DECORATOR:
        before = lines[tag.line - 1][: tag.col]
        after = lines[tag.end_line - 1].rstrip("\r\n")
        tree = ast.parse(text)
        call_end = next(
            (
                d.end_col_offset
                for node in ast.walk(tree)
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
                for d in node.decorator_list
                if d.lineno == tag.line and (d.end_lineno or d.lineno) == tag.end_line
            ),
            None,
        )
        if before.strip() or call_end is None or after.encode()[call_end:].decode(errors="replace").strip():
            plan.diagnostics.append(
                _review(
                    Code.CLEANUP_NEEDS_REVIEW,
                    tag,
                    f"@todo for task {tag.task_id} shares its lines with other code; remove it by hand",
                )
            )
            return None
        start, end = _whole_lines(offsets, text, tag.line, tag.end_line)
        return start, end, ""
    if tag.trailing:
        start, end = _trailing(lines, offsets, tag.line, tag.col)
        return start, end, ""
    start, end = _whole_lines(offsets, text, tag.line, tag.end_line)
    return start, end, ""


def _drop_unused_runtime_imports(
    path: str, text: str, runtime_modules: Sequence[str], consumers: frozenset[str] = frozenset()
) -> tuple[str, list[str]]:
    """Drop ``todo`` from ``from <runtime> import ...`` statements once nothing uses it.

    Only BytePlan's ``todo`` is ours to remove: other imported names stay (the statement is
    rewritten without ``todo``), a statement that spans lines or shares one is left alone, and
    ``import <runtime>`` module imports are never touched.
    """
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError:
        return text, []  # the caller's validation reports it
    names = resolve_runtime_names(tree, runtime_modules)
    runtime = set(runtime_modules)
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    used |= {_root(node) for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    used |= _exported(tree)
    used |= consumers
    # FIXME[e3d6bd]: Index physical lines with edits.physical_lines, not str.splitlines
    #   splitlines also breaks at \f, \v, \x1c-\x1e, \x85, U+2028 and U+2029, so ast line numbers
    #   point at the wrong entry. `resolve --sync-source` then deletes user text: with `# a<U+2028>b`
    #   above the runtime import it removes "b" and moves the import into the comment; with a form-feed
    #   line it removes a newline, keeps the import, and still reports "unused runtime import" removed.
    #   release.py's `_lines` (strip/restore: false "shares its line" refusals) and scaffold.plan's
    #   import insertion share the pattern.
    lines = physical_lines(text)
    removed: list[str] = []
    for stmt in sorted(tree.body, key=lambda s: s.lineno, reverse=True):
        if not (isinstance(stmt, ast.ImportFrom) and stmt.level == 0 and stmt.module in runtime):
            continue
        drop = [
            alias
            for alias in stmt.names
            if alias.name == "todo" and "*" not in used and (alias.asname or alias.name) not in used | names.ambiguous
        ]
        if not drop or stmt.end_lineno != stmt.lineno or stmt.col_offset != 0:
            continue
        line = lines[stmt.lineno - 1]
        content = line.rstrip("\r\n")
        if content[stmt.end_col_offset or 0 :].strip():
            continue  # shares the line with other code
        keep = [alias for alias in stmt.names if alias not in drop]
        removed.append(content)
        if keep:
            names_text = ", ".join(a.name + (f" as {a.asname}" if a.asname else "") for a in keep)
            lines[stmt.lineno - 1] = f"from {stmt.module} import {names_text}" + line[len(content) :]
            continue
        del lines[stmt.lineno - 1]
        # Don't leave the blank lines that separated it from the code below at the top of the
        # file (or doubled up between blocks).
        at = stmt.lineno - 1
        while at < len(lines) and not lines[at].strip() and (at == 0 or not lines[at - 1].strip()):
            del lines[at]
    return "".join(lines), removed


def _exported(tree: ast.Module) -> set[str]:
    """String literals in module-level ``__all__`` assignments (``=``, ``+=``, annotated).

    Contains ``"*"`` (may export anything) when ``__all__`` is used in a way that can't be
    resolved statically: ``.append``/``.extend``, subscripts, being passed around, or a
    non-literal value.
    """
    names: set[str] = set()
    resolved: set[int] = set()  # ids of the __all__ target names read exactly
    for stmt in tree.body:
        targets: list[ast.expr]
        value: ast.expr | None
        if isinstance(stmt, ast.Assign):
            targets, value = stmt.targets, stmt.value
        elif isinstance(stmt, ast.AugAssign | ast.AnnAssign):
            targets, value = [stmt.target], stmt.value
        else:
            continue
        if value is None or not any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
            continue
        if not _literal_names(value):
            names.add("*")
        names |= {n.value for n in ast.walk(value) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        resolved |= {id(t) for t in targets if isinstance(t, ast.Name)}
    if any(isinstance(n, ast.Name) and n.id == "__all__" and id(n) not in resolved for n in ast.walk(tree)):
        names.add("*")
    return names


def _literal_names(node: ast.expr) -> bool:
    """A list/tuple of strings, or ``+`` of such: an ``__all__`` value read exactly."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_names(node.left) and _literal_names(node.right)
    return isinstance(node, ast.List | ast.Tuple) and all(
        isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts
    )


def _root(node: ast.Attribute) -> str:
    value: ast.expr = node
    while isinstance(value, ast.Attribute):
        value = value.value
    return value.id if isinstance(value, ast.Name) else ""
