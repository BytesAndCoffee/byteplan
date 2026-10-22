# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Phase 4e: tags in JSON comments and tagged string values."""

from __future__ import annotations

import textwrap

import pytest

from byteplan.config import DetectConfig
from byteplan.diagnostics import Code
from byteplan.errors import EditError, SourceError
from byteplan.models import AttachmentKind, IdSlot
from byteplan.scanner import FileScan, ensure_unchanged, scan_file
from byteplan.scanner.source import decode_source

TAGS = DetectConfig().todo_tags


def scan(text: str, *, path: str = "config.json", detect: DetectConfig | None = None) -> FileScan:
    return scan_file(decode_source(path, textwrap.dedent(text).encode()), detect or DetectConfig())


def summary(text: str, *, detect: DetectConfig | None = None) -> list[tuple[str, str | None]]:
    return [(t.title, t.symbol) for t in scan(text, detect=detect).tags]


def test_line_comment_with_continuation() -> None:
    (tag,) = scan(
        """\
        {
          // TODO: Turn on strict mode
          //   once the legacy modules are typed
          //   and the shared base config moves
          // not a continuation: only one space
          "strict": false
        }
        """
    ).tags
    assert (tag.line, tag.end_line, tag.col) == (2, 4, 2)
    assert tag.title == "Turn on strict mode"
    assert tag.description == "once the legacy modules are typed\nand the shared base config moves"
    assert tag.symbol == "/strict"
    assert tag.id_slot == IdSlot(2, 9, "[{id}]")
    assert tag.attachment_kind is AttachmentKind.MODULE


def test_block_comment_strips_javadoc_stars() -> None:
    (tag,) = scan(
        """\
        {
          /* FIXME[7fa2]: Paths drift between packages
           * Keep them in one place.
           *   Indented detail.
           */
          "paths": {}
        }
        """,
        path="tsconfig.jsonc",
    ).tags
    assert (tag.task_id, tag.title, tag.end_line, tag.symbol) == ("7fa2", "Paths drift between packages", 5, "/paths")
    assert tag.description == "Keep them in one place.\n  Indented detail."
    assert summary('{"a": 1 /* TODO: inline block */}') == [("inline block", "/a")]
    assert scan("/* TODO: plain\n   block lines\n*/\n{}").tags[0].description == "block lines"


def test_comment_symbols() -> None:
    text = """\
        // TODO: top of file
        {
          "outer": {
            "a": 1, // TODO: trailing follows a
            // TODO: last in object
          },
          "list": [
            // TODO: before element
            "x"
          ] /* TODO: trailing after a container */
        }
        """
    assert summary(text) == [
        ("top of file", None),
        ("trailing follows a", "/outer/a"),
        ("last in object", "/outer"),
        ("before element", "/list/0"),
        ("trailing after a container", "/list"),
    ]
    assert summary('{"a": "TODO: x"} // TODO: after the root') == [("x", "/a"), ("after the root", None)]


def test_string_values() -> None:
    text = r"""
        {
          "scripts": {"todo": "TODO: pin the version"},
          "a/b~c": ["x", "FIXME[7fa2]: escaped \"title\"\nand a description"],
          "TODO: keys never match": "Todo: lowercase never matches",
          "plain": "TODO without a colon is data"
        }
        """
    tags = scan(text).tags
    assert [(t.kind, t.task_id, t.title, t.description, t.symbol) for t in tags] == [
        ("TODO", None, "pin the version", "", "/scripts/todo"),
        ("FIXME", "7fa2", 'escaped "title"', "and a description", "/a~1b~0c/1"),
    ]
    assert tags[0].id_slot == IdSlot(3, 27, "[{id}]")
    assert summary('"TODO: a top-level string"') == [("a top-level string", None)]


def test_string_values_can_be_turned_off() -> None:
    detect = DetectConfig(json_string_values=False)
    assert summary('{"a": "TODO: x"} // TODO: y', detect=detect) == [("y", None)]


def test_trailing_commas_and_literals() -> None:
    assert summary('{"a": [1, -2.5e3, true, null,], // TODO: ok\n}') == [("ok", "/a")]


def test_ignore_markers_and_malformed_ids() -> None:
    assert summary('{"a": "TODO: skip byteplan: ignore", "b": "TODO: keep"}') == [("keep", "/b")]
    assert summary('// byteplan: ignore-file\n{"a": "TODO: x"}') == []
    result = scan('{"a": "TODO[nope]: x"} // FIXME[ABCD]: y')
    assert result.tags == []
    assert [d.code for d in result.diagnostics] == [Code.MALFORMED_ID, Code.MALFORMED_ID]


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ('{"a": "x', "unterminated string"),
        ('{"a": "x\n"}', "unterminated string"),
        ("{} /* x", "unterminated comment"),
        ('{"a": 1', "unclosed"),
        ('{"a": 1]', "unexpected ']'"),
        ('{"a" 1}', "expected an object key"),
        ('{"a": 1 2}', "expected ','"),
        ("[1,,2]", "unexpected ','"),
        ("{} {}", "after the top-level value"),
        ('{"a":: 1}', "unexpected ':'"),
        ('{"\\x": 1}', "invalid string escape"),
        ("{'a': 1}", "expected an object key"),
    ],
)
def test_lexer_errors_fail_the_scan(text: str, reason: str) -> None:
    with pytest.raises(SourceError, match=reason):
        scan(text)


def test_edit_guard_allows_only_comments_and_tag_ids() -> None:
    before = '{"a": "TODO: x", "b": 1} // TODO: y\n'
    ensure_unchanged("a.json", before, '{"a": "TODO[7fa2]: x", "b": 1} // TODO[1234]: y\n', TAGS)
    with pytest.raises(EditError, match="change JSON data"):
        ensure_unchanged("a.json", before, '{"a": "TODO: x!", "b": 1} // TODO: y\n', TAGS)
    with pytest.raises(EditError, match="change JSON data"):
        ensure_unchanged("a.json", before, '{"a": "TODO[7fa2]x", "b": 1}\n', TAGS)
    with pytest.raises(EditError, match="no longer parses"):
        ensure_unchanged("a.json", before, '{"a": "TODO: x", "b": 1\n', TAGS)
