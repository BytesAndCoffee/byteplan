# BytePlan 1.0.0rc1 readiness report

<!-- FIXME[fd02a3]: Reconcile this report with the final frozen revision before approval
  It still says the whole-repository reviews and artifact checks are pending. Record the reviewed
  SHA (b551870; CI 40450659828 passed 15/15 on d5b7af9), the review rounds and dispositions, the
  native Windows junction pass, artifact hashes and install smoke results, and update README's
  "Status: preparing 1.0.0rc1" line when the tag is approved. -->

<!-- FIXME[bf67e6]: Drop the PyPy classifier or add PyPy to CI
  pyproject.toml declares `Implementation :: PyPy`, but no CI job runs PyPy, and this report says
  untested platforms must not be described as supported. -->

<!-- FIXME[bbff04]: Keep internal review notes out of the sdist
  docs/reviews/ and rc1-next-steps.md ship in the sdist with internal /workspace/... paths and
  process detail. Exclude them in [tool.hatch.build.targets.sdist] or move them out of docs/. -->

**Status: preparation in progress; release approval is pending.** No RC1 tag or package has
been published by this work. This report must be completed against the final integrated
revision before it can support an approval decision.

## Revision and integration gates

| Item | Current evidence |
|---|---|
| Common whole-repository review SHA | Pending integration and freeze; no final review has started. |
| Architecture plan | Addendum E and roadmap integrated through PR #44. Graph and Assignment implementation remain deferred. |
| Compatibility | PR #45 merged as `3745551c4ded3656ceef02b3760d5d73bb4a4ffa`; all 15 jobs passed on `182c882441cdaef35e88eb37f4cb55677c75e029`. |
| Restore integrity follow-up | PR #46 merged as `027578b75f2657fa54c8eff49ccb6e1bcbc561c7`; all 15 jobs passed on `fea1d3eb769a2f7d20f27c2d4227bfa660ade32f`. |
| API decomposition | PR #47 at `4e0256b1346aedd351419e09785cc8765bcd85df`; local validation and independent focused reviews passed; platform CI/integration pending. |
| Candidate version | Core `1.0.0rc1` prepared separately from structural work; runtime remains separately versioned `0.1.0`. |
| Independent reviews | Both initial whole-repository reviews pending, against one common integrated SHA. |
| Final artifacts | Candidate wheel/sdist builds, hashes, isolated install checks and integration smoke results pending. Earlier `0.2.0` development builds do not establish candidate artifact identity. |

## Compatibility, migration and authoritative state

Persistent IDs are lowercase hexadecimal strings of at least four characters. Four-character
annotations remain valid; new tasks receive six characters. Exact IDs win before unambiguous
UI prefixes. Persisted references keep full identities; ambiguous abbreviations fail safely.
Allocation excludes active, reserved and discovered identities. Explicit original-branch
collision repair preserves the task record and exact supported references, reserves both IDs
and requires new verification.

Upgrade clients, preview and apply `byteplan migrate`, and stage/commit the schema-v2 boundary
before allocating expanded IDs. Migration is journaled and idempotent, preserving tasks,
history, evidence and extension fields. Published 0.1.0/0.2.0 clients visibly reject schema v2
in the tested ordinary commands; schema-v1 scans can otherwise warn yet report no tasks with
a successful exit. Do not downgrade by editing the schema number. Historical 0.2.0
`init --runtime-shim` can create a new inert shim before rejection. Recovery and the measured
matrix are in [the compatibility report](rc1-compatibility.md).

The JSON registry remains authoritative; no major layout migration was justified by size.
Historical evidence, external mappings and rebuildable indexes remain conceptually distinct.
Ordinary Git may produce explicit conflicts. The optional merge driver preserves valid work
and rejects competing authoritative edits. Malformed JSON, duplicate keys, conflict markers
and inconsistent evidence are diagnosed rather than treated as valid merged state.

In Git, archival requires the current task/evidence/run to have a committed copy. Exact parsed
bytes guard planned writes; restore preserves existing canonical evidence even when stale or
failing. Other clones can recover task records from available history, but current traversal
does not automatically import their historical verification payload. Shallow/rewritten history
and local SQLite backup limits are documented in [the storage decision](rc1-storage.md).

## Final module and interface boundaries

`byteplan.api.Project` remains the supported facade. Its 725-line module delegates cohesive
scan, task, verification, scaffold, release, sync, archive and initialization operations to
internal modules. Existing algorithm modules keep their responsibilities. The 13 public result
types retain their `byteplan.api` identities, pickle lookup and supported constructor annotation
namespaces. Public signatures, exception semantics, sentinel behavior, late-bound tested patch
targets and transactional ownership remain intact. See [the module map](api-architecture.md).

The [compatibility policy](compatibility-policy.md) covers the documented CLI, Python API,
configuration, decorators, MCP stdio, Hatch/Git integrations and extension points. Python MCP
embedding is experimental. Stable identity, source safety and authoritative task/evidence
semantics apply throughout. Source mutation and execution reject read-only snapshots before
side effects; selected-view queries use selected data, and index HEAD freshness is uncertain.
Preview and first-run behavior are documented in [the source-safety map](rc1-source-safety.md).

## Validation to complete at the frozen revision

The decomposition's local combined run passed 1,210 ordinary tests; all three explicit network
cases passed separately. One existing nonblocking P3 scaffold placeholder remains xfailed.
Strict typing passed 111 files and formatting passed 112 files. Public manifest comparisons
cover 43 signatures, 13 result types and six helper signatures; normalized AST comparisons cover
52 methods and 24 helpers. Focused independent reviews supplement these checks, but do not
replace either final whole-repository review.

Final evidence must record:

- Exact-head platform CI: CPython 3.11–3.14 on Linux, macOS and Windows; released clients;
  formatting/types, runtime checks and BytePlan consistency.
- Final local suite/network results and any changes after the recorded decomposition run.
- Wheel/sdist names, SHA-256 values, package metadata/contents and clean isolated installations.
- Installed CLI init/preview/scan/check, optional MCP stdio and Hatch hook smoke results.
- Both independent reviewers' common SHA, scope, findings, severities and dispositions.
- Any administrative documentation/task-record changes after the reviewed code revision.

Current CI does not establish PyPy coverage or the runtime's full advertised Python 3.8–3.14
matrix. Record actual coverage; do not describe untested platforms as passing.

## Known nonblocking and deferred work

Scaffold import formatting task `67a65c` remains open/P3: new files using a first-party runtime
shim can need a formatter pass to separate that import from pytest. It does not demonstrate
source-semantic or verification-integrity failure. Its strict expected-failure placeholder is
not evidence of implementation.

Graph foundations target 1.5; impact/verification intelligence and relevant Assignment
traceability target 2.0. Those tasks remain open under their release labels. Optional historical
phases and other future obligations remain tracked; a simple TODO requires none of them.
No semantic graph implementation belongs in RC1.

## Approval decision

**Pending.** Complete the frozen-revision reviews, resolve confirmed release blockers, verify
candidate artifacts/platforms and reconcile this report before presenting it for explicit
approval. Do not tag or publish automatically.
