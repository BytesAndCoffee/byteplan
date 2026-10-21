# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

import pytest

from byteplan.edits import Insertion, apply_insertions, ensure_equivalent, line_offsets
from byteplan.errors import EditError


def test_line_offsets_match_tokenize_newlines() -> None:
    assert line_offsets("a\r\nb\nc\rd") == [0, 3, 5, 7]


def test_insertions_apply_right_to_left() -> None:
    text = "# TODO: a\r\n# FIXME: b\r\n"
    edited = apply_insertions(text, [Insertion(1, 6, "[0001]"), Insertion(2, 7, "[0002]")])
    assert edited == "# TODO[0001]: a\r\n# FIXME[0002]: b\r\n"


@pytest.mark.parametrize(
    ("insertions", "message"),
    [
        ([Insertion(3, 0, "x")], "outside the file"),
        ([Insertion(1, 99, "x")], "outside the line"),
        ([Insertion(1, 1, "x"), Insertion(1, 1, "y")], "same position"),
    ],
)
def test_invalid_insertions(insertions: list[Insertion], message: str) -> None:
    with pytest.raises(EditError, match=message):
        apply_insertions("# TODO: a\n", insertions)


def test_equivalence_allows_comment_only_changes() -> None:
    ensure_equivalent("a.py", "x = 1  # TODO: a\n", "x = 1  # TODO[0001]: a\n")


def test_equivalence_refuses_code_changes() -> None:
    with pytest.raises(EditError, match="change program structure"):
        ensure_equivalent("a.py", "x = 1\n", "x = 2\n")


def test_equivalence_refuses_unparseable_result() -> None:
    with pytest.raises(EditError, match="no longer parses"):
        ensure_equivalent("a.py", "x = 1\n", "x = (\n")
