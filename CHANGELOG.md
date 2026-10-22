# Changelog

All notable changes to `byteplan`. The runtime decorators ship separately as
[`byteplan-runtime`](https://pypi.org/project/byteplan-runtime/), with their own versions.

## Unreleased

### Tracking
- **Markdown and JSON:** tags in Markdown HTML comments (`<!-- TODO: ... -->`) and fully hidden
  link-reference comments (`[//]: # (TODO: ...)`), and in JSON
  `//` / `/* */` comments and string values (`"TODO: ..."`) are tracked like Python comments, with
  IDs, Git integration and repair. Opt in through `include`; the default scope is still `**/*.py`.
  New `[tool.byteplan.detect] json_string_values` option.
- The registry file is never scanned, even when `include` matches it.

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
