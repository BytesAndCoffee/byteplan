# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Interface methods and deliberate no-op overrides are not stubs (found trialling bytesim)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from byteplan.api import Project

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory, RunCli

BASE = """\
class CommandHost:
    def queue_action(self, tokens):
        raise NotImplementedError

    def refresh_sidebar(self):
        raise NotImplementedError

    def genuinely_unfinished(self):
        raise NotImplementedError
"""

MIXIN = """\
from pkg.base import CommandHost


class TrafficCommands(CommandHost):
    def queue_action(self, tokens):
        return tokens
"""

RUNNER = """\
from pkg.mixins import TrafficCommands


class ScriptRunner(TrafficCommands):
    def refresh_sidebar(self):
        pass  # headless: nothing to refresh

    def arrange(self):
        pass
"""


def stub_titles(project: ProjectFactory, *targets: str) -> list[str]:
    report = Project.open(project.root).scan(list(targets) or None, cwd=project.root, dry_run=True)
    return sorted(p.tag.title for p in report.proposals)


@pytest.fixture
def commands(project: ProjectFactory) -> ProjectFactory:
    project.init()
    project.write("pkg/base.py", BASE)
    project.write("pkg/mixins.py", MIXIN)
    project.write("pkg/runner.py", RUNNER)
    return project


def test_interfaces_and_overrides_are_not_stubs(commands: ProjectFactory) -> None:
    assert stub_titles(commands) == [
        "Implement CommandHost.genuinely_unfinished (detected stub)",  # nobody implements it
        "Implement ScriptRunner.arrange (detected stub)",  # not an override of anything
    ]


def test_interface_detection_is_transitive(commands: ProjectFactory) -> None:
    # refresh_sidebar is only implemented two levels down (ScriptRunner), and that
    # implementation is itself a no-op override of the base declaration.
    titles = stub_titles(commands)
    assert not any("refresh_sidebar" in t for t in titles)


def test_narrowed_scan_still_sees_subclasses_elsewhere(commands: ProjectFactory) -> None:
    assert stub_titles(commands, "pkg/base.py") == ["Implement CommandHost.genuinely_unfinished (detected stub)"]


def test_can_be_disabled(commands: ProjectFactory) -> None:
    pyproject = commands.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text() + "\n[tool.byteplan.detect]\nrespect_overrides = false\n")
    assert len(stub_titles(commands)) == 5


def test_writing_scan_annotates_only_real_stubs(commands: ProjectFactory, run_cli: RunCli) -> None:
    assert run_cli("scan", "--project", commands.root).code == 0
    base = (commands.root / "pkg/base.py").read_text()
    assert base.count("# TODO[") == 1
    assert "Implement CommandHost.genuinely_unfinished" in base
    assert run_cli("scan", "--project", commands.root).out.count("+0 added") == 1


# `byteplan init`: registry packaging warning -------------------------------------------------------


HATCH = '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n\n[project]\nname = "demo"\nversion = "0.1"\n'


@pytest.mark.parametrize(
    ("sdist", "warns"),
    [
        ('include = ["src/pkg", "tests", "README.md"]', False),  # bytesim's style: explicit list
        ('include = ["src", ".byteplan"]', True),
        ('only-include = ["src"]', False),
        ('only-include = ["src", ".byteplan"]', True),
        ('exclude = [".byteplan"]', False),
        ('exclude = ["docs"]', True),
        ('include = ["**/*.json"]\nexclude = [".byteplan/"]', False),
    ],
)
def test_init_packaging_warning_follows_hatch_rules(
    project: ProjectFactory,
    run_cli: RunCli,
    sdist: str,
    warns: bool,  # noqa: FBT001 - pytest parameter
) -> None:
    project.write("pyproject.toml", HATCH + f"\n[tool.hatch.build.targets.sdist]\n{sdist}\n", dedent=False)
    result = run_cli("init", "--project", project.root)
    assert result.code == 0
    assert ("would be shipped" in result.err or "so the registry is not shipped" in result.err) is warns
