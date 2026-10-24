# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Internal common orchestration delegated by Project."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from byteplan.diagnostics import Code, Diagnostic, Severity
from byteplan.errors import (
    TaskNotFoundError,
)

if TYPE_CHECKING:
    from pathlib import Path


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


_NODE_ID_RE = re.compile(r"[^:\s][^:]*\.py(?:::[A-Za-z_][A-Za-z0-9_]*)+(?:\[[^\n]*\])?")


def _not_found(task_id: str) -> TaskNotFoundError:
    return TaskNotFoundError(f"no task with ID {task_id!r}")


def is_node_id(node: str) -> bool:
    """A pytest node ID: ``path/to/test_x.py::name[::name...][param]``."""
    return _NODE_ID_RE.fullmatch(node) is not None


def normalize_review(task_id: str, message: str) -> Diagnostic:
    return Diagnostic(Code.CONVERSION_NEEDS_REVIEW, Severity.INFO, f"task {task_id} {message}", task_id=task_id)


def _development_dependencies(pyproject: dict[str, Any]) -> list[Any]:
    """Requirement strings from optional dependencies, dependency groups and Hatch environments."""
    found: list[Any] = []
    for extra in pyproject.get("project", {}).get("optional-dependencies", {}).values():
        found += list(extra) if isinstance(extra, list) else []
    for group in pyproject.get("dependency-groups", {}).values():
        found += list(group) if isinstance(group, list) else []
    for env in pyproject.get("tool", {}).get("hatch", {}).get("envs", {}).values():
        if isinstance(env, dict):
            for key in ("dependencies", "extra-dependencies"):
                found += list(env.get(key, [])) if isinstance(env.get(key), list) else []
    return found


def _requirement_name(requirement: str) -> str:
    """The normalized project name of a PEP 508 requirement string."""
    match = re.match(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)", requirement)
    return re.sub(r"[-_.]+", "-", match.group(1)).lower() if match else ""
