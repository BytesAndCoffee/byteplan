# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Internal initialize orchestration delegated by Project."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pathspec

from byteplan import registry as registry_io
from byteplan.config import (
    DEFAULT_REGISTRY,
    PYPROJECT,
    find_project_root,
    load_config,
    read_pyproject,
)
from byteplan.errors import (
    ConfigError,
)
from byteplan.persistence import (
    STATE_DIR,
    atomic_write_bytes,
)
from byteplan.registry import Registry, load_registry
from byteplan.scanner.source import decode_source
from byteplan.writeguard import control_directory, project_target

if TYPE_CHECKING:
    from collections.abc import Sequence


from byteplan._api_types import InitResult

RUNTIME_SHIM = '''"""BytePlan task markers, inert at runtime (written by `byteplan init --runtime-shim`).

BytePlan reads @todo/@verifies statically; at runtime they return the object unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

_T = TypeVar("_T")


def _identity(obj: _T) -> _T:
    return obj


def todo(
    title: str,
    /,
    *,
    id: str | None = None,  # noqa: A002 - BytePlan's documented keyword
    kind: str = "TODO",
    description: str = "",
    test: str | None = None,
    tests: Sequence[str] = (),
) -> Callable[[_T], _T]:
    del title, id, kind, description, test, tests
    return _identity


def verifies(*ids: str) -> Callable[[_T], _T]:
    del ids
    return _identity
'''


_SDIST_BLOCK = """\
[tool.hatch.build.targets.sdist]
exclude = [".byteplan"]
"""


_CONFIG_BLOCK = """\
[tool.byteplan]
registry = ".byteplan/tasks.json"
include = ["**/*.py"]
"""


BYTEPLAN_GITIGNORE = "txn/\nscan.lock\n"


def shim_module_name(rel: str) -> str:
    """The import name of a shim at a project-relative path (``src/`` layouts supported)."""
    stem = rel.removesuffix(".py").removesuffix("/__init__").removeprefix("src/")
    return stem.replace("/", ".")


def _init_target(root: Path, path: Path, *, control: bool = False) -> Path:
    """Apply the shared write boundary before initialization reads or creates a target."""
    try:
        target = project_target(root, path.relative_to(root).as_posix(), control=control)
    except ValueError as exc:
        msg = f"unsafe initialization target: {exc}"
        raise ConfigError(msg) from exc
    for parent in target.parents:
        if parent == root:
            break
        if parent.exists() and not parent.is_dir():
            msg = f"initialization target {path.relative_to(root).as_posix()!r} has a non-directory parent"
            raise ConfigError(msg)
    return target


def _shim_target(root: Path, rel: str) -> tuple[Path, str]:
    path = root / rel
    if not path.is_relative_to(root) or path.suffix != ".py":
        msg = f"--runtime-shim {rel!r} must be a .py file inside the project"
        raise ConfigError(msg)
    try:
        path = _init_target(root, path)
    except ConfigError as exc:
        msg = f"--runtime-shim {rel!r} must be a .py file inside the project ({exc})"
        raise ConfigError(msg) from exc
    path = path.resolve()
    rel = path.relative_to(root).as_posix()
    module = shim_module_name(rel)
    if not all(part.isidentifier() for part in module.split(".")):
        msg = f"--runtime-shim {rel!r} isn't importable as a module ({module!r})"
        raise ConfigError(msg)
    if path.exists() and path.read_text(encoding="utf-8") != RUNTIME_SHIM:
        msg = f"{rel} already exists; remove it or choose another path for the shim"
        raise ConfigError(msg)
    return path, module


def _write_shim(root: Path, rel: str, result: InitResult) -> str:
    path, module = _shim_target(root, rel)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(path, RUNTIME_SHIM.encode())
        rel = path.relative_to(root).as_posix()
        result.actions.append(f"wrote runtime shim {rel} (module {module})")
    return module


def init_project(start: Path | None = None, *, runtime_shim: str | None = None) -> InitResult:
    """Create configuration and an empty registry. Safe to run repeatedly.

    ``runtime_shim`` writes an inert ``todo``/``verifies`` module at that project-relative
    path, for projects that won't depend on ``byteplan-runtime``, and registers it in
    ``runtime_modules``.
    """
    root = find_project_root(start or Path.cwd())
    result = InitResult(root)
    pyproject_path = _init_target(root, root / PYPROJECT)
    pyproject = read_pyproject(root)
    registry_path = _init_target(root, load_config(root).registry_path)
    try:
        control_directory(root, STATE_DIR)
    except ValueError as exc:
        msg = f"unsafe initialization state directory: {exc}"
        raise ConfigError(msg) from exc
    gitignore = _init_target(root, root / STATE_DIR / ".gitignore", control=True)
    targets = [pyproject_path, registry_path, gitignore]
    if runtime_shim:
        targets.append(_shim_target(root, runtime_shim)[0])
    resolved = [path.resolve() for path in targets]
    for path in resolved:
        if any(other != path and other in path.parents for other in resolved):
            msg = "initialization targets overlap as files and directories"
            raise ConfigError(msg)
    if registry_path.exists():
        load_registry(registry_path)  # reject incompatible data before writing a shim or config
    shim = _write_shim(root, runtime_shim, result) if runtime_shim else None

    additions: list[str] = []
    if "byteplan" not in pyproject.get("tool", {}):
        block = _CONFIG_BLOCK
        if shim:
            block += f'\n[tool.byteplan.annotations]\nruntime_modules = ["byteplan_runtime", "{shim}"]\n'
        additions.append(block)
        result.actions.append(f"added [tool.byteplan] to {PYPROJECT}")
    elif shim:
        configured = pyproject["tool"]["byteplan"].get("annotations", {}).get("runtime_modules", ["byteplan_runtime"])
        if shim not in configured:
            result.warnings.append(
                f'add "{shim}" to [tool.byteplan.annotations] runtime_modules in {PYPROJECT} '
                "so BytePlan recognizes the shim's decorators"
            )
    if pyproject.get("build-system", {}).get("build-backend") == "hatchling.build":
        sdist = pyproject.get("tool", {}).get("hatch", {}).get("build", {}).get("targets", {}).get("sdist")
        if sdist is None:
            additions.append(_SDIST_BLOCK)
            result.actions.append(f"excluded .byteplan from Hatch sdists in {PYPROJECT}")
        elif _sdist_ships(sdist, pyproject.get("tool", {}).get("byteplan", {}).get("registry", DEFAULT_REGISTRY)):
            result.warnings.append(
                f'add ".byteplan" to [tool.hatch.build.targets.sdist] exclude in {PYPROJECT} '
                "so the registry is not shipped in source distributions"
            )
    if additions:
        _append_to_pyproject(pyproject_path, additions)

    config = load_config(root)
    registry_path = _init_target(root, config.registry_path)
    if registry_path.exists():
        load_registry(registry_path)  # validate; raises on corruption
    else:
        atomic_write_bytes(registry_path, registry_io.dumps(Registry()).encode())
        result.actions.append(f"created {registry_path.relative_to(root).as_posix()}")
    gitignore = _init_target(root, gitignore, control=True)
    if not gitignore.exists():
        atomic_write_bytes(gitignore, BYTEPLAN_GITIGNORE.encode())
        result.actions.append(f"created {gitignore.relative_to(root).as_posix()}")
    return result


def _sdist_ships(sdist: dict[str, Any], registry: str) -> bool:
    """Whether a Hatch sdist with this target config would include the registry file.

    Follows Hatch's selection rules: ``only-include`` (paths) restricts to those paths,
    ``include`` (gitignore-style patterns) restricts to matches, and ``exclude`` removes
    matches. The build hook re-checks with Hatchling's own ``include_path`` at build time.
    """
    rel = registry.removeprefix("./")
    only = sdist.get("only-include")
    if only and not any(rel == p.strip("/") or rel.startswith(p.strip("/") + "/") for p in only):
        return False
    include = sdist.get("include")
    if include and not pathspec.PathSpec.from_lines("gitignore", include).match_file(rel):
        return False
    exclude = sdist.get("exclude")
    return not (exclude and pathspec.PathSpec.from_lines("gitignore", exclude).match_file(rel))


def _append_to_pyproject(path: Path, blocks: Sequence[str]) -> None:
    source = decode_source(PYPROJECT, path.read_bytes())
    nl = source.newline
    text = source.text
    if text and not text.endswith(("\n", "\r")):
        text += nl
    for block in blocks:
        text += nl + block.replace("\n", nl)
    try:
        tomllib.loads(text)  # never write a pyproject we can't read back
    except tomllib.TOMLDecodeError as exc:
        msg = f"cannot add BytePlan settings to {PYPROJECT} automatically ({exc}); add them by hand"
        raise ConfigError(msg) from exc
    atomic_write_bytes(path, text.encode(source.encoding))
