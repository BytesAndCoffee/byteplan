# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Lossless source decoding.

The decoded text keeps the file's original newlines, and ``encode()`` round-trips
to the exact original bytes (including a UTF-8 BOM and a missing final newline),
so edits only touch the characters they mean to.
"""

from __future__ import annotations

import io
import re
import tokenize
from dataclasses import dataclass
from typing import TYPE_CHECKING

from byteplan.errors import SourceError

if TYPE_CHECKING:
    from pathlib import Path

_NEWLINE_RE = re.compile(r"\r\n|\n|\r")


@dataclass(frozen=True)
class SourceFile:
    path: str
    text: str
    encoding: str
    newline: str

    def encode(self) -> bytes:
        return self.text.encode(self.encoding)

    def readline_io(self) -> io.StringIO:
        # newline="" splits on \n, \r\n and \r without translating them.
        return io.StringIO(self.text, newline="")


def decode_source(path: str, data: bytes) -> SourceFile:
    try:
        encoding, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    except SyntaxError as exc:
        raise SourceError(path, f"cannot determine encoding: {exc.msg}") from exc
    try:
        text = data.decode(encoding)
    except (UnicodeDecodeError, LookupError) as exc:
        raise SourceError(path, f"cannot decode as {encoding}: {exc}") from exc
    match = _NEWLINE_RE.search(text)
    return SourceFile(path=path, text=text, encoding=encoding, newline=match.group() if match else "\n")


def read_source(root: Path, path: str) -> SourceFile:
    try:
        data = (root / path).read_bytes()
    except OSError as exc:
        raise SourceError(path, f"cannot read: {exc.strerror}") from exc
    return decode_source(path, data)
