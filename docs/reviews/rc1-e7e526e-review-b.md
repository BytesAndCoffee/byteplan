# Independent whole-repository review B2 — RC1

Frozen revision: `e7e526e43c888dcdf6821dd755de3969dd308fa1`.
Checkout: `/workspace/byteplan-rc1-review-b`, detached HEAD, initially clean.
Review date: 2026-10-25 UTC.

This is an initial independent review. I did not consult another reviewer, another reviewer's temporary files, or delegate. I verified HEAD directly and searched for applicable `AGENTS.md`: none existed at `/AGENTS.md`, `/workspace/AGENTS.md`, the checkout root, or among repository files. The managed cloud runtime skill was read; no network or external service work was needed. No tracked file, registry, evidence, branch, commit, tag or publication was changed.

## Disposition

**Unresolved release blockers remain: B2-1 and B2-2 (P1). Do not approve RC1 at this SHA.** B2-3, B2-4 and B2-5 are P2 items requiring explicit triage. No P0 finding. These are code-supported findings; I did not construct or execute security payloads. Existing ordinary regression coverage is extensive, but does not cover the boundaries below.

## Findings

### B2-1 — P1: Serialized restore/recovery paths are accepted as filesystem authority without confinement

Primary location: `src/byteplan/operations/release.py:299–323`. Related sinks: `src/byteplan/persistence.py:238–249`, `:268–285`; `src/byteplan/gitwrite.py:112–120`, `:277–286`, `:348–358`.

`restore()` takes each key of the registry's `release.files` mapping and reads `self.root / path`, then passes the same unvalidated string to `FileWrite`. Registry parsing treats the entire release block as opaque extra data. There is no requirement that the selected path be relative, canonically inside the project, a regular non-symlink Python file, or free of symlink parent components. `persistence.commit()` and `_apply()` also join the root and path without such checks. A registry obtained from another branch or repository therefore crosses from untrusted serialized metadata into write authority outside the project. This also arises without malicious metadata if a previously released source directory is replaced by a symlink before restoration: the recorded source path is followed into the other directory.

AST equivalence and compilation constrain the transformation of the selected Python file; neither constrains which file was selected. Hash checks establish that the chosen bytes match a plan, not that its location is authorized. The same issue exists in ordinary recovery: the journal's target and staged-copy names are used directly, its version and entry structure are not validated, and hashes cannot establish path confinement. Staged recovery additionally accepts its recorded index pathname directly.

Realistic impact is unintended modification of files outside the selected project under the user's filesystem permissions; the auto-recovery entry point makes this reachable from an otherwise ordinary writing command. It contradicts the documented project/symlink boundary. This is static dataflow evidence, not a claim that an exploit was executed.

Bounded correction: validate the whole restore/journal schema before any read, mutation or recovery cleanup; reject unknown versions and duplicate keys; centralize canonical project-target checks (including parent symlinks) at the write boundary; restrict transaction-copy names to the transaction directory. For staged journals, verify that the saved index is an expected index for the current repository/worktree and supported commit mode, rather than trusting an arbitrary saved path. Preserve invalid records and return an actionable domain error. Add benign temporary-project regressions for absolute/escaping paths, a source-parent symlink introduced after release, malformed/future journals and journal copies outside their directory. No external real files are needed for those regressions.

### B2-2 — P1: Registry-only MCP calls can recover source writes without source permission or apply

Locations: `src/byteplan/mcp_server.py:256–278`; `src/byteplan/operations/tasks.py:350–360`; `src/byteplan/api.py:284–297`.

The server registers `set_status`, `resolve`, `edit_task` and test-link mutations when only `registry_write` is enabled. These invoke the ordinary mutation context, which unconditionally rolls forward any pending ordinary transaction before performing the requested registry change. A legitimate interrupted scan/sync/scaffold/release transaction can contain source targets. Consequently a registry-only `set_status`, or `resolve(sync_source=false)`/`resolve(sync_source=true, apply=false)`, finishes those source writes even though source permission is absent and no source apply was requested. An unchanged requested status still enters recovery.

This is a permission-boundary violation in the documented stable MCP contract: README lines 780–790 promise separate source permission and explicit `apply=true`. The prerequisite can be a normal interrupted earlier CLI write; it does not require malformed journal contents or B2-1. Existing crash tests demonstrate the journal roll-forward mechanism; the MCP permission tests only exercise ordinary clean state.

Bounded correction: carry an operation/recovery policy through the MCP-created project and enforce it while holding the project lock. Registry-only and preview requests should refuse a pending transaction that would write source and explain how to finish it through an explicitly authorized source operation. A preflight check outside the lock alone leaves a race. Add a regression using an ordinary simulated interrupted source transaction and an actual MCP registry-only client; assert source bytes and journal bytes remain unchanged until an authorized explicit apply.

### B2-3 — P2: Archive-index loading ignores its version and structural contract

Location: `src/byteplan/archive.py:180–188`; callers include `operations/archive.py:archive_index`, direct archive/restore, and the archive merge driver.

`Index.loads()` parses JSON and converts `data.get("tasks", {})` to a dictionary, but does not inspect `schema_version`, validate task IDs/entry shapes/hash fields, or preserve top-level extension metadata. `dumps()` always emits version 1 with only `tasks`. A valid JSON index with a newer schema is therefore accepted and can be rewritten as version 1, discarding its unknown metadata, by ordinary archive writes or the merge driver. Structurally invalid entries can survive this loader and then fail with raw `AttributeError`/`KeyError` in lookup, scan diagnostics or recovery instead of a controlled format error.

The index selects the canonical archived record by SHA and is committed, so silently normalizing an unsupported format is a meaningful compatibility/integrity gap, even though the full record may remain recoverable from Git/SQLite. A current malformed task container that converts to an empty dict is also accepted as an empty index. Strict registry/evidence loaders already implement the safer pattern.

Bounded correction: validate exact supported index versions and entry structure before exposing entries; fail closed on future versions; preserve same-version unknown fields if additive extension compatibility is intended. Test future versions, invalid task containers/entries and successful merge serialization without discarding supported metadata.

### B2-4 — P2: Narrowed allocation omits already embedded IDs outside its selected targets

Locations: `src/byteplan/operations/scan.py:129–141`, `:209–211`, `:813–828`.

A narrowed scan collects only the selected files, builds `tags` from that scope, and calls `_plan_allocations(tags, registry)` with no `also_used`. The allocator therefore excludes registered/reserved identities and selected-file identities, but not an unregistered embedded identity elsewhere in the configured project scope. If a new allocation's deterministic candidate equals that other identity, the scan writes it and registers it for the selected task; a later full scan discovers the duplicate. The omitted identity is a real possible state after copied annotations, branch work or a partially reconciled registry. Hash collision probability changes frequency, not the missing namespace check.

This is bounded duplicate creation rather than demonstrated data loss. It conflicts with the stated allocation rule in `ids.allocate()` and `docs/rc1-compatibility.md:100–106`, and the planner already has an `also_used` hook for precisely this purpose. Existing narrowed-scan tests establish scope behavior but do not exercise an allocator collision with an unregistered ID elsewhere.

Bounded correction: collect exact embedded IDs across the relevant project scope for allocation reservations without reconciling or marking unselected tasks missing; pass them through `also_used`. Apply the same rule to working-tree and snapshot narrowed scans. A deterministic allocator-collision regression can verify it without searching for random collisions.

### B2-5 — P2: Staged recovery does not verify the bytes of its saved copies

Locations: `src/byteplan/gitwrite.py:277–286`, `:328–338` and `:347–365`.

The staged journal records `before_hash` and `after_hash`, but `_read_copy()` returns saved bytes without checking either. `_write_worktree()` verifies the existing target's before hash and then writes `after_copy` directly; `_restore_file()` similarly writes `before_copy` directly during rollback. If a saved copy is truncated or otherwise corrupted between a crash and recovery, recovery can overwrite a still-valid source file with those corrupt bytes and subsequently delete the journal/copies. It can leave the index containing the validated planned blob while the working tree contains different bytes. Ordinary transaction recovery already rejects a corrupt staged copy (`persistence.py:281–284`), so the staged path lacks an existing integrity invariant.

This is a reliability/data-integrity finding rather than a demonstrated irrecoverable loss: Git's recorded before/after objects generally remain available. Existing staged crash/rollback tests cover foreign target edits but not damaged saved copies.

Bounded correction: verify every needed before/after copy against its recorded hash before applying forward or backward recovery, and retain the journal on a mismatch with an actionable conflict error. Test ordinary truncated scratch copies in a temporary repository for both directions; no external files or adversarial content are needed.

## Whole-repository coverage and conclusions

I inspected the current implementation across every source responsibility, rather than a diff: facade/result types, config/errors/diagnostics, registry/strict JSON/IDs/models, persistence, Git plumbing/snapshots/staged writes/merge/collision recovery, scanner source/comments/decorators/bindings/symbols/stubs/hierarchy/association/Markdown/JSONC, annotation/edit/normalize/cleanup, reconcile, verification/plugin, archive, release/smoke, scaffold, all operation modules, CLI/reporting, Hatch and MCP adapters, runtime/shim and package entry points. I also inspected root/runtime packaging configuration, both workflows, pre-commit configurations, attributes/ignores, both scripts, the custom Hatch example, contribution guidance and release/public-interface documentation. Documentation review was risk-based, using the active release and compatibility documents and relevant README/spec/implementation-plan sections; it was not a line-by-line copy edit of every historical design paragraph. Test coverage was assessed through the existing suite plus selected regression source inspection.

- Source edits use lossless decoding, exact hashes, AST/structure checks and scanner round trips, with substantial BOM/CRLF/Unicode/tab/no-final-newline/idempotence regression coverage. One follow-up audit opportunity is inconsistent `splitlines(keepends=True)` in `release.py:77`, `cleanup.py:250` and `scaffold.py:350` versus `edits.physical_lines`: Python AST lines do not split on all those characters. I have not promoted an unexecuted end-to-end impact hypothesis into a finding; investigate benign form-feed/Unicode-separator source fixtures.
- Current schema-1/2 task handling, explicit journaled migration, exact-before-prefix UI lookup and exact persisted references are coherent. Unsupported registry/evidence schemas and duplicate JSON keys fail visibly. Released 0.1.0/0.2.0 compatibility tests exist, and historical limitations are candidly documented; I did not independently run their network downloads.
- Managed fields and history survive reconciliation; source disappearance and verification never resolve tasks. Semantic merge conservatively rejects competing managed states, creation collisions and rewritten history. Real Git tests cover plain/custom driver, evidence conflicts, migration and branch collision repair. Ordinary Git can still require explicit user conflict resolution, as documented.
- Archive checks committed task and current evidence/run durability in Git. Restore now captures parsed-byte baselines and preserves newer canonical evidence. The previously corrected restore-race/false-green and snapshot-isolation issues are resolved in this code and covered by existing regressions; they are not repeated as findings here. Cross-clone historical evidence recovery and shallow-history/local-SQLite limits remain documented limits.
- Evidence includes fingerprints and complete run provenance; readiness requires linked fresh passes and rejects placeholders/stubs. Head-mode uses source fingerprints as well as repository changes. Results remain advisory and lifecycle resolution stays explicit. Executing project test/build commands is explicitly requested, uses argument lists, and is separate from ordinary static scans.
- The decomposition is cohesive: the 725-line public facade retains public signatures/result identities and delegates to operation modules while algorithms remain in their existing owners. Shared transaction hooks and tested late-bound patch targets remain intact. I found no demonstrated extraction-specific compatibility regression.
- Package/runtime separation and optional MCP/Hatch dependencies are sensible. CI describes Linux/macOS/Windows CPython 3.11–3.14 coverage; configuration alone is not evidence those jobs passed at this frozen SHA. Runtime advertises Python 3.8+ and PyPy metadata is present, but this review only executed Linux CPython 3.12.
- `docs/rc1-readiness.md` intentionally remains pending and contains prior-revision integration status. It must be refreshed with exact reviewed/fixed SHA, both independent dispositions, actual platform results and candidate wheel/sdist hashes/install evidence before approval. Graph/Assignment work remains deferred; existing P3 scaffold formatting task `67a65c` is open and explicitly nonblocking.

## Checks and review limits

Final normal-environment suite: **1210 passed, 3 deselected, 1 xfailed in 197.08 seconds**, exit 0, Linux CPython 3.12.14. Optional MCP integration tests ran in this environment. Command (after sourcing `/workspace/byteplan-env.sh`):

```console
PYTHONPATH=/workspace/byteplan-rc1-review-b/src /workspace/.byteplan-data/hatch/env/virtual/byteplan/vUbTbYbp/hatch-test.py3.12/bin/python -B -m pytest -q -p no:cacheprovider --basetemp=/tmp/byteplan-final-review-b2-suite-scratch
```

Log: `/tmp/byteplan-final-review-b2-suite.log`. The three network-marked cases were deselected by the repository configuration; the known scaffold-formatting placeholder xfailed. Parent Python `-B` prevented parent-import bytecode writes without disabling bytecode for fixture subprocesses. Final `git diff`, `git diff --cached` and `git status --porcelain` were clean, HEAD remained the exact frozen SHA and detached.

Additional completed checks:

- Frozen commit `byteplan check --commit HEAD --format json`: exit 0; only the existing `67a65c` scaffold-placeholder informational diagnostic. Logs: `/tmp/byteplan-final-review-b2-check.json` and `-check.err`.
- Runtime existing tests with the runtime source path: **10 passed** on CPython 3.12.14. Log: `/tmp/byteplan-final-review-b2-runtime.log`.
- Initial core run using the reused types interpreter and global `PYTHONDONTWRITEBYTECODE=1`: **1129 passed, 1 failed, 3 skipped, 2 deselected, 1 xfailed**. The failing `test_stale_on_head` relies on the pytest subprocess creating bytecode/cache dirt in its fixture; disabling bytecode globally changes that fixture. Both it and `test_head_mode_ignores_the_evidence_store` passed on rerun with normal subprocess bytecode behavior (**2 passed**). This is an explained test-environment observation, not a product correctness finding. Logs: `-tests.log`, `-head.log`, `-head-normal.log`.

No exploit payloads or adversarial chains were built or run. No external files were probed for security testing. No new tests were added and no tracked code was edited. No tool/safety action was blocked. I did not run network/released-client downloads, the full platform matrix, PyPy/older runtime interpreters, independent candidate artifact builds/install checks, lint or typing at this revision; the release coordinator must supply those gates. Inspection and the existing suite cannot prove absence of races, hostile-input defects or all platform failures. Recommendations above require confirmation through bounded regressions and affected-area re-review after fixes; release approval remains pending.
