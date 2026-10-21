# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from byteplan.errors import SourceError
from byteplan.scanner.source import decode_source


@pytest.mark.parametrize(
    ("data", "encoding", "newline"),
    [
        (b"x = 1\n", "utf-8", "\n"),
        (b"x = 1\r\ny = 2\r\n", "utf-8", "\r\n"),
        (b"x = 1", "utf-8", "\n"),  # no final newline
        (b"\xef\xbb\xbfx = 1\n", "utf-8-sig", "\n"),  # BOM
        (b"# -*- coding: latin-1 -*-\nname = '\xe9'\n", "iso-8859-1", "\n"),
        ("# TODO: Überprüfen 路由\n".encode(), "utf-8", "\n"),
    ],
)
def test_decode_round_trips_exact_bytes(data: bytes, encoding: str, newline: str) -> None:
    source = decode_source("a.py", data)
    assert source.encoding == encoding
    assert source.newline == newline
    assert source.encode() == data


def test_bom_is_not_part_of_text() -> None:
    assert decode_source("a.py", b"\xef\xbb\xbfx = 1\n").text == "x = 1\n"


def test_undecodable_file_is_a_source_error() -> None:
    with pytest.raises(SourceError, match=r"^a\.py: cannot"):
        decode_source("a.py", b"x = '\xff\xfe'\n")


def test_bytes_invalid_for_declared_encoding_is_a_source_error() -> None:
    with pytest.raises(SourceError, match="cannot decode as ascii"):
        decode_source("a.py", b"# coding: ascii\nx = '\xe9'\n")


def test_bad_coding_cookie_is_a_source_error() -> None:
    with pytest.raises(SourceError, match="encoding"):
        decode_source("a.py", b"# -*- coding: not-a-codec -*-\n")
