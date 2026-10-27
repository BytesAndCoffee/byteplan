# BytePlan implementation plan

The behavioural contract is [`spec.md`](spec.md), extended by
[`spec-addendum-a.md`](spec-addendum-a.md), [`spec-addendum-b.md`](spec-addendum-b.md),
[`spec-addendum-c.md`](spec-addendum-c.md), [`spec-addendum-d.md`](spec-addendum-d.md) and
[`spec-addendum-e.md`](spec-addendum-e.md).
Addendum A covers `@todo` decorators, stub decoration, acceptance-test links, verification, and
registry-to-source cleanup. Addendum B covers test scaffolding, optional acceptance criteria,
release-stripping semantics, and the end-to-end development workflow. Addendum C covers Git
integration: staged-snapshot checks for pre-commit, a published pre-commit hook, and CI recipes.
Addendum D reframes a task as an **assignment**, a durable unit of development intent. It adds
typed links to commits, PRs, issues and tests, orthogonal state axes, external-issue intake, and
an optional "Relay" workflow for GitHub. Addendum E defines remaining RC1 hardening gates and
the proposed post-1.0 semantic graph roadmap. Proposed interfaces are not current functionality.
This document records implementation decisions and phase order. Toolchain: Hatch / Hatchling
(verified against Hatch 1.18.1, Hatchling 1.32.4).

One rule underlies everything: the disappearance of a comment, the disappearance of a stub, or a
passing test never resolves a task. Only an explicit `status`/`resolve` does.

## Active release plan — Addendum E

**Target: `v1.0.0rc1`. Core feature freeze remains in effect.**
The [release-readiness report](rc1-readiness.md) records candidate preparation evidence and
pending integration/review/artifact gates. It is not yet an approval declaration.
The [verified starting-point assessment](spec-addendum-e.md#operating-instructions-and-verified-starting-point)
records main revision `e0b66318574ef72e23c80b529fb28a825b6d12ec`, current limitations,
existing protections and unmerged review work. Reinspect the base before implementation.
The phase table later in this document is historical progress; completion there does not imply
that the new release gates have passed.

| Order / release | Deliverables | Required evidence / dependency |
|---|---|---|
| RC1-A: compatibility and reliability | Expanded IDs, schema boundary and explicit migration, collision recovery, plain-Git validation, source-safety audit, public compatibility inventory and authoritative storage decision. | E A1–A6: actual released-client interoperability, failure/recovery tests, merge matrix, risk assessment, migration procedure and compatibility matrix. Reassess PR #43 after integration. |
| RC1-B: API decomposition | Concise public facade, cohesive operations, stable imports/signatures/errors/patch targets and final module documentation. | After A integration, separate PR: full before/after suite, CLI/MCP/Hatch/Git regressions, strict types/formatting, wheel/sdist builds and platform CI. |
| RC1-C: architecture documentation | Complete Addendum E, roadmap, allocated tasks/release labels and Assignment cross-references. | Independently reviewed documentation PR; no graph implementation. May precede A/B completion. |
| RC1-F: final independent reviews | Freeze one integrated SHA for two whole-repository reviews, with independent initial conclusions. | After A/B/C integration; register findings, fix blockers with evidence, repeat affected reviews or both whole-repository reviews when conclusions are invalidated. |
| RC1-G: readiness report | Reviewed SHA, merged PRs, contracts/decisions, module boundaries, tests/platform/build/install results, review dispositions and deferred work. | All E exit criteria; explicit approval before tagging or publishing RC1. |
| 1.5: graph foundations | Semantic schema/identity, symbol/scope/import/reference/inheritance indexing, task associations, incremental rebuildable cache, uncertainty and bounded queries. | E E2/E3/E5/E6: optional indexing, no source mutation, deterministic results, dependency invalidation, checkout/move/merge and partial-failure tests. After 1.0 stable. |
| 2.0: graph intelligence | Cross-module dependencies, impact, verification recommendations, specification/Assignment traceability, bounded MCP and portable optional visualization. | E E4–E7: traceable provenance/uncertainty, no competing task authority or inferred verification claims. Depends on graph foundations and relevant Assignment capabilities. |

PR A contains compatibility changes; PR B contains structural refactoring; PR C contains future
architecture documentation and registrations. Each receives applicable checks and independent
review. Keep confirmed flaws as `FIXME`, planned/design obligations as `TODO`, allocated by
BytePlan with `release:1.0`, `release:1.5` or `release:2.0` labels. Annotations in
[Addendum E](spec-addendum-e.md) are the source locations for its new obligations; do not
duplicate them here. Future tasks stay open. Annotation disappearance never resolves work.

**Storage and identity:** the current JSON registry stays authoritative pending A3's documented
decision. Size alone does not authorize redesign. A1 preserves four-character IDs, allocates
six-character IDs, supports longer identities, prefers exact lookup before unambiguous prefixes,
and persists full identities. A2 establishes schema v2 where required before incompatible
annotation writes, superseding the older reservation for Assignments below. The active
compatibility increment and original-branch collision recovery procedure are recorded in the
[RC1 compatibility report](rc1-compatibility.md). The historical completion table does not
complete these new release gates.

**Compatibility execution checkpoint (24 October 2026):** the approved
[next-steps assessment](rc1-next-steps.md) has been executed through the remaining Track A
acceptance work: merge (`edc2`), source safety (`1b81`), storage (`4842`) and interface policy
(`8aeb`). Independent review additionally confirmed archive durability (`af82fd`) and snapshot
isolation (`c35e66`) defects; both are corrected with linked regression evidence and explicit
resolution. Missing-test and MCP diagnostic gaps (`b29c72`, `932b36`) are also resolved.
First-party scaffold formatting (`67a65c`) remains an explicitly nonblocking P3.

PR #45 is integrated after all 15 platform/quality jobs passed on `182c882`. The dedicated API
decomposition (`3844`) is implemented behind the existing public facade. Its independent review
also reproduced an inherited archive-restore integrity defect (`50ad66`): concurrent edits could
be overwritten and cached passing evidence could replace a newer canonical failure. The separate
compatibility follow-up PR #46 is integrated as `027578b` after all 15 jobs passed on `fea1d3e`.
The extracted archive operation retains the same correction, confirmed by method-body and
runtime-binding comparisons plus the restore regressions.

Final whole-repository reviews (`c053`) and the release-readiness/approval report (`a70d`) remain
later gates. The [compatibility report](rc1-compatibility.md) links acceptance maps, independent
review evidence, the storage decision and public stability policy. Its earlier pause checkpoint
retains historical evidence; it does not describe the current execution state.

**Compatibility policy:** the completed [interface inventory](compatibility-policy.md) defines
stable CLI, Python API, configuration, decorators, MCP stdio, Hatch and documented extension
contracts. Python MCP embedding remains experimental. Core identity, source safety and
authoritative state share the stable contract. Existing previews and read-only defaults are
documented without adding commands.

**Post-1.0:** optional historical phases 6c/11/11b, Assignments (12) and Relay (13) are outside
RC1. Existing Assignment task `15df` remains authoritative; its specification traceability
participates in the 2.0 roadmap without replacing the 1.5 symbol graph. This does not commit
every optional or Relay feature to a release. Simple TODO workflows remain independent of both
Assignments and graph indexing. Graph edges and MCP names are proposed, not stable API.

## Toolchain

| Task | Command |
|---|---|
| Tests | `hatch test` · `hatch test --cover` · `hatch test --all` (3.11–3.14 matrix) |
| Lint / format | `hatch fmt` · `hatch fmt --check` |
| Types | `hatch run types:check` (mypy `--strict`) |
| Build | `hatch build` |

BytePlan's own `[build-system].requires` stays `["hatchling"]` to avoid a recursive
self-build. To track BytePlan's own TODOs, run `hatch run byteplan scan`; don't use the build hook.

## Dogfooding: BytePlan manages its own development

Self-management starts now, not at Phase 10. Each phase widens what BytePlan manages about
itself.

| Milestone | What BytePlan manages about itself |
|---|---|
| **Now (with Phase 4b)** ✅ | Its own registry. `[tool.byteplan]` scopes `src/` of both packages (later also `scripts/`, `tests/` and Markdown). Real follow-ups live as tagged TODOs in the code they concern. The registry merges by task ID (`.byteplan/.gitattributes`). CI runs `byteplan check --commit HEAD` on every push and PR. |
| Phase 4b ✅ | Staged commits are checked: `hatch run byteplan git install-hooks`, or the local `.pre-commit-config.yaml`. |
| Phase 4c ✅ | BytePlan's own new TODOs get their IDs automatically when committed (`hatch run byteplan git install-hooks`, once per clone). |
| Phases 6a–6b | Its own tasks link to acceptance tests, and regression tests are scaffolded with `tests scaffold`. |
| Phase 9 | Coding agents developing BytePlan query it over MCP for outstanding work, record evidence, and hand the next session an authoritative state snapshot. |
| Phase 10 ✅ | A documented, fully integrated self-managed workflow ([CONTRIBUTING.md](../CONTRIBUTING.md)): commit hooks and merge drivers, auto-scaffolded `@verifies` placeholders, evidence before `resolve --sync-source`, `byteplan.md` regenerated on `main`, MCP for agents. CI on ubuntu, macOS and Windows. |
| Phase 12 | Assignments link the commits, PRs and evidence produced by BytePlan's own development. |
| Phase 13 | Relay for GitHub runs BytePlan's own issue-to-PR lifecycle, as the reference demonstration. |

**Found by dogfooding.** Ruff's flake8-todos rule TD004, which Hatch's defaults enable, flags
BytePlan's own `TODO[id]:` syntax because it expects the colon right after the tag. The syntax
stays, since the spec mandates it and `TODO(…)` is reserved for the planned owner syntax. The
README documents `lint.extend-ignore = ["TD004"]`, and BytePlan uses that itself. A future
`byteplan init` could detect TD004 in the project's ruff config and suggest the ignore.

**Workflow today:**
- After editing, run `hatch run byteplan scan`, then commit the source together with
  `.byteplan/tasks.json`.
- Run `hatch run byteplan git install-merge-driver` once per clone.
- Resolve work explicitly with `hatch run byteplan resolve ID`. Removing a TODO only makes it
  `missing`.

## Module layout

The repository root is the `byteplan` devtool project. The runtime distribution is a separate
Hatch project nested in it, with its own `pyproject.toml`, tests and release cycle. It's excluded
from `byteplan`'s sdist; `byteplan`'s wheel only ever contains `src/byteplan`.

```
./                              devtool distribution "byteplan" (src/, tests/, docs/)
byteplan-runtime/               runtime distribution "byteplan-runtime" (Addendum A, see below)
```

```
src/byteplan/
  models.py         frozen dataclasses + enums (Task, SourceRef, HistoryEvent, Edit, Diagnostic, ...)
  config.py         [tool.byteplan] via tomllib, defaults, validation, project-root resolution
  files.py          scope collection: pathspec include/exclude, .gitignore, symlink policy, sorted
  ids.py            shake_128 24-bit candidates, legacy/long ID validation, exact-first UI prefixes
  scanner/
    source.py       bytes -> detect_encoding (BOM / PEP 263) -> text + newline style
    symbols.py      ast declarations, qualnames, line -> symbol
    comments.py     tokenize-based tags and continuation blocks (pure)
    decorators.py   static @todo / @verifies discovery with import-alias resolution (pure)
    stubs.py        ast-based stubs, exclusions, suppressions (pure)
    association.py  pair comments / decorators with stubs -> one obligation each
  edits.py          span edits: apply in memory, re-tokenize, re-parse, AST-equivalence guard
  annotate.py       ID insertion for comments ([abcd]) and decorators (id="abcd")
  normalize.py      comment -> decorator, stub -> decorator, import insertion (sync)
  cleanup.py        removal of resolved/dismissed managed annotations (sync)
  release.py        release strip of runtime decorators/imports + registry record, and restore
  reconcile.py      pure: (registry, scan, scope, clock) -> (registry', edits, diagnostics)
  registry.py       JSON load / validate / migrate / deterministic serialize
  verification.py   test links, pytest runner, evidence store, readiness, freshness
  scaffold.py       pure planner for failing acceptance-test skeletons (path, name, template, conflicts)
  persistence.py    lock, staged writes, journal, atomic replace, roll-forward recovery
  diagnostics.py    codes, severity, remediation text, exit-code policy
  reporting.py      text / json / markdown
  api.py            stable Project facade, configuration/snapshots and guarded transaction boundaries
  _api_types.py     canonical public result types and sentinel, re-exported through api.py
  operations/       internal scan/task/verify/scaffold/release/sync/archive/init orchestration
  cli.py            argparse; stdout = payload, stderr = diagnostics
  hatch_hook.py     BuildHookInterface subclass + hookimpl registration
  snapshot.py       read-only Snapshot sources: working tree, Git index, Git commit
  gitio.py          Git plumbing wrapper (rev-parse, ls-files -z, cat-file --batch); never writes
  mcp_server.py     MCP server (optional extra), thin adapter over api.py
  _verify_plugin.py pytest plugin injected into `verify` runs (pytest-only imports)
```

Project file writes use `persistence.py`; `cli`, `hatch_hook` and `mcp_server` remain thin
adapters over `api.Project`. The [facade/operations architecture](api-architecture.md) documents
the internal boundaries, preserved patch targets and validation. Leaf modules retain their
existing algorithms; the facade and internal operations share one canonical set of result types.

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

Existing lock markers fail closed, including dead-looking PIDs. Automatic stale-lock removal
can delete a newer writer's lock between inspection and unlink. For deliberate recovery,
stop all writers, confirm none is running, remove only the stale lock marker and retry the
authorized write while preserving `.byteplan/txn/` and its journal/copies.

Any later command that finds a journal **rolls forward**. If a hash matches neither the before
nor the after value, it reports `journal_conflict` and leaves resolution to `repair`.

**Scope.** Only regular `.py` files are collected. Symlinked files and directories are never
followed, so a file can't be scanned twice or reached from outside the root. `.gitignore` files
from the Git top level (which may be above the project root) down to each file are respected.
`.git/info/exclude` and global excludes are not read. Directories are pruned when an exclude
pattern matches everything under them.

**Not yet recognized.** Google-style `TODO(owner): ...` comments don't match the tag grammar.
Supporting them, by mapping the owner to `assignee` on creation, is a candidate follow-up.

**Missing detection.** It runs only after a complete, error-free, un-narrowed scan, and only on
tasks inside the configured scope. Tasks outside the scope get `scope_state = "excluded"`.
`status` is never touched.

**Concurrent modification.** Every file's bytes are hashed when a scan or sync reads them. Just
before staging, each target is re-read. If any hash changed, the whole run aborts with
`concurrent_modification` and writes nothing. The journal's before-hashes extend the same check
to the replace step (addendum test 18).

**History events (Phase 2).**
- `created`, `moved` (path or symbol changed; line-only shifts aren't events), `text_changed`,
  `missing`, `reappeared`, `resolved`, `status_changed`, and `edited` (old/new of each changed
  managed field). An optional `note` is recorded on `status`/`resolve`.
- `last_seen` is set only when a task seen in source gets an event.
- A `missing` diagnostic is reported for open and in-progress tasks only. A resolved or dismissed
  task whose annotation is gone is simply finished.
- A dry run or read command that finds an interrupted write reports `pending_journal` and leaves
  it alone. Only write commands (`scan`, `status`, `resolve`, `edit`) roll it forward, under the lock.
- `--project` and `--format` go after the subcommand, e.g. `byteplan scan --project PATH`.

**Found trialling BytePlan on bytesim.**
- **Interfaces and overrides.** Stub detection now consults a project-wide class index
  (`scanner/hierarchy.py`). A trivial method isn't a stub when a project subclass, transitively,
  defines the same name (interface by convention), or when a project ancestor does (deliberate
  no-op override). The index always covers the full scope, even for narrowed scans. Classes match
  by simple name, which can only mask a stub, never invent one. `detect.respect_overrides`
  switches it off.
- **Result on bytesim:** 9 false annotations became 1. The remaining one is a duck-typed hook with
  no declaring base, which is left to an explicit `# byteplan: ignore`.
- **`init` packaging warning:** it now follows Hatch's `only-include`, `include` and `exclude`
  rules, so an explicit `include` list that omits `.byteplan` no longer triggers it.

**Phase 3 decisions.**
- **Stubs:** a docstring-only body counts as a stub (spec: "effectively empty").
  `placeholder_assignments = true` is rejected with "not supported yet" rather than silently
  ignored.
- **Ownership:** a comment among a declaration's decorator or header lines, or anywhere in a stub's
  body, owns that declaration, in addition to a comment directly above it. A comment in a real
  (non-stub) body is a statement-level task.
- **Observing edited files:** after writing IDs, a scan observes the *edited* text. Lines added
  above an annotation (a stub comment, or a new `id=` line) therefore don't show up as relocations
  on the next scan.
- **Inserting `id=`:** the ID goes right after the last argument. It's refused
  (`decorator_needs_review`) when anything other than whitespace, comments and one comma sits
  before the call's closing parenthesis, e.g. a parenthesized title.
- **`[tool.byteplan.annotations]`:** for now holds only `runtime_modules`. `mode` and the other
  conversion keys arrive with Phase 5.
- **`@verifies` links:** discovered and validated now (`unknown_task_reference`, `malformed_id`),
  but stored in the registry only from Phase 6a.
- **`repair --reassign`:** ordinary duplicate-copy repair requires a duplicated annotation.
  Addendum E adds explicit `--against REV` recovery for independently created branch collisions,
  preserving the original branch's record and stale evidence before merging; shared/inherited
  identity is rejected. Both support `--dry-run`. `PATH:LINE` is root-relative first, as diagnostics print it.

**Exit codes.** 0 means OK, 1 means findings under the check policy, 2 means a
config, runtime or registry error.

## Addendum A decisions

### Runtime distribution: a separate `byteplan-runtime` package

**Decided:** publish a separate pure-Python, zero-dependency distribution named `byteplan-runtime`
(import name `byteplan_runtime`). It is built from `byteplan-runtime/` in this repository and
versioned separately with a frozen API. Projects can use a local shim module instead.

- **Why a separate package:** application code imports the decorator at runtime. A separate package
  keeps the devtool's dependencies (pathspec, and later the MCP SDK) out of production installs.
- **Why the shim option:** some projects won't accept any new runtime dependency.

```python
def todo(title: str, /, *, id: str | None = None, kind: str = "TODO", description: str = "",
         test: str | None = None, tests: Sequence[str] = ()) -> Callable[[T], T]: ...
def verifies(*ids: str) -> Callable[[T], T]: ...
```

Both return a function that returns its argument unchanged (`obj is decorated`). They don't
validate, register, wrap, read files or log. Bad arguments can never break an import in
production; the static scanner reports them instead.

**Recognized imports.** The scanner treats a decorator as BytePlan's only when it resolves to one
of `[tool.byteplan.annotations] runtime_modules`. The default is `["byteplan_runtime"]`; a shim
such as `"myproj._byteplan"` is added there. Recognized forms are module-level
`from M import todo [as x]`, `import M [as y]` used as `@y.todo(...)`, and the same inside
`if not TYPE_CHECKING` / `try` blocks. A local `def todo`, a rebinding, or a star import makes the
name ambiguous: the decorator is reported as `unresolved_todo_decorator`, and no task is created.

`byteplan init --runtime-shim PATH` writes a 10-line shim module for projects that won't add a
dependency.

**Deviation from the addendum's example:** a converted comment's continuation text goes in
`description=`, and a non-TODO tag kind goes in `kind=`. The addendum embedded both in the title
with `\n`. The separate keywords round-trip exactly, and they keep the kind in source even if the
registry is lost.

### Decorator discovery

- **One task per decorator.** Each `@todo(...)` on a `def`, `async def` or `class` is one task, and
  stacked `@todo`s are independent tasks.
- **Literal arguments only.** Arguments must be literals: string constants (including implicit
  concatenation), `None`, and tuples or lists of strings for `tests`.
- **`test` and `tests` together** produce `conflicting_test_arguments`.
- **Dynamic arguments** produce `dynamic_todo_argument`. If `id=` is a literal, the task still
  counts as present, so a dynamic title can't make it go missing. Fields that can't be read keep
  their previous registry values.
- **Allocating an ID** inserts `id="abcd"` as the last keyword before the closing parenthesis. The
  parenthesis position comes from `tokenize`, and the edit keeps a trailing comma and multi-line
  layout: a new line at the argument indentation when the call spans lines, `, id="abcd"` inline
  otherwise.
- **Location fields.** `source` gains `decl_line`, `attachment_kind`
  (`function | method | class | module | statement`) and `representation` (`comment | decorator`).
  `line` is the annotation's line. The ID remains the only identity key.

### Edit engine: span edits plus an AST-equivalence check (no libcst)

**Decided:** keep the span-edit approach from Phase 2 and add a stronger check, rather than adding
libcst.

- **Why not libcst:** it's a heavy compiled dependency and its grammar can lag new Python releases.
- **How edits work:** they're `(start, end, replacement)` spans computed from `tokenize`/`ast`
  positions. They are applied in memory using the file's newline style and encoding, never by
  regex over the whole file.
- **The check (`edits.verify_equivalent`):** after every edit, `ast.dump(new)` with BytePlan's own
  decorators and imports removed must equal `ast.dump(old)` with the same removal. An edit that
  could change program behaviour therefore can't be written.
- **What never changes:** shebang, encoding cookie, BOM, CRLF, final-newline state, docstring
  position and `__future__` imports.
- **Where imports go:** after the module docstring and any `__future__` imports, before the first
  other statement.

### Annotation modes

```toml
[tool.byteplan.annotations]
mode = "comment"                 # comment | preserve | decorator
convert_attached_comments = false
auto_decorate_stubs = false
remove_resolved = false
runtime_modules = ["byteplan_runtime"]
```

| Mode | Untagged comment | Unowned stub | Author-written `@todo` |
|---|---|---|---|
| `comment` (default) | `[abcd]` inserted | `# TODO[abcd]: ... (detected stub)` inserted | gets `id=` |
| `preserve` | `[abcd]` inserted | reported only, `stub_needs_review` | gets `id=` |
| `decorator` | `[abcd]`; converted by `sync` if `convert_attached_comments` | `@todo(...)` by `sync` if `auto_decorate_stubs` | gets `id=` |

**Two commands with separate jobs:**
- `scan` only discovers, inserts IDs and reconciles the registry.
- Structural rewrites (conversion, stub decoration, cleanup) happen only in `sync --apply`.

**Conversion is refused** (`conversion_needs_review`) when any of these hold:
- the runtime isn't available, meaning neither `byteplan-runtime` is in `[project].dependencies`
  nor a configured shim module is in scope
- an import would have to be inserted in an unsafe place
- the comment isn't attached to exactly one declaration
- the comment is module-level, trailing, inside a body, or separated by a blank line

A refused conversion leaves the comment exactly as it was.

### Acceptance tests and verification

**Where links come from.** Links are pytest node IDs (`path::name[::name][param]`), from:
- `@todo(tests=...)` or `@todo(test=...)`, with provenance `decorator`
- `@verifies("abcd")` on a test, with provenance `verifies`
- `@pytest.mark.byteplan("abcd")`, with provenance `marker`, only when
  `[tool.byteplan.tests] pytest_marker = true`, which also registers the marker through the plugin
- `byteplan tests add/remove`, with provenance `managed`

**How links are stored.** Each task gets `tests.managed` (written only by the CLI or MCP) and
`tests.discovered` (a list of `{node, provenance, path, line}`). `tests.discovered` is recomputed
on full scans; narrowed scans only replace entries from the paths they covered. A scan never
touches `managed`. The effective set is the deduplicated union, and each entry keeps all of its
provenances.

**Diagnostics.** `@verifies` with an unknown ID produces `unknown_task_reference`. A malformed
node ID produces `malformed_test_id`. A test file that isn't in scope produces `test_not_in_scope`.

**Runner.** `verify` runs `[*runner, "-p", "_byteplan_verify_plugin", *node_ids]` as an argument
list (never through a shell), with the project root as the working directory.
- **Default runner:** `[sys.executable, "-m", "pytest"]`. It can be configured as an argument list,
  e.g. `["hatch", "test", "--"]`.
- **The plugin:** a standalone file that imports only pytest. It's copied to a temporary directory
  that's put first on `PYTHONPATH`, so it loads in the project's test environment even when
  BytePlan is installed somewhere else.
- **Reading results:** the plugin records each node's outcome from `pytest_runtest_logreport`
  (including `wasxfail`) and `pytest_collectreport`, which junitxml can't distinguish for
  xpass/xfail.
- **Timeout:** configurable (default 300 s). On timeout the whole process group is killed, and
  unfinished nodes are recorded as `timeout`.

**Outcomes.** Each test's outcome is one of `passed`, `failed`, `skipped`, `xfailed`, `xpassed`,
`error`, `not_found`, `not_run`, `timeout` or `stale`. A node that was requested but never
collected is `not_found`. Only `passed` counts as positive evidence; `xpassed` is reported but
not counted.

**Where evidence is stored:** `.byteplan/verification.json`, separate from `tasks.json`.
- Only `verify` writes it, so scans can never churn it.
- It's serialized deterministically and committed by default so teammates share evidence. Projects
  can gitignore it.
- Per test it stores the outcome, duration (ms) and up to 1 KB of failure text, plus run metadata:
  runner argv, Python version, UTC time, `git rev-parse HEAD`, a dirty flag, and a fingerprint.

**Freshness.** The fingerprint is a sha256 over the task's source file and each linked test file.
A result is `stale` when the current fingerprint differs from the stored one.
- **Why a fingerprint rather than Git HEAD:** it's precise to the relevant files and works without
  Git or with a dirty tree.
- **Its limit:** it can't see changes in imported helpers. Reports state this, and
  `[tool.byteplan.tests] stale_on = "head"` gives a stricter mode where any HEAD change or dirty
  tree makes results stale.

**Readiness** is computed, never stored, and is independent of `status`:

| Readiness | Condition |
|---|---|
| `unverified` | no linked tests, or none run |
| `failing` | any fresh `failed`/`error`/`timeout` |
| `needs_review` | fresh results include `skipped`/`xfailed`/`not_found`, any result is stale, or the declaration is still a stub |
| `ready_for_review` | every linked test is fresh `passed`, none is still a scaffold placeholder, and the declaration is not a stub |

`verify --ready` lists `ready_for_review` tasks. Nothing is ever resolved automatically.

**Stub-change advisories.** When a declaration that was a stub stops being one,
`implementation_changed` is logged once. If its linked tests are also fresh `passed`, the
diagnostic is `implementation_complete_candidate`. Both are advisories only.

### Registry-to-source cleanup

- **Resolving doesn't touch source.** `resolve` and `status` only change the registry.
  `resolve --sync-source` is the same as `resolve` followed by `sync --apply --only ID`.
- **What `sync --apply` removes:** the managed annotations of resolved or dismissed tasks, when
  `remove_resolved = true` or `--remove-resolved` is passed.
  - For a comment, that's the exact tag line plus its discovered continuation lines.
  - For a decorator, that's the decorator's full span, but only when it occupies whole lines by
    itself.
  - A `byteplan_runtime` import is removed only when the AST shows no remaining references to it.
  - Adjacent comments, other decorators, bodies and tests are never touched; the
    AST-equivalence check enforces this.
  - The reserved ID, the last `source` reference and the history are kept. A `cleaned` event is
    logged.
- **Cycle guard.** If a resolved task's declaration still matches the stub heuristics, the
  diagnostic is `resolved_but_stubbed` and cleanup is refused for that task. `--suppress-stubs`
  replaces the annotation with `# byteplan: ignore` on the declaration line (a visible, persistent
  suppression). The alternative is to implement the stub.
- **Manual deletion** of an annotation still produces `missing`, never `resolved`.

### Release stripping: `byteplan release` / `byteplan restore`

`byteplan release` strips BytePlan's runtime decorators from the working tree **in place**, so a
commit you make from that tree, and every artifact built from it, has no `byteplan_runtime` import.
The registry records exactly what was removed and where. `byteplan restore` puts every decorator
back. Stripping is a description of a deliberate source transformation. It isn't resolution, it
isn't disappearance, and it isn't verification evidence: no task changes `status`, and none becomes
`missing`.

**What BytePlan does not do** (Addendum B §B5.1). `release` prepares the tree and records what it
did. It never runs `git commit`, `git tag`, `git reset`, a build, the test suite or a publish, and it
never marks tasks resolved. It doesn't claim to leave a clean Git tree: it deliberately changes
tracked files, and `git status` shows that.

> **Revision note.** An earlier draft of this plan made the default an automated "branch mode": a
> temporary worktree, an automatic commit on `release/<version>`, an optional tag, and a smoke test
> on by default. Addendum B §B5 settles it the other way: in-place stripping plus a separate
> restore, no Git or build operations, and an opt-in smoke test. That draft's goal, keeping
> strip/restore churn off the development line, is kept below as a documented workflow that you run
> yourself.

#### Supported Git workflow (documented, not automated)

The stripped and decorated forms are two snapshots of the same code. If they took turns on `main`,
history would get a strip commit and a restore commit for every release, plus merge conflicts on
decorator lines. Releasing from a short-lived release branch avoids that:

```console
$ git switch -c release/1.2.0            # from a clean main
$ byteplan release --version 1.2.0       # strip in place; registry records it
byteplan: stripped 14 decorators (12 @todo, 2 @verifies) and 5 imports from 9 files
byteplan: registry marked stripped for release 1.2.0
byteplan: next: review `git diff`, commit, tag, build; then switch back to your development branch
$ git commit -am "Release 1.2.0" && git tag v1.2.0 && hatch build
$ git switch main                        # main never had the strip: nothing to restore
```

- **`main` and its registry never change.** The "where were the decorators" record lives in the
  release commit's registry, which is the snapshot it describes.
- **Hotfixes:** fix on `main` and cherry-pick onto the release branch. Stripping removes only whole
  decorator lines, so ordinary fixes apply cleanly.
- **`restore`** is for in-place use without a branch (strip, build, then restore before
  committing), and for getting a decorated tree back on a release branch for local debugging.
- **Expected diffs:** after a restore, `git status` shows the expected decorator diffs relative to a
  stripped commit. BytePlan reports them and never commits or resets them.
- **Default-branch guard:** `release` warns `release_on_default_branch` when run on the repository's
  default branch, pointing to this workflow. It doesn't refuse.

#### Smoke test (opt-in: `--smoke-test`)

The static rule "no remaining runtime-module references" is necessary but not sufficient. With
`--smoke-test`, `release` also checks that the stripped tree produces a working wheel. Because this
builds and imports code, it never runs without the flag.

1. Build a wheel from the stripped tree into a temporary directory with the project's own backend
   (`python -m build --wheel`). Nothing is written to `dist/`.
2. Create a temporary venv with no `byteplan-runtime`, install the wheel (dependencies resolved
   normally; `--offline` uses `--no-index` with `--find-links` if configured), and assert that
   `byteplan_runtime` is not importable there.
3. Import each top-level package/module the wheel installs, read from its `RECORD`, or the list
   `[tool.byteplan.release] smoke_imports`, in a subprocess with a timeout.

If it fails, the stripped tree is restored automatically from the just-written records, so the
release is all-or-nothing, and the import traceback is reported. The release block records
`smoke_test: "passed" | "not_run"`.

**Design principle: refuse what can't be proven safe.** Release doesn't have to understand
every Python program. It only has to refuse any transformation it can't establish as safe:
- If an import can't be proven unused, it's kept.
- If keeping it means the release would still depend on the runtime, the release is refused
  with a diagnostic (`release_needs_review`). It never ships something that breaks on import.

PR #32's thirteen Codex review rounds (20 findings) converged on this contract. Examples:
- wildcard imports
- re-exports reached through aliases, escaped modules or escaped parent packages
- `__all__` mutations
- non-literal decorator arguments
- relative or parent-package imports of the runtime

Each class closed as a refusal rule rather than deeper analysis. New findings should be judged
against it: a missed refusal is a defect, an unhandled exotic form that's already refused is
not.

**What is stripped:**
- every recognized `@todo(...)` and `@verifies(...)` decorator
- every import of a `runtime_modules` module that's unused once those decorators are gone

Tagged `# TODO[abcd]` comments stay, because they have no runtime cost. Other decorators, comments
and code are never touched, and the AST-equivalence check enforces this. Afterwards the stripped
tree must contain **no** remaining reference to a runtime module (for example
`byteplan_runtime.todo` used as a plain value). Otherwise the release is refused, since
production code would fail to import.

**When it refuses.** The release is all-or-nothing, and nothing is written if any of these hold:
- the Git tree is dirty (override with `--allow-dirty`, so the strip is the only change in what
  you commit)
- a journal is pending
- the full scan fails or has blocking diagnostics
- any `@todo` lacks an `id=` (`untagged_decorator`: run `scan` first)
- any decorator shares a line with other code (`release_needs_review`)
- the tree is already stripped

**Registry record.** It's written in the same journaled transaction as the source edits.
- **Top-level `release` block:** `state` (`stripped`), `version`, `stripped_at` (UTC), and
  `files` (path → sha256 of the stripped content).
  - The version comes from `--version`, or `[project].version`, or from Hatchling's metadata for a
    dynamic version.
- **Per-task `stripped` record**, one entry per decorator, containing:
  - path, annotation line and declaration line
  - the symbol's qualname
  - the decorator's index within its decorator stack
  - the exact original source text, including indentation and newline style
- **Per-file `imports` entries:** each removed import line's exact text and its position (the line,
  plus the statement before it as an anchor).
- **Status and events:** each affected task gets `presence = "stripped"`, a new presence value
  meaning "deliberately absent from source; location on record". A `stripped_for_release` event
  records the version.

**Behaviour while stripped:**
- **`scan`** still works. Stripped tasks are never marked `missing`, and their decorator-derived
  fields (title, description, and test links from `@todo(tests=)` / `@verifies`) are frozen at
  their recorded values.
- **Refused commands:** `sync`, write-mode Hatch builds, and a second `release`, with the
  diagnostic `release_stripped`.
- **`check` and `list`** show the stripped state, and `show ID` prints where the decorator was.

**Restore** re-inserts the recorded decorators and imports, then validates with re-parse and AST
equivalence.
- **Fast path:** if a file's hash still matches the recorded stripped hash, restore uses the
  recorded line positions. The restored file is then byte-identical to the pre-release file.
- **If the file changed after the release** (a version bump, a hotfix): each decorator is anchored
  by qualname and stack index through the AST, and each import by its anchor statement. Line
  numbers are not used.
- **When something can't be placed:** if a symbol can't be found or is ambiguous, restore refuses
  the whole operation with `restore_conflict` for each affected entry, and the stripped records stay
  intact. `--partial` restores the entries it can resolve and leaves the rest on record. Nothing is
  ever dropped.
- **After a restore:** tasks go back to `present` with a `restored` event. The `release` block moves
  to a bounded `releases` history (version, stripped_at, restored_at, counts), and the per-task
  `stripped` records are cleared.

**Dependency guidance.** With this workflow, production code no longer imports the runtime.
- **Where to declare it:** `byteplan-runtime` belongs in a development dependency (a
  `[dependency-groups]` entry or a Hatch environment's `dependencies`), not in
  `[project].dependencies`.
- **What counts as "available":** the conversion check from Addendum A counts development
  dependencies too.
- **Leftover dependency warning:** when `release` strips everything but `byteplan-runtime` is still
  a project dependency, `check` warns `runtime_dependency_in_release`.
- **Build guard:** the Hatch hook gains `require_stripped = true` (default false). For standard
  wheel/sdist builds it fails the build when recognized decorators are present. This guards against
  shipping an unstripped tree by mistake.

### Schema

These fields originally shipped in `schema_version` 1, since released with real data in 0.1.0
and 0.2.0. The original pre-release rationale is not a current compatibility policy. Addendum E
A2 now requires a tested compatibility boundary and explicit migration for expanded identities.
These existing fields are optional on read and always
written. They are `source.decl_line`, `source.attachment_kind`, `source.representation`,
`tests.managed`, `tests.discovered`, `origin` (adds `decorator`), presence `stripped`, task
`stripped`, and the top-level `release` and `releases` blocks. Verification data lives in
`verification.json`, not in tasks.

## Addendum B decisions

Addendum B is infrastructure, not a methodology. It supports TDD, ATDD and backlog-driven work
through one task identity, and every part can be adopted on its own: comments only, without tests,
and without MCP are all fully supported. The documentation won't claim BytePlan does Domain-Driven
Design or any other `*DD` practice.

### Test scaffolding: `byteplan tests scaffold ID` (planned, Phase 6b)

`tests scaffold` creates a **deliberately failing** pytest test bound to a task. A pure planner
(`scaffold.py`) decides the file, name and template. Writes go through the same lock, journal,
hash checks and AST validation as every other source edit.

**Auto-scaffolding** (added after Phase 9): `[tool.byteplan.tests.scaffold] auto = true` makes
a writing working-tree `scan` call `scaffold_test` for each task in `summary.added` that is open,
unlinked, and in a `.py` file outside `directory` (after the scan's lock is released, like auto
archiving). Failures (e.g. `scaffold_needs_path`) are reported per task and never fail the scan.
Snapshot scans, including the commit hook, never scaffold: a new test file there would be
left unstaged.

```python
import pytest
from byteplan_runtime import verifies


@verifies("a83f")
def test_router_advertise_routes():
    """Acceptance test scaffold for BytePlan task a83f.

    Target: Router.advertise_routes (method)
    Requirement: Implement poisoned reverse
    """
    # GIVEN: TODO - arrange the state this requirement depends on
    # WHEN: TODO - exercise Router.advertise_routes
    # THEN: TODO - assert the required result
    pytest.fail("BytePlan a83f: acceptance test not implemented")
```

**Zero false greens.** The body always ends in an unconditional `pytest.fail(...)` whose message
starts with `BytePlan <id>: acceptance test not implemented`.
- **No body that passes:** never `pass`, `...`, a bare docstring or `assert True`.
- **Skip/xfail only on request:** `--policy xfail` or `--policy skip` produce those outcomes, and
  neither counts as evidence.
- **No invented behaviour:** GIVEN/WHEN/THEN lines are comments, never synthesized assertions,
  fixtures, constructor calls or imports of the target.
- **The `# GIVEN: TODO - …` lines are not tasks.** A tag must open the comment, and these open with
  `GIVEN`/`WHEN`/`THEN`, so a scaffold never creates new tasks. A Phase 6b test checks this.

**Placeholder detection is static.** A test whose body, after the docstring and comments, is only
that `pytest.fail` call is a **scaffold placeholder**.
- Scans mark its link `placeholder: true`.
- `verify --ready` never treats it as ready.
- `check` reports `scaffold_placeholder` (info).
- Editing the body is all it takes to stop being a placeholder; no flag has to be cleared.

**Target file.** The defaults are in `[tool.byteplan.tests.scaffold]`:
- **Location:** `directory = "tests"`, `filename = "test_{module}.py"`. So `src/pkg/routing.py` maps
  to `tests/test_routing.py`. `mirror = true` maps to `tests/pkg/test_routing.py` instead.
- **Ambiguous names:** if two in-scope modules share a stem and `mirror` is off, the result is a
  `scaffold_needs_path` diagnostic asking for `--path`. BytePlan doesn't guess.
- **Tasks with no source file** get `tests/test_byteplan_tasks.py`.
- **`--path FILE`** overrides the location; it must be in scope and inside the project.

**Test name.** It's `test_` plus the snake-cased qualname, without `<locals>`. For example,
`Router.advertise_routes` becomes `test_router_advertise_routes`, and a TODO with no symbol becomes
`test_task_<id>`.
- **Collisions:** if the name is already used in the target file, `_<id>` is appended, then `_2`,
  `_3` and so on.
- **`--name`:** must be a valid, unused `test_*` identifier.

**Templates by target kind.**
- **Function or async function:** a plain synchronous test. An `async def` test is generated only
  when `async_tests = "pytest-asyncio"` or `"anyio"` is configured; that adds the matching marker.
  This way a missing plugin can never silently skip the scaffold.
- **Method or property:** a comment names the owning class and says an instance is needed. No
  fixture is invented.
- **Class:** a behaviour-level test; there's no assumption that the constructor can be called.
- **Module-level TODO:** a generic test bound to the task ID.
- **Every kind:** the task's acceptance criteria, if any (below), go in as GIVEN/WHEN/THEN hint
  comments.

**Link style.** `link_style = "verifies"` is the default.
- **`verifies`** adds `@verifies("id")` and the runtime import. It needs the runtime to be
  available, as a development dependency or a configured shim. Otherwise the result is
  `runtime_unavailable` with the two alternatives below.
- **`marker`** uses `@pytest.mark.byteplan("id")` and needs `pytest_marker = true`.
- **`managed`** adds no decorator and records the node ID in `tests.managed`.

All three can be found statically.

**Editing an existing test file.** BytePlan appends the function at the end with two blank lines,
using the file's newline style. It inserts `import pytest` or the runtime import only if missing,
after the existing top-level imports. The AST check is extended so that the old module body must
equal the new one, minus the added imports and the added function. Existing tests can't be altered.
A new file goes through the journal as a create; a file that exists by then is a concurrent
modification.

**Idempotence.** If the task already has a linked test (discovered, managed, or a placeholder), it
reports that test and writes nothing. `--force-new` adds another distinct test, still
collision-free.
- **Registry record:** a `test_scaffolded` event with path, node ID and policy. The link carries the
  provenance of the decorator plus `scaffold: true`.
- **Generated code is never stored in the registry;** the source file is authoritative.
- **Repeating it with unchanged inputs** creates no new file, function, link, event or timestamp.

### Acceptance criteria and planning links (optional, Phase 6c)

These are registry-managed planning metadata, separate from verification metadata.
- **Criteria:** a task can carry `acceptance_criteria: [{id: "ac1", text, verification: [node IDs]}]`.
  The minimum is the text entries. The criterion-to-test `verification` list is a later, optional
  step.
- **Managing them:** `byteplan criteria add/list/edit/remove ID`. Scans never touch them.
- **No implied satisfaction:** a criterion is never shown as satisfied because some other test
  passed. Readiness stays per task (Addendum A); per-criterion status appears only once
  criterion-to-test links exist.
- **Dependencies:** `depends_on: [ids]`, managed with `edit --depends-on/--no-depends-on`.
  `list --blocked-by` and the reports show them. Nothing is enforced automatically.
- **Scheduling:** these never hold up the scanner or scaffolding work. Phase 6c can ship after 6b.

### Lifecycle vocabulary (Addendum B §B4)

The reports describe a task with these computed facts, which are kept separate from `status`:

| Fact | Source |
|---|---|
| discovered | an ID and a source reference exist |
| planned | any managed field is set (priority, owner, labels, notes, criteria, dependencies) |
| test scaffolded | a linked test is still a scaffold placeholder (not evidence) |
| implemented (heuristic) | the attached declaration no longer matches the stub detector |
| verified | every linked test is fresh `passed` on the current fingerprint, and none is a placeholder |
| ready for review | the computed readiness (Addendum A), never stored |
| resolved | only the explicit `status`/`resolve` transition |

`missing`, `stripped`, `resolved` and `verified` are reported as distinct facts and never inferred
from one another.

### Releases and unfinished scaffolds (Addendum B §B5.2)

- **Stripping keeps scaffolds failing.** A scaffold's `@verifies` may be stripped by `release`, but
  its `pytest.fail` stays. Stripping never turns an unfinished test into a passing one.
- **Warning when an sdist would ship them:** `release` and `check` warn
  `unfinished_scaffold_in_sdist` when placeholder tests would go into the sdist.
  - The file list comes from Hatchling's own sdist file selection when Hatchling is importable.
  - Otherwise BytePlan conservatively assumes `tests/` is included.
- **Wheels and tests are independent.** Wheel contents are unaffected, since tests are normally not
  packaged. Test packaging follows the project's own build config; BytePlan only reports.

## Addendum C decisions: Git lifecycle

*The committed backlog must describe the committed code.* Git integration is an adapter: the
same scanner, association, reconciliation and diagnostics run over a different read-only
**snapshot**. No rule is duplicated per integration.

### Snapshot abstraction (planned, Phase 4b)

`api.Project` gains a snapshot parameter. Every read currently done directly against the
filesystem goes through it.

```python
class Snapshot(Protocol):
    label: str                                  # "working tree", "index", "commit 3f9c2e1"
    def read(self, rel: str) -> bytes | None    # project-relative POSIX path; None if absent
    def entries(self) -> Iterable[Entry]        # (rel, kind: file | symlink | submodule)
```

- **`WorkingTree`:** today's behaviour, and the only writable snapshot.
- **`GitIndex`:** the staging area.
- **`GitCommit(rev)`:** for CI and the base...head delta.

Scope collection (`ScopeMatcher`), config loading, registry loading and `.gitignore` reading all
take their bytes from the snapshot. A staged check therefore uses the **staged** `pyproject.toml`,
the **staged** `.gitignore` files and the **staged** registry. It never mixes in working-tree
copies. Symlinks (mode `120000`) and submodules (`160000`) are skipped, exactly as the
working-tree walk skips symlinks. Scans over non-working-tree snapshots are always dry runs.

### Git plumbing (`gitio.py`)

- **Locating things:** `git rev-parse --show-toplevel` gives the repository root. The project
  root's offset inside it maps index paths (top-relative) to project-relative paths. Monorepos and
  this repository's nested `byteplan-runtime/` both work.
- **Listing the index:** `git ls-files --stage -z --full-name -- :(top)<project-dir>`, parsed as
  `<mode> <oid> <stage>\t<path>\0`.
  - NUL-delimited, so spaces, newlines and non-ASCII names are handled.
  - Any entry with stage ≠ 0 means an unresolved merge, giving `unmerged_index` (exit 2).
- **Reading contents:** one `git cat-file --batch` process reads every blob by OID, never the
  working-tree file. A staged file is therefore checked even when the unstaged version has a
  syntax error.
- **Truly read-only:** every invocation runs as `git --no-optional-locks` with
  `GIT_OPTIONAL_LOCKS=0`, and only uses `rev-parse`, `ls-files`, `ls-tree` and `cat-file`. Commands
  that may refresh `.git/index` stat data (`status`, `diff` without care) are never run. Tests
  assert that `.git/index` is byte-identical before and after a staged check.
- **Comparing with the working tree:** done by reading working-tree bytes directly and comparing
  them to the staged blob bytes, never with `git diff`.

### Snapshot checks: `check --staged` and `check --commit REV` (read-only, planned Phase 4b)

`check --staged` reconstructs the **full staged snapshot** within the configured scope, from the
index listing rather than `git diff --cached --name-only`. `check --commit REV` does the same for a
commit (`git ls-tree -r -z`). Both run the standard dry-run scan against *that snapshot's*
registry.

**One consistency policy for every snapshot.** A snapshot check asks whether this code and this
registry are already reconciled with each other. Pre-commit (`--staged`) and CI (`--commit HEAD`)
apply exactly the same rules, so CI can't accept what the hook rejects (Addendum C §C9.18).
- **Plain working-tree `check`** keeps its current meaning. Untagged TODOs there are expected,
  because the next `scan` will annotate them.
- **Opting in:** `[tool.byteplan.check] require_reconciled = true` makes the plain `check` enforce
  the same rules, for CI setups that don't use Git snapshots.

The consistency diagnostics:

| Code | When | Exit |
|---|---|---|
| `new_unregistered` | a TODO/stub/`@todo` in the snapshot has no ID yet | 1 |
| `registry_not_staged` | the staged registry is missing from the index, or staged source carries IDs the staged registry lacks while the working-tree registry has them | 1 |
| `registry_out_of_sync` | reconciling the snapshot would make a **semantic** registry change: added, missing, reappeared, moved (path or symbol), `text_changed`, `implementation_changed` | 1 |
| `position_drift` | only line or `decl_line` metadata would change | info (0); `fail_on_position_drift = true` makes it 1 |
| `staged_config_mismatch` | the working-tree `pyproject.toml` (BytePlan sections) differs from the staged one; the staged one is used | warning |
| `working_tree_changed_but_not_staged` | the working-tree registry differs from the staged one (a hint that `git add .byteplan/tasks.json` is needed) | info |
| `unmerged_index` | unresolved merge entries | 2 |

- **Position drift is informational on purpose.** A line shift above an annotation is metadata
  only (Phase 2 rule). Making it a failure would force a rescan and a re-staged registry on almost
  every commit.
- **Policy keys** (`[tool.byteplan.check]`): `require_reconciled` (working-tree check only;
  snapshot checks always enforce) and `fail_on_position_drift` (all checks). Existing keys apply
  unchanged. Exit codes stay 0/1/2.
- **Missing detection** runs only for a complete staged snapshot, and `check --staged PATHS`
  never marks anything missing.
- **Resolved work:** a task that's resolved in the staged registry *and* has its annotation removed
  in staged source is simply finished, not missing.
- **Determinism:** findings carry no timestamps, so two checks of the same index give identical
  output.
- **Release state:** a staged release snapshot (registry `release.state = "stripped"` with matching
  records) is accepted. An unrecorded strip, or a development commit that inherits a stripped
  registry, gives `release_stripped`. These checks arrive with Phase 8.
- **No side effects:** never runs pytest, imports application code, uses the network or performs
  MCP actions.
- **JSON output:** each diagnostic gets `snapshot` (`index`) and, where relevant, the staged
  `blob` OID. stdout stays pure JSON.

`byteplan scan --staged --dry-run` shows the same snapshot's reconciliation plan: proposed ID
insertions as they'd apply to the *staged* blobs, and the registry diff. It writes nothing. Until
Phase 4c, the remediation it prints is: run `byteplan scan` (working tree), review, then stage the
source and `.byteplan/tasks.json` explicitly. Phase 4c adds `--apply`, which performs exactly that
reconciliation on the staged snapshot. It updates index entries through plumbing and never runs
`git add` on user files.

### Hooks and CI (planned, Phase 4b)

**Pre-commit framework.** The repository root ships `.pre-commit-hooks.yaml`:
- `byteplan-check`: `byteplan check --staged`, `language: python`, `pass_filenames: false`,
  `always_run: true`, stage `pre-commit`.
- `byteplan-scan-preview`: `scan --staged --dry-run`, `stages: [manual]`.

The hooks deliberately have no `types: [python]` filter. Registry-only, rename and deletion commits
must be checked too. They run in pre-commit's isolated environment with only BytePlan installed,
and never import the project. Consumer docs pin a published tag.

**Direct Git hooks.**
- **`byteplan git install-hooks [--mode check|scan]`** (Phase 4c adds `--mode reconcile`, which
  becomes the default)**:** writes `.git/hooks/pre-commit` (or the
  `core.hooksPath` target) **only if it doesn't exist** or is a BytePlan-managed hook, identified
  by a marker line. Otherwise it refuses and prints how to chain the hook manually. This is the
  one Git-adjacent command that writes, and it never touches `.git/index`.
- **`byteplan git hooks-status`:** reports what's installed and how: pre-commit framework config,
  direct hook, or none.

Hooks are a convenience, and documented as skippable (`--no-verify`). CI is the enforcement point.

**CI.** `docs/ci.md` and the README give a GitHub Actions recipe. It runs
`byteplan check --commit HEAD --format json` on the checked-out commit, with pinned action versions
and a published BytePlan version. That's the same enforcing snapshot policy as the pre-commit
hook. CI never writes source; it fails with findings. Optional later additions (Phase 11b) are a
SARIF or Markdown annotation publisher and `byteplan diff BASE...HEAD`, which compares two
`GitCommit` snapshots (tasks added, resolved, made missing, newly blocked). That's a view over
registry states, not a second database.

### Staged reconciliation: `scan --staged --apply` (Phase 4c)

**Design principle:** *the first committed appearance of an obligation already carries its
permanent ID.* The developer writes a plain TODO, stages, and commits. BytePlan does the
bookkeeping before the commit is finalized:

```console
$ echo '# FIXME: Handle withdrawn routes' >> src/rip.py
$ git add . && git commit -m "Document route withdrawal bug"
byteplan: annotated 1 staged file and .byteplan/tasks.json: [a83f] FIXME src/rip.py:42
[main 3f9c2e1] Document route withdrawal bug
$ git show HEAD:src/rip.py | tail -1
# FIXME[a83f]: Handle withdrawn routes
```

**Phase 4b stays exactly as built:** read-only, never writing. Phase 4c is the only Git-writing
phase, and everything it writes is limited to **BytePlan-managed annotations** (an inserted
`[id]`, an `id="…"` decorator keyword, a stub comment line) and **the registry**. The existing
edit engine enforces the boundary: AST equivalence and a scanner round-trip. It never stages
anything the developer didn't stage, and never changes program behaviour.

**Which files can be reconciled.** Each target is classified against three versions: HEAD, the
index and the working tree.
- **Fully staged** (working-tree bytes = staged blob bytes): eligible. The same annotated bytes are
  written to **both** the index and the working tree. Updating the index alone would leave the
  working-tree file *without* the ID, so Git would show the ID as an unstaged deletion, and the next
  `git add .` would commit that deletion.
- **Partially staged** (working tree ≠ staged blob): refused with `partial_stage_conflict`.
  Nothing is written. The message names the file and shows the dry-run preview. The fix is to
  stage the whole file or run `byteplan scan` and re-stage.
- **Registry:** it must be absent from both, or byte-identical in the index and working tree.
  Unstaged registry edits are refused (`registry_partial_stage_conflict`), so they can never be
  swept into the commit.
- **Deleted, renamed, untracked or unstaged-only files** are never touched. Untracked files stay
  untracked.

**Which index file.**
- **Standalone** (`byteplan scan --staged --apply`): the index is `git rev-parse --git-path index`.
- **Inside `git commit`**, `$GIT_INDEX_FILE` is authoritative. With `git commit -a`,
  `git commit <paths>` or `--include`, Git runs hooks against a **temporary index** and already
  holds the real `index.lock`. BytePlan writes to that temporary index (taking its `<file>.lock`),
  not the main index, so the parent `git commit` stays the single owner of `.git/index`.
- **To verify against the installed Git during implementation, with a test per mode:**
  - that a pre-commit hook's index changes are included in the commit
  - which index file and lock each `commit` mode uses

**Transaction.** The writes span three stores: Git objects, the index and the working tree. They're
made all-or-nothing as far as the platform allows, and recoverable beyond that.

1. **Capture and plan.**
   - **Capture:** the index snapshot (path → mode, OID), the staged registry bytes and the staged
     config.
   - **Plan:** build and validate the complete edit plan against the staged blobs: tokenize,
     parse, AST equivalence, and a scanner round-trip.
   - **Classify:** every target as above. Any refusal stops here with nothing written.
2. **Write new blobs** with `git hash-object -w --stdin`. This only adds unreferenced objects and
   is safe to repeat.
3. **Record the journal.** Before touching the index, write a journal under `.byteplan/txn/`
   (reusing `persistence`). It records:
   - each index entry's before and after (mode, OID)
   - each working-tree file's before and after hash
   - the target index file
4. **Update the index under one held lock.** This is Git's lock protocol: re-checking entries and
   then calling `git update-index --index-info` would allow a lost update, because
   `--index-info` has no expected-OID condition.
   1. Create `<index>.lock` with `O_CREAT|O_EXCL`. In a commit with a temporary index, this is
      `$GIT_INDEX_FILE.lock`.
   2. While holding the lock, re-verify every affected entry's (mode, OID) **and** every target's
      working-tree hash against the capture.
   3. Build the new index in a scratch copy (`GIT_INDEX_FILE=<scratch> git update-index
      --index-info`) and verify it with `ls-files --stage -z`.
   4. Write the verified bytes into the lock, fsync, and `rename` the lock over the index.
   5. On any failure, delete the lock and leave the index untouched.
5. **Update the working tree.** Each fully staged target is replaced atomically through
   `persistence`, keeping its permissions, one file at a time. **Source files go first and the
   registry goes last**, so a partial run can never leave new IDs without registry entries. Each
   replacement happens only if the file's bytes still equal the captured staged blob (its *before*
   bytes), so a concurrent editor save is never overwritten. The journal marks each target as
   written once it's done.
   - **If any write can't proceed** (a concurrent edit or an I/O error), BytePlan **rolls the
     whole reconciliation back** before aborting with `concurrent_modification`:
     1. The journal's direction is set to `rollback`.
     2. Every already-written working-tree target whose bytes still equal BytePlan's *after*
        bytes is restored to its *before* bytes (atomically, permissions kept).
     3. The index entries are restored, taking the lock again, OID-guarded.
   - **What the developer is left with:** the index, every working-tree file and the registry are
     exactly as before the commit attempt. A retry then sees the same fully staged files, not a
     self-inflicted `partial_stage_conflict`.
   - **When a file can't be restored** because something else changed it after BytePlan's write,
     it's left untouched. The journal is kept and the run exits 2 with `rollback_conflict`, naming
     the file, its before and after hashes, and the two ways to resolve it. BytePlan never
     overwrites someone else's edit, in either direction.
6. **Revalidate.** Run `check --staged` against the new index. Success is reported only if it
   passes. Otherwise the journal is kept and the hook exits non-zero.
7. **Finish.** Delete the journal and print what was annotated. Exit 0, so the commit proceeds,
   carrying the IDs in both the source blobs and the staged registry.

**Unsupported formats.** A split index (`core.splitIndex`) or sparse index (`index.sparse`) can't be
replaced as a single file. Either is refused with `unsupported_index_format`, and the read-only
check still works.

**Recovery and retries.**
- **Crash before step 4:** the index is unchanged. At most a stale lock is left, reported with Git's
  usual guidance.
- **Crash after step 4, including partway through step 5's working-tree writes:** the next
  BytePlan run finds the journal and picks *one* direction for every target, then records it in
  the journal so a crash during recovery resumes the same way.
  - **Forward:** used when every target is at either its *before* or *after* bytes, i.e.
    nothing else touched them. Unwritten targets are written, registry last, and the run
    revalidates.
  - **Back:** used when any target holds foreign bytes. Targets at *after* revert to *before*, the
    index entries are restored (OID-guarded), and foreign files are reported as
    `rollback_conflict`, never overwritten.

  Either way, the index never claims IDs the working tree lacks, and the working tree never holds
  IDs that neither the index nor the registry knows about.
- **Retries are idempotent:** re-running on an already-annotated snapshot finds no untagged
  annotations and writes nothing. A re-commit after an aborted commit just works.

**Hooks.**
- **Direct hook** (`byteplan git install-hooks --mode reconcile`, the default once Phase 4c ships):
  runs `scan --staged --apply` and then `check --staged`. This is the transparent experience above.
- **pre-commit framework** (`byteplan-reconcile` in `.pre-commit-hooks.yaml`): the framework
  **stashes unstaged changes** before running hooks, so partial staging is invisible to the hook.
  It also treats any hook that modifies files as **failed**.
  - Under the framework (detected by `PRE_COMMIT=1`), the hook therefore acts like a formatter. It
    writes the annotations to the working tree and index, and exits 1 with "annotated N files;
    commit again".
  - The framework restores the stash, and the second commit passes. That's the standard fixer
    workflow, documented as such.
- **Other hooks:** `byteplan-check` stays the read-only hook for teams that want validation only.

**As built (verified against git 2.51).** A probe hook checked which index file each commit
mode hands a pre-commit hook:

| Mode | `GIT_INDEX_FILE` | Git holds `.git/index.lock` | Result |
|---|---|---|---|
| `git commit`, `--amend` | `.git/index` (relative) | no | BytePlan takes `.git/index.lock` itself |
| `git commit -a`, `--include` | `.git/index.lock` (absolute) | yes | BytePlan locks `.git/index.lock.lock`; Git renames the result into place |
| `git commit <paths>` | `.git/next-index-<pid>.lock` | yes | **check-only**: Git separately stages the paths into the real index, so annotating the temporary one would leave the real index behind |

In the first two modes, a hook using the lock → scratch index → rename protocol put its change into
the commit, with index = HEAD and working tree = index afterwards (no phantom diff). Other
decisions:
- **pre-commit framework (`PRE_COMMIT=1`):** writes the working tree only, never the index. The
  framework may roll back a hook's working-tree fixes when they conflict with its stash, and an
  index change would then be left without its file.
- **Revalidation:** runs after the journal is deleted, because the transaction itself is complete
  and consistent. A failing revalidation (e.g. an unregistered ID elsewhere) is reported and exits
  1, without undoing the reconciliation.
- **Pending journal:** any other writing command refuses to run while
  `.byteplan/txn/staged-journal.json` is pending.

**Policy.** `[tool.byteplan.git] on_reconcile = "commit"` (default) lets the commit proceed after a
successful reconciliation. `"stop"` exits 1 after writing, so the developer reviews first, which
was the earlier design's behaviour.

**Never.**
- **Never broadens the commit:** no `git add` of user files, and no staging of unrelated or
  unstaged changes.
- **Never guesses** in ambiguous states: partial staging, registry conflicts, unmerged index,
  concurrent edits. These abort with an actionable diagnostic instead.
- **Never resolves anything.**
- **`--no-verify`** still skips the hook. CI (`check --commit HEAD`) is where consistency is
  enforced.

### Phase 4b as built

- **`snapshot.py`:** `GitSnapshot` covers the index and commits, using `ls-files --stage -z` or
  `ls-tree -r -z` plus a single `cat-file --batch` process, all `--no-optional-locks`.
- **Shared scope rules:** `files.TextSource` lets scope rules read `.gitignore` files from the
  snapshot, including repository ancestors above the project root.
- **`Project.open_snapshot`:** loads config and the registry from the snapshot.
  `staged_config_mismatch` compares the BytePlan tables of the staged and working-tree
  `pyproject.toml`.
- **Consistency rules** apply when `--staged`, `--commit` or `require_reconciled` is in effect.
  - **Out of sync:** `registry_out_of_sync` is raised for the events `moved`, `text_changed`,
    `reappeared` and `implementation_changed`, and for `missing` on open tasks only.
  - **Resolved and removed together:** a closed task whose annotation was removed raises nothing.
  - **Position-only changes:** these produce `position_drift`.
- **Hooks:** `git install-hooks` writes a marked `/bin/sh` hook that runs
  `<absolute python> -m byteplan check --staged`. `core.hooksPath` is honoured.
- **Test infrastructure:** subprocesses spawned in tests (builds, Git hooks, the merge driver)
  write coverage data to the repository's `.coverage`, never into the project under test.
  Without this, `hatch test --cover` failed the Phase 4 build tests.

## Markdown and JSON sources (Phase 4e)

Docs, configuration and data files carry unfinished work too: a README section that needs
rewriting, a `tsconfig.json` option to tighten later, a fixture with a placeholder. Phase 4e
lets BytePlan track TODOs in Markdown and JSON files, with the same IDs, registry, lifecycle,
Git integration and never-auto-resolve rule as Python.

### File types

- **The file type comes from the suffix:**
  - `.py`: Python
  - `.md` and `.markdown`: Markdown
  - `.json` and `.jsonc`: JSON, with comments allowed in both, because `tsconfig.json`,
    `.vscode/*.json` and `devcontainer.json` are commented `.json` files
- **Files of any other type are never collected,** even if `include` matches them.
- **`include` decides which supported files are scanned.** The default stays `["**/*.py"]`, so
  existing projects see no change. Projects opt in with patterns like `"README.md"`,
  `"docs/**/*.md"` or `"config/**/*.json"`.
- **The registry file is never scanned,** even when it sits outside `.byteplan/` and an `include`
  pattern matches it.
- **Python-only features don't apply to Markdown and JSON:** stub detection, `@todo` decorators,
  declaration attachment and the class index. Tags attach as `module`, or as `statement` for
  trailing ones.
- **No schema change:** `representation` and `origin` stay `comment`.

### Markdown

- **What counts:** a tag inside an HTML comment, `<!-- TODO: title -->`, under the same tag
  rules as Python. The tag must open the comment, `[id]` is optional, and tags match
  case-insensitively.
  - Prose `TODO`s are not tracked; "TODO list" in a sentence is not a task.
- **Title and description:** the comment's first line is the title. The rest of a multi-line
  comment, up to `-->`, is the description, dedented.
- **Code is skipped:** comments inside fenced code blocks (` ``` ` / `~~~`, including in lists and
  block quotes, and fences opened on a list item's first line like `- ```html`) and inline code
  spans are not comments. Inline code can continue over the lines of a paragraph, and is scanned
  left to right as Markdown parses it.
  - Known gap: indented (four-space) code blocks are not recognized.
- **Link-reference comments:** `[//]: # (TODO: title)`, an unused link definition to `#`, renders
  as nothing at all, not even in the HTML.
  - Any label works. The title can use `()`, `""` or `''`, and the tag must open it.
  - Directly following comment lines whose text starts with two spaces are the description, as
    with Python `#` comments.
  - It's recognized only where CommonMark accepts a link definition: never inside a paragraph
    (including a list item's lazy continuation), in code, or indented four spaces.
- **Symbol:** the nearest preceding heading (ATX `##` or setext), so moving a TODO to another
  section records a `moved` event. YAML front matter is skipped.
- **Ignoring:** `byteplan: ignore` inside a tag comment ignores that tag.
  `<!-- byteplan: ignore-file -->` within the first five lines ignores the file.
- **Edit guard:** with every HTML comment removed, the edited text must equal the original.

### JSON

- **Comments:** `// TODO: title` and `/* TODO: title */`.
  - Line comments take continuation lines exactly as Python does: the next line, the same column,
    two spaces after `//`.
  - A block comment's later lines are its description. A leading `*` on each line, Javadoc
    style, is removed.
  - `// byteplan: ignore-file` within the first five lines ignores the file.
- **String values,** for strict JSON that can't hold comments (`package.json`, fixtures, a JSON
  Schema `$comment`):
  - A value string tracks a task when it begins with a tag, an optional `[id]` and a colon:
    `"todo": "TODO: pin the version"`.
  - Matching is case-sensitive and the colon is required, so data like `"Todo: buy milk"` is
    left alone. Keys never match.
  - An ID is written inside the string (`"TODO[7fa2]: pin the version"`), which stays valid JSON.
  - A `\n` in the value separates the title from the description.
  - Turned off with `[tool.byteplan.detect] json_string_values = false`.
- **Symbol:** a JSON Pointer.
  - String value: the value's own pointer (`/scripts/todo`).
  - Comment above a member: that member's pointer.
  - Trailing comment: the member it follows.
  - Otherwise the enclosing container's pointer, or none at the top level.
- **Parsing:** a small tolerant lexer accepts comments and trailing commas. Anything else that
  isn't JSON fails the scan, like a Python syntax error, so BytePlan never writes into a malformed
  file:
  - unterminated strings or comments
  - mismatched brackets
  - invalid literals (`garbage`, `True`, `01`)
  - invalid string escapes
- **Edit guard:** the token stream without comments must be unchanged, except that a tagged
  string may gain an `[id]` right after its tag.

### Encoding

Markdown and JSON are read as UTF-8, keeping a BOM if there is one. Python coding cookies apply
only to `.py` files. Newline style, BOM and a missing final newline round-trip byte for byte, as
they do for Python.

### Phase 4e tests

- **Markdown:**
  - Single-line and multi-line comments, with titles, descriptions and ID slots.
  - Several comments on one line, and trailing comments.
  - Comments skipped in fences (backtick, tilde, longer closers, in lists and block quotes) and in
    inline code.
  - ATX, setext and front-matter handling for symbols.
  - Ignore markers and malformed IDs.
- **JSON:**
  - Line and block comments, with continuations and Javadoc stripping.
  - String values in objects and arrays, with escaped content and pointers containing `~` and
    `/`.
  - Keys never match, case-sensitivity, the opt-out, and trailing commas.
  - Lexer errors.
- **End to end:**
  - `scan` writes IDs into `.md`, `.json` and `.jsonc` files byte-for-byte safely (CRLF, BOM,
    no final newline), and a second scan is a no-op.
  - Unsupported suffixes and the registry are never collected.
  - `check --staged` and `scan --staged --apply` work on Markdown and JSON.
  - `repair --reassign` works in both formats.
  - The edit guard refuses changes outside comments and tag strings.

## Committed report file (`report_file`)

A readable, committed task list (`byteplan.md`), kept current at commit time. It was added
alongside Phase 4e.

- **Pure function of the registry:** no clock and no scan diagnostics, so the same registry
  always renders the same bytes and staleness is a plain comparison. Open work comes first
  (`in_progress`, `blocked`, then `open`, by path and line), then closed tasks. Locations link
  relative to the report's directory, with paths percent-encoded so `#` and spaces don't break
  links. Missing locations are struck through.
- **Written with the registry:** `_registry_writes` puts the report write before the registry
  write in every registry-writing command (scan, mutations, repair). The commit hook's
  `scan --staged --apply` already stages every planned write, so the report needs no
  hook-specific code: partial-stage refusal, journaling and crash recovery all apply.
- **Checked:** snapshot consistency (`--staged`, `--commit`, `require_reconciled`) compares
  the snapshot's copy with the render of the snapshot's registry. A copy whose only difference is
  CRLF line endings counts as current, and isn't rewritten.
- **Diagnostic:** `report_out_of_sync` is a warning, or a failure with
  `[tool.byteplan.check] fail_on_stale_report`. It's a warning by default because merges can't
  regenerate the file: a per-file merge driver can't see the merged registry. So
  `install-merge-driver` registers `merge=byteplan-report` (driver `true`, which keeps ours), and
  the next hooked commit or scan regenerates it.
- **Never scanned,** like the registry.
- **`report_branch`** (added after Phase 9): GitHub runs no merge drivers, so two PRs that both
  change tasks conflicted on the report there. With `report_branch = "main"`, `maintains_report`
  is false on any other branch or a detached HEAD: registry writes skip the report and the
  staleness check is skipped. `report --write` regenerates it explicitly, on any branch, for the
  post-merge CI job (`.github/workflows/report.yml` here). The registry itself still merges
  textually on GitHub; overlapping `reserved_ids` edits are resolved locally with the drivers.

## Registry format and merging

**JSON stays the canonical registry, and SQLite is not used for it.** This was decided on
2026-10-22.
- **The registry is committed and travels with the code.** That needs readable diffs and PR
  review, text merges, and byte-identical rewrites for idempotence. Git-snapshot checks also read
  it straight from blobs. JSON does all of these; a SQLite file does none of them, since its layout
  changes with page allocation and vacuuming.
- **Locking is already covered.** On one machine, the project lock plus the journal handle it.
  Across branches, the concurrency is resolved by Git merges, where SQLite's locking can't help.
- **SQLite remains a candidate for a local, gitignored, rebuildable cache.** That could serve fast
  queries on very large projects, the MCP server, or verification evidence (Phase 6). It would
  never be authoritative.

**Archive ✅** (`archive.py`; `byteplan archive`, `list --archived`, `merge-archive`). This is the
local SQLite use foreseen above, and the registry stays authoritative for every open task:
- **Eligible:** closed for `[tool.byteplan.archive] after_days` (7), not stripped, annotation gone
  (presence `missing`, or no source). In a Git repository, the current record must also equal
  `HEAD`'s, so every archived record is in history.
- **Store:** `.byteplan/archive.sqlite`, gitignored, one row per task: id, record sha256,
  archived_at, zlib(canonical JSON `{task, evidence}`). Written before the journaled JSON writes,
  so an interruption only leaves extra rows.
- **Index:** `.byteplan/archive.json`, committed, deterministic, sorted. Its merge driver is
  three-way per task ID against base, comparing record hashes, so a one-sided re-archive or
  restore survives and two independent archives of the same record agree. Both sides changing an
  entry differently falls back to `git merge-file` markers. An entry for a registered task is
  ignored.
- **Reconcile:** walk `git log -- tasks.json` newest first, hash each version's records, and stop
  once every wanted hash is found. Evidence isn't in history and isn't recovered.
- **Automatic:** after every writing, unblocked, non-snapshot scan (`auto = true`).
- **Registry merge:** an archived task is a removal, and "removed on one side and changed on the
  other" is already a reported conflict.

**Registry merge driver ✅** (`merge.py`, `gitio.py`; `byteplan git install-merge-driver`,
`byteplan merge-registry`). It's a three-way merge by task ID:
- unions reserved IDs and tasks
- append-only history, ordered by `(at, event)`
- set-merge for labels
- per-field three-way merge for managed fields
- `first_seen` takes the earlier value, `last_seen` the later

**Conflicts fall back to `git merge-file` markers, with an explanation.** These include the same
field changed differently on both sides, an ID allocated on both branches for different work
(return to an original branch and use the [explicit pre-merge repair procedure](rc1-compatibility.md#merge-and-collision-recovery)),
removed versus changed, and a schema mismatch. Nothing is
chosen silently.

**Discovered fields** changed on both sides keep ours and ask for a `scan`, which recomputes them
from the merged source.

**Installation.** `.byteplan/.gitattributes` is committed. The driver command is local
`git config`, recorded with the absolute interpreter path (`python -m byteplan`) so it works
outside the virtualenv. A clone without the driver falls back to Git's text merge; I checked on
git 2.51 that an undefined driver name is harmless.

## Addendum D decisions: assignments, provenance, development cycles

### Terminology: "assignment" is the concept, `task` stays the name (§D.12 Q1)

Assignments come **alias first**. An assignment *is* today's task: same ID, same registry entry,
same CLI. The docs adopt "assignment" as the conceptual noun, and nothing is renamed: not
commands, not `tasks.json`, not the field names. A rename would be its own decision, with its own
migration, if real use ever justifies it. Every existing TODO, decorator, stub, ID and registry
file keeps working unchanged (§D.9).

### State axes, mapped onto what exists

Addendum D proposes four axes. Most already exist under other names, so the plan maps them
rather than duplicating them:

| §D.3 axis | BytePlan field | Decision |
|---|---|---|
| `lifecycle` | `status`: `open`, `in_progress`, `blocked`, `resolved`, `dismissed` | Kept as is. `cancelled` is accepted as CLI and API input for `dismissed`. **`ready_for_review` is not stored as a lifecycle value**: readiness stays *computed* from evidence (Addenda A and B). Storing it would let a stale "ready" outlive the evidence behind it. |
| `binding` | `presence`: `present`, `missing`, `unknown`, `stripped`, plus new **`unbound`** | `bound` = `present`, `stripped` is unchanged, and Addendum D's `stale` binding is today's `missing`. `unbound` is new: created without a source annotation (intake, explicit creation). Scans never mark an unbound assignment missing, because it never had a source. **Proposed** bindings are a separate list (below), never a presence value. |
| `verification` | computed readiness (Addendum A) | Kept computed. §D.3.1's three distinct facts stay separate: stale evidence (fingerprint/revision), a scaffold placeholder (Addendum B), and **coverage adequacy**. That last one is new: a managed `coverage_review` field (`unassessed`, `adequate`, `needs_review`) set by a human or agent, never derived from test results. |
| `approval` | new managed `approval` object | `{required: bool, state: not_required, pending, approved, changes_requested}` |

**Approval rules:**
- `byteplan approve ID` and `byteplan request-changes ID` set the state.
- When `required` is true, `resolve` refuses unless the state is `approved`. `--override-approval`
  is allowed only for a human at the CLI, and is recorded.
- The MCP server never exposes `approve`. No merge, check result or agent statement can stand in
  for approval (§D.3 rule 7).
- `[tool.byteplan.approval] required_by_default = false` controls new assignments.

### Links: typed, directed, many-to-many (§D.2.2–D.2.4)

Each assignment gains `links: [{relation, ref, note?, added: {at, actor}}]`.

**Relations:** the §D.2.3 verbs (`originated_from`, `investigates`, `consumes`, `produces`,
`delivered_by`, `verified_by`, `blocked_by`, `supersedes`, `reverted_by`, `related_to`).
Provider-namespaced verbs such as `github:labelled_by` are allowed. Unknown relations and fields
round-trip untouched.

**Artifact references (§D.12 Q3):** one URI-like string grammar, no provider SDK needed:

```
<scheme>:<locator>                       # scheme and kind are lowercase
git:commit:<full-oid>[@<repo>]            # algorithm inferred from length (40 = SHA-1, 64 = SHA-256)
github:<owner>/<repo>:issue:<n>  github:<owner>/<repo>:pull:<n>  github:<owner>/<repo>:release:<tag>
gitlab:<group>/<project>:issue:<n>
test:<pytest node id>
byteplan:<id>                             # another assignment in this project
url:<https://...>                         # anything else
```

- **`<repo>`:** defaults to `[tool.byteplan] repository = "github:BytesAndCoffee/byteplan"`.
- **Commit references** are validated as full object IDs. Branch names are accepted only as a
  note, never as a ref (§D.2.2).

**Merging existing concepts into links:**
- Phase 6c's `depends_on` is converted by `byteplan migrate` into `blocked_by` links, with cycle detection.
- Test links (Addendum A `tests`) stay in their own subsystem, because they carry discovery and
  provenance details. Queries present them as `verified_by` relationships, so there's one view and
  two storage paths.

**Queries (§D.5)** are computed from the registry on demand, with no separate index:
- `byteplan links ID`: forward.
- `byteplan refs REF`: reverse ("which assignments touch this PR or commit?").
- `byteplan history ID`.
- `byteplan impact REV`, which reports three separately labelled sections:
  1. *explicit* links to that commit
  2. *source-overlap candidates* (files changed by `git diff-tree` that contain bound annotations)
  3. *verified effects* (evidence recorded at that revision)

  It never states that a commit completed anything.

**Commit trailers** (`BytePlan-Assignment: a83f`): `byteplan links discover REV-RANGE` *proposes*
links from trailers, dry-run by default. A trailer is never the sole authority, and history is
never rewritten.

**Rebases, squashes and cherry-picks (§D.12 Q4):**
- Each `git:commit` link also stores `patch_id` (`git patch-id --stable`).
- `byteplan links reconcile` re-associates links whose commit vanished after a rebase or
  cherry-pick by matching patch IDs, and reports any that can't be matched.
- For squash merges, the durable link is the PR (`delivered_by`), plus the final integrated commit
  as `produces` once known.
- Both outcomes are reported, never guessed.

### Event history (§D.4, §D.12 Q2)

History stays **embedded per assignment**, as now. It's append-only, and the registry merge driver
already merges it. That keeps atomicity under the existing journal and avoids a second file to
keep consistent.

Events gain optional fields:
- `actor` (from `BYTEPLAN_ACTOR`, else `git config user.email`, else `"unknown"`)
- `actor_type` (`human`, `agent`, `ci`, `integration`; CLI default `human`, MCP `agent`, `$CI`
  sets `ci`)
- `revision` (HEAD at the time, when in Git)
- `inputs` (refs)
- `evidence` (evidence IDs)
- `idempotency_key`

A write that carries an idempotency key already present in that assignment's history is a no-op.
That makes webhook redelivery and agent retries safe (§D.8.1).

The docs will not call this an audit trail or tamper-proof. It's a Git-versioned record of why
state changed.

### Intake and binding (§D.2.1, §D.8.1–D.8.2)

**Creating assignments without source:**
- `byteplan create --title T [--kind FIXME] [--link RELATION=REF]...` creates an **unbound**
  assignment with a fresh ID.
- `byteplan intake REF [--title T]` does the same for an external report, and is **idempotent by
  canonical ref**. If an assignment already has `originated_from` that ref, it returns the
  existing ID and writes nothing.
  - **Offline:** a title is required.
  - **Fetching titles:** an optional provider fetch (e.g. through `gh`) is a later, separate
    adapter. Core never needs the network.
- **Several issues per assignment, or several assignments per issue,** are both expressible
  through links. Deduplication never uses title or body text.

**Binding:**
- **Doing it by hand:** put the existing ID into source (`# FIXME[a83f]: ...` or
  `@todo(..., id="a83f")`). The next scan finds an ID that's registered and `unbound`, and binds it
  (`unbound → present`, a `bound` event).
- **`byteplan bind ID TARGET`:** inserts the comment above a symbol or at `PATH:LINE` through the
  existing edit engine.
- **Proposals:** `byteplan propose-binding ID PATH[:SYMBOL] [--confidence low|medium|high]
  [--note]` records a candidate in `binding_proposals` without editing source. A proposal never
  changes presence.

**Branch awareness:** an annotation that exists only on an unmerged branch shows as `present` on
that branch's registry and `unbound` on `main`. The merge driver's "discovered field, ours plus
rescan" rule reconciles them when the branch lands. This matches §D.8.2's "proposed project
change, not proof".

### Trust boundaries (§D.8.4)

- **Untrusted data:** issue bodies, PR text, commit messages and trailers are stored as data, and
  returned through MCP as clearly delimited untrusted content.
- **Never executed or obeyed:** BytePlan never runs anything they contain and never treats them as
  instructions.
- **MCP permissions:** the agent tools from §D.7.1 are added to the MCP server in Phase 12, and map
  onto its existing three permission flags.
  `request_resolution` is policy-checked: it is refused when approval is required and not given,
  or when evidence is stale. It is never an unconditional resolve. `approve` doesn't exist on MCP.
- **Tokens:** least-privilege token guidance lives in the Relay docs, not core.

### Relay (§D.6–D.7)

Relay is **one optional development cycle**, not part of the protocol. Core BytePlan remains fully
usable offline with no GitHub account.

- **Packaging:** the reference integration ships separately as `relay-for-github/`, described as
  "Relay for GitHub, powered by BytePlan" and explicitly **unofficial**. It is never branded in a
  way that implies GitHub sponsorship.
- **Contents:**
  - reusable GitHub Actions workflows: issue intake on `opened`/`reopened`, idempotent by
    canonical ref
  - PR reconciliation using `check --commit`
  - a single updatable status comment
  - documentation for a triage agent that only *proposes* bindings
  - branch-protection and required-review guidance
- **Prerequisites:** it's built only after the assignment model (Phase 12), verification
  (Phase 6a), scaffolding (6b) and MCP (Phase 9) exist.
- **GitHub App or Checks API:** deferred until real use justifies it (§D.10 D5).

### Future Assignment schema and migration (§D.9)

The original Phase 12 proposal reserved schema v2 for Assignments. **Addendum E A2 supersedes
that numbering:** RC1 may need v2 for persistent-ID compatibility. Assignments will use an
appropriate subsequent boundary after inspecting the integrated RC1 contract; its exact version
and compatibility matrix remain undecided. Older clients must not silently misread `unbound`.
- Reuse E A2's explicit migration infrastructure through the journal, idempotently, preserving
  unrelated data and evidence.
- Establish read/write compatibility against actual released clients; reject incompatible writes
  with actionable migration guidance.
- **Proposed Assignment additions:** empty `links`, `approval: {required: false, state:
  not_required}`, `coverage_review: unassessed`, and an empty `binding_proposals`. Phase 6c's
  `depends_on` becomes `blocked_by` links. No other existing value changes.
- **Prerequisite already completed in Phase 4d:** unknown top-level keys round-trip as task-level
  ones do. Preserve this protection through both migrations. The merge driver
  merges them three-way and structurally: objects key by key, and lists that both sides only
  appended to as the base plus both sides' additions. Anything else changed on both sides is a
  conflict.

### Remaining open questions (§D.12)

- **Q5 (readiness versus adequacy):** answered above. Readiness is derived; adequacy is the
  managed `coverage_review`.
- **Q6 (narrowest triage-agent permissions):** answered in the Relay docs: read-only reconnaissance
  plus `propose-binding` and branch PRs; no merge, approve or close.
- **Q7 (duplicate and invalid reports):** BytePlan never decides these. Intake only deduplicates by
  canonical ref. A human or agent can link `related_to`/`supersedes` or dismiss with a note, and
  the tool reports its uncertainty instead of asserting.

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
- **Implemented (Phase 4):** the hook is `byteplan.hatch_hook`, verified against Hatchling 1.32.4.
  - **Config:** unknown keys fail the build. Hatchling's own per-hook keys (`dependencies`,
    `enable-by-default`, `require-runtime-*`) are accepted.
  - **`write_source`:** accepts only `true`, `false` or `"editable"`, using identity checks so the
    integer `1` isn't taken as `true`.
  - **CI detection:** `$CI` counts unless it's empty, `0`, `false` or `no`.
  - **Registry packaging:** checked with the target's own `build_config.include_path`, which covers
    include/exclude rules and VCS-ignore.
  - **Tests:** real `python -m build --no-isolation` builds of a scratch project, plus a
    `network`-marked isolated build. That one uses a local wheelhouse with the index disabled, so
    it exercises this checkout rather than a published byteplan.

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
- **Read-only by default, with three separate permissions** (Addendum A §8):
  - `--allow-registry-write` registers `set_status`, `resolve`, `edit_task`, `add_task_test` and
    `remove_task_test`.
  - `--allow-source-write` lets `scan` and `sync_source` write source. Even then, every call needs
    `apply=true`.
  - `--allow-test-execution` registers `verify_task`.
  - A tool whose permission is missing isn't registered at all.
  - Listing, searching and scanning never execute tests.

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
| `get_task_tests(id)` / `get_verification(id)` / `list_ready_tasks()` | no | `tests list`, `verify --json` (cached), `verify --ready` |
| `add_task_test(id, node)` / `remove_task_test(id, node)` | registry | `byteplan tests add/remove` |
| `sync_source(apply=false, only?)` | source, only with `apply=true` | `byteplan sync` |
| `verify_task(id)` | executes tests | `byteplan verify ID` |
| `preview_test_scaffold(id, path?, name?)` | no | `tests scaffold --dry-run` (returns the planned file edit) |
| `scaffold_test(id, path?, name?, apply=false)` | source, only with `apply=true` | `byteplan tests scaffold` |
| `release(version?, apply=false)` / `restore(apply=false, partial=false)` | source, only with `apply=true` | `byteplan release` / `restore` |

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

**Phase 9 as built** (`mcp_server.py`, `tests/test_mcp.py`):
- **SDK:** `mcp>=2.3,<3`. In 2.x, FastMCP is `mcp.server.mcpserver.MCPServer`, and
  `mcp.Client(server)` connects in process (the tests use it). Sync tools run in worker threads.
- **Launch:** three flags, `--allow-registry-write`, `--allow-source-write` and
  `--allow-test-execution`. There is no catch-all `--allow-write`. The options are defined in
  `cli.py`, so the CLI never imports the SDK; a missing extra prints the install command and
  exits 2.
- **Gating, made precise:**
  - `scan` and `sync_source` are always registered, because their previews are read-only.
    `apply=true` without source-write is a tool error.
  - `scaffold_test`, `release` and `restore` exist only with source-write (Addendum B).
  - `release(smoke_test=true)` also needs test-execution, because it builds and imports the
    project.
  - `resolve(sync_source=true)` resolves (a registry write) and previews the cleanup;
    `apply=true` removes the annotation and needs source-write.
- **Shapes:** a list comes back wrapped in an object (`{"tasks": [...]}`), since structured
  results must be objects. `get_task_tests` returns `{id, title, tests}`. `edit_task` takes the
  CLI's `add_labels` / `remove_labels`, `unassign` and `clear_title` rather than a whole label
  set.
- **Errors:** `ByteplanError` becomes the SDK's `ToolError`, so the agent sees the message.
  `LockedError` is prefixed `locked:`. Anything else is a crash, which the SDK reports
  generically and logs to stderr.
- **A fresh `Project` per call,** so config and registry changes made outside the server are
  always seen.

## Phases

Each phase ends green on `hatch fmt --check`, `hatch run types:check` and `hatch test --all`.

The historical phases merge Addendum A §10, Addendum B §B9 and Addendum C §C10.
**The active Addendum E release gates above take priority.** Addendum D remains post-1.0:
- **Phase 12:** §D.10 stages D0–D2, plus the D4 agent tools.
- **Phase 13:** D3, the optional `relay-for-github` package.
- **D5:** deferred.

D builds on nearly everything before it (verification, scaffolding, release, MCP), and nothing
earlier depends on it.

Addendum items are planned, not implemented, until their phase is marked ✅. Phase 4c (IDs at
commit time) is done. Phases 4d, 4e and 5 (runtime and normalization: annotation modes,
`byteplan sync`, `init --runtime-shim`) and 6a (test links, `byteplan tests`, `byteplan verify`
with evidence, freshness and readiness) 6b (test scaffolding) and 7 (cleanup, for Python, Markdown and JSON annotations) are done. **Phase 8 is done** (`release`/`restore`, the opt-in `--smoke-test`, Hatch
`require_stripped`, and the two release warnings). **Phase 9 is done** (`byteplan mcp`; see
"Phase 9 as built" under [MCP server](#mcp-server)). **Phase 10 is done** (see "Phase 10 as built" below). The
remaining historical feature phases are 12 and optional 6c, 11 and 11b, all outside RC1.
Addendum E adds required compatibility, decomposition and release-review gates before them.
Phase 8 deviations: the smoke
test installs into an isolated target directory run with `python -I -S` rather than a venv (the
same isolation, without creating one); `unfinished_scaffold_in_sdist` is reported at release time and
by `check` while stripped, not on every development `check`, where placeholders are expected.
Finished phases' TODOs stay in this file until their task is resolved; BytePlan's own cleanup
(`resolve --sync-source`) removes them.
**Historical schema note:** schema v1 shipped in 0.1.0 and 0.2.0. The existing `stripped`
presence was added without a version bump; 0.2 rejects such records. This does not establish
expanded-ID compatibility. E A2 requires actual released-package tests and an appropriate
version boundary before incompatible writes.
6b deviation: whether a linked test is still a placeholder is computed from source when needed
(readiness, `check`), not stored as `placeholder: true` on the link, so editing the body is
all it takes and the registry doesn't churn. Acceptance-criteria hints wait for Phase 6c, and
`unfinished_scaffold_in_sdist` for Phase 8. Addendum A's step 2 (choosing the runtime design) is already done, and the
runtime package has shipped.

| Phase | Deliverables | Spec §12 tests | Addendum §9 tests |
|---|---|---|---|
| 0. Scaffold ✅ | pyproject (3.11+, URLs, envs, sdist excludes), CLI skeleton, smoke tests, `.gitignore`, docs/ | – | – |
| 1. Core ✅ | config, files, registry, ids, source + comment scanner, `api.Project`, CLI `init/scan(report-only)/list/show` | 1, 5, 19, 20 | – |
| 2. Write path ✅ | `edits.py` (span edits + equivalence guard), comment annotation, reconcile, persistence (journal, concurrent-modification check), `status/resolve/edit/missing/duplicates`, `--dry-run` | 6–17 | 13 (resolve without source edits), 15, 17, 18 |
| 3. Stubs + decorators ✅ | `stubs.py`, `decorators.py` (static `@todo`/`@verifies` discovery, alias resolution), `association.py` (comment / decorator / stub → one obligation), decorator `id=` allocation, schema fields, `implementation_changed`, `check`, `report`, `repair` | 2, 3, 4, 17 | 1, 2, 6 (comment mode), 7, 19 |
| 4. Hatch ✅ | hatch_hook + entry point, `examples/hatch_build.py`, decorator discovery in builds (read-only), README onboarding | 18 | 16 (Hatch part) |
| 4b. Git lifecycle (read-only) ✅ | `snapshot.py` + `gitio.py` (index/commit snapshots via NUL-safe plumbing, no-optional-locks), `check --staged`, `scan --staged --dry-run`, staged diagnostics and policy keys, `.pre-commit-hooks.yaml`, `git install-hooks` / `git hooks-status`, `docs/ci.md` GitHub Actions recipe | – | C: 1–6, 8–14, 17–21 (C: 7, 22 with Phase 8) |
| 4c. Git staged reconciliation ✅ | `scan --staged --apply`; fully-staged / partial-stage classification against HEAD, index and working tree (`partial_stage_conflict`, `registry_partial_stage_conflict`); blobs → journal → index swap under the index lock (`$GIT_INDEX_FILE`-aware inside `git commit`) → hash-guarded working-tree writes, with index rollback on conflict → revalidation; crash recovery and idempotent retries; `install-hooks --mode reconcile` (new default) and a `byteplan-reconcile` framework hook (fixer behaviour); `[tool.byteplan.git] on_reconcile`; `unsupported_index_format` | – | C: 15, 16 + 4c tests below |
| 4d. Registry forward compatibility ✅ | unknown **top-level** and task-level registry keys round-trip, and the merge driver merges them three-way. A general fix, needed before Phase 8 adds top-level `release` records, so it isn't deferred with Addendum D | – | – |
| 4e. Markdown and JSON sources ✅ | suffix-based file types (`.md`/`.markdown`, `.json`/`.jsonc`); Markdown HTML-comment tags with heading symbols, skipping code; JSON comment tags and tagged string values with JSON Pointer symbols; per-format edit guards; `detect.json_string_values`; registry never scanned. See [Markdown and JSON sources](#markdown-and-json-sources-phase-4e) | – | Phase 4e tests |
| 5. Runtime + normalization ✅ | `byteplan-runtime/` project (✅ 0.1.0 on PyPI: inert `todo`/`verifies`), `init --runtime-shim`, `[tool.byteplan.annotations]`, `normalize.py`, `byteplan sync --dry-run/--apply` | – | 3, 4, 5, 6 (decorator mode), 8 |
| 6a. Acceptance tests ✅ | test links + provenance, `byteplan tests list/add/remove`, `_verify_plugin.py`, `verification.py`, `byteplan verify [ID] [--json] [--ready]`, readiness, freshness | – | A: 9, 10, 11, 12 · B: 10 |
| 6b. Test scaffolding ✅ | `scaffold.py` planner, `byteplan tests scaffold ID [--path] [--name] [--policy] [--force-new] [--dry-run]`, placeholder detection, `[tool.byteplan.tests.scaffold]` | – | B: 1–9, 11 (CLI), 12 |
| 6c. Criteria + dependencies (optional) | `acceptance_criteria`, `byteplan criteria …`, `depends_on`, lifecycle facts in reports (Phase 12 later turns `depends_on` into `blocked_by` links) | – | – |
| 7. Cleanup ✅ | `cleanup.py`, `sync --remove-resolved`, `resolve --sync-source`, `resolved_but_stubbed`, `--suppress-stubs` | – | 13 (cleanup), 14 |
| 8. Release ✅ | `release.py`, `byteplan release [--version] [--dry-run] [--allow-dirty] [--smoke-test]`, `byteplan restore [--dry-run] [--partial]`, presence `stripped`, registry `release`/`releases`, `release_on_default_branch` and `unfinished_scaffold_in_sdist` warnings, Hatch `require_stripped`, documented release-branch workflow | – | release tests below · B: 13–18 |
| 9. MCP ✅ | `[mcp]` extra, `mcp_server.py` with all tools above (including scaffold preview / `scaffold_test`), the three permissions, `byteplan mcp`, README client snippets | – | A: 16 (MCP part), 20 · B: 11 (MCP) |
| 10. Integration ✅ | README end-to-end developer journey (`# TODO` → `scan` → `tests scaffold` → implement → `verify` → `resolve` → `sync`, including where BytePlan notices but never closes work), docs for every config key, dogfood `hatch run byteplan scan` on BytePlan itself, CI on ubuntu/macos/windows | DoD | full suite · B: 19 |
| 11 (optional) | spec §14 phase 5 items, `TODO(owner):` syntax | – | – |
| 11b (optional) | Git reporting: `byteplan diff BASE...HEAD`, SARIF output, Markdown PR annotations | – | – |
| 12. Assignment model (post-1.0; Addendum D: D0–D2, D4) | compatible migration after RC1 (also converts `depends_on` to `blocked_by` links); `presence: unbound`; `binding_proposals`; `approval` + `approve` / `request-changes`, approval-gated `resolve`; `coverage_review`; typed `links` with ref grammar and patch IDs; `create`, `intake` (offline, idempotent), `bind`, `propose-binding`, `link` / `unlink`, `links`, `refs`, `history`, `impact REV`, `links discover` (trailers), `links reconcile` (patch IDs); event actor/revision/idempotency fields; merge driver handles the new fields; MCP gains the §D.7.1 contract (`intake_issue`, `propose_binding`, `bind_source`, `link_artifact`, `scaffold_regression`, `record_verification`, `get_assignment`, `get_handoff`, policy-checked `request_resolution`; no `approve`) | – | D.11: 1–8 (9 for local retries) |
| 13 (optional, separate package) | `relay-for-github/`: reusable workflows (idempotent intake, PR reconciliation, single status comment), triage-agent guide, branch-protection docs, end-to-end demo (issue → intake → binding PR → failing scaffold → fix → verification → human approval → reconciliation, with a retry/failure path) | – | D.11: 9–12 |

<!-- The phases still to build, tracked by BytePlan itself (see byteplan.md). Remove a TODO when
     its phase is marked ✅ in the table above, then `byteplan resolve` it. -->

<!-- TODO[de66]: Phase 6c (optional): acceptance criteria and dependencies
     `acceptance_criteria`, `byteplan criteria ...`, `depends_on`, lifecycle facts in reports. -->

<!-- TODO[75b4]: Phase 11 (optional): spec section 14 phase 5 items
     Includes the `TODO(owner):` syntax, also tracked on its own in comments.py. -->

<!-- TODO[9054]: Phase 11b (optional): Git reporting
     `byteplan diff BASE...HEAD`, SARIF output, Markdown PR annotations. -->

<!-- TODO[15df]: Phase 12: assignment model (Addendum D stages D0-D2, D4)
     Future compatible migration after RC1, unbound assignments, binding proposals, approvals, typed
     links, intake, event provenance, merge-driver support, and the MCP assignment contract. -->

<!-- TODO[ec99]: Phase 13 (optional): relay-for-github
     Separate package: reusable workflows, triage-agent guide, branch-protection docs, end-to-end
     demo. -->

**Phase 10 as built:**
- **CI** runs the suite on ubuntu, macOS and Windows (Python 3.11–3.14). Windows found two real
  bugs: the staged index swap wrote through a text-mode fd (`\n` → `\r\n`, a corrupt index),
  and a write whose directory couldn't be created failed after its journal, leaving a
  transaction no recovery could complete. Git output is now decoded as UTF-8 everywhere.
- **The README journey** ("A task's life, end to end") was captured from a real run.
- **Every config key is documented**, enforced by `tests/test_docs.py`, which compares the
  README's TOML blocks with the config dataclasses and the Hatch hook's settings.
- **The self-managed workflow** is `CONTRIBUTING.md`.

**Phase 8 release tests:**
- `release` changes only decorator lines, runtime imports and the registry. It never commits,
  tags, builds or resets, and `HEAD` is unchanged afterwards.
- On a release branch made by the documented workflow, the commit diff contains only
  decorator/import lines plus the registry, and `main` is untouched. A hotfix cherry-pick applies
  cleanly.
- `--smoke-test` catches a stripped wheel that fails to import, for example a module that uses the
  runtime dynamically. It also catches `byteplan-runtime` being pulled in as a dependency. A smoke
  test failure leaves the tree exactly as before the release. Without the flag, nothing is built.
- A scaffold placeholder in an sdist-included test file stays failing after stripping, and it
  triggers `unfinished_scaffold_in_sdist`.
- `release` followed by `restore` gives back byte-identical files: CRLF, BOM, coding cookie,
  shebang, `__future__`, stacked decorators, and no final newline.
- The stripped tree has no runtime-module references and imports in an environment without
  `byteplan-runtime`.
- No status changes. No task becomes `missing` on scans while stripped, and decorator-derived
  fields and test links are frozen.
- Restore works after a hotfix that shifts lines (AST anchoring). A renamed symbol gives
  `restore_conflict`, and `--partial` leaves the unresolved records in place.
- Refusals cover a dirty tree, an untagged decorator, a decorator sharing a line, an
  already-stripped tree, and a remaining runtime reference.
- A crash mid-release rolls forward through the journal.
- `--dry-run` writes nothing, and `require_stripped` fails an unstripped wheel build.

**Phase 4b Git tests (Addendum C §C9).** These run against real temporary Git repositories
(`git init` in `tmp_path`), never mocked `git diff` output.
- `.git/index` and the working tree are byte-identical before and after every read-only command.
- A staged-valid file passes when the unstaged copy has a syntax error.
- Partially staged files are judged by their blobs.
- Code staged without the registry is rejected even when the working tree is reconciled.
- A registry-only status change is accepted.
- Deleting an annotation in the index gives `missing`. Deleting it together with a staged
  resolution gives nothing.
- Renames keep IDs.
- Filenames with spaces, newlines and Unicode work.
- Added, deleted, untracked and renamed files are told apart.
- A narrowed staged check never reports missing.
- Repeated checks give identical findings.
- `check --staged` and `check --commit HEAD` give identical findings and exit codes when the index
  equals `HEAD`. The working-tree `check` with `require_reconciled = true` matches both.
- A commit with an untagged TODO or an unreconciled title change passes neither the hook nor the
  CI command.
- The pre-commit hook runs through `pre-commit try-repo` on a registry-only commit (marked
  `network`).

**Phase 12 tests (Addendum D §D.11):**
- A v1 registry migrates losslessly, unknown keys survive, and migrating twice changes nothing.
- An unbound assignment is never marked missing, and binding it keeps its ID.
- A source TODO's assignment keeps its pre-existing ID.
- An issue ref and an assignment ID never collide or alias.
- One commit links to several assignments, and one assignment to several commits/PRs. Both query
  directions agree.
- `resolve` is refused when approval is required and missing.
- Neither a merge, a passing test, a deleted TODO nor a closed issue resolves anything.
- Replaying an intake or a write with the same idempotency key is a no-op.
- `impact` labels explicit links, overlap candidates and verified effects separately.
- The merge driver merges links and approval three-way.

**Phase 4c tests.** These run against real Git repositories, like Phase 4b's. They carry over
Addendum C §C9 items 15 and 16, plus:
- **The design principle, end to end.** `git add` + `git commit` of a file with a plain TODO
  produces a commit whose blob and staged registry carry the ID. The working tree matches afterwards
  (no phantom unstaged diff).
- **Every commit mode,** each with a test: plain `git commit`, `git commit -a`,
  `git commit <path>`, `--amend`, and a `core.hooksPath` hook.
- **Partial staging is refused** with nothing written, whether the extra change is in the same file
  or in an unstaged registry edit. An untracked file with a TODO stays untracked and unannotated.
- **Unstaged changes in other files** stay unstaged and out of the commit (index and working-tree
  diffs compared before and after).
- **Concurrency:** an editor save between capture and write, or a concurrent `git add` while
  BytePlan holds the lock, aborts with the index unchanged (or rolled back) and nothing lost.
- **Partial failure:** with three targets (two source files and the registry), the second
  source write fails because of an injected concurrent edit or I/O error. Afterwards:
  - the first file is restored to its staged bytes
  - the second file keeps the developer's edit
  - the registry is untouched
  - the index entries are restored

  An immediate retry with no `partial_stage_conflict` succeeds once the edit is resolved.
- **Crash recovery** at each step-5 boundary: after the index swap, after each working-tree write,
  and during a rollback. Recovery rolls forward when nothing foreign is present and back otherwise,
  is idempotent when re-run, and never overwrites a foreign edit (`rollback_conflict`, exit 2,
  journal kept).
- **Retries:** an immediate re-commit is a no-op, and a second hook run writes nothing.
- **pre-commit framework fixer flow:** the first commit exits 1 with the files annotated, and the
  second commit passes (marked `network` if it needs to install `pre-commit`).
- **Refusals:** split and sparse indexes are refused, and the read-only check still works on them.
- **Safety:** program semantics are unchanged (AST equivalence) for every edit kind: comment `[id]`,
  decorator `id=`, and stub comment line.

**Phase 6b scaffold tests (Addendum B §B8):**
- An untouched scaffold is collected and **fails** in a real pytest subprocess. It never passes,
  and it never skips or xfails unless asked to.
- A repeated scaffold writes nothing.
- An existing file keeps every test byte for byte, with no duplicate imports or names.
- Sync, async (with and without a configured plugin), class, method, property and module-level
  targets each get a safe template.
- A moved or shifted source keeps the same ID and a single association.
- `@verifies` round-trips through a scan.
- A placeholder is never `ready_for_review`.
- `--dry-run` and MCP preview write nothing.
- A crash between the test file and the registry write recovers through the journal.

**Phase 5 runtime tests:** `todo(...)(f) is f` and `verifies(...)(cls) is cls`, including stacked
under `@staticmethod`, `@classmethod`, `@property` and `@functools.wraps`-style decorators.
Application order and behaviour are unchanged, and importing the package does no I/O (checked with
`-X importtime` and an audit hook).

**Phase 6 runner tests** use real pytest subprocesses on fixture projects. They cover every
outcome, a collection error, an unknown node ID, a timeout (a sleeping test with a 1 s limit), and
stale detection after editing the source or the test file.

**Phase 4 tests:**
- `python -m build --no-isolation` on a `tmp_path` copy of `tests/fixtures/projects/hatch_consumer`,
  checking: read-only by default, opt-in writes reach the wheel, two builds are byte-identical,
  `.byteplan/` is absent from both archives, and `CI=1` refuses writes.
- A real isolated build is marked `network`.

**Phase 2 crash test:** make `os.replace` fail on its second call, run `scan` again, and check that
source matches the registry, no ID is allocated twice, and the journal is gone.

**Cross-platform:** fixtures with CRLF, no final newline, a BOM, latin-1 and non-ASCII text. CI runs
ubuntu, macos and windows with `hatch test --all`.
