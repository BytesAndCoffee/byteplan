# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Merge-driver installation refuses unsafe destinations and uses literal Git patterns."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from byteplan._todo import verifies
from byteplan.api import Project
from byteplan.gitio import install_merge_driver
from byteplan.models import Task
from byteplan.registry import Registry, dumps, loads
from tests.gitutil import git

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import ProjectFactory, RunCli


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="requires Git")


def configure(project: ProjectFactory, registry: str = "records/tasks.json", report: str = "") -> Project:
    project.write(
        "pyproject.toml",
        '[project]\nname = "demo"\nversion = "0.1"\n[tool.byteplan]\n'
        f"registry = {json.dumps(registry)}\nreport_file = {json.dumps(report)}\n",
    )
    git(project.root, "init", "-q", "-b", "main")
    git(project.root, "config", "user.email", "test@example.com")
    git(project.root, "config", "user.name", "Test")
    git(project.root, "config", "commit.gpgsign", "false")
    return Project.open(project.root)


def symlink(path: Path, target: Path, *, directory: bool = False) -> None:
    try:
        path.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")


def snapshot(root: Path) -> dict[str, tuple[str, bytes | str]]:
    found: dict[str, tuple[str, bytes | str]] = {}
    for path in root.rglob("*"):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            found[rel] = ("link", os.readlink(path))
        elif path.is_file():
            found[rel] = ("file", path.read_bytes())
        else:
            found[rel] = ("dir", b"")
    return found


def merge_attribute(root: Path, path: str) -> str:
    result = subprocess.run(
        ["git", "check-attr", "-z", "merge", "--", path],
        cwd=root,
        capture_output=True,
        check=True,
    )
    assert not result.stderr
    return result.stdout.split(b"\0")[-2].decode("utf-8")


@verifies("e86b8e")
@pytest.mark.parametrize("outside", [True, False])
def test_state_directory_alias_refused_before_any_installation_write(
    project: ProjectFactory, run_cli: RunCli, tmp_path: Path, *, outside: bool
) -> None:
    configure(project)
    destination = tmp_path / "outside" if outside else project.root / "state"
    destination.mkdir()
    (destination / ".gitattributes").write_bytes(b"important.bin -text\n")
    symlink(project.root / ".byteplan", destination, directory=True)
    before = snapshot(tmp_path)
    result = run_cli("git", "install-merge-driver", "--project", project.root)
    assert result.code == 2
    assert "unsafe merge-driver installation" in result.err
    assert snapshot(tmp_path) == before


@verifies("e86b8e")
@pytest.mark.parametrize("problem", ["symlink", "directory", "parent-file", "overlap", "invalid-utf8"])
def test_every_attributes_destination_is_preflighted_before_the_first_mutation(
    project: ProjectFactory, run_cli: RunCli, tmp_path: Path, problem: str
) -> None:
    registry = ".byteplan/.gitattributes/nested/tasks.json" if problem == "overlap" else "records/tasks.json"
    configure(project, registry)
    state = project.root / ".byteplan"
    if problem == "parent-file":
        state.write_bytes(b"existing user file")
    elif problem != "overlap":
        state.mkdir()
        target = state / ".gitattributes"
        if problem == "symlink":
            outside = tmp_path / "outside-attributes"
            outside.write_bytes(b"important.bin -text\n")
            symlink(target, outside)
        elif problem == "directory":
            target.mkdir()
        else:
            target.write_bytes(b"\xff")
    before = snapshot(tmp_path)
    result = run_cli("git", "install-merge-driver", "--project", project.root)
    assert result.code == 2
    assert "unsafe merge-driver installation" in result.err
    assert snapshot(tmp_path) == before


@verifies("e86b8e")
@pytest.mark.parametrize(
    "registry",
    [".git/tasks.json", ".byteplan/txn/tasks.json", ".byteplan/scan.lock/tasks.json"],
)
def test_protected_installation_destinations_fail_without_side_effects(
    project: ProjectFactory, run_cli: RunCli, tmp_path: Path, registry: str
) -> None:
    configure(project, registry)
    before = snapshot(tmp_path)
    result = run_cli("git", "install-merge-driver", "--project", project.root)
    assert result.code == 2
    assert "unsafe merge-driver installation" in result.err
    assert snapshot(tmp_path) == before


@verifies("e86b8e")
@pytest.mark.parametrize(
    ("registry", "report"),
    [
        (".byteplan/archive.json/nested/tasks.json", ""),
        (".byteplan/archive.json", ""),
        ("records/tasks.json", "records/tasks.json/plan.md"),
    ],
)
def test_installation_cannot_turn_metadata_file_destinations_into_parents(
    project: ProjectFactory, run_cli: RunCli, tmp_path: Path, registry: str, report: str
) -> None:
    configure(project, registry, report)
    before = snapshot(tmp_path)
    result = run_cli("git", "install-merge-driver", "--project", project.root)
    assert result.code == 2
    assert "destinations overlap" in result.err
    assert snapshot(tmp_path) == before


@verifies("e86b8e", "9e4d1c")
def test_confined_ordinary_parent_alias_combines_rules_for_the_same_attributes_file(
    project: ProjectFactory,
) -> None:
    configure(project, "alias/tasks.json", "records/plan.md")
    (project.root / "records").mkdir()
    symlink(project.root / "alias", project.root / "records", directory=True)
    p = Project.open(project.root)
    assert install_merge_driver(p)
    assert merge_attribute(project.root, "alias/tasks.json") == "byteplan"
    assert merge_attribute(project.root, "records/plan.md") == "byteplan-report"
    before = snapshot(project.root)
    assert install_merge_driver(p) == []
    assert snapshot(project.root) == before


@verifies("9e4d1c")
@pytest.mark.parametrize(
    ("filename", "unrelated"),
    [
        ("tasks with space.json", "other.json"),
        ("tasks[one].json", "taskso.json"),
        ("#tasks.json", "other.json"),
        ("!tasks.json", "other.json"),
        ("café.json", "other.json"),
        pytest.param(
            "tasks*.json",
            "tasks-other.json",
            marks=pytest.mark.skipif(sys.platform == "win32", reason="invalid Windows filename"),
        ),
        pytest.param(
            "tasks?.json",
            "tasksx.json",
            marks=pytest.mark.skipif(sys.platform == "win32", reason="invalid Windows filename"),
        ),
        pytest.param(
            'tasks"quoted.json',
            "other.json",
            marks=pytest.mark.skipif(sys.platform == "win32", reason="invalid Windows filename"),
        ),
        pytest.param(
            "tasks\ttab.json",
            "other.json",
            marks=pytest.mark.skipif(sys.platform == "win32", reason="invalid Windows filename"),
        ),
        pytest.param(
            "tasks\nline.json",
            "other.json",
            marks=pytest.mark.skipif(sys.platform == "win32", reason="invalid Windows filename"),
        ),
    ],
)
def test_actual_git_patterns_match_only_literal_configured_names(
    project: ProjectFactory, filename: str, unrelated: str
) -> None:
    p = configure(project, f"records/{filename}", "task plan.md")
    project.write("records/.gitattributes", b"important.bin -text\r\n")
    assert install_merge_driver(p)
    assert (project.root / "records/.gitattributes").read_bytes().startswith(b"important.bin -text\r\n")
    assert merge_attribute(project.root, f"records/{filename}") == "byteplan"
    assert merge_attribute(project.root, "task plan.md") == "byteplan-report"
    assert merge_attribute(project.root, f"records/{unrelated}") == "unspecified"
    before = snapshot(project.root)
    assert install_merge_driver(p) == []
    assert snapshot(project.root) == before


@verifies("9e4d1c")
def test_spaced_registry_and_report_use_their_drivers_in_a_real_divergent_merge(
    project: ProjectFactory,
) -> None:
    p = configure(project, "records/tasks with space.json", "task plan.md")
    target = project.root / "records/tasks with space.json"

    def write_registry(*ids: str) -> None:
        record = Registry(
            reserved_ids=set(ids),
            tasks={task_id: Task(task_id, "TODO", task_id) for task_id in ids},
        )
        project.write("records/tasks with space.json", dumps(record))

    write_registry("aaaa")
    project.write("task plan.md", "base report\n")
    install_merge_driver(p)
    git(project.root, "add", "-A")
    git(project.root, "commit", "-qm", "base with drivers")
    git(project.root, "switch", "-q", "-c", "side")
    write_registry("aaaa", "bbbb")
    project.write("task plan.md", "side report\n")
    git(project.root, "commit", "-qam", "independent side task")
    git(project.root, "switch", "-q", "main")
    write_registry("aaaa", "cccc")
    project.write("task plan.md", "main report\n")
    git(project.root, "commit", "-qam", "independent main task")
    result = git(project.root, "merge", "--no-edit", "side", check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert set(loads(target.read_text(encoding="utf-8")).tasks) == {
        "aaaa",
        "bbbb",
        "cccc",
    }
    assert (project.root / "task plan.md").read_bytes() == b"main report\n"


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows junction check")
def test_native_windows_state_junction_is_refused_before_installation_writes(
    project: ProjectFactory, run_cli: RunCli, tmp_path: Path
) -> None:
    configure(project)
    destination = tmp_path / "outside"
    destination.mkdir()
    attributes = destination / ".gitattributes"
    attributes.write_bytes(b"important.bin -text\r\n")
    state = project.root / ".byteplan"
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(state), str(destination)],
        capture_output=True,
        check=True,
    )
    before_config = (project.root / ".git/config").read_bytes()
    try:
        result = run_cli("git", "install-merge-driver", "--project", project.root)
        assert result.code == 2
        assert "unsafe merge-driver installation" in result.err
        assert attributes.read_bytes() == b"important.bin -text\r\n"
        assert not (project.root / "records").exists()
        assert (project.root / ".git/config").read_bytes() == before_config
        assert state.exists()
    finally:
        state.rmdir()  # remove the junction itself, preserving its target
