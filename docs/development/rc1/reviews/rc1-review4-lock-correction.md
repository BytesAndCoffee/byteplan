# Independent review of project-lock correction

Baseline: `d29ac93bbbf57e9216a2c10694b307409399c734`.
Reviewed working tree: `/workspace/byteplan-rc1-review4-fixes`.
Scope: `src/byteplan/persistence.py`, `tests/test_project_lock_integrity.py`, changed stale-lock coverage in `tests/test_write.py`, and lock/recovery changes in README, public compatibility policy and implementation plan.

Verdict: the correction closes the demonstrated stale-lock task-loss defect. No additional blocking finding in this correction's scope. This is a focused correction review, not a final whole-repository verdict or cross-platform CI result.

The old path read a PID, checked liveness, then unlinked the lock pathname and retried. The new existing-lock path only reads diagnostic owner information and raises the existing `LockedError`; it neither removes the existing file nor retries acquisition. PID liveness is no longer treated as writer authority. The exclusive-create path, successful-owner cleanup and public function signature remain. Private `_pid_alive` was removed with no remaining code/test references. No registry/journal format, lifecycle, verification freshness, MCP permission or source-write authority changes are introduced by this locking correction.

The deliberate compatibility change is appropriate and documented: even dead-looking locks now require the operator to stop every CLI/hook/MCP/build writer before removing only the stale marker. Journal and staged-copy authority is preserved for the next authorized write. Windows no longer needs a special liveness exception; all platforms take the same conservative existing-marker branch. Deliberately deleting a live writer's lock contrary to the instructions is not granted by this fix.

## Regression evidence

Independently reran exactly:

```text
PYTHONPATH=/workspace/byteplan-rc1-review4-fixes/src \
/workspace/.byteplan-data/hatch/env/virtual/byteplan/c1S_SeYs/hatch-test.py3.12/bin/python \
-m pytest -q tests/test_project_lock_integrity.py \
tests/test_write.py::test_stale_lock_requires_deliberate_cleanup \
tests/test_write.py::test_lock_held_by_live_process
```

Result: **10 passed in 1.90s**, exit 0, retained in `independent-lock-tests.log`.

The deterministic competing-stale-lock regression preserves the original successful-task-loss schedule: delay only owner inspection and the real atomic target write after its hash check, then perform real journaled commits. It does not fabricate lock, hash or write outcomes. Root's baseline log was inspected: the same scheduler reports both writers committed on the vulnerable implementation; the separate journal-authority test also fails baseline. Fixed behavior refuses both stale-marker attempts before transaction files exist, preserving original registry and lock bytes.

Coverage also includes invalid/empty/zero/negative/dead-looking markers; a real separate process refused while the parent owns the lock, followed by a successful child commit retaining both parent's task and its own task; explicit manual cleanup preserving an interrupted journal and exact CRLF source bytes, then successful idempotent recovery; and actual CLI stale-lock refusal without project mutations followed by deliberate cleanup and ordinary scanning.

The changed old stale-takeover test is a necessary expectation update for the documented behavior change. Its Windows skip was removed, and assertions were strengthened to include error guidance, complete project preservation and successful manual recovery. No passing product behavior was hidden by a new skip or xfail.

## Reviewed file fingerprints

```text
79ca956396f3eeca59a315f39de8c3bb1651443d9c58c87340646b56f74ebd5e  src/byteplan/persistence.py
2b9a56dfd2abb155ec961461fbcff83fa4a926c571207a2a005421c5d75394be  tests/test_project_lock_integrity.py
6bea61a26d9b900c192da7793f32af07d87232a683349d2e4d1850905643042e  tests/test_write.py
47e6ede82530e5db5e5122babaf44287a3f3f1ef24ef4b4ff48252b1cb6f953c  README.md
a2dc69e97231c3f9d81aa4a142678c9376f9a621a586f1f113fb75114892e961  docs/compatibility-policy.md
```

No reviewed source/test/canonical registry file was modified by this reviewer. The review did not read Claude's whole-repository conclusions. Native Windows/macOS execution and broad suite/build/type checks remain root/CI validation responsibilities; this reviewer ran only the focused cases above and sent no process signals during this correction review.

## Follow-up: child-process watchdog tolerance

After the first successful canonical verification and independent 10-case run, a later canonical verification under concurrent full-suite load recorded a real failure in `test_real_process_writer_is_excluded_then_preserves_prior_successful_work` (reported duration 38.568 seconds). The original canonical failure message was truncated; a complete initial traceback was not retained. Root preserved that failure in commit `6aa3494` and `failed-post-cleanup-evidence.json`, and reopened the task rather than treating earlier green runs as overriding it. A same-environment direct rerun then passed. The incomplete original trace does **not** establish that the failure was definitely a timeout; its cause remains incompletely diagnosed.

Reviewed the follow-up test diff: both `subprocess.run` watchdogs change from 30 to the shared `_CHILD_TIMEOUT = 120`, with an explanatory comment. Production behavior is unchanged. All actual safety assertions remain: real child refusal while the parent's lock is held, exact lock-byte preservation, successful subsequent child commit, retention of all task identities/reservations, and absence of leftover lock/journal. The parent retains the lock for the entire refused-child invocation. Increasing the watchdog therefore does not grant a child an opportunity to pass by waiting until the parent unlocks. The subsequent successful child is still required to finish within a finite watchdog. No product performance guarantee was stated at the old 30-second threshold.

This is a reasonable test-environment tolerance change, not independent proof of the original failure's cause. The two child deadlines can consume up to 240 seconds combined, within the reported 300-second verification envelope under ordinary scheduling; heavily loaded environments can still exceed that envelope, so canonical outcomes must remain authoritative and full failure output should be retained.

Independently reran only the exact affected subprocess test using the prepared CPython 3.12 interpreter and absolute fixed-checkout PYTHONPATH. Result: **1 passed in 3.25s**, exit 0; `independent-lock-watchdog-test.log`. Current test-file SHA-256: `ad2e259fb49f5662a0c07737ff6d66dcd7e870b0b27040274758bfb8d8895c6f`. No broad suite or native Windows run was performed by this reviewer for this follow-up. No process signals or rootfile mutations were issued.
