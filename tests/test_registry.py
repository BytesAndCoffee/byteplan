# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from byteplan.errors import RegistryError
from byteplan.models import HistoryEvent, Presence, SourceRef, Status, Task
from byteplan.registry import Registry, dumps, load_registry, loads

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import ProjectFactory, RunCli


def sample() -> Registry:
    task = Task(
        id="7fa2",
        kind="TODO",
        title="Implement route poisoning",
        description="Support split horizon.",
        status=Status.IN_PROGRESS,
        priority="high",
        assignee="sam",
        labels=["routing"],
        notes="see RFC 2453 §3.4.3 — ✓",
        presence=Presence.PRESENT,
        source=SourceRef("src/rip.py", 84, "Router.send_route_update"),
        first_seen="2026-10-21T00:00:00Z",
        last_seen="2026-10-21T00:00:00Z",
        history=[HistoryEvent("created", "2026-10-21T00:00:00Z")],
    )
    return Registry(reserved_ids={"7fa2", "0001"}, tasks={"7fa2": task})


def task_json(**overrides: Any) -> str:
    task: dict[str, Any] = {"id": "7fa2", "kind": "TODO", "title": "t"}
    task.update(overrides)
    return json.dumps({"schema_version": 1, "reserved_ids": ["7fa2"], "tasks": {"7fa2": task}})


def test_round_trip_is_byte_stable() -> None:
    text = dumps(sample())
    assert dumps(loads(text)) == text
    assert loads(text).tasks["7fa2"] == sample().tasks["7fa2"]


def test_serialization_format() -> None:
    text = dumps(sample())
    assert text.endswith("}\n")
    assert '\n  "reserved_ids": [\n    "0001",\n    "7fa2"\n  ]' in text
    assert "✓" in text  # UTF-8, not \u escapes
    assert "\r" not in text


def test_unknown_task_fields_are_preserved() -> None:
    registry = loads(task_json(custom_field={"from": "newer tool"}))
    assert json.loads(dumps(registry))["tasks"]["7fa2"]["custom_field"] == {"from": "newer tool"}


def test_minimal_task_gets_defaults() -> None:
    task = loads(task_json()).tasks["7fa2"]
    assert (task.status, task.presence, task.priority, task.labels) == (Status.OPEN, Presence.UNKNOWN, "normal", [])


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{not json", "not valid JSON"),
        ("[]", "top level must be an object"),
        ('{"tasks": {}}', "schema_version"),
        ('{"schema_version": 99}', "newer than this byteplan supports"),
        ('{"schema_version": 0}', "unsupported schema_version"),
        ('{"schema_version": 1, "reserved_ids": ["XYZ1"]}', "reserved_ids"),
        ('{"schema_version": 1, "tasks": []}', "tasks must be an object"),
        (task_json(status="done"), "status 'done' is not one of"),
        (task_json(presence="gone"), "presence"),
        (task_json(id="0000"), "does not match its key"),
        (task_json(labels="x"), "labels"),
        (task_json(title=None), "title must be a string"),
        (task_json(source={"path": "a.py"}), "source must be an object"),
        (task_json(history=[{"event": "created"}]), "history entries"),
        (
            json.dumps(
                {
                    "schema_version": 1,
                    "reserved_ids": [],
                    "tasks": {"7fa2": {"id": "7fa2", "kind": "TODO", "title": "t"}},
                }
            ),
            "not in reserved_ids",
        ),
        (json.dumps({"schema_version": 1, "reserved_ids": [], "tasks": {"bad": {}}}), "lowercase hexadecimal ID"),
    ],
)
def test_invalid_registry(text: str, message: str) -> None:
    with pytest.raises(RegistryError, match=message):
        loads(text)


def test_missing_registry_suggests_init(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="byteplan init"):
        load_registry(tmp_path / "tasks.json")


def test_unknown_top_level_keys_are_preserved() -> None:
    """Phase 4d: a newer BytePlan's top-level data (e.g. release records) survives a save."""
    text = task_json()
    data = json.loads(text)
    data["releases"] = [{"version": "1.0", "stripped": ["7fa2"]}]
    data["x-tool"] = {"nested": True}
    registry = loads(json.dumps(data))
    saved = json.loads(dumps(registry))
    assert saved["releases"] == [{"version": "1.0", "stripped": ["7fa2"]}]
    assert saved["x-tool"] == {"nested": True}
    assert dumps(loads(dumps(registry))) == dumps(registry)  # still byte-stable


def test_unknown_top_level_keys_survive_a_writing_scan(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    path = project.root / ".byteplan/tasks.json"
    data = json.loads(path.read_text())
    data["release"] = {"version": "0.9", "at": "2026-10-22T00:00:00Z"}
    path.write_text(json.dumps(data))
    project.write("src/a.py", "# TODO: x\n")
    assert run_cli("scan", "--project", project.root).code == 0
    saved = json.loads(path.read_text())
    assert saved["release"] == {"version": "0.9", "at": "2026-10-22T00:00:00Z"}
    assert len(saved["tasks"]) == 1
