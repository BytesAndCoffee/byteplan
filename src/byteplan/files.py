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
* A directory that can't be listed fails the collection (``ScanError``) rather
  than being skipped, so missing detection never treats it as deleted.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pathspec

from byteplan.errors import ConfigError, ScanError, SourceError

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
    """``.gitignore`` files from the Git top down to the project root, plus any below it (loaded lazily)."""

    def __init__(self, root: Path) -> None:
        self._root = root
        # Specs at or above the root, with the prefix that turns a root-relative
        # path into one relative to that spec's directory.
        self._ancestors: list[tuple[str, pathspec.GitIgnoreSpec]] = []
        for ancestor in _git_ancestors(root):
            spec = _read_gitignore(ancestor / ".gitignore")
            if spec is not None:
                prefix = "" if ancestor == root else root.relative_to(ancestor).as_posix() + "/"
                self._ancestors.append((prefix, spec))
        self._nested: dict[str, pathspec.GitIgnoreSpec | None] = {}

    def _nested_spec(self, rel_dir: str) -> pathspec.GitIgnoreSpec | None:
        if rel_dir not in self._nested:
            self._nested[rel_dir] = _read_gitignore(self._root / rel_dir / ".gitignore")
        return self._nested[rel_dir]

    def ignored(self, rel_path: str, *, is_dir: bool = False) -> bool:
        suffix = "/" if is_dir else ""
        if any(spec.match_file(prefix + rel_path + suffix) for prefix, spec in self._ancestors):
            return True
        parts = rel_path.split("/")
        for depth in range(1, len(parts)):
            base = "/".join(parts[:depth])
            spec = self._nested_spec(base)
            if spec is not None and spec.match_file("/".join(parts[depth:]) + suffix):
                return True
        return False


class ScopeMatcher:
    """The configured scope as a predicate over root-relative POSIX paths."""

    def __init__(self, config: Config) -> None:
        self.root = config.root
        self._include = pathspec.PathSpec.from_lines("gitignore", config.include)
        self._exclude = pathspec.PathSpec.from_lines("gitignore", config.exclude)
        self._gitignores = _GitIgnores(config.root) if config.respect_gitignore else None

    def dir_excluded(self, rel_dir: str) -> bool:
        name = rel_dir.rsplit("/", 1)[-1]
        return (
            name in ALWAYS_SKIP_DIRS
            or self._exclude.match_file(f"{rel_dir}/{_DIR_PROBE}")
            or (self._gitignores is not None and self._gitignores.ignored(rel_dir, is_dir=True))
        )

    def file_selected(self, rel: str) -> bool:
        """Whether a file in a non-excluded directory is in scope (no symlink check)."""
        return (
            rel.endswith(".py")
            and self._include.match_file(rel)
            and not self._exclude.match_file(rel)
            and not (self._gitignores is not None and self._gitignores.ignored(rel))
        )

    def contains(self, rel: str) -> bool:
        """Whether ``rel`` is in scope, whether or not the file currently exists."""
        parts = rel.split("/")
        if any(self.dir_excluded("/".join(parts[:depth])) for depth in range(1, len(parts))):
            return False
        return self.file_selected(rel)


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
    matcher = ScopeMatcher(config)

    found: list[str] = []
    errors: list[SourceError] = []

    def on_error(exc: OSError) -> None:
        # An unreadable directory must not look like deleted source: that would
        # mark every task in it missing. Fail the whole scan instead.
        where = Path(exc.filename).relative_to(root).as_posix() if exc.filename else "."
        errors.append(SourceError(where or ".", f"cannot list directory: {exc.strerror}"))

    for dirpath, dirnames, filenames in os.walk(root, onerror=on_error):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        rel_dir = "" if rel_dir == "." else rel_dir

        kept: list[str] = []
        for name in sorted(dirnames):
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if not os.path.islink(os.path.join(dirpath, name)) and not matcher.dir_excluded(rel):
                kept.append(name)
        dirnames[:] = kept

        for name in filenames:
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if not os.path.islink(os.path.join(dirpath, name)) and matcher.file_selected(rel):
                found.append(rel)

    if errors:
        raise ScanError(errors)
    if targets is None:
        return Scope(files=tuple(sorted(found)))
    narrowed = [rel for rel in found if any(_is_under(rel, target) for target in targets)]
    return Scope(files=tuple(sorted(narrowed)), narrowed=True, targets=tuple(targets))
