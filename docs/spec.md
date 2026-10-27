# BytePlan — Implementation Specification for Kiro

**Working package:** `byteplan`  
**CLI:** `byteplan`  
**Registry:** `.byteplan/tasks.json`  
**Tagline:** *Plan in code. Track in one place.*  
**Implementation target:** Python 3.11+; installable PyPI package with optional Hatchling integration.

## 1. Product summary

BytePlan is a source-first, project-local development task manager. Developers declare unfinished work where it is encountered: source comments and unfinished implementations. BytePlan scans Python source, assigns each tracked item a permanent lowercase hexadecimal ID, writes the ID back into the source, and reconciles discoveries with a Git-versioned central registry. Project management fields live in the registry, not in comments.

BytePlan must also detect when a registry item no longer exists within a completed source scan and flag it as **missing**, without assuming the task has been resolved. Scanning must be deterministic, idempotent after the initial annotation, and safe to run from Hatch builds or CI.

The product is not a GitHub Issues replacement, not a full code-quality linter, and not a runtime instrumentation system.

## 2. Core invariants

1. A tracked task has **one immutable, project-unique ID**. Existing four-character identities such as `7fa2` remain valid; newly allocated tasks use six characters.
2. Persistent IDs use `[0-9a-f]{4,}`. They are assigned once, embedded in source, and *never recomputed* when text, file path, symbol, or line number changes. Exact lookup takes precedence over unambiguous UI prefixes; stored references always use full IDs.
3. The registry is the canonical source of status, priority, assignee, notes, and history; source code is the canonical evidence that the item exists.
4. IDs are never reused, including IDs from closed or deleted/archived entries. Maintain a permanent reservation ledger.
5. Registry lifecycle status and source presence are separate dimensions.
6. No scanner may silently mark tasks completed, delete task history, or overwrite user-managed metadata.
7. A scan must finish successfully over the *entire configured project scope* before any absent item is marked missing.
8. A repeated scan of unchanged code produces **zero textual changes** to both source and registry (including timestamps).
9. The same ID appearing on two independent annotations is an error, not two tasks to merge.
10. Scanning is locally executable independent of Hatch; Hatch is only an integration adapter.

## 3. User-facing source syntax

<!-- FIXME[971b9d]: Describe the current tag case rule in the spec and implementation plan
  Here and in IMPLEMENTATION_PLAN.md (the "case-insensitive" tag regex near line 187), discovery is
  still described as case-insensitive. Since 415a0f only the configured spelling matches bare;
  other spellings need `:` or `[id]` right after the tag. -->

Supported comment kinds, case-insensitive during initial discovery:

```python
# TODO: Implement route poisoning
#   Support split horizon and poisoned reverse.
# FIXME: ARP entries can outlive interfaces
# HACK: This adapter is temporary
# XXX: Investigate nondeterministic routing updates
```

After annotation (write mode):

```python
# TODO[7fa2]: Implement route poisoning
#   Support split horizon and poisoned reverse.
# FIXME[a491]: ARP entries can outlive interfaces
```

Preserve original content, casing where practicable, indentation, whitespace, encoding, newline convention, and end-of-file newline. Avoid touching strings, docstrings, or commented-out code that merely *contains* `TODO`. Use `tokenize`, not a whole-file regex, for comment identification.

Multiline comments: the tagged first line owns immediately adjacent comment continuation lines; continuation lines must either be indented after `#` or use a configured continuation convention. Terminate blocks at blank lines, another task annotation, ordinary unrelated comments, or syntactic boundaries. Keep all continuation text in the registry's discovered description. Document exact grouping rules and test them.

Support existing `TODO[abcd]` annotations as-is, including source files moved to different paths. Do not require explicit task IDs from authors.

## 4. Automatic stub discovery

Use Python `ast` to discover candidate unfinished implementations, initially:

- `def` / `async def` with an effectively empty body (`pass`, standalone `...`) after ignoring a docstring.
- `def` / `async def` whose only effective statement is `raise NotImplementedError` or `raise NotImplementedError(...)`.
- Classes with an effectively empty body, after ignoring a docstring.
- Optionally configurable module-level placeholder assignments (`name = ...` or `name = NotImplemented`) — disabled by default to reduce false positives.

Exclusions by default: abstract methods (`@abstractmethod` and qualified variants), overload definitions (`@overload`), protocol/interface declarations, `.pyi` files, and explicitly ignored paths or symbols. Do not infer an unfinished task merely because a method is intentionally a no-op; provide `# byteplan: ignore` as an explicit suppression directive with a documented scope. Support configuration to disable each heuristic.

To make stub identity persist through movement, add one tagged TODO above the declaration *only when no associated TODO is already present*:

```python
# TODO[e301]: Implement Router.send_route_update (detected stub)
def send_route_update(self):
    raise NotImplementedError
```

A nearby existing TODO immediately attached to the same declaration is the owner; do not create a duplicate task. For classes and methods, preserve indentation and decorators (insert annotation above the first decorator, unless that would break association or formatter/linter behaviour; specify consistent logic). Never inject annotations inside a function body when that would alter docstring semantics. For one-line suites or syntactically ambiguous cases, report a candidate without mutating and require manual review.

**Avoid perpetual rediscovery:** an open tagged TODO for a stub remains tracked even after its body is implemented until the source TODO is removed or the task is deliberately resolved. When a stub is implemented but its annotation remains, flag `implementation_changed` as an advisory; do not silently close it.

## 5. ID allocation

Use Python stdlib `hashlib.shake_128` to propose a 24-bit (three-byte) ID, represented as six lowercase hex characters. **SHAKE128 is an implementation choice for convenient deterministic output, not a security claim.** Preserve existing four-character IDs and support longer lowercase hexadecimal identities. The expanded contract supersedes the original 16-bit proposal under Addendum E A1–A2.

Input seed for new annotations: normalized relative source path, qualified symbol when available, TODO kind and text, and deterministic disambiguator for identical occurrences. Include a counter for collision retries. Example:

```python
from hashlib import shake_128

def candidate(seed: str, attempt: int) -> str:
    return shake_128(f"{seed}\0{attempt}".encode("utf-8")).hexdigest(3)
```

Scan files in a stable sorted order and allocate IDs in a stable order within each file. When a candidate is in the active-or-reserved set, increment `attempt` until an unused ID is found, with a deterministic fallback probe. Never overwrite an existing ID. Preserve the reservation ledger even if the task is archived or removed from the active view. Exhaustion of the 16,777,216 six-character candidates must be reported as a clear failure; legacy and longer identities do not consume that entire namespace merely by sharing prefixes. IDs provide only **project-local uniqueness**, not collision resistance or cross-project coordination.

## 6. Registry format

Default: `.byteplan/tasks.json`, UTF-8, formatted with 2-space indentation and deterministic sorted keys/task ordering. JSON is mandatory for MVP; SQLite or YAML may be added later. The registry is intended to be committed to Git and excluded from package distributions.

Suggested schema (evolve with `schema_version` and migrations):

New repositories use schema v2. Existing schema-v1 repositories retain their version until an
explicit, journaled `byteplan migrate`. Incompatible annotation writes require completed
migration first. Migration preserves source, task/history metadata and verification evidence;
see [the compatibility and recovery procedure](rc1-compatibility.md#migration-and-recovery).

```json
{
  "schema_version": 2,
  "reserved_ids": ["7fa2", "a491", "e301"],
  "tasks": {
    "7fa2": {
      "id": "7fa2",
      "kind": "TODO",
      "title": "Implement route poisoning",
      "description": "Support split horizon and poisoned reverse.",
      "status": "open",
      "priority": "normal",
      "assignee": null,
      "labels": [],
      "notes": "",
      "presence": "present",
      "source": {
        "path": "src/bytesim/routing/rip.py",
        "line": 84,
        "symbol": "Router.send_route_update"
      },
      "first_seen": "2026-10-21T00:00:00Z",
      "last_seen": "2026-10-21T00:00:00Z",
      "history": []
    }
  }
}
```

Use UTC timestamps only when actual events occur; do not update `last_seen` on unchanged scans if this would dirty the repository. If scanning occurred without substantive change, retain the previous persisted last-seen timestamp. History records events (`created`, `moved`, `text_changed`, `missing`, `reappeared`, `status_changed`, `resolved`, `archived`) with old/new values where appropriate. Do not redundantly append events every run. Recompute discovered title, description, source path/line/symbol, and presence while preserving managed fields. A source spelling change may update display metadata, but not identity.

`status` enum: `open`, `in_progress`, `blocked`, `resolved`, `dismissed`.
`presence` enum: `present`, `missing`, `unknown` (incomplete/never successfully scanned).

Examples of independent combinations: `open+present`, `open+missing`, `resolved+present` (stale annotation warning), `resolved+missing`.

## 7. Reconciliation algorithm

A `scan` run:

1. Load and validate the registry; on corruption or unsupported version, fail without changing files.
2. Resolve project root and configured scan scope; collect all `.py` files, applying ignores and symlink policy. Fail the complete scan if a required file cannot be read, decoded, or parsed (if AST enabled).
3. Tokenize comments, parse AST, and detect explicit TODOs/stubs.
4. Validate existing embedded IDs: formatting, uniqueness, and consistency with the registry. Treat ID conflicts as a blocking diagnostic; never silently reassign a previously tagged item.
5. Pair nearby TODO blocks with AST stubs before allocation; generate one task per distinct implementation obligation.
6. Propose and reserve IDs for untagged discoveries, plan source edits, and build the new registry in memory.
7. Update present tasks' discovered metadata, retaining their user-managed fields. Relocations are ordinary updates by ID; line number is metadata, not identity.
8. For known registry IDs not found in a *complete authoritative scan*, change `presence` from `present` to `missing` once and log an event. Do **not** change `status`.
9. If a missing task reappears, restore `presence=present` and log one event; preserve ID and management history.
10. If a resolved/dismissed task remains in source, issue a `stale_annotation` warning. If the source contains an ID absent from the registry, issue `unregistered_id` and offer an explicit repair/import option rather than rewriting the ID.
11. Validate proposed changes and write them safely. Subsequent unchanged scans should produce no diff.

**Scan scopes:** missing detection must only evaluate registry entries belonging to the configured *fully scanned* scope. Narrowed scans (e.g. a single file) may discover/update tasks but must not mark other tasks missing. If the configured scope changes, flag previously tracked out-of-scope items as `unknown` or `excluded` in diagnostic metadata rather than falsely missing them. A parse error, I/O error, or interrupted run must not perform absence reconciliation.

**Write safety:** first compute every edit in memory and validate it. Use temporary files in the same directory and atomic replacement per file. Because there is no filesystem-wide atomic transaction, record a recovery journal/backup manifest before the first replacement and implement idempotent restart or rollback; never claim cross-file atomicity without this. Preserve permissions. Provide `--dry-run` and `check` which never write. Avoid changing source on wheel/sdist release builds unless explicitly opted in.

## 8. CLI

Use `argparse` or Typer; prefer stdlib unless a dependency measurably improves UX. Commands:

```text
byteplan init                        Create configuration and empty registry
byteplan scan                        Discover, annotate, reconcile, report
byteplan scan --dry-run              Preview planned changes without writing
byteplan check                       Read-only validation; nonzero on configured failures
byteplan list [--status ...] [--presence ...] [--kind ...]
byteplan show 7fa2                   Details, source, management history
byteplan edit 7fa2                   Update title override, priority, assignee, labels, notes
byteplan status 7fa2 in_progress     Change lifecycle status
byteplan resolve 7fa2                Mark resolved (do not silently remove source TODO)
byteplan missing                     Show orphaned registry tasks
byteplan duplicates                  Report duplicate embedded IDs
byteplan report --format text|json|markdown
byteplan repair --interactive        Explicit fix-up for ambiguous states
```

`byteplan edit` may open `$EDITOR` or support individual `--priority`, `--assignee`, `--note`, etc. No mandatory TUI in MVP. Define and document exit codes: 0 success, 1 validation/policy findings (for `check`), 2 runtime/configuration errors. Machine-readable JSON output must not mix progress text with stdout payload; diagnostics go to stderr.

A task title override set through the CLI should be stored separately from the detected source title so that future scans do not erase it.

## 9. Configuration

Use `pyproject.toml`:

```toml
[tool.byteplan]
registry = ".byteplan/tasks.json"
include = ["src/**/*.py"]
exclude = ["**/.venv/**", "**/__pycache__/**", "**/generated/**", "**/*.pyi"]
auto_annotate = true
missing_policy = "warn"

[tool.byteplan.detect]
todo_tags = ["TODO", "FIXME", "HACK", "XXX"]
pass_stubs = true
ellipsis_stubs = true
not_implemented_stubs = true
empty_classes = true
placeholder_assignments = false

[tool.byteplan.check]
fail_on_duplicate_ids = true
fail_on_missing = false
fail_on_stale_annotations = false
```

Path resolution is relative to the project root, not process cwd. Reject path traversal outside the root in write mode. Respect `.gitignore` where feasible, but make explicit include/exclude behaviour documented and testable. Prevent symlink traversal outside root. Optionally honor `# byteplan: ignore` suppressions.

## 10. Hatch integration

Support the Hatchling build system, preferably with a **dedicated installed Hatch build-hook plugin** so that users do not have to copy an ad-hoc `hatch_build.py`. A custom hook example is acceptable as a minimal reference integration.

Expected configuration should be documented against the actual Hatchling API before implementation. Conceptual example:

```toml
[build-system]
requires = ["hatchling", "byteplan"]
build-backend = "hatchling.build"

[tool.hatch.build.hooks.byteplan]
scan = true
write_source = false
```

Requirements:

- On a normal *local development* Hatch build, allow an explicit opt-in to source annotation/reconciliation.
- Default installed build hooks to **read-only** for source distributions, wheels, CI and other reproducible builds. A build must not unexpectedly dirty a Git checkout.
- Document an opt-in pre-build workflow for projects that explicitly want registry updates on every `hatch build` (the user's intended workflow), e.g. enabling `write_source=true` with clear warnings and deterministic behaviour.
- Run reconciliation once per intended invocation, or make hook calls fully idempotent across wheel/sdist targets.
- Ensure dependencies used by the hook are available in isolated PEP 517 builds; avoid recursive self-build dependencies when building BytePlan itself.
- Do not accidentally package `.byteplan/` or generated registry data into published artifacts unless explicitly requested.
- Make `byteplan scan` independently usable in CI, pre-commit and editor tasks.

## 11. Reports / diagnostics

Example:

```text
$ byteplan scan
BytePlan: 87 Python files scanned
  39 comment annotations · 12 stub candidates · 48 unique tasks
  +3 added · ~4 relocated · !2 missing · !1 duplicate · 0 stale

! [b83e] MISSING     src/bytesim/routing/rip.py (previously line 140)
! [a419] DUPLICATE   src/bytesim/a.py:20 and src/bytesim/b.py:55
```

Diagnostics must include ID, classification, file, line when known, and remediation suggestions. Summarize tasks by status, kind, priority, and presence. JSON/Markdown reporting is useful for GitHub Actions, documentation, and dashboards.

## 12. Tests and acceptance criteria

Implement tests with `pytest` covering at least:

1. Single-line and multiline TODO discovery, with correct lexical handling of strings/docstrings.
2. Stub discovery for sync/async functions, methods, classes, `pass`, `...`, `NotImplementedError`.
3. Intentional stubs/interfaces excluded, explicit suppressions honored.
4. One attached TODO plus stub results in one task, not two.
5. Legacy four-character and expanded lowercase hex IDs; six-character allocation; exact-first/prefix lookup; collision retry, exhaustion and historical reservations; schema migration and released-client rejection.
6. Fresh annotation writes IDs to source while preserving indentation, comments, encodings, newline style, and parseability.
7. Inserted lines above a task do not change its ID; moving/renaming source does not change its ID.
8. Edit task's priority/notes/status, scan again: those managed fields survive.
9. Delete TODO from source: complete scan flags existing registry item `missing`, without marking `resolved` or deleting it.
10. Re-add same tagged TODO: item becomes `present` with old history/metadata preserved.
11. `resolved+present` yields stale-annotation diagnostic.
12. Duplicate ID in two distinct files causes nonzero validation failure; no silent reassignment.
13. An ID in source absent from registry triggers explicit `unregistered_id`, without replacing it.
14. Scanning one file or an incomplete/failed scan never marks unrelated tasks missing.
15. Repeated identical scan produces no file diffs, no new history events, no timestamp churn.
16. Crash/interruption during write can be recovered cleanly without orphaned or conflicting IDs.
17. `check` and `--dry-run` do not mutate files; CI exit codes predictable.
18. Hatch development build runs requested hook; wheel/sdist are reproducible; hooks are idempotent across build targets; no unintended distribution of registry.
19. Windows/macOS/Linux path and newline compatibility; non-ASCII source and comments.
20. Registry schema validation and clear errors for incompatible versions/corrupt files.

**Definition of done for MVP:** `pip install -e .` works, `byteplan init`, `scan`, `check`, `list`, `show`, `status`, `missing`, `report` work, Hatch integration is documented and tested, unit tests pass, and README shows end-to-end onboarding and reconciliation.

## 13. Suggested implementation structure

```text
src/byteplan/
  __init__.py
  cli.py
  config.py
  models.py
  registry.py
  ids.py
  scanner/
    comments.py
    stubs.py
    association.py
  reconcile.py
  annotate.py
  persistence.py
  reporting.py
  hatch_hook.py
  diagnostics.py
tests/
pyproject.toml
README.md
```

Keep scanners pure: return discovery objects and source edit proposals rather than writing directly. Keep reconciliation and persistence separate. Model task identity by explicit ID, never by current line number or source-text hash after initial allocation. Prefer typed dataclasses or similarly clear domain models; avoid overengineering.

## 14. Implementation order for Kiro

**Phase 1:** Config, registry schema, SHAKE128 ID allocator with collision handling (originally 16-bit; expanded to 24-bit under Addendum E), comment tokenizer, CLI `init/scan/list/show`.
**Phase 2:** Source annotator, full reconciliation, missing detection, duplicates, status management, idempotence and safe writes.  
**Phase 3:** AST stubs, association/suppression rules, diagnostics and `check/report`.  
**Phase 4:** Hatch build hook, isolated-build testing, packaging and README.  
**Phase 5 (optional):** Rich TUI, IDE integrations, GitHub/GitLab sync, Markdown/HTML dashboards, smart reattachment of legacy untagged TODOs.

## 15. Instructions to coding agent

Implement BytePlan as a production-quality, independently published Python development tool. Use the specification as the behavioural contract. Add tests before or alongside each phase, preserve data on all error paths, and prefer conservative diagnostics over destructive automatic fixes. Avoid interactive questions where sensible defaults are specified. Where an API is version-sensitive (especially Hatchling), verify current actual API behaviour rather than assuming the conceptual TOML is exact. Explain unavoidable tradeoffs in the README. Do not claim a TODO is resolved merely because its annotation disappeared.
