# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Tagged HTML comments in Markdown.

Grammar:

* A tag lives in an HTML comment and must open it: ``<!-- TODO: title -->``, with the
  same tag, ``[id]`` and case rules as Python comments. The tag must be on the line
  of ``<!--``. Prose is never scanned, so "a TODO list" is not a task.
* The rest of that line is the title. The comment's remaining lines, up to ``-->``,
  are the description (dedented).
* Comments inside fenced code blocks (backticks or tildes, also inside lists and
  block quotes) and inline code spans (which may continue over a paragraph's lines)
  are text, not comments. Indented (four-space)
  code blocks are not recognized.
* A tag's symbol is the nearest preceding heading (ATX or setext). YAML front matter
  is skipped.
* ``byteplan: ignore`` inside a tag comment suppresses it, and
  ``<!-- byteplan: ignore-file -->`` within the first five lines suppresses the file.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass
from typing import TYPE_CHECKING

from byteplan.diagnostics import Diagnostic
from byteplan.edits import line_offsets, physical_lines
from byteplan.errors import EditError
from byteplan.scanner.comments import IGNORE_FILE_MAX_LINE, IGNORE_RE, tag_annotation, tag_pattern

if TYPE_CHECKING:
    from collections.abc import Sequence

    from byteplan.models import Annotation
    from byteplan.scanner.source import SourceFile

OPEN, CLOSE = "<!--", "-->"
# Container prefixes (block quotes, list markers) may precede a fence: "> ```", "- ```html".
_FENCE_RE = re.compile(r"^(?:[ \t]*(?:>|(?:[-+*]|\d{1,9}[.)])(?=[ \t])))*[ \t]*(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
_ATX_RE = re.compile(r"^ {0,3}#{1,6}(?:[ \t]+(?P<text>.*?))?(?:[ \t]+#+)?[ \t]*$")
_SETEXT_RE = re.compile(r"^ {0,3}(?:=+|-+)[ \t]*$")
_LIST_RE = re.compile(r"^ {0,3}(?:[-+*]|\d{1,9}[.)])(?:[ \t]|$)")
_FRONT_MATTER_END = frozenset({"---", "..."})
_BACKTICKS_RE = re.compile(r"`+")
_IGNORE_FILE_RE = re.compile(r"^\s*byteplan:\s*ignore-file\b", re.IGNORECASE)
_INLINE_COMMENT_RE = re.compile(r"<!--.*?-->")


@dataclass(frozen=True)
class HtmlComment:
    start: int  # offset of "<!--"
    end: int  # offset just past "-->", or the end of the text if unterminated
    line: int
    col: int
    end_line: int
    standalone: bool

    def text(self, source: str) -> str:
        return source[self.start : self.end]


@dataclass(frozen=True)
class MarkdownStructure:
    comments: list[HtmlComment]
    headings: list[tuple[int, str]]  # (line, text), in order

    def heading_for(self, line: int) -> str | None:
        found = None
        for heading_line, text in self.headings:
            if heading_line > line:
                break
            found = text
        return found


def _front_matter_end(lines: Sequence[str]) -> int:
    """Number of leading lines that are YAML front matter (0 if none)."""
    if not lines or lines[0].rstrip("\r\n") != "---":
        return 0
    for number, line in enumerate(lines[1:], start=2):
        if line.rstrip("\r\n").rstrip() in _FRONT_MATTER_END:
            return number
    return 0


def _interrupts_paragraph(content: str) -> bool:
    return not content.strip() or bool(_FENCE_RE.match(content) or _ATX_RE.match(content))


class _Parser:
    def __init__(self, text: str, lines: Sequence[str]) -> None:
        self.text = text
        self.lines = [line.rstrip("\r\n") for line in lines]
        self.offsets = line_offsets(text)
        self.comments: list[HtmlComment] = []
        # An open comment: (start offset, line, col, standalone).
        self.pending: tuple[int, int, int, bool] | None = None
        # An inline code span continuing onto later lines: where it ends (line, col).
        self.code_until: tuple[int, int] | None = None

    def code_span_end(self, line: int, col: int, ticks: int) -> tuple[int, int] | None:
        """Where a code span opened by ``ticks`` backticks ending at (line, col) closes: at the
        next run of exactly that many, within the paragraph. None if it never closes (then
        the backticks are literal)."""
        closer = re.compile(rf"(?<!`)`{{{ticks}}}(?!`)")
        for number in range(line, len(self.lines) + 1):
            content = self.lines[number - 1]
            if number > line and _interrupts_paragraph(content):
                return None
            match = closer.search(content, col if number == line else 0)
            if match:
                return number, match.end()
        return None

    def close(self, line: int, end_col: int) -> None:
        if self.pending is not None:
            start, start_line, col, standalone = self.pending
            self.comments.append(
                HtmlComment(start, self.offsets[line - 1] + end_col, start_line, col, line, standalone)
            )
            self.pending = None

    def scan_line(self, content: str, line: int, pos: int = 0) -> None:
        """Find comments on one line from ``pos``, outside inline code, continuing an open one first.

        Scanning goes left to right, as Markdown's inline parsing does: a code span that
        opens first hides a ``<!--`` inside it, and a comment that opens first hides backticks.
        """
        while pos < len(content):
            if self.pending is not None:
                end = content.find(CLOSE, pos)
                if end < 0:
                    return
                pos = end + len(CLOSE)
                self.close(line, pos)
                continue
            start = content.find(OPEN, pos)
            ticks = _BACKTICKS_RE.search(content, pos)
            if ticks is not None and (start < 0 or ticks.start() < start):
                span_end = self.code_span_end(line, ticks.end(), len(ticks.group()))
                if span_end is None:
                    pos = ticks.end()  # unmatched backticks are literal
                elif span_end[0] == line:
                    pos = span_end[1]
                else:
                    self.code_until = span_end
                    return
                continue
            if start < 0:
                return
            self.pending = (self.offsets[line - 1] + start, line, start, not content[:start].strip())
            pos = start + len(OPEN)
            # "<!-->" and "<!--->" are complete (empty) comments.
            empty = next((e for e in (">", "->") if content.startswith(e, pos)), None)
            if empty is not None:
                pos += len(empty)
                self.close(line, pos)


def parse_markdown(text: str) -> MarkdownStructure:
    lines = physical_lines(text)
    parser = _Parser(text, lines)
    headings: list[tuple[int, str]] = []
    fence: tuple[str, int] | None = None
    previous_paragraph: str | None = None  # the line above, if it could be a setext heading's text

    for number, raw in enumerate(lines[_front_matter_end(lines) :], start=_front_matter_end(lines) + 1):
        content = raw.rstrip("\r\n")
        if parser.code_until is not None:  # inside a multi-line inline code span
            end_line, end_col = parser.code_until
            if number == end_line:
                parser.code_until = None
                parser.scan_line(content, number, end_col)
            previous_paragraph = None
            continue
        if parser.pending is not None:
            parser.scan_line(content, number)
            previous_paragraph = None
            continue
        match = _FENCE_RE.match(content)
        if fence is not None:
            if match and match.group("fence")[0] == fence[0] and len(match.group("fence")) >= fence[1]:
                fence = None if not match.group("info").strip() else fence
            continue
        if match and not (match.group("fence")[0] == "`" and "`" in match.group("info")):
            fence = (match.group("fence")[0], len(match.group("fence")))
            previous_paragraph = None
            continue

        atx = _ATX_RE.match(content)
        if atx:
            headings.append((number, _heading_text(atx.group("text") or "")))
        elif previous_paragraph is not None and _SETEXT_RE.match(content):
            headings.append((number - 1, _heading_text(previous_paragraph)))
        parser.scan_line(content, number)
        prose = _heading_text(content)
        previous_paragraph = (
            content
            if prose
            and not atx
            and parser.pending is None
            and not _LIST_RE.match(content)
            and not prose.startswith(">")
            else None
        )
    if parser.pending is not None:  # unterminated: runs to the end of the document, as in CommonMark
        start, start_line, col, standalone = parser.pending
        parser.comments.append(HtmlComment(start, len(text), start_line, col, max(len(lines), 1), standalone))
    return MarkdownStructure(parser.comments, headings)


def _heading_text(text: str) -> str:
    return " ".join(_INLINE_COMMENT_RE.sub("", text).split())


def scan_markdown(source: SourceFile, tags: Sequence[str]) -> tuple[list[Annotation], list[Diagnostic]]:
    structure = parse_markdown(source.text)
    comments = structure.comments
    if any(c.line <= IGNORE_FILE_MAX_LINE and _IGNORE_FILE_RE.match(_body(c.text(source.text))) for c in comments):
        return [], []
    pattern = tag_pattern(tags, opener=re.escape(OPEN))
    canonical = {tag.upper(): tag for tag in tags}
    found: list[Annotation] = []
    diagnostics: list[Diagnostic] = []
    for comment in comments:
        text = comment.text(source.text)
        match = pattern.fullmatch(text)
        if match is None or "\n" in text[: match.end("tag")] or "\r" in text[: match.end("tag")]:
            continue
        if IGNORE_RE.search(text):
            continue
        rest = match.group("rest")
        if text.endswith(CLOSE):
            rest = rest[: -len(CLOSE)]
        title, *more = re.split(r"\r\n|\n|\r", rest)
        result = tag_annotation(
            source,
            match,
            canonical,
            line=comment.line,
            end_line=comment.end_line,
            col=comment.col,
            slot_col=comment.col + match.end("tag"),
            title=title,
            description=textwrap.dedent("\n".join(line.rstrip() for line in more)).strip("\n"),
            symbol=structure.heading_for(comment.line),
            trailing=not comment.standalone,
        )
        if isinstance(result, Diagnostic):
            diagnostics.append(result)
        else:
            found.append(result)
    return found, diagnostics


def _body(comment: str) -> str:
    body = comment[len(OPEN) :]
    return body.removesuffix(CLOSE)


def without_comments(text: str) -> str:
    """The document with every HTML comment removed: what an annotation edit must not change."""
    kept, pos = [], 0
    for comment in parse_markdown(text).comments:
        kept.append(text[pos : comment.start])
        pos = comment.end
    kept.append(text[pos:])
    return "".join(kept)


def ensure_markdown_equivalent(path: str, before: str, after: str) -> None:
    if without_comments(before) != without_comments(after):
        msg = f"{path}: edit would change text outside comments; nothing was written"
        raise EditError(msg)
