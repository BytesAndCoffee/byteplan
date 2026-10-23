# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""The README documents every configuration key, with its real default."""

from __future__ import annotations

import dataclasses
import re
import tomllib
from pathlib import Path
from typing import Any

from byteplan import hatch_hook
from byteplan.config import Config

README = Path(__file__).resolve().parents[1] / "README.md"


def toml_blocks(heading: str) -> dict[str, Any]:
    """Every ```toml block under the README's ``## heading``, merged."""
    text = README.read_text(encoding="utf-8")
    section = text.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]
    merged: dict[str, Any] = {}
    for block in re.findall(r"```toml\n(.*?)```", section, re.DOTALL):
        for name, table in tomllib.loads(block).get("tool", {}).items():
            merged.setdefault(name, {}).update(table)
    return merged


def defaults(cls: type[Any], skip: frozenset[str] = frozenset()) -> dict[str, Any]:
    """A config dataclass as TOML would spell it: nested sections become tables."""
    out: dict[str, Any] = {}
    for field in dataclasses.fields(cls):
        if field.name in skip:
            continue
        if field.default_factory is not dataclasses.MISSING:
            value = field.default_factory()
            out[field.name] = defaults(type(value)) if dataclasses.is_dataclass(value) else value
        elif field.default is not dataclasses.MISSING:
            out[field.name] = field.default
    return out


def normalized(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: normalized(item) for key, item in value.items()}
    return list(value) if isinstance(value, tuple) else value


def test_every_config_key_is_documented_with_its_default() -> None:
    documented = toml_blocks("Configuration")["byteplan"]
    actual = normalized(defaults(Config, skip=frozenset({"root"})))
    assert documented == actual


def test_every_hatch_hook_key_is_documented_with_its_default() -> None:
    documented = toml_blocks("Hatch integration")["hatch"]["build"]["hooks"]["byteplan"]
    actual = defaults(hatch_hook.HookSettings)
    assert documented == actual
