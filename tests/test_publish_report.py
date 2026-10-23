# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""``scripts/publish_report.py``: the post-merge job that keeps ``report_file`` current on main."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from byteplan.api import Project
from byteplan.cli import EXIT_OK
from tests.gitutil import git

if TYPE_CHECKING:
    from types import ModuleType

    from tests.conftest import ProjectFactory, RunCli

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "publish_report.py"


@pytest.fixture(scope="module")
def publish_report() -> ModuleType:
    spec = importlib.util.spec_from_file_location("publish_report", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["publish_report"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def clones(repo: ProjectFactory, run_cli: RunCli, tmp_path: Path) -> tuple[Path, Path]:
    """A bare ``origin`` with ``report_branch = "main"``, and two clones of it: CI's and a developer's."""
    pyproject = repo.root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text().replace(
            'include = ["**/*.py"]', 'include = ["**/*.py"]\nreport_file = "byteplan.md"\nreport_branch = "main"'
        )
    )
    assert run_cli("scan", "--project", repo.root).code == EXIT_OK
    top = repo.root.parent
    git(top, "add", "-A")
    git(top, "commit", "-qm", "report on main")
    origin = tmp_path / "origin.git"
    git(tmp_path, "clone", "-q", "--bare", str(top), str(origin))
    paths = []
    for name in ("ci", "dev"):
        clone = tmp_path / name
        git(tmp_path, "clone", "-q", str(origin), str(clone))
        git(clone, "config", "user.email", "test@example.com")
        git(clone, "config", "user.name", "Test")
        git(clone, "config", "commit.gpgsign", "false")
        paths.append(clone / "proj")
    return paths[0], paths[1]


def add_task(project: Path, name: str, title: str) -> None:
    """A pull request merged to main: a new task in the registry, and the report left stale."""
    git(project, "switch", "-qc", name)
    (project / f"src/{name}.py").write_text(f"# TODO: {title}\n")
    Project.open(project).scan(dry_run=False)
    git(project, "add", "-A")
    git(project, "commit", "-qm", title)
    git(project, "switch", "-q", "main")
    git(project, "merge", "-q", "--no-ff", "--no-edit", name)
    git(project, "push", "-q", "origin", "HEAD:main")


def pushed_report(project: Path) -> str:
    git(project, "fetch", "-q", "origin")
    return git(project, "show", "origin/main:proj/byteplan.md").stdout


def test_publishes_the_regenerated_report(publish_report: Any, clones: tuple[Path, Path]) -> None:
    ci, dev = clones
    add_task(dev, "merged", "merged work")
    git(ci, "pull", "-q")
    assert publish_report.publish(ci) == "pushed"
    assert "merged work" in pushed_report(dev)
    assert publish_report.publish(ci) == "unchanged"


def test_retries_when_main_advances_before_the_push(
    publish_report: Any, clones: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    ci, dev = clones
    add_task(dev, "first", "first merge")
    git(ci, "pull", "-q")
    write_report = Project.write_report
    raced: list[bool] = []

    def racing_write(self: Project) -> bool:
        if not raced:  # another merge lands while the job is generating
            raced.append(True)
            add_task(dev, "second", "second merge")
        return write_report(self)

    monkeypatch.setattr(Project, "write_report", racing_write)
    assert publish_report.publish(ci) == "pushed"
    report = pushed_report(dev)
    assert "first merge" in report
    assert "second merge" in report  # regenerated from the newer registry, not just rebased


def test_gives_up_when_main_keeps_moving(
    publish_report: Any, clones: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    ci, dev = clones
    add_task(dev, "stale", "stale report")
    write_report = Project.write_report
    merges = iter(range(10))

    def racing_write(self: Project) -> bool:
        n = next(merges)
        add_task(dev, f"m{n}", f"merge {n}")
        return write_report(self)

    monkeypatch.setattr(Project, "write_report", racing_write)
    with pytest.raises(SystemExit, match="kept moving; gave up after 2 attempts"):
        publish_report.publish(ci, attempts=2)
