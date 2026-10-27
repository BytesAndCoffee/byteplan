# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Tagged-comment discovery using ``tokenize``.

Grammar (applied only to comment tokens, so strings and docstrings never match):

* A tag comment starts with ``#``, optional whitespace, then a configured tag, an
  optional ``[id]``, and then ``:``, whitespace, or the end of the comment. The tag
  matches in any case when ``:`` or ``[id]`` follows it (``# todo: x``); otherwise
  only its configured spelling does, so ``# Todo list model`` is prose, not a task.
  ``# x = f()  # TODO`` is not a tag: the tag must open the comment.
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

from byteplan._todo import todo
from byteplan.diagnostics import Code, Diagnostic, Location, Severity
from byteplan.errors import SourceError
from byteplan.ids import is_valid_id
from byteplan.models import Annotation, IdSlot

if TYPE_CHECKING:
    from collections.abc import Sequence

    from byteplan.scanner.source import SourceFile
    from byteplan.scanner.symbols import SymbolIndex

__all__ = [
    "CONTINUATION_INDENT",
    "IGNORE_FILE_MAX_LINE",
    "IGNORE_RE",
    "Comment",
    "file_ignored",
    "iter_comments",
    "scan_comments",
    "tag_annotation",
    "tag_pattern",
]

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


@todo(
    "Recognize Google-style `TODO(owner): ...` tags",
    id="46b6",
    description=(
        "Today `TODO(alice):` doesn't match the grammar and is silently not tracked. Accept an\n"
        "optional `(owner)` after the tag and record it as the assignee when a task is created."
    ),
)
def tag_pattern(tags: Sequence[str], opener: str = "#") -> re.Pattern[str]:
    """The tag grammar after a comment opener (a regex: ``#``, ``<!--``, ``//``, ``/\\*``)."""
    # FIXME[415a0f]: [P2] Don't treat prose comments that start with a tag word as tasks
    #   Matching is case-insensitive and only needs whitespace after the tag, so prose comments
    #   reading "Todo list model" or "hack around the parser" become tasks, and the first writing
    #   scan (or the default reconcile commit hook) inserts an ID into them. Markdown already
    #   promises "a TODO list" is not a task. E.g. require `:` or `[id]` after a non-uppercase tag.
    alternatives = "|".join(re.escape(tag) for tag in sorted(tags, key=len, reverse=True))
    # The configured spelling is a tag wherever it opens the comment. Any other case must be
    # followed by `:` or `[id]`, so prose such as "Todo list model" is never a task.
    tag = rf"(?:(?:{alternatives})(?=[\[:\s]|\Z)|(?i:{alternatives})(?=[\[:]))"
    return re.compile(
        rf"{opener}\s*(?P<tag>{tag})(?:\[(?P<id>[^\]]*)\])?(?P<rest>(?:[:\s].*)?)",
        re.DOTALL,
    )


def tag_annotation(
    source: SourceFile,
    match: re.Match[str],
    canonical: dict[str, str],
    *,
    line: int,
    end_line: int,
    col: int,
    slot_col: int,
    title: str,
    description: str,
    symbol: str | None,
    trailing: bool,
) -> Annotation | Diagnostic:
    """The annotation for a matched tag, or a ``malformed_id`` diagnostic.

    ``slot_col`` is where an ``[id]`` goes (right after the tag); ``title`` is the text
    after the tag and ID, from which a leading ``:`` is removed.
    """
    raw_id = match.group("id")
    if raw_id is not None and not is_valid_id(raw_id):
        return Diagnostic(
            Code.MALFORMED_ID,
            Severity.WARNING,
            f"tag ID [{raw_id}] is not a lowercase hexadecimal ID (at least four characters); the tag is not tracked",
            locations=(Location(source.path, line),),
            hint=f"remove the brackets to get a new ID, or fix it to a registered ID, e.g. {match.group('tag')}[7fa2]",
        )
    title = title.strip()
    if title.startswith(":"):
        title = title[1:].strip()
    return Annotation(
        path=source.path,
        line=line,
        end_line=end_line,
        col=col,
        kind=canonical[match.group("tag").upper()],
        tag_text=match.group("tag"),
        task_id=raw_id,
        title=title,
        description=description,
        symbol=symbol,
        trailing=trailing,
        id_slot=None if raw_id is not None else IdSlot(line, slot_col, "[{id}]"),
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

        end_line = comment.line + len(continuation)
        result = tag_annotation(
            source,
            match,
            canonical,
            line=comment.line,
            end_line=end_line,
            col=comment.col,
            slot_col=comment.col + match.end("tag"),
            title=match.group("rest"),
            description=textwrap.dedent("\n".join(continuation)),
            symbol=symbols.symbol_for(comment.line, end_line, comment.col),
            trailing=not comment.standalone,
        )
        if isinstance(result, Diagnostic):
            diagnostics.append(result)
        else:
            found.append(result)
    return found, diagnostics
