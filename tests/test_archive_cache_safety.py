# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""SQLite's implicit cache writes stay inside the selected archive authority."""

from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, Any

import pytest

from byteplan import archive
from byteplan._todo import verifies
from byteplan.api import Project
from byteplan.errors import ConfigError
from tests.test_archive import _close_and_commit

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import ProjectFactory, RunCli


def _ordinary_database(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE ordinary_notes (note TEXT)")
        connection.execute("INSERT INTO ordinary_notes VALUES (?)", ("private fixture sentinel",))


def _assert_ordinary_database(path: Path, original: bytes) -> None:
    assert path.read_bytes() == original
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [
            ("ordinary_notes",)
        ]
        assert connection.execute("SELECT note FROM ordinary_notes").fetchall() == [("private fixture sentinel",)]


def _snapshot(root: Path) -> dict[str, bytes | str | None]:
    result: dict[str, bytes | str | None] = {}
    for path in root.rglob("*"):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[name] = f"symlink:{path.readlink()}"
        else:
            result[name] = path.read_bytes() if path.is_file() else None
    return result


@verifies("cda4d1")
@pytest.mark.parametrize("alias", ["outside-symlink", "inside-symlink", "hardlink"])
def test_fresh_archived_lookup_rejects_cache_alias_before_mutating_foreign_database(
    repo: ProjectFactory, run_cli: RunCli, tmp_path: Path, alias: str
) -> None:
    task_id = _close_and_commit(repo, run_cli)
    project = Project.open(repo.root)
    task = project.get_task(task_id)
    assert project.archive(older_than=0).tasks == (task_id,)
    cache = repo.root / ".byteplan" / archive.STORE
    cache.unlink()
    ordinary = (repo.root if alias == "inside-symlink" else tmp_path) / "ordinary-fixture.sqlite"
    _ordinary_database(ordinary)
    original = ordinary.read_bytes()
    if alias == "hardlink":
        os.link(ordinary, cache)
    else:
        cache.symlink_to(ordinary)
    before = _snapshot(tmp_path)

    # Each public access starts with a fresh Project and must retain all metadata,
    # the selected alias, and the unrelated database's exact bytes/schema/sentinel.
    with pytest.raises(ConfigError, match=r"archive cache.*repair the cache"):
        Project.open(repo.root).get_task(task_id)
    with pytest.raises(ConfigError, match="archive cache"):
        Project.open(repo.root).reconcile_archive()
    with pytest.raises(ConfigError, match="archive cache"):
        Project.open(repo.root).readiness(task)
    with pytest.raises(ConfigError, match="archive cache"):
        Project.open(repo.root).restore_archived(task_id)
    result = run_cli("show", task_id, "--project", repo.root)
    assert result.code == 2
    assert "archive cache" in result.err
    assert _snapshot(tmp_path) == before
    _assert_ordinary_database(ordinary, original)


@verifies("cda4d1")
@pytest.mark.parametrize("inside", [True, False])
@pytest.mark.parametrize("fresh", [True, False])
def test_project_cache_parent_alias_keeps_actual_project_root_authority(
    project: ProjectFactory, tmp_path: Path, *, inside: bool, fresh: bool
) -> None:
    if fresh:
        project.write(
            "pyproject.toml", '[project]\nname="fixture"\nversion="0.1"\n[tool.byteplan]\nregistry="tasks.json"\n'
        )
    project.init()
    project.write(".byteplan/archive.json", archive.Index({"abcd": {"sha256": "a" * 64}}).dumps())
    state = project.root / ".byteplan"
    _ordinary_database(state / archive.STORE)
    facade = None if fresh else Project.open(project.root)
    target = (project.root if inside else tmp_path) / "private-saved-state"
    state.rename(target)
    state.symlink_to(target, target_is_directory=True)
    original = (target / archive.STORE).read_bytes()
    before = _snapshot(tmp_path)
    if facade is None:
        # The custom in-project registry avoids incidental config rejection of the
        # .byteplan alias; the Store must independently enforce the real root.
        facade = Project.open(project.root)
    with pytest.raises(ConfigError, match="archive cache"):
        facade.get_task("abcd")
    assert _snapshot(tmp_path) == before
    _assert_ordinary_database(target / archive.STORE, original)


@verifies("cda4d1")
@pytest.mark.parametrize("operation", ["get", "hashes", "put"])
@pytest.mark.parametrize("suffix", ["", "-journal", "-wal", "-shm"])
@pytest.mark.parametrize("alias", ["symlink", "hardlink"])
def test_every_store_entrypoint_validates_cache_and_sidecars_before_connect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, suffix: str, alias: str
) -> None:
    root = tmp_path / "project"
    state = root / ".byteplan"
    state.mkdir(parents=True)
    ordinary = tmp_path / "ordinary-fixture.sqlite"
    _ordinary_database(ordinary)
    original = ordinary.read_bytes()
    selected = state / f"{archive.STORE}{suffix}"
    if alias == "symlink":
        selected.symlink_to(ordinary)
    else:
        os.link(ordinary, selected)
    store = archive.Store(state, project_root=root)
    before = _snapshot(tmp_path)

    def forbidden_connect(*_args: Any, **_kwargs: Any) -> sqlite3.Connection:
        msg = "SQLite opened before validating all cache paths"
        raise AssertionError(msg)

    def access_store() -> None:
        if operation == "get":
            store.get("abcd")
        elif operation == "hashes":
            store.hashes()
        else:
            store.put([("abcd", {"task": {"id": "abcd"}, "evidence": None}, "stamp")])

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", forbidden_connect)
        with pytest.raises(ConfigError, match="archive cache"):
            access_store()
    assert _snapshot(tmp_path) == before
    _assert_ordinary_database(ordinary, original)


@verifies("cda4d1")
@pytest.mark.parametrize("suffix", ["", "-journal", "-wal", "-shm"])
def test_dangling_and_nonregular_sqlite_paths_fail_without_creating_cache(tmp_path: Path, suffix: str) -> None:
    state = tmp_path / "custom-state"
    state.mkdir()
    selected = state / f"{archive.STORE}{suffix}"
    selected.symlink_to(tmp_path / "not-created.sqlite")
    store = archive.Store(state)
    before = _snapshot(tmp_path)
    with pytest.raises(ConfigError, match="archive cache"):
        store.get("abcd")
    with pytest.raises(ConfigError, match="archive cache"):
        store.hashes()
    with pytest.raises(ConfigError, match="archive cache"):
        store.put([])
    assert _snapshot(tmp_path) == before
    selected.unlink()
    selected.mkdir()
    before = _snapshot(tmp_path)
    with pytest.raises(ConfigError, match="archive cache"):
        store.put([])
    assert _snapshot(tmp_path) == before


@verifies("cda4d1")
def test_explicit_project_root_rejects_an_external_state_directory_without_mkdir(tmp_path: Path) -> None:
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "uncreated-state"
    store = archive.Store(outside, project_root=root)
    before = _snapshot(tmp_path)
    with pytest.raises(ConfigError, match="archive cache"):
        store.put([])
    assert _snapshot(tmp_path) == before


@verifies("cda4d1")
@pytest.mark.parametrize("suffix", ["", "-journal", "-wal", "-shm"])
def test_archiving_rejects_aliases_without_changing_registry_index_or_foreign_database(
    repo: ProjectFactory, run_cli: RunCli, tmp_path: Path, suffix: str
) -> None:
    _close_and_commit(repo, run_cli)
    ordinary = tmp_path / "ordinary-fixture.sqlite"
    _ordinary_database(ordinary)
    selected = repo.root / ".byteplan" / f"{archive.STORE}{suffix}"
    selected.symlink_to(ordinary)
    original = ordinary.read_bytes()
    before = _snapshot(tmp_path)
    with pytest.raises(ConfigError, match="archive cache"):
        Project.open(repo.root).archive(older_than=0)
    assert _snapshot(tmp_path) == before
    _assert_ordinary_database(ordinary, original)


@verifies("cda4d1")
@pytest.mark.parametrize("bound", [True, False])
def test_legitimate_custom_store_creation_and_versioned_roundtrip(tmp_path: Path, *, bound: bool) -> None:
    state = tmp_path / "nested" / "custom-state"
    store = archive.Store(state, project_root=tmp_path) if bound else archive.Store(state)
    assert store.get("abcd") is None
    assert store.hashes() == set()
    assert not state.exists()
    first: dict[str, Any] = {
        "task": {"id": "abcd", "title": "first"},
        "evidence": {"run": "proof"},
        "run": {"head": "saved"},
    }
    second: dict[str, Any] = {"task": {"id": "abcd", "title": "second"}, "evidence": None}
    store.put([("abcd", first, "first"), ("abcd", second, "second")])
    assert store.get("abcd", archive.record_hash(first["task"])) == first
    assert store.get("abcd") == second
    assert store.hashes() == {("abcd", archive.record_hash(payload["task"])) for payload in (first, second)}
    store.put([("abcd", {"task": first["task"], "evidence": None}, "third")])
    assert store.get("abcd", archive.record_hash(first["task"])) == first


@verifies("cda4d1")
def test_legitimate_wal_cache_sidecars_remain_supported(tmp_path: Path) -> None:
    store = archive.Store(tmp_path / "custom-state")
    first = {"task": {"id": "abcd", "title": "first"}, "evidence": None}
    store.put([("abcd", first, "first")])
    with closing(sqlite3.connect(store.path)) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        connection.execute("SELECT * FROM tasks").fetchall()
        second = {"task": {"id": "abcd", "title": "second"}, "evidence": None}
        store.put([("abcd", second, "second")])
        assert store.path.with_name(f"{archive.STORE}-wal").is_file()
        assert store.path.with_name(f"{archive.STORE}-shm").is_file()
        assert store.get("abcd") == second
