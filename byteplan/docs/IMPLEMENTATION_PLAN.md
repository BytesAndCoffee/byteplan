# BytePlan implementation plan

The behavioural contract is [`spec.md`](spec.md). This document records how it is built,
the decisions the spec leaves open, and the phase order. Toolchain: Hatch / Hatchling
(verified against Hatch 1.18.1, Hatchling 1.32.4).

## Toolchain

| Task | Command |
|---|---|
| Tests | `hatch test` · `hatch test --cover` · `hatch test --all` (3.11–3.14 matrix) |
| Lint / format | `hatch fmt` · `hatch fmt --check` |
| Types | `hatch run types:check` (mypy `--strict`) |
| Build | `hatch build` |

BytePlan's own `[build-system].requires` stays `["hatchling"]` to avoid a recursive
self-build. To track BytePlan's own TODOs, run `hatch run byteplan scan`; don't use the build hook.

## Module layout

```
src/byteplan/
  models.py         frozen dataclasses + enums (Task, SourceRef, HistoryEvent, Edit, Diagnostic, ...)
  config.py         [tool.byteplan] via tomllib, defaults, validation, project-root resolution
  files.py          scope collection: pathspec include/exclude, .gitignore, symlink policy, sorted
  ids.py            shake_128 16-bit candidates, collision retry, exhaustion error
  scanner/
    source.py       bytes -> detect_encoding (BOM / PEP 263) -> text + newline style
    comments.py     tokenize-based tags and continuation blocks (pure)
    stubs.py        ast-based stubs, exclusions, suppressions (pure)
    association.py  pair TODO blocks with stubs -> one obligation each
  annotate.py       allocations -> Edit objects, applied in memory, re-parsed to validate
  reconcile.py      pure: (registry, scan, scope, clock) -> (registry', edits, diagnostics)
  registry.py       JSON load / validate / migrate / deterministic serialize
  persistence.py    lock, staged writes, journal, atomic replace, roll-forward recovery
  diagnostics.py    codes, severity, remediation text, exit-code policy
  reporting.py      text / json / markdown
  api.py            Project facade: the single programmatic surface used by cli, hook and MCP
  cli.py            argparse; stdout = payload, stderr = diagnostics
  hatch_hook.py     BuildHookInterface subclass + hookimpl registration
  mcp_server.py     MCP server (optional extra), thin adapter over api.py
```

Only `persistence.py` writes to disk. `cli`, `hatch_hook` and `mcp_server` are thin adapters
over `api.Project`, so all three front ends behave the same.

## Resolved design decisions

**Comment grammar.** This applies only to the text of `tokenize.COMMENT` tokens. The tag pattern is
`^#\s*(TODO|FIXME|HACK|XXX)(?:\[([^\]]*)\])?(?=[:\s]|$)`, case-insensitive, and the tag must
start the comment. A non-hex or wrong-length bracket raises `malformed_id` and is never rewritten.
Trailing comments (`x = 1  # TODO: ...`) are tasks without continuations. A continuation line is
the next physical line, holds only a comment, has its `#` in the same column, and has at least
2 spaces after `#`. A block ends at a blank line, a code line, another tag, an ordinary comment
(fewer than 2 spaces after `#`) or a different `#` column. The title is the text after `:`, and the
description is the continuation lines joined with `\n`.

**Annotation.** Tags get `[abcd]` inserted right after the tag word, and nothing else changes.
Files are decoded with their detected encoding and `newline=''`. After editing, each file is
re-tokenized and re-parsed before any write. A stub without an owner gets
`# TODO[id]: Implement <qualname> (detected stub)` above its first decorator, at the
decorator's indentation and using the file's newline style. One-line suites, and declarations
that share a line or sit inside continued lines, are not edited; they produce `stub_needs_review`.

**Stub ownership.** A TODO block owns a stub if its last line sits directly above the first
decorator or `def`/`class` line at the same indentation, or if it is the first comment inside
the stub's body. Either way the result is one task with `origin: "stub"`.

**Stub exclusions (all configurable).**
- `abstract*` decorators
- `overload`, in its `typing.` and `typing_extensions.` forms
- `Protocol` classes and their methods
- `.pyi` files
- empty classes whose bases are exception, enum, `TypedDict` or `NamedTuple` types (`*Error`, `*Exception`, `*Warning`, `Enum`, …)

**Suppression.**
- `# byteplan: ignore` on a declaration line or in its decorator block applies to that declaration only.
- `# byteplan: ignore` inside a tag comment suppresses that tag.
- `# byteplan: ignore-file` within the first 5 lines suppresses the whole file.

**ID seed.** `relpath \0 qualname \0 KIND \0 title \0 dup_index \0 attempt`. Files are scanned
in sorted POSIX path order and tags in line order. The used set is reserved IDs, plus IDs already
in source, plus IDs allocated earlier in the same run.

**Registry schema v1** adds `title_override`, `origin`, `stub {symbol, implemented}` and
`scope_state` to the spec's example. `last_seen` changes only when an event happens. The new file
is written only if its bytes differ from the existing one.

**Blocking states.**
- Duplicate IDs block all writes (exit 1). `repair --reassign PATH:LINE` is the explicit fix.
- An unregistered ID is reported, and `repair --import ID` registers it without editing source.

**Write safety.**
1. Take the lock at `.byteplan/scan.lock`.
2. Stage new contents in `.byteplan/txn/`.
3. Write and fsync `journal.json` with the before and after hashes.
4. `os.replace` each source file, keeping its permissions.
5. Write the registry last.
6. Delete the journal.

Any later command that finds a journal **rolls forward**. If a hash matches neither the before
nor the after value, it reports `journal_conflict` and leaves resolution to `repair`.

**Missing detection.** It runs only after a complete, error-free, un-narrowed scan, and only on
tasks inside the configured scope. Tasks outside the scope get `scope_state = "excluded"`.
`status` is never touched.

**Exit codes.** 0 means OK, 1 means findings under the check policy, 2 means a
config, runtime or registry error.

## Hatch build hook

```toml
[build-system]
requires = ["hatchling", "byteplan"]
build-backend = "hatchling.build"

[tool.hatch.build.hooks.byteplan]
scan = true
write_source = false   # false | true | "editable"
fail_build = false
allow_in_ci = false
```

- **Default behaviour:** read-only `check` semantics.
- **When it writes:** only when `write_source` permits it for the current `(target_name, version)`,
  the `CI` env var is unset (or `allow_in_ci`), and `.byteplan/tasks.json` exists.
- **Builds from an unpacked sdist:** the hook skips them.
- **sdist and wheel in one `hatch build`:** the second run is a guaranteed no-op because of idempotence,
  and a test covers it.
- **Packaging:** the hook warns `registry_packaged` if `.byteplan` isn't excluded from the sdist,
  and `byteplan init` appends that exclude to `pyproject.toml`.
- **Entry point:** `[project.entry-points.hatch] byteplan = "byteplan.hatch_hook"` is added in the
  same change as the module. Registering it earlier would break every Hatchling build in
  environments where byteplan is installed.

## MCP server

The MCP server lets AI agents and editors query and manage the registry through the same
contract as the CLI.

- **Packaging:** an optional extra, `pip install byteplan[mcp]`, built on the official `mcp` Python
  SDK (FastMCP). Pin the SDK version and check the current API at implementation time, as the spec
  requires for Hatchling. The core install stays at a single dependency.
- **Launch:** `byteplan mcp [--project PATH] [--allow-write]`, plus a `byteplan-mcp` script. It uses
  the stdio transport. If the extra is missing, the command prints how to install it and exits 2.
- **stdout:** it carries JSON-RPC only. All logging and diagnostics go to stderr, and a test
  guards this.
- **Read-only by default.** Write tools are registered only with `--allow-write`. Even then,
  source annotation needs `apply=true` on every call.

| Tool | Write? | Maps to |
|---|---|---|
| `list_tasks(status?, presence?, kind?, label?)` | no | `byteplan list` |
| `show_task(id)` | no | `byteplan show` |
| `scan(paths?, apply=false)` | only with `apply=true` | `scan --dry-run` / `scan` |
| `check()` | no | `byteplan check` (returns diagnostics + would-be exit code) |
| `missing()` / `duplicates()` | no | same-named commands |
| `report(format="json"\|"markdown")` | no | `byteplan report` |
| `set_status(id, status, note?)` | registry | `byteplan status` |
| `resolve(id, note?)` | registry | `byteplan resolve` |
| `edit_task(id, priority?, assignee?, labels?, notes?, title_override?)` | registry | `byteplan edit` |

- **Resources:** `byteplan://tasks` (the registry view as JSON) and `byteplan://tasks/{id}`.
- **Prompt:** a `triage` prompt that summarizes open, missing and stale tasks.
- **Same guarantees as the CLI:** all writes go through `api.Project` → `persistence`, so the
  lock, journal, determinism and conflict blocking all apply. A concurrent CLI scan makes MCP
  write calls fail cleanly with a `locked` error.
- **Results:** typed, JSON-serializable dicts that use the same schemas as `--format json`.
  Diagnostics come back as data, not exceptions. Exceptions are reserved for exit-code-2 errors.
- **Tests:** in-process tests through the SDK's client session over memory streams. They cover
  read-only mode hiding write tools, `scan(apply=false)` not mutating anything, preserved managed
  fields after `edit_task` and a rescan, the lock conflict, and clean stdout from a subprocess
  stdio run.

## Phases

Each phase ends green on `hatch fmt --check`, `hatch run types:check` and `hatch test --all`.

| Phase | Deliverables | Spec §12 tests |
|---|---|---|
| 0. Scaffold ✅ | pyproject (3.11+, URLs, envs, sdist excludes), CLI skeleton, smoke tests, `.gitignore`, docs/ | – |
| 1. Core | config, files, registry, ids, source + comment scanner, `api.Project`, CLI `init/scan(report-only)/list/show` | 1, 5, 19, 20 |
| 2. Write path | annotate, reconcile, persistence, duplicates/unregistered, `status/resolve/edit/missing/duplicates`, `--dry-run` | 6–17 |
| 3. Stubs | stubs, association, suppressions, `implementation_changed`, `check`, `report`, `repair` | 2, 3, 4, 17 |
| 4. Hatch | hatch_hook + entry point, `examples/hatch_build.py`, README onboarding | 18 |
| 5. MCP | `[mcp]` extra, `mcp_server.py`, `byteplan mcp`, README client config snippets | MCP tests above |
| 6 (optional) | spec §14 phase 5 items | – |

**Phase 4 tests:**
- `python -m build --no-isolation` on a `tmp_path` copy of `tests/fixtures/projects/hatch_consumer`,
  checking: read-only by default, opt-in writes reach the wheel, two builds are byte-identical,
  `.byteplan/` is absent from both archives, and `CI=1` refuses writes.
- A real isolated build is marked `network`.

**Phase 2 crash test:** make `os.replace` fail on its second call, run `scan` again, and check that
source matches the registry, no ID is allocated twice, and the journal is gone.

**Cross-platform:** fixtures with CRLF, no final newline, a BOM, latin-1 and non-ASCII text. CI runs
ubuntu, macos and windows with `hatch test --all`.
