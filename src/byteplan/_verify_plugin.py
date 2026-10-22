# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""pytest plugin used by ``byteplan verify``. It imports only pytest and the standard library.

``byteplan verify`` copies this file to a temporary directory as
``_byteplan_verify_plugin.py``, puts that directory first on ``PYTHONPATH`` and runs
``pytest -p _byteplan_verify_plugin <test files>``, so it loads in the project's own test
environment even when BytePlan is installed elsewhere.

* ``BYTEPLAN_VERIFY_NODES``: JSON list of requested node IDs. Collected items that don't
  match one are deselected. A request matches its own item, its parametrizations
  (``node[...]``) and, for a class or module, everything below it (``node::...``).
* ``BYTEPLAN_VERIFY_OUT``: a file that gets one JSON object per line, appended (and
  flushed) as results arrive, so a run killed on timeout still leaves what finished.

Records: ``{"matched": {request: [nodeid, ...]}}`` after collection,
``{"collect": nodeid, "failed": bool, "message": str}`` per collection report,
``{"node": nodeid, "when": ..., "outcome": ..., "xfail": bool, "duration": float,
"message": str}`` per test phase, and ``{"done": true}`` at the end of the session.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pytest

_MESSAGE_LIMIT = 1024


def _requested() -> list[str]:
    try:
        nodes = json.loads(os.environ.get("BYTEPLAN_VERIFY_NODES", "[]"))
    except ValueError:
        return []
    return [node for node in nodes if isinstance(node, str)]


def _emit(record: dict[str, Any]) -> None:
    path = os.environ.get("BYTEPLAN_VERIFY_OUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
        handle.flush()


def _message(report: Any) -> str:
    if not report.longrepr:
        return ""
    text = str(report.longrepr)
    return text if len(text) <= _MESSAGE_LIMIT else text[: _MESSAGE_LIMIT - 1] + "…"


def _matches(request: str, nodeid: str) -> bool:
    return nodeid == request or nodeid.startswith((request + "[", request + "::"))


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "byteplan(*ids): link this test to BytePlan task IDs")


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    requested = _requested()
    if not requested:
        return
    matched: dict[str, list[str]] = {request: [] for request in requested}
    kept: list[pytest.Item] = []
    deselected: list[pytest.Item] = []
    for item in items:
        hits = [request for request in requested if _matches(request, item.nodeid)]
        for request in hits:
            matched[request].append(item.nodeid)
        (kept if hits else deselected).append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = kept
    _emit({"matched": matched})


def pytest_collectreport(report: pytest.CollectReport) -> None:
    _emit({"collect": report.nodeid, "failed": report.failed, "message": _message(report) if report.failed else ""})


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    _emit(
        {
            "node": report.nodeid,
            "when": report.when,
            "outcome": report.outcome,
            "xfail": hasattr(report, "wasxfail"),
            "duration": report.duration,
            "message": _message(report) if report.failed else "",
        }
    )


def pytest_sessionfinish(session: pytest.Session) -> None:
    del session
    _emit({"done": True})
