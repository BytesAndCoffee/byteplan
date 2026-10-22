# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Phase 4e end to end: Markdown and JSON files through scan, Git commits and repair."""

from __future__ import annotations

import json
import re
import shutil
from typing import TYPE_CHECKING, Any

import pytest

from byteplan.api import Project
from byteplan.cli import EXIT_OK
from byteplan.files import collect_files
from tests.gitutil import git

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory, RunCli

INCLUDE = 'include = ["**/*.py", "**/*.md", "**/*.json", "**/*.jsonc"]'


def include_all(project: ProjectFactory) -> None:
    pyproject = project.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace('include = ["**/*.py"]', INCLUDE))


@pytest.fixture
def formats(project: ProjectFactory) -> ProjectFactory:
    project.init()
    include_all(project)
    return project


def tasks(project: ProjectFactory) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((project.root / ".byteplan/tasks.json").read_text())["tasks"]
    return data


def ids(text: str) -> list[str]:
    return re.findall(r"\[([0-9a-f]{4})\]", text)


def test_default_scope_is_still_python_only(project: ProjectFactory) -> None:
    project.init()
    project.write("README.md", "<!-- TODO: x -->\n")
    project.write("src/a.py", "# TODO: y\n")
    assert collect_files(Project.open(project.root).config).files == ("src/a.py",)


def test_unsupported_types_and_the_registry_are_never_collected(project: ProjectFactory) -> None:
    project.init()
    pyproject = project.root / "pyproject.toml"
    text = pyproject.read_text().replace('registry = ".byteplan/tasks.json"', 'registry = "tasks.json"')
    pyproject.write_text(text.replace('include = ["**/*.py"]', 'include = ["**/*"]'))
    project.write("tasks.json", '{"schema_version": 1, "tasks": {}}\n')
    for name in ("notes.txt", "a.yaml", "b.pyi", "c.md", "d.JSON", "e.markdown", "f.jsonc", "Makefile", ".md"):
        project.write(name, "")
    files = collect_files(Project.open(project.root).config).files
    assert files == ("c.md", "d.JSON", "e.markdown", "f.jsonc")


def test_scan_writes_ids_and_registers_tasks(formats: ProjectFactory, run_cli: RunCli) -> None:
    formats.write("README.md", "# Usage\n\n<!-- TODO: Document the merge driver\n     with an example. -->\n")
    formats.write("package.json", '{\n  "scripts": {"todo": "TODO: pin the version"}\n}\n')
    formats.write(".vscode/settings.jsonc", '{\n  // FIXME: turn on format-on-save\n  "editor.tabSize": 4\n}\n')
    result = run_cli("scan", "--project", formats.root)
    assert result.code == EXIT_OK, result.err
    assert "+3 added" in result.out

    readme = (formats.root / "README.md").read_text()
    package = (formats.root / "package.json").read_text()
    settings = (formats.root / ".vscode/settings.jsonc").read_text()
    (readme_id,) = ids(readme)
    assert readme.startswith(f"# Usage\n\n<!-- TODO[{readme_id}]: Document the merge driver\n")
    (package_id,) = ids(package)
    assert json.loads(package) == {"scripts": {"todo": f"TODO[{package_id}]: pin the version"}}
    (settings_id,) = ids(settings)
    assert f"// FIXME[{settings_id}]: turn on format-on-save" in settings

    registered = tasks(formats)
    assert registered[readme_id]["title"] == "Document the merge driver"
    assert registered[readme_id]["description"] == "with an example."
    assert registered[readme_id]["source"]["symbol"] == "Usage"
    assert registered[readme_id]["source"]["attachment_kind"] == "module"
    assert registered[package_id]["source"]["symbol"] == "/scripts/todo"
    assert registered[settings_id]["source"]["symbol"] == "/editor.tabSize"
    assert registered[settings_id]["kind"] == "FIXME"

    before = formats.snapshot()
    again = run_cli("scan", "--project", formats.root)
    assert "+0 added" in again.out
    assert formats.snapshot() == before


@pytest.mark.parametrize(
    ("path", "data"),
    [
        ("a.md", b"\xef\xbb\xbf# T\r\n<!-- TODO: crlf and bom -->\r\ntext"),
        ("a.md", b"<!-- TODO: no final newline -->"),
        ("a.json", b'\xef\xbb\xbf{\r\n  "a": "TODO: crlf and bom"\r\n}'),
        ("a.jsonc", b'{"a": 1} // TODO: no final newline'),
    ],
)
def test_annotation_changes_only_the_id(formats: ProjectFactory, run_cli: RunCli, path: str, data: bytes) -> None:
    formats.write(path, data)
    assert run_cli("scan", "--project", formats.root).code == EXIT_OK
    written = (formats.root / path).read_bytes()
    (task_id,) = ids(written.decode("utf-8-sig"))
    assert written == re.sub(rb"(TODO)", rb"\1[" + task_id.encode() + rb"]", data, count=1)


def test_moving_a_markdown_todo_between_sections_is_a_move(formats: ProjectFactory, run_cli: RunCli) -> None:
    formats.write("README.md", "# One\n<!-- TODO: travel -->\n# Two\n")
    assert run_cli("scan", "--project", formats.root).code == EXIT_OK
    (task_id,) = ids((formats.root / "README.md").read_text())
    formats.write("README.md", f"# One\n# Two\n<!-- TODO[{task_id}]: travel -->\n")
    assert run_cli("scan", "--project", formats.root).code == EXIT_OK
    task = tasks(formats)[task_id]
    assert task["source"]["symbol"] == "Two"
    assert [e["event"] for e in task["history"]][-1] == "moved"


def test_invalid_json_fails_the_scan_and_writes_nothing(formats: ProjectFactory, run_cli: RunCli) -> None:
    formats.write("README.md", "<!-- TODO: fine -->\n")
    formats.write("broken.json", '{"a": "TODO: x"\n')
    before = formats.snapshot()
    result = run_cli("scan", "--project", formats.root)
    assert result.code != EXIT_OK
    assert "broken.json: invalid JSON at line 1, column 1: unclosed '{'" in result.err
    assert formats.snapshot() == before


@pytest.mark.parametrize(
    ("path", "content"),
    [
        ("notes.md", "# A\n<!-- TODO[{id}]: shared -->\n<!-- TODO[{id}]: shared copy -->\n"),
        ("data.json", '{{"a": "TODO[{id}]: shared",\n "b": "TODO[{id}]: shared copy"}}\n'),
    ],
)
def test_repair_reassign(formats: ProjectFactory, run_cli: RunCli, path: str, content: str) -> None:
    formats.write(path, content.format(id="").replace("[]", ""))
    assert run_cli("scan", "--project", formats.root).code == EXIT_OK
    first = ids((formats.root / path).read_text())[0]
    formats.write(path, content.format(id=first))  # a copy-paste duplicated the ID
    result = run_cli(
        "repair", "--reassign", f"{path}:3" if path.endswith(".md") else f"{path}:2", "--project", formats.root
    )
    assert result.code == EXIT_OK, result.err
    first_after, second_after = ids((formats.root / path).read_text())
    assert first_after == first
    assert second_after != first
    assert tasks(formats)[second_after]["title"] == "shared copy"


# Git: staged checks and commit-time IDs ------------------------------------------------------------


@pytest.fixture
def hooked_formats(repo: ProjectFactory, run_cli: RunCli) -> ProjectFactory:
    include_all(repo)
    git(repo.root.parent, "commit", "-qam", "scan markdown and json")
    assert run_cli("git", "install-hooks", "--project", repo.root).code == EXIT_OK
    return repo


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_commit_carries_ids_in_markdown_and_json(hooked_formats: ProjectFactory, run_cli: RunCli) -> None:
    top = hooked_formats.root.parent
    hooked_formats.write("docs/guide.md", "## Setup\n\n<!-- TODO: Explain the hook modes -->\n")
    hooked_formats.write("config/app.json", '{"retries": "TODO: choose a retry budget"}\n')
    git(top, "add", ".")
    assert run_cli("check", "--staged", "--project", hooked_formats.root).code != EXIT_OK  # untagged
    result = git(top, "commit", "-qm", "docs and config", check=False)
    assert result.returncode == 0, result.stdout + result.stderr

    committed_guide = git(top, "show", "HEAD:proj/docs/guide.md").stdout
    committed_config = git(top, "show", "HEAD:proj/config/app.json").stdout
    registry = json.loads(git(top, "show", "HEAD:proj/.byteplan/tasks.json").stdout)["tasks"]
    (guide_id,) = ids(committed_guide)
    (config_id,) = ids(committed_config)
    assert registry[guide_id]["source"] == {
        "attachment_kind": "module",
        "decl_line": None,
        "line": 3,
        "path": "docs/guide.md",
        "representation": "comment",
        "symbol": "Setup",
    }
    assert registry[config_id]["source"]["symbol"] == "/retries"
    assert git(top, "status", "--porcelain").stdout == ""  # the working tree matches the commit
    assert run_cli("check", "--commit", "HEAD", "--project", hooked_formats.root).code == EXIT_OK


def test_scan_writes_ids_into_link_reference_comments(formats: ProjectFactory, run_cli: RunCli) -> None:
    formats.write("README.md", "# Usage\n\n[//]: # (TODO: Hidden from the rendered page)\n")
    assert run_cli("scan", "--project", formats.root).code == EXIT_OK
    readme = (formats.root / "README.md").read_text()
    (task_id,) = ids(readme)
    assert readme == f"# Usage\n\n[//]: # (TODO[{task_id}]: Hidden from the rendered page)\n"
    assert tasks(formats)[task_id]["source"]["symbol"] == "Usage"
