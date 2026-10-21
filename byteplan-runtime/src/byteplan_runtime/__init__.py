# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Inert task markers for BytePlan.

``todo`` and ``verifies`` exist so that source code can declare BytePlan tasks
and acceptance-test links with ordinary decorator syntax. BytePlan reads them
statically (with ``ast``); it never imports your modules to find them.

At runtime both decorators are deliberately inert: they return the decorated
object itself, unchanged. They do not wrap, register, validate, log, read files,
or touch the network, so a malformed argument can never break an import in
production. Any checking happens in ``byteplan scan``/``byteplan check`` instead.

The public API is frozen: new keyword arguments may be added, but existing
parameters will not be removed or change meaning.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence, TypeVar

__version__ = "0.1.0"
__all__ = ["todo", "verifies"]

_T = TypeVar("_T")


def _identity(obj: _T) -> _T:
    return obj


def todo(
    title: str,
    /,
    *,
    # Optional[...] rather than "X | None": typing.get_type_hints() must work on 3.8/3.9.
    id: Optional[str] = None,  # noqa: A002, UP045 - "id" is the documented keyword
    kind: str = "TODO",
    description: str = "",
    test: Optional[str] = None,  # noqa: UP045
    tests: Sequence[str] = (),
) -> Callable[[_T], _T]:
    """Mark a function, method, or class as having an open BytePlan task.

    Args:
        title: One-line summary of the work.
        id: The task's four-hex-digit ID. Leave it out; ``byteplan scan``
            allocates one and writes it here.
        kind: ``"TODO"``, ``"FIXME"``, ``"HACK"`` or ``"XXX"``.
        description: Longer explanation.
        test: One pytest node ID that verifies the task.
        tests: Several pytest node IDs that verify the task.

    Returns:
        A decorator that returns its argument unchanged.

    Example::

        @todo(
            "Implement route poisoning",
            id="a83f",
            tests=("tests/test_routing.py::test_route_poisoning",),
        )
        def advertise_routes(self): ...
    """
    del title, id, kind, description, test, tests
    return _identity


def verifies(*ids: str) -> Callable[[_T], _T]:
    """Mark a test as acceptance evidence for one or more BytePlan task IDs.

    Returns:
        A decorator that returns its argument unchanged.

    Example::

        @verifies("a83f")
        def test_route_poisoning(): ...
    """
    del ids
    return _identity
