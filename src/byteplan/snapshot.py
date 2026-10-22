# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Read-only Git snapshots: the index (staging area) or a commit.

A snapshot supplies file contents from Git objects, never from the working
tree, so ``check --staged`` judges exactly what will be committed even when the
working tree holds other (possibly broken) edits.

Only plumbing is used: ``rev-parse``, ``ls-files --stage -z``, ``ls-tree -r -z``
and one long-lived ``cat-file --batch``, all with ``--no-optional-locks`` and
``GIT_OPTIONAL_LOCKS=0`` so ``.git/index`` is never rewritten. Paths are
NUL-delimited, so spaces, newlines and non-ASCII names are handled. Symlinks
(mode 120000) and submodules (160000) are not regular files and are skipped,
as the working-tree walk skips symlinks.
"""

from __future__ import annotations

import os
import posixpath
import subprocess
from dataclasses import dataclass
from typing import IO, TYPE_CHECKING, Self

from byteplan.errors import ByteplanError, ConfigError
from byteplan.gitio import toplevel

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

REGULAR_FILE_MODES = frozenset({"100644", "100755"})


class UnmergedIndexError(ByteplanError):
    """The index has unresolved merge entries; there is no single staged snapshot."""


@dataclass(frozen=True)
class Entry:
    mode: str
    oid: str


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", "surrogateescape")


def _git_bytes(args: list[str], cwd: Path) -> bytes:
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    try:
        # `git` from PATH, the same Git the user runs; read-only plumbing only.
        return subprocess.run(
            ["git", "--no-optional-locks", *args],  # noqa: S607
            cwd=cwd,
            capture_output=True,
            env=env,
            check=True,
        ).stdout
    except FileNotFoundError as exc:
        msg = "git is not installed or not on PATH"
        raise ConfigError(msg) from exc
    except subprocess.CalledProcessError as exc:
        msg = f"`git {' '.join(args)}` failed: {_decode(exc.stderr).strip() or exc.returncode}"
        raise ConfigError(msg) from exc


class _CatFile:
    """One ``git cat-file --batch`` process for all blob reads."""

    def __init__(self, cwd: Path) -> None:
        self._process = subprocess.Popen(
            ["git", "--no-optional-locks", "cat-file", "--batch"],  # noqa: S607
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )

    def read(self, oid: str) -> bytes:
        stdin: IO[bytes] = self._process.stdin  # type: ignore[assignment]
        stdout: IO[bytes] = self._process.stdout  # type: ignore[assignment]
        stdin.write(oid.encode() + b"\n")
        stdin.flush()
        header = stdout.readline().split()
        if len(header) != 3:  # noqa: PLR2004 - "<oid> <type> <size>"
            msg = f"git object {oid} is missing"
            raise ConfigError(msg)
        data = stdout.read(int(header[2]))
        stdout.read(1)  # trailing newline
        return data

    def close(self) -> None:
        if self._process.stdin:
            self._process.stdin.close()
        self._process.wait(timeout=30)
        if self._process.stdout:
            self._process.stdout.close()


class GitSnapshot:
    """The Git index (``rev=None``) or a commit, seen from a project inside the repository."""

    writable = False

    def __init__(self, project_root: Path, rev: str | None = None) -> None:
        self.root = project_root
        self.top = toplevel(project_root)
        offset = project_root.resolve().relative_to(self.top).as_posix()
        self.offset = "" if offset == "." else offset
        if rev is None:
            self.kind = "index"
            self.label = "index"
            self.entries = self._index_entries()
        else:
            commit = _decode(_git_bytes(["rev-parse", "--verify", "--end-of-options", f"{rev}^{{commit}}"], self.top))
            self.commit = commit.strip()
            self.kind = "commit"
            self.label = f"commit {self.commit[:12]}"
            self.entries = self._tree_entries(self.commit)
        self._cat: _CatFile | None = None
        self._cache: dict[str, bytes | None] = {}

    def _index_entries(self) -> dict[str, Entry]:
        entries: dict[str, Entry] = {}
        unmerged: set[str] = set()
        for record in _git_bytes(["ls-files", "--stage", "-z", "--full-name"], self.top).split(b"\0"):
            if not record:
                continue
            meta, _, path = record.partition(b"\t")
            mode, oid, stage = _decode(meta).split(" ")
            if stage != "0":
                unmerged.add(_decode(path))
                continue
            entries[_decode(path)] = Entry(mode, oid)
        if unmerged:
            listed = ", ".join(sorted(unmerged)[:5]) + (" ..." if len(unmerged) > 5 else "")  # noqa: PLR2004
            msg = f"the index has unmerged paths ({listed}); finish or abort the merge first (unmerged_index)"
            raise UnmergedIndexError(msg)
        return entries

    def _tree_entries(self, commit: str) -> dict[str, Entry]:
        entries: dict[str, Entry] = {}
        for record in _git_bytes(["ls-tree", "-r", "-z", "--full-tree", commit], self.top).split(b"\0"):
            if not record:
                continue
            meta, _, path = record.partition(b"\t")
            mode, _kind, oid = _decode(meta).split(" ")
            entries[_decode(path)] = Entry(mode, oid)
        return entries

    # Reading ------------------------------------------------------------------------------------

    def _top_rel(self, rel: str) -> str | None:
        path = posixpath.normpath(posixpath.join(self.offset, rel)) if self.offset else posixpath.normpath(rel)
        return None if path == ".." or path.startswith("../") else path

    def read_top(self, top_rel: str) -> bytes | None:
        if top_rel not in self._cache:
            entry = self.entries.get(top_rel)
            if entry is None or entry.mode not in REGULAR_FILE_MODES:
                self._cache[top_rel] = None
            else:
                if self._cat is None:
                    self._cat = _CatFile(self.top)
                self._cache[top_rel] = self._cat.read(entry.oid)
        return self._cache[top_rel]

    def read(self, rel: str) -> bytes | None:
        """Bytes of a project-relative path (``../`` reaches into the rest of the repository)."""
        top_rel = self._top_rel(rel)
        return None if top_rel is None else self.read_top(top_rel)

    def blob_oid(self, rel: str) -> str | None:
        top_rel = self._top_rel(rel)
        entry = None if top_rel is None else self.entries.get(top_rel)
        return None if entry is None else entry.oid

    # TextSource (for .gitignore files) ----------------------------------------------------------------

    def read_text(self, rel: str) -> str | None:
        data = self.read(rel)
        try:
            return None if data is None else data.decode("utf-8")
        except UnicodeDecodeError:
            return None

    def ancestors(self) -> list[tuple[str, str]]:
        parts = self.offset.split("/") if self.offset else []
        return [("/".join([".."] * (len(parts) - depth)), "/".join(parts[depth:]) + "/") for depth in range(len(parts))]

    def files(self) -> Iterator[str]:
        """Project-relative paths of the regular files in this snapshot."""
        prefix = f"{self.offset}/" if self.offset else ""
        for path, entry in self.entries.items():
            if entry.mode in REGULAR_FILE_MODES and path.startswith(prefix):
                yield path[len(prefix) :]

    def close(self) -> None:
        if self._cat is not None:
            self._cat.close()
            self._cat = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


__all__ = ["Entry", "GitSnapshot", "UnmergedIndexError"]
