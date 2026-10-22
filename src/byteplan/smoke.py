# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""``byteplan release --smoke-test``: does the stripped tree make a wheel that works without
BytePlan?

The static rule (no runtime-module references left) is necessary but not sufficient. With the
flag, release also:

1. builds a wheel from the stripped tree into a temporary directory (nothing goes to ``dist/``),
   with ``[tool.byteplan.release] smoke_build`` or ``python -m build --wheel``;
2. installs it, with its dependencies resolved normally (``--offline``: no index, only
   ``find_links``), into a private target directory;
3. in a Python started with ``-I -S`` (no site-packages, no user site, no environment), so only
   the standard library and that target are visible, asserts that ``byteplan_runtime`` is
   *not* importable (a dependency that pulls it in fails here) and imports each top-level
   module the wheel installs (or ``smoke_imports``).

Building and importing run project code, so this never happens without the flag.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

    from byteplan.config import ReleaseConfig

RUNTIME_DISTRIBUTION_MODULE = "byteplan_runtime"


@dataclass(frozen=True)
class SmokeResult:
    passed: bool
    stage: str  # build | install | import | passed
    detail: str = ""
    imports: tuple[str, ...] = field(default_factory=tuple)


def _run(argv: Sequence[str], cwd: Path, timeout: int) -> tuple[bool, str]:
    try:
        done = subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout} s: {' '.join(argv)}"
    except OSError as exc:
        return False, f"can't run {argv[0]!r}: {exc.strerror or exc}"
    output = (done.stdout + done.stderr)[-3000:]
    return done.returncode == 0, output


def top_level_modules(wheel: Path) -> list[str]:
    """Importable top-level names in a wheel, from its RECORD."""
    names: set[str] = set()
    with zipfile.ZipFile(wheel) as archive:
        record = next((n for n in archive.namelist() if n.endswith(".dist-info/RECORD")), None)
        entries = archive.read(record).decode().splitlines() if record else archive.namelist()
    for line in entries:
        path = line.split(",", 1)[0]
        first = path.split("/", 1)[0]
        if not first or first.endswith((".dist-info", ".data")) or first in {"__pycache__", ".."}:
            continue
        if "/" in path:
            names.add(first)
        elif first.endswith(".py"):
            names.add(first.removesuffix(".py"))
        elif first.endswith((".so", ".pyd")):  # extension module: name.<abi tag>.so, or name.so
            names.add(first.split(".", 1)[0])
    return sorted(n for n in names if n.isidentifier())


def run_smoke(root: Path, config: ReleaseConfig, *, offline: bool) -> SmokeResult:
    with tempfile.TemporaryDirectory(prefix="byteplan-smoke-") as scratch:
        tmp = Path(scratch)
        out, target = tmp / "dist", tmp / "site"
        build = list(config.smoke_build) or [sys.executable, "-m", "build", "--wheel", "--outdir", "{out}"]
        ok, output = _run([arg.replace("{out}", str(out)) for arg in build], root, config.smoke_timeout)
        wheels = sorted(out.glob("*.whl")) if out.exists() else []
        if not ok or len(wheels) != 1:
            return SmokeResult(False, "build", output if not ok else f"expected one wheel, found {len(wheels)}")

        install = [sys.executable, "-m", "pip", "install", "--quiet", "--target", str(target), str(wheels[0])]
        if offline:
            links = (link if "://" in link else str(root / link) for link in config.find_links)
            install += ["--no-index", *(arg for link in links for arg in ("--find-links", link))]
        ok, output = _run(install, tmp, config.smoke_timeout)
        if not ok:
            return SmokeResult(False, "install", output)

        modules = list(config.smoke_imports) or top_level_modules(wheels[0])
        script = (
            "import importlib, importlib.util, sys\n"
            f"sys.path.insert(0, {str(target)!r})\n"
            f"if importlib.util.find_spec({RUNTIME_DISTRIBUTION_MODULE!r}) is not None:\n"
            f"    sys.exit('{RUNTIME_DISTRIBUTION_MODULE} is importable from the installed wheel"
            " (is byteplan-runtime a dependency?)')\n"
            f"for name in {modules!r}:\n"
            "    importlib.import_module(name)\n"
        )
        ok, output = _run([sys.executable, "-I", "-S", "-c", script], tmp, config.smoke_timeout)
        if not ok:
            return SmokeResult(False, "import", output, tuple(modules))
        return SmokeResult(True, "passed", imports=tuple(modules))
