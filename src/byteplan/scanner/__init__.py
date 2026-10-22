# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Pure source scanners: they return discoveries and never write."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from byteplan.scanner.association import associate
from byteplan.scanner.comments import IGNORE_RE, file_ignored, iter_comments, scan_comments
from byteplan.scanner.decorators import VerifiesLink, scan_decorators
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


def scan_file(
    source: SourceFile,
    detect: DetectConfig,
    runtime_modules: Sequence[str] = DEFAULT_RUNTIME_MODULES,
    hierarchy: ClassHierarchy | None = None,
) -> FileScan:
    """Scan one decoded file. Raises ``SourceError`` if it can't be tokenized or parsed.

    ``hierarchy`` is the project-wide class index; with ``respect_overrides`` it keeps
    interface methods and deliberate no-op overrides from being reported as stubs.
    """
    tree = parse_module(source)
    comments = iter_comments(source)
    if file_ignored(comments):
        return FileScan(source.path)
    decls = declarations(tree)
    index = SymbolIndex(decls)
    tags, diagnostics = scan_comments(source, detect.todo_tags, index, comments)
    decorated = scan_decorators(source, tree, decls, runtime_modules, detect.todo_tags)
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
    )
