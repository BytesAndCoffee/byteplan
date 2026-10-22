# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

from byteplan.config import DetectConfig
from byteplan.diagnostics import Code
from byteplan.errors import SourceError
from byteplan.models import IdSlot
from byteplan.scanner import FileScan, scan_file
from byteplan.scanner.source import decode_source

if TYPE_CHECKING:
    from byteplan.models import Annotation


def scan(code: str, *, tags: tuple[str, ...] = DetectConfig().todo_tags, dedent: bool = True) -> FileScan:
    text = textwrap.dedent(code) if dedent else code
    # Stub detection is covered in test_stubs.py; keep these tests about comments.
    no_stubs = DetectConfig(
        todo_tags=tags, pass_stubs=False, ellipsis_stubs=False, not_implemented_stubs=False, empty_classes=False
    )
    return scan_file(decode_source("mod.py", text.encode()), no_stubs)


def only(code: str) -> Annotation:
    result = scan(code)
    assert len(result.tags) == 1, result.tags
    return result.tags[0]


def test_single_line_todo() -> None:
    tag = only("# TODO: Implement route poisoning\n")
    assert (tag.kind, tag.title, tag.description, tag.task_id) == ("TODO", "Implement route poisoning", "", None)
    assert (tag.line, tag.col) == (1, 0)
    assert tag.id_slot == IdSlot(1, len("# TODO"), "[{id}]")


def test_tagged_comment_has_no_id_slot() -> None:
    assert only("# TODO[7fa2]: x\n").id_slot is None


@pytest.mark.parametrize("kind", ["TODO", "FIXME", "HACK", "XXX"])
def test_all_default_kinds(kind: str) -> None:
    assert only(f"# {kind}: thing\n").kind == kind


def test_case_insensitive_with_canonical_kind() -> None:
    tag = only("#todo  lower case works\n")
    assert (tag.kind, tag.tag_text, tag.title) == ("TODO", "todo", "lower case works")


def test_tag_without_colon_or_title() -> None:
    assert only("# FIXME\n").title == ""
    assert only("# FIXME needs work\n").title == "needs work"


def test_existing_id_is_read() -> None:
    tag = only("# TODO[7fa2]: tagged\n")
    assert (tag.task_id, tag.title) == ("7fa2", "tagged")


@pytest.mark.parametrize("code", ["# TODOS are fun\n", "# TODO-list\n", "# a TODO in prose\n", "# x = f()  # TODO\n"])
def test_not_tags(code: str) -> None:
    assert scan(code).tags == []


def test_strings_and_docstrings_are_ignored() -> None:
    code = '''
    """Module docstring. TODO: not a task."""
    s = "# TODO: not a task"
    t = """
    # FIXME: still a string
    """
    def f():
        """TODO: docstring"""
    '''
    assert scan(code).tags == []


def test_trailing_comment_is_a_tag_without_continuation() -> None:
    result = scan("""
    x = 1  # FIXME: trailing
    #   not a continuation of a trailing tag
    """)
    assert len(result.tags) == 1
    assert result.tags[0].trailing
    assert result.tags[0].description == ""


def test_multiline_continuation_keeps_relative_indentation() -> None:
    tag = only("""
    # TODO: Implement route poisoning
    #   Support split horizon and poisoned reverse.
    #     - nested detail
    """)
    assert tag.description == "Support split horizon and poisoned reverse.\n  - nested detail"
    assert (tag.line, tag.end_line) == (2, 4)


@pytest.mark.parametrize(
    ("terminator", "reason"),
    [
        ("\n#   after blank line\n", "blank line"),
        ("x = 1\n#   after code\n", "code"),
        ("# ordinary comment\n#   after ordinary\n", "ordinary comment"),
        ("#\n#   after empty comment\n", "empty comment"),
        ("  #   different column\n", "different column"),
    ],
)
def test_continuation_terminators(terminator: str, reason: str) -> None:
    code = "# TODO: first\n#   kept\n" + terminator
    tag = scan(code, dedent=False).tags[0]
    assert tag.description == "kept", reason


def test_another_tag_ends_the_block() -> None:
    result = scan("""
    # TODO: one
    #   detail one
    #   FIXME: two
    #   detail two
    """)
    assert [(t.kind, t.title, t.description) for t in result.tags] == [
        ("TODO", "one", "detail one"),
        ("FIXME", "two", "detail two"),
    ]


def test_indented_block_inside_function() -> None:
    tag = only("""
    def f():
        # TODO: inner
        #   more
        return 1
    """)
    assert (tag.col, tag.symbol, tag.description) == (4, "f", "more")


def test_symbol_for_block_attached_to_declaration() -> None:
    result = scan("""
    class Router:
        # TODO: Implement route updates
        @staticmethod
        def send_route_update():
            raise NotImplementedError

        def other(self):
            def inner():
                pass  # HACK: nested
    """)
    assert [t.symbol for t in result.tags] == ["Router.send_route_update", "Router.other.<locals>.inner"]


def test_module_level_symbol_is_none() -> None:
    assert only("# TODO: module level\nx = 1\n").symbol is None


def test_malformed_id_is_reported_and_not_tracked() -> None:
    result = scan("# TODO[ZZ12]: bad\n# TODO[7FA2]: uppercase\n")
    assert result.tags == []
    assert [d.code for d in result.diagnostics] == [Code.MALFORMED_ID, Code.MALFORMED_ID]
    assert result.diagnostics[0].locations[0].line == 1


def test_ignore_suppresses_one_tag() -> None:
    result = scan("""
    # TODO: tracked
    # TODO: not tracked  byteplan: ignore
    """)
    assert [t.title for t in result.tags] == ["tracked"]


def test_ignore_file() -> None:
    assert scan("#!/usr/bin/env python\n# byteplan: ignore-file\n# TODO: x\n").tags == []


def test_ignore_file_only_near_top() -> None:
    code = "\n" * 6 + "# byteplan: ignore-file\n# TODO: x\n"
    assert len(scan(code, dedent=False).tags) == 1


def test_custom_tags() -> None:
    result = scan("# NOTE: a\n# TODO: b\n# REVIEW: c\n", tags=("REVIEW", "NOTE"))
    assert [t.kind for t in result.tags] == ["NOTE", "REVIEW"]


def test_crlf_and_non_ascii() -> None:
    tag = only("# TODO: Überprüfen\r\n#   路由 détail\r\nx = 1\r\n")
    assert (tag.title, tag.description) == ("Überprüfen", "路由 détail")


def test_unparseable_file_raises() -> None:
    with pytest.raises(SourceError, match="syntax error"):
        scan("def f(:\n    pass\n")
