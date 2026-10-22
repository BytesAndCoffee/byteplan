# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""The source formats BytePlan scans, chosen by file suffix."""

from __future__ import annotations

from enum import StrEnum


class Language(StrEnum):
    PYTHON = "python"
    MARKDOWN = "markdown"
    JSON = "json"


_SUFFIXES = {
    ".py": Language.PYTHON,
    ".md": Language.MARKDOWN,
    ".markdown": Language.MARKDOWN,
    # Comments are accepted in both: tsconfig.json and .vscode/*.json are commented .json files.
    ".json": Language.JSON,
    ".jsonc": Language.JSON,
}


def language_for(path: str) -> Language | None:
    """The format of a POSIX path, or None if BytePlan doesn't scan files like it."""
    name = path.rsplit("/", 1)[-1]
    dot = name.rfind(".")
    return _SUFFIXES.get(name[dot:].lower()) if dot > 0 else None
