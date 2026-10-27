# RC1 initial whole-repository review findings

> This is a record of the review rounds at `e7e526e` and `378e722`; statements such as "pending"
> describe that time. For the current state, see the [readiness report](rc1-readiness.md).

Both initial independent reviews examined exactly
`e7e526e43c888dcdf6821dd755de3969dd308fa1`. Their conclusions were formed separately.
That revision is **not ready for RC1 approval**: three P1 defects are confirmed and all three
P2 findings below are accepted for correction before RC1. No tag or package is published.

The original reports remain available as [review A](reviews/rc1-e7e526e-review-a.md) and
[review B](reviews/rc1-e7e526e-review-b.md). An earlier B attempt was interrupted before a report
and is not counted. Completed review B uses a fresh independent assessment, defensive code
inspection and ordinary regression tests.

| BytePlan task | Severity | Independent findings | Required correction | Disposition |
|---|---|---|---|---|
| `62edd5` | P1 | A1, B2-1; control-alias follow-up | Confine commit, ordinary/staged recovery and serialized release-restore targets; validate journal schema, copy names and supported index identity before side effects. Reject control-directory aliases including junctions. Retain invalid recovery material. | Implementation explicitly resolved; portable evidence passes, native Windows CI remains a merge gate. |
| `81cc04` | P1 | A2, B2-2 | Enforce operation-specific MCP recovery authority under the project lock. Source recovery requires source permission and an explicit meaningful apply; metadata-only recovery may retain its supported scope. | Implemented; explicitly resolved with fresh linked evidence. |
| `38e8db` | P1 | A3 | Reject repair import of an archived identity and direct to guarded archive restore, preserving lifecycle, managed history and evidence. | Implemented; explicitly resolved with fresh linked evidence. |
| `dcd417` | P2 | A4, B2-5 | Validate every required forward/rollback staged copy hash before any worktree/index or direction changes; preserve damaged material on rejection. | Implemented; explicitly resolved with fresh linked evidence. |
| `3d5bb4` | P2 | A5, B2-4 | Reserve embedded identities across the full configured scope during narrowed allocation, without reconciling outside-target tasks or changing missing detection. | Implemented; explicitly resolved with fresh linked evidence. |
| `765f23` | P2 | A6, B2-3 | Validate archive-index version and record shape, reject unsupported formats safely and preserve supported same-version opaque metadata through serialization and merge. | Implemented; explicitly resolved with fresh linked evidence. |
| `cda4d1` | P1 | Independent cache-boundary follow-up | Bind Project archive stores to the actual project root; validate the SQLite database, directory and implicit sidecars before opening, including hardlink rejection. | Implemented; explicitly resolved with fresh linked evidence. |

All seven identities were allocated by BytePlan from appropriate source FIXMEs and registered
through supported APIs, with `release:1.0` labels and explicit in-progress lifecycle events.
The initial acceptance placeholders were replaced by real linked regressions. After passing
evidence and independent correction review, each task was explicitly resolved and its source
FIXME removed through BytePlan cleanup. The original six-task checkpoint had fresh passing
evidence; `62edd5` was subsequently reopened for the control-alias follow-up and explicitly
resolved after correction and independent portable verification. Its new automated record
honestly remains `needs_review` because the native Windows case is skipped on Linux. A separate
Windows CI step must execute that case and report a pass before merge; a successful skipped
step is insufficient. `cda4d1` has fresh passing linked evidence. This implementation disposition
does not approve RC1: the post-cleanup full suite, exact-head platform CI and two new
whole-repository reviews remain release gates.

## Evidence limits and release gates

Independent review of the combined correction identified one incomplete staged-journal
invariant, P2-I1: original object identity, original fingerprint and original copy must agree
on whether the file existed. It remains part of task `62edd5`, not a duplicate obligation.
The parser now requires all three present or all absent. Twelve real produced-plan cases cover
both recovery directions and all six inconsistent combinations; the independent reproduction
now rejects with the index, worktree, journal and copies retained. The original finding and
its verified disposition remain in the correction-review evidence. Earlier pre-amendment
test runs are explicitly interim; the corrected full-suite run is a separate release gate.

The first combined suite also exposed an old scaffold fixture assumption: it expected an
allocation to proceed while another configured file already had an unknown encoding. That is
incompatible with reserving the complete identity universe. Production validation was retained.
The existing scaffold test now introduces undecodability at the post-scan scaffold boundary,
retaining every original assertion and adding the exact decoder error and byte-preservation
checks. Separate preview/write cases require an initially unknown-codec source to block all
writes. Independent boundary verification passed all nine relevant cases; the complete
scaffold/allocation selection passed 67 cases with the existing P3 xfail. No assertion or
source-safety check was removed to obtain that result.

## Compatibility and recovery procedure

The control-directory follow-up demonstrated that an in-project alias reporting
`is_symlink=False` could redirect no-journal cleanup into unrelated project files. Both control
guards now require lexical and resolved identity for every component. Portable regressions and
an independent real-filesystem fixture model that junction distinction and preserve the entire
tree on rejection. Ordinary confined source-parent aliases remain supported. Native Windows
execution is a separate CI gate, not a claimed local result.

The cache follow-up demonstrated that a fresh archived-task lookup could open an aliased
SQLite database and create BytePlan tables in an unrelated database; a hardlink fixture also
demonstrated mutation. Project-owned stores now retain the actual project root. The state
directory, database and rollback-journal/WAL/SHM paths are checked before directory creation,
connection or DDL. Aliases, nonregular paths and multiply linked SQLite files fail with an
actionable configuration error. Legitimate standalone stores, legacy migration and live WAL
remain covered by passing regressions. These checks establish the boundary before opening;
they do not promise descriptor-based protection against concurrent adversarial path replacement.

Well-formed task registries, archive indexes and journals retain their existing versions:
task schema 2, archive-index schema 1, and ordinary/staged journal version 1. Existing legacy
IDs and valid minimal archive entries remain supported. No storage migration is introduced.
The earlier schema-1 task-registry upgrade procedure and released-client matrix are unchanged.

Previously tolerated malformed/future control data now fails explicitly. Preserve the journal
and copies when investigating a rejection; do not lower schema numbers or overwrite hashes to
force recovery. Restore the original valid transaction material or use a compatible client.
Staged recovery accepts the selected Git index and supported commit/worktree contexts; a
discarded legacy alternate index takes the established worktree rollback path without
opening or recreating that missing index. Unrecognized existing index aliases are refused.

Source targets must be canonical project-relative paths. Escaping or protected paths and
nonregular targets are rejected; transaction controls cannot use filesystem aliases. Atomic
replacement retains file modes, ordinary creation umask and Windows binary bytes while
allocating an exclusive random temporary file. Deliberate Git index/worktree differences
remain possible; these guards do not automatically stage a user's later worktree edits.

The coordinator's configured candidate suite passed 1,210 ordinary tests and all three explicit
network checks before these findings, with one existing P3 xfail. Review B independently passed
the configured 1,210-test non-network selection. Review A's reused types environment lacked
`build`, so three entire modules were skipped and its 1,130-pass selection is a reduced run;
the report records the exact command and limitation. Neither result disproves the confirmed
boundary defects. Both runtime selections passed 10 tests.

Named initial artifacts also passed installation/MCP/Hatch checks, but remain unapproved because
their source revision has release blockers. Corrected source requires a new artifact build and
new recorded hashes; the initial artifact evidence must not be presented as testing later code.

These changes cross shared persistence and adapter boundaries. After their dedicated
compatibility PR is integrated and platform checks pass, freeze a new common SHA and repeat
both independent whole-repository reviews. Preserve these initial reports and record findings,
regressions, verification evidence and dispositions rather than replacing the blocked result
with a later green claim. The final readiness report remains pending.

No graph, Assignment, storage redesign or unrelated product feature is authorized by this
hardening increment. The existing scaffold-formatting P3 `67a65c` remains a separately tracked
nonblocking issue.

## Second independent whole-repository review: 378e722

Both new independent initial assessments reviewed exactly
`378e722797d57b0bae257ca0f7fd2ad8d746547d`, after PR #49 integration and generated-report
settlement. Their complete original reports are preserved as
[review A](reviews/rc1-378e722-review-a.md) and
[review B](reviews/rc1-378e722-review-b.md). This revision is **not ready for RC1 approval**.

| BytePlan task | Severity | Independent findings | Accepted correction | Disposition |
|---|---|---|---|---|
| `12ce1c` | P1 | B1 | Preflight initialization targets before any side effects; reject external state-directory aliases and unsafe configuration/registry/shim targets. | Implemented; explicitly resolved after independent correction review and full combined validation. |
| `17f1f0` | P1 | A1 | Complete and validate index-lock bytes before publishing a staged Git index; preserve unrelated staged entries and recovery authority on failure. | Implemented; explicitly resolved after independent correction review and full combined validation. |
| `631761` | P2 | A2 | Reuse matching already-restored annotations/imports or retain an explicit recoverable conflict; never introduce duplicate task IDs during restore. | Accepted before RC1; implemented and explicitly resolved after independent correction review and full combined validation. |
| `d78b89` | P2 | A3, B2 | Reject duplicate identity evidence before narrowed task relocation or allocation writes, preserving configured scope and narrowed absence/parse behavior. | Accepted before RC1; implemented and explicitly resolved after independent correction review and full combined validation. |
| `28e56f` | P2 | A4 | Use the actual Git repository object format for null deletion IDs, including SHA-256 rollback and recovery. | Accepted before RC1; implemented and explicitly resolved after independent correction review and full combined validation. |

All five identities were allocated through supported BytePlan scanning from appropriate source
FIXMEs, labelled `release:1.0` and explicitly placed in progress. No task is complete merely
because a regression passes. Implementation, linked verification, explicit resolution,
independent correction review and final platform/artifact gates remain separate.

The initialization evidence demonstrates constrained fixed-file creation outside the selected
root, not arbitrary overwrite. That still violates the write-authority guarantee and is a P1
release blocker. Initial root triage based on its limited extent is preserved in task history;
the accepted severity is P1. The staged-index finding uses legal short-write fault injection
in a private fixture and demonstrates loss of an unrelated staged entry; it does not claim a
real disk-exhaustion event. SHA-256 recovery retains its journal and unchanged source but cannot
complete. The restore and narrowed-identity fixtures retain authored lifecycle/history; their
bounded correctness impact warrants P2 and explicit pre-RC acceptance.

Review A's redundant broad attempt was explicitly interrupted after 786 passes, three network
deselections and one xfail. Review B's interrupted attempt reported 275 passes, three network
deselections and one xfail. Neither is a full-suite pass. Their complete code assessments and
bounded proofs establish the findings; successful focused checks and root's earlier completed
full/platform runs remain distinct evidence. Review A transparently records incidental shared
process-argument metadata exposure; it used no peer report or conclusions for its findings.
Neither reviewer's conclusions were supplied to the other before its initial report.

Clean `378e722` artifacts passed independent installed wheel/sdist, CLI/API, MCP, isolated Hatch
and runtime checks. Those results do not disprove the defects and do not validate later source.
The corrections require the complete post-correction suite, exact-head platform CI, independent
review and a new integrated freeze with appropriate review/artifact evidence before approval.

The initialization, narrowed-identity and Git-index implementations now have clear independent
correction checks. Initialization also rejects descendants of the reserved `scan.lock` path;
the independent recheck covers complete fixture preservation and valid lookalike paths.
The restored-annotation correction includes a further literal-preservation regression: moving
a declaration must not change multiline string values inside its decorators. The final
token-aware transform has an AST postcondition and a recoverable-conflict path. Its independent
recheck passes both original fixtures, sixteen literal-move cases, encoding and retry cases.

The compatibility boundaries are deliberate. Narrowed scans without allocation retain
unrelated-parse tolerance and validate prior canonical ownership, rather than claiming global
uniqueness. Allocation already requires the complete configured identity namespace and now
diagnoses duplicates in that view. Restoring task identities checks configured sources for
copies; unrelated unreadable or unparseable sources yield explicit `restore_conflict` and
retain restoration authority. Valid existing imports/decorators are reused without duplication;
competing blocks or transformations that change annotation semantics retain a conflict.

These checks require no registry schema or storage migration. Existing valid schema-2 data,
four-character and expanded identities, SHA-1 indexes and supported index selections remain
supported. SHA-256 index deletion/recovery now uses the actual repository object format.
The complete combined validation and exact-head platform CI remain pending; implementation
and independent correction evidence are not an RC1 approval.

Final combined checks passed on the frozen correction: **1,632 passed**, one native-Windows
skip on Linux, three network deselections and the existing P3 scaffold xfail. All three
explicit network cases passed separately. Core strict typing passed 120 files and lint/format
passed 121 files. Runtime passed ten tests, typing and formatting; both distributions build.
Production, test, script and configuration hashes were unchanged during the final run.
An earlier interrupted run predates the last one-line warning-wrapper correction and remains
explicitly interim, including its interruption/teardown output; it is not a green final run.

Independent correction reports are retained for [initialization/narrowing](reviews/rc1-review3-init-correction.md),
[Git indexes](reviews/rc1-review3-git-correction.md) and
[restore semantics](reviews/rc1-review3-restore-correction.md). The five implementations were
explicitly resolved before source cleanup. Fresh linked verification after cleanup passes for all five new corrections and affected
existing tasks. The existing `62edd5` Linux record retains its native-Windows skip honestly;
actual execution of that case in new exact-head Windows CI remains mandatory. No release is
approved or published.

### Windows verification follow-up

PR #50's initial head `4cf857b` passed Linux/macOS but failed new Windows test fixtures.
The Git helper decoded command output in universal-newline text mode, then compared re-encoded
LF data with a real CRLF source file. Independent portable reproduction with `core.autocrlf=true`
produced the same fourteen failures. The corrected tests read raw Git blob bytes with an
explicit selected index and verify exact per-view bytes under both LF and CRLF attributes,
retaining unrelated staged/unstaged data, modes and rollback assertions.

Ten restore assertions also decoded UTF-8 fixtures using Windows' default cp1252. Portable
emulation reproduced all ten failures; explicit UTF-8 assertion reads preserve all original
AST, literal, description and source assertions. Latin-1/CRLF byte coverage remains intact.
A module-local fixture now exercises the Windows decoding default on every host, with teardown
and explicit-encoding forwarding independently checked. No production decoding or Git-write
regression was demonstrated, and no production code was changed for this follow-up.

The [independent fixture review](reviews/rc1-review3-windows-fixtures.md) passed 139 complete
corrected cases and reproduced both original failure sets. The failed Windows run and earlier
successful source checks remain separate evidence. Fresh linked verification and all fifteen
new-head platform checks, including actual native Windows junction execution, are required.
