# BytePlan 1.0.0rc1 readiness report

<!-- FIXME[fd02a3]: Record the frozen tag commit before approval
  The evidence below is from b551870 plus the follow-up PRs. Once the tag commit is chosen,
  record its exact-head CI run, rebuild the wheel/sdist there and record their hashes and install
  smoke, and update README's "Status: preparing 1.0.0rc1" line when the tag is approved. -->

**Status: the four Codex review findings are corrected on this branch; final release gates
remain open.** No RC1 tag or package has been published. The [frozen review](reviews/rc1-d29ac93-codex.md)
demonstrated task loss (`c6bc7c`, P1), an external attributes write (`e86b8e`, P1), and two P2
findings (`9e4d1c`, `668a6c`). [Focused corrections](reviews/rc1-review4-corrections.md) have real
regressions, recorded linked verification, explicit task resolution and independent affected-area
reviews. Integration/platform checks and a new common-SHA pair of whole-repository reviews are
still required. Earlier `b551870` checks below are historical evidence, not final approval.

## Revision and integration gates

| Item | Current evidence |
|---|---|
| Readiness check SHA | `b551870` (`main` after PR #50). CI run 40450659828 passed all 15 jobs on its code commit `d5b7af9`; `b551870` only regenerates `byteplan.md`. |
| Changes after the check | PR #51 (merged as `ba32637`): prose comments that open with a tag word, such as `# Todo list model`, are no longer tasks (415a0f); review findings tracked. The RC1 follow-up PR: scaffold import sections (67a65c), PyPy classifier, sdist contents, documentation corrections. |
| Architecture plan | Addendum E and roadmap integrated through PR #44. Graph and Assignment implementation remain deferred. |
| Compatibility | PR #45 merged as `3745551c4ded3656ceef02b3760d5d73bb4a4ffa`; all 15 jobs passed on `182c882441cdaef35e88eb37f4cb55677c75e029`. |
| Restore integrity follow-up | PR #46 merged as `027578b75f2657fa54c8eff49ccb6e1bcbc561c7`; all 15 jobs passed on `fea1d3eb769a2f7d20f27c2d4227bfa660ade32f`. |
| API decomposition | PR #47 at `4e0256b1346aedd351419e09785cc8765bcd85df`; local validation and independent focused reviews passed; integrated and covered by the 15-job CI run on `d5b7af9`. |
| Candidate version | Core `1.0.0rc1` prepared separately from structural work; runtime remains separately versioned `0.1.0`. |
| Independent reviews | Two whole-repository reviews at `e7e526e` and two at `378e722`, with review-3 corrections (see [the findings](rc1-review-findings.md)). At `b551870`, one code and documentation review: one P2 (415a0f, fixed in PR #51) and five P3 documentation findings (fixed in PR #52). The subsequent independent Codex whole-repository review freezes `d29ac93bbbf57e9216a2c10694b307409399c734` and requires changes for two P1 and two P2 findings. Every PR also received an automated Codex review. No final pair has approved one common SHA after these corrections. Addendum E requires that pair; it is not replaced by PR reviews or green CI. |
| Reference artifacts | Built at `b551870`; these identify that revision only, not the tag. `byteplan-1.0.0rc1-py3-none-any.whl` `0da0391c7b51af27995bf9087f083b5d8c53a09288d0ccf63d7fc9a811e793ae`; `byteplan-1.0.0rc1.tar.gz` `18ff92142fdd6119b60dfae805b19ef7d4bd96e3c48d1c584a71d05f29add35f`; `byteplan_runtime-0.1.0-py3-none-any.whl` `ea09ff29453e3ddf99bcdb294f800be5cb4bc5d0276941dab213fdb33ebb1c94`; `byteplan_runtime-0.1.0.tar.gz` `19de333d1e04862f449e7055a60ef635484bd8f718246b46efc9a94a19f8d22b`. A clean virtual environment installed the wheel and its CLI ran. |

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

`byteplan.api.Project` remains the supported facade. Its 734-line module delegates cohesive
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

## Validation

At `b551870`, from a fresh clone: 1,659 tests passed, with one skip and the then-open
67a65c placeholder xfailed; `hatch fmt --check` passed 121 files; strict typing passed 120
files; `byteplan check` reported no errors or warnings; a second scan changed nothing; both
distributions built. The native Windows directory-junction test passed. After PR #51 the suite
passed 1,667 tests, and the BytePlan repository's own rescan found the same 24 annotations.

Earlier, the decomposition's local combined run passed 1,210 ordinary tests; all three explicit network
cases passed separately. One existing nonblocking P3 scaffold placeholder remains xfailed.
Strict typing passed 111 files and formatting passed 112 files. Public manifest comparisons
cover 43 signatures, 13 result types and six helper signatures; normalized AST comparisons cover
52 methods and 24 helpers. Focused independent reviews supplement these checks, but do not
replace either final whole-repository review.

Evidence still to record at the tag commit:

- Exact-head platform CI: CPython 3.11–3.14 on Linux, macOS and Windows; released clients;
  formatting/types, runtime checks and BytePlan consistency.
- Final local suite/network results and any changes after the recorded decomposition run.
- Wheel/sdist names, SHA-256 values, package metadata/contents and clean isolated installations.
- Installed CLI init/preview/scan/check, optional MCP stdio and Hatch hook smoke results.
- Any administrative documentation/task-record changes after the reviewed code revision.

Current CI does not establish PyPy coverage or the runtime's full advertised Python 3.8–3.14
matrix, so the core package no longer declares a PyPy classifier. Record actual coverage; do
not describe untested platforms as passing.

## Known nonblocking and deferred work

Graph foundations target 1.5; impact/verification intelligence and relevant Assignment
traceability target 2.0. Those tasks remain open under their release labels. Optional historical
phases and other future obligations remain tracked; a simple TODO requires none of them.
No semantic graph implementation belongs in RC1.

## Approval decision

**Pending final release gates.** The four confirmed P1/P2 corrections have real regression
tests, recorded evidence and explicit lifecycle resolution. Complete their integration and
platform validation. The writer-lock correction affects repository-wide integrity:
freeze a new common SHA and complete two independent whole-repository reviews under Addendum E,
then record its platform CI and freshly rebuilt/installed artifacts. Update this report with
the exact evidence and dispositions before presenting it for explicit approval. Do not tag
or publish automatically.
