# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from byteplan.config import DEFAULT_EXCLUDE, find_project_root, load_config
from byteplan.errors import ConfigError

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import ProjectFactory


def test_defaults_without_table(project: ProjectFactory) -> None:
    config = load_config(project.root)
    assert config.registry_path == project.root.resolve() / ".byteplan/tasks.json"
    assert config.include == ("**/*.py",)
    assert config.exclude == DEFAULT_EXCLUDE
    assert config.detect.todo_tags == ("TODO", "FIXME", "HACK", "XXX")
    assert config.check.fail_on_duplicate_ids
    assert config.annotations.runtime_modules == ("byteplan_runtime",)


def test_values_are_loaded(project: ProjectFactory) -> None:
    project.write(
        "pyproject.toml",
        """
        [tool.byteplan]
        registry = "meta/tasks.json"
        include = ["src/**/*.py"]
        exclude = ["**/generated/**"]
        missing_policy = "ignore"

        [tool.byteplan.detect]
        todo_tags = ["TODO"]
        empty_classes = false

        [tool.byteplan.check]
        fail_on_missing = true
        """,
    )
    config = load_config(project.root)
    assert config.registry == "meta/tasks.json"
    assert config.include == ("src/**/*.py",)
    assert config.exclude == ("**/generated/**",)
    assert config.missing_policy == "ignore"
    assert config.detect.todo_tags == ("TODO",)
    assert not config.detect.empty_classes
    assert config.check.fail_on_missing


@pytest.mark.parametrize(
    ("toml", "message"),
    [
        ('[tool.byteplan]\nregistery = "x.json"\n', "unknown key 'registery'"),
        ("[tool.byteplan]\nauto_annotate = 1\n", "true or false"),
        ('[tool.byteplan]\ninclude = "src"\n', "list of strings"),
        ('[tool.byteplan]\nmissing_policy = "explode"\n', "missing_policy"),
        ('[tool.byteplan]\nregistry = "../outside.json"\n', "outside the project root"),
        ('[tool.byteplan]\nregistry = "tasks.yaml"\n', ".json"),
        ("[tool.byteplan.detect]\ntodo_tags = []\n", "must not be empty"),
        ('[tool.byteplan.detect]\ntodo_tags = ["TO DO"]\n', "must be a word"),
        ("[tool.byteplan]\ndetect = 3\n", "must be a table"),
        ("[tool.byteplan\n", "invalid TOML"),
        ("[tool.byteplan.detect]\nplaceholder_assignments = true\n", "not supported yet"),
        ('[tool.byteplan.annotations]\nruntime_modules = ["not a module"]\n', "not a module name"),
        ('[tool.byteplan.annotations]\nmode = "decorators"\n', "mode must be one of comment, preserve, decorator"),
    ],
)
def test_invalid_config(project: ProjectFactory, toml: str, message: str) -> None:
    project.write("pyproject.toml", toml)
    with pytest.raises(ConfigError, match=message):
        load_config(project.root)


def test_project_root_found_from_subdirectory(project: ProjectFactory) -> None:
    sub = project.write("src/pkg/mod.py", "").parent
    assert find_project_root(sub) == project.root.resolve()


def test_no_project_root(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match=r"no pyproject\.toml"):
        find_project_root(tmp_path)
