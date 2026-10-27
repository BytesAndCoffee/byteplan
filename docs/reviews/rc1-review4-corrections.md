# Corrections to the independent d29ac93 RC1 review

The [frozen review](rc1-d29ac93-codex.md) identified two P1 and two P2 findings.
All four are implemented on this branch and explicitly resolved through BytePlan after
actual linked verification and independent affected-area review. Linux retains a linked
native-Windows skip as `needs_review`; it is not positive platform evidence. This is not a final
whole-repository release approval. The writer-lock change requires a new common review SHA.

## Corrections and compatibility

| Task | Focused commit | Result |
|---|---|---|
| `c6bc7c` (P1) | `322fd6c` | Existing project locks always refuse acquisition; no PID check authorizes unlinking or retrying another writer's lock. The old successful-task-loss schedule now safely refuses both attempts. |
| `e86b8e` (P1) | `0821cb2` | Preflight all metadata and attributes destinations, lexical state identity, parents, existing file types and authority/ancestor overlaps before installation writes. Unsafe known plans leave attributes, outside files and Git configuration unchanged. |
| `9e4d1c` (P2) | `0821cb2` | Encode literal names with Git's attributes glob escaping and C quoting. Actual Git matching and divergent merges work for spaced registry/report filenames; wildcard lookalikes remain unmatched. |
| `668a6c` (P2) | `c0e1cb6` | Unclosed ID brackets produce actionable `malformed_id` diagnostics in Python/Markdown/JSONC comments and supported JSON strings. No identity is guessed or allocated into malformed syntax. |

No registry, evidence, archive or journal schema changes, layout migration, public signature
changes, graph implementation or Assignment functionality are introduced. Four/six/longer
valid IDs, case/prose rules, suppressions, source encodings and lifecycle authority remain intact.
Malformed-ID warnings retain the existing diagnostic/exit policy; they are now visible.

The deliberate compatibility change is lock recovery. Stop all CLI, hook, MCP and build
writers and confirm none is running before removing only a stale `.byteplan/scan.lock`.
Preserve `.byteplan/txn/`, its journal and copies; retry the intended authorized write to
recover. Refusing a dead-looking PID is necessary because it cannot prove ownership of the
pathname at unlink time. Tests cover actual competing transactions, a separate process,
preservation of prior successful work, and interrupted-write recovery after deliberate cleanup.

Installation retains ordinary confined parent aliases and existing attributes bytes, newline
style and custom entries. It adds missing literal rules idempotently; it does not infer which
pre-existing custom rules to remove. This preflight closes known unsafe destinations and
overlapping authorities; it does not promise an atomic transaction across arbitrary Git-config
and filesystem failures, or protection against adversarial concurrent path replacement.

## Regression and independent review evidence

Evidence root: `/workspace/byteplan-rc1-evidence/review4-fixes/`.

- Locking: the two principal new regressions fail the frozen old implementation, including
  actual successful competing commits losing a task. The correction passes 10 focused cases,
  independently rerun as 10 passed. See [the locking review](rc1-review4-lock-correction.md).
- Git installation: the selected old-source regressions produce 12 failures. The new and
  existing merge/report tests pass 86 cases with one native-Windows capability test skipped on
  Linux. Tests use actual `git check-attr`, preserve unrelated rules and bytes, and perform a
  real divergent merge using spaced registry/report filenames.
- Malformed identities: the 40 new cases produce 15 failures and 25 passes on the old source;
  all 167 focused scanner/format cases pass on the correction. A malformed registered task
  retains its identity, open status, reservation and prior history; BOM/CRLF bytes remain intact.
- A separate [Git/scanner correction review](rc1-review4-git-scanner-corrections.md) passes
  65 focused cases with one native-Windows skip, plus the actual spaced-path divergent merge
  under `core.autocrlf=true`. No further confirmed blocker was found in either affected review.
- Supported `Project.scan`, `verify`, `set_status` and `cleanup` register acceptance links,
  record real outcomes (including platform skips), explicitly resolve tasks and only then remove their FIXMEs.
  Post-cleanup verification refreshes the final fingerprints. No outcome is edited manually.
  The final configured run reports 74 passed, one linked native-Windows skip and 28 deselected;
  `e86b8e` therefore remains `needs_review` on Linux despite explicit lifecycle resolution.
- Strict typing passes 123 files; Ruff passes 124 files; wheel/sdist builds pass. All three
  explicit network cases pass, including published older clients and the isolated Hatch build.
- The complete local core suite and new compatibility-PR platform CI are separate validation
  gates. Their final results are recorded when complete; no partial run counts as a full pass.

Native Windows execution is required before claiming the added junction regression passes
there. It is linked to `e86b8e`; Linux records a skip and `needs_review`. The normal CI Windows
matrix executes that capability test. Existing whole-repository
reviews and prior CI remain attributed to their original SHAs.

## Verification follow-up retained honestly

An initial post-cleanup verification recorded a real failure in the separate-process locking
test after earlier passing focused and linked runs. Commit `6aa3494` retains that failed
canonical evidence and the explicit reopening of `c6bc7c`. Its traceback was truncated by the
bounded evidence message, so the original cause is not claimed proven. The same exact Hatch
environment reran that test successfully in 1.22 seconds.

Commit `6f9b723` changes only two test concerns: link the native junction regression so its
Linux skip remains visible, and allow 120 seconds instead of 30 for cold child startup/fsync
under load. The watchdog is not a product performance requirement. Every exclusion, lock-byte,
identity, reservation and journal assertion remains. Independent follow-up reviewed that
reasoning and reran the subprocess case successfully in 3.25 seconds. Fresh linked results
are recorded without altering or relabelling the earlier failure. The final whole-suite run
starts afresh after these refinements; the earlier interrupted broad run is retained as interim.

After integration, freeze one new common SHA for the required independent whole-repository
reviews, then rebuild/install final artifacts and update release readiness. Do not tag or
publish RC1 automatically.
