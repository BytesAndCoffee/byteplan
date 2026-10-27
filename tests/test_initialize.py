# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Initialization validates its complete write set before changing project files."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from byteplan._todo import verifies
from byteplan.api import RUNTIME_SHIM, Project, init_project
from byteplan.errors import ConfigError

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import ProjectFactory


def _symlink(path: Path, target: Path, *, directory: bool = False) -> None:
    try:
        path.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks unavailable: {exc}")


def _snapshot(root: Path) -> dict[str, tuple[str, bytes | str]]:
    """Include directory creation and link identity, as well as all local/outside bytes."""
    result: dict[str, tuple[str, bytes | str]] = {}
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            result[rel] = ("symlink", os.readlink(path))
        elif path.is_dir():
            result[rel] = ("directory", "")
        else:
            result[rel] = ("file", path.read_bytes())
    return result


def _custom_registry(project: ProjectFactory, registry: str = "tasks.json") -> None:
    path = project.root / "pyproject.toml"
    path.write_bytes(path.read_bytes() + f'\n[tool.byteplan]\nregistry = "{registry}"\n'.encode())


@verifies("12ce1c")
@pytest.mark.parametrize("destination", ["outside", "inside", "vcs"])
@pytest.mark.parametrize("existing_ignore", [False, True])
@pytest.mark.parametrize("runtime_shim", [None, "src/pkg/shim.py"])
def test_init_rejects_state_directory_alias_before_any_side_effect(
    project: ProjectFactory, tmp_path: Path, destination: str, runtime_shim: str | None, *, existing_ignore: bool
) -> None:
    _custom_registry(project)
    target = tmp_path / "private" if destination == "outside" else project.root / destination
    if destination == "vcs":
        target = project.root / ".git"
    target.mkdir()
    (target / "private.txt").write_bytes(b"private bytes\x00\xff")
    if existing_ignore:
        (target / ".gitignore").write_bytes(b"existing ignore\r\n")
    _symlink(project.root / ".byteplan", target, directory=True)
    before = _snapshot(tmp_path)

    with pytest.raises(ConfigError):
        init_project(project.root, runtime_shim=runtime_shim)

    assert _snapshot(tmp_path) == before


@verifies("12ce1c")
@pytest.mark.parametrize("outside", [False, True])
@pytest.mark.parametrize("existing_target", [False, True])
def test_init_rejects_ignore_file_alias_before_any_side_effect(
    project: ProjectFactory, tmp_path: Path, *, outside: bool, existing_target: bool
) -> None:
    _custom_registry(project)
    target = (tmp_path if outside else project.root) / "private-ignore"
    if existing_target:
        target.write_bytes(b"private ignore\r\n")
    state = project.root / ".byteplan"
    state.mkdir()
    _symlink(state / ".gitignore", target)
    before = _snapshot(tmp_path)

    with pytest.raises(ConfigError):
        init_project(project.root, runtime_shim="src/pkg/shim.py")

    assert _snapshot(tmp_path) == before


@verifies("12ce1c")
@pytest.mark.parametrize("destination", ["outside", "inside", "vcs"])
def test_init_rejects_pyproject_alias_before_any_side_effect(
    project: ProjectFactory, tmp_path: Path, destination: str
) -> None:
    path = project.root / "pyproject.toml"
    target = tmp_path / "private.toml" if destination == "outside" else project.root / destination / "private.toml"
    if destination == "vcs":
        target = project.root / ".git" / "private.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    path.rename(target)
    _symlink(path, target)
    before = _snapshot(tmp_path)

    with pytest.raises(ConfigError):
        init_project(project.root, runtime_shim="src/pkg/shim.py")

    assert _snapshot(tmp_path) == before


@verifies("12ce1c")
@pytest.mark.parametrize("metadata", [".git", ".hg", ".svn", ".byteplan/txn"])
@pytest.mark.parametrize("alias", [False, True])
def test_init_rejects_registry_in_vcs_or_transaction_metadata(
    project: ProjectFactory, tmp_path: Path, metadata: str, *, alias: bool
) -> None:
    target = project.root / metadata
    target.mkdir(parents=True)
    (target / "private.txt").write_bytes(b"retained metadata\x00")
    registry = f"{metadata}/tasks.json"
    if alias:
        _symlink(project.root / "metadata", target, directory=True)
        registry = "metadata/tasks.json"
    _custom_registry(project, registry)
    before = _snapshot(tmp_path)

    with pytest.raises(ConfigError):
        init_project(project.root, runtime_shim="src/pkg/shim.py")

    assert _snapshot(tmp_path) == before


@verifies("12ce1c")
@pytest.mark.parametrize("target_kind", ["registry", "shim"])
@pytest.mark.parametrize("existing_target", [False, True])
def test_init_rejects_existing_target_symlink_even_inside_project(
    project: ProjectFactory, tmp_path: Path, target_kind: str, *, existing_target: bool
) -> None:
    target = project.root / ("real.json" if target_kind == "registry" else "real.py")
    if existing_target:
        data = (
            b'{"schema_version":2,"reserved_ids":[],"tasks":{}}\n'
            if target_kind == "registry"
            else RUNTIME_SHIM.encode()
        )
        target.write_bytes(data)
    link = project.root / ("tasks.json" if target_kind == "registry" else "shim.py")
    _symlink(link, target)
    if target_kind == "registry":
        _custom_registry(project)
    before = _snapshot(tmp_path)

    with pytest.raises(ConfigError):
        init_project(project.root, runtime_shim="shim.py")

    assert _snapshot(tmp_path) == before


@verifies("12ce1c")
@pytest.mark.parametrize("target_kind", ["registry", "shim"])
def test_init_rejects_non_directory_parent_before_other_writes(
    project: ProjectFactory, tmp_path: Path, target_kind: str
) -> None:
    (project.root / "parent").write_bytes(b"not a directory")
    if target_kind == "registry":
        _custom_registry(project, "parent/tasks.json")
    before = _snapshot(tmp_path)

    with pytest.raises(ConfigError):
        init_project(project.root, runtime_shim="parent/shim.py" if target_kind == "shim" else "src/shim.py")

    assert _snapshot(tmp_path) == before


@verifies("12ce1c")
@pytest.mark.parametrize("registry", ["shim.py/tasks.json", "tasks.json"])
def test_init_rejects_overlapping_file_and_directory_targets(
    project: ProjectFactory, tmp_path: Path, registry: str
) -> None:
    _custom_registry(project, registry)
    before = _snapshot(tmp_path)

    with pytest.raises(ConfigError):
        init_project(project.root, runtime_shim="shim.py" if registry.startswith("shim") else "tasks.json/shim.py")

    assert _snapshot(tmp_path) == before


@verifies("12ce1c")
def test_init_keeps_confined_ordinary_parent_aliases_and_custom_registry(
    project: ProjectFactory, tmp_path: Path
) -> None:
    (project.root / "pkg").mkdir()
    (project.root / "data").mkdir()
    _symlink(project.root / "src", project.root / "pkg", directory=True)
    _symlink(project.root / "metadata", project.root / "data", directory=True)
    _custom_registry(project, "metadata/tasks.json")

    result = init_project(project.root, runtime_shim="src/shim.py")

    assert "created metadata/tasks.json" in result.actions
    assert (project.root / "pkg/shim.py").read_text() == RUNTIME_SHIM
    assert Project.open(project.root).load_registry().tasks == {}
    before = _snapshot(tmp_path)
    assert init_project(project.root, runtime_shim="src/shim.py").actions == []
    assert _snapshot(tmp_path) == before


@verifies("12ce1c")
@pytest.mark.parametrize("metadata", [".git", ".hg", ".svn", ".byteplan/txn"])
@pytest.mark.parametrize("alias", [False, True])
def test_init_rejects_shim_in_vcs_or_transaction_metadata(
    project: ProjectFactory, tmp_path: Path, metadata: str, *, alias: bool
) -> None:
    target = project.root / metadata
    target.mkdir(parents=True)
    (target / "private.txt").write_bytes(b"retained metadata\x00")
    shim = f"{metadata}/shim.py"
    if alias:
        _symlink(project.root / "metadata", target, directory=True)
        shim = "metadata/shim.py"
    before = _snapshot(tmp_path)

    with pytest.raises(ConfigError):
        init_project(project.root, runtime_shim=shim)

    assert _snapshot(tmp_path) == before


@verifies("12ce1c")
@pytest.mark.parametrize("data", [b"[project\n", b'\xef\xbb\xbf[project]\r\nname="fixture"\r\n'])
def test_init_preserves_invalid_or_bom_pyproject_error_without_side_effects(
    project: ProjectFactory, tmp_path: Path, data: bytes
) -> None:
    (project.root / "pyproject.toml").write_bytes(data)
    before = _snapshot(tmp_path)

    with pytest.raises(ConfigError, match="invalid TOML"):
        init_project(project.root, runtime_shim="src/pkg/shim.py")

    assert _snapshot(tmp_path) == before


@verifies("12ce1c")
@pytest.mark.parametrize("path_kind", ["direct", "resolved_alias", "lexical_alias"])
def test_init_rejects_lock_descendant_before_any_side_effect(
    project: ProjectFactory, tmp_path: Path, path_kind: str
) -> None:
    state = project.root / ".byteplan"
    state.mkdir()
    (state / "keep.txt").write_bytes(b"retained state\x00\xff")
    registry = ".byteplan/scan.lock/tasks.json"
    if path_kind == "resolved_alias":
        _symlink(project.root / "metadata", state, directory=True)
        registry = "metadata/scan.lock/tasks.json"
    elif path_kind == "lexical_alias":
        ordinary = project.root / "ordinary"
        ordinary.mkdir()
        (ordinary / "keep.txt").write_bytes(b"retained ordinary data\r\n")
        _symlink(state / "scan.lock", ordinary, directory=True)
    _custom_registry(project, registry)
    before = _snapshot(tmp_path)

    with pytest.raises(ConfigError, match="transaction or lock state"):
        init_project(project.root, runtime_shim="pkg/markers.py")

    assert _snapshot(tmp_path) == before


@verifies("12ce1c")
@pytest.mark.parametrize(
    "registry",
    [".byteplan/scan.lock.backup/tasks.json", "scan.lock/tasks.json", "pkg/.byteplan/scan.lock/tasks.json"],
)
def test_init_keeps_ordinary_lock_lookalike_paths(project: ProjectFactory, tmp_path: Path, registry: str) -> None:
    _custom_registry(project, registry)

    init_project(project.root, runtime_shim="pkg/markers.py")

    assert (project.root / registry).is_file()
    Project.open(project.root).scan(dry_run=False)
    before = _snapshot(tmp_path)
    assert init_project(project.root, runtime_shim="pkg/markers.py").actions == []
    assert _snapshot(tmp_path) == before
