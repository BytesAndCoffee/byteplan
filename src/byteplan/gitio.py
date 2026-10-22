# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Git integration: the registry merge driver and its installation.

Read-only Git calls run with ``--no-optional-locks`` so they never rewrite
``.git/index``. The only writes are the explicit, user-requested ones in
``install_merge_driver`` (a ``.gitattributes`` line and local ``git config``).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from byteplan import registry as registry_io
from byteplan.errors import ByteplanError, ConfigError, RegistryError
from byteplan.merge import MergeResult, merge_registries
from byteplan.persistence import atomic_write_bytes

if TYPE_CHECKING:
    from byteplan.api import Project

DRIVER = "byteplan"
DRIVER_NAME = "BytePlan registry (merge by task ID)"


def git(args: list[str], cwd: Path, *, read_only: bool = True) -> str:
    command = ["git", "--no-optional-locks", *args] if read_only else ["git", *args]
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"} if read_only else None
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, env=env, check=True)
    except FileNotFoundError as exc:
        msg = "git is not installed or not on PATH"
        raise ConfigError(msg) from exc
    except subprocess.CalledProcessError as exc:
        msg = f"`git {' '.join(args)}` failed: {exc.stderr.strip() or exc.returncode}"
        raise ConfigError(msg) from exc
    return completed.stdout


def toplevel(path: Path) -> Path:
    return Path(git(["rev-parse", "--show-toplevel"], path).strip()).resolve()


# Merge driver -----------------------------------------------------------------------------------


@dataclass
class DriverOutcome:
    code: int  # 0 merged, 1 conflicts left for the user
    messages: list[str] = field(default_factory=list)


def _load(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.strip():  # no common ancestor: git passes an empty base
        return registry_io.to_dict(registry_io.Registry())
    return registry_io.to_dict(registry_io.loads(text, str(path)))


def merge_driver(base: Path, ours: Path, theirs: Path, label: str = ".byteplan/tasks.json") -> DriverOutcome:
    """Merge ``theirs`` into ``ours`` in place (``ours`` is Git's %A file)."""
    merged: MergeResult | None = None
    try:
        merged = merge_registries(_load(base), _load(ours), _load(theirs))
        problems = merged.conflicts
    except (RegistryError, OSError, ValueError) as exc:
        problems = [f"cannot merge by task ID: {exc}"]

    if merged is not None and merged.data is not None:
        registry = registry_io.from_dict(merged.data, label)  # validate before writing
        ours.write_text(registry_io.dumps(registry), encoding="utf-8", newline="\n")
        outcome = DriverOutcome(0, [f"byteplan: merged {label} by task ID"])
        if merged.rescan_needed:
            outcome.messages.append(
                f"byteplan: both branches changed source details of {', '.join(merged.rescan_needed)}; "
                "run `byteplan scan` after the merge to refresh them from the merged code"
            )
        return outcome

    # Fall back to Git's own text merge so the user resolves with familiar tools.
    # Git is running this driver, so `git` on PATH is the same Git; a nonzero
    # exit here just means conflicts remain, which is the expected outcome.
    subprocess.run(
        ["git", "merge-file", "-L", "ours", "-L", "base", "-L", "theirs", str(ours), str(base), str(theirs)],  # noqa: S607
        capture_output=True,
        check=False,
    )
    messages = [f"byteplan: {label} needs a manual merge:"]
    messages += [f"  - {problem}" for problem in problems]
    if any("ID collision" in problem for problem in problems):
        messages.append(
            "  For an ID collision: keep one task in the registry, finish the merge, run `byteplan scan`, "
            "then `byteplan repair --reassign PATH:LINE` on the other annotation (the scan reports where)."
        )
    messages.append(f"  Resolve the conflict markers in {label}, then `git add` it.")
    return DriverOutcome(1, messages)


# Installation ------------------------------------------------------------------------------------


def driver_command() -> str:
    """Absolute interpreter path, so Git can run the driver outside the virtualenv."""
    return f"{shlex.quote(sys.executable)} -m byteplan merge-registry %O %A %B %P"


def install_merge_driver(project: Project) -> list[str]:
    root = project.root
    toplevel(root)  # fails clearly outside a Git work tree
    actions: list[str] = []

    registry = project.config.registry_path
    attributes = registry.parent / ".gitattributes"
    line = f"{registry.name} merge={DRIVER}"
    try:
        existing = attributes.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""
    if line not in existing.splitlines():
        prefix = existing if not existing or existing.endswith("\n") else existing + "\n"
        atomic_write_bytes(attributes, (prefix + line + "\n").encode())
        actions.append(f"added `{line}` to {attributes.relative_to(root).as_posix()} (commit this file)")

    for key, value in ((f"merge.{DRIVER}.name", DRIVER_NAME), (f"merge.{DRIVER}.driver", driver_command())):
        try:
            current = git(["config", "--local", "--get", key], root).strip()
        except ConfigError:
            current = None
        if current != value:
            git(["config", "--local", key, value], root, read_only=False)
            actions.append(f"set git config {key} (local to this clone)")
    return actions


def merge_driver_main(base: str, ours: str, theirs: str, label: str | None) -> int:
    try:
        outcome = merge_driver(Path(base), Path(ours), Path(theirs), label or ".byteplan/tasks.json")
    except ByteplanError as exc:
        sys.stderr.write(f"byteplan: merge driver error: {exc}\n")
        return 2
    for message in outcome.messages:
        sys.stderr.write(message + "\n")
    return outcome.code


__all__ = ["DriverOutcome", "driver_command", "git", "install_merge_driver", "merge_driver", "toplevel"]
