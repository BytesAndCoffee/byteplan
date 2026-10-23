# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Scan-scope collection.

Rules, applied to POSIX paths relative to the project root:

* Only regular files of a supported type are collected (``.py``, ``.md``/``.markdown``,
  ``.json``/``.jsonc``; see ``languages.py``), and never the registry or report file.
  Symlinks (files and directories) are
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
from typing import TYPE_CHECKING, Protocol

import pathspec

from byteplan.errors import ConfigError, ScanError, SourceError
from byteplan.languages import language_for

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


class TextSource(Protocol):
    """Where scope rules read ``.gitignore`` files from: the filesystem or a Git snapshot."""

    def read_text(self, rel: str) -> str | None:
        """Text of a project-relative POSIX path (``../`` reaches repository ancestors), or None."""
        ...

    def ancestors(self) -> list[tuple[str, str]]:
        """Directories from the Git top down to the root's parent, outermost first, as
        (directory relative to the root, prefix turning a root-relative path into one
        relative to that directory). Empty outside Git."""
        ...


class FilesystemSource:
    def __init__(self, root: Path) -> None:
        self.root = root

    def read_text(self, rel: str) -> str | None:
        try:
            return (self.root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None

    def ancestors(self) -> list[tuple[str, str]]:
        return [
            (Path(os.path.relpath(ancestor, self.root)).as_posix(), self.root.relative_to(ancestor).as_posix() + "/")
            for ancestor in _git_ancestors(self.root)
            if ancestor != self.root
        ]


class _GitIgnores:
    """``.gitignore`` files from the Git top down to the project root, plus any below it (loaded lazily)."""

    def __init__(self, source: TextSource) -> None:
        self._source = source
        # Specs at or above the root, with the prefix that turns a root-relative
        # path into one relative to that spec's directory.
        self._ancestors: list[tuple[str, pathspec.GitIgnoreSpec]] = []
        for rel_dir, prefix in [*source.ancestors(), ("", "")]:
            spec = _parse_gitignore(source.read_text(f"{rel_dir}/.gitignore" if rel_dir else ".gitignore"))
            if spec is not None:
                self._ancestors.append((prefix, spec))
        self._nested: dict[str, pathspec.GitIgnoreSpec | None] = {}

    def _nested_spec(self, rel_dir: str) -> pathspec.GitIgnoreSpec | None:
        if rel_dir not in self._nested:
            self._nested[rel_dir] = _parse_gitignore(self._source.read_text(f"{rel_dir}/.gitignore"))
        return self._nested[rel_dir]

    def ignored(self, rel_path: str, *, is_dir: bool = False) -> bool:
        suffix = "/" if is_dir else ""
        # FIXME[ae7a]: [P2] Apply nested gitignore negations with Git's precedence rules
        #   Returning on an ancestor *.py match prevents a deeper !keep.py from restoring
        #   a file, silently omitting source that Git includes from scans and snapshot checks.
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

    def __init__(self, config: Config, source: TextSource | None = None) -> None:
        self.root = config.root
        root = config.root.resolve()
        # Generated files BytePlan writes itself are never scanned.
        self._generated = {config.registry_path.resolve().relative_to(root).as_posix()}
        if config.report_file:
            self._generated.add((config.root / config.report_file).resolve().relative_to(root).as_posix())
        self._include = pathspec.PathSpec.from_lines("gitignore", config.include)
        self._exclude = pathspec.PathSpec.from_lines("gitignore", config.exclude)
        if config.respect_gitignore:
            self._gitignores: _GitIgnores | None = _GitIgnores(source or FilesystemSource(config.root))
        else:
            self._gitignores = None

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
            language_for(rel) is not None
            and rel not in self._generated
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


def _parse_gitignore(text: str | None) -> pathspec.GitIgnoreSpec | None:
    return None if text is None else pathspec.GitIgnoreSpec.from_lines(text.splitlines())


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
            # FIXME[a740]: [P2] Require regular files before selecting sources for scanning
            #   os.walk includes named pipes in filenames; selecting a FIFO such as pipe.py
            #   blocks indefinitely in read_source().read_bytes() while waiting for a writer.
            if not os.path.islink(os.path.join(dirpath, name)) and matcher.file_selected(rel):
                found.append(rel)

    if errors:
        raise ScanError(errors)
    if targets is None:
        return Scope(files=tuple(sorted(found)))
    narrowed = [rel for rel in found if any(_is_under(rel, target) for target in targets)]
    return Scope(files=tuple(sorted(narrowed)), narrowed=True, targets=tuple(targets))


def scope_from_paths(
    config: Config, paths: Sequence[str], source: TextSource, targets: Sequence[str] | None = None
) -> tuple[Scope, ScopeMatcher]:
    """The scope over an explicit file list (a Git snapshot's regular files), using the same
    rules as ``collect_files`` with ``.gitignore`` files read from ``source``."""
    matcher = ScopeMatcher(config, source)
    found = sorted(path for path in paths if matcher.contains(path))
    if targets is None:
        return Scope(files=tuple(found)), matcher
    narrowed = [rel for rel in found if any(_is_under(rel, target) for target in targets)]
    return Scope(files=tuple(narrowed), narrowed=True, targets=tuple(targets)), matcher
