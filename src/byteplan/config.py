# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""``[tool.byteplan]`` configuration and project-root resolution."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from typing import TYPE_CHECKING, Any, TypeVar

from byteplan.errors import ConfigError

if TYPE_CHECKING:
    from pathlib import Path

PYPROJECT = "pyproject.toml"
DEFAULT_REGISTRY = ".byteplan/tasks.json"
DEFAULT_INCLUDE = ("**/*.py",)
DEFAULT_EXCLUDE = (
    "**/.venv/**",
    "**/venv/**",
    "**/__pycache__/**",
    "**/build/**",
    "**/dist/**",
    "**/.tox/**",
    "**/.nox/**",
    "**/node_modules/**",
    "**/*.pyi",
)
MISSING_POLICIES = ("warn", "ignore")

_T = TypeVar("_T")


@dataclass(frozen=True)
class DetectConfig:
    todo_tags: tuple[str, ...] = ("TODO", "FIXME", "HACK", "XXX")
    pass_stubs: bool = True
    ellipsis_stubs: bool = True
    not_implemented_stubs: bool = True
    empty_classes: bool = True
    placeholder_assignments: bool = False


@dataclass(frozen=True)
class AnnotationsConfig:
    # Modules whose `todo`/`verifies` BytePlan recognizes (a project shim can be added).
    runtime_modules: tuple[str, ...] = ("byteplan_runtime",)


@dataclass(frozen=True)
class GitConfig:
    # After `scan --staged --apply` reconciles a commit: "commit" lets it proceed,
    # "stop" exits 1 so the developer reviews first.
    on_reconcile: str = "commit"


@dataclass(frozen=True)
class CheckConfig:
    fail_on_duplicate_ids: bool = True
    fail_on_missing: bool = False
    fail_on_stale_annotations: bool = False
    # Apply the snapshot consistency rules (as `check --staged` / `--commit` always do)
    # to the plain working-tree `check` too.
    require_reconciled: bool = False
    fail_on_position_drift: bool = False


@dataclass(frozen=True)
class Config:
    root: Path
    registry: str = DEFAULT_REGISTRY
    include: tuple[str, ...] = DEFAULT_INCLUDE
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE
    respect_gitignore: bool = True
    auto_annotate: bool = True
    missing_policy: str = "warn"
    detect: DetectConfig = field(default_factory=DetectConfig)
    check: CheckConfig = field(default_factory=CheckConfig)
    annotations: AnnotationsConfig = field(default_factory=AnnotationsConfig)
    git: GitConfig = field(default_factory=GitConfig)

    @property
    def registry_path(self) -> Path:
        return self.root / self.registry


def find_project_root(start: Path) -> Path:
    """Return the nearest directory at or above ``start`` containing ``pyproject.toml``."""
    start = start.resolve()
    for candidate in (start, *start.parents):
        if (candidate / PYPROJECT).is_file():
            return candidate
    msg = f"no {PYPROJECT} found in {start} or any parent directory"
    raise ConfigError(msg)


def read_pyproject(root: Path) -> dict[str, Any]:
    path = root / PYPROJECT
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except OSError as exc:
        msg = f"cannot read {path}: {exc.strerror}"
        raise ConfigError(msg) from exc
    except tomllib.TOMLDecodeError as exc:
        msg = f"invalid TOML in {path}: {exc}"
        raise ConfigError(msg) from exc


def load_config(root: Path) -> Config:
    root = root.resolve()
    table = read_pyproject(root).get("tool", {}).get("byteplan", {})
    return parse_config(root, table)


def parse_pyproject_text(text: str, label: str) -> dict[str, Any]:
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        msg = f"invalid TOML in {label}: {exc}"
        raise ConfigError(msg) from exc


def config_from_text(root: Path, text: str, label: str) -> Config:
    """Configuration from a ``pyproject.toml`` that isn't (necessarily) on disk, e.g. a staged one."""
    table = parse_pyproject_text(text, label).get("tool", {}).get("byteplan", {})
    return parse_config(root.resolve(), table)


def parse_config(root: Path, table: Any) -> Config:
    if not isinstance(table, dict):
        msg = "[tool.byteplan] must be a table"
        raise ConfigError(msg)
    table = dict(table)
    detect = _parse_section(DetectConfig, table.pop("detect", {}), "tool.byteplan.detect")
    check = _parse_section(CheckConfig, table.pop("check", {}), "tool.byteplan.check")
    annotations = _parse_section(AnnotationsConfig, table.pop("annotations", {}), "tool.byteplan.annotations")
    git = _parse_section(GitConfig, table.pop("git", {}), "tool.byteplan.git")
    skip = frozenset({"root", "detect", "check", "annotations", "git"})
    values = _parse_values(Config, table, "tool.byteplan", skip=skip)
    config = Config(root=root, detect=detect, check=check, annotations=annotations, git=git, **values)
    _validate(config)
    return config


def _parse_section(cls: type[_T], table: Any, name: str) -> _T:
    if not isinstance(table, dict):
        msg = f"[{name}] must be a table"
        raise ConfigError(msg)
    return cls(**_parse_values(cls, table, name))


def _parse_values(
    cls: type[Any], table: dict[str, Any], name: str, skip: frozenset[str] = frozenset()
) -> dict[str, Any]:
    # Every configurable field has a plain class-level default, which also gives its type.
    known = {f.name: f for f in fields(cls) if f.name not in skip}
    values: dict[str, Any] = {}
    for key, value in table.items():
        attr = key.replace("-", "_")
        if attr not in known:
            msg = f"unknown key {key!r} in [{name}]"
            raise ConfigError(msg)
        values[attr] = _coerce(value, getattr(cls, attr), f"{name}.{key}")
    return values


def _coerce(value: Any, default: Any, name: str) -> Any:
    if isinstance(default, bool):
        if not isinstance(value, bool):
            msg = f"{name} must be true or false"
            raise ConfigError(msg)
        return value
    if isinstance(default, str):
        if not isinstance(value, str):
            msg = f"{name} must be a string"
            raise ConfigError(msg)
        return value
    if isinstance(default, tuple):
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            msg = f"{name} must be a list of strings"
            raise ConfigError(msg)
        return tuple(value)
    return value  # no cov


ON_RECONCILE = ("commit", "stop")


def _validate(config: Config) -> None:
    if config.git.on_reconcile not in ON_RECONCILE:
        msg = f"tool.byteplan.git.on_reconcile must be one of {', '.join(ON_RECONCILE)}"
        raise ConfigError(msg)
    # TODO[a6b2]: Support detect.placeholder_assignments
    #   Module-level `name = ...` / `= NotImplemented` stubs need a declaration model for
    #   plain assignments (position, attachment, annotation slot). Until then the option
    #   is rejected rather than silently ignored.
    if config.detect.placeholder_assignments:
        msg = "tool.byteplan.detect.placeholder_assignments is not supported yet; remove it or set it to false"
        raise ConfigError(msg)
    for module in config.annotations.runtime_modules:
        if not all(part.isidentifier() for part in module.split(".")):
            msg = f"tool.byteplan.annotations.runtime_modules entry {module!r} is not a module name"
            raise ConfigError(msg)
    if config.missing_policy not in MISSING_POLICIES:
        msg = f"tool.byteplan.missing_policy must be one of {', '.join(MISSING_POLICIES)}"
        raise ConfigError(msg)
    if not config.detect.todo_tags:
        msg = "tool.byteplan.detect.todo_tags must not be empty"
        raise ConfigError(msg)
    for tag in config.detect.todo_tags:
        if not tag.isidentifier():
            msg = f"tool.byteplan.detect.todo_tags entry {tag!r} must be a word"
            raise ConfigError(msg)
    registry = config.registry_path.resolve()
    if not registry.is_relative_to(config.root):
        msg = f"tool.byteplan.registry {config.registry!r} resolves outside the project root"
        raise ConfigError(msg)
    if registry.suffix != ".json":
        msg = "tool.byteplan.registry must be a .json file"
        raise ConfigError(msg)
