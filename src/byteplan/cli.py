# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
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
from byteplan.gitio import hooks_status, install_hooks, install_merge_driver, merge_driver_main
from byteplan.gitwrite import reconcile_staged
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
    result = init_project(args.project, runtime_shim=args.runtime_shim)
    for action in result.actions:
        _out(f"byteplan: {action}")
    if not result.actions:
        _out(f"byteplan: already initialized in {result.root}")
    for warning in result.warnings:
        _err(f"byteplan: warning: {warning}")
    return EXIT_OK


def cmd_sync(args: argparse.Namespace) -> int:
    project = _project(args)
    settings = project.config.annotations
    remove = args.remove_resolved or settings.remove_resolved
    normalizing = settings.mode == "decorator" and (settings.convert_attached_comments or settings.auto_decorate_stubs)
    code = EXIT_OK
    payload: dict[str, Any] = {}
    # Always the original top-level shape; `sync` returns at once when normalization is off.
    report = project.sync(args.only, dry_run=not args.apply)
    payload.update(reporting.sync_json(report))
    if normalizing or not remove:
        if args.format == "text" and not (remove and report.blocked and report.blocked.startswith("nothing to do")):
            _out(reporting.sync_text(report))
        for diagnostic in report.diagnostics:
            _err(diagnostic.format_text())
        if report.blocked and not report.blocked.startswith("nothing to do"):
            code = EXIT_FINDINGS
    if remove:
        cleaned = project.cleanup(args.only, dry_run=not args.apply, suppress_stubs=args.suppress_stubs)
        payload["cleanup"] = reporting.cleanup_json(cleaned)
        if args.format == "text":
            _out(reporting.cleanup_text(cleaned))
        for diagnostic in cleaned.diagnostics:
            _err(diagnostic.format_text())
        if cleaned.blocked or any(d.code is Code.RESOLVED_BUT_STUBBED for d in cleaned.diagnostics):
            code = EXIT_FINDINGS
    if args.format == "json":
        _out(reporting.to_json(payload))
    return code


def _snapshot_project(args: argparse.Namespace) -> Project:
    """The working tree, or a read-only Git snapshot for --staged / --commit."""
    if getattr(args, "staged", False):
        return Project.open_snapshot(args.project)
    if getattr(args, "commit", None):
        return Project.open_snapshot(args.project, rev=args.commit)
    return _project(args)


def cmd_scan(args: argparse.Namespace) -> int:
    if args.apply and not args.staged:
        msg = "--apply is for --staged; a plain `byteplan scan` already writes"
        raise ConfigError(msg)
    if args.staged and args.apply == args.dry_run:
        msg = "`scan --staged` needs exactly one of --dry-run (preview) or --apply (reconcile the commit)"
        raise ConfigError(msg)
    if args.apply:
        if args.paths:
            msg = "`scan --staged --apply` reconciles the whole staged snapshot; it doesn't take paths"
            raise ConfigError(msg)
        outcome = reconcile_staged(args.project)
        if args.format == "json":
            _out(
                reporting.to_json(
                    {"exit_code": outcome.code, "annotated": outcome.annotated, "messages": outcome.messages}
                )
            )
        else:
            for line in outcome.messages:
                _out(line)
        return outcome.code
    project = _snapshot_project(args)
    try:
        report = project.scan(args.paths or None, dry_run=args.dry_run)
    finally:
        project.close()
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


def cmd_tests_list(args: argparse.Namespace) -> int:
    project = _project(args)
    tasks = [project.get_task(args.id)] if args.id else [t for _, t in sorted(project.load_registry().tasks.items())]
    if args.format == "json":
        _out(reporting.to_json(reporting.tests_json(tasks)))
    else:
        _out(reporting.tests_text(tasks))
    return EXIT_OK


def cmd_tests_add(args: argparse.Namespace) -> int:
    task, changed = _project(args).link_tests(args.id, args.nodes)
    _print_task_change(args, task, changed=changed, what=f"linked {', '.join(args.nodes)}")
    return EXIT_OK


def cmd_tests_remove(args: argparse.Namespace) -> int:
    task, changed = _project(args).unlink_tests(args.id, args.nodes)
    _print_task_change(args, task, changed=changed, what=f"unlinked {', '.join(args.nodes)}")
    return EXIT_OK


def cmd_tests_scaffold(args: argparse.Namespace) -> int:
    result = _project(args).scaffold_test(
        args.id,
        path=args.path,
        name=args.name,
        policy=args.policy,
        link_style=args.link,
        force_new=args.force_new,
        dry_run=args.dry_run,
    )
    if args.format == "json":
        _out(
            reporting.to_json(
                {
                    "id": result.task.id,
                    "node": result.node,
                    "path": result.path,
                    "created_file": result.created_file,
                    "existing": list(result.existing),
                    "dry_run": result.dry_run,
                    "written": list(result.written),
                }
            )
        )
    elif result.existing:
        _out(f"byteplan: [{result.task.id}] already has linked tests; nothing written:")
        for node in result.existing:
            _out(f"  {node}")
        _out("  (use --force-new to add another)")
    elif result.dry_run:
        _out(f"byteplan: would {'create' if result.created_file else 'append to'} {result.path}: {result.node}")
        _out(result.text)
    else:
        _out(
            f"byteplan: [{result.task.id}] scaffolded {result.node} ({'new file' if result.created_file else 'appended'})"
        )
        _out("  it fails until you write the real test; `byteplan verify` won't count it as evidence until then")
    return EXIT_OK


def cmd_show(args: argparse.Namespace) -> int:
    project = _project(args)
    task = project.get_task(args.id)
    state = project.readiness(task)
    if args.format == "json":
        _out(
            reporting.to_json(
                {**reporting.task_json(task), "readiness": state.state, "readiness_reasons": list(state.reasons)}
            )
        )
    else:
        _out(reporting.task_text(task, state))
    return EXIT_OK


def cmd_verify(args: argparse.Namespace) -> int:
    project = _project(args)
    if args.ready:
        found = project.ready()
        if args.format == "json":
            _out(reporting.to_json([{"id": t.id, "title": t.display_title} for t, _ in found]))
        else:
            _out(reporting.ready_text(found))
        return EXIT_OK
    report = project.verify(args.ids)
    _out(reporting.to_json(reporting.verify_json(report)) if args.format == "json" else reporting.verify_text(report))
    return EXIT_FINDINGS if report.failed else EXIT_OK


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


def cmd_release(args: argparse.Namespace) -> int:
    report = _project(args).release(
        args.version,
        dry_run=args.dry_run,
        allow_dirty=args.allow_dirty,
        smoke_test=args.smoke_test,
        offline=args.offline,
    )
    if args.format == "json":
        _out(
            reporting.to_json(
                {
                    "version": report.version,
                    "files": list(report.files),
                    "decorators": report.decorators,
                    "imports": report.imports,
                    "tasks": list(report.tasks),
                    "dry_run": report.dry_run,
                    "written": list(report.written),
                    "smoke_test": report.smoke_test,
                    "smoke_imports": list(report.smoke_imports),
                    "warnings": [w.to_dict() for w in report.warnings],
                }
            )
        )
    else:
        verb = "would strip" if report.dry_run else "stripped"
        _out(
            f"byteplan: {verb} {report.decorators} decorator(s) and {report.imports} import(s) "
            f"from {len(report.files)} file(s) for release {report.version}"
        )
        if report.tasks:
            _out(f"byteplan: {len(report.tasks)} task(s) marked stripped (on record, never missing)")
        if report.smoke_test == "passed":
            _out(
                f"byteplan: smoke test passed: the wheel imports ({', '.join(report.smoke_imports)}) without byteplan_runtime"
            )
        if not report.dry_run:
            _out("byteplan: next: review `git diff`, commit, tag, build; `byteplan restore` puts them back")
    for warning in report.warnings:
        _err(warning.format_text())
    return EXIT_OK


def cmd_restore(args: argparse.Namespace) -> int:
    report = _project(args).restore(dry_run=args.dry_run, partial=args.partial)
    if args.format == "json":
        _out(
            reporting.to_json(
                {
                    "files": list(report.files),
                    "decorators": report.decorators,
                    "imports": report.imports,
                    "tasks": list(report.tasks),
                    "conflicts": list(report.conflicts),
                    "partial": report.partial,
                    "dry_run": report.dry_run,
                    "written": list(report.written),
                }
            )
        )
    else:
        verb = "would restore" if report.dry_run else "restored"
        _out(
            f"byteplan: {verb} {report.decorators} decorator(s) and {report.imports} import(s) in {len(report.files)} file(s)"
        )
        for conflict in report.conflicts:
            _err(f"byteplan: restore_conflict: {conflict}")
        if report.partial:
            _out("byteplan: the entries above stay on record; fix them and run `byteplan restore` again")
    return EXIT_FINDINGS if report.partial else EXIT_OK


def cmd_resolve(args: argparse.Namespace) -> int:
    project = _project(args)
    task, changed = project.set_status(args.id, Status.RESOLVED, note=args.note)
    _print_task_change(args, task, changed=changed, what="resolved")
    if args.sync_source:
        cleaned = project.cleanup([task.id], dry_run=False, suppress_stubs=args.suppress_stubs)
        if args.format == "text":
            _out(reporting.cleanup_text(cleaned))
        for diagnostic in cleaned.diagnostics:
            _err(diagnostic.format_text())
        return (
            EXIT_OK if cleaned.removed or cleaned.suppressed or task.presence is not Presence.PRESENT else EXIT_FINDINGS
        )
    if changed and task.presence is Presence.PRESENT and args.format == "text" and task.source:
        _err(
            f"byteplan: note: the annotation at {task.source.path}:{task.source.line} is still in source; "
            f"`byteplan resolve {task.id} --sync-source` or `byteplan sync --remove-resolved --apply` removes it"
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
    project = _snapshot_project(args)
    try:
        report = project.check()
    finally:
        project.close()
    code = project.exit_code(report.diagnostics)
    where = f" ({project.snapshot.label})" if project.snapshot is not None else ""
    counts = Counter(str(d.severity) for d in report.diagnostics)
    if args.format == "json":
        snapshot = None if project.snapshot is None else project.snapshot.label
        payload = {"exit_code": code, "snapshot": snapshot, "diagnostics": [d.to_dict() for d in report.diagnostics]}
        _out(reporting.to_json(payload))
    else:
        _out(
            f"BytePlan check{where}: {report.files_scanned} files · {counts['error']} error(s) · "
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


def cmd_merge_registry(args: argparse.Namespace) -> int:
    return merge_driver_main(args.base, args.ours, args.theirs, args.label)


def cmd_git_install_hooks(args: argparse.Namespace) -> int:
    actions = install_hooks(_project(args), args.mode)
    for action in actions or ["pre-commit hook already installed"]:
        _out(f"byteplan: {action}")
    return EXIT_OK


def cmd_git_hooks_status(args: argparse.Namespace) -> int:
    status = hooks_status(_project(args))
    if args.format == "json":
        _out(reporting.to_json(status.to_dict()))
    else:
        _out(f"pre-commit framework (byteplan-check): {'yes' if status.pre_commit_framework else 'no'}")
        _out(f"direct pre-commit hook: {status.direct_hook} ({status.direct_hook_path})")
        _out(f"registry merge driver: {'installed' if status.merge_driver else 'not installed'}")
    return EXIT_OK


def cmd_git_install_merge_driver(args: argparse.Namespace) -> int:
    actions = install_merge_driver(_project(args))
    for action in actions or ["merge driver already installed"]:
        _out(f"byteplan: {action}")
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
    init.add_argument(
        "--runtime-shim",
        metavar="PATH",
        help="also write an inert todo/verifies module at PATH (instead of depending on byteplan-runtime)",
    )
    init.set_defaults(handler=cmd_init)

    sync = sub.add_parser(
        "sync",
        parents=[common, formatted],
        help="source rewrites: @todo normalization (decorator mode) and --remove-resolved cleanup",
    )
    mode = sync.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="preview the rewrites (the default)")
    mode.add_argument("--apply", action="store_true", help="write the rewrites and update the registry")
    sync.add_argument("--only", action="append", metavar="ID", help="only these task IDs (repeatable)")
    sync.add_argument(
        "--remove-resolved",
        action="store_true",
        help="remove the source annotations of resolved and dismissed tasks (or set remove_resolved)",
    )
    sync.add_argument(
        "--suppress-stubs",
        action="store_true",
        help="for a closed task whose code is still a stub, leave `# byteplan: ignore` instead of refusing",
    )
    sync.set_defaults(handler=cmd_sync)

    scan = sub.add_parser("scan", parents=[common, formatted], help="discover, annotate, reconcile, report")
    scan.add_argument("paths", nargs="*", help="limit the scan to these files or directories")
    scan.add_argument("--dry-run", action="store_true", help="preview planned changes without writing")
    scan.add_argument("--staged", action="store_true", help="scan the Git index instead (with --dry-run or --apply)")
    scan.add_argument(
        "--apply",
        action="store_true",
        help="with --staged: add IDs to the staged commit (index and working tree) before it's finalized",
    )
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

    release = sub.add_parser(
        "release",
        parents=[common, formatted],
        help="strip BytePlan's decorators and runtime imports in place for a release (no git or build)",
    )
    release.add_argument("--version", help="the release version (default: the project's)")
    release.add_argument("--dry-run", action="store_true", help="show what would be stripped")
    release.add_argument("--allow-dirty", action="store_true", help="strip even with uncommitted changes")
    release.add_argument(
        "--smoke-test",
        action="store_true",
        help="also build the stripped wheel, install it in isolation and import it (restores on failure)",
    )
    release.add_argument(
        "--offline", action="store_true", help="smoke test without a package index ([tool.byteplan.release] find_links)"
    )
    release.set_defaults(handler=cmd_release)

    restore = sub.add_parser("restore", parents=[common, formatted], help="put back what `byteplan release` stripped")
    restore.add_argument("--dry-run", action="store_true", help="show what would be restored")
    restore.add_argument(
        "--partial", action="store_true", help="restore what can be placed; keep conflicting entries on record"
    )
    restore.set_defaults(handler=cmd_restore)

    resolve = sub.add_parser(
        "resolve", parents=[common, formatted], help="mark a task resolved (edits source only with --sync-source)"
    )
    resolve.add_argument("id")
    resolve.add_argument("--note", help="reason, recorded in the task's history")
    resolve.add_argument("--sync-source", action="store_true", help="also remove the task's annotation from source")
    resolve.add_argument(
        "--suppress-stubs",
        action="store_true",
        help="with --sync-source: on a still-stub declaration, leave `# byteplan: ignore`",
    )
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

    check = sub.add_parser("check", parents=[common, formatted], help="read-only validation for CI and hooks")
    snapshot = check.add_mutually_exclusive_group()
    snapshot.add_argument("--staged", action="store_true", help="check exactly what's staged (pre-commit)")
    snapshot.add_argument("--commit", metavar="REV", help="check a commit, e.g. HEAD (CI)")
    check.set_defaults(handler=cmd_check)

    report = sub.add_parser("report", parents=[common], help="summarize tasks and findings")
    report.add_argument("--format", choices=("text", "json", "markdown"), default="text")
    report.set_defaults(handler=cmd_report)

    repair = sub.add_parser("repair", parents=[common], help="explicitly fix states scans won't guess about")
    action = repair.add_mutually_exclusive_group(required=True)
    action.add_argument("--import", dest="import_id", metavar="ID", help="register an ID found in source")
    action.add_argument("--reassign", metavar="PATH:LINE", help="give a duplicate ID copy a fresh ID")
    repair.set_defaults(handler=cmd_repair)

    merge = sub.add_parser(
        "merge-registry",
        help="Git merge driver for the registry (set up by `byteplan git install-merge-driver`)",
    )
    merge.add_argument("base", help="%%O: the common ancestor version")
    merge.add_argument("ours", help="%%A: our version; the result is written here")
    merge.add_argument("theirs", help="%%B: their version")
    merge.add_argument("label", nargs="?", help="%%P: the registry's path, for messages")
    merge.set_defaults(handler=cmd_merge_registry)

    verify = sub.add_parser(
        "verify", parents=[common, formatted], help="run linked tests with pytest and record the evidence"
    )
    verify.add_argument("ids", nargs="*", metavar="ID", help="only these tasks (default: every open task with tests)")
    verify.add_argument("--ready", action="store_true", help="list tasks ready for review; runs nothing")
    verify.set_defaults(handler=cmd_verify)

    tests_cmd = sub.add_parser("tests", help="acceptance tests linked to tasks")
    tests_sub = tests_cmd.add_subparsers(dest="tests_command", metavar="COMMAND", required=True)
    tests_list = tests_sub.add_parser(
        "list", parents=[common, formatted], help="show linked tests and their provenance"
    )
    tests_list.add_argument("id", nargs="?", help="only this task")
    tests_list.set_defaults(handler=cmd_tests_list)
    tests_add = tests_sub.add_parser("add", parents=[common, formatted], help="link pytest node IDs to a task")
    tests_add.add_argument("id")
    tests_add.add_argument("nodes", nargs="+", metavar="NODE", help="e.g. tests/test_routing.py::test_poison")
    tests_add.set_defaults(handler=cmd_tests_add)
    tests_remove = tests_sub.add_parser("remove", parents=[common, formatted], help="unlink tests added with `add`")
    tests_remove.add_argument("id")
    tests_remove.add_argument("nodes", nargs="+", metavar="NODE")
    tests_remove.set_defaults(handler=cmd_tests_remove)
    tests_scaffold = tests_sub.add_parser(
        "scaffold", parents=[common, formatted], help="write a deliberately failing acceptance test for a task"
    )
    tests_scaffold.add_argument("id")
    tests_scaffold.add_argument(
        "--path", help="test file to create or append to (default from [tool.byteplan.tests.scaffold])"
    )
    tests_scaffold.add_argument("--name", help="test function name (a test_* identifier)")
    tests_scaffold.add_argument(
        "--policy", choices=("fail", "xfail", "skip"), help="how the placeholder fails (default fail)"
    )
    tests_scaffold.add_argument("--link", choices=("verifies", "marker", "managed"), help="how the test is linked")
    tests_scaffold.add_argument("--force-new", action="store_true", help="add a test even if the task has linked tests")
    tests_scaffold.add_argument("--dry-run", action="store_true", help="show the test without writing it")
    tests_scaffold.set_defaults(handler=cmd_tests_scaffold)

    git_cmd = sub.add_parser("git", help="Git integration")
    git_sub = git_cmd.add_subparsers(dest="git_command", metavar="COMMAND", required=True)
    install = git_sub.add_parser(
        "install-merge-driver",
        parents=[common],
        help="merge the registry by task ID instead of as text (per clone; commits a .gitattributes line)",
    )
    install.set_defaults(handler=cmd_git_install_merge_driver)
    hooks = git_sub.add_parser(
        "install-hooks", parents=[common], help="install a direct pre-commit hook (never replaces a foreign one)"
    )
    hooks.add_argument(
        "--mode",
        choices=("reconcile", "check", "scan"),
        default="reconcile",
        help="reconcile: add IDs at commit time (default); check: validate only; scan: preview only",
    )
    hooks.set_defaults(handler=cmd_git_install_hooks)
    status = git_sub.add_parser("hooks-status", parents=[common, formatted], help="show installed Git integration")
    status.set_defaults(handler=cmd_git_hooks_status)
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
