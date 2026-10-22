# BytePlan implementation plan

The behavioural contract is [`spec.md`](spec.md), extended by
[`spec-addendum-a.md`](spec-addendum-a.md) and [`spec-addendum-b.md`](spec-addendum-b.md).
Addendum A covers `@todo` decorators, stub decoration, acceptance-test links, verification, and
registry-to-source cleanup. Addendum B covers test scaffolding, optional acceptance criteria,
release-stripping semantics, and the end-to-end development workflow. This document records how it is
built, the decisions both documents leave open, and the phase order. Toolchain: Hatch / Hatchling
(verified against Hatch 1.18.1, Hatchling 1.32.4).

One rule underlies everything: the disappearance of a comment, the disappearance of a stub, or a
passing test never resolves a task. Only an explicit `status`/`resolve` does.

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
  ids.py            shake_128 16-bit candidates, collision retry, exhaustion error
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
  api.py            Project facade: the single programmatic surface used by cli, hook and MCP
  cli.py            argparse; stdout = payload, stderr = diagnostics
  hatch_hook.py     BuildHookInterface subclass + hookimpl registration
  mcp_server.py     MCP server (optional extra), thin adapter over api.py
  _verify_plugin.py pytest plugin injected into `verify` runs (pytest-only imports)
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

The new fields stay in `schema_version` 1. Version 1 hasn't been released with real data yet
(0.0.1 was a placeholder), so no migration is needed. All of them are optional on read and always
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

## Phases

Each phase ends green on `hatch fmt --check`, `hatch run types:check` and `hatch test --all`.

Addendum A's six-step order (§10) and Addendum B's order (§B9) are merged in below. Addendum B's items are planned, not implemented, until their phase is marked ✅. Its step 2 (choosing the runtime design)
is done above, so the runtime package can ship before anything generates decorators.

| Phase | Deliverables | Spec §12 tests | Addendum §9 tests |
|---|---|---|---|
| 0. Scaffold ✅ | pyproject (3.11+, URLs, envs, sdist excludes), CLI skeleton, smoke tests, `.gitignore`, docs/ | – | – |
| 1. Core ✅ | config, files, registry, ids, source + comment scanner, `api.Project`, CLI `init/scan(report-only)/list/show` | 1, 5, 19, 20 | – |
| 2. Write path ✅ | `edits.py` (span edits + equivalence guard), comment annotation, reconcile, persistence (journal, concurrent-modification check), `status/resolve/edit/missing/duplicates`, `--dry-run` | 6–17 | 13 (resolve without source edits), 15, 17, 18 |
| 3. Stubs + decorators | `stubs.py`, `decorators.py` (static `@todo`/`@verifies` discovery, alias resolution), `association.py` (comment / decorator / stub → one obligation), decorator `id=` allocation, schema fields, `implementation_changed`, `check`, `report`, `repair` | 2, 3, 4, 17 | 1, 2, 6 (comment mode), 7, 19 |
| 4. Hatch | hatch_hook + entry point, `examples/hatch_build.py`, decorator discovery in builds (read-only), README onboarding | 18 | 16 (Hatch part) |
| 5. Runtime + normalization | `byteplan-runtime/` project (✅ 0.1.0 on PyPI: inert `todo`/`verifies`), `init --runtime-shim`, `[tool.byteplan.annotations]`, `normalize.py`, `byteplan sync --dry-run/--apply` | – | 3, 4, 5, 6 (decorator mode), 8 |
| 6a. Acceptance tests | test links + provenance, `byteplan tests list/add/remove`, `_verify_plugin.py`, `verification.py`, `byteplan verify [ID] [--json] [--ready]`, readiness, freshness | – | A: 9, 10, 11, 12 · B: 10 |
| 6b. Test scaffolding | `scaffold.py` planner, `byteplan tests scaffold ID [--path] [--name] [--policy] [--force-new] [--dry-run]`, placeholder detection, `[tool.byteplan.tests.scaffold]` | – | B: 1–9, 11 (CLI), 12 |
| 6c. Criteria + dependencies (optional) | `acceptance_criteria`, `byteplan criteria …`, `depends_on`, lifecycle facts in reports | – | – |
| 7. Cleanup | `cleanup.py`, `sync --remove-resolved`, `resolve --sync-source`, `resolved_but_stubbed`, `--suppress-stubs` | – | 13 (cleanup), 14 |
| 8. Release | `release.py`, `byteplan release [--version] [--dry-run] [--allow-dirty] [--smoke-test]`, `byteplan restore [--dry-run] [--partial]`, presence `stripped`, registry `release`/`releases`, `release_on_default_branch` and `unfinished_scaffold_in_sdist` warnings, Hatch `require_stripped`, documented release-branch workflow | – | release tests below · B: 13–18 |
| 9. MCP | `[mcp]` extra, `mcp_server.py` with all tools above (including scaffold preview / `scaffold_test`), the three permissions, `byteplan mcp`, README client snippets | – | A: 16 (MCP part), 20 · B: 11 (MCP) |
| 10. Integration | README end-to-end developer journey (`# TODO` → `scan` → `tests scaffold` → implement → `verify` → `resolve` → `sync`, including where BytePlan notices but never closes work), docs for every config key, dogfood `hatch run byteplan scan` on BytePlan itself, CI on ubuntu/macos/windows | DoD | full suite · B: 19 |
| 11 (optional) | spec §14 phase 5 items, `TODO(owner):` syntax | – | – |

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
