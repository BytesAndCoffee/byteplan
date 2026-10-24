# RC1 source safety and first-run audit

This report supplies the acceptance map for BytePlan task `1b81` (Addendum E A5).
The audit starts at `8e829805d2e950d31c1e2a6c746aa215ea143dc6`; the regression cases
below extend that revision. It evaluates existing workflows rather than introducing commands.
The final integrated revision still needs the release-wide platform checks and independent
whole-repository reviews.

## First use in an existing repository

1. Inspect `git status` and retain a recoverable copy of existing work. Run `byteplan init` to
   create the registry/configuration; initialization is a write operation. A requested runtime
   shim is also a write. Existing incompatible registry metadata is validated before the new
   implementation writes a shim.
2. Review `[tool.byteplan]` include/exclude patterns, `.gitignore`, annotation mode and optional
   post-scan automation. Default scope is Python; Markdown/JSON/JSONC require configured
   inclusion. Symlink files/directories are excluded, and targets outside the project are refused.
3. Run `byteplan scan --dry-run` or `byteplan check`. Both leave project files unchanged and
   statically inspect source without importing repository modules. Text preview lists proposed
   IDs, annotation kinds, locations and titles; JSON gives structured proposals and diagnostics.
   The Python API additionally exposes planned source bytes on `ScanReport.planned`.
4. Narrow an initial preview with `byteplan scan PATH --dry-run` when useful. Narrowed scans
   deliberately do not mark unexamined tasks missing. If detected stubs are unwanted, configure
   detection/suppression or annotation `mode = "preserve"` before applying. Preserve mode still
   supports IDs on authored task comments; it reports unowned stubs without inserting their
   annotations.
5. Run the writing `byteplan scan` only after reviewing the proposed scope, then inspect the Git
   diff. Commit the changed source together with registry/evidence changes. Use `byteplan check
   --staged` before committing and `byteplan check --commit HEAD` to validate the resulting
   snapshot. Working-tree `check` uses configurable policy; enable `require_reconciled = true`
   for the strict source/registry consistency policy also applied to index/commit checks.

**Preview boundary:** scan previews cover discovery, ID annotation and registry reconciliation.
Writing scans can subsequently run configured automatic test scaffolding and archiving as
separate operations. Those additional file changes are not enumerated by a scan dry-run's
planned-file list. Auto-scaffolding defaults off; automatic archiving defaults on and only
selects eligible closed tasks whose annotations are gone (with committed-record checks in Git).
For separately reviewable operations, set `[tool.byteplan.tests.scaffold] auto = false` and
`[tool.byteplan.archive] auto = false`, then use `byteplan tests scaffold ID --dry-run` and
`byteplan archive --dry-run` explicitly. After an actual scan, its report lists scaffolded
tests, scaffold failures and archived IDs. Do not interpret one scan preview as a transaction
plan for every optional post-scan operation.

The preview describes the source/configuration it read. It is not an apply token: later edits
require a fresh plan. Writing commands re-read and validate hashes before applying their own
plan, refusing conflicting edits instead of applying a stale preview.

## Operations and mutation contract

| Operation | Default and explicit mutation behavior |
|---|---|
| `scan --dry-run`, `check`, list/report, active-task show and snapshot checks | Read-only; no source edits, test execution, source imports or journal recovery. A pending ordinary transaction produces a diagnostic where scanning occurs. Invalid inputs can produce errors while remaining unchanged. |
| Archived-task lookup/show | Leaves source and authoritative JSON unchanged, but may lazily recover records from Git into the gitignored local SQLite store. Reading that store can migrate its old local schema. This is cache maintenance, not a completely write-free file operation; see the archive recovery contract in the storage report. |
| Python snapshot projects | `scan`/`check`, active registry queries, reports, verification readiness and runtime/version metadata queries use selected index/commit blobs. Mutation, test execution, source-operation previews, archive operations/previews and archived-record lookup reject the snapshot with working-tree guidance before side effects. HEAD freshness uses the selected commit; index snapshots conservatively report HEAD freshness as uncertain. |
| CLI `scan` / Python `Project.scan(dry_run=False)` | Adds IDs and, in comment mode, detected-stub comments; reconciles the registry. Configured scaffold/archive follow-ups may write further files. Python `Project.scan()` defaults to preview. |
| `sync` and cleanup | Preview by default. `sync --apply` makes the supported decorator/cleanup changes. Runtime imports/decorators are deliberate changes validated against the allowed AST transformation; comment-only edits preserve the Python AST. Unsafe placements and ambiguous bindings remain unchanged with diagnostics. |
| `resolve` / `dismiss` | Registry lifecycle mutation; source cleanup only with the explicit supported sync-source option. Annotation disappearance never resolves tasks. |
| `repair --reassign` | Explicit writing action with a `--dry-run` preview. Cross-branch repair additionally pins Git commits, checks lineage, holds the index lock and rejects pending Git operations/journals. See the compatibility report for supported reference scope. |
| `tests scaffold` | Explicit source write with `--dry-run` support. Existing linked tests are reused by default; forcing another test requires the documented option. |
| `verify` | Explicit test execution and evidence mutation. Tests themselves may have side effects; verification is not a read-only operation. |
| `migrate`, `archive`, `release`, `restore` | Explicit mutation, each with preview support. Release stripping/restoration preserves supported source structure and keeps a recovery record. Optional release smoke testing builds, installs and imports code only when requested. |
| Installed direct Git hook | Default mode reconciles the staged snapshot, updating index and working tree; it refuses partial staging and unstaged registry changes. `--mode check` validates only; `--mode scan` previews. `on_reconcile = "stop"` allows review after edits before retrying the commit. |
| Pre-commit framework reconcile hook | Formatter-style working-tree fixer: leaves the index unchanged, stops after edits and asks the developer to stage/retry. The check hook is read-only. |
| Hatch integration | BytePlan checks are read-only by default. Source writes require `write_source`; CI refuses them unless explicitly allowed. A tree already stripped for release is checked without reannotation. Building itself may execute the selected build backend; the BytePlan check does not import project modules. |
| MCP | Default tools cannot mutate source or authoritative task state. Archived-task lookup has the same local-cache maintenance exception as the Python API. Source-writing operations require server permission and their documented apply flag; previews remain the default where provided. Test execution has its own permission. |

## Acceptance-to-test map

The named tests are real assertions, not scaffold placeholders. Existing coverage is reused;
the audit adds only the first-run scale and interrupted-state read-only cases.

| Acceptance area | Concrete evidence |
|---|---|
| Larger first scan, understandable preview, deterministic allocations and static inspection | New `test_rc1_source_safety.py::test_large_first_scan_previews_source_then_applies_idempotently`: 256 modules, 512 tasks, a module body that would raise if imported, exact proposed source bytes, six-character unique IDs, unchanged preview snapshot, full AST/BOM/CRLF checks and strictly write-free second scan. `test_cli.py::test_scan_text_and_dry_run_do_not_write` and `test_scan_json_stdout_is_pure_json` cover human/machine reporting. |
| Read-only behavior even after interruption | New `test_rc1_source_safety.py::test_read_only_operations_leave_pending_recovery_untouched`: scan/check/report/cleanup/sync/migrate/archive previews preserve the complete file snapshot, staged transaction bytes and pending journal; a subsequent writing scan completes recovery and is then idempotent. `test_mcp.py::test_read_only_tools_change_nothing` covers actual MCP clients. |
| Read-only Python snapshot API | `test_snapshot_api.py::test_snapshot_mutations_fail_before_any_execution_or_recovery` and `test_source_and_archive_previews_refuse_mixed_snapshot_working_tree_state` cover index/commit guards. Registry queries, readiness/evidence/fingerprints, head-mode uncertainty and runtime/static/dynamic version metadata have selected-blob regressions in the same file. |
| Encoding, BOM, CRLF, missing final newline, Unicode, tabs and permissions | `test_source.py::test_decode_round_trips_exact_bytes`, `test_write.py::test_annotation_changes_only_the_id`, `test_permissions_are_preserved`, `test_normalize.py::test_byte_level_safety`, `test_cleanup.py::test_crlf_and_bom_survive`, and `test_formats.py::test_annotation_changes_only_the_id`. |
| Python syntax and AST integrity | `test_edits.py::test_equivalence_refuses_code_changes` / `test_equivalence_refuses_unparseable_result`; `test_normalize.py::test_equivalence_guard_rejects_real_changes` / `test_rewritten_module_behaves_identically`; first-run test above compares complete before/after ASTs. |
| Stub safety and scope | `test_stubs.py::test_unsafe_stubs_are_reported_not_annotated`, `test_non_comment_modes_report_stubs_instead_of_annotating` in `test_normalize.py`, `test_files.py::test_symlinks_are_not_followed` / `test_resolve_targets_rejects_paths_outside_root`, `test_write.py::test_narrowed_scan_never_marks_other_tasks_missing`. |
| Writing failures preserve valid work | `test_write.py::test_failed_scan_writes_nothing` / `test_duplicate_ids_block_all_writes`; `test_persistence.py::test_concurrent_edit_between_plan_and_commit` / `test_edit_after_journal_is_written_is_not_overwritten`; `test_compatibility.py::test_init_rejects_future_schema_before_writing_any_source`. |
| Durability and recoverability | `test_persistence.py::test_crash_mid_commit_rolls_forward`, `test_crash_before_journal_leaves_files_untouched`, `test_journal_conflict_is_not_overwritten`, `test_target_directories_are_fsynced_before_the_journal_is_removed`; `test_cleanup.py::test_crash_recovers_through_the_journal`; `test_collision_recovery.py::test_interrupted_rekey_recovers_all_source_evidence_and_registry`. |
| Git hook and snapshot behavior | `test_git_snapshot.py::test_clean_staged_project_passes_and_changes_nothing`, `test_judges_staged_blobs_not_the_working_tree`, `test_check_mode_hook_blocks_an_unreconciled_commit`; `test_staged_apply.py::test_partially_staged_file_is_refused`, `test_unstaged_registry_edits_are_refused`, `test_pre_commit_framework_mode_is_a_working_tree_fixer`, `test_crlf_files_with_autocrlf`, `test_apply_is_idempotent`, `test_crash_recovers_forward`, and `test_rollback_never_overwrites_an_edit_to_a_file_byteplan_wrote`. |
| Build and agent source permissions | `test_hatch_hook.py::test_default_build_is_read_only`, `test_ci_refuses_writes`, `test_editable_mode_does_not_write_on_release_builds`; `test_mcp.py::test_source_writes_need_permission_and_apply`, `test_scaffold_release_and_restore_preview_unless_applied`, `test_resolve_with_sync_source_previews_unless_applied`. |
| Release and restoration | `test_release.py::test_release_then_restore_is_byte_identical`, `test_refusals_write_nothing`, `test_release_refuses_a_pending_journal_without_recovering_it`, `test_crash_mid_release_rolls_forward`; `test_release_guards.py::test_import_failure_restores_the_tree`. |

## Recovery and limits

Ordinary writes hold the project lock, stage and fsync contents, persist a hash journal, and
replace files with the registry last. A crash after the journal is durable may leave some
files updated. Read-only commands do not conceal that state by recovering it. A subsequent
writing command rolls forward; if a file differs from both before/after hashes, recovery stops
with actionable diagnostics and retains the journal. Preserve it and the competing source work
while resolving that conflict. Staged reconciliation has a separate journal and can roll
forward or backward according to its recorded index/worktree state; ordinary writes refuse
to operate over a pending staged reconciliation.

These guarantees are not a filesystem-wide atomic transaction or distributed lock. A narrow
race between checking a file's hash and replacing it remains because portable filesystem
compare-and-swap replacement is unavailable. Directory fsync is used on supported POSIX
systems; Windows lacks the same directory-handle fsync mechanism. Optional scan follow-ups are
separate transactions and may fail after the annotation transaction succeeds; their reports
must be inspected. These boundaries are documented limitations, not claims that every failing
writing command leaves the entire repository byte-identical.

Task `c35e66` records a confirmed Python API safety defect: a supposedly read-only snapshot
project could mutate the working-tree registry, and verification could execute tests before
reaching a write guard. Some query methods also combined selected metadata with live files.
The snapshot guards and selected-blob query regressions address this defect without enabling
source/archive operations on historical snapshots. The existing preview and permission
mechanisms meet the reviewed A5 workflow requirements with the explicit boundaries above.
Final task resolution requires recorded linked verification and review of this acceptance map;
green CI or this document alone does not resolve the task.

## Audit validation

Linux/Python 3.12 validation in the fresh checkout passed **326 tests** across source decoding,
edits, writing scans, normalization, cleanup, persistence, staged reconciliation, Git snapshots,
MCP, supported formats, stubs, file scope, collision recovery and the eight new audit cases.
The new file also passes strict mypy and Hatch's full Ruff lint/format checks. A separate run
in the Hatch test environment (including its build dependencies) passed **103 tests** for the
Hatch hook, release and release guards; its one network-marked case was deselected. The runs use an absolute
`PYTHONPATH` to this checkout so subprocesses launched from temporary project directories do
not fall back to an older editable installation. These are focused working-tree results;
the integrated commit still requires the full suite, final artifact validation and cross-platform
CI before a release-readiness claim.
