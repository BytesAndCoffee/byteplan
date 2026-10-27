# Independent whole-repository RC1 review B

Reviewed revision: **378e722797d57b0bae257ca0f7fd2ad8d746547d**.
Checkout: `/workspace/byteplan-rc1-review2-b`.
Evidence: `/workspace/byteplan-rc1-evidence/review2-b`.

## Verdict

**Changes required before RC1 approval.** One demonstrated P1 write-boundary defect remains in initialization. A separate P2 narrowed-scan identity problem requires explicit triage. No release approval, tag or publication is supplied by this review. The independent initial assessment and bounded focused validation are complete. The redundant full-suite attempt was interrupted after the blocking verdict, with its exact partial result preserved below.

This is an independent initial whole-repository assessment, not a latest-diff review. I did not read reviewer A's report or receive that reviewer's conclusions. Historical acceptance documentation was consulted after the initial production-code pass. No tracked source, registry, Git history or remote state was changed by this reviewer. Tests and reproductions use disposable private data.

## Findings

### B1 — P1: initialization follows the state-directory alias outside project authority

Location: `src/byteplan/operations/initialize.py:169-171`.

Trigger: a project has a valid custom local registry (`registry="tasks.json"`) and `.byteplan` is a symlink to another directory outside its root. Calling the ordinary supported `init_project(project)` creates `.gitignore` in that external directory. The normal transaction path rejects aliased control directories, but initialization directly calls `atomic_write_bytes` without applying that boundary.

Demonstrated impact: unauthorized external file creation, with ignore rules for `txn/` and `scan.lock`. A tracked symlink and project configuration can supply the trigger; no concurrent replacement or real external-data access is required. The exact observed effect is constrained to this new fixed-name ignore file; this reproduction does **not** establish arbitrary file overwrite or execution. It nevertheless violates the project write boundary at the first-run entry point.

Private reproduction: `repro_init_alias.py`, output `repro_init_alias.log`; the retained private project and sibling destination are named in that log. The script calls production `init_project`, observes the new external file and asserts its exact bytes. All directories belong to this evidence area.

Bounded remedy: validate the state directory with the existing `control_directory` boundary and validate initialization targets before **any** initialization write, including shim/config/registry changes. Reject the alias with an actionable domain error, retaining it and every existing file. Add regression coverage for custom-registry projects with an external state-directory alias, plus confined aliases/native Windows junction behavior as applicable. This does not require redesigning storage or changing public interfaces.

### B2 — P2: a narrowed writing scan bypasses duplicate-ID blocking and rebinds observations

Locations: `src/byteplan/operations/scan.py:209-218`, the narrowed reservation helper at `:325`, and the write gate at `:298-301`.

Trigger: `a.py` owns an existing registered ID; `b.py` contains a copied annotation with the same ID and different title. A full preview reports `blocked=True`. Calling `scan(['b.py','c.py'], cwd=root, dry_run=False)` only diagnoses selected annotations. Its whole-scope allocation reservation pass reserves identities but does not diagnose the duplicate.

Demonstrated impact: the narrowed call returns `blocked=False`, writes a new ID into unrelated `c.py`, and changes the existing task's discovered title/location to `b.py`. Its managed status/notes and previous history remain present; no permanent record deletion was demonstrated. This contradicts the README's duplicate-ID write-blocking guarantee and associates one task's managed state with ambiguous source until repaired.

Private reproduction: `repro_narrow_duplicate.py`, output `repro_narrow_duplicate.log`, with retained fixture under this evidence directory. It verifies both the full-scan refusal and narrowed-scan writes using the public API.

Bounded remedy: before a narrowed mutation reconciles an observed ID or writes new annotations, check selected identities against the complete configured namespace for duplicate occurrences. Preserve narrowed missing/link semantics; do not reconcile out-of-selection tasks merely to check uniqueness. Add regression coverage with and without new allocations and verify every planned target remains unchanged on duplicate refusal.

## Scope and assessment

Production review covered models/configuration/identity validation; all scanner families and attachment/stub/binding rules; annotation, normalization, cleanup, scaffold and release/restore planners; registry/reconciliation/merge serialization; ordinary/staged transactions and recovery; snapshots, collision repair, archives and evidence; facade/result-type decomposition; CLI, MCP, Hatch, runtime package and repository automation. This is a finite code review, not proof of all possible inputs.

| Area | Assessment and evidence |
|---|---|
| Correctness and source safety | Structural edit validation, rescan checks, exact byte decoding, registry-last plans and source hashes are implemented coherently. B1 and B2 expose paths outside otherwise strong guard coverage. Existing safe-refusal and first-run fixtures were inspected. |
| Migrations/backcompat/IDs | Schema 2 explicitly gates expanded IDs, old four-character IDs remain accepted, exact UI lookup precedes prefixes, persistent references use exact IDs, reservations survive removal. Migration preserves raw extension data and uses transaction baselines. Released-client tests and their explicit network marker were inspected; this review has not independently rerun the network matrix. |
| Git/concurrency/recovery | Strict duplicate-key/conflict-marker loading and conservative semantic merges preserve history/extensions or surface conflicts. Ordinary recovery validates complete plans/copies; staged recovery distinguishes forward/rollback and index authority. Real-Git tests cover branch collisions, plain/custom merge, partial staging and interruption. Residual check/rename races are explicitly documented and not presented as new findings. |
| Evidence and resolution | Fingerprints, per-run identities, provenance validation, placeholder/non-pass handling, selected-snapshot reads and archive committed-copy checks are present. Tests never resolve tasks automatically. Explicit status/resolve remains the lifecycle authority. Imported-helper freshness limits and missing remote archive evidence are documented. |
| Security and untrusted inputs | Static scanners avoid repository imports. MCP separates registry/source/execution permissions and confines pending source recovery to authorized apply operations. Serialized journals/restores and SQLite aliases have explicit validation. B1 remains a first-run boundary gap. No real external-data probe was used. |
| API architecture/stability | Public facade delegates to cohesive operations and one canonical result-type layer; shared transaction ownership and tested late-binding boundaries remain centralized. Result identities/signatures/introspection have meaningful contract tests. No graph or Assignment implementation is introduced. |
| Adapters/platform/packaging | CLI dispatch, MCP stdio registration, default read-only Hatch behavior, pre-commit modes, project/runtime packaging and CI configuration were inspected. Local execution is Linux CPython 3.12 only. Parent-provided source-identical platform results and final artifact checks are separate evidence, not local platform passes claimed here. |
| Documentation/readiness | Compatibility, storage, merge, source-safety and architecture documents generally describe the implementation and limits accurately. At the frozen SHA, `docs/rc1-readiness.md` is explicitly a pending draft with stale integration/freeze rows; it needs final administrative reconciliation. B2 also needs the duplicate-safety documentation reconciled with its disposition. |

## Validation and limits

All core commands run from the reviewed checkout after sourcing `/workspace/byteplan-env.sh`, with absolute `PYTHONPATH=/workspace/byteplan-rc1-review2-b/src`. Interpreter: `/workspace/.byteplan-data/hatch/env/virtual/byteplan/c1S_SeYs/hatch-test.py3.12/bin/python` (CPython 3.12.14, pytest 9.1.1). Build, Hatchling, MCP and pathspec imports were verified before the test run (`dependencies.log`). Normal bytecode caches remained enabled.

- Additional focused selection: **73 passed in 102.54s**, covering facade contracts, the first-run/read-only source-safety audit, evidence integrity and restore-path validation (`focused.log`).
- Core full ordinary suite attempt: **incomplete, deliberately interrupted with SIGINT**, with **275 passed, 3 deselected and 1 xfailed in 672.97s** reported before interruption (`pytest.log`). This is not a full-suite pass. Collection was **1480 selected /1483 total**, with three network cases deselected (`collection.log`). The root reviewer agreed to stop this redundant old-revision run because B1 already blocks the freeze and a complete baseline/source-identical CI record exists separately; root will require the full suite and platform checks after correction. No test was weakened or skipped to obtain a pass. The normal xfail is the tracked P3 scaffold placeholder, not implementation evidence.
- Strict mypy: **passed**, 118 source files (`mypy.log`), using the prepared `types/bin/python` and `python -m mypy src/byteplan scripts tests`.
- Frozen committed consistency: **exit 0**, only the existing `67a65c` scaffold-placeholder informational diagnostic (`consistency.json`, `consistency.stderr`).
- Runtime CPython 3.12: **10 passed** (`runtime-py312-corrected.log`). This adds the runtime's absolute source directory to the core absolute PYTHONPATH for subprocess imports. An initial invocation inserted runtime source only into the parent process's `sys.path`, producing 9 passes and one subprocess import failure; `runtime-py312.log` is retained as an environment setup failure, not a product regression.
- Both new bounded reproductions completed with assertions confirming the findings.

No claim is made of locally verified macOS/Windows, Python 3.8–3.11/3.13–3.14, PyPy, downloaded released clients, final artifact identity, exhaustive races or performance guarantees. The root reviewer owns final frozen wheel/sdist and platform evidence. A green existing suite does not resolve the demonstrated findings.

The successful focused suite overlaps the interrupted broad run; their counts must not be added as unique coverage. Root-supplied prior full and platform results remain separate from this reviewer's measured results. After correcting B1, independently review the affected initialization paths, run the complete post-correction suite and reconcile B2's explicit triage before the readiness decision. No architectural objection or other demonstrated P0/P1 defect emerged from this finite review.
