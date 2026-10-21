# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Pure source scanners: they return discoveries and never write."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from byteplan.scanner.comments import scan_comments
from byteplan.scanner.symbols import SymbolIndex, declarations, parse_module

if TYPE_CHECKING:
    from byteplan.config import DetectConfig
    from byteplan.diagnostics import Diagnostic
    from byteplan.models import CommentTag
    from byteplan.scanner.source import SourceFile


@dataclass(frozen=True)
class FileScan:
    path: str
    tags: list[CommentTag] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)


def scan_file(source: SourceFile, detect: DetectConfig) -> FileScan:
    """Scan one decoded file. Raises ``SourceError`` if it can't be tokenized or parsed."""
    tree = parse_module(source)
    tags, diagnostics = scan_comments(source, detect.todo_tags, SymbolIndex(declarations(tree)))
    return FileScan(source.path, tags, diagnostics)
