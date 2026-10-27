# RC1 independent whole-repository review gate

**Outcome:** this gate (`a5de5c8`) was not approved. Its findings are corrected in PR #55; see
the [readiness report](rc1-readiness.md). The owner waived a repeat AI review pair for RC1 in
favour of independent human review of the tagged candidate. The protocol below still applies to
future gates.

Reviewers: Codex and Claude, independently.
Release target: `1.0.0rc1`; no tag or publication is authorized by this checkpoint.
Baseline: `2c2b1ae2e38271097d9943155819055e2bf8db82`, after compatibility PR #54.
Tracking: existing BytePlan tasks `c053` (common revision and reviews) and `a70d` (readiness evidence).

## Exact review target

Use the full SHA of the commit that first adds this document. The handoff records that SHA;
it can also be recovered without relying on a moving branch:

```sh
git fetch origin
git log --diff-filter=A -1 --format=%H -- docs/rc1-gate-check.md
git switch --detach <full-gate-sha>
git rev-parse HEAD
```

The history lookup requires the relevant history to be available. In a shallow clone,
fetch the missing history or use the explicit full SHA from the handoff. Verify that the
gate's parent is the baseline listed above before relying on a discovered target.

Both initial reports must identify that same full SHA. Keep the gate revision immutable;
subsequent findings, fixes and review reports belong on follow-up commits or branches.
If main advances, continue examining the pinned gate until a replacement common revision
is explicitly established. Changes that invalidate whole-repository conclusions require
another pair of independent reviews of one new common revision.

## Independent review protocol

Inspect the entire repository at the gate, including inherited code. The gate commit's diff
and a green suite alone cannot establish whole-repository approval. Git does not track file
modification times, so touching files does not expand a commit diff or its review scope.

Record each reviewer's initial findings and verdict separately before consulting the other
reviewer's current conclusions. Existing architecture, implementation plans, public contracts,
tests and historical evidence remain available as repository context. Keep new initial reports
separate until independence has been preserved; do not seed one reviewer with the other's verdict.

Each review should cover:

1. Correctness and edge cases throughout the repository.
2. Source editing, encodings, syntax preservation and data integrity.
3. Registry migrations, version boundaries and backward compatibility.
4. Persistent task identities, reservations, lookup and collision recovery.
5. Git merging, competing writers, locks and transaction recovery.
6. Verification provenance, outcomes, freshness and explicit resolution authority.
7. Untrusted repository inputs, filesystem boundaries and execution permissions.
8. CLI, Python API, MCP, Hatch and Git integrations.
9. Cross-platform behavior, packaging and installed artifacts.
10. Cohesion and supported interfaces after API decomposition.
11. Documentation accuracy and stable/experimental interface classifications.
12. Release readiness, known limits and deferred 1.5/2.0 work.

Classify demonstrated findings as P0/P1 release blockers, P2 concerns requiring explicit
triage, or P3 polish/maintainability/future work. Include source locations, reproducible
triggers, impact and relevant evidence; distinguish confirmed defects from untested risks.
Record actual commands, completed and partial checks, platform skips and coverage limits.
Register confirmed findings through supported BytePlan annotations/APIs and its allocator;
retain evidence and resolve tasks explicitly after corrections. Do not mutate the frozen
checkout to perform fixes or interpret disappearing annotations as resolution.

## Evidence and approval boundaries

Before this gate, PR #54's head `b8cdbc5f6f17632c05118716d48756f39ef483ac` passed
all 15 CI jobs in run `40541039783`, the full local suite (1,742 passed, two skipped), three
explicit network cases, typing, formatting and clean installed wheel/sdist, MCP, Hatch and
runtime checks. Its explicit Windows 3.12 installer-junction regression passed. The baseline
above differs from that tested head only in generated `byteplan.md`.

Those are attributed prior results, not new evidence for this gate's exact artifacts or an
independent release verdict. Run the gate's CI and rebuild/install artifacts from this exact
revision before final readiness approval. Preserve the recorded Linux native-Windows skip;
actual Windows results are separate platform evidence. See the
[correction record](reviews/rc1-review4-corrections.md),
[compatibility policy](compatibility-policy.md) and [Addendum E](spec-addendum-e.md).

Agreement requires neither reviewer to identify an unresolved release blocker. Register and
fix confirmed blockers with regression evidence, repeat affected reviews and replace the
common freeze if material changes invalidate the full reviews. The final readiness report
must state the exact reviewed SHA, dispositions, platform/artifact evidence and remaining
nonblocking/deferred work. Present it for explicit approval; do not tag or publish RC1 automatically.
