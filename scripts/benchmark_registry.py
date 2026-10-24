# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Measure registry operations against deterministic synthetic records; never writes a registry."""

from __future__ import annotations

import argparse
import copy
import json
import platform
import statistics
import sys
import time
import tracemalloc
from pathlib import Path
from typing import TYPE_CHECKING, Any

from byteplan import registry
from byteplan.merge import merge_registries
from byteplan.models import HistoryEvent, SourceRef, Status, Task

if TYPE_CHECKING:
    from collections.abc import Callable

MINIMUM_TASKS = 2
MAXIMUM_TASKS = 0xFFFFFF


def synthetic(size: int) -> registry.Registry:
    """Six-digit fixture IDs model the stored format, not allocation performance."""
    result = registry.Registry()
    for index in range(size):
        identity = f"{index:06x}"
        path = f"src/package_{index // 100}/module_{index % 100}.py"
        result.reserved_ids.add(identity)
        result.tasks[identity] = Task(
            id=identity,
            kind="TODO",
            title=f"Implement requirement {index}",
            description="A representative task with source, labels, test links and five lifecycle events.",
            source=SourceRef(path, 10, "process"),
            labels=["release:1.0", "component:example"],
            notes="Authored notes remain authoritative across discovery and merges.",
            tests_managed=[f"tests/test_module_{index}.py::test_requirement"],
            first_seen="2026-10-21T00:00:00Z",
            last_seen="2026-10-21T00:00:04Z",
            history=[
                HistoryEvent("created", "2026-10-21T00:00:00Z", new={"path": path, "line": 10}),
                *[
                    HistoryEvent("edited", f"2026-10-21T00:00:0{event}Z", old={"notes": "old"}, new={"notes": "new"})
                    for event in range(1, 5)
                ],
            ],
        )
    return result


def median_ms(call: Callable[[], object], repeats: int) -> float:
    timings = []
    for _ in range(repeats):
        start = time.perf_counter()
        call()
        timings.append((time.perf_counter() - start) * 1000)
    return round(statistics.median(timings), 3)


def distribution(record: registry.Registry, serialized: str) -> dict[str, Any]:
    without_history = copy.deepcopy(record)
    for task in without_history.tasks.values():
        task.history.clear()
    no_history_bytes = len(registry.dumps(without_history).encode())
    byte_count = len(serialized.encode())
    return {
        "tasks": len(record.tasks),
        "reserved_ids": len(record.reserved_ids),
        "history_events": sum(len(task.history) for task in record.tasks.values()),
        "bytes": byte_count,
        "bytes_without_history": no_history_bytes,
        "history_bytes": byte_count - no_history_bytes,
        "history_fraction": round((byte_count - no_history_bytes) / byte_count, 4),
    }


def measure(size: int, repeats: int) -> dict[str, Any]:
    record = synthetic(size)
    serialized = registry.dumps(record)
    reversed_record = registry.Registry(
        reserved_ids=set(record.reserved_ids), tasks=dict(reversed(list(record.tasks.items())))
    )
    if registry.dumps(registry.loads(serialized)) != serialized or registry.dumps(reversed_record) != serialized:
        msg = "registry serialization is not deterministic"
        raise RuntimeError(msg)
    base = registry.to_dict(record)
    ours, theirs = copy.deepcopy(base), copy.deepcopy(base)
    identities = sorted(record.tasks)
    ours["tasks"][identities[0]]["priority"] = "high"
    theirs["tasks"][identities[-1]]["assignee"] = "reviewer"

    def merged() -> object:
        outcome = merge_registries(base, ours, theirs)
        if outcome.data is None or outcome.conflicts:
            msg = f"independent edits did not merge: {outcome.conflicts}"
            raise RuntimeError(msg)
        if (
            outcome.data["tasks"][identities[0]]["priority"] != "high"
            or outcome.data["tasks"][identities[-1]]["assignee"] != "reviewer"
        ):
            msg = "the merge discarded an independent task edit"
            raise RuntimeError(msg)
        return outcome

    result = distribution(record, serialized)
    result["median_ms"] = {
        "parse_validate": median_ms(lambda: registry.loads(serialized), repeats),
        "serialize": median_ms(lambda: registry.dumps(record), repeats),
        "exact_lookup": median_ms(lambda: record.get(identities[-1]), repeats),
        "filter_sort": median_ms(
            lambda: [task for _, task in sorted(record.tasks.items()) if task.status is Status.OPEN], repeats
        ),
        "merge": median_ms(merged, repeats),
    }
    tracemalloc.start()
    parsed = registry.loads(serialized)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    if len(parsed.tasks) != size:
        msg = "the parser discarded synthetic tasks"
        raise RuntimeError(msg)
    result["parse_peak_mib"] = round(peak / (1024 * 1024), 3)
    result["deterministic_roundtrip_and_order"] = True
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[1000, 10000])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--registry", type=Path)
    args = parser.parse_args(argv)
    if args.repeats < 1 or any(size < MINIMUM_TASKS or size > MAXIMUM_TASKS for size in args.sizes):
        parser.error("repeats must be positive and sizes must be between 2 and 16777215")
    results: dict[str, Any] = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "repeats": args.repeats,
        "synthetic": [measure(size, args.repeats) for size in args.sizes],
    }
    if args.registry is not None:
        text = args.registry.read_text(encoding="utf-8")
        results["repository"] = distribution(registry.loads(text), text)
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
