# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Internal verify orchestration delegated by Project."""

from __future__ import annotations

import dataclasses
import platform
import sys
from typing import TYPE_CHECKING

from byteplan import scaffold, verification
from byteplan.errors import (
    ConfigError,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from byteplan.models import Task

from byteplan._api_types import TaskVerification, VerifyReport
from byteplan.operations.common import _read_bytes

if TYPE_CHECKING:
    from byteplan.api import Project


def runner(self: Project) -> list[str]:
    return list(self.config.tests.runner) or [sys.executable, "-m", "pytest"]


def evidence(self: Project) -> verification.Evidence:
    if self.snapshot is None:
        return verification.Evidence.load(self.root)
    data = self.snapshot.read(verification.STORE)
    return verification.Evidence() if data is None else verification.Evidence.loads(data)


def readiness(self: Project, task: Task, evidence: verification.Evidence | None = None) -> verification.Readiness:
    """Derived, never stored: ``unverified``, ``failing``, ``needs_review`` or ``ready_for_review``."""
    if evidence is None:
        evidence = self._evidence()
        if task.id not in evidence.tasks and task.id in self.archive_index().tasks:
            if self.snapshot is not None:
                msg = (
                    "archived verification requires the working-tree project; snapshots do not consult its local cache"
                )
                raise ConfigError(msg)
            evidence = self._archived_evidence(task.id)
    head: tuple[str | None, bool] = (None, False)
    if self.config.tests.stale_on == "head":
        if self.snapshot is None:
            head = verification.git_state(self.root)
        else:
            head = (self.snapshot.commit, False) if self.snapshot.kind == "commit" else (None, True)
    state = verification.readiness(
        task,
        evidence,
        self.root,
        stale_on=self.config.tests.stale_on,
        head=head,
        placeholders=self._placeholders(task.linked_tests()),
        read=None if self.snapshot is None else self.snapshot.read,
    )
    if (
        self.snapshot is not None
        and self.snapshot.kind == "index"
        and self.config.tests.stale_on == "head"
        and state.state == "needs_review"
    ):
        state = dataclasses.replace(
            state, reasons=(*state.reasons, "HEAD freshness is uncertain for an index snapshot")
        )
    return state


def placeholders(self: Project, nodes: Iterable[str]) -> frozenset[str]:
    """Which of these node IDs are still scaffold placeholders (read statically from the
    working tree, or from the snapshot)."""
    found: set[str] = set()
    for path in sorted({node.split("::", 1)[0] for node in nodes}):
        data = self.snapshot.read(path) if self.snapshot is not None else _read_bytes(self.root / path)
        if data is not None:
            found |= scaffold.placeholder_nodes(path, data.decode("utf-8", "replace"))
    return frozenset(found)


def verify(self: Project, task_ids: Sequence[str] | None = None) -> VerifyReport:
    """Run the linked tests of ``task_ids`` (default: every open task with links) and record
    the evidence in ``.byteplan/verification.json``. Never changes a task's status."""
    self._require_working_tree()
    registry = self.load_registry()
    if task_ids:
        tasks = list({task.id: task for task in (self.get_task(task_id) for task_id in task_ids)}.values())
    else:
        tasks = [t for _, t in sorted(registry.tasks.items()) if not t.status.is_closed and t.linked_tests()]
    tasks = [t for t in tasks if t.linked_tests()]
    argv = (*self.runner(), "-p", verification.PLUGIN_MODULE)
    if not tasks:
        return VerifyReport((), argv, 0)
    fingerprints = {t.id: verification.fingerprint(self.root, verification.task_files(t)) for t in tasks}
    head, dirty = verification.git_state(self.root)
    nodes = list(dict.fromkeys(node for t in tasks for node in t.linked_tests()))
    started = self.clock()
    run = verification.run_tests(self.root, nodes, self.runner(), self.config.tests.timeout)

    with self._writing():  # brief: the tests ran without holding the project lock
        evidence = verification.Evidence.load(self.root)
        run_id = evidence.add_run(
            {
                "argv": list(argv),
                "python": platform.python_version(),
                "at": started,
                "head": head,
                "dirty": dirty,
                "timed_out": run.timed_out,
            }
        )
        for task in tasks:
            previous = evidence.tasks.get(task.id, {})
            prior_tests = previous.get("tests", {})
            evidence.tasks[task.id] = {
                **previous,
                "fingerprint": fingerprints[task.id],
                "run": run_id,
                "tests": {
                    node: {
                        **{
                            key: value
                            for key, value in prior_tests.get(node, {}).items()
                            if key not in {"outcome", "duration_ms", "message"}
                        },
                        **run.results[node].to_dict(),
                    }
                    for node in task.linked_tests()
                },
            }
        evidence.save(self.root)
    verified = tuple(
        TaskVerification(
            task, self.readiness(task, evidence), {node: run.results[node] for node in task.linked_tests()}
        )
        for task in tasks
    )
    return VerifyReport(verified, argv, run.returncode, run.timed_out, run.output)


def ready(self: Project) -> list[tuple[Task, verification.Readiness]]:
    """Open tasks whose evidence makes them ready for a human to review and resolve."""
    evidence = self._evidence()
    found = []
    for _, task in sorted(self.load_registry().tasks.items()):
        if task.status.is_closed:
            continue
        state = self.readiness(task, evidence)
        if state.state == "ready_for_review":
            found.append((task, state))
    return found
