# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

import functools
import inspect
import json
import subprocess
import sys
import textwrap
from typing import Any, Callable, TypeVar

import pytest

import byteplan_runtime
from byteplan_runtime import todo, verifies

F = TypeVar("F", bound=Callable[..., Any])


def test_todo_returns_the_identical_function() -> None:
    def f() -> int:
        return 1

    before = dict(vars(f))
    assert todo("x")(f) is f
    assert todo("x", id="a83f", kind="FIXME", description="d", tests=("t.py::t",))(f) is f
    assert vars(f) == before
    assert f() == 1


def test_todo_returns_identical_async_function_and_class() -> None:
    async def coro() -> None:
        pass

    class C:
        pass

    assert todo("x")(coro) is coro
    assert inspect.iscoroutinefunction(todo("x")(coro))
    assert todo("x")(C) is C
    assert vars(C) == vars(todo("y")(C))


def test_verifies_returns_identical_object() -> None:
    def test_something() -> None:
        pass

    assert verifies("a83f")(test_something) is test_something
    assert verifies("a83f", "beef")(test_something) is test_something
    assert verifies()(test_something) is test_something


def test_decorators_are_applied_bottom_up_like_any_other() -> None:
    order: list[str] = []

    def tracer(name: str) -> Callable[[F], F]:
        def apply(fn: F) -> F:
            order.append(name)
            return fn

        return apply

    @tracer("outer")
    @todo("x", id="a83f")
    @tracer("inner")
    def f() -> None:
        pass

    assert order == ["inner", "outer"]


def test_stacking_with_descriptors_preserves_behaviour() -> None:
    class Router:
        @todo("static")
        @staticmethod
        def s() -> str:
            return "s"

        @classmethod
        @todo("class")
        def c(cls) -> str:
            return cls.__name__

        @property
        @todo("prop", id="beef")
        def p(self) -> int:
            return 42

        @todo("method", test="tests/test_r.py::test_m")
        def m(self, value: int) -> int:
            return value * 2

    router = Router()
    assert Router.s() == "s"
    assert Router.c() == "Router"
    assert router.p == 42
    assert router.m(3) == 6
    assert isinstance(Router.__dict__["s"], staticmethod)
    assert isinstance(Router.__dict__["p"], property)


def test_wrapped_functions_keep_their_metadata() -> None:
    def logged(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    @todo("x")
    @logged
    def documented() -> None:
        """Docstring."""

    assert documented.__name__ == "documented"
    assert documented.__doc__ == "Docstring."
    assert documented.__wrapped__ is not None  # type: ignore[attr-defined]


def test_signature_is_the_frozen_api() -> None:
    params = inspect.signature(todo).parameters
    assert [(name, p.kind) for name, p in params.items()] == [
        ("title", inspect.Parameter.POSITIONAL_ONLY),
        ("id", inspect.Parameter.KEYWORD_ONLY),
        ("kind", inspect.Parameter.KEYWORD_ONLY),
        ("description", inspect.Parameter.KEYWORD_ONLY),
        ("test", inspect.Parameter.KEYWORD_ONLY),
        ("tests", inspect.Parameter.KEYWORD_ONLY),
    ]
    assert byteplan_runtime.__all__ == ["todo", "verifies"]


def test_title_is_positional_only() -> None:
    with pytest.raises(TypeError):
        todo(title="x")  # type: ignore[call-arg]


_AUDIT_SCRIPT = textwrap.dedent(
    """
    import __future__, json, os, sys, typing  # stdlib imports are not the package's I/O
    events = []
    phase = ["import"]
    package_dir = None

    def hook(event, args):
        if event in {"open", "socket.connect", "socket.bind", "subprocess.Popen", "os.system",
                     "os.exec", "os.posix_spawn", "os.spawn", "urllib.Request", "os.remove",
                     "os.rename", "os.mkdir", "shutil.rmtree", "os.chmod", "os.listdir"}:
            path = args[0] if args else None
            if phase[0] == "import" and (
                event == "os.listdir" or (isinstance(path, str) and "byteplan_runtime" in path)
            ):
                return  # the import system locating and loading the module's own .py / .pyc
            events.append([phase[0], event, repr(path)])

    sys.addaudithook(hook)
    import byteplan_runtime
    phase[0] = "call"
    f = lambda: None
    byteplan_runtime.todo("x", id="a83f", tests=("t.py::t",))(f)
    byteplan_runtime.verifies("a83f")(f)
    sys.stdout.write(json.dumps(events))
    """
)


def test_import_and_calls_perform_no_io() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _AUDIT_SCRIPT],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    assert json.loads(result.stdout) == []


def test_type_hints_resolve_on_every_supported_python() -> None:
    import typing

    assert set(typing.get_type_hints(todo)) == {"title", "id", "kind", "description", "test", "tests", "return"}
    assert set(typing.get_type_hints(verifies)) == {"ids", "return"}
