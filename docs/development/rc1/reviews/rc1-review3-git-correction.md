# Independent final Git correction review

Date: 2026-10-27 UTC. Reviewer: independent Git review agent. Scope: tasks 17f1f0 (P1 short index writes) and 28e56f (P2 SHA256 recovery), checkout `/workspace/byteplan-rc1-review3-fixes`, HEAD `378e722797d57b0bae257ca0f7fd2ad8d746547d` plus the uncommitted corrections reviewed below.

**Disposition: no blocker found in these two corrections.** The original short-write index-loss and SHA256 deletion/recovery defects are corrected in the reviewed bytes. This is a scoped result, not RC1/full-suite/platform approval.

## Exact reviewed bytes

Both initial and final SHA256 readings matched:

- `src/byteplan/gitwrite.py`: `a22da404ecfd4a128d5c119fa190768ec9e6193a43d9b7329f134cb75d83bc49`
- `tests/test_gitwrite.py`: `ea54b7a7f270ccaf6bf83b1ec8f7164b4bb987126f7e2f75c62db4f20bc7985a`

Only these Git files were treated as frozen. A separate writer was actively correcting restore code; the whole worktree was not frozen. No checkout source, generated files, documentation, registry, Git state, task resolutions, or PR were modified by this reviewer. New files and private Git fixtures are confined to this external evidence directory. Private fixture Git init/add/commit/worktree operations are probe setup, not checkout mutations.

Prior context read: `docs/reviews/rc1-378e722-review-a.md`, external `review2-a/probe_short_index_write.py`, `probe_sha256_recovery.py`, and correction author `review3-fixes/git-index/report.md`. The old probes assert the original buggy outcome, so they were inspected and replaced with independent positive probes below rather than rerun in place.

## Inspection findings

The single `_swap_index` implementation serves initial application, forward recovery, and rollback. It acquires the selected index's exclusive `.lock` before checking expected entries and the optional worktree precheck; copies the whole original index to scratch; updates and validates requested scratch entries; drains short writes through a memoryview; retries `InterruptedError`; rejects nonpositive progress; fsyncs/closes; compares the entire completed lock with the Git-generated scratch; and only then replaces the index. Complete-byte verification protects unrelated staged entries and detects positive but dishonest counts/content. Exceptions and KeyboardInterrupt before publication retain original index bytes and clean the owned lock and scratch. A pre-existing lock is never removed.

`_apply` and recovery retain their original project lock, validated index authority/copy set, foreign-entry checks, and rollback journal behavior. A clean pre-publication failure can safely roll back/delete its journal because the index and worktree remain original; if recovery is still required, retained plans can complete later. Independent probes explicitly exercised retained journal completion and a failed rollback publication followed by production recovery.

Deletion uses repository `rev-parse --show-object-format=storage`, mapping SHA1 to 40 zeroes and SHA256 to 64. The object database, including alternate indexes and linked worktrees, is the appropriate authority. Unsupported formats fail before publication. Existing index path/authority validation remains unchanged.

The corrected tests' DIRC-header selector genuinely reaches the raw index descriptor: Git update-index's stdin begins index-info records, not a DIRC binary header. The fault tests call `_swap_index` directly, so fsync/replace injections reach index publication. The author's initial pipe-targeting harness was superseded. Independent probes below instead identify the descriptor by matching `os.fstat(fd)` device/inode to the selected `.lock`, independently confirming the fault target and avoiding Git's pipe descriptors entirely.

## Independent execution

Environment: Linux, Git 2.52.0, prepared Python 3.12 environment. All commands used `source /workspace/byteplan-env.sh` and absolute `PYTHONPATH=/workspace/byteplan-rc1-review3-fixes/src`. Interpreter:

`/workspace/.byteplan-data/hatch/env/virtual/byteplan/c1S_SeYs/hatch-test.py3.12/bin/python`

1. Cwd `/workspace/byteplan-rc1-review3-fixes`:

   `PYTHONPATH=/workspace/byteplan-rc1-review3-fixes/src /workspace/.byteplan-data/hatch/env/virtual/byteplan/c1S_SeYs/hatch-test.py3.12/bin/python -m pytest tests/test_gitwrite.py tests/test_staged_apply.py tests/test_merge.py tests/test_merge_integrity.py tests/test_rc1_merge_acceptance.py tests/test_git_snapshot.py -q -ra --basetemp=/workspace/byteplan-rc1-evidence/review3-fixes/independent-git-final/pytest-fixtures`

   **231 passed in 274.51s; exit 0**, no skips/failures. Log: `pytest.log`. Includes the author's 24 real-Git SHA1/SHA256 forward/rollback/recovery matrix, seven publication faults, short/EINTR regressions, malformed recovery authority, linked/selected indexes, overlapping reconciliation serialization, concurrent editor preservation, staged apply/merge/snapshot regressions.

2. Each private script was run with that same absolute PYTHONPATH and interpreter, redirecting stdout/stderr to its matching `.log`:

   - `/workspace/byteplan-rc1-evidence/review3-fixes/independent-git-final/probe.py`: **72 passed; exit 0**. SHA1/SHA256 × default/alternate/linked × short, EINTR, zero, short-then-zero, negative count, OSError, short-then-OSError, KeyboardInterrupt, successful-count corrupted contents, overreported count with partial contents, fsync failure, replace failure. Every injected write is confirmed against the actual selected index lock inode. Failure cases compare the exact whole original index and private non-Git file snapshot, including journal/copies; all cases assert cleanup, production forward recovery, executable staged unrelated entry, separate unstaged bytes, source index/worktree identity, and alternate/main-worktree index isolation. Log: `probe.log`.
   - `/workspace/byteplan-rc1-evidence/review3-fixes/independent-git-final/probe_lock.py`: **8 passed; exit 0**. SHA1/SHA256 × pre-existing lock ownership, stale expected target preserves concurrent staging, precheck executes under lock and cleans up on abort, unsupported future object format preserves original index. Log: `probe_lock.log`.
   - `/workspace/byteplan-rc1-evidence/review3-fixes/independent-git-final/probe_rollback.py`: **6 passed; exit 0**. SHA1/SHA256 × default/alternate/linked. Force original source-write failure and then failed rollback publication; confirm rollback journal retained and newly generated registry still indexed; production `recover` must remove that registry with the correct null OID width, restore original stage entries/source, preserve unrelated staged/unstaged user bytes, and remove the completed journal. Log: `probe_rollback.log`.

3. Cwd checkout: `git diff --check -- src/byteplan/gitwrite.py tests/test_gitwrite.py`: **exit 0**.

Private probe script SHA256 identities:

- `probe.py`: `1fa51960c77db0ddc1c099c8c4d8cf98732a9249954713071dc6af0dac8cdbc3`
- `probe_lock.py`: `af6530c7e5391b215cdef41bc173f5cc67d66e04fad65654062fd95f8d068dbb`
- `probe_rollback.py`: `3c4f9129e43b1ebd9d0682c4343e72861c57661ccb7e018cf438606d1e015a03`

## Limits

Deterministic benign fault injection and real local Git fixtures establish the stated exception/recovery behavior. They do not simulate real disk exhaustion, power loss, kill -9, Windows filesystems, or hostile concurrent lock/path replacement. Windows O_BINARY is preserved by inspection. Close/unlink failure and directory-fsync durability are not new guarantees claimed by these corrections. Full suite, platform CI, final task resolution, and PR ownership remain with the root agent. No new blocker was established in scope.
