# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Text and JSON renderers. Renderers return strings; callers choose the stream."""

from __future__ import annotations

import json
from collections import Counter
from typing import TYPE_CHECKING, Any

from byteplan.registry import task_to_dict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from byteplan.api import ScanReport
    from byteplan.models import Annotation, Task


def to_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True)


def _tag_dict(tag: Annotation) -> dict[str, Any]:
    return {
        "id": tag.task_id,
        "kind": tag.kind,
        "title": tag.title,
        "description": tag.description,
        "path": tag.path,
        "line": tag.line,
        "symbol": tag.symbol,
    }


def scan_json(report: ScanReport) -> dict[str, Any]:
    summary = report.summary
    return {
        "dry_run": report.dry_run,
        "blocked": report.blocked,
        "files_scanned": report.files_scanned,
        "narrowed": report.scope.narrowed,
        "tracked": report.tracked,
        "annotations": [_tag_dict(tag) for tag in report.tags],
        "annotated": [{**_tag_dict(p.tag), "id": p.task_id} for p in report.proposals],
        "added": summary.added,
        "relocated": summary.relocated,
        "text_changed": summary.text_changed,
        "missing": summary.missing,
        "reappeared": summary.reappeared,
        "excluded": summary.excluded,
        "written": list(report.written),
        "recovered": list(report.recovered),
        "diagnostics": [d.to_dict() for d in report.diagnostics],
    }


def scan_text(report: ScanReport) -> str:
    noun = "file" if report.files_scanned == 1 else "files"
    scope = " (narrowed scope; missing detection skipped)" if report.scope.narrowed else ""
    summary = report.summary
    codes = Counter(str(d.code) for d in report.diagnostics)
    lines = [
        f"BytePlan: {report.files_scanned} Python {noun} scanned{scope}",
        f"  {len(report.tags)} annotations · {report.tracked} tracked tasks",
        f"  +{len(summary.added)} added · ~{len(summary.relocated)} relocated · "
        f"!{codes['missing']} missing · !{codes['duplicate_id']} duplicate · {codes['stale_annotation']} stale",
    ]
    if report.recovered:
        lines.append(f"  completed an interrupted write to {len(report.recovered)} file(s)")
    if report.proposals:
        verb = "Would annotate" if report.dry_run or report.blocked else "Annotated"
        lines.append("")
        lines.append(f"{verb}:")
        lines.extend(f"  + [{p.task_id}] {p.tag.kind:<5} {p.tag.location}  {p.tag.title}" for p in report.proposals)
    if report.blocked:
        lines.append("")
        lines.append("Nothing was written: resolve the duplicate IDs below first.")
    elif report.dry_run:
        lines.append("")
        lines.append("Dry run: nothing was written.")
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
            if event.old is None and event.new is None:
                change = ""
            elif event.old is None:
                change = f"  {_value(event.new)}"
            else:
                change = f"  {_value(event.old)} → {_value(event.new)}"
            lines.append(f"    {event.at}  {event.event}{change}")
            if event.note:
                lines.append(f"      note: {event.note}")
    return "\n".join(lines)


def _value(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{key}={_value(item)}" for key, item in value.items())
    if isinstance(value, list):
        return "[" + ", ".join(_value(item) for item in value) + "]"
    return "-" if value is None else str(value)


def task_json(task: Task) -> dict[str, Any]:
    return task_to_dict(task)


def _summary_lines(summary: dict[str, Any]) -> list[tuple[str, str]]:
    rows = []
    for key, label in (
        ("by_status", "status"),
        ("by_presence", "presence"),
        ("by_kind", "kind"),
        ("by_priority", "priority"),
    ):
        counts = summary[key]
        rows.append((label, " · ".join(f"{name} {n}" for name, n in counts.items()) or "-"))
    return rows


def report_text(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [f"BytePlan report: {summary['total']} tasks"]
    lines.extend(f"  {label:<9} {value}" for label, value in _summary_lines(summary))
    severities = Counter(d["severity"] for d in report["diagnostics"])
    lines.append(
        f"  findings  {severities['error']} error(s) · {severities['warning']} warning(s) · {severities['info']} info"
    )
    return "\n".join(lines)


def _md(text: str | None) -> str:
    return (text or "").replace("|", "\\|").replace("\n", " ")


def report_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = ["# BytePlan report", "", f"**{summary['total']} tasks**", ""]
    lines += ["| | |", "|---|---|"]
    lines += [f"| {label} | {_md(value)} |" for label, value in _summary_lines(summary)]
    lines += ["", "## Tasks", ""]
    if report["tasks"]:
        lines += ["| ID | Status | Presence | Kind | Priority | Location | Title |", "|---|---|---|---|---|---|---|"]
        for task in report["tasks"]:
            source = task["source"]
            where = f"`{source['path']}:{source['line']}`" if source else "-"
            title = task["title_override"] or task["title"]
            lines.append(
                f"| `{task['id']}` | {task['status']} | {task['presence']} | {task['kind']} | "
                f"{_md(task['priority'])} | {where} | {_md(title)} |"
            )
    else:
        lines.append("No tasks.")
    lines += ["", "## Findings", ""]
    if report["diagnostics"]:
        for diag in report["diagnostics"]:
            where = ", ".join(
                f"`{loc['path']}:{loc['line']}`" if loc["line"] else f"`{loc['path']}`" for loc in diag["locations"]
            )
            ident = f"`{diag['task_id']}` " if diag["task_id"] else ""
            lines.append(f"- **{diag['severity']}** `{diag['code']}` {ident}{where}: {_md(diag['message'])}")
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"
