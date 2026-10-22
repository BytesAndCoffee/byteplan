# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Hatch build hook (spec 18; Addendum A 16, Hatch part).

Most tests run real PEP 517 builds with ``python -m build --no-isolation`` in this
environment, where byteplan is installed and its ``hatch`` entry point is
registered, exactly as it would be in an isolated build that requires it.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from byteplan.hatch_hook import HookConfigError, HookSettings, in_ci, write_decision

if TYPE_CHECKING:
    from tests.conftest import ProjectFactory

pytest.importorskip("build")

PYPROJECT = """\
[build-system]
requires = ["hatchling", "byteplan"]
build-backend = "hatchling.build"

[project]
name = "demo"
version = "1.0"

[tool.hatch.build.targets.wheel]
packages = ["src/demo"]

[tool.hatch.build.hooks.byteplan]
{hook}
"""


# Pure decision logic --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("write_source", "version", "env", "expected"),
    [
        (False, "standard", {}, False),
        (True, "standard", {}, True),
        (True, "editable", {}, True),
        ("editable", "standard", {}, False),
        ("editable", "editable", {}, True),
        (True, "standard", {"CI": "true"}, False),
        (True, "standard", {"CI": "1"}, False),
        (True, "standard", {"CI": "false"}, True),
        (True, "standard", {"CI": ""}, True),
    ],
)
def test_write_decision(write_source: bool | str, version: str, env: dict[str, str], expected: bool) -> None:  # noqa: FBT001 - pytest parameters
    write, _ = write_decision(HookSettings(write_source=write_source), version, env)
    assert write is expected


def test_ci_override() -> None:
    settings = HookSettings(write_source=True, allow_in_ci=True)
    assert write_decision(settings, "standard", {"CI": "true"}) == (True, None)
    write, reason = write_decision(HookSettings(write_source=True), "standard", {"CI": "true"})
    assert not write
    assert reason is not None
    assert "allow_in_ci" in reason
    assert in_ci({"CI": "yes"})
    assert not in_ci({"CI": "No"})


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"write": True}, "unknown option"),
        ({"scan": "yes"}, "scan must be true or false"),
        ({"write_source": 1}, "write_source must be"),
        ({"write_source": "always"}, "write_source must be"),
    ],
)
def test_invalid_hook_config(config: dict[str, object], message: str) -> None:
    with pytest.raises(HookConfigError, match=message):
        HookSettings.parse(config)


def test_hatchling_keys_are_accepted() -> None:
    assert HookSettings.parse({"enable-by-default": False, "dependencies": ["x"]}) == HookSettings()


# Real builds -----------------------------------------------------------------------------------


def make_demo(project: ProjectFactory, hook: str = "") -> ProjectFactory:
    project.write("pyproject.toml", PYPROJECT.format(hook=hook), dedent=False)
    project.write("src/demo/__init__.py", "def run():\n    # TODO: make this fast\n    return 1\n")
    project.init()
    return project


class Built:
    """A finished build; ``output`` is stdout and stderr together (the backend's
    messages go to stderr under ``python -m build``)."""

    def __init__(self, process: subprocess.CompletedProcess[str]) -> None:
        self.returncode = process.returncode
        self.output = process.stdout + process.stderr


def build(root: Path, out: Path, *targets: str, env: dict[str, str] | None = None) -> Built:
    environ = {k: v for k, v in os.environ.items() if k != "CI"}
    environ.update(env or {})
    flags = [f"--{target}" for target in targets or ("sdist", "wheel")]
    return Built(
        subprocess.run(
            [sys.executable, "-m", "build", "--no-isolation", *flags, "--outdir", str(out), str(root)],
            capture_output=True,
            text=True,
            env=environ,
            timeout=300,
            check=False,
        )
    )


def wheel_source(out: Path) -> str:
    (wheel,) = out.glob("*.whl")
    with zipfile.ZipFile(wheel) as archive:
        return archive.read("demo/__init__.py").decode()


def sdist_names(out: Path) -> list[str]:
    (sdist,) = out.glob("*.tar.gz")
    with tarfile.open(sdist) as archive:
        return archive.getnames()


def test_default_build_is_read_only(project: ProjectFactory, tmp_path: Path) -> None:
    make_demo(project)
    before = project.snapshot()
    result = build(project.root, tmp_path / "dist")
    assert result.returncode == 0, result.output
    assert "byteplan check (sdist)" in result.output
    assert "byteplan check (wheel)" in result.output
    assert project.snapshot() == before
    assert "# TODO: make this fast" in wheel_source(tmp_path / "dist")


def test_write_source_annotates_before_packaging(project: ProjectFactory, tmp_path: Path) -> None:
    make_demo(project, "write_source = true")
    result = build(project.root, tmp_path / "dist")
    assert result.returncode == 0, result.output
    tasks = json.loads((project.root / ".byteplan/tasks.json").read_text())["tasks"]
    (task_id,) = tasks
    assert f"# TODO[{task_id}]: make this fast" in (project.root / "src/demo/__init__.py").read_text()
    assert f"# TODO[{task_id}]: make this fast" in wheel_source(tmp_path / "dist")
    assert "wrote 2 file(s)" in result.output  # first target writes source + registry...
    assert result.output.count("wrote") == 1  # ...and the second target finds nothing to do


def test_registry_is_not_packaged(project: ProjectFactory, tmp_path: Path) -> None:
    make_demo(project)
    result = build(project.root, tmp_path / "dist")
    assert result.returncode == 0, result.output
    assert not [name for name in sdist_names(tmp_path / "dist") if "/.byteplan/" in name]
    assert "registry_packaged" not in result.output


def test_warns_when_sdist_would_ship_the_registry(project: ProjectFactory, tmp_path: Path) -> None:
    make_demo(project)
    pyproject = project.root / "pyproject.toml"
    pyproject.write_text(pyproject.read_text().replace('exclude = [".byteplan"]', "exclude = []"))
    result = build(project.root, tmp_path / "dist", "sdist")
    assert result.returncode == 0, result.output
    assert "registry_packaged" in result.output


def test_builds_are_reproducible(project: ProjectFactory, tmp_path: Path) -> None:
    make_demo(project, "write_source = true")
    assert build(project.root, tmp_path / "first").returncode == 0  # annotates the source
    assert build(project.root, tmp_path / "second").returncode == 0
    assert build(project.root, tmp_path / "third").returncode == 0
    for pattern in ("*.whl", "*.tar.gz"):
        second = hashlib.sha256(next((tmp_path / "second").glob(pattern)).read_bytes()).hexdigest()
        third = hashlib.sha256(next((tmp_path / "third").glob(pattern)).read_bytes()).hexdigest()
        assert second == third, pattern


def test_ci_refuses_writes(project: ProjectFactory, tmp_path: Path) -> None:
    make_demo(project, "write_source = true")
    before = project.snapshot()
    result = build(project.root, tmp_path / "dist", env={"CI": "true"})
    assert result.returncode == 0, result.output
    assert "CI is set; not writing source" in result.output
    assert project.snapshot() == before


def test_editable_mode_does_not_write_on_release_builds(project: ProjectFactory, tmp_path: Path) -> None:
    make_demo(project, 'write_source = "editable"')
    before = project.snapshot()
    assert build(project.root, tmp_path / "dist").returncode == 0
    assert project.snapshot() == before


def test_fail_build_on_findings(project: ProjectFactory, tmp_path: Path) -> None:
    make_demo(project, "fail_build = true")
    project.write("src/demo/a.py", "# TODO[beef]: one\n")
    project.write("src/demo/b.py", "# TODO[beef]: two\n")
    result = build(project.root, tmp_path / "dist", "wheel")
    assert result.returncode != 0
    assert "fail the configured check policy" in result.output
    assert not list((tmp_path / "dist").glob("*.whl"))


def test_findings_warn_without_fail_build(project: ProjectFactory, tmp_path: Path) -> None:
    make_demo(project)
    project.write("src/demo/a.py", "# TODO[beef]: one\n")
    project.write("src/demo/b.py", "# TODO[beef]: two\n")
    result = build(project.root, tmp_path / "dist", "wheel")
    assert result.returncode == 0, result.output
    assert "DUPLICATE_ID" in result.output


def test_wheel_from_unpacked_sdist_skips_quietly(project: ProjectFactory, tmp_path: Path) -> None:
    make_demo(project, "write_source = true")
    assert build(project.root, tmp_path / "dist", "sdist").returncode == 0
    (sdist,) = (tmp_path / "dist").glob("*.tar.gz")
    with tarfile.open(sdist) as archive:
        # Our own freshly built archive; the data filter only exists from 3.11.4/3.12.
        if hasattr(tarfile, "data_filter"):
            archive.extractall(tmp_path / "unpacked", filter="data")
        else:  # pragma: no cover
            archive.extractall(tmp_path / "unpacked")
    (unpacked,) = (tmp_path / "unpacked").iterdir()
    result = build(unpacked, tmp_path / "wheel", "wheel")
    assert result.returncode == 0, result.output
    assert "no registry here" in result.output


def test_disabled_hook_does_nothing(project: ProjectFactory, tmp_path: Path) -> None:
    make_demo(project, "scan = false")
    result = build(project.root, tmp_path / "dist", "wheel")
    assert result.returncode == 0, result.output
    assert "byteplan check" not in result.output
    assert "byteplan scan" not in result.output


def test_bad_hook_config_fails_the_build(project: ProjectFactory, tmp_path: Path) -> None:
    make_demo(project, "write = true")
    result = build(project.root, tmp_path / "dist", "wheel")
    assert result.returncode != 0
    assert "unknown option(s)" in result.output


@pytest.mark.network
def test_isolated_pep517_build(project: ProjectFactory, tmp_path: Path) -> None:
    """End-user path: `requires = ["hatchling", "byteplan"]` in a fresh isolated build env.

    Uses a local wheelhouse (hatchling from PyPI plus byteplan built from this
    checkout) with the index disabled, so the build can't pick up a published
    byteplan instead of the one under test.
    """
    wheels = tmp_path / "wheels"
    repo = Path(__file__).resolve().parents[1]
    download = [sys.executable, "-m", "pip", "download", "--quiet", "-d", str(wheels), "hatchling", "pathspec"]
    subprocess.run(download, check=True, timeout=300)
    assert build(repo, wheels, "wheel").returncode == 0

    make_demo(project, "write_source = true")
    environ = {k: v for k, v in os.environ.items() if k != "CI"}
    environ.update({"PIP_NO_INDEX": "1", "PIP_FIND_LINKS": str(wheels)})
    result = subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(tmp_path / "dist"), str(project.root)],
        capture_output=True,
        text=True,
        env=environ,
        timeout=600,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "TODO[" in wheel_source(tmp_path / "dist")
