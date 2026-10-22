# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Hatchling build hook: ``[tool.hatch.build.hooks.byteplan]``.

Read-only by default: a build runs ``byteplan check`` and reports findings.
Source annotation (``byteplan scan``) happens only when explicitly enabled:

.. code-block:: toml

    [build-system]
    requires = ["hatchling", "byteplan"]
    build-backend = "hatchling.build"

    [tool.hatch.build.hooks.byteplan]
    scan = true            # run at all (false disables the hook's work)
    write_source = false   # false | true | "editable" (only `pip install -e` / Hatch dev envs)
    fail_build = false     # turn check failures into a build failure
    allow_in_ci = false    # with write_source, still refuse to write when $CI is set

Writes are refused in CI unless ``allow_in_ci``, and skipped when there's no
registry (for example when building a wheel from an unpacked sdist). The hook
runs once per target; a ``hatch build`` that makes an sdist and a wheel runs it
twice, and the second run is a no-op because scans are idempotent. Hook edits
happen in ``initialize``, before Hatchling collects files, so annotated source
is what gets packaged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from hatchling.plugin import hookimpl

from byteplan.api import Project
from byteplan.config import load_config
from byteplan.diagnostics import EXIT_OK, Severity
from byteplan.errors import ByteplanError

if TYPE_CHECKING:
    from collections.abc import Mapping

    from byteplan.diagnostics import Diagnostic

PLUGIN_NAME = "byteplan"
# Keys Hatchling itself interprets for every build hook.
_HATCH_KEYS = frozenset(
    {"dependencies", "enable-by-default", "require-runtime-dependencies", "require-runtime-features"}
)
_KEYS = frozenset({"scan", "write_source", "fail_build", "allow_in_ci"})


class HookConfigError(ValueError):
    pass


@dataclass(frozen=True)
class HookSettings:
    scan: bool = True
    write_source: bool | str = False
    fail_build: bool = False
    allow_in_ci: bool = False

    @classmethod
    def parse(cls, config: Mapping[str, Any]) -> HookSettings:
        unknown = sorted(set(config) - _KEYS - _HATCH_KEYS)
        if unknown:
            msg = f"unknown option(s) in [tool.hatch.build.hooks.byteplan]: {', '.join(unknown)}"
            raise HookConfigError(msg)
        for key in ("scan", "fail_build", "allow_in_ci"):
            if key in config and not isinstance(config[key], bool):
                msg = f"[tool.hatch.build.hooks.byteplan] {key} must be true or false"
                raise HookConfigError(msg)
        write_source = config.get("write_source", False)
        # Identity checks: 1 == True, so `in (False, True, ...)` would accept integers.
        if not (write_source is True or write_source is False or write_source == "editable"):
            msg = '[tool.hatch.build.hooks.byteplan] write_source must be false, true or "editable"'
            raise HookConfigError(msg)
        return cls(
            scan=config.get("scan", True),
            write_source=write_source,
            fail_build=config.get("fail_build", False),
            allow_in_ci=config.get("allow_in_ci", False),
        )


def in_ci(environ: Mapping[str, str]) -> bool:
    return environ.get("CI", "").strip().lower() not in {"", "0", "false", "no"}


def write_decision(settings: HookSettings, version: str, environ: Mapping[str, str]) -> tuple[bool, str | None]:
    """Whether this build may write source, and why not if it may not (None = not requested)."""
    if settings.write_source is False:
        return False, None
    if settings.write_source == "editable" and version != "editable":
        return False, None
    if in_ci(environ) and not settings.allow_in_ci:
        return False, "CI is set; not writing source (set allow_in_ci = true to override)"
    return True, None


class BytePlanBuildHook(BuildHookInterface):  # type: ignore[type-arg]
    PLUGIN_NAME = PLUGIN_NAME

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:  # noqa: ARG002
        try:
            settings = HookSettings.parse(self.config)
        except HookConfigError as exc:
            self.app.abort(f"byteplan: {exc}")
            return
        if not settings.scan:
            return

        root = Path(self.root)
        try:
            project = Project(load_config(root))
        except ByteplanError as exc:
            self._fail_or_warn(settings, f"byteplan: {exc}")
            return
        if not project.config.registry_path.exists():
            self.app.display_info("byteplan: no registry here (e.g. building from an sdist); skipping")
            return
        self._check_packaging(project)

        write, reason = write_decision(settings, version, os.environ)
        if reason:
            self.app.display_warning(f"byteplan: {reason}")
        try:
            report = project.scan(dry_run=not write)
        except ByteplanError as exc:
            self._fail_or_warn(settings, f"byteplan: {exc}")
            return

        mode = "scan" if write else "check"
        written = f", wrote {len(report.written)} file(s)" if report.written else ""
        self.app.display_info(
            f"byteplan {mode} ({self.target_name}): {report.files_scanned} files, {report.tracked} tasks{written}"
        )
        self._show(report.diagnostics)
        if project.exit_code(report.diagnostics) != EXIT_OK:
            self._fail_or_warn(settings, "byteplan: findings fail the configured check policy")

    def _check_packaging(self, project: Project) -> None:
        registry = project.registry_rel
        if self.target_name == "sdist" and self.build_config.include_path(registry, is_package=False):
            self.app.display_warning(
                f"byteplan: {registry} would be included in the sdist (registry_packaged); "
                'add ".byteplan" to [tool.hatch.build.targets.sdist] exclude'
            )

    def _show(self, diagnostics: tuple[Diagnostic, ...]) -> None:
        for diagnostic in diagnostics:
            text = diagnostic.format_text()
            if diagnostic.severity is Severity.INFO:
                self.app.display_info(text)
            else:
                self.app.display_warning(text)

    def _fail_or_warn(self, settings: HookSettings, message: str) -> None:
        if settings.fail_build:
            self.app.abort(message)
        else:
            self.app.display_warning(message)


@hookimpl
def hatch_register_build_hook() -> type[BuildHookInterface]:  # type: ignore[type-arg]
    return BytePlanBuildHook
