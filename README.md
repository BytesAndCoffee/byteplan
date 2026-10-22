# BytePlan

[![PyPI - Version](https://img.shields.io/pypi/v/byteplan.svg)](https://pypi.org/project/byteplan)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/byteplan.svg)](https://pypi.org/project/byteplan)

*Plan in code. Track in one place.*

BytePlan is a source-first task tracker for Python projects. You write `# TODO:` where the work is,
or leave a function unfinished, and BytePlan does the rest:
- gives each obligation a permanent four-character ID, written back into the source (`# TODO[7fa2]:`)
- keeps status, priority, owner, notes and history in a Git-versioned registry,
  `.byteplan/tasks.json`
- reconciles the two on every scan

It never decides that work is done. If a TODO disappears, its task is marked **missing**, not
resolved. Only you resolve tasks.

<!-- TODO: The status line below undersells what works. Also mention the Git integration: IDs added
     at commit time (`scan --staged --apply` / `git install-hooks`), `check --staged` and
     `check --commit` for pre-commit and CI, and the registry merge driver. Fix before the next release. -->
> **Status: alpha, in active development.** The CLI, scanner, registry and Hatch hook described
> here work today. Test linking and verification, test scaffolding, release stripping, and an MCP
> server are planned; see the [implementation plan](https://github.com/BytesAndCoffee/byteplan/blob/main/docs/IMPLEMENTATION_PLAN.md) and the
> [changelog](https://github.com/BytesAndCoffee/byteplan/blob/main/CHANGELOG.md).

## Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [What BytePlan tracks](#what-byteplan-tracks)
- [Status, presence and resolution](#status-presence-and-resolution)
- [Commands](#commands)
- [Configuration](#configuration)
- [Hatch integration](#hatch-integration)
- [Safety guarantees and tradeoffs](#safety-guarantees-and-tradeoffs)
- [License](#license)

## Installation

```console
pip install byteplan
```

BytePlan needs Python 3.11+ and has one runtime dependency, `pathspec`. The optional
[`byteplan-runtime`](https://pypi.org/project/byteplan-runtime/) package (Python 3.8+, no
dependencies) provides the `@todo` and `@verifies` decorators. It's only needed if you use them.

## Quick start

```console
$ byteplan init                      # adds [tool.byteplan], creates .byteplan/tasks.json
$ byteplan scan --dry-run            # preview: nothing is written
$ byteplan scan                      # write IDs into source and update the registry
BytePlan: 3 Python files scanned
  3 annotations · 3 tracked tasks
  +3 added · ~0 relocated · !0 missing · !0 duplicate · 0 stale

Annotated:
  + [33b4] TODO  src/pkg/rip.py:2  Implement route poisoning
  + [dc20] FIXME src/pkg/rip.py:5  ARP entries outlive interfaces
  + [243a] TODO  src/pkg/rip.py:22  Implement Router.withdraw (detected stub)
$ byteplan list
$ byteplan edit 33b4 --priority high --assignee sam --label routing
$ byteplan status 33b4 in_progress
$ byteplan resolve 33b4 --note "shipped in 1.2"
```

Commit `.byteplan/tasks.json` along with your code. `init` keeps `.byteplan/` out of Hatch sdists
and ignores BytePlan's working files (`.byteplan/txn/`, `.byteplan/scan.lock`).

## What BytePlan tracks

**Tagged comments.** `TODO`, `FIXME`, `HACK` and `XXX` (case-insensitive, configurable) at the
start of a comment. An indented comment line directly below becomes the description:

```python
# TODO: Implement route poisoning
#   Support split horizon and poisoned reverse.
```

- **Continuation lines:** a line continues the description only if it's directly below, in the same
  column, and has at least two spaces after `#`. A blank line, code, another tag or an ordinary
  comment ends it.
- **Ignored on purpose:** comments are found with `tokenize`, so strings, docstrings and
  commented-out code such as `# x = f()  # TODO` are never tasks.
- **Trailing comments:** `x = 1  # TODO: ...` counts too.

**Unfinished implementations (stubs).** These are found with `ast`:
- functions and methods whose body is `pass`, `...`, only a docstring, or
  `raise NotImplementedError`
- empty classes

Excluded automatically:
- `@abstractmethod`, `@overload`
- `Protocol` classes and their methods
- deliberately empty classes: exceptions, enums, `TypedDict`, `NamedTuple`

**Interfaces and overrides aren't stubs.** BytePlan looks at the whole project's class hierarchy:
- **Base-class interface methods:** a base class method that raises `NotImplementedError` (or is
  `pass`/`...`) isn't reported when a subclass, at any depth, implements it.
- **No-op overrides:** a method that overrides one inherited from a project base class isn't
  reported either.
- **Duck-typed hooks:** a no-op that no shared base declares can't be told apart from unfinished
  work, so mark it `# byteplan: ignore`.

A stub that already has a TODO above it or inside it, or a `@todo`, is the same task, not a
second one. Otherwise BytePlan adds `# TODO[id]: Implement Router.withdraw (detected stub)` above
it. One-line stubs like `def f(): pass` are reported for review instead of edited. Mark
intentional no-ops with `# byteplan: ignore` on the `def` or decorator line.

**Decorators** (optional, with `byteplan-runtime`):

```python
from byteplan_runtime import todo

@todo("Implement poisoned reverse", tests=("tests/test_routing.py::test_poisoned_reverse",))
def advertise_routes(self):
    raise NotImplementedError
```

- **Runtime behaviour:** the decorators do nothing at all; they return the function unchanged.
- **How BytePlan reads them:** statically, never by importing your code, and adds `id="…"` on the
  first scan.
- **What counts:** only names really imported from `byteplan_runtime`, or a shim module you list in
  `runtime_modules`. A local or shadowed `todo` is ignored.

**Suppression.**
- `# byteplan: ignore` inside a tag comment skips that tag.
- `# byteplan: ignore-file` in a file's first five lines skips the whole file.

## Status, presence and resolution

Every task has two independent dimensions:

| | Values | Changed by |
|---|---|---|
| **status** | `open`, `in_progress`, `blocked`, `resolved`, `dismissed` | only you: `status`, `resolve` |
| **presence** | `present`, `missing`, `unknown` | scans |

- **Missing:** when the annotation disappears, the task becomes `missing` and keeps its status and
  history.
- **Reappeared:** if the annotation comes back (same ID), the task becomes `present` again.
- **Stale annotation:** a resolved task whose annotation is still in source is reported, never
  removed for you.
- **`implementation_changed`:** when a tracked stub gets a real body, BytePlan reports it once. It
  doesn't resolve the task.

IDs never change and are never reused. Line numbers, file paths and function names are only
metadata, so moving or renaming code keeps the same task.

## Commands

| Command | What it does |
|---|---|
| `byteplan init` | add configuration and an empty registry (safe to re-run) |
| `byteplan scan [PATHS] [--dry-run] [--staged]` | discover, add IDs, reconcile, report. With paths, the scan is narrowed and never marks anything missing. `--staged --dry-run` previews against the Git index |
| `byteplan scan --staged --apply` | add IDs to the staged commit (index and working tree) before it's finalized; what the pre-commit hook runs |
| `byteplan check [--staged \| --commit REV]` | read-only validation, with policy-based exit code. `--staged` checks exactly what's staged (pre-commit); `--commit HEAD` checks a commit (CI) |
| `byteplan list [--status S] [--presence P] [--kind K]` | list tasks |
| `byteplan show ID` | details, location and history |
| `byteplan status ID STATUS [--note]` | change lifecycle status |
| `byteplan resolve ID [--note]` | mark resolved (never edits source) |
| `byteplan edit ID [--priority] [--assignee/--unassign] [--label] [--remove-label] [--notes/--add-note] [--title/--clear-title]` | managed fields; scans never overwrite them |
| `byteplan missing` | tasks no longer found in source |
| `byteplan duplicates` | the same ID on more than one annotation |
| `byteplan report [--format text\|json\|markdown]` | summary by status, presence, kind and priority, plus findings |
| `byteplan repair --import ID` | register an ID found in source but not in the registry |
| `byteplan repair --reassign PATH:LINE` | give a duplicated ID's copy a fresh ID |
| `byteplan git install-merge-driver` | merge the registry by task ID in Git merges (per clone) |
| `byteplan git install-hooks [--mode reconcile\|check\|scan]` | direct pre-commit hook (default `reconcile`: IDs at commit time); never replaces a hook it didn't write |
| `byteplan git hooks-status` | show the pre-commit framework hook, direct hook and merge driver |
| `byteplan merge-registry BASE OURS THEIRS [PATH]` | the merge driver itself; Git runs it, you don't |

- **Common options:** `--project PATH` and `--format json` go after the command.
- **Output streams:** stdout carries only the result (pure JSON with `--format json`); diagnostics
  go to stderr.
- **Exit codes:** `0` OK, `1` findings that fail your `[tool.byteplan.check]` policy (duplicate IDs
  by default), `2` errors (bad config, unreadable registry, a file that won't parse).

## Configuration

Everything lives in `pyproject.toml`. These are the defaults:

```toml
[tool.byteplan]
registry = ".byteplan/tasks.json"
include = ["**/*.py"]
exclude = ["**/.venv/**", "**/venv/**", "**/__pycache__/**", "**/build/**", "**/dist/**",
           "**/.tox/**", "**/.nox/**", "**/node_modules/**", "**/*.pyi"]
respect_gitignore = true
auto_annotate = true          # false: only track comments that already carry an ID
missing_policy = "warn"       # or "ignore"

[tool.byteplan.detect]
todo_tags = ["TODO", "FIXME", "HACK", "XXX"]
pass_stubs = true
ellipsis_stubs = true
not_implemented_stubs = true
empty_classes = true
respect_overrides = true       # interface methods and no-op overrides aren't stubs (see below)

[tool.byteplan.check]
fail_on_duplicate_ids = true
fail_on_missing = false
fail_on_stale_annotations = false

[tool.byteplan.annotations]
runtime_modules = ["byteplan_runtime"]   # add a project shim module here
```

- **Paths and patterns:** paths are relative to the project root (the directory with
  `pyproject.toml`), not your current directory. Patterns use `.gitignore` syntax.
- **Strictness:** unknown keys are errors, so typos don't silently do nothing.

## Hatch integration

BytePlan ships a Hatchling build hook. Enable it in the project that uses BytePlan:

```toml
[build-system]
requires = ["hatchling", "byteplan"]
build-backend = "hatchling.build"

[tool.hatch.build.hooks.byteplan]
scan = true            # set false to disable without removing the table
write_source = false   # false | true | "editable"
fail_build = false     # fail the build on findings that fail [tool.byteplan.check]
allow_in_ci = false    # write_source still won't write when $CI is set, unless this is true
```

- **Read-only by default.** A build runs `byteplan check` and prints its findings. Your checkout is
  never modified, so release builds and CI stay reproducible.
- **Writes are opt-in.** With `write_source = true`, every local `hatch build` runs `byteplan scan`
  before packaging. New IDs land in your source, so you'll see Git changes after a build. That's
  the point of this mode, but don't enable it unless you want it.
  - `write_source = "editable"` writes only for editable installs (`pip install -e`, Hatch dev
    environments).
  - With `$CI` set, writes are refused unless `allow_in_ci = true`.
- **Building from an sdist:** there's no registry in an unpacked sdist, so the hook does nothing.
- **Registry packaging:** the hook warns if the sdist would include `.byteplan/`.
- **Without the plugin:** [`examples/hatch_build.py`](https://github.com/BytesAndCoffee/byteplan/blob/main/examples/hatch_build.py) is a minimal custom
  hook (`[tool.hatch.build.hooks.custom]`) that does the read-only check.
- **Without Hatch:** `byteplan scan` and `byteplan check` work in CI, pre-commit hooks and editor
  tasks.

## IDs at commit time

Install the hook once per clone, and every new TODO gets its ID as you commit:

```console
$ byteplan git install-hooks
$ echo '# FIXME: Handle withdrawn routes' >> src/rip.py
$ git add . && git commit -m "Document route withdrawal bug"
byteplan: annotated 2 staged file(s)
  [a83f] FIXME src/rip.py:42  Handle withdrawn routes
$ git show HEAD:src/rip.py | tail -1
# FIXME[a83f]: Handle withdrawn routes
```

**What it writes.** Only BytePlan's own annotations (`[id]`, `id="…"`, stub comments) and
`.byteplan/tasks.json`. They go into both the staged copy and your working tree, so nothing is left
behind as an unstaged diff.

**What it refuses.** If a file has unstaged changes as well as staged ones
(`partial_stage_conflict`), or the registry has unstaged edits, it writes nothing and the commit
stops. It never stages anything you didn't, and never runs `git add` on your files.

**If anything goes wrong mid-way,** everything it changed is undone, and an interrupted run is
finished or undone by the next one.

**Commit modes:**
- **`git commit`, `-a`, `--include` and `--amend`** all work.
- **`git commit <paths>`** uses a temporary index BytePlan can't safely update, so it only checks
  in that mode and tells you why.

**Settings and alternatives:**
- **Review first:** set `[tool.byteplan.git] on_reconcile = "stop"` to review annotations before
  the commit proceeds.
- **pre-commit framework:** the `byteplan-reconcile` hook works like a formatter. It annotates the
  files and fails, and after `git add` the next commit passes.

## Git hooks and CI

The committed backlog should describe the committed code. Three read-only commands check that,
with the same rules everywhere:

```console
$ byteplan check --staged          # pre-commit: exactly what's staged, never the working tree
$ byteplan check --commit HEAD     # CI: the checked-out commit
$ byteplan scan --staged --dry-run # preview what the staged snapshot still needs
```

**What fails a snapshot check:**
- a TODO without an ID (`new_unregistered`)
- source staged without the updated registry (`registry_not_staged`)
- a registry that doesn't reflect its code (`registry_out_of_sync`)
- IDs that aren't registered anywhere

**What doesn't:** line numbers that merely shifted (`position_drift`) are informational.

**How it reads the snapshot:**
- **Git objects only.** It never reads the working tree, so a broken unstaged file can't block
  a valid commit.
- **Read-only.** It never changes `.git/index`, never runs your tests, and never imports your
  code.

**Setup:**
- **pre-commit framework:** use the hook `byteplan-check` from this repository.
- **Direct hook:** `byteplan git install-hooks`.
- **CI recipe:** see [docs/ci.md](https://github.com/BytesAndCoffee/byteplan/blob/main/docs/ci.md).

The hooks are a convenience and can be skipped with `--no-verify`; CI is where to enforce.

## Merging the registry in Git

`.byteplan/tasks.json` is plain, deterministic JSON, so it diffs and reviews like code. Two
branches that each add tasks would still conflict on the shared `reserved_ids` list under Git's
text merge, so BytePlan ships a merge driver that merges **by task ID**:

```console
$ byteplan git install-merge-driver
byteplan: added `tasks.json merge=byteplan` to .byteplan/.gitattributes (commit this file)
byteplan: set git config merge.byteplan.name (local to this clone)
byteplan: set git config merge.byteplan.driver (local to this clone)
```

**What merges automatically:**
- Reserved IDs and tasks combine (IDs are never reused).
- Both sides' history events are kept, in order.
- Labels merge as a set.
- Fields changed on only one side, such as status on one branch and priority on the other, take
  that side's value.

**What it leaves to you.** These fall back to Git's normal text merge with conflict markers,
plus an explanation:
- the same field changed differently on both sides
- the same ID created on both branches for different work
- a task removed on one side and changed on the other

If both branches moved the same annotation, the merged registry keeps our location and asks you
to run `byteplan scan`, which refreshes it from the merged code.

**Per clone, and safe to skip.** Commit `.byteplan/.gitattributes`. Each clone runs
`byteplan git install-merge-driver` once, because Git doesn't version merge-driver configuration.
A clone that hasn't installed the driver just gets Git's ordinary text merge. The driver is
recorded as `<this Python> -m byteplan`, so it works even when Git runs outside your virtualenv;
re-run the installer if you recreate that environment.

## Linters

Ruff's flake8-todos rule **TD004** ("missing colon in TODO") expects the colon directly after the
tag, so it flags BytePlan's annotated form `# TODO[a6b2]: ...`. Hatch's default ruff rules enable
TD004. If you lint with them, ignore that one rule:

```toml
[tool.ruff]
lint.extend-ignore = ["TD004"]
```

Use `lint.extend-ignore` rather than `extend-ignore`. Hatch skips its default ruff configuration
for a `[tool.ruff]` table containing a line that starts with `extend`. The other flake8-todos
rules aren't affected.

## Safety guarantees and tradeoffs

**What BytePlan guarantees.**
- **Scans are idempotent:** a second scan of unchanged code changes nothing, not even timestamps.
- **Edits are minimal:** each edit inserts only the ID text, and must leave the parsed program
  unchanged apart from added decorator `id=` keywords.
- **Encodings and formatting survive:** BOMs, coding cookies, CRLF, tabs, shebangs and a missing
  final newline are all preserved byte-for-byte.
- **Writes are journaled and crash-safe:** a multi-file update is staged under a lock and journaled
  before anything is replaced. Each file is replaced atomically with its permissions kept, and the
  registry goes last.
- **Interrupted writes finish safely:** the next write command completes them. If a file was
  changed by something else in the meantime, BytePlan stops instead of overwriting it.
- **Failures stop the scan cleanly:** a file that can't be read or parsed, or a directory that can't
  be listed, fails the whole scan before anything is reconciled.

**Tradeoffs worth knowing.**
- **No cross-file atomicity.** Filesystems have no multi-file atomic rename. The journal guarantees
  completion (roll-forward), not that all files change at the same instant.
- **A small race window remains.** Each file's content is re-checked immediately before it's
  replaced, but nothing portable can close the gap between that check and the rename.
- **Symlinks are never followed.** That prevents scanning a file twice or reaching outside the
  project.
- **Only `.gitignore` files are honoured.** `.git/info/exclude` and global Git excludes aren't read.
- **Stub detection is a heuristic.** It reports candidates; `# byteplan: ignore` and the
  `[tool.byteplan.detect]` switches are there for intentional no-ops.
- **Duplicate IDs block all writes** until you resolve them, so nothing ambiguous is ever rewritten.

## License

`byteplan` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
