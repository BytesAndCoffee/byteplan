# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Pure source scanners: they return discoveries and never write."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from byteplan.edits import ensure_equivalent
from byteplan.languages import Language, language_for
from byteplan.models import AttachmentKind
from byteplan.scanner.association import associate
from byteplan.scanner.comments import IGNORE_RE, file_ignored, iter_comments, scan_comments
from byteplan.scanner.decorators import VerifiesLink, scan_decorators, scan_markers
from byteplan.scanner.jsonc import ensure_json_equivalent, scan_json
from byteplan.scanner.markdown import ensure_markdown_equivalent, scan_markdown
from byteplan.scanner.stubs import find_stubs
from byteplan.scanner.symbols import SymbolIndex, declarations, parse_module

if TYPE_CHECKING:
    from collections.abc import Sequence

    from byteplan.config import DetectConfig
    from byteplan.diagnostics import Diagnostic
    from byteplan.models import Annotation
    from byteplan.scanner.hierarchy import ClassHierarchy
    from byteplan.scanner.source import SourceFile

DEFAULT_RUNTIME_MODULES = ("byteplan_runtime",)


@dataclass(frozen=True)
class FileScan:
    path: str
    # Comment tags, @todo decorators, and proposed comments for unowned stubs, in line order.
    tags: list[Annotation] = field(default_factory=list)
    links: list[VerifiesLink] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    runtime_decorated: bool = False


def scan_file(
    source: SourceFile,
    detect: DetectConfig,
    runtime_modules: Sequence[str] = DEFAULT_RUNTIME_MODULES,
    hierarchy: ClassHierarchy | None = None,
    *,
    pytest_marker: bool = False,
) -> FileScan:
    """Scan one decoded file. Raises ``SourceError`` if it can't be tokenized or parsed.

    ``hierarchy`` is the project-wide class index; with ``respect_overrides`` it keeps
    interface methods and deliberate no-op overrides from being reported as stubs.
    Markdown and JSON files have tags only: no stubs, decorators or declarations.
    """
    language = language_for(source.path)
    if language is Language.MARKDOWN:
        return FileScan(source.path, *_loose(*scan_markdown(source, detect.todo_tags)))
    if language is Language.JSON:
        return FileScan(source.path, *_loose(*scan_json(source, detect)))
    tree = parse_module(source)
    comments = iter_comments(source)
    if file_ignored(comments):
        return FileScan(source.path)
    decls = declarations(tree)
    index = SymbolIndex(decls)
    tags, diagnostics = scan_comments(source, detect.todo_tags, index, comments)
    decorated = scan_decorators(source, tree, decls, runtime_modules, detect.todo_tags)
    if pytest_marker:
        decorated.links.extend(scan_markers(source, tree, decls, decorated.diagnostics))
    ignore_lines = {c.line for c in comments if IGNORE_RE.search(c.text)}
    intentional = hierarchy.intentional if hierarchy is not None and detect.respect_overrides else None
    stubs = find_stubs(decls, detect, ignore_lines, intentional)
    annotations, stub_diagnostics = associate(
        source, [*tags, *decorated.annotations], stubs, decls, index, detect.todo_tags
    )
    return FileScan(
        source.path,
        annotations,
        decorated.links,
        [*diagnostics, *decorated.diagnostics, *stub_diagnostics],
        runtime_decorated=bool(decorated.runtime_lines),
    )


def _loose(
    tags: list[Annotation], diagnostics: list[Diagnostic]
) -> tuple[list[Annotation], list[VerifiesLink], list[Diagnostic]]:
    """Attach non-Python tags to the file: ``statement`` when trailing, else ``module``."""
    attached = [
        dataclasses.replace(t, attachment_kind=AttachmentKind.STATEMENT if t.trailing else AttachmentKind.MODULE)
        for t in tags
    ]
    return attached, [], diagnostics


def ensure_unchanged(path: str, before: str, after: str, tags: Sequence[str]) -> None:
    """Refuse an annotation edit that changes anything but comments (and, in JSON, tagged
    strings' IDs). Raises ``EditError``."""
    language = language_for(path)
    if language is Language.MARKDOWN:
        ensure_markdown_equivalent(path, before, after)
    elif language is Language.JSON:
        ensure_json_equivalent(path, before, after, tags)
    else:
        ensure_equivalent(path, before, after)
