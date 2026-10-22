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


# Codex review of #20 ------------------------------------------------------------------------------


@pytest.mark.parametrize("marker", ["-", "*", "+", "1.", "2)", "> -", "- >"])
def test_fence_opened_on_a_list_item_line(marker: str) -> None:
    text = f"{marker} ```html\n  <!-- TODO: example -->\n  ```\n\n<!-- TODO: real -->\n"
    assert titles(text) == ["real"]


def test_inline_code_spans_continue_over_paragraph_lines() -> None:
    text = "Inline code `example\n<!-- TODO: not real -->\nend` then <!-- TODO: real -->\n"
    assert titles(text) == ["real"]
    assert titles("Double ``code ` with\n<!-- TODO: no -->\n`` end\n<!-- TODO: yes -->\n") == ["yes"]


def test_unclosed_code_span_ends_at_the_paragraph() -> None:
    # A blank line, fence or heading ends the paragraph, so these backticks are literal.
    assert titles("A ` tick\n\n<!-- TODO: after blank -->\n") == ["after blank"]
    assert titles("A ` tick\n# Heading <!-- TODO: in heading -->\n`\n") == ["in heading"]


def test_comment_opened_first_hides_backticks() -> None:
    assert titles("<!-- TODO: has ` a tick -->\nand ` another\n") == ["has ` a tick"]


def test_lines_inside_a_multi_line_code_span_are_not_headings() -> None:
    text = "# Real\nText `span\nNot a heading\n---` <!-- TODO: x -->\n"
    assert scan(text).tags[0].symbol == "Real"


# Link-reference comments: [//]: # (...) ------------------------------------------------------------


def test_link_reference_comments() -> None:
    text = """\
        # Guide

        [//]: # (TODO: Rewrite the intro)
        [comment]: # "FIXME[7fa2]: Fix the example"
          [_]: # 'HACK: single quotes, indented'
        """
    tags = scan(text).tags
    assert [(t.kind, t.task_id, t.title, t.line, t.col, t.symbol, t.trailing) for t in tags] == [
        ("TODO", None, "Rewrite the intro", 3, 0, "Guide", False),
        ("FIXME", "7fa2", "Fix the example", 4, 0, "Guide", False),
        ("HACK", None, "single quotes, indented", 5, 2, "Guide", False),
    ]
    assert tags[0].id_slot == IdSlot(3, 13, "[{id}]")
    assert tags[0].attachment_kind is AttachmentKind.MODULE


def test_link_reference_comment_continuation() -> None:
    text = """\
        [//]: # (TODO: Document the merge driver)
        [//]: # (  Show the .gitattributes line.)
        [//]: # (    And a conflict example.)
        [//]: # (Not indented: not a continuation)
        """
    (tag,) = scan(text).tags
    assert (tag.title, tag.description, tag.end_line) == (
        "Document the merge driver",
        "Show the .gitattributes line.\n  And a conflict example.",
        3,
    )


def test_link_reference_comment_title_with_parentheses() -> None:
    assert titles("[//]: # (TODO: call f(x) twice)\n") == ["call f(x) twice"]


@pytest.mark.parametrize(
    "text",
    [
        "A paragraph line\n[//]: # (TODO: no, it would continue the paragraph)\n",
        "- list item\n[//]: # (TODO: no, lazy continuation)\n",
        "```\n[//]: # (TODO: no, in a fence)\n```\n",
        "[//]: <https://example.com> (TODO: no, not a # destination)\n",
        "[//]: # (see TODO: the tag must open the title)\n",
        "    [//]: # (TODO: no, four spaces is too deep)\n",
        "Inline `code\n[//]: # (TODO: no, inside a code span)\nend`\n",
    ],
)
def test_link_reference_comments_only_where_definitions_are(text: str) -> None:
    assert scan(text, dedent=False).tags == []


def test_link_reference_comment_after_a_heading_or_html_comment() -> None:
    text = "# H\n[//]: # (TODO: after a heading)\n<!-- x -->\n[//]: # (TODO: after a comment)\n"
    assert titles(text) == ["after a heading", "after a comment"]


def test_link_reference_comment_ignore_markers() -> None:
    assert titles("[//]: # (TODO: skip byteplan: ignore)\n\n[//]: # (TODO: keep)\n") == ["keep"]
    assert titles("[//]: # (byteplan: ignore-file)\n\n[//]: # (TODO: x)\n<!-- TODO: y -->\n") == []


def test_edit_guard_covers_link_reference_comments() -> None:
    before = "[//]: # (TODO: x)\ntext\n"
    ensure_unchanged("a.md", before, "[//]: # (TODO[7fa2]: x)\ntext\n", ("TODO",))
    with pytest.raises(EditError, match="outside comments"):
        ensure_unchanged("a.md", before, "[//]: # (TODO: x)\ntext!\n", ("TODO",))
