# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Write newly allocated IDs into source.

* comment tags: ``# TODO: x`` -> ``# TODO[7fa2]: x``
* decorators: ``@todo("x")`` -> ``@todo("x", id="7fa2")``
* unowned stubs: a new ``# TODO[7fa2]: Implement f (detected stub)`` line above them
"""

from __future__ import annotations

import dataclasses
from collections import Counter
from typing import TYPE_CHECKING

from byteplan.edits import Insertion, apply_insertions, ensure_equivalent
from byteplan.errors import EditError
from byteplan.scanner import DEFAULT_RUNTIME_MODULES, FileScan, scan_file

if TYPE_CHECKING:
    from collections.abc import Sequence

    from byteplan.api import Proposal
    from byteplan.config import DetectConfig
    from byteplan.models import Annotation
    from byteplan.scanner.source import SourceFile


def _identity(annotation: Annotation, task_id: str | None) -> tuple[object, ...]:
    return (
        annotation.representation,
        annotation.kind,
        annotation.title,
        annotation.description,
        annotation.symbol,
        task_id,
    )


def annotate(
    source: SourceFile,
    proposals: Sequence[Proposal],
    detect: DetectConfig,
    runtime_modules: Sequence[str] = DEFAULT_RUNTIME_MODULES,
) -> tuple[SourceFile, FileScan]:
    """Return ``source`` with every proposal's ID written, plus a scan of the result.

    The result is validated: it must parse to the same AST (apart from added
    decorator ``id=`` keywords), and re-scanning it must find exactly the original
    annotations, now carrying the proposed IDs.
    """
    insertions = []
    proposed: dict[tuple[int, int], str] = {}
    for p in proposals:
        slot = p.tag.id_slot
        if slot is None:
            msg = f"{p.tag.location}: annotation already has an ID"
            raise EditError(msg)
        insertions.append(Insertion(slot.line, slot.col, slot.text(p.task_id)))
        proposed[(p.tag.line, p.tag.col)] = p.task_id
    edited = dataclasses.replace(source, text=apply_insertions(source.text, insertions))
    ensure_equivalent(source.path, source.text, edited.text)

    before = scan_file(source, detect, runtime_modules).tags
    after = scan_file(edited, detect, runtime_modules)
    expected = Counter(_identity(a, proposed.get((a.line, a.col), a.task_id)) for a in before)
    if expected != Counter(_identity(a, a.task_id) for a in after.tags):
        msg = f"{source.path}: annotation did not round-trip through the scanner; nothing was written"
        raise EditError(msg)
    return edited, after
