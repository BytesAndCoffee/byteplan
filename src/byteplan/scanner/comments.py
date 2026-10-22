# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Tagged-comment discovery using ``tokenize``.

Grammar (applied only to comment tokens, so strings and docstrings never match):

* A tag comment starts with ``#``, optional whitespace, then a configured tag
  (case-insensitive), an optional ``[id]``, and then ``:``, whitespace, or the
  end of the comment. ``# x = f()  # TODO`` is not a tag: the tag must open the
  comment.
* A tag on its own line owns the continuation lines directly below it. A
  continuation line is a comment-only line, on the very next physical line, with
  its ``#`` in the same column, whose text after ``#`` starts with at least two
  spaces. The block ends at the first line that is not one: a blank line, code,
  another tag, an ordinary comment (fewer than two spaces after ``#``), or a
  comment in a different column.
* A trailing tag (``x = 1  # TODO: ...``) never has continuation lines.
* ``byteplan: ignore`` inside a tag comment suppresses that tag.
  ``# byteplan: ignore-file`` within the first five lines suppresses the file.
"""

from __future__ import annotations

import re
import textwrap
import tokenize
from dataclasses import dataclass
from typing import TYPE_CHECKING

from byteplan.diagnostics import Code, Diagnostic, Location, Severity
from byteplan.errors import SourceError
from byteplan.ids import is_valid_id
from byteplan.models import Annotation, IdSlot

if TYPE_CHECKING:
    from collections.abc import Sequence

    from byteplan.scanner.source import SourceFile
    from byteplan.scanner.symbols import SymbolIndex

__all__ = ["IGNORE_RE", "Comment", "file_ignored", "iter_comments", "scan_comments", "tag_pattern"]

IGNORE_RE = re.compile(r"\bbyteplan:\s*ignore(?![-\w])", re.IGNORECASE)
IGNORE_FILE_RE = re.compile(r"^#\s*byteplan:\s*ignore-file\b", re.IGNORECASE)
IGNORE_FILE_MAX_LINE = 5
CONTINUATION_INDENT = "  "


@dataclass(frozen=True)
class Comment:
    line: int
    col: int
    text: str
    # True when nothing but whitespace precedes the comment on its line.
    standalone: bool


def tag_pattern(tags: Sequence[str]) -> re.Pattern[str]:
    alternatives = "|".join(re.escape(tag) for tag in sorted(tags, key=len, reverse=True))
    return re.compile(
        rf"#\s*(?P<tag>{alternatives})(?:\[(?P<id>[^\]]*)\])?(?P<rest>(?:[:\s].*)?)",
        re.IGNORECASE | re.DOTALL,
    )


def iter_comments(source: SourceFile) -> list[Comment]:
    comments: list[Comment] = []
    try:
        for token in tokenize.generate_tokens(source.readline_io().readline):
            if token.type == tokenize.COMMENT:
                row, col = token.start
                comments.append(Comment(row, col, token.string, not token.line[:col].strip()))
    except (tokenize.TokenError, SyntaxError) as exc:
        raise SourceError(source.path, f"cannot tokenize: {exc}") from exc
    return comments


def file_ignored(comments: Sequence[Comment]) -> bool:
    return any(c.line <= IGNORE_FILE_MAX_LINE and IGNORE_FILE_RE.match(c.text) for c in comments)


def scan_comments(
    source: SourceFile,
    tags: Sequence[str],
    symbols: SymbolIndex,
    comments: Sequence[Comment] | None = None,
) -> tuple[list[Annotation], list[Diagnostic]]:
    if comments is None:
        comments = iter_comments(source)
    if file_ignored(comments):
        return [], []

    pattern = tag_pattern(tags)
    canonical = {tag.upper(): tag for tag in tags}
    found: list[Annotation] = []
    diagnostics: list[Diagnostic] = []

    index = 0
    while index < len(comments):
        comment = comments[index]
        index += 1
        match = pattern.fullmatch(comment.text)
        if match is None:
            continue

        continuation: list[str] = []
        if comment.standalone:
            previous = comment.line
            while index < len(comments):
                nxt = comments[index]
                body = nxt.text[1:]
                if (
                    nxt.line != previous + 1
                    or not nxt.standalone
                    or nxt.col != comment.col
                    or pattern.fullmatch(nxt.text)
                    or not body.startswith(CONTINUATION_INDENT)
                    or not body.strip()
                ):
                    break
                continuation.append(body.rstrip())
                previous = nxt.line
                index += 1

        if IGNORE_RE.search(comment.text):
            continue

        raw_id = match.group("id")
        if raw_id is not None and not is_valid_id(raw_id):
            diagnostics.append(
                Diagnostic(
                    Code.MALFORMED_ID,
                    Severity.WARNING,
                    f"tag ID [{raw_id}] is not four lowercase hex digits; the tag is not tracked",
                    locations=(Location(source.path, comment.line),),
                    hint=f"remove the brackets to get a new ID, or fix it to a registered ID, e.g. {match.group('tag')}[7fa2]",
                )
            )
            continue

        title = match.group("rest").strip()
        if title.startswith(":"):
            title = title[1:].strip()
        end_line = comment.line + len(continuation)
        found.append(
            Annotation(
                path=source.path,
                line=comment.line,
                end_line=end_line,
                col=comment.col,
                kind=canonical[match.group("tag").upper()],
                tag_text=match.group("tag"),
                task_id=raw_id,
                title=title,
                description=textwrap.dedent("\n".join(continuation)),
                symbol=symbols.symbol_for(comment.line, end_line, comment.col),
                trailing=not comment.standalone,
                id_slot=None if raw_id is not None else IdSlot(comment.line, comment.col + match.end("tag"), "[{id}]"),
            )
        )
    return found, diagnostics
