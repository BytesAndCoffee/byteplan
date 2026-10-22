# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Pair annotations with declarations so each obligation gets exactly one task.

An annotation *owns* a declaration when it is:

* a ``@todo`` decorator on it;
* a comment block ending on the line right above its first decorator or ``def``/
  ``class`` line, at the same column, or a comment among its decorator/header lines;
* a comment inside its body (the innermost enclosing declaration).

A stub owned by any annotation produces no extra task. An unowned stub gets a
proposed ``# TODO[id]: Implement <qualname> (detected stub)`` line above its
first decorator, unless that isn't clearly safe (a one-line body such as
``def f(): pass``, a declaration not starting its line, or a preceding line
continuation); those are reported as ``stub_needs_review`` and left alone.
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from byteplan.diagnostics import Code, Diagnostic, Location, Severity
from byteplan.models import Annotation, AttachmentKind, IdSlot, Origin, Representation

if TYPE_CHECKING:
    from collections.abc import Sequence

    from byteplan.scanner.source import SourceFile
    from byteplan.scanner.stubs import Stub
    from byteplan.scanner.symbols import Declaration, SymbolIndex


def _owner(annotation: Annotation, decls: Sequence[Declaration], index: SymbolIndex) -> tuple[Declaration | None, bool]:
    """The declaration an annotation owns, and whether it owns it from inside the body."""
    if annotation.representation is Representation.DECORATOR:
        return next((d for d in decls if d.node.lineno == annotation.decl_line), None), False
    if not annotation.trailing:
        attached = index.attached(annotation.end_line, annotation.col)
        if attached is not None:
            return attached, False
    enclosing = index.enclosing(annotation.line)
    if enclosing is None:
        return None, False
    return enclosing, annotation.line > enclosing.header_end


def associate(
    source: SourceFile,
    annotations: Sequence[Annotation],
    stubs: Sequence[Stub],
    decls: Sequence[Declaration],
    index: SymbolIndex,
    tags: Sequence[str],
) -> tuple[list[Annotation], list[Diagnostic]]:
    """Return annotations enriched with attachment info, plus proposals for unowned stubs."""
    stub_starts = {stub.decl.start: stub for stub in stubs}
    owned: set[int] = set()
    result: list[Annotation] = []
    for annotation in annotations:
        decl, in_body = _owner(annotation, decls, index)
        if decl is None:
            loose = AttachmentKind.STATEMENT if annotation.trailing else AttachmentKind.MODULE
            result.append(dataclasses.replace(annotation, attachment_kind=loose))
            continue
        owned.add(decl.start)
        is_stub = decl.start in stub_starts
        # A comment in a stub's body is about the declaration; in a real body, about a statement.
        attachment = AttachmentKind.STATEMENT if in_body and not is_stub else decl.kind
        result.append(
            dataclasses.replace(
                annotation,
                decl_line=decl.node.lineno,
                attachment_kind=attachment,
                decl_is_stub=is_stub,
            )
        )

    diagnostics: list[Diagnostic] = []
    lines = source.text.splitlines(keepends=True)
    kind = "TODO" if "TODO" in tags else tags[0]
    for start, stub in sorted(stub_starts.items()):
        if start in owned:
            continue
        decl = stub.decl
        line_text = lines[start - 1] if start <= len(lines) else ""
        previous = lines[start - 2].rstrip("\r\n") if start > 1 else ""
        one_line_body = decl.node.body[0].lineno == decl.node.lineno
        if one_line_body or line_text[: decl.col].strip() or previous.endswith("\\"):
            diagnostics.append(
                Diagnostic(
                    Code.STUB_NEEDS_REVIEW,
                    Severity.INFO,
                    f"{decl.qualname} looks unfinished ({stub.reason}) but can't be annotated automatically",
                    locations=(Location(source.path, decl.node.lineno),),
                    hint=f"add `# {kind}: ...` above it, or `# byteplan: ignore` if it's intentional",
                )
            )
            continue
        indent = line_text[: len(line_text) - len(line_text.lstrip(" \t"))]
        title = f"Implement {decl.qualname} (detected stub)"
        result.append(
            Annotation(
                path=source.path,
                line=start,
                end_line=start,
                col=len(indent),
                kind=kind,
                tag_text=kind,
                task_id=None,
                title=title,
                description="",
                symbol=decl.qualname,
                trailing=False,
                id_slot=IdSlot(start, 0, f"{indent}# {kind}[{{id}}]: {title}{source.newline}"),
                origin=Origin.STUB,
                decl_line=decl.node.lineno,
                attachment_kind=decl.kind,
                decl_is_stub=True,
            )
        )
    result.sort(key=lambda a: (a.line, a.col))
    return result, diagnostics
