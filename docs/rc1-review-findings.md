# RC1 initial whole-repository review findings

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
| `62edd5` | P1 | A1, B2-1 | Confine commit, ordinary/staged recovery and serialized release-restore targets; validate journal schema, copy names and supported index identity before side effects. Retain invalid recovery material. | Implemented; explicitly resolved with fresh linked evidence. |
| `81cc04` | P1 | A2, B2-2 | Enforce operation-specific MCP recovery authority under the project lock. Source recovery requires source permission and an explicit meaningful apply; metadata-only recovery may retain its supported scope. | Implemented; explicitly resolved with fresh linked evidence. |
| `38e8db` | P1 | A3 | Reject repair import of an archived identity and direct to guarded archive restore, preserving lifecycle, managed history and evidence. | Implemented; explicitly resolved with fresh linked evidence. |
| `dcd417` | P2 | A4, B2-5 | Validate every required forward/rollback staged copy hash before any worktree/index or direction changes; preserve damaged material on rejection. | Implemented; explicitly resolved with fresh linked evidence. |
| `3d5bb4` | P2 | A5, B2-4 | Reserve embedded identities across the full configured scope during narrowed allocation, without reconciling outside-target tasks or changing missing detection. | Implemented; explicitly resolved with fresh linked evidence. |
| `765f23` | P2 | A6, B2-3 | Validate archive-index version and record shape, reject unsupported formats safely and preserve supported same-version opaque metadata through serialization and merge. | Implemented; explicitly resolved with fresh linked evidence. |

All six identities were allocated by BytePlan from appropriate source FIXMEs and registered
through supported APIs, with `release:1.0` labels and explicit in-progress lifecycle events.
The initial acceptance placeholders were replaced by real linked regressions. After passing
evidence and independent correction review, each task was explicitly resolved and its source
FIXME removed through BytePlan cleanup. A fresh verification run after cleanup reports all six
`ready_for_review`. This implementation disposition does not approve RC1: the post-cleanup full
suite, exact-head platform CI and two new whole-repository reviews remain release gates.

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
nonregular targets are rejected; transaction controls cannot use symlink aliases. Atomic
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
