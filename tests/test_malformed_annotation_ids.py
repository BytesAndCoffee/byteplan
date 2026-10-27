# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Malformed identity syntax is visible without guessing identities or editing source."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from byteplan._todo import verifies
from byteplan.api import Project
from byteplan.config import DetectConfig
from byteplan.diagnostics import Code
from byteplan.models import Presence, Status
from byteplan.scanner import scan_file
from byteplan.scanner.source import decode_source

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory, RunCli


@verifies("668a6c")
@pytest.mark.parametrize(
    ("path", "text", "line"),
    [
        ("a.py", "# TODO[abcdef: unfinished\nx = 1\n", 1),
        ("a.py", "x = 1  # todo[abcdef\n", 1),
        ("a.py", "# TODO[\nx = 1\n", 1),
        ("plan.md", "<!-- TODO[abcdef: unfinished -->\n", 1),
        ("plan.md", "[//]: # (TODO[abcdef: unfinished)\n", 1),
        ("a.jsonc", "{\n// TODO[abcdef: unfinished\n}\n", 2),
        ("a.jsonc", "{/* TODO[abcdef: unfinished */}\n", 1),
        ("a.json", '{"work": "TODO[abcdef: unfinished"}\n', 1),
        ("a.json", '{"work": "TODO[abcdef"}\n', 1),
        ("a.json", '{"work": "TODO["}\n', 1),
        ("a.json", '{"work": "TODO[abcdef: say \\"hello\\""}\n', 1),
    ],
)
def test_unclosed_id_bracket_is_diagnosed(path: str, text: str, line: int) -> None:
    source = decode_source(path, text.encode())
    report = scan_file(source, DetectConfig(json_string_values=True))
    assert report.tags == []
    assert len(report.diagnostics) == 1
    diagnostic = report.diagnostics[0]
    assert diagnostic.code is Code.MALFORMED_ID
    assert diagnostic.locations[0].path == path
    assert diagnostic.locations[0].line == line
    assert "closing" in diagnostic.message
    assert diagnostic.hint is not None
    assert "]" in diagnostic.hint
    assert source.encode() == text.encode()


@verifies("668a6c")
@pytest.mark.parametrize("task_id", ["abcd", "abcdef", "abcdef0123456789"])
@pytest.mark.parametrize(
    ("path", "template"),
    [
        ("a.py", "# Todo[{task_id}]: feature\nx = 1\n"),
        ("plan.md", "<!-- Todo[{task_id}]: feature -->\n"),
        ("a.jsonc", "{{// Todo[{task_id}]: feature\n}}\n"),
        ("a.json", '{{"work": "TODO[{task_id}]: feature"}}\n'),
    ],
)
def test_supported_identity_grammar_is_unchanged(path: str, template: str, task_id: str) -> None:
    text = template.format(task_id=task_id)
    report = scan_file(decode_source(path, text.encode()), DetectConfig(json_string_values=True))
    assert not report.diagnostics
    assert [tag.task_id for tag in report.tags] == [task_id]


@verifies("668a6c")
@pytest.mark.parametrize(
    ("path", "text"),
    [
        ("a.py", '# Todo list model\nx = "# TODO[abcdef: string"\n'),
        ("a.py", "# TODO(owner): unsupported owner\nx = 1\n"),
        ("a.py", "# TODO[abcdef: ignored byteplan: ignore\nx = 1\n"),
        ("a.py", "# byteplan: ignore-file\n# TODO[abcdef: ignored\nx = 1\n"),
        ("plan.md", "```md\n<!-- TODO[abcdef: code -->\n```\n"),
        ("plan.md", "---\nvalue: '<!-- TODO[abcdef: metadata -->'\n---\n"),
        ("plan.md", "<!-- Todo list model -->\n"),
        ("a.jsonc", '{"work": "TODO"}\n'),
        ("a.jsonc", '{"TODO[abcdef: key": 1}\n'),
        ("a.jsonc", "{// Todo list model\n}\n"),
        ("a.jsonc", "{// TODO[abcdef: ignored byteplan: ignore\n}\n"),
        ("a.jsonc", "// byteplan: ignore-file\n{// TODO[abcdef: ignored\n}\n"),
    ],
)
def test_non_annotations_and_suppressions_remain_excluded(path: str, text: str) -> None:
    report = scan_file(decode_source(path, text.encode()), DetectConfig(json_string_values=True))
    assert report.tags == []
    assert report.diagnostics == []


@verifies("668a6c")
def test_json_string_suppression_still_applies() -> None:
    report = scan_file(
        decode_source("a.json", b'{"work": "TODO[abcdef: feature"}\n'), DetectConfig(json_string_values=False)
    )
    assert not report.tags
    assert not report.diagnostics


@verifies("668a6c")
def test_malformed_tag_does_not_hide_in_previous_task_description() -> None:
    text = "# TODO[abcd]: first\n#   description\n# TODO[abcdef: broken\nx = 1\n"
    report = scan_file(decode_source("a.py", text.encode()), DetectConfig())
    assert [tag.task_id for tag in report.tags] == ["abcd"]
    assert report.tags[0].description == "description"
    assert [d.code for d in report.diagnostics] == [Code.MALFORMED_ID]


@verifies("668a6c")
def test_project_scan_reports_malformed_identity_without_source_edits(project: ProjectFactory, run_cli: RunCli) -> None:
    project.init()
    source = project.write("src/a.py", "# TODO[abcdef: broken\nx = 1\n")
    p = Project.open(project.root)
    before = source.read_bytes()
    registry_before = p.config.registry_path.read_bytes()
    for dry_run in (True, False, False):
        report = p.scan(dry_run=dry_run)
        assert not report.tags
        assert not report.proposals
        assert [d.code for d in report.diagnostics] == [Code.MALFORMED_ID]
        assert source.read_bytes() == before
        assert p.config.registry_path.read_bytes() == registry_before
        assert not p.list_tasks()
    result = run_cli("check", "--project", project.root, "--format", "json")
    assert '"malformed_id"' in result.out
    assert "closing" in result.err
    assert source.read_bytes() == before


@verifies("668a6c")
@pytest.mark.parametrize("bom_crlf", [False, True])
def test_registered_task_with_broken_bracket_keeps_identity_and_open_status(
    project: ProjectFactory, *, bom_crlf: bool
) -> None:
    project.init()
    source = project.write("src/a.py", "# TODO: existing task\nx = 1\n")
    p = Project.open(project.root)
    p.scan(dry_run=False)
    (task,) = p.list_tasks()
    before_history = list(task.history)
    newline = "\r\n" if bom_crlf else "\n"
    broken = f"# TODO[{task.id}: existing task{newline}x = 1{newline}".encode()
    if bom_crlf:
        broken = b"\xef\xbb\xbf" + broken
    source.write_bytes(broken)
    registry_before = p.config.registry_path.read_bytes()
    preview = p.scan(dry_run=True)
    assert Code.MALFORMED_ID in {d.code for d in preview.diagnostics}
    assert p.config.registry_path.read_bytes() == registry_before
    result = p.scan(dry_run=False)
    assert Code.MALFORMED_ID in {d.code for d in result.diagnostics}
    assert not result.proposals
    assert not result.summary.added
    assert source.read_bytes() == broken
    (current,) = p.list_tasks()
    assert current.id == task.id
    assert current.status is Status.OPEN
    assert current.presence is Presence.MISSING
    assert current.history[: len(before_history)] == before_history
    assert task.id in p.load_registry().reserved_ids
