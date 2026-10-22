# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Phase 4e: tags in Markdown HTML comments."""

from __future__ import annotations

import textwrap

import pytest

from byteplan.config import DetectConfig
from byteplan.diagnostics import Code
from byteplan.errors import EditError
from byteplan.models import AttachmentKind, IdSlot
from byteplan.scanner import FileScan, ensure_unchanged, scan_file
from byteplan.scanner.source import decode_source


def scan(text: str, *, dedent: bool = True, path: str = "README.md") -> FileScan:
    return scan_file(decode_source(path, (textwrap.dedent(text) if dedent else text).encode()), DetectConfig())


def titles(text: str) -> list[str]:
    return [t.title for t in scan(text).tags]


def test_single_line_comment() -> None:
    (tag,) = scan("# Title\n\n<!-- TODO: Rewrite the intro -->\n").tags
    assert (tag.line, tag.end_line, tag.col) == (3, 3, 0)
    assert (tag.kind, tag.task_id, tag.title, tag.description) == ("TODO", None, "Rewrite the intro", "")
    assert tag.id_slot == IdSlot(3, 9, "[{id}]")
    assert tag.attachment_kind is AttachmentKind.MODULE
    assert not tag.trailing


def test_multi_line_comment_has_a_description() -> None:
    (tag,) = scan(
        """\
        <!-- FIXME[7fa2]: Status line undersells the Git integration
             Mention commit-time IDs and the merge driver.

               Before the next release. -->
        """
    ).tags
    assert (tag.line, tag.end_line, tag.task_id) == (1, 4, "7fa2")
    assert tag.title == "Status line undersells the Git integration"
    assert tag.description == "Mention commit-time IDs and the merge driver.\n\n  Before the next release."
    assert tag.id_slot is None


def test_closing_marker_on_its_own_line() -> None:
    (tag,) = scan("<!--\nTODO: not a tag: the tag must be on the opening line\n-->\n<!-- TODO: yes\n-->\n").tags
    assert (tag.title, tag.description, tag.end_line) == ("yes", "", 5)


def test_tag_rules_match_python() -> None:
    assert titles("<!-- todo: lower -->\n<!-- TODO -->\n<!-- TODOS: no -->\n<!-- see TODO: no -->\n") == ["lower", ""]
    assert scan("<!-- todo: x -->").tags[0].kind == "TODO"
    assert titles("<!-- HACK work around -->\n") == ["work around"]


def test_several_comments_on_a_line_and_trailing_comments() -> None:
    tags = scan("Some prose <!-- TODO: one --> and <!-- FIXME: two -->\n").tags
    assert [(t.title, t.col, t.trailing, t.attachment_kind) for t in tags] == [
        ("one", 11, True, AttachmentKind.STATEMENT),
        ("two", 34, True, AttachmentKind.STATEMENT),
    ]


def test_prose_is_not_scanned() -> None:
    assert titles("TODO: this is prose\n\n- [ ] TODO list item\n") == []


@pytest.mark.parametrize(
    "fence",
    [
        "```\n<!-- TODO: no -->\n```\n",
        "~~~html\n<!-- TODO: no -->\n~~~\n",
        "````\n```\n<!-- TODO: no -->\n````\n",  # a shorter run doesn't close
        "```\n<!-- TODO: no -->\n```` \n",  # a longer run does
        "- item\n\n  ```\n  <!-- TODO: no -->\n  ```\n",
        "> ```\n> <!-- TODO: no -->\n> ```\n",
        "```\n<!-- TODO: no -->\n``` info\n<!-- TODO: still no -->\n```\n",  # closers have no info string
    ],
)
def test_fenced_code_is_skipped(fence: str) -> None:
    assert titles(fence + "<!-- TODO: after -->\n") == ["after"]


def test_backtick_fence_info_cannot_contain_backticks() -> None:
    # "```a`b" is inline code, not a fence, so the comment below is real.
    assert titles("```a`b\n<!-- TODO: real -->\n") == ["real"]


def test_inline_code_is_skipped() -> None:
    text = "Write `<!-- TODO: no -->` or ``<!-- TODO: `no` -->``, then <!-- TODO: yes -->\n"
    assert titles(text) == ["yes"]
    assert titles("An unmatched ` backtick <!-- TODO: yes -->\n") == ["yes"]


def test_empty_and_unterminated_comments() -> None:
    assert titles("<!--> <!---> <!-- TODO: after empties -->\n") == ["after empties"]
    (tag,) = scan("<!-- TODO: open\nruns to the end\n").tags
    assert (tag.title, tag.description, tag.end_line) == ("open", "runs to the end", 2)


def test_symbol_is_the_nearest_heading() -> None:
    text = """\
        ---
        title: front matter
        ---
        <!-- TODO: before any heading -->

        # Guide <!-- TODO: in a heading -->

        Setext Section
        --------------
        <!-- TODO: under setext -->

        ## Install ##
        <!-- TODO: under atx -->

        - list item
        ---
        <!-- TODO: thematic break is not a heading -->

        Underlined Twice
        ================
        <!-- TODO: under === -->
        """
    assert [(t.title, t.symbol) for t in scan(text).tags] == [
        ("before any heading", None),
        ("in a heading", "Guide"),
        ("under setext", "Setext Section"),
        ("under atx", "Install"),
        ("thematic break is not a heading", "Install"),
        ("under ===", "Underlined Twice"),
    ]


def test_headings_inside_fences_and_comments_are_ignored() -> None:
    text = "# Real\n```\n# Not a heading\n```\n<!--\n# Nor this\n-->\n<!-- TODO: x -->\n"
    assert scan(text).tags[0].symbol == "Real"


def test_ignore_markers() -> None:
    assert titles("<!-- TODO: skip me byteplan: ignore -->\n<!-- TODO: keep -->\n") == ["keep"]
    assert titles("# Doc\n\n<!-- byteplan: ignore-file -->\n<!-- TODO: x -->\n") == []
    assert titles("1\n2\n3\n4\n5\n<!-- byteplan: ignore-file -->\n<!-- TODO: x -->\n") == ["x"]


def test_malformed_id() -> None:
    result = scan("<!-- TODO[XYZ]: bad -->\n")
    assert result.tags == []
    assert [d.code for d in result.diagnostics] == [Code.MALFORMED_ID]


def test_crlf_and_bom() -> None:
    result = scan_file(decode_source("a.md", b"\xef\xbb\xbf# H\r\n<!-- TODO: a\r\n  more -->\r\n"), DetectConfig())
    (tag,) = result.tags
    assert (tag.title, tag.description, tag.symbol, tag.end_line) == ("a", "more", "H", 3)


def test_markdown_ignores_python_coding_cookies() -> None:
    source = decode_source("a.md", b"# -*- coding: latin-1 -*-\n\xc3\xa9\n")
    assert source.encoding == "utf-8"
    assert source.text == "# -*- coding: latin-1 -*-\né\n"


def test_edit_guard_allows_only_comment_changes() -> None:
    before = "# T\n<!-- TODO: x -->\ntext\n"
    ensure_unchanged("a.md", before, "# T\n<!-- TODO[7fa2]: x -->\ntext\n", ("TODO",))
    with pytest.raises(EditError, match="outside comments"):
        ensure_unchanged("a.md", before, "# T\n<!-- TODO: x -->\ntext!\n", ("TODO",))
