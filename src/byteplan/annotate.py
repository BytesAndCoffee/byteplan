# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Write newly allocated IDs into tag comments: ``# TODO: x`` -> ``# TODO[7fa2]: x``."""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from byteplan.edits import Insertion, apply_insertions, ensure_equivalent
from byteplan.errors import EditError
from byteplan.scanner import scan_file

if TYPE_CHECKING:
    from collections.abc import Sequence

    from byteplan.api import Proposal
    from byteplan.config import DetectConfig
    from byteplan.scanner.source import SourceFile


def annotate(source: SourceFile, proposals: Sequence[Proposal], detect: DetectConfig) -> SourceFile:
    """Return ``source`` with each proposal's ID inserted after its tag word.

    The result is validated: it must parse to the same AST, and re-scanning it
    must find exactly the original tags, with the new IDs on the proposed lines.
    """
    insertions = []
    for p in proposals:
        slot = p.tag.id_slot
        if slot is None:
            msg = f"{p.tag.location}: annotation already has an ID"
            raise EditError(msg)
        insertions.append(Insertion(slot.line, slot.col, slot.text(p.task_id)))
    edited = dataclasses.replace(source, text=apply_insertions(source.text, insertions))
    ensure_equivalent(source.path, source.text, edited.text)

    before = scan_file(source, detect).tags
    after = scan_file(edited, detect).tags
    expected = {p.tag.line: p.task_id for p in proposals}
    if len(before) != len(after) or any(
        (b.line, b.kind, b.title, b.description, expected.get(b.line, b.task_id))
        != (a.line, a.kind, a.title, a.description, a.task_id)
        for b, a in zip(before, after, strict=True)
    ):
        msg = f"{source.path}: annotation did not round-trip through the scanner; nothing was written"
        raise EditError(msg)
    return edited
