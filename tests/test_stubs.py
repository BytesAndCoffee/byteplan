# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Stub detection, exclusions, suppressions, and association (spec 2, 3, 4)."""

from __future__ import annotations

import textwrap

import pytest

from byteplan.config import DetectConfig
from byteplan.diagnostics import Code
from byteplan.models import Annotation, AttachmentKind, Origin
from byteplan.scanner import FileScan, scan_file
from byteplan.scanner.source import decode_source


def scan(code: str, detect: DetectConfig | None = None) -> FileScan:
    source = decode_source("mod.py", textwrap.dedent(code).encode())
    return scan_file(source, detect or DetectConfig())


def stub_symbols(code: str, detect: DetectConfig | None = None) -> list[str | None]:
    return [a.symbol for a in scan(code, detect).tags if a.origin is Origin.STUB]


@pytest.mark.parametrize(
    ("code", "symbol"),
    [
        ("def f():\n    pass\n", "f"),
        ("def f():\n    ...\n", "f"),
        ("def f():\n    raise NotImplementedError\n", "f"),
        ("def f():\n    raise NotImplementedError('later')\n", "f"),
        ("async def f():\n    pass\n", "f"),
        ('def f():\n    """Only a docstring."""\n', "f"),
        ('def f():\n    """Doc."""\n    raise NotImplementedError\n', "f"),
        ("class C:\n    pass\n", "C"),
        ("class C:\n    def m(self):\n        ...\n", "C.m"),
        ("def outer():\n    def inner():\n        pass\n    return inner\n", "outer.<locals>.inner"),
    ],
)
def test_stub_shapes(code: str, symbol: str) -> None:
    assert stub_symbols(code) == [symbol]


@pytest.mark.parametrize(
    "code",
    [
        "def f():\n    return 1\n",
        "def f():\n    pass\n    return 1\n",
        "def f():\n    raise ValueError\n",
        "from abc import abstractmethod\nclass A:\n    @abstractmethod\n    def m(self):\n        ...\n",
        "import abc\nclass A:\n    @abc.abstractmethod\n    def m(self):\n        pass\n",
        "from typing import overload\n@overload\ndef f(x: int) -> int:\n    ...\n",
        "import typing\n@typing.overload\ndef f(x: int) -> int: ...\n",
        "from typing import Protocol\nclass P(Protocol):\n    def m(self) -> int:\n        ...\n",
        "import typing\nclass P(typing.Protocol[int]):\n    pass\n",
        "class RoutingError(Exception):\n    pass\n",
        "class Bad(ValueError):\n    pass\n",
        "class Deprecated(UserWarning):\n    pass\n",
        "from enum import Enum\nclass Color(Enum):\n    pass\n",
        "from typing import TypedDict\nclass TD(TypedDict):\n    pass\n",
    ],
    ids=[
        "real-body", "pass-then-code", "other-exception", "abstractmethod", "abc.abstractmethod", "overload",
        "typing.overload", "protocol-method", "protocol-class", "exception-subclass", "error-subclass",
        "warning-subclass", "enum", "typeddict",
    ],
)  # fmt: skip
def test_not_stubs(code: str) -> None:
    assert stub_symbols(code) == []


def test_each_heuristic_can_be_disabled() -> None:
    code = """
    def a():
        pass
    def b():
        ...
    def c():
        raise NotImplementedError
    class D:
        pass
    """
    assert stub_symbols(code, DetectConfig(pass_stubs=False)) == ["b", "c"]
    assert stub_symbols(code, DetectConfig(ellipsis_stubs=False)) == ["a", "c", "D"]
    assert stub_symbols(code, DetectConfig(not_implemented_stubs=False)) == ["a", "b", "D"]
    assert stub_symbols(code, DetectConfig(empty_classes=False)) == ["a", "b", "c"]


@pytest.mark.parametrize(
    "code",
    [
        "def f():  # byteplan: ignore\n    pass\n",
        "@decorator  # byteplan: ignore\ndef f():\n    pass\n",
        "def f(\n    x,  # byteplan: ignore\n):\n    pass\n",
        "# byteplan: ignore-file\ndef f():\n    pass\n",
    ],
    ids=["def-line", "decorator-line", "multiline-header", "ignore-file"],
)
def test_suppression(code: str) -> None:
    assert stub_symbols(code) == []


def test_suppression_applies_to_that_declaration_only() -> None:
    code = """
    class C:  # byteplan: ignore
        def m(self):
            pass
    """
    assert stub_symbols(code) == ["C.m"]


# Association: one obligation, one task (spec 4) -------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "# TODO: implement f\ndef f():\n    pass\n",
        "# TODO: implement f\n@decorator\ndef f():\n    pass\n",
        "def f():\n    # TODO: implement f\n    pass\n",
        'def f():\n    """Doc."""\n    raise NotImplementedError  # TODO: implement f\n',
        "from byteplan_runtime import todo\n@todo('implement f')\ndef f():\n    pass\n",
    ],
    ids=["comment-above", "comment-above-decorators", "comment-in-body", "trailing-in-body", "decorator"],
)
def test_owned_stub_gives_one_task(code: str) -> None:
    tags = scan(code).tags
    assert len(tags) == 1
    assert tags[0].origin is not Origin.STUB
    assert tags[0].symbol == "f"
    assert tags[0].decl_is_stub is True


def test_separated_comment_does_not_own_the_stub() -> None:
    tags = scan("# TODO: something else\n\ndef f():\n    pass\n").tags
    assert [t.origin for t in tags] == [Origin.COMMENT, Origin.STUB]


def test_unowned_stub_proposal_goes_above_first_decorator() -> None:
    code = """
    class Router:
        @property
        @cached
        def table(self):
            raise NotImplementedError
    """
    proposal = only_stub(code)
    assert proposal.title == "Implement Router.table (detected stub)"
    assert proposal.id_slot is not None
    assert (proposal.id_slot.line, proposal.id_slot.col) == (3, 0)
    assert proposal.id_slot.text("abcd") == "    # TODO[abcd]: Implement Router.table (detected stub)\n"
    assert proposal.attachment_kind is AttachmentKind.METHOD


def only_stub(code: str) -> Annotation:
    stubs = [t for t in scan(code).tags if t.origin is Origin.STUB]
    assert len(stubs) == 1
    return stubs[0]


@pytest.mark.parametrize(
    "code",
    ["def f(): pass\n", "class C: ...\n", "if True: x = 1\nelse: x = 2\nclass C: pass\n"],
    ids=["one-line-def", "one-line-class", "after-one-line-suites"],
)
def test_unsafe_stubs_are_reported_not_annotated(code: str) -> None:
    result = scan(code)
    assert [t for t in result.tags if t.origin is Origin.STUB] == []
    assert [d.code for d in result.diagnostics] == [Code.STUB_NEEDS_REVIEW]


def test_custom_tag_list_uses_first_tag_for_stub_comments() -> None:
    result = scan("def f():\n    pass\n", DetectConfig(todo_tags=("FIXME",)))
    assert result.tags[0].kind == "FIXME"
