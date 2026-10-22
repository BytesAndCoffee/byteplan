# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from byteplan.config import load_config
from byteplan.errors import ConfigError
from byteplan.files import collect_files, resolve_targets

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import ProjectFactory


def files(project: ProjectFactory, targets: list[str] | None = None) -> list[str]:
    return list(collect_files(load_config(project.root), targets).files)


def test_sorted_python_files_only(project: ProjectFactory) -> None:
    for rel in ["src/b.py", "src/a.py", "src/pkg/__init__.py", "README.md", "src/stub.pyi", "z.py"]:
        project.write(rel, "")
    assert files(project) == ["src/a.py", "src/b.py", "src/pkg/__init__.py", "z.py"]


def test_default_excludes(project: ProjectFactory) -> None:
    for rel in [".venv/lib/x.py", "a/__pycache__/x.py", "build/lib/x.py", ".byteplan/x.py", ".git/x.py", "ok.py"]:
        project.write(rel, "")
    assert files(project) == ["ok.py"]


def test_include_and_exclude(project: ProjectFactory) -> None:
    project.write("pyproject.toml", '[tool.byteplan]\ninclude = ["src/**/*.py"]\nexclude = ["**/generated/**"]\n')
    for rel in ["src/a.py", "src/generated/g.py", "tests/t.py"]:
        project.write(rel, "")
    assert files(project) == ["src/a.py"]


def test_gitignore_respected_including_nested_and_parent(project: ProjectFactory) -> None:
    # The Git top is one level above the project, like this repository's layout.
    git_top = project.root.parent
    (git_top / ".git").mkdir()
    (git_top / ".gitignore").write_text("proj/ignored_by_parent.py\n")
    project.write(".gitignore", "secret/\n*_local.py\n")
    project.write("src/.gitignore", "gen_*.py\n")
    for rel in ["ignored_by_parent.py", "secret/x.py", "a_local.py", "src/gen_x.py", "src/keep.py"]:
        project.write(rel, "")
    assert files(project) == ["src/keep.py"]


def test_gitignore_can_be_disabled(project: ProjectFactory) -> None:
    project.write("pyproject.toml", "[tool.byteplan]\nrespect_gitignore = false\n")
    project.write(".gitignore", "*.py\n")
    project.write("a.py", "")
    assert files(project) == ["a.py"]


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="symlinks unavailable")
def test_symlinks_are_not_followed(project: ProjectFactory, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "o.py").write_text("")
    real = project.write("src/real.py", "")
    try:
        os.symlink(outside, project.root / "linked_dir")
        os.symlink(real, project.root / "src" / "alias.py")
    except OSError:
        pytest.skip("cannot create symlinks")
    assert files(project) == ["src/real.py"]


def test_narrowed_scope(project: ProjectFactory) -> None:
    for rel in ["src/a/x.py", "src/a/y.py", "src/b/z.py"]:
        project.write(rel, "")
    scope = collect_files(load_config(project.root), ["src/a"])
    assert scope.files == ("src/a/x.py", "src/a/y.py")
    assert scope.narrowed
    assert scope.covers("src/a/new.py")
    assert not scope.covers("src/b/z.py")


def test_full_scope_covers_everything(project: ProjectFactory) -> None:
    assert collect_files(load_config(project.root)).covers("anything.py")


def test_resolve_targets_rejects_paths_outside_root(project: ProjectFactory, tmp_path: Path) -> None:
    root = project.root.resolve()
    project.write("src/a.py", "")
    assert resolve_targets(root, ["src/a.py", "src"], cwd=root) == ("src", "src/a.py")
    with pytest.raises(ConfigError, match="outside the project root"):
        resolve_targets(root, [tmp_path], cwd=root)
    with pytest.raises(ConfigError, match="does not exist"):
        resolve_targets(root, ["nope.py"], cwd=root)
