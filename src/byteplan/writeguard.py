# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Filesystem boundaries for serialized write and recovery plans."""

from __future__ import annotations

import re
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath

_PROTECTED = frozenset({".git", ".hg", ".svn"})
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def valid_hash(value: object, *, absent: bool = False) -> bool:
    return (absent and value is None) or (isinstance(value, str) and _HASH.fullmatch(value) is not None)


def relative_path(value: object) -> str:
    """Accept canonical portable project paths, never OS-dependent absolute paths."""
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        msg = "a nonempty project-relative POSIX path is required"
        raise ValueError(msg)
    parts = value.split("/")
    if (
        PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).drive
        or any(part in {"", ".", ".."} for part in parts)
    ):
        msg = f"unsafe project-relative path {value!r}"
        raise ValueError(msg)
    return value


def project_target(root: Path, value: object, *, control: bool = False) -> Path:
    """Validate before reading a target or creating its parents.

    Confined parent aliases are permitted for ordinary targets. Control directories and
    files must not be aliases; otherwise journal/lock cleanup could affect another tree.
    Existing targets must be regular, non-symlink files.
    """
    rel = relative_path(value)
    base = root.resolve()
    path = base / rel
    try:
        resolved = path.resolve(strict=False)
    except RuntimeError as exc:
        msg = f"target {rel!r} contains a symlink loop"
        raise ValueError(msg) from exc
    if not resolved.is_relative_to(base) or resolved == base:
        msg = f"target {rel!r} escapes the project"
        raise ValueError(msg)
    lexical = PurePosixPath(rel).parts
    actual = resolved.relative_to(base).parts
    if any(part.rstrip(" .").casefold() in _PROTECTED for part in (*lexical, *actual)):
        msg = f"target {rel!r} selects protected version-control metadata"
        raise ValueError(msg)
    normalized = tuple(part.rstrip(" .").casefold() for part in lexical)
    normalized_actual = tuple(part.rstrip(" .").casefold() for part in actual)
    if not control and (
        normalized[:2] == (".byteplan", "txn")
        or normalized_actual[:2] == (".byteplan", "txn")
        or normalized == (".byteplan", "scan.lock")
        or normalized_actual == (".byteplan", "scan.lock")
    ):
        msg = f"target {rel!r} selects transaction or lock state"
        raise ValueError(msg)
    if control:
        current = base
        for part in lexical:
            current /= part
            if current.is_symlink():
                msg = f"transaction control path {rel!r} contains a symlink"
                raise ValueError(msg)
    try:
        mode = path.lstat().st_mode
    except (FileNotFoundError, NotADirectoryError):
        return path
    if not stat.S_ISREG(mode):
        msg = f"target {rel!r} is not a regular non-symlink file"
        raise ValueError(msg)
    return path


def control_directory(root: Path, rel: str) -> Path:
    """Validate an internal transaction directory without requiring it to exist."""
    relative_path(rel)
    base = root.resolve()
    current = base
    for part in PurePosixPath(rel).parts:
        current /= part
        if current.is_symlink():
            msg = f"transaction directory {rel!r} contains a symlink"
            raise ValueError(msg)
        if current.exists() and not current.is_dir():
            msg = f"transaction directory {rel!r} is not a directory"
            raise ValueError(msg)
    return current


def copy_path(directory: Path, name: object, suffix: str) -> Path:
    """A copy belongs to one transaction and is read only as a regular file."""
    if not isinstance(name, str) or re.fullmatch(rf"[0-9]+\.{suffix}", name) is None:
        msg = f"invalid transaction copy name {name!r}"
        raise ValueError(msg)
    path = directory / name
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return path
    if not stat.S_ISREG(mode):
        msg = f"transaction copy {name!r} is not a regular non-symlink file"
        raise ValueError(msg)
    return path
