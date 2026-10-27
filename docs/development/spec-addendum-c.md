# BytePlan — Addendum C: Git Lifecycle Integration

**Audience:** Claude Code implementing `BytesAndCoffee/byteplan`  
**Status:** Proposed additive specification  
**Dependencies:** `docs/spec.md`, `docs/spec-addendum-a.md`, `docs/spec-addendum-b.md`, and `docs/IMPLEMENTATION_PLAN.md`  
**Guiding principle:** *The committed backlog must describe the committed code, not an unrelated working-tree snapshot.*

## C1. Objective

Provide first-class Git integration so developers naturally synchronize and validate BytePlan at **build, commit, and merge** time, without maintaining a second workflow.

- **Hatch build:** Optional development-time discovery and reconciliation; release builds remain reproducible and read-only by default.
- **Git pre-commit:** Validate that staged annotations and staged registry are internally consistent; optionally offer safe automated reconciliation.
- **CI:** Apply the same validation to a checked-out commit or pull request and provide machine-readable findings.

Git integration is an adapter around the existing `api.Project` discovery, reconciliation, reporting, and persistence engines. Do not fork or duplicate semantic rules for each integration.

## C2. Core invariants

1. The **Git index (staging area)** is authoritative during `--staged` operations. A working-tree file may contain additional changes that must never enter the commit inadvertently.
2. Read-only staged checks never write to the index, working tree, registry, Git configuration, or `.git` metadata.
3. A write-enabled staged scan must never silently stage previously unstaged user edits, discard changes, or rewrite another tool's concurrent modifications.
4. Task identity, reserved IDs, statuses, provenance, and histories follow the existing BytePlan contract. Missing annotations are never automatically resolved.
5. Only a **complete, authoritative scan of the selected snapshot** may mark tracked tasks missing. A `--staged` file subset is not authoritative for the rest of the project.
6. Checks must distinguish a new untracked annotation from an intentionally stripped release decorator (`presence="stripped"`) and from a resolved task whose annotation has been deliberately cleaned up.
7. All user-facing operations remain deterministic. Two checks of the same index produce identical findings; a successful no-op scan creates no new registry events.
8. Local hooks can be skipped; CI is the authoritative enforcement point for teams that enable policy gates.
9. Never run pytest, application imports, MCP actions, or remote issue-sync as a side effect of a pre-commit check.
10. All mutating Git operations must be opt-in, explain their planned changes, and fail closed when the index or worktree has changed mid-operation.

## C3. Commands and semantics

Introduce:

```console
byteplan check --staged [--format text|json]
byteplan scan --staged --dry-run [--format text|json]
byteplan scan --staged --apply [--format text|json]  # explicitly opt-in
byteplan git install-hooks [--mode check|scan]      # optional convenience
byteplan git hooks-status
```

`check --staged` is the preferred pre-commit entry point. The existing `check` command (once available) continues to validate the configured full working tree. `scan --staged --dry-run` produces a preview of changes needed for the staged snapshot, including suggested ID insertions and registry updates, without writing.

### Staged check policy

- Read the staged `pyproject.toml` configuration if present; clearly report when an unstaged configuration differs. Do not silently use an incompatible hybrid of staged and working-tree config.
- Enumerate staged paths using `git ls-files --stage -z` (or equivalent plumbing). Read staged content from Git objects (e.g. `git cat-file blob <oid>`), not from working-tree paths.
- Handle additions, modifications, renames, deletions, and filenames with spaces, newlines, or non-ASCII characters.
- Reconstruct the selected project's **full staged snapshot** (within configured scope) for authoritative missing detection; do not equate `git diff --cached --name-only` with a complete scan.
- Read the staged `.byteplan/tasks.json`, not the working-tree registry. The index may contain an older registry version or an intentionally staged update.
- If the registry or configuration is absent from the index, emit an explicit diagnostic and documented policy outcome; do not substitute a working-tree copy without telling the developer.
- Resolve renamed files by persistent task ID. A changed line number alone does not imply a new task.
- Detect new TODOs and inferred stubs under the existing discovery policy, IDs absent from staged registry, duplicate IDs, malformed IDs, unexpected missing tasks, stale annotations, and staged-release inconsistencies.
- If a developer stages only code but not the updated registry, fail with an actionable `registry_not_staged` / `staged_registry_out_of_sync` diagnostic.
- If source or registry edits are required, report them and use exit code **1** for policy findings; retain the existing **0** success and **2** runtime/config errors conventions.

**Important:** `check --staged` must be usable even if the working tree contains syntactically invalid unstaged edits; these are irrelevant when the corresponding staged blobs are valid.

## C4. Writing staged changes safely

Safe staged auto-reconciliation is substantially harder than ordinary working-tree edits. Implement it **after** read-only staged validation is stable.

Default behaviour for a proposed `scan --staged --apply`:

1. Build and validate a complete edit plan against a captured index snapshot (blob OIDs, modes, paths, staged registry bytes, staged configuration).
2. Distinguish fully staged files from **partially staged files** where working-tree bytes differ from the staged blob.
3. **For v1, refuse to auto-write partially staged files** (`partial_stage_conflict`) and offer a dry-run preview plus manual reconciliation instructions. Never `git add` the whole file merely to capture BytePlan's changes.
4. For eligible files, apply BytePlan edits to the staged blob in memory. Validate tokenization, parseability, and semantic equivalence rules from the existing edit engine.
5. Prepare new blobs and proposed index entries. Re-check the original index entries immediately before replacement; on mismatch, abort without changing anything.
6. Prefer writing new blob objects and updating the index via Git plumbing with expected-mode/OID checks, rather than running `git add` on user files. Where Git offers no atomic multi-entry index transaction, use a lock and recoverable before/after index manifest; do not claim stronger atomicity than can be provided.
7. If working-tree updates are part of the mode, ensure that they cannot erase concurrent or unstaged changes. A simpler initial implementation may **update only the index**, explicitly report that the working tree needs reconciliation, and return a non-success outcome requiring user review before committing.
8. Do not claim `--apply` success until the staged snapshot is revalidated. Any unexpected mismatch is blocking and leaves a recoverable record.

A narrower first release is acceptable: ship **only** `check --staged` and `scan --staged --dry-run`, document that `byteplan scan` updates the working tree and the developer must stage relevant changes manually, and postpone `--apply` until correctness can be demonstrated. Do not compromise partial-staging safety to deliver convenience.

## C5. Integration with the pre-commit framework

Publish `.pre-commit-hooks.yaml` with at least:

```yaml
- id: byteplan-check
  name: BytePlan staged consistency
  entry: byteplan check --staged
  language: python
  pass_filenames: false
  always_run: true
  stages: [pre-commit]

- id: byteplan-scan-preview
  name: BytePlan staged reconciliation preview
  entry: byteplan scan --staged --dry-run
  language: python
  pass_filenames: false
  always_run: true
  stages: [manual]
```

Illustrative consumer configuration:

```yaml
repos:
  - repo: https://github.com/BytesAndCoffee/byteplan
    rev: vX.Y.Z
    hooks:
      - id: byteplan-check
```

Use an actual published tag when documenting released examples. The hooks must function from an isolated pre-commit environment without needing to import the consuming project's application code. Avoid `types: [python]` as a filter because registry-only, rename, and deletion commits also require checking; `always_run: true` and `pass_filenames: false` are intentional.

`byteplan git install-hooks` is optional sugar, not a reason to replace or overwrite the user's existing `.git/hooks/pre-commit`. Prefer installing via the pre-commit framework and provide a safe conflict-aware path for direct hooks.

## C6. CI integration

Offer a documented CI recipe, starting with GitHub Actions, that validates the complete committed checkout:

```yaml
name: BytePlan consistency
on:
  pull_request:
  push:
    branches: [main]
jobs:
  byteplan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: python -m pip install byteplan
      - run: byteplan check --format json
```

This is a conceptual example; adjust pinned action versions, project initialization and actual CLI support when implemented. CI should **not write source** to fix inconsistencies. It should fail with actionable findings. A later optional report publisher can attach Markdown/JSON/SARIF annotations to PRs, but must not be required for core enforcement.

Optionally provide a comparison report for `base...head`: tasks introduced, resolved, made missing, newly blocked, or with stale evidence. This is a view over already grounded registry states and Git snapshots, not an independent task database.

## C7. Interaction with Hatch, cleanup, and release

- Local Hatch builds may reconcile the working tree if explicitly opted in; pre-commit validates **exactly what is staged**. Both call the same core scanner and registry rules.
- Reconciliation that modifies source or registry will often require an explicit `git add` before `check --staged` passes. Provide clear remediation output, but do not auto-stage unrelated changes.
- `byteplan sync --apply` remains an explicitly authorized source rewrite and is not silently invoked by read-only Git hooks.
- `byteplan release` / `restore` keep their separate intentional `stripped` state. A release commit must not be rejected because its decorators are absent when the committed registry correctly records the stripped release state.
- A normal development commit must not accidentally inherit a stale release-stripped state; surface `release_stripped` diagnostics when the intended workflow is inconsistent.
- `require_stripped` on Hatch release builds complements, rather than substitutes for, staged registry consistency checks.
- A Git hook must never execute `release` or `restore` on behalf of a developer.

## C8. Suggested output

```console
$ byteplan check --staged
BytePlan: checked 86 staged Python files and .byteplan/tasks.json
  42 tracked · 1 new unregistered TODO · 1 missing open task

! NEW_UNREGISTERED  src/bytesim/routing/rip.py:92
  # TODO: Implement triggered updates
  Run `byteplan scan`, inspect changes, and stage source + registry.

! MISSING [a83f]  src/bytesim/routing/rip.py (last attached: RIPRouter.advertise_routes)
  The staged source no longer contains this open obligation.
  Restore the annotation or explicitly resolve the task and stage the registry.

Check failed (exit 1). No files changed.
```

Output should distinguish `working_tree_changed_but_not_staged`, `registry_not_staged`, `partial_stage_conflict`, `staged_config_mismatch`, and genuine semantic task issues. In JSON output, emit a stable diagnostic schema with ID, kind, path, symbol, staged blob OID where useful, severity, and remediation. Diagnostics on stderr must not corrupt JSON payload on stdout.

## C9. Acceptance tests

Add focused tests on real temporary Git repositories, not mocked `git diff` strings:

1. A clean staged project passes `check --staged` and leaves index and working tree byte-identical.
2. An untagged staged `# TODO` is detected and produces an actionable nonzero finding.
3. A staged annotated source change with an unstaged registry update is rejected, even if the working tree is fully reconciled.
4. A staged registry-only status change is accepted when it matches the staged code.
5. An open task whose annotation is deleted in the index is flagged `missing`, never implicitly resolved.
6. A simultaneously staged `resolved` registry update and legitimate annotation cleanup does not produce a false missing-task error.
7. A staged release snapshot with recorded stripped decorators is accepted; an unrecorded strip is rejected.
8. A staged rename preserves IDs and source associations; line shifts do not create new tasks.
9. Partially staged files are validated against the index rather than working-tree content.
10. Staged valid Python succeeds even when the unstaged worktree version has a syntax error.
11. Filenames with spaces, Unicode, and unusual characters are correctly handled with NUL-delimited Git plumbing.
12. Deleted files, newly added files, untracked files, and renamed files are correctly distinguished.
13. Duplicate and unregistered IDs in the staged snapshot produce nonzero findings without silent changes.
14. `scan --staged --dry-run` leaves the index, working tree, and registry unchanged.
15. If staged `--apply` is implemented, it refuses partial staging and concurrent index changes; it never stages unrelated edits.
16. If staged `--apply` is implemented, interruption during index updates is detectable/recoverable without losing previous staged data.
17. The isolated pre-commit hook runs on a registry-only commit and does not require application dependencies.
18. CI and pre-commit use identical semantic validation for equivalent snapshots.
19. A narrowed staged scan cannot mark out-of-scope tasks missing.
20. Repeated checks produce identical findings without timestamp or history churn.
21. Hook execution never runs tests, application modules, MCP actions, or network synchronization.
22. Release/restore state transitions continue to validate according to their existing explicit semantics.

## C10. Implementation order

1. **Git snapshot reader:** Resolve repo root, index tree/blob reader, path/mode/rename metadata, staged configuration/registry loader, and tests.
2. **Read-only check:** Feed staged source bytes to existing parsing/reconciliation logic without writing; add staged-specific diagnostics and exit codes.
3. **Pre-commit packaging:** Publish hook manifest and documented consumer setup.
4. **CI recipes:** Add full-check example, human-readable and machine-readable reports.
5. **Optional staged writer:** Only after index/working-tree conflict and recovery tests establish its safety.
6. **Optional PR delta reports:** Compare two complete snapshots of the same registry and codebase.

## C11. Instructions to Claude

Treat this as **Addendum C**, additive to the original spec and Addenda A/B. Integrate it into `docs/IMPLEMENTATION_PLAN.md` as a Git lifecycle phase after the underlying scanner/reconciliation engine is stable. Preserve the existing `api.Project` and persistence architecture, extending it with a read-only snapshot abstraction rather than reimplementing the scanner for Git. Document the staged-snapshot boundary and Git plumbing assumptions precisely. Implement `check --staged` before any staged writeback. Do not misrepresent a pre-commit hook as mandatory or a build as an atomic Git transaction. Prioritize safe partial-staging behavior over convenience. Add phase-appropriate tests and docs before claiming production readiness.

**Product promise:** *Write unfinished work where it lives. BytePlan ensures the backlog travels with the code—through builds, commits, reviews, and releases.*
