# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
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

from byteplan import archive
from byteplan import registry as registry_io
from byteplan.errors import ByteplanError, ConfigError, RegistryError
from byteplan.merge import MergeResult, merge_registries
from byteplan.persistence import STATE_DIR, atomic_write_bytes

if TYPE_CHECKING:
    from byteplan.api import Project

DRIVER = "byteplan"
DRIVER_NAME = "BytePlan registry (merge by task ID)"
# The report file is generated from the registry, so a text merge of two regenerated copies
# only produces conflicts. Keep ours (`true` leaves %A as is); the next commit's hook, or
# `byteplan scan`, regenerates it from the merged registry.
REPORT_DRIVER = "byteplan-report"
REPORT_DRIVER_NAME = "BytePlan report (generated; keep ours, the next scan regenerates it)"
ARCHIVE_DRIVER = "byteplan-archive"
ARCHIVE_DRIVER_NAME = "BytePlan archive index (three-way per task ID)"


def git(args: list[str], cwd: Path, *, read_only: bool = True) -> str:
    command = ["git", "--no-optional-locks", *args] if read_only else ["git", *args]
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"} if read_only else None
    try:
        # Git writes UTF-8 (paths included); the locale's encoding (cp1252 on Windows) would garble it.
        completed = subprocess.run(
            command, cwd=cwd, capture_output=True, encoding="utf-8", errors="surrogateescape", env=env, check=True
        )
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


def driver_command(subcommand: str = "merge-registry") -> str:
    """Absolute interpreter path, so Git can run the driver outside the virtualenv."""
    return f"{shlex.quote(sys.executable)} -m byteplan {subcommand} %O %A %B %P"


def _add_attribute(root: Path, target: Path, driver: str) -> list[str]:
    """Add ``<name> merge=<driver>`` to the ``.gitattributes`` next to ``target``."""
    attributes = target.parent / ".gitattributes"
    line = f"{target.name} merge={driver}"
    try:
        existing = attributes.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""
    if line in existing.splitlines():
        return []
    prefix = existing if not existing or existing.endswith("\n") else existing + "\n"
    atomic_write_bytes(attributes, (prefix + line + "\n").encode())
    return [f"added `{line}` to {attributes.relative_to(root).as_posix()} (commit this file)"]


def install_merge_driver(project: Project) -> list[str]:
    root = project.root
    toplevel(root)  # fails clearly outside a Git work tree
    actions = _add_attribute(root, project.config.registry_path, DRIVER)
    settings = [(f"merge.{DRIVER}.name", DRIVER_NAME), (f"merge.{DRIVER}.driver", driver_command())]
    if project.report_rel is not None:
        actions += _add_attribute(root, root / project.report_rel, REPORT_DRIVER)
        settings += [(f"merge.{REPORT_DRIVER}.name", REPORT_DRIVER_NAME), (f"merge.{REPORT_DRIVER}.driver", "true")]
    actions += _add_attribute(root, root / STATE_DIR / archive.INDEX, ARCHIVE_DRIVER)
    settings += [
        (f"merge.{ARCHIVE_DRIVER}.name", ARCHIVE_DRIVER_NAME),
        (f"merge.{ARCHIVE_DRIVER}.driver", driver_command("merge-archive")),
    ]

    for key, value in settings:
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


def archive_driver_main(base: str, ours: str, theirs: str, label: str | None) -> int:
    """Merge two archive indexes into ``ours``, three-way per task ID."""
    label = label or archive.INDEX
    try:
        texts = [Path(p).read_text(encoding="utf-8") for p in (base, ours, theirs)]
        merged, conflicts = archive.merge(*texts)
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        merged, conflicts = None, [f"can't merge by task ID: {exc}"]
    if merged is not None:
        Path(ours).write_text(merged, encoding="utf-8", newline="\n")
        return 0
    # As for the registry: Git's own text merge, so the user resolves with familiar tools.
    subprocess.run(
        ["git", "merge-file", "-L", "ours", "-L", "base", "-L", "theirs", ours, base, theirs],  # noqa: S607
        capture_output=True,
        check=False,
    )
    sys.stderr.write(
        f"byteplan: {label} needs a manual merge; both sides archived or restored "
        f"{', '.join(conflicts)} differently. Keep the entry matching the merged registry's history, "
        "then `git add` it.\n"
    )
    return 1


__all__ = [
    "DriverOutcome",
    "archive_driver_main",
    "driver_command",
    "git",
    "install_merge_driver",
    "merge_driver",
    "toplevel",
]


# Pre-commit hooks -------------------------------------------------------------------------------

HOOK_MARKER = "# byteplan-managed-hook"
HOOK_COMMANDS = {
    "reconcile": "scan --staged --apply",
    "check": "check --staged",
    "scan": "scan --staged --dry-run",
}


def hooks_dir(root: Path) -> Path:
    """Where Git runs hooks from: ``core.hooksPath`` if set, else ``$GIT_DIR/hooks``."""
    top = toplevel(root)
    try:
        custom = git(["config", "--get", "core.hooksPath"], root).strip()
    except ConfigError:
        custom = ""
    if custom:
        path = Path(os.path.expanduser(custom))
        return path if path.is_absolute() else top / path
    return (root / git(["rev-parse", "--git-path", "hooks"], root).strip()).resolve()


def hook_script(project: Project, mode: str) -> str:
    return (
        "#!/bin/sh\n"
        f"{HOOK_MARKER} (installed by `byteplan git install-hooks`; edit or delete freely)\n"
        f"exec {shlex.quote(sys.executable)} -m byteplan {HOOK_COMMANDS[mode]} "
        f"--project {shlex.quote(str(project.root))}\n"
    )


def install_hooks(project: Project, mode: str = "reconcile") -> list[str]:
    """Install a direct pre-commit hook, never replacing a hook BytePlan didn't write."""
    path = hooks_dir(project.root) / "pre-commit"
    script = hook_script(project, mode)
    try:
        existing = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = None
    except (OSError, UnicodeDecodeError):
        existing = ""
    if existing is not None and HOOK_MARKER not in existing:
        msg = (
            f"{path} already exists and wasn't installed by BytePlan; leaving it alone. "
            f"Add this line to it instead: `{sys.executable} -m byteplan {HOOK_COMMANDS[mode]}`, "
            "or use the pre-commit framework hook `byteplan-check`"
        )
        raise ConfigError(msg)
    if existing == script:
        return []
    atomic_write_bytes(path, script.encode(), mode=0o755)
    path.chmod(0o755)
    return [f"{'updated' if existing else 'installed'} {path} (runs `byteplan {HOOK_COMMANDS[mode]}`)"]


@dataclass
class HooksStatus:
    pre_commit_framework: bool
    direct_hook: str  # "none" | "byteplan" | "other"
    direct_hook_path: str
    merge_driver: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "pre_commit_framework": self.pre_commit_framework,
            "direct_hook": self.direct_hook,
            "direct_hook_path": self.direct_hook_path,
            "merge_driver": self.merge_driver,
        }


def hooks_status(project: Project) -> HooksStatus:
    top = toplevel(project.root)
    framework = top / ".pre-commit-config.yaml"
    try:
        uses_framework = "byteplan-check" in framework.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        uses_framework = False
    path = hooks_dir(project.root) / "pre-commit"
    try:
        direct = "byteplan" if HOOK_MARKER in path.read_text(encoding="utf-8") else "other"
    except FileNotFoundError:
        direct = "none"
    except (OSError, UnicodeDecodeError):
        direct = "other"
    try:
        driver = bool(git(["config", "--get", f"merge.{DRIVER}.driver"], project.root).strip())
    except ConfigError:
        driver = False
    return HooksStatus(uses_framework, direct, str(path), driver)
