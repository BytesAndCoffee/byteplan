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
| `62edd5` | P1 | A1, B2-1 | Confine commit, ordinary/staged recovery and serialized release-restore targets; validate journal schema, copy names and supported index identity before side effects. Retain invalid recovery material. | Accepted; in progress. |
| `81cc04` | P1 | A2, B2-2 | Enforce operation-specific MCP recovery authority under the project lock. Source recovery requires source permission and an explicit meaningful apply; metadata-only recovery may retain its supported scope. | Accepted; in progress. |
| `38e8db` | P1 | A3 | Reject repair import of an archived identity and direct to guarded archive restore, preserving lifecycle, managed history and evidence. | Accepted; in progress. |
| `dcd417` | P2 | A4, B2-5 | Validate every required forward/rollback staged copy hash before any worktree/index or direction changes; preserve damaged material on rejection. | Accepted for RC1; in progress. |
| `3d5bb4` | P2 | A5, B2-4 | Reserve embedded identities across the full configured scope during narrowed allocation, without reconciling outside-target tasks or changing missing detection. | Accepted for RC1; in progress. |
| `765f23` | P2 | A6, B2-3 | Validate archive-index version and record shape, reject unsupported formats safely and preserve supported same-version opaque metadata through serialization and merge. | Accepted for RC1; in progress. |

All six identities were allocated by BytePlan from appropriate source FIXMEs and registered
through supported APIs, with `release:1.0` labels and explicit in-progress lifecycle events.
Acceptance placeholders identify unimplemented obligations; they are not passing verification.
Real linked regressions and explicit resolution are required for each completed correction.

## Evidence limits and release gates

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
