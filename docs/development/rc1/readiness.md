# BytePlan 1.0.0rc1 readiness report

**Status: ready for explicit approval.** The frozen code has its full release evidence below.
No RC1 tag or package has been published.

The [`a5de5c8` gate](gate-check.md) was reviewed independently by Codex and Claude, with a
focused third review by ChatGPT. None approved it. Together they confirmed one P1 (`53c751`, a
journal supplied by repository content was replayed into arbitrary paths), five P2s and five P3s
([Claude](reviews/rc1-a5de5c8-claude.md), [Codex](reviews/rc1-a5de5c8-codex.md),
[ChatGPT](reviews/rc1-a5de5c8-chatgpt.md)). PR #55 corrects all eleven, plus three P2 regressions
Codex found in those corrections, each with a regression test, recorded verification and explicit
resolution. The code is frozen at the PR #55 merge, `0964bb4b333843b43409a58f5fbe7e73e3d610d5`;
only documentation changes follow it. Earlier evidence below is history, not approval.

**Owner decision (2026-10-27):** no further pair of AI whole-repository reviews for RC1. Addendum
E's repeat-pair requirement after material corrections is explicitly waived for this candidate,
not met. Instead, independent human review is invited against the tagged RC1; its findings are
triaged for RC2 or 1.0.

## Revision and integration gates

| Item | Current evidence |
|---|---|
| Release evidence | `c4b812015d151f508113329b7e7fd1d9113b3ae3` (`main` after the docs review, PR #56), code-identical to the freeze. CI run `40587846922` passed all 15 jobs. From a fresh clone: 1,776 tests passed, two skipped, no expected failures; three network tests passed; formatting (124 files), strict typing (123 files) and `byteplan check` clean; a dry-run scan found nothing to change; the tree stayed clean. Its artifacts (wheel `d145f0a6f5bd536544c2e6e4490eca6d53b166a4ae2003a02b7fe47308a1ccf3`, sdist `a547a9d84ad9e469b709f1788895afc463ff90b9228ea004925affb2499b4c62`; runtime wheel `ea09ff29…bb1c94` and sdist `19de333d…f8d22b`, byte-identical to every earlier build) passed clean-install smoke tests: CLI `init`, preview, `scan`, `check` and `list`; MCP stdio (12 read-only tools, `scan(apply=true)` refused without permission); a PEP 517 build with the Hatch hook; and an sdist install. |
| Documentation after the evidence | Documentation only: `docs/` split into `guide/` and `development/` (the sdist now excludes `docs/development`), README review, and this report. The sdist ships these documents, so the tag commit's artifact hashes differ from the ones above; they are recorded in the RC1 tag message and release notes, since no file can hold the hash of an sdist that contains it. |
| Current code freeze | `0964bb4b333843b43409a58f5fbe7e73e3d610d5`, the PR #55 merge. Its code is identical to PR head `b8d130c`, whose CI run `40568261164` passed all 15 jobs. Local suite at that head: 1,776 passed, two skipped, no expected failures. |
| Gate review (`a5de5c8`) | Not approved. Codex and Claude reviewed the whole repository independently; ChatGPT reviewed focused paths. Findings: P1 `53c751`; P2 `e3d6bd`, `6944ec`, `515d45`, `6698e7`, `26756c`; P3 `aaf7d7`, `bbe04c`, `7140aa`, `971b9d`, `e8bd84`. All are resolved in PR #55, as are Codex's follow-up P2s `4308bf`, `e56005` and `8df831`. Gate artifacts (wheel `f708b6e8…db95`, sdist `92815239…4eec`) identify the rejected gate only. |
| Latest compatibility correction | PR #54 merged as `013f71b0f88824001fdf2e3d0dcdb30425b6e77d`; CI run `40541039783` passed all 15 jobs at head `b8cdbc5f6f17632c05118716d48756f39ef483ac`. Local suite: 1,742 passed, two skipped; network: three passed; typing: 123 files; formatting: 124 files. Clean installed artifacts/MCP/Hatch/runtime passed. The reference artifacts identify that pre-integration head, not the new gate. |
| Readiness check SHA | `b551870` (`main` after PR #50). CI run 40450659828 passed all 15 jobs on its code commit `d5b7af9`; `b551870` only regenerates `byteplan.md`. |
| Changes after the check | PR #51 (merged as `ba32637`): prose comments that open with a tag word, such as `# Todo list model`, are no longer tasks (415a0f); review findings tracked. The RC1 follow-up PR: scaffold import sections (67a65c), PyPy classifier, sdist contents, documentation corrections. |
| Architecture plan | Addendum E and roadmap integrated through PR #44. Graph and Assignment implementation remain deferred. |
| Compatibility | PR #45 merged as `3745551c4ded3656ceef02b3760d5d73bb4a4ffa`; all 15 jobs passed on `182c882441cdaef35e88eb37f4cb55677c75e029`. |
| Restore integrity follow-up | PR #46 merged as `027578b75f2657fa54c8eff49ccb6e1bcbc561c7`; all 15 jobs passed on `fea1d3eb769a2f7d20f27c2d4227bfa660ade32f`. |
| API decomposition | PR #47 at `4e0256b1346aedd351419e09785cc8765bcd85df`; local validation and independent focused reviews passed; integrated and covered by the 15-job CI run on `d5b7af9`. |
| Candidate version | `byteplan` and `byteplan-runtime` are both `1.0.0rc1`: from this release they are versioned in lockstep (owner decision, 2026-10-27). The runtime's API is unchanged from 0.1.0; only its version moves. |
| Independent reviews | Two whole-repository reviews at `e7e526e` and two at `378e722`, with review-3 corrections (see [the findings](review-findings.md)). At `b551870`, one code and documentation review: one P2 (415a0f, fixed in PR #51) and five P3 documentation findings (fixed in PR #52). The subsequent independent Codex whole-repository review freezes `d29ac93bbbf57e9216a2c10694b307409399c734` and requires changes for two P1 and two P2 findings. Every PR also received an automated Codex review. No final pair has approved one common SHA after these corrections. Addendum E requires that pair; it is not replaced by PR reviews or green CI. |
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
matrix are in [the compatibility report](../../guide/migration.md).

The JSON registry remains authoritative; no major layout migration was justified by size.
Historical evidence, external mappings and rebuildable indexes remain conceptually distinct.
Ordinary Git may produce explicit conflicts. The optional merge driver preserves valid work
and rejects competing authoritative edits. Malformed JSON, duplicate keys, conflict markers
and inconsistent evidence are diagnosed rather than treated as valid merged state.

In Git, archival requires the current task/evidence/run to have a committed copy. Exact parsed
bytes guard planned writes; restore preserves existing canonical evidence even when stale or
failing. Other clones can recover task records from available history, but current traversal
does not automatically import their historical verification payload. Shallow/rewritten history
and local SQLite backup limits are documented in [the storage decision](../../guide/storage.md).

## Final module and interface boundaries

`byteplan.api.Project` remains the supported facade. Its 739-line module delegates cohesive
scan, task, verification, scaffold, release, sync, archive and initialization operations to
internal modules. Existing algorithm modules keep their responsibilities. The 13 public result
types retain their `byteplan.api` identities, pickle lookup and supported constructor annotation
namespaces. Public signatures, exception semantics, sentinel behavior, late-bound tested patch
targets and transactional ownership remain intact. See [the module map](../api-architecture.md).

The [compatibility policy](../../guide/compatibility-policy.md) covers the documented CLI, Python API,
configuration, decorators, MCP stdio, Hatch/Git integrations and extension points. Python MCP
embedding is experimental. Stable identity, source safety and authoritative task/evidence
semantics apply throughout. Source mutation and execution reject read-only snapshots before
side effects; selected-view queries use selected data, and index HEAD freshness is uncertain.
Preview and first-run behavior are documented in [the source-safety map](../../guide/source-safety.md).

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

**Ready for explicit approval.** Every finding from the `a5de5c8` gate reviews is corrected with
regression tests, recorded evidence and explicit resolution; the frozen code passes the full
platform matrix, the local gates and clean-install smoke tests. By the owner decision above, no
further AI review pair is required. To tag:

1. Finish documentation changes. The last documentation commit on `main` is the tag commit.
2. Confirm its platform CI passes, rebuild the wheel and sdist from a fresh clone of it, and put
   their SHA-256 hashes in the tag message and the release notes.
3. The owner approves and tags. Nothing is tagged or published automatically.

After the tag, independent human review of RC1 is invited; its findings are triaged for RC2 or
1.0.
