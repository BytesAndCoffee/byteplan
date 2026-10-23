# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""``byteplan tests scaffold``: plan a deliberately failing acceptance test for a task.

Pure planning: the caller supplies the task, the target file's current text and what's
available, and gets back the new file text (or a ``ScaffoldError``). Writing goes through
the usual lock, journal and hash checks.

* **Zero false greens.** The body always ends in an unconditional
  ``pytest.fail("BytePlan <id>: acceptance test not implemented")``. GIVEN/WHEN/THEN lines
  are comments (they never open with a tag, so they aren't tasks). ``--policy xfail`` /
  ``skip`` add a marker on top; neither outcome is evidence.
* **Placeholders are detected statically.** A test whose body, after its docstring, is only
  a ``pytest.fail(...)`` call is a placeholder; editing the body is all it takes to stop
  being one.
* **Existing files are only appended to.** The function goes at the end after two blank
  lines, missing imports go after the file's leading imports, and the new module must equal
  the old one plus exactly those additions.
"""

from __future__ import annotations

import ast
import posixpath
import re
import warnings
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from byteplan.edits import header_end
from byteplan.errors import ByteplanError, EditError
from byteplan.models import AttachmentKind

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from byteplan.config import ScaffoldConfig
    from byteplan.models import Task

FAIL_MESSAGE = "BytePlan {id}: acceptance test not implemented"
NO_SOURCE_FILE = "test_byteplan_tasks.py"
_NAME_RE = re.compile(r"test_[A-Za-z0-9_]*")
NEEDS_PATH = "scaffold_needs_path"
RUNTIME_UNAVAILABLE = "runtime_unavailable"
INVALID_NAME = "invalid_test_name"
MARKER_NOT_ENABLED = "marker_not_enabled"


class ScaffoldError(ByteplanError):
    """The scaffold can't be planned safely; ``code`` names the diagnostic."""

    def __init__(self, code: str, message: str, hint: str | None = None) -> None:
        super().__init__(f"{code}: {message}" + (f" ({hint})" if hint else ""))
        self.code = code
        self.hint = hint


@dataclass(frozen=True)
class Target:
    """What the test is about, from the task's declaration."""

    kind: AttachmentKind | None
    qualname: str | None
    is_async: bool = False


@dataclass(frozen=True)
class ScaffoldPlan:
    path: str
    name: str
    node: str
    text: str  # the whole file after the edit
    created: bool
    imports: tuple[str, ...] = field(default_factory=tuple)  # import lines added


# Where and what --------------------------------------------------------------------------------


def target_path(task: Task, config: ScaffoldConfig, python_files: Iterable[str]) -> str:
    """The default test file for a task (``--path`` overrides it)."""
    if task.source is None:
        return posixpath.join(config.directory, NO_SOURCE_FILE)
    source = task.source.path
    stem = posixpath.splitext(posixpath.basename(source))[0]
    if stem == "__init__":
        stem = posixpath.basename(posixpath.dirname(source)) or "init"
    filename = config.filename.replace("{module}", stem)
    if config.mirror:
        package = posixpath.dirname(source)
        package = package.removeprefix("src/") if package != "src" else ""
        return posixpath.normpath(posixpath.join(config.directory, package, filename))
    namesakes = sorted(
        path
        for path in python_files
        if path != source and _stem(path) == stem and not path.startswith(config.directory.rstrip("/") + "/")
    )
    if namesakes:
        raise ScaffoldError(
            NEEDS_PATH,
            f"{source} and {namesakes[0]} would both map to {posixpath.join(config.directory, filename)}",
            "pass --path, or set [tool.byteplan.tests.scaffold] mirror = true",
        )
    return posixpath.join(config.directory, filename)


def _is_docstring(node: ast.stmt) -> bool:
    return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)


def _stem(path: str) -> str:
    stem = posixpath.splitext(posixpath.basename(path))[0]
    return posixpath.basename(posixpath.dirname(path)) if stem == "__init__" else stem


def snake(name: str) -> str:
    name = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name)
    return re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_").lower()


def default_name(task: Task, target: Target, taken: set[str]) -> str:
    parts = [snake(p) for p in (target.qualname or "").split(".") if p and p != "<locals>"]
    base = "test_" + "_".join(parts) if parts else f"test_task_{task.id}"
    if base not in taken:
        return base
    candidate = f"{base}_{task.id}"
    number = 2
    while candidate in taken:
        candidate = f"{base}_{task.id}_{number}"
        number += 1
    return candidate


def defined_names(tree: ast.Module) -> set[str]:
    """Top-level names a new test function must not reuse."""
    names: set[str] = set()
    # FIXME[5aae]: [P2] Collect occupied test names inside module-level control-flow blocks
    #   An existing test_f under if/try/with is missed here, so scaffolding can append
    #   another test_f that overwrites the original test and silently drops its coverage.
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            names.update((alias.asname or alias.name).split(".")[0] for alias in node.names)
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names.update(n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name))
    return names


# Rendering -------------------------------------------------------------------------------------


def _doc(text: str) -> str:
    """Text safe inside a triple-quoted docstring."""
    return " ".join(text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"').split())


def render(
    task: Task,
    target: Target,
    name: str,
    *,
    policy: str,
    link_style: str,
    async_tests: str,
    nl: str = "\n",
) -> str:
    message = FAIL_MESSAGE.format(id=task.id)
    decorators: list[str] = []
    if link_style == "verifies":
        decorators.append(f'@verifies("{task.id}")')
    elif link_style == "marker":
        decorators.append(f'@pytest.mark.byteplan("{task.id}")')
    if policy == "xfail":
        decorators.append(f'@pytest.mark.xfail(reason="{message}", strict=True)')
    elif policy == "skip":
        decorators.append(f'@pytest.mark.skip(reason="{message}")')
    use_async = target.is_async and async_tests in {"pytest-asyncio", "anyio"}
    if use_async:
        decorators.append("@pytest.mark.asyncio" if async_tests == "pytest-asyncio" else "@pytest.mark.anyio")

    qualname = target.qualname or f"task {task.id}"
    kind = target.kind.value if target.kind is not None else "task"
    owner = qualname.rsplit(".", 1)[0] if "." in qualname else None
    if target.kind is AttachmentKind.METHOD and owner:
        when = [f"# WHEN: TODO - exercise {qualname} (needs a {owner} instance; none is assumed)"]
    elif target.kind is AttachmentKind.CLASS:
        when = [f"# WHEN: TODO - exercise {qualname}'s behaviour (constructing it isn't assumed)"]
    elif target.kind in {AttachmentKind.FUNCTION, AttachmentKind.METHOD}:
        when = [f"# WHEN: TODO - {'await' if use_async else 'call'} {qualname}"]
    else:
        when = [f"# WHEN: TODO - exercise the code task {task.id} is about"]
    body = [
        '"""Acceptance test scaffold for BytePlan task ' + task.id + ".",
        "",
        f"Target: {_doc(qualname)} ({kind})",
        f"Requirement: {_doc(task.display_title)}",
        '"""',
        "# GIVEN: TODO - arrange the state this requirement depends on",
        *when,
        "# THEN: TODO - assert the required result",
        f'pytest.fail("{message}")',
    ]
    header = f"{'async def' if use_async else 'def'} {name}():"
    lines = [*decorators, header, *(f"    {line}" if line else "" for line in body)]
    return nl.join(lines) + nl


def required_imports(link_style: str, runtime: str | None) -> list[str]:
    imports = ["import pytest"]
    if link_style == "verifies":
        if runtime is None:
            raise ScaffoldError(
                RUNTIME_UNAVAILABLE,
                "@verifies needs byteplan-runtime (a dependency or dev dependency) or a configured shim",
                "add it, or use --link marker (with pytest_marker = true) or --link managed",
            )
        imports.append(f"from {runtime} import verifies")
    return imports


# Planning --------------------------------------------------------------------------------------


def _parse(path: str, text: str) -> ast.Module:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.parse(text, filename=path)
    except (SyntaxError, ValueError) as exc:
        raise ScaffoldError(NEEDS_PATH, f"{path} doesn't parse ({exc})", "fix it or pass --path") from exc


def _present(tree: ast.Module, statement: str) -> bool:
    wanted = ast.dump(ast.parse(statement).body[0])
    return any(ast.dump(node) == wanted for node in tree.body)


def _import_offset(tree: ast.Module, lines: Sequence[str]) -> int:
    """Line index (0-based) after the file's leading imports (or docstring), for new imports."""
    index = 0
    body = tree.body
    position = 0
    if body and _is_docstring(body[0]):
        position = body[0].end_lineno or 0
        index = 1
    while index < len(body) and isinstance(body[index], ast.Import | ast.ImportFrom):
        position = body[index].end_lineno or position
        index += 1
    # Never above a shebang or encoding cookie: Python only honours a cookie on line 1 or 2.
    return min(max(position, header_end(lines)), len(lines))


def plan(
    task: Task,
    target: Target,
    path: str,
    existing: str | None,
    *,
    name: str | None,
    policy: str,
    link_style: str,
    runtime: str | None,
    async_tests: str,
) -> ScaffoldPlan:
    imports = required_imports(link_style, runtime)
    if existing is None:
        if name is not None:
            _check_name(name, set())
        test = name or default_name(task, target, set())
        function = render(task, target, test, policy=policy, link_style=link_style, async_tests=async_tests)
        text = "\n".join(imports) + "\n\n\n" + function
        return ScaffoldPlan(path, test, f"{path}::{test}", text, created=True, imports=tuple(imports))

    tree = _parse(path, existing)
    taken = defined_names(tree)
    if name is not None:
        _check_name(name, taken)
    test = name or default_name(task, target, taken)
    match = re.search(r"\r\n|\n|\r", existing)
    nl = match.group() if match else "\n"
    missing = [line for line in imports if not _present(tree, line)]
    lines = existing.splitlines(keepends=True)
    if missing:
        at = _import_offset(tree, lines)
        lines[at:at] = [line + nl for line in missing]
    text = "".join(lines)
    if text and not text.endswith(("\n", "\r")):
        text += nl
    text = (
        text.rstrip("\r\n")
        + nl * 3
        + render(task, target, test, policy=policy, link_style=link_style, async_tests=async_tests, nl=nl)
    )
    ensure_only_added(path, existing, text, test, missing)
    return ScaffoldPlan(path, test, f"{path}::{test}", text, created=False, imports=tuple(missing))


def _check_name(name: str, taken: set[str]) -> None:
    if not _NAME_RE.fullmatch(name) or not name.isidentifier():
        raise ScaffoldError(INVALID_NAME, f"--name {name!r} must be a test_* identifier")
    if name in taken:
        raise ScaffoldError(INVALID_NAME, f"--name {name!r} is already used in the target file")


def ensure_only_added(path: str, before: str, after: str, name: str, imports: Sequence[str]) -> None:
    """The new module must be the old one plus the added imports and the added function."""
    old = _parse(path, before)
    new = _parse(path, after)
    added = {ast.dump(ast.parse(line).body[0]) for line in imports}
    kept = [
        node
        for node in new.body
        if ast.dump(node) not in added
        and not (isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == name)
    ]
    if [ast.dump(n) for n in kept] != [ast.dump(n) for n in old.body]:
        msg = f"{path}: adding the scaffold would change existing code; nothing was written"
        raise EditError(msg)


# Placeholder detection -------------------------------------------------------------------------


def is_placeholder(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A body that, after its docstring, is only a ``pytest.fail(...)`` call."""
    body = list(function.body)
    if body and _is_docstring(body[0]):
        body = body[1:]
    if len(body) != 1 or not isinstance(body[0], ast.Expr) or not isinstance(body[0].value, ast.Call):
        return False
    func = body[0].value.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "fail"
        and isinstance(func.value, ast.Name)
        and func.value.id == "pytest"
    )


def placeholder_nodes(path: str, text: str) -> set[str]:
    """Node IDs of the placeholder tests in a test file (functions and class methods)."""
    try:
        tree = _parse(path, text)
    except ScaffoldError:
        return set()
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and is_placeholder(node):
            found.add(f"{path}::{node.name}")
        elif isinstance(node, ast.ClassDef):
            found.update(
                f"{path}::{node.name}::{item.name}"
                for item in node.body
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and is_placeholder(item)
            )
    return found
