# BytePlan — Claude Code Specification Addendum A

**Subject:** Symbol-bound TODO declarations, automatic stub decoration, test attachments, and bidirectional source synchronization  
**Applies to:** `docs/spec.md` and `docs/IMPLEMENTATION_PLAN.md` in `BytesAndCoffee/byteplan`  
**Status:** Proposed additive requirements; do not discard the original specification  
**Python:** 3.11+  
**Tagline:** *Plan in code. Track in one place.*

**Compatibility update:** The four-character allocation assumptions in this historical addendum
are superseded by [Addendum E](spec-addendum-e.md#track-a--pre-10-compatibility-and-reliability)
and the [1.0 compatibility policy](compatibility-policy.md). Legacy identities remain valid;
new allocation uses six characters, with supported longer identities and explicit migration.

## 1. Purpose and compatibility

Extend BytePlan from source-comment discovery into a source-aware development task registry with three equivalent ways to originate a task: an ordinary TODO/FIXME/HACK/XXX comment, an explicit decorator on a function/method/class, and automatic discovery of AST stubs. All representations reconcile to the same central registry and stable four-character hexadecimal ID. Add test linkage and verification evidence so developers, teammates, and AI agents can determine whether work is ready for resolution.

Keep existing contracts: SHAKE128 two-byte candidate IDs (`[0-9a-f]{4}`), collision retry, permanent reservation of all issued IDs, immutable IDs embedded in source, separate task lifecycle and source presence, deterministic/idempotent scanning, conservative missing detection, transaction journaling, read-only-by-default Hatch integration, and permission-gated MCP writes. New behavior is opt-in where it can change runtime dependencies or delete annotations. Do not silently resolve tasks.

## 2. Native Python task declaration

Recognize these declarations without importing or executing application modules:

```python
from byteplan_runtime import todo

@todo("Implement route poisoning")
def advertise_routes(self):
    raise NotImplementedError

@todo("Implement route poisoning", id="a83f")
def advertise_routes(self):
    raise NotImplementedError

@todo(
    "Implement route poisoning",
    id="a83f",
    tests=("tests/test_routing.py::test_route_poisoning",),
)
def advertise_routes(self):
    raise NotImplementedError
```

Support `def`, `async def`, `class`, and multiple independent tasks on one declaration. Allow `test="..."` as shorthand for `tests=("...",)`; reject simultaneous `test` and `tests`. Support static literal arguments only; report dynamic expressions rather than evaluating them. Resolve explicitly known imports/aliases conservatively; do not assume unrelated functions named `todo` belong to BytePlan.

The first successful authorized write allocates and embeds the ID as a decorator keyword argument. Preserve the ID thereafter regardless of line movements, symbol rename, file move, or description changes. Track source path, fully qualified symbol, annotation location, declaration location, attachment kind, and representation separately. ID is the only authoritative identity key.

### Runtime semantics

A decorator necessarily runs at Python import time. It must be **no-op/inert**: return the identical object; never wrap or register it, mutate it, run tests, access files, or contact services. Avoid imposing the full BytePlan devtools dependency on production code. Provide a tiny optional `byteplan-runtime` distribution or a documented project-local shim. Decide this packaging strategy before generating decorators automatically. Source discovery uses AST and tokenize; it never requires runtime import.

## 3. Comment-to-decorator conversion

Retain full support for the existing comment syntax:

```python
# TODO: Implement route poisoning
#   Support split horizon and poisoned reverse.
def advertise_routes(self):
    ...
```

When explicitly configured and structurally safe, BytePlan may normalize this to:

```python
@todo(
    "Implement route poisoning\nSupport split horizon and poisoned reverse.",
    id="a83f",
)
def advertise_routes(self):
    ...
```

Preserve the original tag kind (TODO/FIXME/HACK/XXX) in registry metadata and preserve the full comment description. Conversion requires unambiguous attachment to the next declaration at appropriate indentation. Do not convert module-wide comments, trailing inline TODOs, comments inside methods about individual statements, separated comments, ambiguous cases, or comments associated with multiple declarations. Issue a review diagnostic instead. Conversion may never drop a task, its description, or an existing ID.

Proposed configuration (adapt names as needed while documenting them):

```toml
[tool.byteplan.annotations]
mode = "comment"                  # comment (default) | decorator | preserve
convert_attached_comments = false
auto_decorate_stubs = false
remove_resolved = false
```

`comment` retains existing annotation behavior; `preserve` annotates each original representation without conversion; `decorator` enables safe normalization when the runtime import is explicitly available. An author-written decorator is always accepted regardless of selected mode. Never introduce a mandatory runtime import into an application unexpectedly. If automatic import insertion is unsafe or unconfigured, retain the comment and flag `conversion_needs_review`.

Use syntax-aware edits rather than whole-file regex replacement. Retain decorator order, indentation, shebang, encoding cookie, BOM, newlines (including CRLF), EOF newline state, comments, docstring and `__future__` positioning, and permissions. Reparse every proposed edit before writing. Do not modify an existing unrelated decorator stack in a way that changes behavior.

## 4. Automatic TODO decorators for detected stubs

Re-use existing AST stub heuristics: `pass`, `...`, `raise NotImplementedError`, empty classes and configured optional placeholders. Respect all exclusions for abstract methods, protocols, overloads, stubs/interfaces, `.pyi` files, and explicit ignore directives.

In opt-in decorator mode, an unowned stub:

```python
class Router:
    def advertise_routes(self):
        raise NotImplementedError
```

can become:

```python
from byteplan_runtime import todo

class Router:
    @todo("Implement Router.advertise_routes", id="a83f")
    def advertise_routes(self):
        raise NotImplementedError
```

If an eligible TODO comment or decorator already owns the stub, do **not** generate another task. Ambiguous/unsafe syntax produces a candidate diagnostic or uses the existing tagged comment mode. A later implementation change may emit `implementation_changed` or `implementation_complete_candidate`, but must not automatically resolve a task. A method may stop being a stub while still failing its actual acceptance requirements.

## 5. Acceptance tests attached to tasks

Allow zero-to-many test links per task and many-to-many task/test relationships. Accept links from:

1. `@todo(..., tests=("tests/test_routing.py::test_route_poisoning",))` or `test="..."`.
2. Registry-managed links from `byteplan tests add a83f NODE_ID` and `byteplan tests remove a83f NODE_ID`.
3. Test-side annotations:

```python
from byteplan_runtime import verifies

@verifies("a83f")
def test_route_poisoning():
    ...
```

An optional pytest plugin may alternatively register and interpret `@pytest.mark.byteplan("a83f")`. Without plugin registration, do not assume this marker has meaning. Test-side linkage can be statically discovered; it must not force test execution during scans. Merge and deduplicate discovered and manually managed links while preserving provenance. A source scan does not erase registry-managed associations. Invalid or unknown IDs get actionable diagnostics.

### Verification

Provide:

```shell
byteplan tests list a83f
byteplan tests add a83f tests/test_routing.py::test_route_poisoning
byteplan tests remove a83f tests/test_routing.py::test_route_poisoning
byteplan verify a83f
byteplan verify a83f --json
byteplan verify --ready
```

Start with pytest integration. Run only explicitly attached node IDs as a subprocess, using an argument vector (never shell string interpolation), project-root cwd, controlled timeout, and clear errors. Running tests executes project code and is a **privileged action**, especially for MCP: require explicit permission and user-requested invocation. Neither scans nor builds run acceptance tests by default.

Track distinct results: `passed`, `failed`, `skipped`, `xfailed`, `xpassed`, `error`, `not_found`, `not_run`, `timeout`, and `stale`. A skipped/xfail/missing/collection-error test is never proof of acceptance. Store bounded per-test summaries and verification metadata (runner, UTC time, relevant command/environment, Git HEAD and dirty-tree indicator or content fingerprint). Do not dump megabytes of logs into tasks.json. Results from older revisions or changed relevant files must be labeled stale; when confident revision tracking is not possible, report uncertainty conservatively.

Verification/readiness is **orthogonal** to lifecycle status. Compute `unverified`, `failing`, `needs_review`, or `ready_for_review` based on current valid evidence and stub signals; do not promote these to automatic `resolved` status. A passing test is evidence, not proof that all requirements were satisfied.

## 6. Registry-driven cleanup (bidirectional sync)

The central registry owns lifecycle state. Support authorized removal of **BytePlan-managed** source annotations when tasks are resolved or dismissed. Default commands must not quietly mutate source:

```shell
byteplan resolve a83f          # registry status update only
byteplan sync --dry-run         # show proposed normalization/cleanup
byteplan sync --apply           # explicit source writes
```

Optionally provide `byteplan resolve a83f --sync-source` as a clearly explicit, equivalent operation. MCP source editing remains opt-in and requires `apply=true`; ordinary Hatch builds remain read-only.

Cleanup must identify the exact tagged TODO block or `@todo(..., id="a83f")` corresponding to the resolved ID. Remove only the matching managed annotation, not adjacent comments, other decorators, unrelated tasks, imports still used elsewhere, code bodies, or tests. Keep the reserved ID, prior source reference, lifecycle history and completion metadata. A manual annotation disappearance produces `missing`, **not** `resolved`.

Important cycle guard: If a task is resolved but its declaration still meets stub heuristics, emit `resolved_but_stubbed` and **refuse automatic cleanup by default**. Otherwise the next scan would rediscover an unchanged stub and create a fresh task. An explicit developer override or persistent suppression may handle intentional no-op implementations. Do not silently suppress unresolved implementation obligations.

## 7. Registry schema extension

Add optional backwards-compatible fields or a documented schema-version migration. Conceptual fragment:

```json
{
  "id": "a83f",
  "origin": "stub",
  "status": "in_progress",
  "source": {
    "path": "src/bytesim/routing.py",
    "line": 19,
    "symbol": "Router.advertise_routes",
    "attachment_kind": "method",
    "representation": "decorator"
  },
  "tests": {
    "managed": [],
    "discovered": ["tests/test_routing.py::test_route_poisoning"],
    "verification": {"state": "not_run", "revision": null}
  }
}
```

This is a fragment, not a replacement for fields in the current schema. Preserve user-managed title override, status, priority, labels, assignee, notes, events and reserved IDs. Track annotation provenance so cleanup is restricted to safe edits. Normal scans must not churn verification timestamps or test results.

## 8. MCP / Hatch adapters

Extend the MCP server with equivalent read operations (`get_task_tests`, `get_verification`, `list_ready_tasks`) and explicit opt-in write/execute operations (`add_task_test`, `remove_task_test`, `verify_task`, `sync_source`). Distinguish registry-write permission, source-write permission, and test-execution permission. Do not execute tests as a side effect of listing, searching, or scanning. Use the existing `api.Project` facade, locking and journal path.

Hatch scans should discover decorators without importing modules, but ordinary builds must not insert imports, normalize syntax, strip annotations, or run tests. Preserve current opt-in local build-write policy and packaging/reproducibility safeguards. BytePlan must remain able to self-host with `hatch run byteplan scan` to avoid recursive build-system dependency.

## 9. Required acceptance tests

Add tests alongside all existing tests for:

1. Parsing decorators on sync/async functions, methods, classes and stacked decorators without importing modules.
2. First allocation of a four-hex ID to a decorator; subsequent byte-identical scans.
3. Conservative adjacent-comment conversion, including multiline descriptions and original tag kind.
4. Refusal to convert module-level, inline, body-local, ambiguously positioned or dynamic expressions.
5. Preserved method/class behavior and existing decorator application order; inert runtime returns the identical object.
6. Stub-to-decorator creation only when no annotation already owns the stub, respecting existing ignore/exclusion rules.
7. Implemented stub triggers advisory without silently resolving/removing a TODO.
8. CRLF, BOM, encoding cookies, unicode, shebang, `__future__`, decorator stacks and no-final-newline safety.
9. Source-declared and registry-managed test associations, multi-test and shared-test links, and provenance retention.
10. Test-side `@verifies`/registered pytest marker discovery, malformed IDs and unknown tasks.
11. Pytest pass/fail/skip/xfail/xpass/collection errors/timeouts/not-found results, with no false passes.
12. Revision-aware verification evidence and stale-result detection.
13. Explicit resolution without source mutation; authorized cleanup removes *only* the target annotation.
14. `resolved_but_stubbed` prevention of a rediscovery loop.
15. Manual annotation deletion marks missing, never resolved; history and ID reservation survive.
16. Dry-run and default Hatch/MCP flows do not mutate code or execute tests.
17. Crash during multi-file source edits recovers via the existing transaction journal.
18. Concurrent edits between scan and commit are detected and never overwritten.
19. Stable IDs across symbol rename/file move and mixed comment/decorator forms.
20. MCP permission-gating for source edits and test execution.

## 10. Implementation sequencing for Claude Code

1. **Model/discovery:** Extend AST scanner and registry for exact symbol-bound decorators, static arguments, provenance and test metadata; preserve existing semantics.
2. **Runtime design:** Decide on and provide minimal inert `todo`/`verifies` import strategy (or project shim) before automatic conversions.
3. **Normalization:** Add guarded comment-to-decorator and stub-to-decorator transformations through existing persistence/journal machinery.
4. **Acceptance tests:** Add test associations, pytest runner, verification evidence, CLI and MCP access.
5. **Cleanup:** Implement authorized registry-to-source synchronization and resolved-stub safeguards.
6. **Integration:** Update docs, migration, Hatch behavior, full end-to-end tests, and dogfood BytePlan on itself.

### Instructions to Claude

Read the repository's current `docs/spec.md` and `docs/IMPLEMENTATION_PLAN.md` first. Integrate this addendum additively into the roadmap, preserving completed work and established data guarantees. Implement incrementally with passing tests after each phase. Resolve design tradeoffs explicitly (especially inert-runtime distribution, stable CST edits, test provenance, and verification freshness), document them, and favor actionable diagnostics over destructive guesses. **Never equate disappearance of a comment, disappearance of a stub, or a passing test with automatic task completion.**
