# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""The committed archive index has a strict version and lossless metadata contract."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from byteplan import archive
from byteplan._todo import verifies
from byteplan.api import Project
from byteplan.errors import ConfigError
from byteplan.gitio import archive_driver_main
from tests.gitutil import git

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import ProjectFactory, RunCli


def _index(tasks: dict[str, dict[str, Any]] | None = None, **extra: Any) -> str:
    return json.dumps({**extra, "schema_version": 1, "tasks": tasks or {}})


@verifies("765f23")
@pytest.mark.parametrize("version", [2, 999, True, None, "1", 1.0])
def test_archive_index_rejects_unsupported_schema_versions(version: object) -> None:
    with pytest.raises(ValueError, match=r"unsupported archive index schema_version.*upgrade BytePlan"):
        archive.Index.loads(json.dumps({"schema_version": version, "tasks": {}}))


@verifies("765f23")
@pytest.mark.parametrize(
    "data",
    [
        [],
        None,
        1,
        {"schema_version": 1},
        {"schema_version": 1, "tasks": []},
        {"schema_version": 1, "tasks": {"NOT-AN-ID": {"sha256": "a" * 64}}},
        {"schema_version": 1, "tasks": {"abcd": []}},
        {"schema_version": 1, "tasks": {"abcd": {}}},
        {"schema_version": 1, "tasks": {"abcd": {"sha256": "bad"}}},
        {"schema_version": 1, "tasks": {"abcd": {"sha256": "a" * 64, "title": []}}},
        {"schema_version": 1, "tasks": {"abcd": {"sha256": "a" * 64, "status": "open"}}},
        {"schema_version": 1, "tasks": {"abcd": {"sha256": "a" * 64, "closed_at": False}}},
    ],
)
def test_archive_index_rejects_invalid_containers_and_records(data: object) -> None:
    with pytest.raises((ValueError, TypeError), match="archive index"):
        archive.Index.loads(json.dumps(data))


@verifies("765f23")
def test_archive_index_retains_legacy_minimal_records_and_opaque_fields() -> None:
    data: dict[str, dict[str, Any]] = {
        "abcd": {"sha256": "a" * 64},
        "abcdef": {"sha256": "b" * 64, "vendor": [True, 1]},
    }
    text = _index(data, vendor={"mapping": {"remote": "123"}}, evidence_policy="retained")
    parsed = archive.Index.loads(text)
    assert json.loads(parsed.dumps()) == json.loads(text)
    assert archive.Index.loads(parsed.dumps()).dumps() == parsed.dumps()


@verifies("765f23")
@pytest.mark.parametrize("field", ["schema_version", "tasks"])
def test_archive_index_duplicate_keys_fail_explicitly(field: str) -> None:
    text = '{"schema_version":1,"tasks":{},"' + field + '":' + ("1" if field == "schema_version" else "{}") + "}"
    with pytest.raises(ValueError, match="duplicate JSON key"):
        archive.Index.loads(text)


@verifies("765f23")
@pytest.mark.parametrize("operation", ["check", "archive", "archive-preview", "restore", "list", "import"])
@pytest.mark.parametrize("invalid", ["future", "shape", "empty", "whitespace", "duplicate", "malformed", "encoding"])
def test_archive_operations_reject_invalid_indexes_without_writes(
    project: ProjectFactory, run_cli: RunCli, operation: str, invalid: str
) -> None:
    project.init()
    texts: dict[str, str | bytes] = {
        "future": json.dumps({"schema_version": 99, "tasks": {}, "future": {"keep": True}}),
        "shape": json.dumps({"schema_version": 1, "tasks": {"abcd": None}}),
        "empty": "",
        "whitespace": " \n\t",
        "duplicate": '{"schema_version":1,"tasks":{},"tasks":{}}',
        "malformed": "{bad",
        "encoding": b"\xff",
    }
    project.write(".byteplan/archive.json", texts[invalid])
    before = project.snapshot()
    commands = {
        "check": ("check",),
        "archive": ("archive", "--older-than", "0"),
        "archive-preview": ("archive", "--older-than", "0", "--dry-run"),
        "restore": ("archive", "--restore", "abcd"),
        "list": ("list", "--archived"),
        "import": ("repair", "--import", "abcd"),
    }
    result = run_cli(*commands[operation], "--project", project.root)
    assert result.code == 2
    assert "archive.json" in result.err
    assert "restore" in result.err
    assert project.snapshot() == before
    with pytest.raises(ConfigError):
        Project.open(project.root).archive_index()


@verifies("765f23")
@pytest.mark.parametrize("rev", [None, "HEAD"])
@pytest.mark.parametrize("text", ["", " \n\t", '{"schema_version":99,"tasks":{}}'])
def test_snapshot_index_validation_uses_authoritative_bytes(
    repo: ProjectFactory, run_cli: RunCli, rev: str | None, text: str
) -> None:
    repo.write(".byteplan/archive.json", text)
    git(repo.root, "add", ".byteplan/archive.json")
    git(repo.root, "commit", "-qm", "unsupported committed archive index")
    # A valid working-tree replacement must not mask the invalid staged/committed blob.
    repo.write(".byteplan/archive.json", _index())
    before = repo.snapshot()
    project = Project.open_snapshot(repo.root, rev)
    try:
        with pytest.raises(ConfigError, match=r"archive.json.*restore"):
            project.archive_index()
    finally:
        project.close()
    selection = ("--staged",) if rev is None else ("--commit", rev)
    result = run_cli("check", *selection, "--project", repo.root)
    assert result.code == 2
    assert "archive.json" in result.err
    assert repo.snapshot() == before


@verifies("765f23")
def test_unreadable_index_fails_closed_before_import_or_noop_archive(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    project.init()
    path = project.write(".byteplan/archive.json", _index())
    project.write("src/imported.py", "# TODO[abc123]: source task\n")
    before = project.snapshot()
    read_bytes = type(path).read_bytes

    def unreadable(self: Path) -> bytes:
        if self == path:
            msg = "archive index access denied"
            raise PermissionError(msg)
        return read_bytes(self)

    facade = Project.open(project.root)
    with monkeypatch.context() as patch:
        patch.setattr(type(path), "read_bytes", unreadable)
        with pytest.raises(ConfigError, match="archive index access denied"):
            facade.archive_index()
        with pytest.raises(ConfigError, match="archive index access denied"):
            facade.import_task("abc123")
        for dry_run in (True, False):
            with pytest.raises(ConfigError, match="archive index access denied"):
                facade.archive(dry_run=dry_run, older_than=0)
    assert project.snapshot() == before


@verifies("765f23")
def test_archive_merge_preserves_root_and_entry_extensions() -> None:
    original = {"abcd": {"sha256": "a" * 64, "vendor": {"old": True}, "archived_at": "original"}}
    ours = {"abcd": {**original["abcd"], "vendor": {"old": True, "ours": [1]}}}
    theirs = {"abcd": {**original["abcd"], "vendor": {"old": True, "theirs": [2]}, "archived_at": "later"}}
    merged, conflicts = archive.merge(
        _index(original, vendor={"base": 0}),
        _index(ours, vendor={"base": 0, "ours": 1}),
        _index(theirs, vendor={"base": 0, "theirs": 2}),
    )
    assert not conflicts
    assert merged is not None
    result = json.loads(merged)
    assert result["vendor"] == {"base": 0, "ours": 1, "theirs": 2}
    assert result["tasks"]["abcd"]["vendor"] == {"old": True, "ours": [1], "theirs": [2]}
    assert result["tasks"]["abcd"]["archived_at"] == "original"


@verifies("765f23")
@pytest.mark.parametrize("where", ["root", "entry", "deletion", "different_record"])
def test_archive_merge_never_silently_selects_competing_extensions(where: str) -> None:
    old = {"abcd": {"sha256": "a" * 64, "vendor": {"value": 0}}}
    ours = {"abcd": {"sha256": "a" * 64, "vendor": {"value": True}}}
    theirs = {"abcd": {"sha256": "a" * 64, "vendor": {"value": 1}}}
    base_extra, ours_extra, theirs_extra = {}, {}, {}
    if where == "root":
        ours, theirs = old, old
        base_extra, ours_extra, theirs_extra = {"opaque": 0}, {"opaque": True}, {"opaque": 1}
    elif where == "deletion":
        theirs = {}
    elif where == "different_record":
        theirs["abcd"]["sha256"] = "b" * 64
    merged, conflicts = archive.merge(
        _index(old, **base_extra), _index(ours, **ours_extra), _index(theirs, **theirs_extra)
    )
    assert merged is None
    assert conflicts


@verifies("765f23")
@pytest.mark.parametrize("bad", ["future", "malformed", "duplicate", "record"])
def test_archive_merge_driver_preserves_invalid_inputs(tmp_path: Path, bad: str) -> None:
    base, ours, theirs = (tmp_path / name for name in ("base", "ours", "theirs"))
    base.write_text(_index())
    ours.write_text(_index({"abcd": {"sha256": "a" * 64}}))
    invalid = {
        "future": '{"schema_version":99,"tasks":{},"opaque":true}',
        "malformed": "{bad",
        "duplicate": '{"schema_version":1,"tasks":{},"tasks":{}}',
        "record": '{"schema_version":1,"tasks":{"abcd":null}}',
    }
    theirs.write_text(invalid[bad])
    before = [path.read_bytes() for path in (base, ours, theirs)]
    assert archive_driver_main(str(base), str(ours), str(theirs), None) == 1
    assert [path.read_bytes() for path in (base, ours, theirs)] == before


@verifies("765f23")
@pytest.mark.parametrize("where", ["root", "entry"])
def test_archive_driver_leaves_competing_opaque_values_for_manual_resolution(tmp_path: Path, where: str) -> None:
    paths = [tmp_path / name for name in ("base", "ours", "theirs")]
    for path, value in zip(paths, [0, True, 1], strict=True):
        tasks: dict[str, dict[str, Any]] = {"abcd": {"sha256": "a" * 64}}
        extra: dict[str, Any] = {}
        if where == "root":
            extra["vendor"] = value
        else:
            tasks["abcd"]["vendor"] = value
        path.write_text(_index(tasks, **extra))
    originals = [path.read_bytes() for path in paths]
    base, ours, theirs = paths
    assert archive_driver_main(str(base), str(ours), str(theirs), None) == 1
    assert paths[0].read_bytes() == originals[0]
    assert paths[2].read_bytes() == originals[2]
    conflict = paths[1].read_text()
    assert "<<<<<<< ours" in conflict
    assert "=======\n" in conflict
    assert ">>>>>>> theirs" in conflict
    assert '"vendor": true' in conflict
    assert '"vendor": 1' in conflict
