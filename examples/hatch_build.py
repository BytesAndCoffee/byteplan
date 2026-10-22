# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Minimal reference integration as a Hatch *custom* build hook.

Prefer the installed plugin (``[tool.hatch.build.hooks.byteplan]``). Use this
file only if you'd rather keep the integration in your repository:

.. code-block:: toml

    [build-system]
    requires = ["hatchling", "byteplan"]
    build-backend = "hatchling.build"

    [tool.hatch.build.hooks.custom]
    path = "hatch_build.py"

It runs the same read-only ``byteplan check`` and fails the build on findings
that fail your ``[tool.byteplan.check]`` policy. It never writes source.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

from byteplan.api import Project
from byteplan.config import load_config


class CustomBuildHook(BuildHookInterface):  # type: ignore[type-arg]
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:  # noqa: ARG002
        project = Project(load_config(Path(self.root)))
        if not project.config.registry_path.exists():
            return  # e.g. building a wheel from an unpacked sdist
        report = project.check()
        for diagnostic in report.diagnostics:
            self.app.display_warning(diagnostic.format_text())
        if project.exit_code(report.diagnostics):
            self.app.abort("byteplan: findings fail the configured check policy")
