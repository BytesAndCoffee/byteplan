# Addendum E — Repository-Wide Semantic Graph and Change-Impact Intelligence

**BytePlan — Final Pre-1.0 Hardening and Architecture Addendum E**

| Field | Contract |
|---|---|
| Repository | [BytesAndCoffee/byteplan](https://github.com/BytesAndCoffee/byteplan) |
| Hardening release target | `v1.0.0rc1`, followed by approval for 1.0 stable |
| Graph target releases | BytePlan 1.5 and 2.0 |
| Architecture status | Proposed future architecture |
| Graph implementation | Deferred until after 1.0 stable |
| Current release policy | Core feature freeze remains in effect |

The objective is to complete compatibility, maintainability and reliability work required for
RC1, document the semantic graph roadmap, and prepare independent whole-repository reviews.
This addendum extends the [implementation plan](IMPLEMENTATION_PLAN.md) and
[Assignment design](spec-addendum-d.md). It authorizes no semantic graph implementation during
1.0 hardening. Future graph relationships and operation names below are design candidates,
not public schema or API commitments.

## Operating instructions and verified starting point

Inspect the latest code, architecture documents, plan, registry, tests and open PRs before each
implementation track. Findings are review inputs: verify them, record already-resolved work,
and update the assessment when the base changes. Use BytePlan itself, stable allocated task
identities, supported annotations, verification evidence and explicit resolution. Implement no
new product functionality beyond pre-release compatibility, correctness, safety and
maintainability. Keep compatibility, structural refactoring and future architecture in separate PRs.

The documentation assessment used main commit
`e0b66318574ef72e23c80b529fb28a825b6d12ec`. These are observations at that revision,
not claims that the planned work has passed acceptance:

| Area | Verified observation | Disposition |
|---|---|---|
| Persistent IDs | `ids.py` validates exactly four lowercase hex characters and allocates `hexdigest(2)` candidates; `scanner/jsonc.py` also contains a four-character guard. Registry, scanner diagnostics and CLI text contain further assumptions. | A1 must audit the whole codebase. |
| Registry | `SCHEMA_VERSION = 1`; future versions are rejected before task decoding. Unknown top-level and task fields already round-trip. | Preserve existing protections; A2 must test actual released clients. |
| Recovery tooling | `repair --reassign PATH:LINE` already handles duplicate annotations. | Evaluate its adequacy for branch collisions; do not assume no repair mechanism exists. |
| Registry growth | `tasks.json`: 160,949 bytes, 72 tasks (54 resolved, 18 open), 367 history events. Compact JSON task records occupy 108,046 bytes; their compact history arrays occupy 47,975 bytes. | Measurements use compact serialization for both history and record comparison; size alone does not justify migration. |
| Merge support | Custom three-way merging, deterministic serialization, append-only history merging and explicit conflict fallback already exist, with merge/recovery tests. | A4 must establish the complete plain-Git and evidence matrix. |
| Source previews | `scan --dry-run`, `check`, sync preview, staged dry-run and read-only MCP defaults already exist; source-editing tests cover BOMs, newline styles and AST guards. | Audit gaps and explain existing workflows before adding commands. |
| API structure | `api.py`: 2,608 lines; `Project`: 1,865 lines and 67 methods, measured using AST source spans. | B is required before RC1. |
| Lint and CI | README already documents the TD004 ignore; CI defines Ubuntu/macOS/Windows on Python 3.11–3.14. | Configuration is not proof of final revision platform success. |
| Pending review fixes | [PR #43](https://github.com/BytesAndCoffee/byteplan/pull/43) contains the earlier review fixes; it was open during assessment. | Do not count unmerged fixes as integrated or allocate duplicate tasks. |

Earlier review identities remain authoritative: `8c7f`, `ff20`, `ecf4`, `5aae`, `ed2b`,
`98d6`, `1e7f`, `ac9d`, `ae7a`, `a740`, `30c3`. PR #43's additional P2 symlink-path
verification finding is tracked there as `ff72`. See that PR's
[release review report](https://github.com/BytesAndCoffee/byteplan/blob/codex/1.0-review-hardening/docs/stable-release-review.md).
Reassess the integrated state before A or B. The records on the base branch intentionally
remain open until the corresponding implementation and evidence are integrated.

For the first implementation increment after PRs #43/#44 integration, see the
[RC1 compatibility triage and migration report](../guide/migration.md). The measurements above
remain the historical documentation-assessment baseline, not the current completion state.

## Track A — Pre-1.0 compatibility and reliability

### A1. Persistent task identifier compatibility

Accept existing four-character lowercase hexadecimal IDs and longer supported IDs; generate
six-character hexadecimal IDs for newly allocated tasks. Define the supported length contract
centrally, remove hard-coded length assumptions throughout code and diagnostics, and retain
every existing four-character source annotation unchanged.

Lookup must prefer an exact ID, then accept an unambiguous short prefix. Reject ambiguous
prefixes with actionable candidate diagnostics. A short exact ID must still win when a longer
ID shares its prefix; do not prohibit those identities merely to simplify lookup. Persisted
references and external integration mappings use full exact identities. Abbreviations are a
user-interface convenience only.

Allocation checks active and reserved IDs, including independently developed branch collisions.
Test colliding allocations and reconciliation across divergent branches. Assess the existing
duplicate-reassignment command and provide safe, explicit collision reassignment if the
required cases otherwise need manual source edits. Preserve references and evidence or expose
the conflict explicitly; reassignment must never silently transfer another task's identity.

Acceptance: legacy IDs remain functional; new tasks receive six characters; exact lookups
always work; ambiguous abbreviations fail safely; all scanners recognize the supported contract;
unsupported or malformed annotations produce diagnostics rather than silently dropped work;
all source-editing guarantees continue to hold.

### A2. Registry schema compatibility and migration

Introduce schema version 2 where necessary to enforce the expanded persistent-ID contract.
Use the existing rejection of future schemas to protect repositories from incompatible
released clients. Investigate whether older scanners silently ignore six-character annotations;
do not infer safety just because the current client reports malformed annotations.

Provide an explicit migration entry point, even if the initial migration only normalizes
metadata. Complete the upgrade transactionally before writing incompatible annotations. Preserve
all tasks, history, evidence and unrelated fields. Migration must be idempotent and recoverable;
an interrupted migration must not leave a misleadingly valid registry. Test transaction failures
and retries, document recovery and never instruct users to bypass a journal or edit generated
JSON as a routine recovery procedure.

The following is a **required validation matrix**, not measured interoperability results:

| Client / repository | Required behavior |
|---|---|
| New client / existing schema 1 with four-character IDs | Safe read and explicit migration without data loss. |
| New client / schema 2, mixed legacy and new identities | Consistent scan, lookup, edits, verification, archive and merge behavior. |
| Previously released incompatible client / schema 2 | Visible rejection before destructive writes or incompatible source changes. |
| Previously released client / six-character annotations with old metadata | Investigate silent omission risk; prevent this state through upgrade ordering. |
| Interrupted migration / retry | Recovery preserves source and records; retry has no additional semantic changes. |

Run interoperability tests with actual previously released BytePlan packages in isolated
environments, recording versions and outcomes. Older incompatible clients must fail clearly
before destructive changes. Scanner and registry support must never disagree silently.
Addendum D's future Assignment migration must use an appropriate subsequent compatibility
boundary; schema v2 is no longer reserved for Assignments.

### A3. Registry layout and history storage

Choose and document the intended long-term authoritative storage contract before RC1. Compare:

1. Keeping history embedded in registry tasks.
2. Separating history into an append-only representation.
3. Storing tasks individually, with history separated where appropriate.

Evaluate ordinary Git merges, deterministic serialization and ordering, diff noise, growth,
identity stability, historical and verification evidence preservation, branch reconciliation,
future Assignment relationships, Jira/Linear/GitHub mappings, migration/compatibility and
large-repository performance. Record distribution and real conflict behavior matter more than
file size. Implement a layout migration before RC1 only for a demonstrated material
collaboration, integrity or compatibility risk; do not assume a redesign has been approved.

Separate authoritative task records, historical evidence, external mappings and rebuildable
indexes conceptually even if they share a physical file. The current JSON registry remains
authoritative until an explicit decision and migration supersede it. A graph cache must never
become a second task authority.

### A4. Plain-Git merge compatibility

Test independently created tasks on divergent branches both with the custom merge driver and
without it. Include colliding identities, independently updated histories, conflicting
verification evidence, competing lifecycle states, malformed or partially merged JSON,
ordinary conflict markers and partially resolved conflicts.

A successful merge preserves all valid work. A failed merge must not silently corrupt records,
discard evidence or arbitrarily choose competing lifecycle states. `byteplan check` must detect
incompatible or inconsistent merged state with actionable diagnostics. The driver may remain
recommended; correctness must not require every contributor to install it. An explicit ordinary
Git conflict is acceptable where automatic merging cannot be safe.

### A5. Source-editing safety and first-run ergonomics

Evaluate whether users can understand proposed changes before inserting IDs or detected-stub
annotations in an existing repository. Cover large initial scans, commit-hook behavior,
synchronization, BOM and newline preservation, syntax/AST preservation, idempotence, clear
change reports, report-only/preview workflows and predictable recovery. Prefer exposing and
documenting safe behavior already present. An ostensibly read-only operation must not silently
mutate source.

### A6. Compatibility boundary and remaining review inputs

Define the public 1.0 compatibility boundary for CLI, Python API, configuration, decorators,
MCP, Hatch and documented extension points. Inventory advanced interfaces and explicitly decide
which receive stability guarantees and which remain experimental. Mark experimental interfaces
clearly; task identity, source safety and authoritative registry semantics still need one
coherent stable contract. This document does not preempt that inventory by declaring every
current interface either stable or experimental.

Reassess TODO annotation lint behavior, including TD004, rapid-implementation documentation
drift, first-run complexity and progressive disclosure. Existing TD004 documentation is already
present; add functionality only if a verified pre-release need justifies it. A developer writing
a simple TODO must remain productive without learning Assignments or graph internals.

## Track B — Required pre-RC1 API decomposition

After compatibility changes are integrated, transform `api.py` into a concise stable public
facade. Inspect actual dependencies first and reuse existing modules. This is a structural
refactor, not a public API redesign. Suggested cohesive boundaries are:

| Module candidate | Responsibility |
|---|---|
| `api.py` | Public `Project` interface and stable entry points |
| `operations/scan.py` | Discovery and registry reconciliation |
| `operations/tasks.py` | Lookup, editing, lifecycle and resolution |
| `operations/verify.py` | Verification and acceptance evidence |
| `operations/release.py` | Release validation and stripping |
| `operations/scaffold.py` | Scaffolding orchestration |
| `operations/sync.py` | Source and registry synchronization |

These are suggestions, not instructions to duplicate the existing pure planners. Prefer
cohesive extraction and delegation over class hierarchies or unnecessary facade layers. Avoid
circular imports, global mutable state and duplicate implementations.

Preserve `byteplan.api.Project`, documented public imports, supported method signatures and
return values, CLI/MCP behavior, public exception types and error semantics, source editing,
transactions/recovery, registry compatibility, lifecycle and explicit resolution authority,
evidence/freshness, Hatch/Git integrations and documented extension points.

Known dependency checks include CLI, MCP, Hatch, Git write orchestration, reporting and
annotation type imports. Review monkey-patching before moving symbols: for example,
`tests/test_persistence.py` patches `byteplan.api.commit`. Establish intentional patch targets
before extraction rather than silently changing behavior.

Run the full suite before and after extraction: unit/integration, CLI/MCP, scanners/source edits,
registry migrations/archiving, verification/evidence, Git merging and transaction recovery.
Require strict typing, formatting, wheel and sdist builds and cross-platform CI. Add focused
regressions for uncovered behavior. Acceptance requires a substantially smaller, navigable
`api.py`, cohesive internal modules, unchanged supported external behavior, and documented final
module boundaries. Keep schema migration out of this dedicated PR.

## Track C — Proposed future architecture (E1–E8)

### E1. Purpose and authority

Extend source-native task tracking into repository-aware development intelligence using a
semantic graph connecting source entities, tasks, specifications, tests, verification evidence
and future Assignments. Support AI-assisted development while observing existing workflows.
The graph observes and connects artifacts; it does not compete with source code or task state
as an authority.

### E2. Semantic entities and relationships

<!-- TODO[a933]: 1.5 semantic graph schema, identity and provenance design
     Specify meaningful entities, relationship classifications, reproducible identity and
     rename/move behavior; keep the graph rebuildable and independent of task authority. -->

Do not persist every AST node. Represent meaningful modules/packages, classes/methods,
functions/nested functions, imports/symbol references, definitions/scopes, inheritance,
static calls, BytePlan tasks/decorators, tests/verification, authored requirements/specifications
and future Assignment relationships.

Proposed edges are `CONTAINS`, `DEFINES`, `IMPORTS`, `REFERENCES`, `CALLS`, `INHERITS`,
`IMPLEMENTS`, `VERIFIES`, `RELATES_TO_TASK` and `RELATES_TO_ASSIGNMENT`. Every inferred
relationship carries provenance and an explicit confidence or resolution classification.
Distinguish confirmed, possible and unresolved relationships. Do not claim complete static
understanding of dynamic Python.

### E3. BytePlan 1.5 — Graph foundations

<!-- TODO[e4af]: 1.5 repository symbol indexing and task-to-symbol associations
     Build scope/qualified-name, import, definition, reference and inheritance relationships;
     evaluate ast and justified LibCST metadata without modifying source. -->

<!-- TODO[3644]: 1.5 deterministic incremental graph cache and invalidation
     Fingerprint files, invalidate affected dependencies, and rebuild after checkout, moves
     and merges; do not require committing generated graph data. -->

<!-- TODO[1fe7]: 1.5 partial-index reliability, uncertainty and bounded queries
     Handle syntax errors, unresolved references and partial failures; test deterministic
     results, optional indexing, source immutability and preservation of authoritative tasks. -->

Implement repository-wide symbol indexing, qualified-name/scope resolution, import, definition,
reference and inheritance relationships, and associations between tasks and symbols. Evaluate
Python `ast` and, where justified, LibCST metadata/qualified-name resolution.

Construct deterministically, index incrementally using file fingerprints, invalidate affected
records after relevant source/dependency changes, and rebuild after branch checkout, source
moves or merges. Handle syntax errors and partially indexable repositories explicitly. Track
unresolved references and bound symbol/task queries. Prefer a rebuildable graph cache independent
of the authoritative registry; generated graph data need not be committed to Git.

Acceptance: existing workflows work without indexing; equivalent repository states produce
equivalent graph results; unchanged modules avoid unnecessary reindexing; dependency changes
invalidate affected records; indexing never edits source; uncertainty is visible; rebuilding
cannot lose authoritative task information.

### E4. BytePlan 2.0 — Graph intelligence

<!-- TODO[680a]: 2.0 cross-module dependency and change-impact analysis
     Trace known and potential dependencies from diffs, modules, symbols and tasks to
     affected implementation, requirements, Assignments and tests with explicit uncertainty. -->

<!-- TODO[cdcb]: 2.0 verification intelligence with traceable recommendations
     Associate changes with obligations, explicit staleness/unverified-change rules and
     targeted regression recommendations; graph uncertainty cannot establish verification. -->

<!-- TODO[4d69]: 2.0 Assignment and specification traceability
     Connect authored specifications, plans, annotations, symbols, tests and evidence through
     the future Assignment model without making any harness the lifecycle authority. -->

<!-- TODO[595f]: 2.0 bounded MCP graph operations and portable visualization design
     Design structured queries and CLI/IDE/optional visual representations; candidate names
     are not public commitments and no graphical interface is required. -->

Cross-module analysis identifies known and potential dependencies among modules, functions,
methods and imported symbols. Given a Git diff, module, symbol or task, impact analysis identifies
potentially affected implementation, requirements, Assignments and tests.

Verification intelligence links changes to verification obligations, identifies stale evidence
and unverified changes using explicit rules, and recommends targeted regression tests with
traceable explanations. Graph uncertainty must never justify declaring a task or change verified.

Trace Markdown specifications, plan tasks, annotations, implementation symbols, tests and future
Assignment records. Support specification-driven harnesses, coding agents and compatible tools
without assuming any harness controls the entire project lifecycle.

Design bounded structured MCP operations conceptually equivalent to `get_symbol`,
`get_dependencies`, `get_dependents`, `get_impact`, `get_related_tasks`,
`get_verification_coverage` and `get_unverified_changes`. These remain design candidates.
Define portable graph representations for CLI reports, IDE integration and optional interactive
visualization. A graphical interface is not required for core functionality.

### E5. Graph storage and identity

Design node/edge schemas with reproducible identifiers, repository-relative paths, qualified
names, provenance, relationship classifications, cache/schema versions and explicit invalidation
rules. Investigate renames and moves; a symbol's identity is not simply its current path or line.
Do not duplicate authoritative task state or introduce a second independent source of truth.

### E6. Performance and correctness risks

Plan tests for dynamic imports/runtime dispatch, reflection/monkey-patching,
decorators/metaclasses, conditional definitions, aliasing/shadowing, cycles, large repositories
and monorepositories, incremental invalidation, branch switching/merging, partial index failure,
memory/storage growth, false-positive impacts, false-negative dependency resolution and
verification evidence invalidation. Expose uncertainty instead of turning inferred graph
relationships into unjustified verification claims.

### E7. Relationship to the Assignment model

Assignments represent coordinated development obligations. The graph represents relationships
among source entities and development artifacts. They may together trace specification →
assignment → implementation → tests → evidence, while retaining separate responsibilities.
The graph enhances [Addendum D](spec-addendum-d.md); it does not replace it. A simple TODO
requires neither Assignments nor knowledge of graph internals.

### E8. Release boundaries

| Release | Boundary |
|---|---|
| 1.0 | Stable source-native task lifecycle, verification and core integrations; no graph implementation. |
| 1.5 | Semantic graph indexing and task-to-symbol relationships. |
| 2.0 | Cross-module analysis, impact intelligence, verification recommendations, Assignment traceability and advanced MCP queries. |

## Track D — BytePlan task registration and evidence

Use supported source or Markdown annotations and registry APIs for every confirmed issue and
approved obligation. Use `FIXME` for demonstrated correctness, compatibility, safety or technical
flaws; use `TODO` for planned implementation, architectural improvement, deferred capability or
a pending design decision. Never invent an ID or bypass the allocator. Preserve source semantics
and do not insert executable decorators when they change runtime behavior.

Apply `release:1.0`, `release:1.5` and `release:2.0` labels consistently. Keep existing task
identities, link relevant acceptance tests using supported verification mechanisms, record
evidence for fixes, and explicitly resolve completed work. Annotation disappearance does not
resolve a task. Keep future graph obligations open and excluded from RC1; a pending storage,
interface or schema decision is a design task, not authorization for an arbitrary implementation.

The Markdown annotations in this addendum are the source-native plan obligations. The generated
registry holds allocated identities and managed release labels; it must be updated through
BytePlan, not hand-edited. Existing Assignment task `15df` remains authoritative for Addendum D.

## Track E — Focused pull requests

| PR | Scope and review evidence |
|---|---|
| A — Compatibility and reliability | IDs, registry compatibility/migrations, collision recovery, ordinary-Git validation, source safety, storage decision and only justified layout migration. Include tests, risk assessment, migration procedure and measured compatibility matrix. |
| B — API decomposition | Begin after A integration. Behavior-preserving extraction, imports/delegation, regressions and architecture boundaries. Demonstrate equivalence without schema changes or unrelated features. |
| C — Architecture Addendum E | Complete addendum, implementation roadmap, deferred registrations/release labels and Assignment cross-references. No substantive semantic graph implementation. |

Run applicable checks and request independent review for each PR. Resolve confirmed blocking
findings before merging. Do not weaken tests, skip required checks or silently broaden scope to
obtain approval. PR C may document the plan while A and B remain pending; documentation is not
evidence that their acceptance criteria have passed.

## Track F — Final independent whole-repository reviews

<!-- TODO[c053]: RC1 freeze one integrated revision for two independent whole-repository reviews
     After A, B and C integration, record a common SHA, keep initial conclusions independent,
     register confirmed findings and repeat reviews when corrections invalidate conclusions. -->

After the preceding work is integrated, freeze a single Git SHA. Two independent reviewers must
review that exact revision repository-wide, rather than only the latest diff. Do not share one
reviewer's conclusions with the other before their initial review. Each examines:

1. Correctness and edge cases.
2. Source-editing and data-integrity guarantees.
3. Registry migrations and backward compatibility.
4. Task identity and collision handling.
5. Git merging and concurrency.
6. Verification and evidence integrity.
7. Security and untrusted repository inputs.
8. CLI, Python API, MCP and Hatch integrations.
9. Cross-platform compatibility and packaging.
10. Cohesion after API decomposition.
11. Public API stability and documentation accuracy.
12. Release readiness.

Classify demonstrated impact: P0/P1 blocks release for correctness, safety, security, data loss
or serious incompatibility; P2 requires explicit reliability/compatibility triage; P3 covers
polish, maintainability and future improvements. Stylistic preference alone is not a blocker.

Register confirmed findings, fix blockers with regressions and evidence, and repeat affected-area
reviews. If changes materially alter the architecture or invalidate whole-repository conclusions,
repeat both independent reviews against a new common SHA. Agreement means neither reviewer has
an unresolved blocker, not identical wording or the absence of nonblocking issues.

## Track G — Release candidate readiness and approval

<!-- TODO[a70d]: RC1 approval-ready release report and artifact/platform validation
     Assemble the reviewed SHA, integrated PRs, contracts, migration and storage decisions,
     validation and independent dispositions; do not tag or publish without explicit approval. -->

Prepare a report containing the exact reviewed SHA, merged PRs, compatibility/migration decisions,
final module boundaries, registry/ID guarantees, test results and platform coverage, formatting,
typing, packaging and install results, independent findings/dispositions, known nonblocking
issues, deferred graph work, and experimental/stable interface classifications.

RC1 is ready for approval only when:

- All confirmed release-blocking defects are resolved.
- The persistent-ID contract and registry migration/interoperability behavior are tested.
- Plain-Git merge failures are detected safely.
- Source mutation remains predictable and recoverable.
- API decomposition is complete and behaviorally equivalent.
- Cross-platform CI passes and built release artifacts install successfully.
- Both independent whole-repository reviews report no unresolved blocker at the recorded revision.
- Deferred work is tracked and explicitly excluded; Addendum E is documented and committed.
- The readiness report accurately describes the final state.

Do not tag or publish RC1 automatically. Present the final report for explicit approval.
The initial assessment SHA above is not a release-review freeze or an RC1 readiness claim.

## Engineering directive

Establish an auditable, backward-compatible foundation developers and coding agents can trust;
a green suite or two approvals alone do not establish that foundation.

**Plan in code. Track in one place.**

**BytePlan adapts to the way you work.**

Individual developers remain productive with simple TODOs and decorators. Larger teams and AI
systems can adopt coordination and verification without imposing one project-management
interface on everyone. Complete pre-release work carefully, document future architecture without
premature implementation, and stop at an approval-ready `v1.0.0rc1`.
