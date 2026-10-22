# Changelog

All notable changes to `byteplan`. The runtime decorators ship separately as
[`byteplan-runtime`](https://pypi.org/project/byteplan-runtime/), with their own versions.

## Unreleased

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
