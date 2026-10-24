# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Exception hierarchy. Every ``ByteplanError`` maps to CLI exit code 2."""

from __future__ import annotations


class ByteplanError(Exception):
    """Base class for runtime, configuration, and data errors."""


class ConfigError(ByteplanError):
    """Invalid or unreadable ``[tool.byteplan]`` configuration or project layout."""


class RegistryError(ByteplanError):
    """The registry is missing, corrupt, or has an unsupported schema version."""


class SourceError(ByteplanError):
    """A source file in scope could not be read, decoded, tokenized, or parsed."""

    def __init__(self, path: str, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


class ScanError(ByteplanError):
    """A scan could not complete; no reconciliation was performed."""

    def __init__(self, failures: list[SourceError]) -> None:
        lines = "\n".join(f"  {failure}" for failure in failures)
        super().__init__(f"scan aborted, {len(failures)} file(s) could not be processed:\n{lines}")
        self.failures = failures


class IdExhaustedError(ByteplanError):
    """The namespace for newly generated task IDs is exhausted."""


class TaskNotFoundError(ByteplanError):
    """No registry task has the requested ID."""


class EditError(ByteplanError):
    """A planned source edit failed validation; nothing was written."""


class LockedError(ByteplanError):
    """Another BytePlan process holds the project lock."""


class ConcurrentModificationError(ByteplanError):
    """A file changed between being read and being written; nothing was written."""

    def __init__(self, paths: list[str]) -> None:
        listed = ", ".join(paths)
        super().__init__(f"file(s) changed while byteplan was running: {listed}; nothing was written, run again")
        self.paths = paths


class JournalConflictError(ByteplanError):
    """An interrupted write can't be completed because a target has changed since."""
