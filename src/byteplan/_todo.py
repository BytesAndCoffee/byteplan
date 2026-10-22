"""BytePlan task markers, inert at runtime (written by `byteplan init --runtime-shim`).

BytePlan reads @todo/@verifies statically; at runtime they return the object unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_T = TypeVar("_T")


def _identity(obj: _T) -> _T:
    return obj


def todo(
    title: str,
    /,
    *,
    id: str | None = None,  # noqa: A002 - BytePlan's documented keyword
    kind: str = "TODO",
    description: str = "",
    test: str | None = None,
    tests: Sequence[str] = (),
) -> Callable[[_T], _T]:
    del title, id, kind, description, test, tests
    return _identity


def verifies(*ids: str) -> Callable[[_T], _T]:
    del ids
    return _identity
