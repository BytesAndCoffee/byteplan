# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Tags in JSON: comments (JSONC) and tagged string values.

Grammar:

* ``// TODO: title`` takes continuation lines exactly as a Python ``#`` comment does
  (the next line, same column, two spaces after ``//``). ``/* TODO: title ... */``
  takes its later lines as the description, minus a Javadoc-style leading ``*``.
  The tag must open the comment, with the usual ``[id]`` and case rules.
* A value string (never a key) that starts with a tag, an optional ``[id]`` and a
  colon is a task: ``"TODO: pin the version"``. Matching is case-sensitive and the
  colon is required, so data like ``"Todo: buy milk"`` is left alone. The ID is written
  inside the string. A ``\\n`` in the value separates the title from the description.
* Symbols are JSON Pointers: a string value's own pointer; for a comment, the member
  it precedes (or, trailing, the member it follows), else its container.
* ``byteplan: ignore`` in a tag suppresses it; ``// byteplan: ignore-file`` within the
  first five lines suppresses the file.

The lexer is tolerant (comments, trailing commas) but otherwise strict: unterminated
strings or comments, mismatched brackets, invalid literals and invalid string escapes
fail the scan, so BytePlan never writes into malformed JSON.
"""

from __future__ import annotations

import dataclasses
import json
import re
import textwrap
from dataclasses import dataclass
from typing import TYPE_CHECKING

from byteplan.diagnostics import Diagnostic
from byteplan.edits import line_offsets
from byteplan.errors import EditError, SourceError
from byteplan.ids import ID_RE
from byteplan.scanner.comments import IGNORE_FILE_MAX_LINE, IGNORE_RE, tag_annotation, tag_pattern

if TYPE_CHECKING:
    from collections.abc import Sequence

    from byteplan.config import DetectConfig
    from byteplan.models import Annotation
    from byteplan.scanner.source import SourceFile

CONTINUATION_INDENT = "  "
_PUNCTUATION = frozenset("{}[]:,")
_LITERAL_RE = re.compile(r"[^\s{}\[\]:,\"/]+")
_VALID_LITERAL_RE = re.compile(r"true|false|null|-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
_NEWLINE_RE = re.compile(r"\r\n|\n|\r")
_IGNORE_FILE_RE = re.compile(r"^(?://|/\*)\s*byteplan:\s*ignore-file\b", re.IGNORECASE)


@dataclass(frozen=True)
class Token:
    kind: str  # one of "{}[]:,", "string", "literal", "line_comment", "block_comment"
    text: str  # raw source text
    offset: int
    line: int
    col: int
    standalone: bool = False  # comments: nothing but whitespace before it on its line
    # Values and closing brackets: their (container's) JSON Pointer; comments: their symbol.
    pointer: str | None = None
    is_value: bool = False  # strings: a value rather than an object key


def _escape(key: str) -> str:
    return key.replace("~", "~0").replace("/", "~1")


def tokenize_json(path: str, text: str) -> list[Token]:
    """Lex ``text`` and give every value and comment its JSON Pointer."""
    offsets = line_offsets(text)
    tokens: list[Token] = []
    line, pos = 1, 0

    def position(offset: int) -> tuple[int, int]:
        nonlocal line
        while line < len(offsets) and offsets[line] <= offset:
            line += 1
        return line, offset - offsets[line - 1]

    def fail(offset: int, reason: str) -> SourceError:
        where, col = position(offset)
        return SourceError(path, f"invalid JSON at line {where}, column {col + 1}: {reason}")

    while pos < len(text):
        char = text[pos]
        if char.isspace() or char == "﻿":
            pos += 1
            continue
        start = pos
        if char in _PUNCTUATION:
            kind, pos = char, pos + 1
        elif char == '"':
            pos += 1
            while pos < len(text) and text[pos] != '"':
                if text[pos] in "\r\n":
                    raise fail(start, "unterminated string")
                pos += 2 if text[pos] == "\\" else 1
            if pos >= len(text):
                raise fail(start, "unterminated string")
            kind, pos = "string", pos + 1
        elif text.startswith("//", pos):
            newline = _NEWLINE_RE.search(text, pos)
            kind, pos = "line_comment", newline.start() if newline else len(text)
        elif text.startswith("/*", pos):
            end = text.find("*/", pos + 2)
            if end < 0:
                raise fail(start, "unterminated comment")
            kind, pos = "block_comment", end + 2
        else:
            literal = _LITERAL_RE.match(text, pos)
            if literal is None:
                raise fail(start, f"unexpected {char!r}")
            kind, pos = "literal", literal.end()
        row, col = position(start)
        before = text[offsets[row - 1] : start]
        tokens.append(Token(kind, text[start:pos], start, row, col, standalone=not before.strip(" \t﻿")))
    return _comment_symbols(_assign_pointers(path, tokens))


@dataclass
class _Frame:
    opener: Token
    pointer: str
    is_object: bool
    index: int = 0
    key: str | None = None
    colon: bool = False  # objects: the current member's ':' has been seen
    filled: bool = False  # the current member's value has been seen


_COMMENTS = frozenset({"line_comment", "block_comment"})


def _assign_pointers(path: str, tokens: list[Token]) -> list[Token]:
    stack: list[_Frame] = []
    result: list[Token] = []
    top_level_done = False

    def error(token: Token, reason: str) -> SourceError:
        return SourceError(path, f"invalid JSON at line {token.line}, column {token.col + 1}: {reason}")

    for token in tokens:
        frame = stack[-1] if stack else None
        if token.kind in _COMMENTS:
            result.append(token)
        elif token.kind == "string" and frame is not None and frame.is_object and frame.key is None:
            try:
                frame.key = json.loads(token.text)
            except ValueError:
                raise error(token, "invalid string escape") from None
            result.append(token)
        elif token.kind == ":":
            if frame is None or not frame.is_object or frame.key is None or frame.colon:
                raise error(token, "unexpected ':'")
            frame.colon = True
            result.append(token)
        elif token.kind == ",":
            if frame is None or not frame.filled:
                raise error(token, "unexpected ','")
            frame.index += 1
            frame.key, frame.colon, frame.filled = None, False, False
            result.append(token)
        elif token.kind in {"}", "]"}:
            if frame is None or frame.is_object != (token.kind == "}") or (frame.key is not None and not frame.filled):
                raise error(token, f"unexpected {token.kind!r}")
            stack.pop()
            result.append(dataclasses.replace(token, pointer=frame.pointer))  # the container it closes
        else:  # a value: string, literal, or an opening bracket
            if frame is None:
                if top_level_done:
                    raise error(token, "unexpected content after the top-level value")
                pointer = ""
                top_level_done = True
            elif frame.filled or (frame.is_object and not frame.colon):
                raise error(token, "expected ',' or a closing bracket" if frame.filled else "expected an object key")
            else:
                key = _escape(frame.key) if frame.is_object and frame.key is not None else str(frame.index)
                pointer = f"{frame.pointer}/{key}"
                frame.filled = True
            if token.kind == "literal" and not _VALID_LITERAL_RE.fullmatch(token.text):
                raise error(token, f"invalid value {token.text!r}")
            if token.kind == "string":
                try:
                    json.loads(token.text)
                except ValueError:
                    raise error(token, "invalid string escape") from None
            if token.kind in {"{", "["}:
                stack.append(_Frame(token, pointer, is_object=token.kind == "{"))
            result.append(dataclasses.replace(token, pointer=pointer, is_value=True))
    if stack:
        raise error(stack[-1].opener, f"unclosed {stack[-1].opener.kind!r}")
    return result


def _comment_symbols(tokens: list[Token]) -> list[Token]:
    """A comment's symbol: the member it precedes, or (trailing) the one it follows,
    else its container (None at the top level)."""
    result: list[Token] = []
    containers: list[str] = []
    for index, token in enumerate(tokens):
        if token.kind in {"{", "["} and token.pointer is not None:
            containers.append(token.pointer)
        elif token.kind in {"}", "]"} and containers:
            containers.pop()
        if token.kind not in _COMMENTS:
            result.append(token)
            continue
        symbol: str | None = None
        if token.standalone:
            following = (t for t in tokens[index + 1 :] if t.kind not in _COMMENTS and t.kind != ":")
            nxt = next(following, None)
            if nxt is not None and nxt.kind == "string" and not nxt.is_value:  # an object key
                nxt = next(following, None)
            if nxt is not None and nxt.is_value:
                symbol = nxt.pointer
        else:  # trailing: the value (or container) that ends just before it
            prev = next((t for t in reversed(result) if t.kind not in _COMMENTS and t.kind != ","), None)
            symbol = prev.pointer if prev is not None else None
        if symbol is None and containers:
            symbol = containers[-1]
        result.append(dataclasses.replace(token, pointer=symbol or None))
    return result


def _comment_body(token: Token) -> str:
    """Comment text after the opener (and before ``*/``)."""
    body = token.text[2:]
    return body[:-2] if token.kind == "block_comment" else body


def _block_description(lines: list[str]) -> str:
    """Later lines of a block comment, minus a Javadoc-style leading ``*`` on every line."""
    stripped = [line.rstrip() for line in lines]
    while stripped and not stripped[-1].strip():
        stripped.pop()
    if stripped and all(line.lstrip().startswith("*") for line in stripped if line.strip()):
        stripped = [re.sub(r"^\s*\* ?", "", line) for line in stripped]
    return textwrap.dedent("\n".join(stripped)).strip("\n")


def scan_json(source: SourceFile, detect: DetectConfig) -> tuple[list[Annotation], list[Diagnostic]]:
    tokens = tokenize_json(source.path, source.text)
    comments = [t for t in tokens if t.kind in _COMMENTS]
    if any(c.line <= IGNORE_FILE_MAX_LINE and _IGNORE_FILE_RE.match(c.text) for c in comments):
        return [], []
    tags = detect.todo_tags
    canonical = {tag.upper(): tag for tag in tags}
    patterns = {"line_comment": tag_pattern(tags, opener="//"), "block_comment": tag_pattern(tags, opener=r"/\*")}
    alternatives = "|".join(re.escape(tag) for tag in sorted(tags, key=len, reverse=True))
    string_pattern = re.compile(rf'"(?P<tag>{alternatives})(?:\[(?P<id>[^\]"]*)\])?(?P<rest>:.*)"', re.DOTALL)

    found: list[Annotation] = []
    diagnostics: list[Diagnostic] = []

    def add(result: Annotation | Diagnostic) -> None:
        if isinstance(result, Diagnostic):
            diagnostics.append(result)
        else:
            found.append(result)

    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if token.kind == "string" and token.is_value and detect.json_string_values:
            match = string_pattern.fullmatch(token.text)
            if match is None or IGNORE_RE.search(token.text):
                continue
            title, _, description = json.loads(f'"{match.group("rest")}"').partition("\n")
            add(
                tag_annotation(
                    source,
                    match,
                    canonical,
                    line=token.line,
                    end_line=token.line,
                    col=token.col,
                    slot_col=token.col + match.end("tag"),
                    title=title,
                    description=textwrap.dedent(description).strip("\n"),
                    symbol=token.pointer or None,
                    trailing=False,
                )
            )
            continue
        if token.kind not in _COMMENTS:
            continue
        match = patterns[token.kind].fullmatch(token.text)
        if match is None or "\n" in token.text[: match.end("tag")] or "\r" in token.text[: match.end("tag")]:
            continue
        end_line = token.line
        if token.kind == "line_comment":
            title, description = match.group("rest"), []
            if token.standalone:
                while index < len(tokens):
                    nxt = tokens[index]
                    body = _comment_body(nxt)
                    if (
                        nxt.kind != "line_comment"
                        or nxt.line != end_line + 1
                        or not nxt.standalone
                        or nxt.col != token.col
                        or patterns["line_comment"].fullmatch(nxt.text)
                        or not body.startswith(CONTINUATION_INDENT)
                        or not body.strip()
                    ):
                        break
                    description.append(body.rstrip())
                    end_line = nxt.line
                    index += 1
            text = textwrap.dedent("\n".join(description))
        else:
            first, *more = _NEWLINE_RE.split(match.group("rest")[:-2])
            title, text = first, _block_description(more)
            end_line = token.line + len(_NEWLINE_RE.findall(token.text))
        if IGNORE_RE.search(token.text):
            continue
        add(
            tag_annotation(
                source,
                match,
                canonical,
                line=token.line,
                end_line=end_line,
                col=token.col,
                slot_col=token.col + match.end("tag"),
                title=title,
                description=text,
                symbol=token.pointer,
                trailing=not token.standalone,
            )
        )
    return found, diagnostics


def _structure(text: str, path: str, tags: Sequence[str]) -> list[tuple[str, str]]:
    """Tokens without comments, with a tagged string's ``[id]`` removed."""
    alternatives = "|".join(re.escape(tag) for tag in sorted(tags, key=len, reverse=True))
    tagged = re.compile(rf'^"({alternatives})\[{ID_RE.pattern}\]:')
    return [
        (t.kind, tagged.sub(r'"\1:', t.text) if t.kind == "string" and t.is_value else t.text)
        for t in tokenize_json(path, text)
        if t.kind not in _COMMENTS
    ]


def ensure_json_equivalent(path: str, before: str, after: str, tags: Sequence[str]) -> None:
    """Refuse an edit that changes JSON data, other than adding ``[id]`` to tagged strings."""
    try:
        same = _structure(before, path, tags) == _structure(after, path, tags)
    except SourceError as exc:
        msg = f"{path}: edited JSON no longer parses ({exc.reason}); nothing was written"
        raise EditError(msg) from exc
    if not same:
        msg = f"{path}: edit would change JSON data; nothing was written"
        raise EditError(msg)
