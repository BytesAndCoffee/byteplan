# BytePlan — Addendum B: Test Scaffolding, Release Stripping, and the Development-Intent Workflow

**Audience:** Claude Code implementing `BytesAndCoffee/byteplan`  
**Status:** Proposed additive requirements  
**Builds on:** `docs/spec.md`, `docs/IMPLEMENTATION_PLAN.md`, and **Addendum A** (symbol-bound TODOs, decorators, verification)  
**Tagline:** *Plan in code. Track in one place.*

> This document records features discussed **after Addendum A**. It is not a replacement for prior specifications. Keep their permanent four-hex-character task IDs, project-scoped uniqueness, source/registry ownership boundaries, conservative missing detection, transaction journaling, optional Hatch and MCP integration, and explicit human/authorized-agent resolution. The release/restore design has already been incorporated into `docs/IMPLEMENTATION_PLAN.md`; reconcile with that existing design rather than adding a second conflicting implementation.

## B1. Product-level objective

BytePlan should connect the development lifecycle end-to-end:

`# TODO / unfinished stub → stable task ID → symbol attachment → shared backlog → scaffolded failing test → implementation → current-revision verification → review → resolution → annotation cleanup`

This is **not a new mandated `*DD` methodology**. It is source-native infrastructure that supports established practices—TDD, ATDD, BDD-style acceptance descriptions, Agile backlogs, and AI-agent task execution—through a common task identity and data model. Do **not** claim the tool performs Domain-Driven Design by attaching tasks to classes. Features must remain independently adoptable: comments-only usage is fully valid, tests are optional, and AI/MCP integration is optional.

## B2. Test scaffolding: new first-class command

A developer or authorized agent should be able to request a new **deliberately failing** acceptance-test skeleton for an existing task:

```console
byteplan tests scaffold a83f
byteplan tests scaffold a83f --dry-run
byteplan tests scaffold a83f --path tests/test_routing.py
byteplan tests scaffold a83f --name test_advertise_routes_poisoned_reverse
```

Task context available from the existing registry and AST scan includes ID, title, original description, source path, symbol qualified name, kind (`class`, `function`, `method`, `async function`, etc.), source signature, attached acceptance criteria if present, and existing test links.

**Example source:**

```python
@todo("Implement poisoned reverse", id="a83f")
def advertise_routes(self):
    raise NotImplementedError
```

**Generated pytest skeleton (illustrative):**

```python
import pytest
from byteplan_runtime import verifies

@verifies("a83f")
def test_advertise_routes_poisoned_reverse():
    """Acceptance test scaffold for BytePlan task a83f.

    Target: Router.advertise_routes
    Requirement: Implement poisoned reverse
    """
    # GIVEN: TODO — arrange the routing state
    # WHEN: TODO — call the target behavior
    # THEN: TODO — assert the required result
    pytest.fail("BytePlan a83f: acceptance test not implemented")
```

**Critical invariant:** never generate a passing placeholder test (`pass`, `...`, a bare docstring, or only `assert True`). Scaffolds must **fail** when selected and run, unless an explicitly requested alternative policy produces `pytest.xfail`/`pytest.skip`; neither of those states qualifies as passing acceptance evidence. `pytest.fail()` is the default. A generated test does not claim the requirement was validated.

### B2.1 Target location and naming

- Use a deterministic discovery convention such as `src/pkg/routing.py` → `tests/test_routing.py`, configurable via `[tool.byteplan.tests.scaffold]`.
- If the conventional test file exists, propose appending a function safely. Otherwise propose creating it. Never overwrite existing tests or clobber developer edits.
- Derive the initial name from the attached symbol plus a stable task-specific suffix if necessary; ensure syntactically valid unique pytest test names. Prefer a readable name, and include the task ID if needed for disambiguation.
- Inspect existing source/test mappings and registry links first. If the task already has a scaffold or suitable linked test, report that and perform no edit by default. Provide an explicit `--force-new` for an additional distinct test, which must still avoid collisions.
- For class-bound tasks, scaffold a class-level behavior test; do not assume a constructor signature can be safely instantiated. For instance methods, do not manufacture fixtures. Use explanatory placeholders and fail deliberately.
- For async targets, use the project's configured async test framework (e.g. `pytest-asyncio` when available) or conservatively generate a synchronous failing scaffold. Never generate async tests that pytest silently skips due to absent plugin configuration.
- For properties and special methods, generate a generic failing test with a qualified-symbol comment; don't execute unknown code or fabricate meaningful assertions.
- For TODOs not tied to a symbol, generate a generic, clearly named task-ID-bound acceptance-test scaffold.
- Do not write domain-specific GIVEN/WHEN/THEN assertions based solely on a vague TODO. Template comments are fine; an AI agent may separately propose concrete test behavior, subject to normal review.

### B2.2 Provenance and idempotence

- Generated tests use the already specified `@verifies("a83f")` or a supported pytest marker; choose based on configured test-link style. The default must be statically discoverable by BytePlan.
- Record `origin: "scaffold"` (or equivalent test-link provenance), generation timestamp/event, path, pytest node ID once discoverable, and task ID.
- Scaffolding the same task repeatedly with unchanged inputs makes **no new file, duplicate function, duplicate link, or registry timestamp churn**.
- Respect standard release-stripping behavior for runtime decorators and imports, including test code if test files are in the release scope; normal scans must preserve test associations after stripping.
- Store no generated test code in registry metadata as the authoritative copy: source is authoritative for test implementations.

## B3. Separate acceptance criteria from generated assertions

Allow an optional structured set of **human/agent-written acceptance criteria** associated with a task, without requiring Gherkin or BDD syntax. For example:

```json
{
  "id": "a83f",
  "acceptance_criteria": [
    {
      "id": "ac1",
      "text": "A route learned from R2 is advertised to R2 with metric 16",
      "verification": ["tests/test_routing.py::test_poisoned_reverse"]
    }
  ]
}
```

This is an illustrative task fragment, **not a schema replacement**. Acceptance criteria are registry-managed planning metadata; links to executable tests are verification metadata. Unverified criteria must not be marked satisfied merely because a different test passed. The minimum implementation may store criteria as simple text entries and defer one-to-many criterion/test mapping to an optional later phase. Preserve managed criteria through scans and source refactoring.

Enable optional CLI/API operations for adding, listing, editing, and removing criteria; don't force this into the MVP if it delays scanner correctness. Scaffolded GIVEN/WHEN/THEN comments can reference these criteria as human-readable hints, not as synthesized executable assertions.

## B4. Verification and resolution are deliberately distinct

Extend Addendum A's test-verification contract:

1. **Discovered**: task exists, with stable ID and source/symbol reference when available.
2. **Planned**: managed priority, owner, labels, notes, optional dependencies/criteria.
3. **Test scaffolded**: failing placeholder exists and is attached; this is **not** evidence of implementation correctness.
4. **Implemented**: stub detector no longer recognizes a stub, where applicable. This is only a heuristic.
5. **Verified**: every required linked test genuinely passed against an adequately identified current revision, with no scaffold placeholder remaining.
6. **Ready for review**: computed recommendation when evidence supports it; not a stored completion state.
7. **Resolved**: explicit registry lifecycle transition made by a developer or appropriately authorized agent; optional source cleanup follows explicit sync policy.

**Never auto-resolve** merely because the TODO was removed, a method acquired a body, a single test turned green, or a release stripped its decorators. Do not count generated placeholder tests as proof of completion. A test may be passing because it was accidentally weakened; BytePlan reports verifiable facts rather than asserting logical proof of correctness.

CLI additions beyond Addendum A:

```console
byteplan tests scaffold ID [--path FILE] [--name NAME] [--dry-run]
byteplan tests list ID
byteplan verify ID
byteplan verify --ready
```

For MCP, expose a read-only scaffold **preview** tool and a separately permission-gated `scaffold_test(id, path?, name?, apply=false)` write tool, using exactly the same planner, journal, validation, and locking as CLI operations. Test execution remains independently permission-gated, even if an agent is authorized to edit task metadata.

## B5. Release/restore: confirm the already agreed Phase 8 design

`byteplan release` prepares a **temporarily decorator-free working tree**, not a completed backlog. `byteplan restore` reconstructs BytePlan's development-time annotations. This requirement is already documented as Phase 8 in `docs/IMPLEMENTATION_PLAN.md`; **do not overwrite that plan or build a second release path**.

**Decisions already made:**

- The output is **in-place stripping followed by a separate restore**, not a temporary copy.
- Strip recognized `@todo(...)` and `@verifies(...)` decorators, and imports of configured runtime modules only when demonstrably unused after removal. Do **not** strip ordinary `# TODO[abcd]` comments or arbitrary unrelated decorators/code.
- Registry survives stripping; tasks may have `presence = "stripped"` with remembered source path, symbol, position and original decorator text; **lifecycle status is unchanged**. Stripped annotations are not missing TODOs.
- Record release version, timestamp, stripped-file hashes, exact annotation/import records, and release history.
- Block a release on incomplete scanning, missing IDs, conflicts, a pending journal, or an already-stripped tree; default to requiring a clean Git tree, with explicit `--allow-dirty` override.
- Use the existing durable journal for all-or-nothing writes and crash recovery, and validate the stripped AST. Ensure no unresolved runtime-module imports/references remain in distributable code.
- Restoration returns unchanged files **byte-for-byte**. If developers edit stripped files, use qualified-symbol/AST anchors and verified hashes for a conservative restore; conflicts must preserve every recovery record, with explicit opt-in partial restore.
- Hatch builds remain read-only unless expressly opted in. Support an opt-in `require_stripped` release guard to refuse an unstripped package build. `byteplan-runtime` should be a *development* dependency where this workflow is used, not an accidental production dependency.
- Expose release/restore in MCP **only under source-write authorization with explicit `apply=true`**. A normal agent query must never strip sources.

### B5.1 Important release semantics to clarify in implementation

The committed release state and the restored development state are different Git tree snapshots. Document an explicit supported Git workflow (e.g. a release branch/tag and restored development branch) and its registry-history implications. Avoid claiming `release` leaves a clean Git working tree: by design it temporarily changes tracked files. Releasing from a branch and restoring later may produce expected Git diffs; report them rather than silently committing or resetting users' repositories. Do not automatically run `git commit`, `git tag`, or publish distributions.

`byteplan release` should prepare the tree; **it must not implicitly mark tasks resolved or execute build/test/publish steps** unless a separate explicit command wrapper is designed and documented. The registry's release flag is a description of intentional source transformation, not verification evidence. In addition to static checks, offer an opt-in isolated-built-wheel smoke test without `byteplan-runtime` installed.

### B5.2 Tests and scaffolds during a release

- If a scaffold test is included in a release sdist, its `@verifies` decorator may be stripped, but the intentional `pytest.fail()` stays: **a failing unfinished acceptance test is not silently turned into a pass**.
- Make test packaging independent of task management: distinguish wheel vs sdist inclusion according to the project's packaging configuration. Warn if unfinished test scaffolds would cause a consumer's release test suite to fail.
- The registry remembers association links even when source decorators are temporarily stripped, per the Phase 8 frozen-field rule.

## B6. A shared development-intent graph, without methodology lock-in

Treat the registry as a set of **typed relationships** rather than an isolated flat list, while keeping a simple JSON format and avoiding a mandatory graph database:

- task → source symbol(s) or code location(s)
- task → acceptance criteria (optional)
- task ↔ test(s), including their provenance and verification evidence
- task → dependencies/blocks (optional planning metadata)
- task → owner/priority/status/history
- task → release-stripped record(s), when relevant

Keep the existing one-primary-source attachment for the initial implementation if needed; richer multiple-symbol associations can be a later backward-compatible extension. Do not require tickets, sprint ceremonies, GitHub Issues, external accounts, or BDD feature files. If later synchronizing with external issue trackers, **task IDs remain the canonical project-local identity** and remote IDs are metadata.

The human and AI agent should see the same registry-derived truth through CLI, JSON reports, and MCP. The tool can suggest work; it should not imply automatic agent assignment, background execution, or autonomous acceptance unless those capabilities are actually implemented with explicit permissions.

## B7. Security, correctness, and source-edit invariants

- **Zero false-green test scaffolds.** A generated test must fail or be explicitly nonpassing, never silently pass.
- **One obligation, one permanent ID.** No duplicate TODO when a manual annotation already owns a stub; no repeated scaffold when one already exists.
- **Static discovery first.** Scanning/scaffolding must not import, instantiate, or execute arbitrary target source. Running pytest is a separate, explicit operation.
- **No speculative fixtures/assertions.** Stub templates reflect known signatures and context without inventing behavior.
- **No destructive rewrite.** Stage proposed source changes, check before-content hashes, preserve encoding and formatting, reparse, write via the existing transaction journal, and recover safely after crashes.
- **Stable registry metadata.** Never overwrite human-owned notes, priority, owner, criteria, managed test links, or task status based on a scan.
- **Release stripping is not completion.** Distinguish `missing`, `stripped`, `resolved`, and `verified` precisely.
- **No test execution in ordinary `scan`, `hatch build`, or `release`.** Test execution requires a dedicated authorized invocation.
- **No new core runtime dependency.** Decorator usage is opt-in and can be fully stripped from production source.

## B8. Acceptance tests for Addendum B

Implement tests alongside the appropriate phases:

1. `tests scaffold ID` creates one discoverable pytest test with an unconditional `pytest.fail` and a correct task binding.
2. Running that untouched scaffold produces an actual pytest **failure**, never a pass/skip/xfail falsely labeled success.
3. Re-running scaffold is idempotent and reports the existing test instead of duplicating it.
4. Existing test files and tests are preserved; no function-name collisions or import duplication.
5. Sync/async/class/instance-method/property/module TODO cases generate safe templates without inventing fixtures or behavior.
6. With no async pytest plugin, async target scaffolding cannot silently produce a skipped acceptance test.
7. A source move or line shift does not alter a task ID or cause a duplicate test association.
8. A scaffolded test's `@verifies` link is discoverable by the static scanner and reconciles with the registry.
9. A generated scaffold is not eligible for `ready_for_review` until it is genuinely implemented and passes on current code.
10. Test collection failure, missing test, failing assertions, skipped and xfailed tests do not count as passing evidence.
11. The CLI/MCP dry-run/preview makes no file or registry changes; MCP source writes require explicit permission and `apply=true`.
12. Scaffolding interrupted between test file and registry write fully recovers via the journal.
13. Release strips its recognized `@todo`/`@verifies` decorators and now-unused runtime imports but retains comments, tests, registry, and task statuses.
14. Restoring an unchanged stripped tree returns original files byte-for-byte; a changed file restores conservatively or refuses without losing recovery data.
15. During release stripping, previously linked tests and discovered task metadata remain available and are not reported as missing.
16. An unfinished generated test included in an sdist stays failing after decorator stripping; it is never altered into `pass`.
17. No production wheel contains a byteplan runtime dependency solely due to annotations when release stripping and guard are enabled.
18. `release --dry-run`, `restore --dry-run`, readonly Hatch builds, and readonly MCP are side-effect-free.
19. Existing Addendum A and original-spec test suites remain green.

## B9. Roadmap insertion and instructions to Claude

**Do not renumber or discard existing implemented phases unnecessarily.** Update `docs/IMPLEMENTATION_PLAN.md` with a new **Test Scaffolding** subphase adjacent to acceptance-test integration (currently Phase 6), after task/test association and before richer agent-assisted generation. Keep existing Phase 8 **Release** and Phase 9 **MCP** requirements intact. If these additions are not yet implemented, label them planned rather than claiming they work.

Suggested order:

1. Static scaffold planner (pure): choose test path/name, create deliberately failing template, detect conflicts and existing tests.
2. Journaled test-file creation and test-link reconciliation with idempotence tests.
3. CLI `byteplan tests scaffold`, dry-run and configuration for naming/location/async behavior.
4. MCP preview and source-write-gated scaffold endpoint.
5. Optional acceptance-criteria data model and criterion-to-test mapping; do not hold core scaffolding hostage to this enhancement.
6. Extend release integration tests for generated acceptance tests and check the existing release/restore contract.
7. Document an end-to-end developer journey: `# TODO` → `scan` → `tests scaffold` → implementation → `verify` → explicit `resolve` → authorized `sync`, including when BytePlan notices but never automatically closes work.

### Mandate

Implement the smallest reliable version of this workflow first. Update specifications coherently, verify the actual CLI/MCP/Hatch and pytest APIs against the installed toolchain, add tests for every source-mutating pathway, and leave ambiguous operations as diagnostics rather than guesses. **The novelty is the common, persistent development obligation—do not compromise its identity or safety for a flashy automated demonstration.**
