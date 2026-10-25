# Independent final whole-repository RC1 review A — initial conclusions

Reviewed repository: BytesAndCoffee/byteplan.
Frozen SHA: `e7e526e43c888dcdf6821dd755de3969dd308fa1`.
Read-only detached review worktree: `/workspace/byteplan-rc1-review-a`.
HEAD was verified before inspection and again after validation. `git status --porcelain` remained empty. No tracked files, registry records, evidence records, branches, commits, tags or publication were changed. All probes/build artifacts/logs are under `/tmp/byteplan-final-review-a*`.

This is an independent initial review of the integrated repository, not the latest diff. I did not consult the other final reviewer, their report, or their conclusions. No applicable AGENTS.md was found. The compatibility policy, Addendum E, architecture/storage/compatibility documentation were read as requirements and context; prior reports were not treated as proof of implementation correctness.

## Disposition

**RC1 is blocked at the reviewed SHA. Three confirmed P1 findings remain:** recovery can write outside the project from repository-supplied journal paths; registry-only MCP permission can replay source edits; and importing a reappeared archived identity replaces its authoritative task lifecycle/managed fields with a new record. There are three additional P2 findings for staged-copy integrity, narrowed allocation, and archive schema rejection. No P0 was demonstrated. The API extraction itself appears cohesive and its facade/patch boundaries passed the exercised contract tests; that does not cure the inherited cross-operation defects below.

All findings below are demonstrated against the frozen revision. They are not allegations based only on historical reports or stylistic preferences.

## Coverage and validation

Inspected actual implementation across the facade/result types, every operations module, source decoding/edits/annotation, Python/Markdown/JSON scanners, symbol association/stub/binding/hierarchy heuristics, normalization/cleanup, release/restore/smoke, registry/IDs/reconciliation, archive store/index/durability, verification/pytest plugin/freshness, ordinary persistence, Git snapshots/staged writes/merge drivers/collision repair, CLI/reporting/diagnostics/configuration, MCP permissions, Hatch integration, separate runtime distribution, examples, benchmark/report-publishing scripts, workflows/pre-commit hooks and public documentation. Read focused regression tests across these areas and ran the non-network selection available in the reused types interpreter. This was a reduced selection, not the required configured full Hatch suite; the missing `build` dependency caused three entire modules to skip during collection, as detailed below.

Validation used CPython 3.12.14 and absolute `PYTHONPATH=/workspace/byteplan-rc1-review-a/src` with `/workspace/.byteplan-data/hatch/env/virtual/byteplan/vUbTbYbp/types/bin/python`:

- Available non-network selection in the types interpreter: **1130 passed, 3 skipped, 2 deselected, 1 xfailed**, 232.88 seconds. Log: `/tmp/byteplan-final-review-a-tests.log`. The three skips are entire test modules, not three individual test cases. This is not evidence of passing the configured full Hatch suite.
- Additional MCP/released-client selection with default marker policy: **27 passed, 2 deselected**. This exercised MCP; the released-client network cases remained deselected. Log: `/tmp/byteplan-final-review-a-focused.log`.
- Separate runtime package tests: **10 passed**. Log: `/tmp/byteplan-final-review-a-runtime-tests.log`.
- Built wheel and sdist for both `byteplan==1.0.0rc1` and `byteplan-runtime==0.1.0` through Hatchling; artifacts are under `/tmp/byteplan-final-review-a-dist` and `/tmp/byteplan-final-review-a-runtime-dist`.
- Installed both wheels into a new environment, installed the declared pathspec dependency, confirmed imports resolve to that installation, then exercised installed initialization, writing scan, lookup, check, UTF-8 BOM/CRLF preservation, idempotence and inert runtime identity. PASS. Logs: `/tmp/byteplan-final-review-a-install.log`, `/tmp/byteplan-final-review-a-installed-smoke.log`.
- Six adversarial probes: `/tmp/byteplan-final-review-a-probes.py`; output: `/tmp/byteplan-final-review-a-probes.log`. Each creates disposable projects outside the worktree. The MCP probe uses the SDK Client, not a bypass of the tool's registration layer.

Exact command for the 1130-pass run, from `/workspace/byteplan-rc1-review-a`:

```sh
source /workspace/byteplan-env.sh
PYTHONPATH=/workspace/byteplan-rc1-review-a/src /workspace/.byteplan-data/hatch/env/virtual/byteplan/vUbTbYbp/types/bin/python -m pytest -q -p no:cacheprovider > /tmp/byteplan-final-review-a-tests.log 2>&1
```

Follow-up collection-only diagnosis (`--collect-only -q -p no:cacheprovider -rs`, same interpreter/PYTHONPATH) reports `SKIPPED [3] tests/test_hatch_hook.py:30: could not import 'build': No module named 'build'`, with `1131/1133 tests collected (2 deselected)`. The affected modules are:

- `tests/test_hatch_hook.py`: directly calls `pytest.importorskip("build")` at line 30.
- `tests/test_release_guards.py`: imports `build` from `tests.test_hatch_hook` at line 30, triggering that same module-level skip before its own checks.
- `tests/test_stable_review.py`: imports `build` from `tests.test_hatch_hook` at line 30 (and imports the release-guard fixture at line 31), triggering the same skip.

The targeted collection of just these three modules confirms three module-level skips with the identical missing-`build` reason. Diagnostic logs: `/tmp/byteplan-final-review-a-collection.log` and `/tmp/byteplan-final-review-a-skips.log`. The two deselected cases are the explicit network-marked released-client parameter cases under the default `-m 'not network'` policy. The third configured network case, `tests/test_hatch_hook.py::test_isolated_pep517_build`, was never collected because its entire module skipped. Root separately reports the configured Hatch suite at this same product revision passed **1210 ordinary tests plus three network cases and one P3 xfail**; this review did not independently reproduce that configured run. The 80-pass count difference must not be presented as full local Hatch coverage.

Existing checks support lossless BOM/newline edits, AST/scanner round trips, explicit lifecycle resolution, conservative merges/duplicate-key rejection, exact-first UI identity lookup, schema-1 migration guards, task/evidence archive durability, snapshot mutation guards, evidence/run validation and facade delegation. The findings demonstrate important gaps outside those passing regressions.

## P1-A1 — Recovery trusts journal paths and can write outside the project

Locations: `src/byteplan/persistence.py:238` (unvalidated load), `:249`, `:268`, `:281`, `:285` (path use and write). The equivalent staged format also trusts `path`, copy names and `index` at `src/byteplan/gitwrite.py:120`, `:278`, `:297`, `:304`, `:333`.

Trigger: a cloned/untrusted repository contains `.byteplan/txn/journal.json` plus a stage file. Ignored files can still be committed explicitly or delivered in an archive. Set a journal target to `../outside.txt` (or an absolute path), `before=null` for an absent file, and `after` to the supplied payload's hash. Any writing operation automatically runs recovery before its own operation. No project-code execution or source-write request is necessary.

Evidence: the probe creates that journal with even `version=999`, calls the supported `Project.set_status` operation, and observes `ordinary_outside_write: True`. The target was a sibling of the project root. No path containment, symlink boundary, journal-version, allowed-target or strict record-schema check intervened. Existing hashes prove payload consistency, not authorization of its target. This also exposes protected in-repository metadata such as `.git` to crafted targets; the outside-root write alone is reproduced and sufficient for the finding.

Impact: repository metadata can cause arbitrary new-file writes outside the selected project with the caller's permissions during a normal BytePlan mutation. This crosses the documented project-relative write/static-tool safety boundary and is a release-blocking security issue.

Bounded fix: validate the complete journal before any recovery side effect; require the supported version and strict typed/unique entries; reject absolute/traversal/escaping paths, symlink escapes, VCS metadata and transaction self-targets; restrict staged-copy names to regular files owned by the selected transaction directory. Apply equivalent validation to staged journals, including restricting the recorded index to a supported index for this Git worktree. Return an actionable conflict while retaining invalid journals and copies. Add end-to-end regressions for both formats and protected targets.

## P1-A2 — Registry-only MCP permission automatically replays source writes

Locations: `src/byteplan/mcp_server.py:256`–`:261`; shared recovery at `src/byteplan/api.py:284`–`:297`; lifecycle mutation at `src/byteplan/operations/tasks.py` in `mutate`.

Trigger: a legitimate pending ordinary transaction includes a source edit, e.g. after an interrupted CLI scan. Start an MCP server with `Permissions(registry_write=True, source_write=False)`. Call `set_status` (also reachable through the other registry-writing tools). Its Project write context completes all pending source writes before changing the registry.

Evidence: the SDK Client probe writes a well-formed version-1 journal for `a.py`, starts exactly those permissions, and calls `set_status`. Output: `mcp_registry_write_error: False`, `mcp_source_changed: True`. No `apply=true` argument was provided and source-write permission was absent. This finding does not depend on malicious or escaping journal paths.

Impact: the advertised separation between registry-write and source-write permissions is bypassed. A registry-only agent can change project source. This is a release-blocking permission/safety defect, separate from journal path validation.

Bounded fix: make recovery respect the adapter's allowed mutation scope. Registry-only or execution-only MCP operations must fail before side effects when pending recovery would touch source or other unauthorized targets, with guidance to complete it deliberately through an authorized source-writing action. Cover all registry-writing tools and verification's final write context. Do not merely validate paths; a completely valid source transaction reproduces this issue.

## P1-A3 — Repair import recreates an archived identity and discards authoritative state

Location: `src/byteplan/operations/tasks.py:94`–`:108`, especially the active-registry-only existence check and `Observation(..., new=True)`.

Trigger: create a task, add notes/assignee/history, explicitly resolve it, remove its annotation, scan and archive it. Restore the annotation (for example by a Git revert). Run `repair --import ID`/`Project.import_task(ID)` instead of archive restore. The method only checks `registry.tasks`, not the authoritative archive index.

Evidence: the supported API probe archives the task, reintroduces its annotation, then imports it. Output: `archived_import_status: open`, `archived_import_notes_lost: True`, `archived_import_assignee_lost: True`, `archived_import_history: ['created']`. Its prior resolved event and authored state are absent from the new active task. The archive index/cache still selects the old record, creating competing records for one identity; normal lookup now selects the newly created active record. This is not ordinary source-derived refresh of an existing record.

Impact: a documented repair command silently replaces the authoritative meaning/lifecycle of a permanent archived ID and masks its managed work/history. Historical data may still be recoverable, but the operation violates identity/state preservation and serious lifecycle compatibility. Release blocker.

Bounded fix: refuse import for identities present in the archive index and direct the user to `archive --restore ID`, which already preserves the selected record/evidence. Alternatively route through the existing guarded restore transaction without inventing another lifecycle. Add both API/CLI regression coverage with nontrivial metadata/history/evidence and a missing local cache.

## P2-A4 — Staged recovery does not verify the bytes it restores

Locations: `src/byteplan/gitwrite.py:277`–`:286` and `:328`–`:338`.

Trigger: an interrupted staged reconciliation has a damaged `.after` or `.before` copy. The journal hashes still describe the intended original/new bytes, and the target is at a known state. `_write_worktree` reads the copy and writes it without comparing it to `after_hash`; rollback similarly writes `before_copy` without comparing it to `before_hash`.

Evidence: the probe creates a valid journal targeting `a.py` with `index=None` (the supported pre-commit-framework form), a matching original target hash and an intended after hash, but places `CORRUPT RECOVERY BYTES` in the `.after` copy. Public staged recovery reports completed reconciliation, writes the corrupt bytes, then deletes the journal/copies: `staged_corrupt_written: True`, `staged_journal_deleted: True`. Ordinary persistence already verifies stage hashes at `persistence.py:282`; the staged path does not. Source AST/round-trip validation is bypassed on replay.

Impact: an interrupted staged operation can silently replace source with corrupt content and discard its recovery material instead of rejecting the damaged transaction. The repro uses corruption of local transaction material, so classified P2 reliability rather than assuming a spontaneous common-path failure. If journal copy names are attacker controlled, the lack of containment/hash validation also worsens A1.

Bounded fix: verify every required before/after copy's exact hash before index/worktree changes or rollback, using confined regular-file reads. Preserve transaction material and report a domain conflict on missing/corrupt copies. Cover forward and rollback paths, including a multi-entry journal where a later copy is corrupt.

## P2-A5 — Narrowed allocation can reuse an existing source identity outside the target

Locations: `src/byteplan/operations/scan.py:211` and `:813`–`:817`.

Trigger: an existing in-scope annotation outside a narrowed scan contains an ID that is not yet in the registry/reservation ledger (a supported unregistered-ID repair situation). A new annotation inside the narrowed target hashes to that ID. The narrowed scan only passes its selected tags to allocation and does not populate `also_used` from the rest of the source scope.

Evidence: the probe previews `scan(['a.py'])` to obtain its deterministic candidate, puts that exact ID on a preexisting `b.py` annotation, then writes the narrowed scan. Output: `narrow_allocated_existing_source_id: True`, `subsequent_full_scan_blocked: True`. A full scan would have avoided that ID. This directly violates `ids.allocate`'s requirement that `used` contain every ID currently in source. No allocator monkeypatch or manually edited registry is used.

Impact: a successful writing scan introduces an avoidable identity collision and associates a new registry record with an already embedded identity. A subsequent full scan detects the duplicate and blocks; no immediate record overwrite was demonstrated, hence P2.

Bounded fix: collect full configured-scope identities for reservations when a narrowed operation allocates, or require a reconciled full view before writing allocations. Preserve narrowed missing-detection behavior. Include working-tree and snapshot preview coverage, plus unknown IDs outside the selected paths.

## P2-A6 — Archive index ignores unsupported schema versions and drops top-level metadata

Location: `src/byteplan/archive.py:180`–`:188`.

Trigger: read an archive index with an unsupported `schema_version`. `Index.loads` ignores it and consumes `tasks`; any subsequent serialization or semantic merge writes version 1 and discards all other top-level keys. The same archive index is authoritative for selecting canonical archived records.

Evidence: `Index.loads` followed by `dumps` on `{'schema_version': 999, 'tasks': {}, 'future_authority': {'preserve': True}}` succeeds. Probe output: `archive_future_schema_silently_downgraded: True`, `archive_future_metadata_dropped: True`. This is actual implemented acceptance/rewrite behavior; no claim is made that a version-999 producer currently exists. Unlike the task registry/evidence loaders, archive-index loading does not establish a version/type/entry boundary.

Impact: meaningful compatibility risk at the older-client boundary: an older client can silently reinterpret and rewrite an unsupported authoritative index instead of failing safely. Malformed entry shapes also escape the intended domain-error boundary. P2 requires explicit triage; future schema evolution need not be implemented for RC1, but unsupported-version rejection is small and testable.

Bounded fix: enforce the supported archive index schema and validate the task map/required entry fields before use; reject future versions with upgrade/recovery guidance. Preserve recognized same-version opaque extensions if they are within the supported forward-compatibility contract. Test read-only check, restore/archive mutation and the merge driver without changing bytes on rejection.

## Material limits and release recommendation

This review ran locally on Linux/CPython 3.12.14. It did not independently run the configured full Hatch suite, the three skipped Hatch/release/stable-review modules, macOS, Windows, every supported interpreter, the released-client network matrix, strict mypy/formatting, an sdist installation, or remote CI. The reused types interpreter lacked `build`; three entire modules skipped at collection, leaving the reduced 1130-pass selection described above. The one xfail and two network deselections remain as reported. Workflows/configuration for the other gates were inspected; their presence is not a claim that remote gates pass at this SHA. Wheel/sdist builds and installed-wheel behavior were independently checked through separate commands. Root's separately reported configured Hatch results are distinguished from this review's own test evidence. No exhaustive proof of all filesystem races, hostile resource exhaustion, dynamic Python bindings, Git filters or every concurrent interleaving is claimed.

Recommendations: register the six confirmed findings through supported BytePlan operations; fix the three P1 blockers with regressions and run affected-area independent review. Triage each P2 explicitly. Path validation/recovery permission changes cross persistence, Git and adapters, so determine whether the resulting integrated corrections materially invalidate these whole-repository conclusions and require two new same-SHA reviews under Addendum E. Do not tag or publish from this disposition. The frozen revision is **not ready for RC1 approval**.
