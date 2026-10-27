# Codex independent whole-repository RC1 gate review

Review target: `a5de5c861382a61cf2ca38c093e8268f401f82c3`.
Read-only detached checkout: `/workspace/byteplan-codex-gate-review`.

This report records Codex's initial conclusions without reading Claude's current gate
review. The persistence, source-safety and interface inspections are parts of this one
Codex repository-wide review; they are not the second independent whole-repository review.
The gate remains immutable. This report and its task registrations are follow-up records.

Initial disposition: changes required for the confirmed P2 concerns below. No confirmed
P0/P1 finding has been identified so far. Validation is still running; this draft is not
release approval and does not claim agreement with Claude.

## Confirmed findings

### P2 — Scaffold generated imports can collide with existing module bindings

<!-- FIXME[515d45]: Refuse or safely alias scaffold-generated pytest/runtime bindings when existing test-module bindings make generated code unsafe. -->

Location: `src/byteplan/scaffold.py:341-357`, generated imports at `required_imports`
and decorators/body at `render`.

A valid target file containing `pytest = 7` (or a helper `def pytest(): return 7`)
and an existing passing test is accepted by `Project.scaffold_test(...,
policy="xfail", link_style="managed")`. BytePlan writes `import pytest` in the leading
import block and appends `@pytest.mark.xfail(...)`. The later existing binding still
shadows that import when the appended decorator executes. The operation reports success,
but pytest then fails collection for the entire module with `AttributeError`.

Both variants were reproduced with supported initialization, allocated task identities,
real API source writes and actual pytest subprocesses: one existing test passed before;
after successful scaffolding pytest exited 2 during collection. The AST-only additive
guard preserves existing syntax but misses the name-resolution failure. This is a
reversible, user-requested source-editing defect, not demonstrated task loss or a P1.

Before writing, refuse conflicting generated bindings with actionable guidance, or
select safe aliases and render all generated uses consistently. Cover module assignments,
definitions, aliases and relevant conditional/shadowed imports without executing project
code. Preserve existing bindings, tests, encodings, newlines and transactional behavior.

### P2 — Windows verification timeout can wait indefinitely for a wrapper's descendant

<!-- FIXME[6698e7]: Bound verification timeout cleanup and terminate supported Windows runner descendants so inherited output pipes cannot keep verify blocked. -->

Location: `src/byteplan/verification.py:197-214`.

On timeout, `run_tests` kills the runner then calls `communicate()` without a timeout.
The Windows branch kills only the runner, unlike the POSIX process-group path. A
supported wrapper runner such as Hatch can start pytest with the inherited output pipe;
killing the wrapper leaves its child running and the pipe open. The second communicate
therefore waits for the child, potentially forever, beyond `tests.timeout`. CLI/MCP
verification can remain blocked and project tests keep executing after the configured
deadline. No false evidence or registry corruption is asserted.

A Linux branch-isolation reproduction replaced only `verification.sys` with a proxy
selecting `win32`; actual subprocess launch, inherited pipes, timeout, kill and reads
were exercised. A wrapper-start handshake excluded the pre-spawn race, and an actual
kill timestamp separated startup time from post-kill waiting. For a 0.2-second timeout,
the final run spent 3.361 seconds after killing the wrapper while its three-second
descendant retained the output pipe. This confirms the algorithmic branch defect;
it is not a native Windows execution claim. Native Windows wrapper/descendant regression
coverage is required with the correction. Earlier exploratory runs and one failed
pre-handshake assertion are retained separately, not represented as passing tests.

Terminate the supported runner tree on Windows and bound post-timeout cleanup even if
a descendant retains a pipe. Preserve completed outcomes, classify unfinished requests
as timeout and avoid orphan test processes. Test both direct pytest and wrapper runners.

### P2 — Live filesystem aliases can change a staged or committed snapshot check

<!-- FIXME[26756c]: Resolve snapshot registry and generated-report identities from selected Git paths so unstaged filesystem aliases cannot hide staged or committed tasks. -->

Location: `src/byteplan/api.py:178`, `src/byteplan/files.py:136-138` and
configuration path validation in `config.py`.

Snapshot construction reads configuration from Git but canonicalizes configured registry
and report paths through the live filesystem. A real-Git reproduction commits a regular
generated `report.md` and a separate `real.md` containing an unregistered task. Both
index and HEAD checks initially scan `real.md` and fail with `new_unregistered` (exit 1).
Replacing only the unstaged working-tree `report.md` with a symlink to `real.md` changes
the snapshot's generated-file exclusion to `real.md`. With identical index and commit,
both checks then omit the task, emit only a report warning and exit 0.

This breaks the documented guarantee that selected-view checks judge Git objects
independently of unstaged source changes. It requires a particular configured report
and live alias, so it is a P2 consistency-gate defect rather than demonstrated data loss.
The real API/Git reproduction uses no monkey-patching. Keep snapshot identities lexical
and derived from the selected Git view; retain confinement checks for working-tree
writes. Cover index and commit, missing live files, internal/external aliases and
registry/report generated-file exclusion.

## Coverage and evidence

The review examines inherited implementation, not only the gate diff. Coverage includes
registry/schema/migration/archive contracts; task identities, prefixes, reservations and
collision repair; Git merge and competing-writer recovery; scanners, annotations,
normalization, cleanup, scaffolding and release/restore; evidence provenance, freshness,
aggregation and explicit lifecycle authority; filesystem boundaries and untrusted inputs;
CLI, public API/result identities, MCP permissions, Hatch/Git integration; packaging,
platform CI, documentation, decomposition and deferred 1.5/2.0 boundaries.

Local evidence is under `/workspace/byteplan-rc1-evidence/codex-a5de5c8/`.
Reproductions and area reports retain exact commands and limitations. The source-focused
suite completed **404 passed**. Full-suite, remaining focused checks, exact-gate platform
CI and fresh installed-artifact checks are in progress and will be attributed explicitly
when complete. No pending, interrupted or platform-skipped check is counted as passed.

The native Windows junction traversal observation remains unverified and is not a
confirmed finding or an outside-write claim. No product fix, semantic graph implementation,
tag, publication or final release approval is part of this review record.
