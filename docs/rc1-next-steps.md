# RC1 next steps — fresh assessment, 24 October 2026

Assessment revision: `8e829805d2e950d31c1e2a6c746aa215ea143dc6` on
`codex/rc1-compatibility`. Main remains `471ccca109670339a443a6488e90377a00178dab`.
Fresh clone: `/workspace/byteplan-rc1-next`, local branch `codex/rc1-next-plan`.
This is a planning checkpoint, not a release-readiness declaration or implementation increment.

## What changed since the previous checkpoint

Four commits follow `d721919`: registration, implementation and explicit resolution of
mixed-schema merge task `ee606e`, then registration of three ergonomics findings. The merge
now takes schema 2 when merging supported schema-1/schema-2 histories. Its three new unit
cases preserve a branch's status change. The previous conservative conflict did not itself
demonstrate data loss: explicit conflicts are allowed by Addendum E. Treat this as a useful
compatibility improvement, rather than inheriting the task title's P1 severity without evidence.

PR [#45](https://github.com/BytesAndCoffee/byteplan/pull/45) is open and draft. All 15 jobs in
[CI run 40120424523](https://github.com/BytesAndCoffee/byteplan/actions/runs/40120424523)
passed on the assessment revision, including Linux/macOS/Windows Python 3.11–3.14,
released-client interoperability, lint/types and BytePlan consistency. No inline review threads
were returned. The PR description still describes `8c0ec8e` and mixed-schema rejection; update
it when presenting the completed compatibility work for review.

Local targeted validation used this checkout's `src` with the existing Python 3.12 environment:
`tests/test_merge.py`, `test_merge_integrity.py`, `test_mcp_server.py`, `test_verification.py`
and `test_scaffold.py`: **129 passed, 3 xfailed**. The xfails are unfinished acceptance
placeholders for the three new findings, not evidence that those requirements are implemented.
This assessment did not rerun the entire suite, packaging or released-client tests locally.

The registry has 100 tasks (75 resolved, 22 open, 3 in progress), 541 history events and
335,233 bytes before this planning update. Growth alone does not justify a storage migration.
`edc2` is ready for review according to its recorded evidence; its broad acceptance disposition
is still open. `ee606e` and `1b81` have stale evidence. Resolution is a lifecycle decision;
stale evidence does not automatically reopen or re-resolve a task.

## Recommended execution order

| Order | Existing tasks | Next concrete work | Completion evidence |
|---|---|---|---|
| 1. Close merge acceptance | `edc2`, resolved `ee606e` | Review the completed A4 matrix against every requirement. Extend the mixed-schema case through the actual driver and divergent Git branches, with legacy tasks, a new six-character task, history and reservations. Check branch orientations, malformed/future schemas, evidence conflicts and no-write failures. Retain explicit conflicts for competing authoritative state. | Fresh linked verification; successful results preserve both branches' valid work; failures preserve original records/evidence. Record any remaining limits, then explicitly resolve `edc2` only when the whole acceptance scope is met. |
| 2. Finish safety and storage audits | `1b81`, `4842` | Inventory mutation and preview behavior for first scan, hooks, sync, repair, release/restore and read-only commands. Reuse BOM/newline/AST/recovery tests; fill actual gaps. Measure larger synthetic registries and document archive/evidence recovery across clones. | An acceptance-to-test map, non-mutation/idempotence evidence, measured scale results and a final authoritative-storage decision. Preserve current JSON layout unless material risk justifies migration. |
| 3. Finish interface policy and narrow ergonomics fixes | `8aeb`, `b29c72`, `932b36`, optional `67a65c` | Publish stable/experimental boundaries for CLI, Python API, config, decorators, MCP, Hatch and documented extensions. Explain previews and TD004. Implement the two P2 diagnostic fixes below without implicit scans or broader product features; take the P3 formatting fix only if it stays bounded. | Replace placeholders with real regression tests, record fresh evidence and explicitly resolve completed defects. Cross-check README, compatibility report and implementation plan against actual behavior. |
| 4. Complete PR A | `edc2`, `1b81`, `4842`, `8aeb` | Reconcile with any later collaborator commits before writing the shared branch. Refresh stale evidence after final edits, update PR metadata, run required checks and obtain independent compatibility review. | Full suite, released clients, format/types, builds/install checks, all platform CI and disposition of blocking findings. Integrate PR #45 before starting PR B. |
| 5. Decompose the API in PR B | `3844` | Capture the baseline public signatures, exceptions, return types and patch targets. Extract cohesive orchestration using existing modules and a small internal operations layer where needed. | Full before/after suite and integration/build/platform checks; concise public facade and documented final boundaries. No schema or feature changes mixed into the refactor. |
| 6. Freeze and assess the release | `c053`, `a70d` | Freeze one integrated SHA after A/B/C. Run two independent whole-repository reviews without sharing initial conclusions. Register confirmed findings, fix blockers and repeat affected reviews as required. | Exact reviewed SHA, findings/dispositions, fresh final platform/artifact evidence and an accurate readiness report presented for explicit approval. Do not tag or publish RC1. |

Steps 1–3 belong to compatibility PR A. The storage and source audits can be assessed
independently, but their final decisions must precede compatibility integration. PR C's
Addendum E documentation is already merged through PR #44. Graph and Assignment implementation
remain outside RC1.

## Triage of the newly registered findings

| Task | Assessment | Bounded implementation direction |
|---|---|---|
| `b29c72` | P2 workflow reliability: a renamed discovered test retains its old node until scan; verification safely reports `not_found`, not a pass. | Prefer actionable `byteplan scan` guidance. Preserve explicit managed links and avoid making verification silently mutate source or registry discovery state. Test rename → not-found guidance → explicit scan → successful verification. |
| `932b36` | P2 diagnostic/recovery issue: an old long-running MCP process can retain old code after an upgrade. Newer-schema rejection remains protective. | Explain both upgrade and restart/reconnect as applicable; do not assert that restart alone fixes a genuinely unsupported schema. Preserve structured tool errors and read-only failure behavior. |
| `67a65c` | P3 formatting integration: first-party shim imports may need separation from third-party pytest under the repository's Ruff settings. No demonstrated source-semantic or evidence-integrity defect. | Check runtime-module configuration and existing scaffold contracts before changing output. Use a real formatter regression for the first-party case and preserve third-party behavior. Optional before RC1; record explicit nonblocking disposition if deferred. |

All three are planned under `release:1.0`; that label is a scheduling classification, not a
claim that each is release-blocking. Their existing IDs and source FIXMEs remain authoritative.
No duplicate obligations or arbitrary IDs are introduced by this plan.

## API decomposition starting point

`api.py` is now 2,881 lines; `Project` occupies 2,125 lines. Existing modules
already implement low-level scanning, reconciliation, source edits, verification, scaffolding,
release operations, registry, collision checks and persistence. Extract orchestration rather
than duplicate those implementations. Candidate boundaries are scan/reconciliation, verification,
scaffolding, release/restore, task lifecycle/repair and archive operations. Keep locking,
transaction ownership, snapshots and dependencies explicit; avoid a hierarchy of mixins.

Preserve `byteplan.api.Project`, documented result types/imports and signatures. In particular,
`tests/test_persistence.py` patches `byteplan.api.commit`: establish intended patch compatibility
before moving that dependency. Inspect indirect test patching and CLI/MCP/Hatch consumers too.
Choose extraction order and a measurable facade-size goal in PR B after compatibility settles.

## Execution disposition

The user approved execution of this plan. Merge acceptance (`edc2`), source safety (`1b81`),
storage decision (`4842`) and interface policy (`8aeb`) are now explicitly resolved after
their acceptance work. Diagnostics `b29c72` and `932b36` are fixed. Independent review found
and verified two additional defects, allocated through BytePlan: archive durability `af82fd`
and snapshot isolation `c35e66`. Both are explicitly resolved with real regression tests.
The earlier assessment above is retained as a dated starting point, not a claim that its
original stale evidence or task statuses are current. PR #45 is now merged as `3745551`
after all 15 CI jobs passed on `182c882`, including the corrected Windows storage fixtures.

See [the compatibility report](rc1-compatibility.md) and its linked acceptance maps for
implementation/recovery boundaries and final validation. The P3 scaffold import-formatting
issue `67a65c` remains open and nonblocking. Independent API review subsequently reproduced
inherited restore defect `50ad66`: concurrent evidence/index changes could be overwritten,
and an old cached pass could replace a newer canonical failure. Its compatibility correction
is isolated in PR #46; integration precedes the structural PR. The
[API decomposition](api-architecture.md) is implemented locally and retains the corrected
restore semantics, with public contract and method-body comparisons. Next: integrate the
compatibility follow-up and dedicated decomposition, prepare candidate artifacts, freeze a
common reviewed SHA and complete the final approval report. No graph
or Assignment implementation is authorized by this execution; do not tag or publish RC1.
