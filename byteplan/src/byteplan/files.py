# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Scan-scope collection.

Rules, applied to POSIX paths relative to the project root:

* Only regular ``.py`` files are collected. Symlinks (files and directories) are
  never followed, so a file can't be scanned twice or from outside the root.
* ``.git``, ``.hg``, ``.svn`` and ``.byteplan`` directories are always skipped.
* A file is in scope when it matches ``include``, does not match ``exclude``,
  and (with ``respect_gitignore``) is not ignored by a ``.gitignore`` between the
  enclosing Git work tree's top and the file. ``.git/info/exclude`` and global
  excludes are not read.
* Files are returned sorted, so scans and ID allocation are deterministic.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pathspec

from byteplan.errors import ConfigError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from byteplan.config import Config

ALWAYS_SKIP_DIRS = frozenset({".git", ".hg", ".svn", ".byteplan"})
# A child name used to test whether an exclude pattern covers a whole directory.
_DIR_PROBE = "__byteplan_dir_probe__"


@dataclass(frozen=True)
class Scope:
    files: tuple[str, ...]
    # True when the caller limited the scan to specific paths. Narrowed scans
    # must never mark tasks outside those paths missing.
    narrowed: bool = False
    targets: tuple[str, ...] = ()

    def covers(self, rel_path: str) -> bool:
        """Whether a task at ``rel_path`` was fully evaluated by this scope."""
        if not self.narrowed:
            return True
        return any(_is_under(rel_path, target) for target in self.targets)


class _GitIgnores:
    """``.gitignore`` files from the Git top down to (and below) the project root."""

    def __init__(self, root: Path) -> None:
        # (base dir relative to root, "" for root and its ancestors;
        #  prefix that turns a root-relative path into an ancestor-relative one; spec)
        self._specs: list[tuple[str, str, pathspec.GitIgnoreSpec]] = []
        for ancestor in _git_ancestors(root):
            spec = _read_gitignore(ancestor / ".gitignore")
            if spec is not None:
                prefix = "" if ancestor == root else root.relative_to(ancestor).as_posix() + "/"
                self._specs.append(("", prefix, spec))

    def add_dir(self, root: Path, rel_dir: str) -> None:
        spec = _read_gitignore(root / rel_dir / ".gitignore")
        if spec is not None:
            self._specs.append((rel_dir, "", spec))

    def ignored(self, rel_path: str, *, is_dir: bool = False) -> bool:
        suffix = "/" if is_dir else ""
        for base, prefix, spec in self._specs:
            if base:
                if not rel_path.startswith(base + "/"):
                    continue
                candidate = rel_path[len(base) + 1 :]
            else:
                candidate = prefix + rel_path
            if spec.match_file(candidate + suffix):
                return True
        return False


def _git_ancestors(root: Path) -> list[Path]:
    """Directories from the Git top level down to ``root`` (inclusive); just ``root`` outside Git."""
    chain: list[Path] = []
    for directory in (root, *root.parents):
        chain.append(directory)
        if (directory / ".git").exists():
            return list(reversed(chain))
    return [root]


def _read_gitignore(path: Path) -> pathspec.GitIgnoreSpec | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    return pathspec.GitIgnoreSpec.from_lines(lines)


def _is_under(rel_path: str, target: str) -> bool:
    return target in {"", "."} or rel_path == target or rel_path.startswith(target + "/")


def resolve_targets(root: Path, targets: Sequence[str | Path], cwd: Path | None = None) -> tuple[str, ...]:
    """Turn user-supplied paths into root-relative POSIX paths, rejecting anything outside the root."""
    base = (cwd or Path.cwd()).resolve()
    resolved: list[str] = []
    for target in targets:
        path = (base / target).resolve()
        if not path.is_relative_to(root):
            msg = f"{target} is outside the project root {root}"
            raise ConfigError(msg)
        if not path.exists():
            msg = f"{target} does not exist"
            raise ConfigError(msg)
        resolved.append(path.relative_to(root).as_posix())
    return tuple(sorted(set(resolved)))


def collect_files(config: Config, targets: Sequence[str] | None = None) -> Scope:
    """Collect in-scope files. ``targets`` are root-relative paths from ``resolve_targets``."""
    root = config.root
    include = pathspec.PathSpec.from_lines("gitignore", config.include)
    exclude = pathspec.PathSpec.from_lines("gitignore", config.exclude)
    gitignores = _GitIgnores(root) if config.respect_gitignore else None

    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir
        if gitignores is not None and rel_dir:
            gitignores.add_dir(root, rel_dir)

        kept: list[str] = []
        for name in sorted(dirnames):
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if (
                name in ALWAYS_SKIP_DIRS
                or os.path.islink(os.path.join(dirpath, name))
                or exclude.match_file(f"{rel}/{_DIR_PROBE}")
                or (gitignores is not None and gitignores.ignored(rel, is_dir=True))
            ):
                continue
            kept.append(name)
        dirnames[:] = kept

        for name in filenames:
            if not name.endswith(".py"):
                continue
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if os.path.islink(os.path.join(dirpath, name)):
                continue
            if not include.match_file(rel) or exclude.match_file(rel):
                continue
            if gitignores is not None and gitignores.ignored(rel):
                continue
            found.append(rel)

    if targets is None:
        return Scope(files=tuple(sorted(found)))
    narrowed = [rel for rel in found if any(_is_under(rel, target) for target in targets)]
    return Scope(files=tuple(sorted(narrowed)), narrowed=True, targets=tuple(targets))
