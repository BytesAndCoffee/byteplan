# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Text and JSON renderers. Renderers return strings; callers choose the stream."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from byteplan.registry import task_to_dict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from byteplan.api import ScanReport
    from byteplan.models import CommentTag, Task


def to_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)


def _tag_dict(tag: CommentTag) -> dict[str, Any]:
    return {
        "id": tag.task_id,
        "kind": tag.kind,
        "title": tag.title,
        "description": tag.description,
        "path": tag.path,
        "line": tag.line,
        "symbol": tag.symbol,
    }


def scan_json(report: ScanReport, *, dry_run: bool) -> dict[str, Any]:
    return {
        "dry_run": dry_run,
        "files_scanned": report.files_scanned,
        "narrowed": report.scope.narrowed,
        "annotations": [_tag_dict(tag) for tag in report.tags],
        "proposed": [{**_tag_dict(p.tag), "id": p.task_id} for p in report.proposals],
        "diagnostics": [d.to_dict() for d in report.diagnostics],
    }


def scan_text(report: ScanReport) -> str:
    noun = "file" if report.files_scanned == 1 else "files"
    scope = " (narrowed scope)" if report.scope.narrowed else ""
    lines = [
        f"BytePlan: {report.files_scanned} Python {noun} scanned{scope}",
        f"  {len(report.tags)} comment annotations · {len(report.tagged)} tagged · {len(report.proposals)} untagged",
    ]
    if report.proposals:
        lines.append("")
        lines.append("Would annotate:")
        lines.extend(f"  + [{p.task_id}] {p.tag.kind:<5} {p.tag.location}  {p.tag.title}" for p in report.proposals)
    return "\n".join(lines)


def task_row(task: Task) -> tuple[str, ...]:
    where = f"{task.source.path}:{task.source.line}" if task.source else "-"
    return (task.id, str(task.status), str(task.presence), task.kind, task.priority, where, task.display_title)


def task_table(tasks: Sequence[Task]) -> str:
    if not tasks:
        return "No tasks."
    header = ("ID", "STATUS", "PRESENCE", "KIND", "PRIORITY", "LOCATION", "TITLE")
    rows = [header, *(task_row(task) for task in tasks)]
    widths = [max(len(row[i]) for row in rows) for i in range(len(header) - 1)]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(row[:-1], widths, strict=True)) + "  " + row[-1]
        for row in rows
    )


def task_text(task: Task) -> str:
    lines = [f"[{task.id}] {task.kind}: {task.display_title}"]
    if task.title_override:
        lines.append(f"  source title: {task.title}")
    if task.description:
        lines.extend(f"  | {line}" for line in task.description.splitlines())
    lines.append(f"  status:    {task.status}")
    lines.append(f"  presence:  {task.presence}")
    lines.append(f"  priority:  {task.priority}")
    lines.append(f"  assignee:  {task.assignee or '-'}")
    lines.append(f"  labels:    {', '.join(task.labels) or '-'}")
    if task.source:
        symbol = f"  ({task.source.symbol})" if task.source.symbol else ""
        lines.append(f"  source:    {task.source.path}:{task.source.line}{symbol}")
    lines.append(f"  origin:    {task.origin}")
    lines.append(f"  seen:      {task.first_seen or '-'} … {task.last_seen or '-'}")
    if task.notes:
        lines.append("  notes:")
        lines.extend(f"    {line}" for line in task.notes.splitlines())
    if task.history:
        lines.append("  history:")
        for event in task.history:
            change = ""
            if event.old is not None or event.new is not None:
                change = f"  {event.old!r} → {event.new!r}"
            lines.append(f"    {event.at}  {event.event}{change}")
    return "\n".join(lines)


def task_json(task: Task) -> dict[str, Any]:
    return task_to_dict(task)
