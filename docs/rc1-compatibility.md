# RC1 compatibility hardening: triage, migration and remaining work

This is the first implementation increment of Addendum E Track A, based on merged main
`471ccca`. PRs #43 and #44 are integrated. This report is not an RC1 readiness declaration:
API decomposition, the final two whole-repository reviews, platform/artifact validation and
explicit release approval remain required.

## Triage in BytePlan

Severity describes demonstrated impact; an obligatory release gate is not itself a correctness
defect. High scheduling priority also applies to work explicitly required before RC1.

| Task | Impact / release consequence | Current action |
|---|---|---|
| `c978` | Highest compatibility priority: the former four-character-only contract cannot recognize expanded identities. Old clients warn but can still exit successfully with zero tracked tasks. | Implemented six-character allocation, legacy/long IDs, exact-first prefixes, scanner consistency and tests. Completed and explicitly resolved after linked verification and independent collision-recovery review. Original-branch repair preserves the complete task record, supported exact references and historical evidence. |
| `8756` | Highest prerequisite: incompatible source must never be introduced under metadata accepted by older clients. | Completed and explicitly resolved with journaled migration, allocation guards, released-package interoperability and preservation/recovery evidence. |
| `edc2` | P1 integrity risk: duplicate JSON keys can silently discard competing records; malformed merged evidence could escape `check`. | Strict parsing, evidence validation and real Git collision tests implemented. Broader lifecycle/history/evidence reconciliation and recovery matrix remains open. |
| `1b81` | P2 confirmed first-run problem: initialization could write a new shim before rejecting an incompatible registry. The broader safety audit is a required gate. | Validate before writes; retain the task for the full large-scan/hook/preview/source-recovery audit. |
| `4842` | P2 design decision required before RC1; file size alone is not an integrity defect. | Retain the JSON layout under the intended authority contract below; review the decision and collaboration/performance evidence before resolution. |
| `8aeb` | P2 documentation and compatibility-policy work. | Inventory stable/experimental interfaces, first-run guidance and drift after compatibility behavior settles. |
| `3844` | Required structural gate, scheduled high; size/coupling is a maintainability concern, not evidence of a P1 correctness defect. | Dedicated PR B after compatibility integration. |
| `c053` | Required independent-review gate; no defect severity assigned. | Freeze one integrated SHA only after A/B/C; run two independent whole-repository reviews. |
| `a70d` | Required artifact/platform/readiness approval gate; no defect severity assigned. | Assemble the final evidence report; do not tag or publish automatically. |

Future graph tasks remain open under `release:1.5` and `release:2.0`. No graph implementation
or Assignment implementation is included in this increment.

## Identity and schema contract

Persistent task IDs are lowercase hexadecimal strings of at least four characters. Existing
four-character annotations are retained byte-for-byte; new allocations use six characters.
Longer IDs may share prefixes with shorter IDs. Allocation checks active records, permanent
reservations and IDs already in source; only six-character reservations consume the allocation
namespace for exhaustion purposes.

Task selection prefers an exact identity across active and archived records, then an unambiguous
prefix. Ambiguity reports candidates before mutation. An archived exact legacy identity wins
over a longer active identity sharing that prefix. `@verifies`, pytest markers, registry keys
and integration mappings always retain full IDs; they do not resolve abbreviations.

New projects use schema v2. Reads and ordinary legacy task edits preserve schema v1 until
explicit migration. Allocation, stub synchronization, reassignment and importing expanded IDs
require v2 before source/registry writes. Staged reconciliation reads the staged schema, so
an upgraded working tree alone is insufficient: stage the migrated registry first.

Schema v2 here protects persistent-ID compatibility; it does not add Assignments or graph
records. The future Assignment migration must choose its own appropriate subsequent boundary.

## Migration and recovery

1. Upgrade participating clients to the version containing this change. Save existing work in
   Git and inspect the working tree before migration.
2. Run `byteplan migrate --dry-run`. It reports the registry target and writes nothing.
3. Run `byteplan migrate`, then inspect `git diff -- .byteplan/tasks.json` (or your configured
   registry path). This changes the schema boundary and deterministic JSON formatting only;
   source, task identities, history, extension metadata and verification evidence are preserved.
4. Commit/stage the schema change before writing expanded annotations. Run `byteplan scan
   --dry-run` to preview new allocations, then the normal writing workflow. Retain full IDs in
   references and external mappings.
5. Running migration again produces no additional changes. An interrupted migration uses the
   existing journal; rerun `byteplan migrate` to roll forward before allocation. A foreign edit
   conflicting with journal hashes must be inspected and reconciled explicitly rather than
   overwritten. Retain Git copies and the journal while investigating.

Do not downgrade by editing `schema_version`: older clients cannot understand expanded IDs.
If rollback is required, restore a coherent pre-migration repository state, including source,
registry and evidence, while retaining any subsequent valid work separately. A registry-only
rollback is unsafe. Migration itself never changes source annotations or deletes evidence.

Unknown registry/task fields and nested history, source-reference and test-link container metadata survive
subsequent edits and scans. Malformed JSON, duplicate keys and unresolved merge markers are
errors; fix the competing records or restore valid data from Git without discarding history.

## Released-client compatibility evidence

Tests install unmodified published packages in isolated target directories, assert their version,
and invoke their CLI against a schema-v2 repository containing an expanded task. This differs
from running the current registry parser against a synthetic old-version flag.

| Client | Schema 1 with a six-character annotation | Schema 2: `check`, writing `scan`, status mutation, ordinary `init` |
|---|---|---|
| PyPI 0.1.0 | Emits `MALFORMED_ID`, tracks zero tasks, exits 0. | Rejects visibly with upgrade guidance; repository files unchanged. |
| PyPI 0.2.0 | Emits `MALFORMED_ID`, tracks zero tasks, exits 0. | Rejects visibly with upgrade guidance; repository files unchanged. |
| New implementation | Rejects incompatible schema-1 source/allocation with `byteplan migrate` guidance. | Supports legacy and expanded IDs; future schemas are still rejected. |

The old scanners are not completely silent, but their successful exit with untracked annotations
is unsafe for automation that treats exit 0 as complete discovery. The schema boundary prevents
that mixed state in the supported write workflow.

Published 0.2.0 has a narrower limitation: `init --runtime-shim` creates a **new** inert shim
before rejecting schema v2. Existing task/evidence/source files are not overwritten, but this
command is not read-only on failure. Version 0.1.0 does not support the option and rejects it
during argument parsing. The new implementation validates first. Do not claim universal
zero-write rejection by every historical command. Upgrade before running initialization options.
Version 0.0.1 was a placeholder CLI without the registry implementation and is not an
interoperability baseline for task tracking.

Downloaded wheel SHA-256 values for this assessment:

| Package | SHA-256 |
|---|---|
| `byteplan-0.1.0-py3-none-any.whl` | `b80c9c4423e2fbee30b587ac2e0f48e60723a3d2582b5cebf285127dde6b05ff` |
| `byteplan-0.2.0-py3-none-any.whl` | `9dad97bf0a02e34723710b261094093dcca8c280b0a2a268b34b427e76e88d31` |

Run the automated interoperability cases with
`hatch test -- -m network tests/test_released_clients.py`. Ordinary non-network runs intentionally
exclude them; the release evidence must include an explicit network run.

## Intended authoritative storage contract

The measured merged-main registry contains 91 tasks and 450 history events in 218,671 bytes.
That increase includes newly registered release obligations and resolved review history; it does
not itself demonstrate a storage integrity or performance defect.

The intended contract retains deterministic, Git-versioned JSON task records with embedded
append-only lifecycle history. Verification remains a separate Git-versioned evidence store.
External mappings are managed authoritative metadata when introduced, not graph-cache facts.
Indexes and the proposed semantic graph are rebuildable and never independently own task state.

| Layout considered | Collaboration / growth | Decision |
|---|---|---|
| Embedded task history in `tasks.json` | Deterministic, one transaction target for records/history; ordinary Git can conflict on parallel additions. Existing driver merges by identity and rejects competing managed state/history rewrites. Linear parse/memory cost grows with records and history. | Retain. Explicit conflicts are acceptable; strict validation must prevent successful-looking corrupt merges. |
| Separate append-only history | Reduces task-record churn, but ordinary Git may still conflict on parallel appends. Requires stable event identities, cross-file atomicity, branch reconciliation and preservation of evidence references. | No demonstrated RC1 benefit sufficient to justify a new migration. |
| Individual task files, history separate as needed | Fewer independent-task merge collisions; increases files and requires cross-record transactions, archive/mapping migration and new ordering/consistency rules. | Reconsider only with measured collaboration/scale evidence. |

Task identity is independent of file layout and future Assignment relationships. The existing
archive index remains a committed reconciliation artifact; SQLite caches task records recovered
from Git and also holds local archived verification payloads. Such evidence may have no other
local copy until it is preserved elsewhere; the store is not a shared task-state authority.
Automatic archive reconciliation does not recover another clone's verification evidence; unavailable evidence must
remain unverified rather than being invented. Preserve evidence in Git and archival copies when
planning branch reconciliation. This existing limitation needs explicit consideration in A3/A4.

No physical layout migration is included. Benchmarking larger repositories and reviewing evidence
availability/reconciliation remain part of task `4842` before final disposition; do not interpret
this decision as a claim that those validations have already passed.

## Merge and collision recovery

Real divergent branches now demonstrate explicit identity-collision failure both with and without
the custom driver; both original task records remain available in Git. Strict checks reject
unresolved conflict markers, partially merged JSON, duplicate keys and malformed evidence in
the working tree or selected Git snapshot.

`repair --reassign PATH:LINE` still repairs a duplicate source copy. It creates a distinct task;
it does not salvage competing managed records from an already merged registry. For an independent
cross-branch collision, use the explicit original-branch workflow instead:

1. Preserve any merge-resolution work you need. If a merge is in progress, abort it using Git's
   normal procedure and return to one original branch. The repair command never aborts a merge
   or changes branches for you. Do not finish a merge by choosing one colliding registry record.
2. Commit the original branch's reconciled task and supported verification references. Both
   branches must contain the collision, and the ID must be absent from every merge base's active,
   archived, reserved, source-reference and evidence identities. A cherry-picked task with shared
   creation provenance is the same task: merge its managed state rather than reassigning it.
3. On the branch whose task should receive a new identity, run
   `byteplan repair --reassign PATH:LINE --against OTHER_REV --dry-run`. Review the exact pinned
   HEAD and peer commits and proposed file list. The preview does not change source, registry,
   evidence or the index.
4. Repeat without `--dry-run`, inspect the diff, commit it, and retry the merge. The repair does
   not stage files. It reserves both identities and appends an `identity_reassigned` history event
   containing the old/new IDs, both pinned commits and all merge bases.
5. Run `byteplan check` on the result. An ordinary Git conflict in registry or evidence is acceptable:
   reconcile both versions explicitly, keeping both task records and their evidence. A successful
   registry-driver merge does not promise that the separate evidence JSON can merge automatically.
   Run `byteplan scan` to reconcile discovered locations/links, then reverify before resolving work.

The branch workflow preserves local lifecycle, managed fields, history and supported extension
metadata. It edits only the selected annotation and scanner-confirmed exact `@verifies` / enabled
pytest-marker references, checking the expected Python AST or non-Python source invariant before
writing. Escaped and concatenated Python literals, supported Markdown/JSONC annotations, Unicode,
BOMs and newline conventions are covered. Locations and discovered links are recomputed after
multiline edits. Other task records and historical old-ID strings remain intact.

Evidence is moved to the new canonical key with its results, run provenance, extension data and
**old fingerprint** retained. The ID/source changes make it stale; historical passing evidence
is not a fresh verification claim. Other tasks' evidence and unreferenced run records are retained.
Source, evidence and registry use one existing journal transaction. An interrupted repair rolls
forward through `byteplan scan`; conflicting foreign edits must be reconciled rather than overwritten.

The command rejects ongoing Git operations (including a resolved but uncommitted merge), unmerged
indexes, alternate index environments, active index locks and pending BytePlan journals. An index
lock excludes ordinary checkout/add/merge during the write, pinned HEAD is rechecked, and transaction
hashes reject conflicting file edits. It rejects inherited/reserved IDs, missing/shared creation
provenance, rewritten working history, differing project roots/registry paths, uncertain managed
annotations, ignored contexts containing the identity, known test links outside editable scope,
and unknown current metadata containing an exact old-ID reference. These cases need review with
a client that understands the reference semantics; they are not invitations to perform a global
string replacement. The supported scanner/configuration scope defines editable references.
External systems and references outside that scope require explicit coordination; this command
cannot atomically rewrite external mappings.

The remaining Track A matrix includes independently updated histories, competing lifecycle
states, conflicting verification evidence, partially resolved semantic inconsistencies and
source-editing/first-run audits. API decomposition begins only after compatibility integration.
Final whole-repository reviews and the readiness report require a later integrated, frozen SHA.

## Validation of this increment

- Clean merged baseline: 864 non-network tests passed.
- Initial full suite: 918 passed, three network cases deselected by the normal policy.
- Collision follow-up adds 47 passing acceptance cases, independently rerun by the reviewer.
  Final full suite: **965 passed**, three network cases deselected; both actual released-client
  interoperability cases passed explicitly afterward. Formatting, strict typing (89 source files),
  wheel/sdist builds and isolated install/CLI smoke checks passed.
- Both actual released-client cases passed explicitly. A dedicated CI job runs them; BytePlan's
  verification runner also includes linked network acceptance tests instead of silently excluding them.
- Independent review's three P2 findings were corrected with preservation, concurrency and
  malformed-evidence regressions. The reviewer independently ran all 50 compatibility cases and
  reported no unresolved blocker in this draft increment.
- Strict typing and formatting passed. Wheel/sdist build and installation checks are recorded
  with the PR. All 15 CI jobs passed at `c51b871`, including Linux/macOS/Windows with Python
  3.11–3.14, lint/types, registry consistency and actual released clients. The recovery follow-up
  requires its own CI run before integration.
- BytePlan verification records evidence for `8756`, `c978`, `edc2` and `1b81`. Migration `8756`
  and persistent-ID/collision recovery `c978` are explicitly resolved; `c978`'s source annotation
  was removed by `resolve --sync-source`, followed by scan and fresh verification. Passing linked
  tests do not resolve the broader `edc2`, source-safety, storage or interface-policy obligations.
- The independent recovery review corrected Git-operation-state, encoded ignored-reference and
  shared-creation-provenance gaps with regressions, and reported no unresolved blocker in its
  final 47-case rerun. This does not replace updated platform CI or the remaining Track A matrix.

This focused review is not either of the two final whole-repository reviews required by Track F.
