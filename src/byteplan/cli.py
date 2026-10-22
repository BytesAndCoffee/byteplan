# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Command-line entry point.

stdout carries only the command's payload (text or JSON); progress, warnings and
diagnostics go to stderr. Exit codes: 0 success, 1 policy findings, 2 errors.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

from byteplan import reporting
from byteplan.__about__ import __version__
from byteplan.api import Project, init_project
from byteplan.diagnostics import EXIT_ERROR, EXIT_FINDINGS, EXIT_OK, Code
from byteplan.errors import ByteplanError, ConfigError
from byteplan.files import resolve_targets
from byteplan.models import Presence, Status

if TYPE_CHECKING:
    from collections.abc import Sequence

    from byteplan.models import Task

__all__ = ["EXIT_ERROR", "EXIT_FINDINGS", "EXIT_OK", "build_parser", "main"]


def _out(text: str) -> None:
    sys.stdout.write(text + "\n")


def _err(text: str) -> None:
    sys.stdout.flush()  # keep terminal output in order when both streams are a TTY
    sys.stderr.write(text + "\n")


def _project(args: argparse.Namespace) -> Project:
    return Project.open(args.project)


def cmd_init(args: argparse.Namespace) -> int:
    result = init_project(args.project)
    for action in result.actions:
        _out(f"byteplan: {action}")
    if not result.actions:
        _out(f"byteplan: already initialized in {result.root}")
    for warning in result.warnings:
        _err(f"byteplan: warning: {warning}")
    return EXIT_OK


def cmd_scan(args: argparse.Namespace) -> int:
    project = _project(args)
    report = project.scan(args.paths or None, dry_run=args.dry_run)
    if args.format == "json":
        _out(reporting.to_json(reporting.scan_json(report)))
    else:
        _out(reporting.scan_text(report))
    for diagnostic in report.diagnostics:
        _err(diagnostic.format_text())
    return project.exit_code(report.diagnostics)


def cmd_list(args: argparse.Namespace) -> int:
    statuses = [Status(value) for value in args.status or ()]
    presences = [Presence(value) for value in args.presence or ()]
    tasks = _project(args).list_tasks(statuses, presences, args.kind)
    if args.format == "json":
        _out(reporting.to_json([reporting.task_json(task) for task in tasks]))
    else:
        _out(reporting.task_table(tasks))
    return EXIT_OK


def cmd_show(args: argparse.Namespace) -> int:
    task = _project(args).get_task(args.id)
    _out(reporting.to_json(reporting.task_json(task)) if args.format == "json" else reporting.task_text(task))
    return EXIT_OK


def _print_task_change(args: argparse.Namespace, task: Task, *, changed: bool, what: str) -> None:
    if args.format == "json":
        _out(reporting.to_json({"changed": changed, "task": reporting.task_json(task)}))
    elif changed:
        _out(f"byteplan: [{task.id}] {what}")
    else:
        _out(f"byteplan: [{task.id}] unchanged")


def cmd_status(args: argparse.Namespace) -> int:
    task, changed = _project(args).set_status(args.id, Status(args.status), note=args.note)
    _print_task_change(args, task, changed=changed, what=f"status is now {task.status}")
    return EXIT_OK


def cmd_resolve(args: argparse.Namespace) -> int:
    task, changed = _project(args).set_status(args.id, Status.RESOLVED, note=args.note)
    _print_task_change(args, task, changed=changed, what="resolved")
    if changed and task.presence is Presence.PRESENT and args.format == "text" and task.source:
        _err(
            f"byteplan: note: the annotation at {task.source.path}:{task.source.line} is still in source; "
            "remove it when you're ready (scans report it as a stale annotation until then)"
        )
    return EXIT_OK


def cmd_edit(args: argparse.Namespace) -> int:
    changes: dict[str, Any] = {
        "priority": args.priority,
        "add_labels": args.label or (),
        "remove_labels": args.remove_label or (),
        "notes": args.notes,
        "append_note": args.add_note,
    }
    if args.assignee is not None or args.unassign:
        changes["assignee"] = None if args.unassign else args.assignee
    if args.title is not None or args.clear_title:
        changes["title_override"] = None if args.clear_title else args.title
    task, changed = _project(args).edit_task(args.id, **changes)
    _print_task_change(args, task, changed=changed, what="updated")
    return EXIT_OK


def cmd_missing(args: argparse.Namespace) -> int:
    tasks = _project(args).list_tasks(presences=[Presence.MISSING])
    if args.format == "json":
        _out(reporting.to_json([reporting.task_json(task) for task in tasks]))
    else:
        _out(reporting.task_table(tasks) if tasks else "No missing tasks.")
    return EXIT_OK


def cmd_duplicates(args: argparse.Namespace) -> int:
    project = _project(args)
    duplicates = [d for d in project.scan(dry_run=True).diagnostics if d.code is Code.DUPLICATE_ID]
    if args.format == "json":
        _out(reporting.to_json([d.to_dict() for d in duplicates]))
    elif duplicates:
        _out("\n".join(d.format_text() for d in duplicates))
    else:
        _out("No duplicate IDs.")
    return EXIT_FINDINGS if duplicates else EXIT_OK


def cmd_check(args: argparse.Namespace) -> int:
    project = _project(args)
    report = project.check()
    code = project.exit_code(report.diagnostics)
    counts = Counter(str(d.severity) for d in report.diagnostics)
    if args.format == "json":
        _out(reporting.to_json({"exit_code": code, "diagnostics": [d.to_dict() for d in report.diagnostics]}))
    else:
        _out(
            f"BytePlan check: {report.files_scanned} files · {counts['error']} error(s) · "
            f"{counts['warning']} warning(s) · {counts['info']} info" + (" · FAILED" if code else " · OK")
        )
    for diagnostic in report.diagnostics:
        _err(diagnostic.format_text())
    return code


def cmd_report(args: argparse.Namespace) -> int:
    data = _project(args).report()
    if args.format == "json":
        _out(reporting.to_json(data))
    elif args.format == "markdown":
        sys.stdout.write(reporting.report_markdown(data))
    else:
        _out(reporting.report_text(data))
    return EXIT_OK


def cmd_repair(args: argparse.Namespace) -> int:
    project = _project(args)
    if args.import_id:
        result = project.import_task(args.import_id)
        _out(f"byteplan: imported [{result.task.id}] {result.task.display_title}")
    else:
        path, _, line = args.reassign.rpartition(":")
        if not path or not line.isdigit():
            parser_error = "--reassign takes PATH:LINE, e.g. src/a.py:20"
            raise ConfigError(parser_error)
        # Diagnostics print root-relative locations, so accept those first.
        if (project.root / path).is_file():
            rel = (project.root / path).resolve().relative_to(project.root).as_posix()
        else:
            rel = resolve_targets(project.root, [path])[0]
        result = project.reassign(rel, int(line))
        _out(f"byteplan: {rel}:{line} now has [{result.task.id}] (was duplicate [{result.old_id}])")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--project",
        type=Path,
        default=None,
        metavar="PATH",
        help="project directory (default: nearest directory with pyproject.toml)",
    )
    formatted = argparse.ArgumentParser(add_help=False)
    formatted.add_argument("--format", choices=("text", "json"), default="text")

    parser = argparse.ArgumentParser(prog="byteplan", description="Plan in code. Track in one place.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    init = sub.add_parser("init", parents=[common], help="create configuration and an empty registry")
    init.set_defaults(handler=cmd_init)

    scan = sub.add_parser("scan", parents=[common, formatted], help="discover, annotate, reconcile, report")
    scan.add_argument("paths", nargs="*", help="limit the scan to these files or directories")
    scan.add_argument("--dry-run", action="store_true", help="preview planned changes without writing")
    scan.set_defaults(handler=cmd_scan)

    list_ = sub.add_parser("list", parents=[common, formatted], help="list registry tasks")
    list_.add_argument("--status", action="append", choices=[s.value for s in Status])
    list_.add_argument("--presence", action="append", choices=[p.value for p in Presence])
    list_.add_argument("--kind", action="append", metavar="KIND")
    list_.set_defaults(handler=cmd_list)

    show = sub.add_parser("show", parents=[common, formatted], help="show one task with its history")
    show.add_argument("id", help="four-hex-digit task ID")
    show.set_defaults(handler=cmd_show)

    status = sub.add_parser("status", parents=[common, formatted], help="change a task's lifecycle status")
    status.add_argument("id")
    status.add_argument("status", choices=[s.value for s in Status])
    status.add_argument("--note", help="reason, recorded in the task's history")
    status.set_defaults(handler=cmd_status)

    resolve = sub.add_parser("resolve", parents=[common, formatted], help="mark a task resolved (never edits source)")
    resolve.add_argument("id")
    resolve.add_argument("--note", help="reason, recorded in the task's history")
    resolve.set_defaults(handler=cmd_resolve)

    edit = sub.add_parser("edit", parents=[common, formatted], help="update priority, assignee, labels, notes, title")
    edit.add_argument("id")
    edit.add_argument("--priority")
    assignee = edit.add_mutually_exclusive_group()
    assignee.add_argument("--assignee")
    assignee.add_argument("--unassign", action="store_true")
    edit.add_argument("--label", action="append", metavar="LABEL", help="add a label (repeatable)")
    edit.add_argument("--remove-label", action="append", metavar="LABEL", help="remove a label (repeatable)")
    notes = edit.add_mutually_exclusive_group()
    notes.add_argument("--notes", help="replace the notes")
    notes.add_argument("--add-note", metavar="TEXT", help="append a paragraph to the notes")
    title = edit.add_mutually_exclusive_group()
    title.add_argument("--title", help="display title that scans won't overwrite")
    title.add_argument("--clear-title", action="store_true", help="go back to the title from source")
    edit.set_defaults(handler=cmd_edit)

    missing = sub.add_parser("missing", parents=[common, formatted], help="show tasks no longer found in source")
    missing.set_defaults(handler=cmd_missing)

    duplicates = sub.add_parser("duplicates", parents=[common, formatted], help="report duplicate embedded IDs")
    duplicates.set_defaults(handler=cmd_duplicates)

    check = sub.add_parser("check", parents=[common, formatted], help="read-only validation for CI")
    check.set_defaults(handler=cmd_check)

    report = sub.add_parser("report", parents=[common], help="summarize tasks and findings")
    report.add_argument("--format", choices=("text", "json", "markdown"), default="text")
    report.set_defaults(handler=cmd_report)

    repair = sub.add_parser("repair", parents=[common], help="explicitly fix states scans won't guess about")
    action = repair.add_mutually_exclusive_group(required=True)
    action.add_argument("--import", dest="import_id", metavar="ID", help="register an ID found in source")
    action.add_argument("--reassign", metavar="PATH:LINE", help="give a duplicate ID copy a fresh ID")
    repair.set_defaults(handler=cmd_repair)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return EXIT_OK
    try:
        result: int = args.handler(args)
    except ByteplanError as exc:
        _err(f"byteplan: error: {exc}")
        return EXIT_ERROR
    return result


if __name__ == "__main__":
    raise SystemExit(main())
