# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
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
    # Don't treat a trivial method as a stub when a project subclass implements it
    # (interface by convention) or it overrides a project base class's method (no-op).
    respect_overrides: bool = True
    # In JSON, track value strings that start with a tag and a colon ("TODO: ...").
    json_string_values: bool = True


@dataclass(frozen=True)
class AnnotationsConfig:
    # comment: unowned stubs get a `# TODO` line (scan). preserve: stubs are only reported.
    # decorator: like preserve for scan; `byteplan sync` may rewrite to `@todo(...)`.
    mode: str = "comment"
    # decorator mode, `sync`: turn a tagged comment directly above a def/class into @todo(...).
    convert_attached_comments: bool = False
    # decorator mode, `sync`: put @todo(...) on unowned stubs.
    auto_decorate_stubs: bool = False
    # `byteplan sync` also removes the source annotations of resolved and dismissed tasks.
    remove_resolved: bool = False
    # Modules whose `todo`/`verifies` BytePlan recognizes (a project shim can be added).
    runtime_modules: tuple[str, ...] = ("byteplan_runtime",)


@dataclass(frozen=True)
class ScaffoldConfig:
    """``[tool.byteplan.tests.scaffold]``: where and how ``byteplan tests scaffold`` writes."""

    directory: str = "tests"
    filename: str = "test_{module}.py"
    # tests/pkg/test_routing.py for src/pkg/routing.py instead of tests/test_routing.py.
    mirror: bool = False
    link_style: str = "verifies"  # verifies | marker | managed
    policy: str = "fail"  # fail | xfail | skip (only fail can never look finished)
    # Async targets get `async def` tests only with a plugin named here: "pytest-asyncio" or "anyio".
    async_tests: str = ""


@dataclass(frozen=True)
class TestsConfig:
    __test__ = False  # not a pytest test class
    # Also link tests marked @pytest.mark.byteplan("abcd") (register the marker in your pytest
    # configuration until `byteplan verify`'s plugin does it).
    pytest_marker: bool = False
    # `byteplan verify`: the pytest command as an argument list ([] = this Python's `-m pytest`),
    # e.g. ["hatch", "test", "--"]; seconds before the run is killed; and what makes results
    # stale: "files" (the task's source and test files changed) or "head" (HEAD moved or dirty).
    runner: tuple[str, ...] = ()
    timeout: int = 300
    stale_on: str = "files"
    scaffold: ScaffoldConfig = field(default_factory=ScaffoldConfig)


@dataclass(frozen=True)
class ArchiveConfig:
    """``[tool.byteplan.archive]``: moving long-closed tasks out of ``tasks.json``."""

    after_days: int = 7  # closed at least this long ago (and no longer annotated in source)
    auto: bool = True  # archive after every writing `scan`


@dataclass(frozen=True)
class ReleaseConfig:
    """``[tool.byteplan.release]``: the opt-in ``release --smoke-test``."""

    # The wheel build, as an argument list; "{out}" is the output directory. [] means
    # `python -m build --wheel --outdir {out}` with this Python.
    smoke_build: tuple[str, ...] = ()
    # Modules to import from the installed wheel ([] = every top-level module in its RECORD).
    smoke_imports: tuple[str, ...] = ()
    smoke_timeout: int = 300
    # Extra package sources for --offline installs (pip --find-links).
    find_links: tuple[str, ...] = ()


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
    # The committed report_file not matching the registry (warning by default: a merge
    # keeps one side's copy until the next commit regenerates it).
    fail_on_stale_report: bool = False


@dataclass(frozen=True)
class Config:
    root: Path
    registry: str = DEFAULT_REGISTRY
    include: tuple[str, ...] = DEFAULT_INCLUDE
    exclude: tuple[str, ...] = DEFAULT_EXCLUDE
    respect_gitignore: bool = True
    auto_annotate: bool = True
    missing_policy: str = "warn"
    # A Markdown view of the registry, regenerated whenever the registry is written (so the
    # commit hook stages it with the registry). Empty: no report file.
    report_file: str = ""
    detect: DetectConfig = field(default_factory=DetectConfig)
    check: CheckConfig = field(default_factory=CheckConfig)
    annotations: AnnotationsConfig = field(default_factory=AnnotationsConfig)
    git: GitConfig = field(default_factory=GitConfig)
    tests: TestsConfig = field(default_factory=TestsConfig)
    release: ReleaseConfig = field(default_factory=ReleaseConfig)
    archive: ArchiveConfig = field(default_factory=ArchiveConfig)

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
    release = _parse_section(ReleaseConfig, table.pop("release", {}), "tool.byteplan.release")
    archive = _parse_section(ArchiveConfig, table.pop("archive", {}), "tool.byteplan.archive")
    tests_table = table.pop("tests", {})
    if not isinstance(tests_table, dict):
        msg = "[tool.byteplan.tests] must be a table"
        raise ConfigError(msg)
    tests_table = dict(tests_table)
    scaffold = _parse_section(ScaffoldConfig, tests_table.pop("scaffold", {}), "tool.byteplan.tests.scaffold")
    tests = TestsConfig(
        **_parse_values(TestsConfig, tests_table, "tool.byteplan.tests", skip=frozenset({"scaffold"})),
        scaffold=scaffold,
    )
    skip = frozenset({"root", "detect", "check", "annotations", "git", "tests", "release", "archive"})
    values = _parse_values(Config, table, "tool.byteplan", skip=skip)
    config = Config(
        root=root,
        detect=detect,
        check=check,
        annotations=annotations,
        git=git,
        tests=tests,
        release=release,
        archive=archive,
        **values,
    )
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
    if isinstance(default, int):
        if not isinstance(value, int) or isinstance(value, bool):
            msg = f"{name} must be an integer"
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
ANNOTATION_MODES = ("comment", "preserve", "decorator")
STALE_ON = ("files", "head")
LINK_STYLES = ("verifies", "marker", "managed")
SCAFFOLD_POLICIES = ("fail", "xfail", "skip")
ASYNC_PLUGINS = ("", "pytest-asyncio", "anyio")


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
    if config.tests.stale_on not in STALE_ON:
        msg = f"tool.byteplan.tests.stale_on must be one of {', '.join(STALE_ON)}"
        raise ConfigError(msg)
    scaffold = config.tests.scaffold
    for name, value, allowed in (
        ("link_style", scaffold.link_style, LINK_STYLES),
        ("policy", scaffold.policy, SCAFFOLD_POLICIES),
        ("async_tests", scaffold.async_tests, ASYNC_PLUGINS),
    ):
        if value not in allowed:
            msg = f"tool.byteplan.tests.scaffold.{name} must be one of {', '.join(repr(a) for a in allowed)}"
            raise ConfigError(msg)
    if "{module}" not in scaffold.filename or not scaffold.filename.endswith(".py"):
        msg = 'tool.byteplan.tests.scaffold.filename must end in .py and contain "{module}"'
        raise ConfigError(msg)
    if config.archive.after_days < 0:
        msg = "tool.byteplan.archive.after_days must not be negative"
        raise ConfigError(msg)
    if config.tests.timeout <= 0:
        msg = "tool.byteplan.tests.timeout must be a positive number of seconds"
        raise ConfigError(msg)
    if config.annotations.mode not in ANNOTATION_MODES:
        msg = f"tool.byteplan.annotations.mode must be one of {', '.join(ANNOTATION_MODES)}"
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
    if config.report_file:
        report = (config.root / config.report_file).resolve()
        if not report.is_relative_to(config.root) or report == config.root:
            msg = f"tool.byteplan.report_file {config.report_file!r} resolves outside the project root"
            raise ConfigError(msg)
        if report.suffix != ".md":
            msg = "tool.byteplan.report_file must be a .md file"
            raise ConfigError(msg)
        if report == registry:
            msg = "tool.byteplan.report_file must differ from the registry"
            raise ConfigError(msg)
