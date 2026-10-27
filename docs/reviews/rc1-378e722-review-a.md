# Independent whole-repository RC1 review A

Reviewed revision: **378e722797d57b0bae257ca0f7fd2ad8d746547d**.
Checkout: `/workspace/byteplan-rc1-review2-a`.
Evidence directory: `/workspace/byteplan-rc1-evidence/review2-a/`.

## Independent verdict

**Do not approve this frozen revision for RC1.** One confirmed P1 staged-index integrity defect can lose unrelated staged entries after a short filesystem write. Three confirmed P2 reliability/compatibility defects require explicit disposition. No P0 was demonstrated. This report concerns source-native lifecycle functionality; semantic graph and Assignment implementation are deferred.

All findings below were established by reviewer A from this checkout and bounded private fixtures. No source, tracked registry, branch, tag, or PR changes were made in the reviewed checkout. Fixes, task registration and release decisions belong to the coordinating agent/user.

## Findings

### A1 — P1: a short write publishes a truncated Git index and discards recovery state

Location: `src/byteplan/gitwrite.py:385` (unchecked `os.write`), followed by publication at line 389. `reconcile_staged` removes its journal before its final snapshot check.

Trigger: the operating system writes fewer bytes than requested while copying the verified scratch index to the exclusive index lock. Short writes are part of the `os.write` contract, including a filesystem reaching its space limit during a write. The code ignores the returned byte count, fsyncs the partial content and renames it over the original index.

Demonstration: `probe_short_index_write.py` runs the production `reconcile_staged` against a private Git fixture and injects one short index write. The fixture contains a new TODO and an unrelated `user.txt` with different staged and unstaged contents. The 344-byte index is replaced by 172 bytes. Reconciliation later raises `ConfigError` because the index no longer contains `pyproject.toml`; `git show :user.txt` exits 128, while the worktree contains only its different unstaged edits. The staged journal is already absent. On this Git version `ls-files` surprisingly returns 0 while displaying two valid entries and zero-valued garbage entries; its success does not establish index integrity.

Impact: the entire original index, including unrelated partially staged user work, is at risk. The worktree is not a substitute for those staged bytes. BytePlan retains neither the whole original index nor a recovery journal for this completed path. The probe saves an independent `index-before.saved` solely to preserve review evidence; production does not do that.

Evidence: `probe_short_index_write.py`, `probe_short_index_write.log`, `fixture_short_index_final/`. The single injected write reports `(344, 172)`. The script's assertions pass. An earlier exploratory fixture remains separately retained; the final fixture and current script/log are authoritative for this finding.

Bounded fix: write every byte, checking forward progress and handling errors before replacing the real index. A buffered binary writer or a correct write-all loop is suitable. Validate the completed lock content/entries before the swap, and retain rollback material on failure. Add a failure-injection regression with unrelated partial staging, asserting the original complete index survives a short/failed write.

### A2 — P2: anchored release restore duplicates annotations that a hotfix already restored

Locations: `src/byteplan/release.py:411` unconditionally inserts the recorded decorator; lines 413–419 likewise reinsert imports. `src/byteplan/operations/release.py:375` checks AST equivalence after stripping runtime decorators, which cannot detect duplicate runtime annotations, and line 386 schedules the write.

Trigger: release stripping is on record, but a user hotfix/cherry-pick has already put back the original runtime decorator/import before running `restore`.

Demonstration: `probe_restore_duplicate.py` creates an imported task `abcd`, calls `release`, then restores the original decorator/import manually while changing `return 1` to `return 2`. Production `restore()` succeeds with `conflicts=()` and clears the release record. It writes two imports and two identical `@todo("work", id="abcd")` decorators. The next `check()` is blocked by `duplicate_id`.

Impact: a successful supported restore creates ambiguous source identities and makes ordinary scans fail until a user repairs the generated duplicate. The hotfix body and task lifecycle are preserved; this probe does not demonstrate loss of authored code or automatic resolution, so P2 is appropriate.

Evidence: `probe_restore_duplicate.py`, `probe_restore_duplicate.log`, `fixture_restore_duplicate/`.

Bounded fix: inspect the selected declaration/import anchors for a matching or conflicting already-present recorded annotation. Either accept an exactly restored block once or return `restore_conflict` without writing; never append another copy blindly. Validate final source identities/links against the intended restored state before committing. Cover pre-restored identical and competing decorators/imports as well as ordinary changed-file restoration.

### A3 — P2: a narrowed writing scan silently moves a task onto a duplicate copy

Location: `src/byteplan/operations/scan.py:209` diagnoses only selected tags; lines 213–216 consult the remaining namespace only when allocating new untagged tasks. Reconciliation then updates the existing task from the selected copy.

Trigger: registered `a.py` still contains `TODO[abcd]`; a different in-scope `b.py` copies that ID, and a writing scan targets only `b.py`.

Demonstration: `probe_narrow_duplicate.py` imports `a.py`'s "Original task", adds `b.py`'s "Independent copied task", then calls `scan(['b.py'], root, dry_run=False)`. It reports `blocked=False`, no diagnostics, and writes the registry with the task's canonical source/title now pointing to `b.py`. A subsequent full check correctly blocks the duplicate.

Impact: narrowed reconciliation treats ambiguous identity evidence as a legitimate relocation/text edit. Managed status, notes and historical events are not erased in the demonstrated case. This contradicts the broad duplicate-blocking guarantee in README line 827 and the project-unique identity invariant, but has a bounded reliability impact rather than a demonstrated P1 loss.

Evidence: `probe_narrow_duplicate.py`, `probe_narrow_duplicate.log`, `fixture_narrow_duplicate/`.

Compatibility constraint: `tests/test_narrowed_allocation.py:191` intentionally allows a no-allocation narrow scan despite unrelated unparseable files. A blanket mandatory full-scope parse would change that supported behavior.

Bounded fix: at minimum, before moving a selected registered ID from another source path, check whether its prior canonical file still provides the same annotation and block the demonstrated duplicate. Preserve narrow absence rules and tolerance for unrelated parse failures. If broader duplicate detection is deliberately out of scope, explicitly triage the behavior and narrow the public guarantee; do not claim the current narrow scan proves uniqueness project-wide.

### A4 — P2: staged rollback cannot remove newly added entries in SHA-256 Git repositories

Locations: `src/byteplan/gitwrite.py:63` hardcodes a 40-character `ZERO_OID`; line 371 uses it for index deletion. The same module already accepts 64-character real object IDs in serialized journals.

Trigger: a SHA-256 repository needs rollback/recovery of an index entry that did not exist before staged reconciliation, such as a newly generated registry.

Demonstration: `probe_sha256_recovery.py` creates a private `git init --object-format=sha256` repository with staged `pyproject.toml`/`a.py` and no registry. Reconciliation adds the registry to the index. A bounded ordinary worktree-write `OSError` forces rollback. `git update-index` rejects the 40-zero deletion OID as malformed, leaving the new registry indexed while absent from the worktree. The production `gitwrite.recover` call fails identically. The journal is retained and source remains unchanged. A smaller direct `_swap_index` probe establishes the same deletion failure.

Impact: automatic rollback/recovery becomes stuck in a standard Git object format. The journal preserves repair material, so no data loss is demonstrated here. This is a compatibility/recovery P2 requiring either a correction or an explicit, early unsupported-format refusal.

Evidence: `probe_sha256_recovery.py`, `probe_sha256_recovery.log`, `fixture_sha256_recovery/`; supporting `probe_sha256_delete.py` and `.log`.

Bounded fix: derive the null OID width from the repository object format or validated current object identities. Cover forward reconciliation plus forced rollback/recovery of a newly added registry/report entry under SHA-256. An explicit unsupported-format check must happen before any mutation if support is intentionally deferred.

## Scope and assessment of the twelve requested areas

| Area | Assessment and evidence |
|---|---|
| Correctness and edges | Read the scanners, annotation/reconciliation models and ID allocation/lookup. Checked suppression, malformed/dynamic annotations, class/stub heuristics, selected scope, deterministic allocation, missing versus status and idempotence. Cross-format/BOM/CRLF/legacy/long-ID and no-op behavior are exercised by `test_comments`, `test_decorators`, `test_stubs`, `test_formats`, `test_markdown`, `test_json`, `test_write`, `test_narrowed_allocation`, and `test_compatibility`. A3 is the confirmed gap. |
| Source editing and data integrity | Read `annotate`, `edits`, `normalize`, `cleanup`, `release`, source decoders and operation planners. Most source edits have exact-byte baselines, structural checks and scan round trips. The restore path deliberately uses runtime-stripped AST equivalence and lacked a final identity check, producing A2. Existing source safety, normalization, cleanup, scaffold, restore and release tests cover large first scans, unsafe placements, imports, encodings and explicit cleanup. |
| Migration/backward compatibility | Schema v2 is explicit, old schema remains writable without expanded allocation, unknown supported metadata round-trips, and migration is journaled. Reviewed registry serialization, `Project.migrate`, compatibility tests and released-client test implementation. Old binaries are expected to refuse v2; no assertion that they understand expanded annotations under v1. Actual released-client/network tests were not rerun in this review. |
| Task IDs/collisions | Checked six-character allocation, legacy/long validation, exact-first UI prefixes, full persisted references, permanent reservations, full configured reservation scope for narrowed allocation, import/duplicate repair and original-branch collision recovery. Branch repair pins commits, checks all merge bases and lineage, reserves old/new IDs, rewrites supported exact references and retains stale evidence. A3 remains a separate narrowed-observation issue. |
| Git plain/custom merge, concurrency, recovery | Read `merge`, `gitio`, `snapshot`, `gitwrite`, `collisions`, `persistence` and `writeguard`; inspected real-Git migration/evidence/lifecycle matrix tests, staged tests and fault-injection tests. Conservative conflict fallback and parsed-byte transaction hashes are sound within documented race limits. A1 is release-blocking; A4 is a bounded object-format gap. |
| Verification freshness/integrity/resolution authority | Read runner/plugin aggregation, task file fingerprints, provenance validation, readiness, selected-view evidence, placeholders, archive evidence selection and status mutation. Passing evidence is advisory, only `passed` is positive, missing/skip/xfail/error outcomes cannot resolve tasks, and index HEAD freshness stays uncertain. Current canonical evidence wins over cached archived evidence. Inspected evidence-integrity, snapshot and restore-integrity regressions. No new false-verification or automatic-resolution defect demonstrated. |
| Security/untrusted repository input | Checked static scanners versus explicit project-code execution, argv subprocess boundaries, strict authoritative JSON/conflict/duplicate-key handling, serialized journal/restore confinement, protected VCS/control paths, staged selected-index validation, cache aliases/sidecars and permission-scoped MCP recovery. No real external-data probe was used. The documented contract excludes a universal read sandbox and adversarial concurrent path replacement. No additional P0/P1 security finding established independently. |
| CLI/Python API/MCP/Hatch | Read adapters and operation forwarding. Preview/write differences, exception/exit/result semantics, optional MCP dependency, separate registry/source/execution permissions, explicit source apply and read-only Hatch defaults are coherent. Inspected facade identity/pickle/constructor tests, MCP permission/recovery tests, snapshot API tests and Hatch tests. A2 is reachable through API/CLI/MCP restore. |
| Platforms/packaging | Reviewed Python minimums, optional dependencies, scripts/entry points, wheel package selection, sdist exclusion of state/runtime, separate inert runtime distribution, CI matrix and direct-hook shell invocation. Native Linux testing only is claimed locally. A4 covers Git SHA-256; native Windows/macOS and complete interpreter matrix rely on supplied CI evidence, not this machine. Root separately owns frozen artifact build/install identity. |
| Architecture after extraction | Read the facade, canonical result definitions and all operations. Public facade owns selected-view/configuration/transaction/recovery boundaries, operations own orchestration and leaf modules retain algorithms. TYPE_CHECKING-only Project imports avoid runtime cycles; canonical result types preserve public module/pickle identity and sentinel/late commit/allocator boundaries. No competing lifecycle implementation, mixin hierarchy or graph system was introduced. |
| Public stability/documentation | Read README contracts, current compatibility policy, architecture/spec/addenda and active implementation plan, plus source-safety/merge/storage/readiness documentation. Configuration defaults and public identities have executable doc/facade regressions. A3 exposes an overbroad duplicate guarantee. Readiness documentation explicitly remains preparation/pending and contains earlier counts/revisions that must be refreshed before approval; it is not final release evidence. |
| Release readiness | Frozen commit consistency independently passes with only the known informational P3 scaffold placeholder. Existing baseline/CI evidence does not override A1 or dispose of A2–A4. Correct the P1, explicitly triage P2s, retest affected flows and update exact revision/artifact/review evidence before asking for release approval. No tag, publication or approval is performed by this review. |

Production scope includes every `src/byteplan/*.py`, every operation module including common/init, every scanner module, both helper scripts, the custom Hatch example, runtime module, project configuration and workflows. Test review combines the complete test inventory, the explicitly partial ordinary-suite execution, supplied baseline evidence and direct reading of the major identity, migration, merge, transaction, source-write, release, verification, facade, snapshot and MCP regression bodies; it does not claim every test statement was manually audited.

## Execution evidence

- Exact frozen SHA confirmed with `git rev-parse HEAD` and read-only checkout status checks.
- Environment sourced from `/workspace/byteplan-env.sh`; all devtool execution uses absolute `PYTHONPATH=/workspace/byteplan-rc1-review2-a/src` and the prepared Python 3.12 interpreter.
- `dependencies-review2.log` confirms CPython 3.12.14, pytest 9.1.1 and imports of pytest/build/Hatchling/MCP/pathspec before the full run.
- `frozen-check.json` records `byteplan check --commit 378e722797d57b0bae257ca0f7fd2ad8d746547d --format json`: `exit_code: 0`, with only the existing `67a65c` scaffold placeholder information. stderr retained separately.
- `pytest-review2.log` is reviewer A's newly initiated ordinary suite, **deliberately interrupted at the coordinator's instruction once the frozen revision was conclusively blocked**: **786 passed, 3 deselected, 1 xfailed in 856.34 seconds**, then `KeyboardInterrupt`. There were no reported test failures before interruption. This is a partial run, not a full pass; the native Windows-only case was not reached and no new native-platform coverage is claimed. Root retains post-correction full-suite/CI gates.
- The pre-existing `pytest.log` belongs to the interrupted prior attempt and is not represented as this reviewer's new execution. Its supplied result was 1,478 passed / one Linux-native-Windows skip / three network deselections / one P3 xfail.
- All four finding probes execute production code, retain their private fixture state and make assertions. A1/A4 use bounded syscall/worktree-write failure injection, not filesystem exhaustion or external data.
- No network tests, native Windows execution, wheel/sdist build, isolated artifact installation, or external CI fetch was newly performed by A. Supplied CI on code-identical `91c6a4f` and the linked native Windows job are contextual evidence; root owns independent frozen artifact validation.
- Final read-only verification retained in `final-checkout.txt`: HEAD remains the full frozen SHA, and `git diff --stat` / `git status --short` are empty.

## Limitations and independence

This is a bounded code/test/document review, not proof that every possible filesystem, Git, Python dependency or project configuration is safe. The remaining small check/replace race is documented, not newly reported as a defect. Heuristic stub/attachment behavior and deferred graph/Assignment requirements are not release findings simply because they are limited.

Current peer reports/evidence were not opened, and conclusions were not exchanged. A shared process-status command intended to inspect this reviewer's detached pytest process incidentally showed filenames/arguments of a concurrent init-alias probe and root's reproduction command for A2. This was disclosed immediately. No peer evidence was used for a finding; A2 had already been independently proved and reported, and no initialization-alias finding is claimed in this report. Subsequent process inspection avoided shared listings.

This report is an initial independent assessment of the named frozen SHA. Corrections on another revision require affected-flow review and new evidence; this report does not sign off code it has not reviewed.
