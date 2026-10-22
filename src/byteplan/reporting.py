# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Text and JSON renderers. Renderers return strings; callers choose the stream."""

from __future__ import annotations

import json
import posixpath
from collections import Counter
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from byteplan.models import Presence
from byteplan.registry import task_to_dict

if TYPE_CHECKING:
    from collections.abc import Sequence

    from byteplan.api import CleanupReport, ScanReport, SyncReport, VerifyReport
    from byteplan.models import Annotation, Task
    from byteplan.registry import Registry
    from byteplan.verification import Readiness


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
        f"BytePlan: {report.files_scanned} {noun} scanned{scope}",
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


def task_text(task: Task, readiness: Readiness | None = None) -> str:
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
    tests = task.linked_tests()
    if tests:
        outcomes = readiness.tests if readiness is not None else {}
        lines.append("  tests:")
        lines.extend(
            f"    {node}  ({', '.join(provenances)})" + (f"  {outcomes[node]}" if node in outcomes else "")
            for node, provenances in tests.items()
        )
    if readiness is not None:
        lines.extend(readiness_text(readiness))
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


# The committed plan file (`[tool.byteplan] report_file`) ------------------------------------------

_OPEN_ORDER = {"in_progress": 0, "blocked": 1, "open": 2}


def _where(task: Task, report_dir: str) -> str:
    if task.source is None:
        return "-"
    # Percent-encode the path ("issue#1.py", spaces) so only "#L<line>" is the fragment.
    target = quote(posixpath.relpath(task.source.path, report_dir or "."))
    link = f"[`{_md(task.source.path)}:{task.source.line}`]({target}#L{task.source.line})"
    return f"~~{link}~~ (missing)" if task.presence is Presence.MISSING else link


def plan_markdown(registry: Registry, *, registry_rel: str, report_rel: str) -> str:
    """The committed plan: a pure function of the registry (no clock, no scan state), so the
    same registry always renders byte-identically and staleness is a plain comparison."""
    report_dir = posixpath.dirname(report_rel)
    tasks = sorted(registry.tasks.values(), key=lambda t: t.id)
    active = [t for t in tasks if not t.status.is_closed]
    active.sort(
        key=lambda t: (
            _OPEN_ORDER.get(str(t.status), 3),
            t.source.path if t.source else "",
            t.source.line if t.source else 0,
            t.id,
        )
    )
    closed = [t for t in tasks if t.status.is_closed]
    counts = Counter(str(t.status) for t in closed)

    lines = [
        "# BytePlan",
        "",
        f"<!-- Generated from {registry_rel} by BytePlan; don't edit. "
        "`byteplan scan` and the commit hook keep it current. -->",
        "",
        f"**{len(active)} open** · {len(closed)} closed"
        + (f" ({', '.join(f'{status} {n}' for status, n in sorted(counts.items()))})" if closed else ""),
        "",
        "## Open",
        "",
    ]
    if active:
        lines += ["| ID | Status | Kind | Priority | Assignee | Where | Title |", "|---|---|---|---|---|---|---|"]
        lines += [
            f"| `{t.id}` | {t.status} | {t.kind} | {_md(t.priority)} | {_md(t.assignee) or '-'} | "
            f"{_where(t, report_dir)} | {_md(t.display_title)} |"
            for t in active
        ]
    else:
        lines.append("Nothing open.")
    lines += ["", "## Closed", ""]
    if closed:
        lines += ["| ID | Status | Kind | Title |", "|---|---|---|---|"]
        lines += [f"| `{t.id}` | {t.status} | {t.kind} | {_md(t.display_title)} |" for t in closed]
    else:
        lines.append("Nothing closed yet.")
    return "\n".join(lines) + "\n"


# byteplan sync -------------------------------------------------------------------------------------


def sync_json(report: SyncReport) -> dict[str, Any]:
    return {
        "dry_run": report.dry_run,
        "blocked": report.blocked,
        "rewrites": [
            {
                "action": r.action,
                "id": r.task_id,
                "path": r.path,
                "line": r.line,
                "kind": r.kind,
                "title": r.title,
                "symbol": r.symbol,
            }
            for r in report.rewrites
        ],
        "imports_added": list(report.imports_added),
        "written": list(report.written),
        "diagnostics": [d.to_dict() for d in report.diagnostics],
    }


def sync_text(report: SyncReport) -> str:
    if report.blocked:
        return f"byteplan sync: {report.blocked}"
    converted = sum(r.action == "convert" for r in report.rewrites)
    decorated = len(report.rewrites) - converted
    review = len(report.diagnostics)
    lines = [f"BytePlan sync: {converted} comment(s) converted · {decorated} stub(s) decorated · {review} need review"]
    for r in report.rewrites:
        what = "comment -> @todo" if r.action == "convert" else f"@todo on stub {r.symbol}"
        lines.append(
            f"  {'~' if r.action == 'convert' else '+'} [{r.task_id}] {r.kind:<5} {r.path}:{r.line}  {what}: {r.title}"
        )
    lines.extend(f"  + import todo in {path}" for path in report.imports_added)
    if report.dry_run and report.rewrites:
        lines += ["", "Dry run: nothing was written. `byteplan sync --apply` writes these."]
    elif report.written:
        lines += ["", f"Wrote {len(report.written)} file(s)."]
    return "\n".join(lines)


# byteplan tests ------------------------------------------------------------------------------------


def tests_json(tasks: Sequence[Task]) -> list[dict[str, Any]]:
    return [
        {"id": t.id, "title": t.display_title, "status": str(t.status), "node": node, "provenance": provenances}
        for t in tasks
        for node, provenances in t.linked_tests().items()
    ]


def tests_text(tasks: Sequence[Task]) -> str:
    rows = tests_json(tasks)
    if not rows:
        return "No linked tests."
    width = max(len(r["node"]) for r in rows)
    lines = [f"{'ID':<5} {'TEST':<{width}}  PROVENANCE"]
    lines += [f"{r['id']:<5} {r['node']:<{width}}  {', '.join(r['provenance'])}" for r in rows]
    return "\n".join(lines)


# byteplan verify -----------------------------------------------------------------------------------


def verify_json(report: VerifyReport) -> dict[str, Any]:
    return {
        "argv": list(report.argv),
        "returncode": report.returncode,
        "timed_out": report.timed_out,
        "tasks": [
            {
                "id": tv.task.id,
                "title": tv.task.display_title,
                "readiness": tv.readiness.state,
                "reasons": list(tv.readiness.reasons),
                "tests": {node: result.to_dict() for node, result in tv.results.items()},
            }
            for tv in report.tasks
        ],
    }


def verify_text(report: VerifyReport) -> str:
    if not report.tasks:
        return "byteplan verify: no linked tests to run (link some with @todo(tests=...), @verifies or `byteplan tests add`)"
    results = [r for tv in report.tasks for r in tv.results.values()]
    counts = Counter(r.outcome for r in results)
    summary = " · ".join(f"{n} {outcome}" for outcome, n in sorted(counts.items()))
    lines = [f"BytePlan verify: {len(results)} test result(s) for {len(report.tasks)} task(s) · {summary}"]
    for tv in report.tasks:
        lines.append(f"  [{tv.task.id}] {tv.readiness.state:<16} {tv.task.display_title}")
        for node, result in tv.results.items():
            lines.append(f"      {result.outcome:<9} {node}")
            if result.message and result.outcome != "passed":
                lines.extend(f"                {line}" for line in result.message.splitlines()[-3:])
    if report.timed_out:
        lines.append("  the run timed out and was killed ([tool.byteplan.tests] timeout)")
    lines.append("Readiness never changes a task's status; resolve tasks yourself.")
    return "\n".join(lines)


def ready_text(found: Sequence[tuple[Task, Readiness]]) -> str:
    if not found:
        return "No tasks are ready for review."
    lines = ["Ready for review (every linked test is a fresh pass):"]
    lines += [f"  [{task.id}] {task.kind:<5} {task.display_title}" for task, _ in found]
    return "\n".join(lines)


def readiness_text(state: Readiness) -> list[str]:
    lines = [f"  readiness: {state.state}"]
    lines.extend(f"    - {reason}" for reason in state.reasons)
    return lines


# byteplan sync --remove-resolved ---------------------------------------------------------------


def cleanup_json(report: CleanupReport) -> dict[str, Any]:
    return {
        "dry_run": report.dry_run,
        "blocked": report.blocked,
        "removed": [{"id": task_id, "path": path} for task_id, path in report.removed],
        "suppressed": [{"id": task_id, "path": path} for task_id, path in report.suppressed],
        "imports_removed": list(report.imports_removed),
        "written": list(report.written),
        "diagnostics": [d.to_dict() for d in report.diagnostics],
    }


def cleanup_text(report: CleanupReport) -> str:
    if report.blocked:
        return f"byteplan cleanup: {report.blocked}"
    lines = [f"BytePlan cleanup: {len(report.removed)} annotation(s) removed · {len(report.suppressed)} suppressed"]
    lines += [f"  - [{task_id}] {path}" for task_id, path in report.removed]
    lines += [f"  ~ [{task_id}] {path}  (# byteplan: ignore)" for task_id, path in report.suppressed]
    lines += [f"  - unused runtime import in {path}" for path in report.imports_removed]
    if report.dry_run and (report.removed or report.suppressed):
        lines += ["", "Dry run: nothing was written. Add --apply to remove them."]
    elif report.written:
        lines += ["", f"Wrote {len(report.written)} file(s)."]
    return "\n".join(lines)
