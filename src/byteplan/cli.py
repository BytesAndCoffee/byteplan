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
from pathlib import Path
from typing import TYPE_CHECKING

from byteplan import reporting
from byteplan.__about__ import __version__
from byteplan.api import Project, init_project
from byteplan.diagnostics import EXIT_ERROR, EXIT_FINDINGS, EXIT_OK
from byteplan.errors import ByteplanError
from byteplan.models import Presence, Status

if TYPE_CHECKING:
    from collections.abc import Sequence

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
    report = project.scan(args.paths or None)
    if not args.dry_run:
        _err("byteplan: writing annotations and registry updates is not available yet; ran as --dry-run")
    if args.format == "json":
        _out(reporting.to_json(reporting.scan_json(report, dry_run=True)))
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
