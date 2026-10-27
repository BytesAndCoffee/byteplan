# BytePlan

[![PyPI - Version](https://img.shields.io/pypi/v/byteplan.svg)](https://pypi.org/project/byteplan)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/byteplan.svg)](https://pypi.org/project/byteplan)

*Plan in code. Track in one place.*

BytePlan is a source-first task tracker for Python projects. You write `# TODO:` where the work is,
or leave a function unfinished, and BytePlan does the rest:
- gives each obligation a permanent hexadecimal ID, written back into the source (`# TODO[7fa2]:`)
- keeps status, priority, owner, notes and history in a Git-versioned registry,
  `.byteplan/tasks.json`
- reconciles the two on every scan

It never decides that work is done. If a TODO disappears, its task is marked **missing**, not
resolved. Only you resolve tasks.

> **Status: preparing 1.0.0rc1 (beta).** Final release validation and approval remain pending.
> The current implementation includes:
> - the CLI, scanner and registry, for Python, Markdown and JSON
> - Git integration: IDs added at commit time, staged and CI checks, and the merge drivers
> - acceptance tests: linking, scaffolding and `byteplan verify` with recorded evidence
> - the committed `byteplan.md` task list, and archiving long-closed tasks
> - decorator mode (`byteplan sync`), release stripping, and the Hatch hook
> - an MCP server for AI agents
>
> Assignments (linking tasks to issues, commits and PRs) are planned. See the
> [implementation plan](https://github.com/BytesAndCoffee/byteplan/blob/main/docs/IMPLEMENTATION_PLAN.md)
> and [Addendum E](docs/spec-addendum-e.md) for RC1 hardening and the proposed 1.5/2.0 semantic
> graph roadmap. Graph implementation is deferred until after 1.0 stable. Shipped changes are
> recorded in the [changelog](https://github.com/BytesAndCoffee/byteplan/blob/main/CHANGELOG.md).

## Contents

- [Installation](#installation)
- [Quick start](#quick-start)
- [A task's life, end to end](#a-tasks-life-end-to-end)
- [What BytePlan tracks](#what-byteplan-tracks)
- [Status, presence and resolution](#status-presence-and-resolution)
- [Commands](#commands)
- [Configuration](#configuration)
- [1.0 compatibility boundary](#10-compatibility-boundary)
- [Hatch integration](#hatch-integration)
- [MCP server for AI agents](#mcp-server-for-ai-agents)
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

New tasks receive six-character IDs. Four-character IDs in existing projects and the examples
below remain fully supported. Existing projects must [migrate their registry](docs/rc1-compatibility.md#migration-and-recovery)
before allocating new IDs with this version.

```console
$ byteplan init                      # adds [tool.byteplan], creates .byteplan/tasks.json
$ byteplan scan --dry-run            # preview: nothing is written
$ byteplan scan                      # write IDs into source and update the registry
BytePlan: 3 files scanned
  3 annotations · 3 tracked tasks
  +3 added · ~0 relocated · !0 missing · !0 duplicate · 0 stale

Annotated:
  + [33b421] TODO  src/pkg/rip.py:2  Implement route poisoning
  + [dc20f8] FIXME src/pkg/rip.py:5  ARP entries outlive interfaces
  + [243a09] TODO  src/pkg/rip.py:22  Implement Router.withdraw (detected stub)
$ byteplan list
$ byteplan edit 33b421 --priority high --assignee sam --label routing
$ byteplan status 33b421 in_progress
$ byteplan resolve 33b421 --note "shipped in 1.2"
```

Commit `.byteplan/tasks.json` along with your code. `init` keeps `.byteplan/` out of Hatch sdists
and ignores BytePlan's working files (`.byteplan/txn/`, `.byteplan/scan.lock`).

## A task's life, end to end

One obligation, from a comment to a resolved task with evidence. (`pyproject.toml` lists
`byteplan-runtime` as a dev dependency, for `@verifies`.)

**1. Write the TODO where the work is, and scan.** The task gets an ID, in the source and in the
registry. With the commit hook (`byteplan git install-hooks`), committing does this for you.

```console
$ byteplan scan
Annotated:
  + [9333] TODO  src/rip/routes.py:2  Advertise routes through a dead neighbour as unreachable
```

**2. Scaffold its acceptance test.** It fails on purpose, so it can't be mistaken for evidence.
With `[tool.byteplan.tests.scaffold] auto = true`, step 1's scan does this too.

```console
$ byteplan tests scaffold 9333
byteplan: [9333] scaffolded tests/test_routes.py::test_poison (new file)
```

```python
@verifies("9333")
def test_poison():
    """Acceptance test scaffold for BytePlan task 9333. ..."""
    # GIVEN: TODO - arrange the state this requirement depends on
    # WHEN: TODO - call poison
    # THEN: TODO - assert the required result
    pytest.fail("BytePlan 9333: acceptance test not implemented")
```

**3. Implement it, and replace the placeholder with the real test.** Keep the `TODO[9333]`
comment until the task is resolved.

```python
@verifies("9333")
def test_poison():
    routes = {"10.0.0.0/8": (2, "r1"), "10.1.0.0/16": (1, "r2")}
    assert poison(routes, dead="r1") == {"10.0.0.0/8": (INFINITY, "r1"), "10.1.0.0/16": (1, "r2")}
```

**4. Verify.** BytePlan runs the linked tests and records the results in
`.byteplan/verification.json`.

```console
$ byteplan verify 9333
BytePlan verify: 1 test result(s) for 1 task(s) · 1 passed
  [9333] ready_for_review Advertise routes through a dead neighbour as unreachable
      passed    tests/test_routes.py::test_poison
Readiness never changes a task's status; resolve tasks yourself.
```

**5. Resolve it.** That's your call, not BytePlan's. `--sync-source` also removes the annotation.
In decorator mode, `byteplan sync --remove-resolved` does the same for every closed task.

```console
$ byteplan resolve 9333 --sync-source --note "poisoned reverse, verified"
byteplan: [9333] resolved
BytePlan cleanup: 1 annotation(s) removed · 0 suppressed
  - [9333] src/rip/routes.py
```

The task stays in the registry with its history and evidence. A week after it's closed, a scan
moves it to the archive (see [Status, presence and resolution](#status-presence-and-resolution)).

**Where BytePlan notices, but never closes work:**
- **A deleted TODO** makes its task `missing`, still `open`:
  ```console
  ! [76ea] MISSING           src/rip/routes.py
      task 76ea is no longer in source (previously line 9); its status is still open
      hint: if the work is done, run `byteplan resolve 76ea`; if the annotation was removed by mistake, restore it
  ```
- **Passing tests** make a task `ready_for_review`, as in step 4. Its status doesn't change.
- **An implemented stub** is reported once as `implementation_changed`, or as
  `implementation_complete_candidate` when its linked tests are fresh and passing. Either way it
  stays open until you resolve it.
- **A closed task whose annotation is still in source** is a `stale_annotation` warning.
  `resolve --sync-source` or `sync --remove-resolved` removes the annotation.

## What BytePlan tracks

**Tagged comments.** `TODO`, `FIXME`, `HACK` and `XXX` (configurable) at the start of a comment.
An indented comment line directly below becomes the description:

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
- **Other spellings:** `# todo: ...` or `# Fixme[7fa2]: ...` count when a `:` or `[id]` follows the
  tag. Without one, only the configured spelling does, so prose like `# Todo list model` is left
  alone.

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
- **Acceptance tests:** `tests=("tests/test_routing.py::test_poison",)` on `@todo`, or
  `@verifies("a83f")` on the test itself, links a task to the tests that prove it.
  `@pytest.mark.byteplan("a83f")` works too with `[tool.byteplan.tests] pytest_marker = true`,
  and `byteplan tests add` links tests by hand. `byteplan tests list` and `byteplan show` list
  each link with its provenance (`decorator`, `verifies`, `marker`, `managed`).
  - Links declared in source are refreshed by every scan.
  - Hand-added links are only changed by `tests add/remove`.
  - A linked test file that doesn't exist, or isn't scanned, is reported as `test_not_in_scope`.
- **Scaffolding:** `byteplan tests scaffold ID` writes a test for the task that fails on purpose
  (`pytest.fail("BytePlan a83f: acceptance test not implemented")`), with GIVEN/WHEN/THEN
  comments and no invented fixtures or assertions.
  - Where it goes: it's linked with `@verifies` by default, and appended to the matching test
    file (`tests/test_<module>.py`) without touching existing code.
  - Re-running: it reports the existing test instead of adding another.
  - Until you replace the `pytest.fail(...)` body, it's a placeholder: `check` notes it, and
    it can never make the task `ready_for_review`.
  - Automatically: with `[tool.byteplan.tests.scaffold] auto = true`, a writing `scan` scaffolds
    a test for each open task it adds in a Python file outside the test directory. Tasks in
    test files or other formats, and tasks added by the commit hook, are left to
    `tests scaffold`. Pair it with `policy = "xfail"` to keep CI green: the strict xfail fails
    as soon as the code works, prompting you to write the real test.
- **Verifying:** `byteplan verify` runs the linked tests with pytest in a subprocess and records
  each result in `.byteplan/verification.json`.
  - Outcomes: `passed`, `failed`, `skipped`, `xfailed`, `xpassed`, `error`, `not_found`,
    `not_run` or `timeout`. Only `passed` counts as evidence.
  - Readiness: each task is `unverified`, `failing`, `needs_review` (skips, stale results, or
    a declaration that's still a stub) or `ready_for_review`.
  - Results go stale when the file holding the task's annotation or a linked test file
    changes. Edits elsewhere, such as the implementation in another module, leave them
    fresh; set `stale_on = "head"` to go stale whenever HEAD moves or the tree is dirty.
  - Readiness is advice: no task is ever resolved automatically.
- **No new dependency?** `byteplan init --runtime-shim src/pkg/_byteplan.py` writes an inert
  `todo`/`verifies` module and registers it in `runtime_modules`.

**Decorator mode: `byteplan sync`.** With `mode = "decorator"`, BytePlan can rewrite tasks into
decorators for you. It's opt-in, and it's never done by `scan`:

```toml
[tool.byteplan.annotations]
mode = "decorator"
convert_attached_comments = true   # a tagged comment right above a def/class becomes @todo(...)
auto_decorate_stubs = true         # unowned stubs get @todo("Implement <name>", id=...)
```

```console
$ byteplan scan                     # IDs first
$ byteplan sync                     # preview
  ~ [a83f] FIXME src/routes.py:9  comment -> @todo: Withdraw routes on link loss
  + [65ea] TODO  src/routes.py:14  @todo on stub Router.advertise: Implement Router.advertise
$ byteplan sync --apply             # write (journaled), update the registry
```

- **What converts:** only a comment block that ends directly above a `def` or `class`, in the
  same column with no blank line, becomes `@todo(title, id=..., kind=..., description=...)`,
  the outermost decorator. Module-level, trailing, in-body and separated comments stay comments
  and are reported as `conversion_needs_review`. `--only ID` limits the rewrite.
- **Runtime import:** `from byteplan_runtime import todo` is added after the docstring and
  `__future__` imports, but only if `byteplan-runtime` is in `[project].dependencies` or a
  configured shim exists. An existing import (or `import byteplan_runtime as br`) is reused.
- **Safe by construction:**
  - Each file must parse to the same AST once BytePlan's own decorators and imports are
    removed, and must re-scan to the same tasks.
  - Shebangs, encoding cookies, BOM, CRLF and a missing final newline are kept.
  - Task IDs, kinds and descriptions never change.
- **Scan in `preserve` and `decorator` modes** still writes IDs into comments, but it reports
  unowned stubs (`stub_needs_review`) instead of adding `# TODO` lines for them.

**Markdown and JSON.** Add them to `include` (for example `"**/*.md"`, `"config/**/*.json"`)
and BytePlan tracks tags there too, with the same IDs, registry and Git integration:

```markdown
<!-- TODO: Document the merge driver
     Show the .gitattributes line and a conflict example. -->
```

```jsonc
{
  // FIXME: Turn on strict mode once the legacy modules are typed
  "strict": false,
  "scripts": { "todo": "TODO: pin the release script's version" }
}
```

- **Markdown:** tags in HTML comments, so they don't render. The first line is the title and
  the rest of the comment is the description. Prose and code (fenced blocks, inline code) are
  never scanned. The symbol is the nearest heading.
- **Fully hidden Markdown comments:** `[//]: # (TODO: title)` is an unused link definition, so
  it's missing even from the generated HTML. Any label works, the title can use `()`, `""` or
  `''`, and following `[//]: # (  more)` lines indented two spaces are the description. Like any
  link definition it can't interrupt a paragraph, so leave a blank line (or a heading) above it.
- **JSON** (`.json`, `.jsonc`): `//` and `/* */` comments, as in `tsconfig.json`. Strict JSON
  can't hold comments, so a **string value** that starts with `TODO:` (case-sensitive, colon
  required) is tracked too, and its ID goes inside the string. Turn that off with
  `json_string_values = false`. The symbol is a JSON Pointer such as `/scripts/todo`.
- **Not applicable:** stubs and decorators are Python-only. Other file types are never scanned,
  even if `include` matches them.

**Suppression.**
- `# byteplan: ignore` inside a tag comment skips that tag (in any format).
- `# byteplan: ignore-file` in a file's first five lines skips the whole file
  (`<!-- byteplan: ignore-file -->` in Markdown, `// byteplan: ignore-file` in JSON).

## Status, presence and resolution

**Cleaning up after yourself.** Resolving never edits source on its own. When you want the
finished TODOs gone, ask BytePlan to remove them rather than deleting them by hand:

```console
$ byteplan resolve a83f --sync-source           # one task
$ byteplan sync --remove-resolved               # preview every closed task's annotation
$ byteplan sync --remove-resolved --apply
```

- **What's removed:** only the exact annotation, in any format.
  - Python: the tag and its continuation lines, a trailing tag from its `#`, or an `@todo(...)`
    on lines of its own. The `todo` import goes too, once nothing uses it.
  - Markdown: the HTML or link-reference comment.
  - JSON: the comment.
- **What's never touched:** other comments, decorators, code and tests. A JSON string value is
  data, so it's left for you (`cleanup_needs_review`).
- **How it's checked:** Python files must keep the same AST, and every file must re-scan to its
  old tasks minus the removed ones.
- **What the registry keeps:** the ID, the last source location and the history, with a
  `cleaned` event added.
- **Stubs:** a closed task whose code is still a stub is refused (`resolved_but_stubbed`), so the
  next scan doesn't just rediscover it. Implement it, or use `--suppress-stubs` to leave a
  visible `# byteplan: ignore` on its `def` line.
- **Automatically:** set `remove_resolved = true` and plain `byteplan sync --apply` does it.

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

Persistent IDs are lowercase hexadecimal strings of at least four characters; new allocations
use six. Commands accept an exact ID first, then an unambiguous prefix. An exact legacy ID
wins even when a longer ID starts with it. Ambiguous prefixes report candidates and change
nothing. Store full IDs in annotations, verification references and external mappings.

**Archiving.** Closed tasks don't stay in `tasks.json` forever. Once a task has been resolved or
dismissed for a week (`[tool.byteplan.archive] after_days`) and its annotation is gone from
source, the next writing `scan` moves it out (or run `byteplan archive` yourself):

- **Local store:** `.byteplan/archive.sqlite` (gitignored) keeps the full record and its
  verification evidence, zlib-compressed.
- **Reconciliation artifact:** `.byteplan/archive.json` (committed) lists each archived task's
  title, status, dates and the sha256 of its record. It's small and merges by task ID.
- **Other clones:** every archived record is in an earlier commit's `tasks.json`. `byteplan show
  ID` finds it there by hash when the local store lacks it, and `byteplan archive --reconcile`
  fills the store for all of them at once. This may populate the ignored local cache, but never
  rewrites source or authoritative JSON. Evidence is not automatically reconciled; inspect its
  committed Git history to recover historical results, then reverify for fresh evidence.
- **Only committed records and evidence move:** in a Git repository, the current task record,
  its evidence and referenced run must be committed before archival removes them from shared
  JSON. Staging alone is insufficient. Unrelated evidence edits do not block a task's archival.
- **Outside Git:** the SQLite store may be the only archived copy; back it up. See the
  [storage contract and recovery limits](docs/rc1-storage.md).
- **What stays:** the ID stays in `reserved_ids`, so it's never reused. If it turns up in source
  again, `check` says it's archived; `byteplan archive --restore ID` brings it back.

## Commands

| Command | What it does |
|---|---|
| `byteplan init [--runtime-shim PATH]` | add configuration and an empty registry (safe to re-run); optionally write an inert runtime shim |
| `byteplan verify [ID...]` | run linked tests with pytest, record evidence, show readiness (`--ready` lists tasks ready for review; runs nothing) |
| `byteplan tests scaffold ID [--path] [--name] [--policy] [--link] [--force-new] [--dry-run]` | write a deliberately failing acceptance test for a task and link it |
| `byteplan tests list [ID]` | linked acceptance tests and where each link comes from |
| `byteplan tests add ID NODE...` / `tests remove ID NODE...` | link or unlink pytest node IDs by hand |
| `byteplan sync [--apply] [--only ID]` | decorator mode: rewrite attached comments and unowned stubs to `@todo(...)` (preview by default) |
| `byteplan sync --remove-resolved [--apply] [--only ID] [--suppress-stubs]` | remove the source annotations of resolved and dismissed tasks |
| `byteplan release [--version V] [--dry-run] [--allow-dirty] [--smoke-test [--offline]]` | strip `@todo`/`@verifies` and runtime imports in place for a release, recording each one (no git or build) |
| `byteplan restore [--dry-run] [--partial]` | put back what `release` stripped (byte-identical when the files haven't changed) |
| `byteplan resolve ID --sync-source` | resolve, and remove the task's annotation in the same step |
| `byteplan scan [PATHS] [--dry-run] [--staged]` | discover, add IDs, reconcile, report. With paths, the scan is narrowed and never marks anything missing. `--staged --dry-run` previews against the Git index |
| `byteplan scan --staged --apply` | add IDs to the staged commit (index and working tree) before it's finalized; what the pre-commit hook runs |
| `byteplan migrate [--dry-run]` | explicitly upgrade registry metadata through the recovery journal without editing source; required before expanded-ID allocation in older repositories |
| `byteplan check [--staged \| --commit REV]` | read-only validation, with policy-based exit code. `--staged` checks exactly what's staged (pre-commit); `--commit HEAD` checks a commit (CI) |
| `byteplan list [--status S] [--presence P] [--kind K]` | list tasks |
| `byteplan show ID` | details, location and history (archived tasks too) |
| `byteplan list --archived [--kind K]` | list archived tasks |
| `byteplan archive [--dry-run] [--older-than DAYS]` | move long-closed tasks whose annotation is gone into the archive (scans do this automatically) |
| `byteplan archive --reconcile` / `archive --restore ID` | fill the local archive store from Git history / put an archived task back in the registry |
| `byteplan status ID STATUS [--note]` | change lifecycle status |
| `byteplan resolve ID [--note]` | mark resolved (never edits source) |
| `byteplan edit ID [--priority] [--assignee/--unassign] [--label] [--remove-label] [--notes/--add-note] [--title/--clear-title]` | managed fields; scans never overwrite them |
| `byteplan missing` | active tasks no longer found in source (`--include-closed` adds resolved and dismissed ones) |
| `byteplan duplicates` | the same ID on more than one annotation |
| `byteplan report [--format text\|json\|markdown]` | summary by status, presence, kind and priority, plus findings |
| `byteplan repair --import ID` | register an unregistered source ID; archived IDs require `archive --restore ID` |
| `byteplan repair --reassign PATH:LINE` | give a duplicated ID's copy a fresh ID; use `--dry-run` to preview |
| `byteplan repair --reassign PATH:LINE --against REV` | preserve/reassign an independently created branch collision before merging; [procedure and limits](docs/rc1-compatibility.md#merge-and-collision-recovery) |
| `byteplan git install-merge-driver` | merge the registry by task ID in Git merges (per clone) |
| `byteplan git install-hooks [--mode reconcile\|check\|scan]` | direct pre-commit hook (default `reconcile`: IDs at commit time); never replaces a hook it didn't write |
| `byteplan git hooks-status` | show the pre-commit framework hook, direct hook and merge driver |
| `byteplan merge-registry BASE OURS THEIRS [PATH]` | the merge driver itself; Git runs it, you don't |
| `byteplan mcp [--allow-registry-write] [--allow-source-write] [--allow-test-execution]` | serve the registry to AI agents over MCP (stdio); needs `byteplan[mcp]` |
| `byteplan merge-archive BASE OURS THEIRS [PATH]` | the archive index's merge driver (three-way per task ID); Git runs it |

Narrowed paths limit reconciliation and source edits. When allocating a new ID, BytePlan still
reserves identities across the full configured source scope, including the selected Git view.
An unreadable, unparseable or malformed in-scope file therefore blocks allocation even outside
the narrowed paths. Files deliberately excluded from source scope are not allocation inputs.

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
include = ["**/*.py"]         # add "**/*.md", "**/*.json", ... to track those too
exclude = ["**/.venv/**", "**/venv/**", "**/__pycache__/**", "**/build/**", "**/dist/**",
           "**/.tox/**", "**/.nox/**", "**/node_modules/**", "**/*.pyi"]
respect_gitignore = true
auto_annotate = true          # false: only track comments that already carry an ID
missing_policy = "warn"       # or "ignore"
report_file = ""              # e.g. "byteplan.md": a committed Markdown view of the registry
report_branch = ""            # e.g. "main": only that branch writes and checks report_file

[tool.byteplan.detect]
todo_tags = ["TODO", "FIXME", "HACK", "XXX"]
pass_stubs = true
ellipsis_stubs = true
not_implemented_stubs = true
empty_classes = true
placeholder_assignments = false  # module-level `X = ...` stubs: not supported yet (true is an error)
respect_overrides = true       # interface methods and no-op overrides aren't stubs (see below)
json_string_values = true      # JSON strings starting with "TODO:" are tasks

[tool.byteplan.check]
fail_on_duplicate_ids = true
fail_on_missing = false
fail_on_stale_annotations = false
require_reconciled = false    # plain `check` applies the snapshot rules too (as --staged/--commit do)
fail_on_position_drift = false  # registry lines lagging behind source fail instead of an info note
fail_on_stale_report = false  # report_file not matching the registry is a warning by default

[tool.byteplan.git]
on_reconcile = "commit"            # or "stop": the commit hook reconciles, then exits 1 for review

[tool.byteplan.tests]
pytest_marker = false              # also link tests marked @pytest.mark.byteplan("id")
runner = []                        # verify's pytest command; [] = this Python's -m pytest
timeout = 300                      # seconds before a verify run is killed
stale_on = "files"                 # or "head": any HEAD change or dirty tree makes results stale

[tool.byteplan.tests.scaffold]
directory = "tests"
filename = "test_{module}.py"      # mirror = true puts src/pkg/x.py's test in tests/pkg/
mirror = false
link_style = "verifies"            # or "marker" (needs pytest_marker) / "managed"
policy = "fail"                    # or "xfail" / "skip"; neither counts as evidence
async_tests = ""                   # "pytest-asyncio" or "anyio" to scaffold async tests
auto = false                       # a writing scan scaffolds tests for the Python tasks it adds

[tool.byteplan.annotations]
mode = "comment"                   # or "preserve" / "decorator" (see `byteplan sync`)
convert_attached_comments = false  # decorator mode: sync turns attached comments into @todo
auto_decorate_stubs = false        # decorator mode: sync puts @todo on unowned stubs
remove_resolved = false            # sync also removes closed tasks' annotations
runtime_modules = ["byteplan_runtime"]   # add a project shim module here

[tool.byteplan.archive]
after_days = 7                     # archive tasks closed at least this many days ago
auto = true                        # every writing `scan` archives what's eligible

[tool.byteplan.release]            # `release --smoke-test` (see "Releasing without the runtime")
smoke_build = []                   # wheel build command; "{out}" is the output dir; [] = python -m build
smoke_imports = []                 # modules to import from the installed wheel; [] = all top-level ones
smoke_timeout = 300                # seconds for each smoke-test step
find_links = []                    # extra package sources for --offline installs (pip --find-links)
```

- **Paths and patterns:** paths are relative to the project root (the directory with
  `pyproject.toml`), not your current directory. Patterns use `.gitignore` syntax.
- **Strictness:** unknown keys are errors, so typos don't silently do nothing.

## 1.0 compatibility boundary

The [1.0 compatibility policy](docs/compatibility-policy.md) covers task identities and registry
semantics, source safety, the documented CLI and Python API, configuration, runtime decorators,
MCP tools and Hatch/Git integrations. Advanced shipped commands share these guarantees.
Python MCP embedding is explicitly experimental; the documented stdio protocol is included in
the stable boundary. Assignments and semantic graph operations remain future architecture.
This is the intended 1.0 contract; RC1 still requires its documented validation and approval.

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
require_stripped = false  # fail wheel/sdist builds while @todo/@verifies are still present
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

## Releasing without the runtime

`@todo` and `@verifies` are inert, but they still import `byteplan_runtime`. `byteplan release`
removes them, and the runtime imports they leave unused, so the code you release doesn't depend
on BytePlan at all. Tagged `# TODO[id]` comments stay, since they cost nothing at runtime.

```console
$ git switch -c release/1.2.0            # from a clean main
$ byteplan release                       # strip in place; the registry records every line
byteplan: stripped 14 decorator(s) and 5 import(s) from 9 file(s) for release 1.2.0
$ git commit -am "Release 1.2.0" && git tag v1.2.0 && hatch build
$ git switch main                        # main never had the strip
```

- **What stays the same:** no task changes status, and stripped tasks are on record
  (`presence: stripped`), never `missing`. Their test links are frozen until restore.
- **What it never does:** commit, tag, build or reset.
- **Restore:** `byteplan restore` puts everything back, byte for byte when the files haven't
  changed since the strip. After a hotfix, each decorator is placed through the AST by its
  function's name. A function that's gone is a `restore_conflict`, and `--partial` keeps the
  unplaced entries on record.
- **Refusals:** it refuses, writing nothing, on a dirty tree (`--allow-dirty`), an untagged
  `@todo`, a decorator sharing a line, a runtime that's still used outside decorators, or an
  already-stripped tree.
- **While stripped:** `sync`, scaffolding and cleanup refuse, and Hatch builds only check. On
  your default branch, `release` warns: release from a short-lived branch instead.
- **`--smoke-test`** (opt-in, since it builds and imports your code):
  - It builds a wheel from the stripped tree into a temporary directory and installs it in
    isolation.
  - It checks that `byteplan_runtime` isn't importable, and imports every top-level module.
  - If that fails, the strip is restored automatically and the traceback is shown.
  - Configure it in `[tool.byteplan.release]` (`smoke_build`, `smoke_imports`,
    `smoke_timeout`, `find_links` for `--offline`).
- **Warnings:** `runtime_dependency_in_release` (`byteplan-runtime` is still a project
  dependency) and `unfinished_scaffold_in_sdist` (a failing placeholder test would ship).
- **Guard:** `[tool.hatch.build.hooks.byteplan] require_stripped = true` fails wheel and sdist
  builds while decorators are still present.

## A committed task list: `report_file`

Set `report_file = "byteplan.md"` and BytePlan keeps a readable task list next to your code,
with open work first and each location linked to the file and line. It's what reviewers and
GitHub visitors see without installing anything.

- **Always current:** it's rendered from the registry alone, and every command that writes the
  registry (`scan`, `resolve`, `status`, `edit`, `repair`) rewrites it. The commit hook
  (`scan --staged --apply`) stages it with the registry, so each commit carries a matching copy.
- **Checked:** `check --staged`, `check --commit` and `require_reconciled` report
  `report_out_of_sync` when it doesn't match the registry. That's a warning unless
  `fail_on_stale_report = true`.
- **Merges:** two branches both regenerate it, so a text merge would only conflict.
  `byteplan git install-merge-driver` also registers `byteplan.md merge=byteplan-report`, which
  keeps our copy. The next hooked commit, or `byteplan scan`, regenerates it from the merged
  registry; until then `check` warns that it's stale.
- **Pull requests:** GitHub doesn't run merge drivers, so two PRs that both change tasks
  conflict on the report there. Set `report_branch = "main"` and only `main` writes or checks
  it: other branches (and the detached checkouts CI uses for PRs) leave the committed copy
  alone. After a merge, `byteplan report --write` regenerates it on any branch, so a CI job on
  `main` can catch it up (see [docs/ci.md](docs/ci.md#keeping-the-report-current-on-main)).
- **Generated, not scanned:** the report file is never scanned for TODOs. Don't edit it by hand.

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

The installer also sets up `byteplan-archive` for `.byteplan/archive.json`. It merges each task's
entry three-way against the common ancestor, by record hash: entries added, changed (a task
restored and archived again) or removed on one side carry over. If both sides changed the same
entry differently, you get Git's conflict markers and an explanation.

**Per clone, and safe to skip.** Commit `.byteplan/.gitattributes` (and, with a `report_file`, the
`.gitattributes` next to it). Each clone runs
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

## MCP server for AI agents

`byteplan mcp` serves the registry to AI agents and editors over the
[Model Context Protocol](https://modelcontextprotocol.io) (stdio). Agents get the same tasks,
IDs, diagnostics and JSON as the CLI, and every write goes through the same lock and journal.

```console
$ pip install 'byteplan[mcp]'      # the official MCP SDK, 2.x
$ byteplan mcp                     # read-only; or the `byteplan-mcp` script
```

**Claude Code:**

```console
$ claude mcp add byteplan -- byteplan mcp --allow-registry-write
```

**Claude Desktop, Cursor and other `mcpServers` configs** (Claude Code's project `.mcp.json`
too):

```json
{
  "mcpServers": {
    "byteplan": {"command": "byteplan", "args": ["mcp", "--project", "/path/to/project"]}
  }
}
```

**VS Code** (`.vscode/mcp.json`):

```json
{
  "servers": {
    "byteplan": {"type": "stdio", "command": "byteplan", "args": ["mcp", "--project", "${workspaceFolder}"]}
  }
}
```

**Read-only by default.** Three separate permissions add tools; without its permission a tool
isn't offered at all:

| Permission | Adds |
|---|---|
| (none) | `list_tasks`, `show_task`, `scan` (preview), `check`, `missing`, `duplicates`, `report`, `get_task_tests`, `get_verification` (recorded; runs nothing), `list_ready_tasks`, `sync_source` (preview), `preview_test_scaffold`; resources `byteplan://tasks` and `byteplan://tasks/{id}`; a `triage` prompt |
| `--allow-registry-write` | `set_status`, `resolve`, `edit_task`, `add_task_test`, `remove_task_test` |
| `--allow-source-write` | `scaffold_test`, `release`, `restore`, and `apply=true` on `scan`, `sync_source` and `resolve(sync_source=true)` (which otherwise previews) |
| `--allow-test-execution` | `verify_task`, and `release(smoke_test=true)` (both run project code) |

- **Source writes are always explicit:** even with permission, a tool that edits source only
  previews unless it's called with `apply=true`.
- **Nothing runs tests on the side:** listing, searching and scanning never execute project code.
- **Compact by default:** `scan` returns counts and what changed (`detail=true` lists every
  annotation), `missing` lists only active tasks (`include_closed=true` adds closed ones), and
  `preview_test_scaffold` and `scaffold_test` return the new test and its imports (`full=true` adds
  the whole file).
- **Errors:** findings come back as `diagnostics`. A call fails only where the CLI would exit 2,
  for example `locked:` while another BytePlan process is writing.
- **stdout** carries JSON-RPC only; anything else goes to stderr.

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
- **Interrupted writes finish safely:** the next authorized write command completes them once
  the project lock is available. If a file was
  changed by something else in the meantime, BytePlan stops instead of overwriting it.
- **Failures stop the scan cleanly:** a file that can't be read or parsed, or a directory that can't
  be listed, fails the whole scan before anything is reconciled.

**Tradeoffs worth knowing.**
- **No cross-file atomicity.** Filesystems have no multi-file atomic rename. The journal guarantees
  completion (roll-forward), not that all files change at the same instant.
- **A small race window remains.** Each file's content is re-checked immediately before it's
  replaced, but nothing portable can close the gap between that check and the rename.
- **Existing project locks require deliberate cleanup.** BytePlan never automatically removes
  `.byteplan/scan.lock`, even if its recorded process appears dead: another writer could have
  replaced that lock during inspection. Stop all CLI, hook, MCP and build writers and confirm
  none is running before deleting only the stale lock file and retrying the intended write.
  Preserve `.byteplan/txn/` and its journal/copies so recovery can finish interrupted work.
- **Symlinks are never followed.** That prevents scanning a file twice or reaching outside the
  project.
- **Only `.gitignore` files are honoured.** `.git/info/exclude` and global Git excludes aren't read.
- **Stub detection is a heuristic.** It reports candidates; `# byteplan: ignore` and the
  `[tool.byteplan.detect]` switches are there for intentional no-ops.
- **Observed duplicate IDs block scan writes** until you resolve them. Full scans and narrowed
  allocation inspect the configured identity namespace. A narrowed scan without allocation
  checks selected identities against their prior canonical source before moving a task; it
  tolerates unrelated parse errors and does not prove whole-project uniqueness. Run a full
  `byteplan check` to validate the entire configured scope.

## License

`byteplan` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
