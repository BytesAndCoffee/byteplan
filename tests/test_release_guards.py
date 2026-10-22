# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Phase 8 (part 2): `release --smoke-test`, the Hatch `require_stripped` guard,
`runtime_dependency_in_release` and `unfinished_scaffold_in_sdist`.

The plan's release tests: `--smoke-test` catches a stripped wheel that fails to import and
`byteplan-runtime` pulled in as a dependency; a failure leaves the tree exactly as before the
release; without the flag nothing is built; `require_stripped` fails an unstripped wheel
build; a scaffold placeholder in the sdist is reported and stays failing after stripping.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from typing import TYPE_CHECKING, Any

import pytest

from byteplan.cli import EXIT_ERROR, EXIT_OK
from byteplan.smoke import top_level_modules
from tests.test_hatch_hook import COVERAGE_FILE, build

if TYPE_CHECKING:
    from pathlib import Path

    from tests.conftest import ProjectFactory, RunCli

pytest.importorskip("build")
pytest.importorskip("hatchling")

NO_ISOLATION = json.dumps([sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", "{out}"])

PYPROJECT = f"""\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "demo"
version = "1.0"
dependencies = [{{deps}}]

[tool.hatch.build.targets.wheel]
packages = ["src/demo"]

[tool.byteplan.release]
smoke_build = {NO_ISOLATION.replace("{", "{{").replace("}", "}}")}
{{release}}
"""

MODULE = """\
from byteplan_runtime import todo


@todo("Make it fast", id="a83f")
def run():
    return 1
"""


def make(project: ProjectFactory, run_cli: RunCli, *, deps: str = "", release: str = "", module: str = MODULE) -> None:
    project.write("pyproject.toml", PYPROJECT.format(deps=deps, release=release), dedent=False)
    project.write("src/demo/__init__.py", module, dedent=False)
    project.init()
    if "a83f" in module:
        assert run_cli("repair", "--import", "a83f", "--project", project.root).code == EXIT_OK
    assert run_cli("scan", "--project", project.root).code == EXIT_OK


def release(project: ProjectFactory, run_cli: RunCli, *extra: str) -> Any:
    env = {"COVERAGE_FILE": COVERAGE_FILE}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        return run_cli("release", "--allow-dirty", "--project", project.root, *extra)
    finally:
        for key, value in old.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def registry(project: ProjectFactory) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((project.root / ".byteplan/tasks.json").read_text())
    return data


# --smoke-test --------------------------------------------------------------------------------------


def test_smoke_test_passes_for_a_clean_strip(project: ProjectFactory, run_cli: RunCli) -> None:
    make(project, run_cli)
    result = release(project, run_cli, "--smoke-test", "--offline")
    assert result.code == EXIT_OK, result.err
    assert "smoke test passed: the wheel imports (demo) without byteplan_runtime" in result.out
    assert registry(project)["release"]["smoke_test"] == "passed"
    assert not (project.root / "dist").exists()  # built in a temporary directory only


def test_without_the_flag_nothing_is_built(project: ProjectFactory, run_cli: RunCli) -> None:
    make(project, run_cli)
    pyproject = project.root / "pyproject.toml"
    text = pyproject.read_text()
    pyproject.write_text(text[: text.index("smoke_build")] + 'smoke_build = ["no-such-builder-xyz"]\n')
    assert release(project, run_cli).code == EXIT_OK  # a builder that can't run is never invoked
    assert registry(project)["release"]["smoke_test"] == "not_run"


def test_import_failure_restores_the_tree(project: ProjectFactory, run_cli: RunCli) -> None:
    """The runtime is used dynamically (a string), so only importing the wheel finds it."""
    module = MODULE.replace(
        "from byteplan_runtime import todo\n",
        'import importlib\n\nfrom byteplan_runtime import todo\n\nimportlib.import_module("byteplan_runtime")\n',
    )
    make(project, run_cli, module=module)
    before = project.snapshot()
    result = release(project, run_cli, "--smoke-test", "--offline")
    assert result.code == EXIT_ERROR
    assert "smoke_test_failed" in result.err
    assert "the import step failed; the strip was restored" in result.err
    assert "ModuleNotFoundError" in result.err
    after = project.snapshot()
    assert {k: v for k, v in after.items() if not k.startswith(".byteplan/")} == {
        k: v for k, v in before.items() if not k.startswith(".byteplan/")
    }
    assert "release" not in registry(project)  # back to unstripped


def test_runtime_pulled_in_as_a_dependency_fails(project: ProjectFactory, run_cli: RunCli, tmp_path: Path) -> None:
    """A dependency that provides byteplan_runtime defeats the strip; the smoke test sees it."""
    provider = tmp_path / "provider"
    (provider / "byteplan_runtime").mkdir(parents=True)
    (provider / "byteplan_runtime/__init__.py").write_text("def todo(*a, **k):\n    return lambda f: f\n")
    (provider / "pyproject.toml").write_text(
        '[build-system]\nrequires = ["hatchling"]\nbuild-backend = "hatchling.build"\n\n'
        '[project]\nname = "runtime-provider"\nversion = "1.0"\n\n'
        '[tool.hatch.build.targets.wheel]\npackages = ["byteplan_runtime"]\n'
    )
    links = tmp_path / "links"
    built = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", str(links), str(provider)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    make(project, run_cli, deps='"runtime-provider"', release=f"find_links = [{json.dumps(str(links))}]")
    result = release(project, run_cli, "--smoke-test", "--offline")
    assert result.code == EXIT_ERROR
    assert "byteplan_runtime is importable from the installed wheel" in result.err


def test_top_level_modules_from_record(tmp_path: Path) -> None:
    wheel = tmp_path / "demo-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "demo-1.0.dist-info/RECORD",
            "demo/__init__.py,,\ndemo/sub/x.py,,\nsingle.py,,\ndemo-1.0.dist-info/METADATA,,\n../../bin/tool,,\n",
        )
    assert top_level_modules(wheel) == ["demo", "single"]


# Release warnings ----------------------------------------------------------------------------------


def test_runtime_dependency_in_release(project: ProjectFactory, run_cli: RunCli) -> None:
    make(project, run_cli, deps='"byteplan-runtime>=0.1"')
    result = release(project, run_cli)
    assert result.code == EXIT_OK
    assert "RUNTIME_DEPENDENCY_IN_RELEASE" in result.err
    assert "RUNTIME_DEPENDENCY_IN_RELEASE" in run_cli("check", "--project", project.root).err  # while stripped


def test_unfinished_scaffold_in_sdist(project: ProjectFactory, run_cli: RunCli) -> None:
    make(project, run_cli)
    project.write(
        "tests/test_demo.py",
        'import pytest\n\n\ndef test_run():\n    pytest.fail("BytePlan a83f: acceptance test not implemented")\n',
    )
    result = release(project, run_cli)
    assert result.code == EXIT_OK
    assert "UNFINISHED_SCAFFOLD_IN_SDIST" in result.err
    assert "tests/test_demo.py::test_run is an unfinished scaffold" in result.err
    # Stripping never turns it into a passing test.
    assert 'pytest.fail("BytePlan a83f' in (project.root / "tests/test_demo.py").read_text()
    assert "UNFINISHED_SCAFFOLD_IN_SDIST" in run_cli("check", "--project", project.root).err


def test_no_warnings_without_reasons(project: ProjectFactory, run_cli: RunCli) -> None:
    make(project, run_cli)
    result = release(project, run_cli)
    assert "RUNTIME_DEPENDENCY_IN_RELEASE" not in result.err
    assert "UNFINISHED_SCAFFOLD_IN_SDIST" not in result.err


# Hatch require_stripped ------------------------------------------------------------------------------


HOOKED = """\
[build-system]
requires = ["hatchling", "byteplan"]
build-backend = "hatchling.build"

[project]
name = "demo"
version = "1.0"

[tool.hatch.build.targets.wheel]
packages = ["src/demo"]

[tool.hatch.build.hooks.byteplan]
require_stripped = true
"""


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_require_stripped_fails_an_unstripped_build(project: ProjectFactory, run_cli: RunCli, tmp_path: Path) -> None:
    project.write("pyproject.toml", HOOKED, dedent=False)
    project.write("src/demo/__init__.py", MODULE, dedent=False)
    project.init()
    assert run_cli("repair", "--import", "a83f", "--project", project.root).code == EXIT_OK
    refused = build(project.root, tmp_path / "dist", "wheel")
    assert refused.returncode != 0
    assert "require_stripped: 1 file(s) still carry @todo/@verifies (src/demo/__init__.py)" in refused.output

    assert run_cli("release", "--allow-dirty", "--project", project.root).code == EXIT_OK
    allowed = build(project.root, tmp_path / "dist2", "wheel")
    assert allowed.returncode == 0, allowed.output


# Codex review of #34 -----------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_require_stripped_checks_source_despite_a_release_record(
    project: ProjectFactory, run_cli: RunCli, tmp_path: Path
) -> None:
    """A hotfix restoring decorators after `release` must not ship because the record says stripped."""
    project.write("pyproject.toml", HOOKED, dedent=False)
    project.write("src/demo/__init__.py", MODULE, dedent=False)
    project.init()
    assert run_cli("repair", "--import", "a83f", "--project", project.root).code == EXIT_OK
    assert run_cli("release", "--allow-dirty", "--project", project.root).code == EXIT_OK
    project.write("src/demo/__init__.py", MODULE, dedent=False)  # the decorator is back, the record unchanged
    refused = build(project.root, tmp_path / "dist", "wheel")
    assert refused.returncode != 0
    assert "require_stripped" in refused.output


def test_require_stripped_ignores_pytest_markers(project: ProjectFactory, tmp_path: Path) -> None:
    """@pytest.mark.byteplan stays through a release and needs no runtime: not a reason to fail."""
    project.write("pyproject.toml", HOOKED + "\n[tool.byteplan.tests]\npytest_marker = true\n", dedent=False)
    project.write("src/demo/__init__.py", "def run():\n    return 1\n", dedent=False)
    project.write(
        "tests/test_demo.py", 'import pytest\n\n\n@pytest.mark.byteplan("a83f")\ndef test_run():\n    assert True\n'
    )
    project.init()
    allowed = build(project.root, tmp_path / "dist", "wheel")
    assert allowed.returncode == 0, allowed.output
