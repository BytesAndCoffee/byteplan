# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Restoring a hotfixed release reuses recorded annotations or keeps its authority."""

from __future__ import annotations

import ast
import tokenize
from typing import TYPE_CHECKING

import pytest

from byteplan._todo import verifies
from byteplan.api import Project
from byteplan.release import ReleaseError

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory


SOURCE = 'from byteplan_runtime import todo\n\n@todo("work", id="abcd")\ndef f():\n    return 1\n'


def _released(project: ProjectFactory, original: str = SOURCE) -> Project:
    project.init()
    project.write("src/demo.py", original, dedent=False)
    api = Project.open(project.root)
    api.import_task("abcd")
    api.release(allow_dirty=True)
    return api


@verifies("631761")
@pytest.mark.parametrize("partial", [False, True])
def test_restore_reuses_cherry_picked_annotations_and_imports(project: ProjectFactory, *, partial: bool) -> None:
    api = _released(project)
    changed = SOURCE.replace("return 1", "return 2")
    path = project.write("src/demo.py", changed, dedent=False)
    before = project.snapshot()
    preview = api.restore(dry_run=True, partial=partial)
    assert not preview.conflicts
    assert project.snapshot() == before
    assert api.stripped_release() is not None

    report = api.restore(partial=partial)
    assert not report.conflicts
    assert not report.partial
    assert path.read_text() == changed
    assert api.stripped_release() is None
    check = api.check()
    assert not check.blocked
    assert [tag.task_id for tag in check.tags].count("abcd") == 1


@verifies("631761")
@pytest.mark.parametrize(
    "original",
    [
        SOURCE.replace("import todo", "import todo as t").replace("@todo", "@t"),
        SOURCE.replace("import todo", "import todo as τ").replace("@todo", "@τ"),
        SOURCE.replace("from byteplan_runtime import todo", "import byteplan_runtime as bp").replace(
            "@todo", "@bp.todo"
        ),
        SOURCE.replace('@todo("work", id="abcd")', '@todo(\n    "work",\n    id="abcd",\n)  # retained'),
        SOURCE.replace("@todo", "@staticmethod\n@todo"),
        'from byteplan_runtime import todo\n\nclass C:\n    @todo("work", id="abcd", description="""first\nsecond\n    third""")\n    def f(self):\n        return 1\n',
    ],
)
def test_restore_reuses_aliases_multiline_blocks_and_stack_positions(project: ProjectFactory, original: str) -> None:
    api = _released(project, original)
    changed = original.replace("return 1", "return 2")
    path = project.write("src/demo.py", changed, dedent=False)
    assert not api.restore().conflicts
    assert path.read_text() == changed
    assert not api.check().blocked


@verifies("631761")
def test_restore_reuses_semantic_matches_without_losing_user_formatting(project: ProjectFactory) -> None:
    api = _released(project)
    changed = SOURCE.replace("import todo", "import (todo)  # cherry-picked").replace(
        '@todo("work", id="abcd")', "@todo('work', id='abcd')  # keep"
    )
    path = project.write("src/demo.py", changed, dedent=False)
    assert not api.restore().conflicts
    assert path.read_text() == changed


@verifies("631761")
def test_restore_reuses_recorded_names_in_a_larger_import(project: ProjectFactory) -> None:
    api = _released(project)
    changed = SOURCE.replace("import todo", "import todo, verifies  # user extension")
    path = project.write("src/demo.py", changed, dedent=False)
    assert not api.restore().conflicts
    assert path.read_text() == changed


@verifies("631761")
def test_restore_retains_partly_reintroduced_import_authority(project: ProjectFactory) -> None:
    original = SOURCE.replace("import todo", "import todo, verifies")
    api = _released(project, original)
    project.write("src/demo.py", SOURCE, dedent=False)
    report = api.restore(partial=True)
    assert report.conflicts
    assert "partly present" in report.conflicts[0]
    remaining = api.stripped_release()
    assert remaining is not None
    assert remaining["files"]["src/demo.py"]["imports"]
    project.write("src/demo.py", original, dedent=False)
    assert not api.restore().conflicts


@verifies("631761")
def test_restore_keeps_class_local_shadowing_conflicts_recoverable(project: ProjectFactory) -> None:
    original = SOURCE.replace(
        '@todo("work", id="abcd")\ndef f():\n    return 1',
        'class C:\n    @todo("work", id="abcd")\n    def f(self):\n        return 1',
    )
    api = _released(project, original)
    changed = original.replace("class C:\n", "class C:\n    todo = object()\n")
    path = project.write("src/demo.py", changed, dedent=False)
    report = api.restore(partial=True)
    assert report.partial
    assert any("shadowed" in conflict for conflict in report.conflicts)
    assert path.read_text() == changed
    project.write("src/demo.py", original, dedent=False)
    assert not api.restore().conflicts


@verifies("631761")
def test_restore_reuses_an_existing_import_when_its_old_anchor_is_gone(project: ProjectFactory) -> None:
    original = "VERSION = 1\n" + SOURCE
    api = _released(project, original)
    path = project.write("src/demo.py", SOURCE.replace("return 1", "return 2"), dedent=False)
    assert not api.restore().conflicts
    assert path.read_text().count("from byteplan_runtime import todo") == 1


@verifies("631761")
@pytest.mark.parametrize(
    ("changed", "message"),
    [
        (SOURCE.replace('"work"', '"new title"'), "competing @todo"),
        (SOURCE.replace('id="abcd"', 'id="ef01"'), "competing @todo"),
        (SOURCE.replace("@todo", '@todo("work", id="abcd")\n@todo'), "multiple copies"),
        (SOURCE.replace("@todo", "@staticmethod\n@todo"), "different decorator position"),
        (SOURCE.replace("\n\n@todo", "\nfrom byteplan_runtime import todo\n\n@todo"), "multiple copies"),
        (SOURCE.replace("\n\n@todo", "\ntodo = object()\n\n@todo"), "competing bindings"),
        (SOURCE.replace("\n\n@todo", "\nfrom elsewhere import todo\n\n@todo"), "competing bindings"),
        (SOURCE.replace("\n\n@todo", "\ndef todo(*a, **k): pass\n\n@todo"), "competing bindings"),
        (SOURCE + '\n@todo("work", id="abcd")\ndef other(): return 3\n', "exactly once"),
        (SOURCE + "\n# TODO[abcd]: another copy\n", "exactly once"),
        ('@todo("work", id="abcd")\ndef f(): return 2\nfrom byteplan_runtime import todo\n', "before its uses"),
        ("def f(): return 2\nfrom byteplan_runtime import (todo)  # edited\n", "before its uses"),
        (SOURCE.replace("return 1", "return ("), "syntax"),
    ],
)
def test_restore_conflicts_keep_all_authority_and_are_recoverable(
    project: ProjectFactory, changed: str, message: str
) -> None:
    api = _released(project)
    project.write("src/demo.py", changed, dedent=False)
    before = project.snapshot()
    release = api.stripped_release()
    assert release is not None
    for dry_run in (True, False):
        with pytest.raises(ReleaseError, match=message) as exc:
            api.restore(dry_run=dry_run)
        assert exc.value.code == "restore_conflict"
        assert project.snapshot() == before
    partial = api.restore(partial=True)
    assert partial.conflicts
    assert partial.partial
    remaining = api.stripped_release()
    assert remaining is not None
    pending = remaining["files"]["src/demo.py"]
    assert pending["decorators"] == release["files"]["src/demo.py"]["decorators"]
    assert (project.root / "src/demo.py").read_text().count('id="abcd"') == changed.count('id="abcd"')
    path = project.write("src/demo.py", SOURCE.replace("return 1", "return 2"), dedent=False)
    assert not api.restore().conflicts
    assert path.read_text().count('@todo("work", id="abcd")') == 1
    assert api.stripped_release() is None


@verifies("631761")
def test_restore_rejects_identity_copied_to_another_configured_source(project: ProjectFactory) -> None:
    api = _released(project)
    other = project.write("src/other.py", "# TODO[abcd]: copied while stripped\n", dedent=False)
    before = project.snapshot()
    with pytest.raises(ReleaseError, match="exactly once"):
        api.restore()
    assert project.snapshot() == before
    partial = api.restore(partial=True)
    assert partial.partial
    remaining = api.stripped_release()
    assert remaining is not None
    assert remaining["files"]["src/demo.py"]["imports"]
    other.unlink()
    assert not api.restore().conflicts
    assert not api.check().blocked


@verifies("631761")
def test_restore_retry_checks_the_import_even_after_its_record_was_consumed(project: ProjectFactory) -> None:
    api = _released(project)
    project.write("src/demo.py", "def renamed(): return 2\n", dedent=False)
    assert api.restore(partial=True).partial
    remaining = api.stripped_release()
    assert remaining is not None
    assert not remaining["files"]["src/demo.py"]["imports"]
    project.write("src/demo.py", "def f(): return 2\nfrom byteplan_runtime import todo\n", dedent=False)
    before = project.snapshot()
    with pytest.raises(ReleaseError, match="runtime import before f"):
        api.restore()
    assert project.snapshot() == before
    project.write("src/demo.py", SOURCE, dedent=False)
    assert not api.restore().conflicts


@verifies("631761")
def test_restore_reports_unparseable_unrelated_sources_without_clearing_authority(project: ProjectFactory) -> None:
    api = _released(project)
    project.write("src/other.py", "def broken(:\n", dedent=False)
    before = project.snapshot()
    with pytest.raises(ReleaseError, match=r"src/other\.py"):
        api.restore()
    assert project.snapshot() == before
    report = api.restore(partial=True)
    assert report.conflicts
    assert report.partial
    assert api.stripped_release() is not None


@verifies("631761")
def test_partial_restore_reuses_safe_files_and_retries_competing_annotations(project: ProjectFactory) -> None:
    project.init()
    project.write("src/demo.py", SOURCE, dedent=False)
    tests = 'from byteplan_runtime import verifies\n\n@verifies("abcd")\ndef test_work(): assert True\n'
    project.write("tests/test_work.py", tests, dedent=False)
    api = Project.open(project.root)
    api.import_task("abcd")
    api.release(allow_dirty=True)
    project.write("src/demo.py", SOURCE.replace('"work"', '"changed"'), dedent=False)
    project.write("tests/test_work.py", tests + "\n# hotfix\n", dedent=False)
    report = api.restore(partial=True)
    assert report.conflicts
    release = api.stripped_release()
    assert release is not None
    assert set(release["files"]) == {"src/demo.py"}
    assert (project.root / "tests/test_work.py").read_text().count('@verifies("abcd")') == 1
    project.write("src/demo.py", SOURCE, dedent=False)
    assert not api.restore().conflicts
    assert not api.check().blocked


@verifies("631761")
def test_restore_preserves_selected_runtime_and_source_encoding(project: ProjectFactory) -> None:
    project.write(
        "pyproject.toml",
        (project.root / "pyproject.toml").read_text()
        + '\n[tool.byteplan.annotations]\nruntime_modules = ["pkg.annotations"]\n',
        dedent=False,
    )
    original = ("# coding: latin-1\n# caf\xe9\n" + SOURCE.replace("byteplan_runtime", "pkg.annotations")).replace(
        "\n", "\r\n"
    )
    api = _released(project, original)
    changed = original.replace("return 1", "return 2").encode("latin-1")
    path = project.write("src/demo.py", changed)
    assert not api.restore().conflicts
    assert path.read_bytes() == changed


@verifies("631761")
@pytest.mark.parametrize("original_indent", ["", "    ", "\t"])
@pytest.mark.parametrize(
    "literal",
    [
        '"""first\nsecond\n    雪"""',
        'r"""first\\n\n    second\n\t雪"""',
        '"first\\\n    雪"',
    ],
)
def test_restore_moved_decorator_preserves_literal_ast_and_description(
    project: ProjectFactory, original_indent: str, literal: str
) -> None:
    new_indent = "    " if not original_indent else ""
    decorator = (
        original_indent
        + "@todo(  # annotation comment\n"
        + original_indent
        + '    "work", id="abcd",\n'
        + original_indent
        + "    description="
        + literal
        + ",  # literal comment\n"
        + original_indent
        + ")  # trailing comment\n"
    )
    original = (
        "from byteplan_runtime import todo\n\n"
        + ("if True:\n" if original_indent else "")
        + decorator
        + original_indent
        + "def f():\n"
        + original_indent
        + "    return 1\n"
    )
    expected = next(node for node in ast.walk(ast.parse(original)) if isinstance(node, ast.FunctionDef))
    api = _released(project, original)
    description = api.get_task("abcd").description
    changed = ("if True:\n" if new_indent else "") + new_indent + "def f():\n" + new_indent + "    return 2\n"
    path = project.write("src/demo.py", changed, dedent=False)
    before = project.snapshot()
    assert not api.restore(dry_run=True).conflicts
    assert project.snapshot() == before
    assert api.stripped_release() is not None
    assert not api.restore().conflicts
    restored = path.read_text()
    actual = next(node for node in ast.walk(ast.parse(restored)) if isinstance(node, ast.FunctionDef))
    assert ast.dump(actual.decorator_list[0]) == ast.dump(expected.decorator_list[0])
    assert literal in restored
    assert all(comment in restored for comment in ("# annotation comment", "# literal comment", "# trailing comment"))
    assert "return 2" in restored
    check = api.check()
    assert not check.blocked
    assert len(check.tags) == 1
    assert check.tags[0].description == description
    assert api.stripped_release() is None


@verifies("631761")
def test_restore_keeps_authority_when_reindentation_cannot_preserve_annotation_ast(
    project: ProjectFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = SOURCE.replace('id="abcd"', 'id="abcd", description="""first\nsecond\n    third"""')
    api = _released(project, original)
    path = project.write("src/demo.py", "if True:\n    def f():\n        return 2\n", dedent=False)
    before = project.snapshot()
    generate_tokens = tokenize.generate_tokens
    # Missing literal boundaries simulate an unsafe text transformation. The AST
    # postcondition must reject it even though the candidate still parses.
    with monkeypatch.context() as patch:
        patch.setattr(
            tokenize,
            "generate_tokens",
            lambda read: (token for token in generate_tokens(read) if token.type != tokenize.STRING),
        )
        for dry_run in (True, False):
            with pytest.raises(ReleaseError, match="can't preserve @todo"):
                api.restore(dry_run=dry_run)
            assert project.snapshot() == before
        report = api.restore(partial=True)
        assert report.partial
        assert any("can't preserve @todo" in conflict for conflict in report.conflicts)
        remaining = api.stripped_release()
        assert remaining is not None
        assert remaining["files"]["src/demo.py"]["decorators"]
        assert "@todo" not in path.read_text()
    assert not api.restore().conflicts
    assert api.check().tags[0].description == api.get_task("abcd").description
    assert api.stripped_release() is None
