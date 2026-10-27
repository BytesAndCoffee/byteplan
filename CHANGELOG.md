# Changelog

All notable changes to `byteplan`. The runtime decorators ship separately as
[`byteplan-runtime`](https://pypi.org/project/byteplan-runtime/), with their own versions.

## Unreleased

### Fixed
- **Prose comments are no longer tasks:** a comment that merely starts with a tag word in another
  case (`# Todo list model`, `# hack around the parser`) was tracked, and the first writing scan
  inserted an ID into it. A tag spelled differently from its configuration now needs `:` or `[id]`
  right after it (`# todo: ...`); the configured spelling (`# TODO ...`) is unchanged. Already
  annotated tasks (`# Todo[id] ...`) keep matching. Applies to Python, Markdown and JSONC comments.
- **New scaffold files pass isort:** when `@verifies` comes from a project shim rather than
  `byteplan_runtime`, a newly created test file now puts the shim import in its own section
  below `import pytest`, as ruff's isort expects.

### Packaging
- The PyPy classifier is gone; CI tests CPython only. The sdist no longer ships internal review
  notes (`docs/reviews/`, `docs/rc1-next-steps.md`).

## 1.0.0rc1 — candidate preparation

This candidate is being prepared for review; it is not approved or published by these notes.
The final integrated revision still requires the independent whole-repository reviews,
artifact/platform validation and explicit approval described in
[Addendum E](docs/spec-addendum-e.md#track-g--release-candidate-readiness-and-approval).
`byteplan-runtime` remains separately versioned; this is the devtool's release candidate.

### Upgrade and compatibility
- Upgrade participating clients, preview and run `byteplan migrate`, then stage or commit
  the schema-v2 registry before allocating expanded IDs. Migration preserves task identities,
  history, verification evidence and extension metadata, is idempotent, and uses the existing
  transaction journal for recovery. Do not downgrade by changing `schema_version` alone.
- Existing four-character IDs remain valid and unchanged. New tasks receive six-character IDs;
  longer lowercase hexadecimal identities remain supported. Exact identities take precedence
  over unambiguous UI prefixes; persisted links retain complete identities.
- Actual published 0.1.0/0.2.0 clients reject schema v2 for the tested ordinary commands.
  Their schema-v1 scanners can otherwise warn about expanded IDs yet exit successfully with
  no tracked tasks. Historical 0.2.0 `init --runtime-shim` can add a new inert shim before
  rejection; see the [compatibility matrix and recovery procedure](docs/rc1-compatibility.md).

### Added
- Explicit `byteplan migrate [--dry-run]` upgrades registry metadata to schema v2 through the
  existing recovery journal before expanded task identities can be written. New repositories
  use v2; released incompatible clients reject that version boundary.
- New tasks receive six-character IDs. Legacy four-character and longer hexadecimal IDs are
  supported, with exact-ID lookup before unambiguous user-interface prefixes.

### Architecture and public interfaces
- `byteplan.api.Project` is a concise facade over cohesive internal scan, task, verification,
  scaffold, source-sync, release, archive and initialization operations. Supported signatures,
  public result identities, exceptions, sentinel behavior and tested patch targets are retained.
  Result constructors retain their previously supported runtime annotation introspection.
- The [1.0 compatibility policy](docs/compatibility-policy.md) covers the documented CLI,
  Python API, configuration, decorators, MCP protocol and Hatch/Git integrations. SDK-specific
  Python MCP embedding is explicitly experimental; source safety and authoritative state
  guarantees still apply. Advanced shipped commands are included in the compatibility boundary.
- Addendum E documents future graph foundations for 1.5 and graph intelligence/Assignment
  traceability for 2.0. These capabilities are tracked and excluded from RC1 implementation.

### Fixed
- Original-branch collision recovery (`repair --reassign PATH:LINE --against REV [--dry-run]`)
  preserves the complete task record, supported exact source references and historical evidence.
  Repair reserves both identities and requires new verification; uncertain references, inherited
  identities, active Git operations, index locks and pending transactions are rejected safely.
- Registry-driver merges preserve nested source/stub/test extension metadata and reject
  competing authoritative edits. Supported schema-1/schema-2 branches can merge across the
  migration boundary. Plain Git may retain explicit conflicts; installing the driver is optional.
- Verification requires complete run provenance and current file fingerprints, including HEAD
  mode. Opaque evidence fields survive normal writes; run identities remain unique and archive
  restore preserves provenance under run-ID collisions. Missing renamed tests explain explicit
  rescanning or managed-link repair; verification does not silently rescan the registry.
- Git-snapshot Python API queries use selected registry, evidence, source and configuration
  blobs. Mutations and test execution reject snapshot projects before side effects. Source and
  archive previews requiring working-tree state fail explicitly; index HEAD freshness remains
  conservative instead of borrowing a working-tree pass.
- Archiving requires a committed copy of the current task and evidence in Git repositories,
  preserves type-sensitive canonical record hashes and refuses unreadable or malformed stores.
  Restore checks the paired archive-index/evidence state before writes and preserves newer
  canonical verification rather than overwriting it with an archived payload.
- MCP newer-schema errors explain upgrading and restarting the long-running server while
  retaining the original diagnostic and error cause.
- Registry, archive-index and verification parsing reject duplicate JSON keys and unresolved
  Git markers. Checks validate evidence from the same working-tree or Git snapshot as source.
- JSON annotation edit guards recognize expanded IDs; malformed pytest marker IDs are reported.
- Initialization validates an existing registry before writing a runtime shim or configuration.
- Review findings for 1.0: scanning respects module-level rebinding, scaffolds preserve
  conditional tests, and cleanup keeps runtime names consumed by other modules.
- Archived records are cached by ID and hash, preserving local evidence across branch
  switches. Existing SQLite archives migrate transactionally without discarding records.
- Staged reconciliation refuses pending ordinary transactions; source collection skips
  nonregular files and honors nested Git ignore exceptions.
- Verification handles ancestor pytest roots, linked symlink paths, and skipped/xfail teardown. The release guard
  rejects runtime decorators with dynamic arguments, and duplicate repair accepts valid
  whitespace, multiline IDs, and escaped string literals.
- **Windows:** the commit hook's staged reconciliation (`scan --staged --apply`) corrupted the Git
  index: the new index was written through a text-mode file descriptor, turning `\n` bytes into
  `\r\n`. Git then failed with `unknown index entry format`. Found by the new Windows CI.
- **A write whose directory can't be created** (a file in the way) now fails before its recovery
  journal is written. It used to leave a journal that every later write tried, and failed, to
  complete.
- Git's output is decoded as UTF-8 rather than with the locale's encoding (cp1252 on Windows).

### Integration (Phase 10)
- CI runs the test suite on ubuntu, macOS and Windows (Python 3.11–3.14).
- The README walks one task from TODO to resolved, and lists where BytePlan notices but never
  closes work. Every configuration key is documented with its default, which a test enforces.
- `CONTRIBUTING.md` describes how BytePlan manages its own development.

### Auto-scaffolding
- **`[tool.byteplan.tests.scaffold] auto = true`:** a writing `scan` scaffolds an acceptance
  test for each open task it adds in a Python file outside the test directory. `scan` lists
  what it scaffolded (`scaffolded` / `scaffold_failures` in JSON). BytePlan's own repo enables it,
  with `policy = "xfail"`.
- **Scaffold typing and existing-file imports:** tests are annotated `-> None` (mypy
  `--strict`), and imports added to an existing file go into its import sections in isort order
  (ruff `I001`). New files using a first-party runtime shim may still need a formatter pass
  to separate that shim from third-party pytest imports (tracked as nonblocking `67a65c`).

### Compact MCP results
- **`scan`** returns counts and what changed; `detail=true` lists every annotation.
- **`missing`** (and `byteplan missing`) lists only open, in-progress and blocked tasks;
  `include_closed=true` / `--include-closed` adds resolved and dismissed ones.
- **`preview_test_scaffold` and `scaffold_test`** return the new test and the imports it adds;
  `full=true` adds the whole file.

### Report file on one branch
- **`[tool.byteplan] report_branch`** (e.g. `"main"`): only that branch writes and checks
  `report_file`, so pull requests no longer conflict on it on GitHub, which doesn't run merge
  drivers. `byteplan report --write` regenerates it on any branch, for a post-merge CI job
  (see docs/ci.md). BytePlan's own repo now does this.

### MCP server (Phase 9)
- **`byteplan mcp`** (and the `byteplan-mcp` script) serves the registry over MCP's stdio
  transport, with the optional extra `pip install 'byteplan[mcp]'` (MCP SDK 2.x).
- **Tools** mirror the CLI and use the same JSON schemas: listing, showing (archived tasks too),
  scanning, checking, reports, test links, recorded verification, ready tasks, sync and scaffold
  previews. There are also two resources (`byteplan://tasks`, `byteplan://tasks/{id}`) and a
  `triage` prompt.
- **Read-only by default:** `--allow-registry-write`, `--allow-source-write` and
  `--allow-test-execution` each add their tools. Source writes also need `apply=true` on every
  call. Errors where the CLI exits 2 (e.g. `locked`) come back as tool errors with the message.

### Archive
- **Closed tasks leave `tasks.json`:** once a task has been resolved or dismissed for
  `[tool.byteplan.archive] after_days` (7) and its annotation is gone, a writing `scan` archives
  it, or run `byteplan archive [--dry-run] [--older-than DAYS]`. Its ID stays reserved.
- **Local first:** the full record and its evidence go to `.byteplan/archive.sqlite`
  (gitignored, zlib-compressed). The committed `.byteplan/archive.json` is the reconciliation
  artifact: per task, its title, status, dates and record hash.
- **Other clones reconcile task records from Git history:** `show` finds an archived record
  by hash in earlier `tasks.json` versions, and `archive --reconcile` fills the local store when
  that history is available. Shallow, rewritten or missing history can prevent recovery and is
  reported explicitly. Verification payloads have committed copies before archiving, but this
  traversal does not automatically restore another clone's evidence; unavailable evidence stays
  unverified. Preserve the historical payload or run fresh verification before claiming readiness.
- `list --archived`, `archive --restore ID`, and a `byteplan-archive` merge driver (three-way per task ID),
  installed by `git install-merge-driver`. An archived ID back in source gets its own hint.

### Releases (Phase 8, part 2)
- **`byteplan release --smoke-test [--offline]`** (opt-in):
  - It builds a wheel from the stripped tree into a temporary directory and installs it in
    isolation (`-I -S`).
  - It asserts `byteplan_runtime` isn't importable, and imports every top-level module.
  - A failure restores the strip automatically (`smoke_test_failed`), and the release records
    `smoke_test: passed`.
  - Configured in `[tool.byteplan.release]`.
- **Hatch `require_stripped`:** wheel and sdist builds fail while `@todo`/`@verifies` remain.
- **Warnings:**
  - `runtime_dependency_in_release`: `byteplan-runtime` is still a project dependency.
  - `unfinished_scaffold_in_sdist`: a placeholder test would ship. The file list comes from
    Hatchling's own sdist selection.
  - Both appear at release time and from `check` while stripped.

### Releases (Phase 8, part 1)
- **`byteplan release`** strips every recognized `@todo`/`@verifies` decorator, and the runtime
  imports left unused, in place.
  - Records: each one's exact text and position go in the registry.
  - Never: commit, tag, build or reset.
  - Refusals: a dirty tree, untagged decorators, shared lines, leftover runtime references, or an
    already-stripped tree.
  - Warning: releasing on the default branch.
- **`byteplan restore`** puts everything back: byte-identical when unchanged, AST-anchored after
  hotfixes. `restore_conflict` and `--partial` handle anything it can't place.
- **Presence `stripped`:** tasks are on record during a release, never `missing`, and their test
  links are frozen. `sync`, scaffolding and cleanup refuse while stripped.
  - Note: byteplan 0.2 can't read a stripped registry (unknown presence). This only arises on
    release commits made with this version.

### Cleanup (Phase 7)
- **`byteplan sync --remove-resolved`** and **`byteplan resolve ID --sync-source`** remove the
  source annotations of resolved and dismissed tasks.
  - Python: tags with their continuation lines, trailing tags, and whole-line `@todo(...)`
    decorators, plus the `todo` import once unused.
  - Markdown: HTML and link-reference comments.
  - JSON: comments. A JSON string value is left for review.
  - Safety: changes are previewed by default and journaled when written, checked against the
    AST, and must round-trip through the scanner.
  - The registry keeps the ID and history and logs `cleaned`.
- **Tidy Markdown removal:** a whole-line comment between two blank lines takes one of them with
  it, so cleanup doesn't leave a double blank line.
- **`resolved_but_stubbed`:** a closed task whose code is still a stub isn't cleaned (scan
  reports it too). `--suppress-stubs` leaves a visible `# byteplan: ignore` instead.
- **`[tool.byteplan.annotations] remove_resolved`** makes `sync --apply` clean up.
### Decorator mode
- **`sync` writes more natural code:**
  - The runtime import goes after the module's leading import block, where first-party imports
    usually sit, unless that would be below a rewritten declaration.
  - A multi-line description becomes a parenthesized string with one line per source line.
  - Run your formatter afterwards for exact import order.
- **The `init --runtime-shim` template** is now clean under strict linters (ruff's `A002`,
  `ARG001` and `TC003`).
- **BytePlan dogfoods decorator mode:** its own tasks use `@todo` through an in-package shim
  (`byteplan._todo`), so it gains no runtime dependency.

### Test scaffolding (Phase 6b)
- **`byteplan tests scaffold ID`** writes a deliberately failing acceptance test for a task and
  links it.
  - Linking: through `@verifies` (default), `@pytest.mark.byteplan` or a managed link.
  - Where it goes: a new file, or appended to an existing one. Existing code is never altered,
    which an AST check enforces.
  - What it contains: the body always ends in an unconditional `pytest.fail(...)`, so it can't
    pass by accident. GIVEN/WHEN/THEN hints are comments, and no fixtures or assertions are
    invented.
  - Re-running: it's idempotent. `--force-new` adds another test, without name collisions.
    `--dry-run` previews it.
  - Placeholders: they're detected statically. `check` reports `scaffold_placeholder`, and a
    placeholder never counts as ready for review.
  - Configured in `[tool.byteplan.tests.scaffold]`.

### Acceptance tests (Phase 6a)
- **`byteplan verify [ID...]`** runs a task's linked tests with pytest and records the evidence
  in `.byteplan/verification.json`.
  - How it runs: it passes the test files and lets its own plugin select the requested tests, so
    one unknown test can't abort the run. It runs in its own process group, with a
    configurable runner and timeout.
  - Outcomes: `passed`, `failed`, `skipped`, `xfailed`, `xpassed`, `error`, `not_found`,
    `not_run` or `timeout`. Only `passed` is evidence. A crash or kill never produces a pass.
  - Readiness: `unverified`, `failing`, `needs_review` or `ready_for_review`. Results are
    stale when the task's files change (`stale_on = "files"`) or HEAD moves (`"head"`).
  - Reviewing it: `verify --ready` lists tasks ready for review, and `show` displays readiness
    and per-test results.
  - When an implemented stub's tests pass, scan reports `implementation_complete_candidate`.
  - Readiness is advice only: no task is ever resolved automatically.
- **Test links:** a task links to the pytest tests that verify it.
  - Where links come from: `@todo(tests=...)` / `@todo(test=...)`, `@verifies("id")` on the test,
    `@pytest.mark.byteplan("id")` (with `[tool.byteplan.tests] pytest_marker = true`), and
    `byteplan tests add`.
  - How they're stored: as `tests.discovered` (refreshed by scans) and `tests.managed` (CLI
    only), each link keeping its provenance.
  - Reviewing them: `byteplan tests list [ID]`, `tests add` and `tests remove`, and `show`
    lists them.
  - Diagnostics: `malformed_test_id` and `test_not_in_scope`. Unscanned link changes are
    `registry_out_of_sync`. The merge driver merges managed links as a set.

## 0.2.0 (2026-10-22)

Markdown and JSON tracking, a committed task list, decorator mode, and registry forward
compatibility. Everything new is opt-in: projects that don't change their configuration see the
same behaviour as 0.1.0, apart from the scan summary now saying "files scanned".

### Tracking
- **Markdown and JSON:** tags in Markdown HTML comments (`<!-- TODO: ... -->`) and fully hidden
  link-reference comments (`[//]: # (TODO: ...)`), and in JSON
  `//` / `/* */` comments and string values (`"TODO: ..."`) are tracked like Python comments, with
  IDs, Git integration and repair. Opt in through `include`; the default scope is still `**/*.py`.
  New `[tool.byteplan.detect] json_string_values` option.
- The registry file is never scanned, even when `include` matches it.

### Decorators
- **`byteplan sync`** (Phase 5): with `[tool.byteplan.annotations] mode = "decorator"`, rewrite
  tagged comments directly above a `def`/`class` (`convert_attached_comments`) and unowned
  stubs (`auto_decorate_stubs`) to `@todo(...)`. It previews by default, `--apply` writes
  through the journal, and `--only ID` limits it. Unsafe cases are reported as
  `conversion_needs_review`. Every rewrite must keep the AST identical apart from BytePlan's
  own decorators and imports, and must round-trip through the scanner.
- **Annotation modes:** `comment` (default, unchanged), `preserve` and `decorator`. In the last
  two, `scan` reports unowned stubs instead of adding `# TODO` lines.
- **`byteplan init --runtime-shim PATH`** writes an inert `todo`/`verifies` module for projects
  that won't depend on `byteplan-runtime`, and registers it in `runtime_modules`.

### Registry
- **Forward compatibility:** unknown top-level registry keys, from a newer BytePlan, are kept on
  save instead of dropped, as unknown task fields already were. The merge driver merges them
  three-way: objects key by key, and appended lists combined.
- **Merge driver fix:** `true` and `1` (and `false` and `0`) are now different values, as in
  JSON. Before, a change between them could be taken as "unchanged" and one side kept silently.

### Git and reporting
- **`report_file`:** set `[tool.byteplan] report_file = "byteplan.md"` for a committed Markdown
  task list rendered from the registry. Every registry write regenerates it, and the commit hook
  stages it with the registry. `check --staged`, `check --commit` and `require_reconciled` warn
  with `report_out_of_sync` when it's stale (`[tool.byteplan.check] fail_on_stale_report` makes
  that fail). `git install-merge-driver` keeps our copy on merges instead of conflicting.

## 0.1.0 (2026-10-22)

The first usable release. 0.0.1 was an empty placeholder that reserved the name.

### Tracking
- **Tagged comments:** `TODO`, `FIXME`, `HACK` and `XXX` comments get permanent four-hex-digit IDs
  written back into source (`# TODO[7fa2]: ...`), with continuation lines as the description.
- **Stubs:** unfinished functions and classes (`pass`, `...`, docstring-only,
  `raise NotImplementedError`, empty classes) are detected. Abstract methods, overloads,
  Protocols, intentionally empty classes, interface methods implemented by subclasses, and no-op
  overrides are excluded.
- **Decorators:** `@todo(...)` and `@verifies(...)` from `byteplan-runtime` are read statically,
  never by importing your code.
- **Registry:** a Git-versioned `.byteplan/tasks.json` keeps status, priority, assignee, labels,
  notes and history, separate from source presence (`present`, `missing`, `unknown`).
- **No automatic resolution:** removing a TODO marks the task `missing`; only `byteplan resolve`
  resolves it.

### Commands
`init`, `scan` (`--dry-run`, narrowed paths), `check`, `list`, `show`, `status`, `resolve`, `edit`,
`missing`, `duplicates`, `report` (text, JSON, Markdown) and `repair` (`--import`, `--reassign`).

### Git and build integration
- **Snapshot checks:** `check --staged` and `check --commit REV` judge exactly what's staged or
  committed, with a shared consistency policy for pre-commit and CI.
- **IDs at commit time:** `scan --staged --apply` and the default pre-commit hook
  (`byteplan git install-hooks`). Partial staging is refused, rollback is full, and crash
  recovery is supported.
- **pre-commit framework:** hooks `byteplan-reconcile`, `byteplan-check` and
  `byteplan-scan-preview`.
- **Registry merges:** a Git merge driver merges the registry by task ID
  (`byteplan git install-merge-driver`).
- **Hatchling build hook** (`[tool.hatch.build.hooks.byteplan]`): read-only by default, with
  opt-in source annotation.

### Safety
- **Writes:** journaled and crash-safe, under a project lock, with atomic per-file replacement.
- **Concurrent edits:** detected and never overwritten.
- **Validation:** every edit must leave the program's AST unchanged and round-trip through the
  scanner.
- **Byte preservation:** encodings, BOMs, CRLF and missing final newlines are preserved byte for
  byte.

### Known limitations
- **Not yet available:** test linking and verification, test scaffolding, release stripping, and
  the MCP server (see the implementation plan).
- **Platforms:** tested on Linux and macOS (CI: Ubuntu, Python 3.11 to 3.14). Windows is untested.
- **Ruff:** rule TD004 flags the `TODO[id]:` syntax; see the README's "Linters" section.
