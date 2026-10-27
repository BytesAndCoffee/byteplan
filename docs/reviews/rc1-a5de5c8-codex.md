# Codex independent whole-repository RC1 gate review

Review target: `a5de5c861382a61cf2ca38c093e8268f401f82c3`.
Read-only detached checkout: `/workspace/byteplan-codex-gate-review`.

This report records Codex's initial conclusions without reading Claude's current gate
review. The persistence, source-safety and interface inspections are parts of this one
Codex repository-wide review; they are not the second independent whole-repository review.
The gate remains immutable. This report and its task registrations are follow-up records.

Disposition: changes requested for three confirmed P2 concerns. No confirmed P0/P1
finding. All three tasks remain open for explicit triage and correction. This is one
independent review, not release approval or a claim of agreement with Claude.

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
Reproductions and area reports retain exact commands and limitations. Completed focused
checks, which overlap and must not be added as a unique-test total:

| Selection | Completed result |
|---|---|
| Source/scanner/editing/normalization/cleanup/scaffold | 404 passed; exit 0 |
| Persistence/IDs/collisions/merges/archive/evidence | 422 passed, one native Windows case skipped on Linux; exit 0 |
| Public API/CLI/MCP/config/initialization/Hatch | 208 passed, one network case deselected; exit 0 |
| Exact selected-commit consistency | `byteplan check --commit a5de5c861382a61cf2ca38c093e8268f401f82c3 --format json`: exit 0, empty diagnostics |

The complete local run **failed**: **1,741 passed, one failed, two skipped and three
network cases deselected in 1,230.29 seconds**, exit 1. The sole failure was
`tests/test__verify_plugin.py::test_verification_preserves_symlink_node_ids[passed-directory-False]`:
the real child pytest invocation hit the existing 30-second timeout without output;
the expected `passed` result was `timeout`. The same case rerun in isolation passed
(3.22 seconds), then all eight related symlink/plugin cases passed (38.40 seconds),
both exit 0. No test, timeout or product source was changed. The original full-run
failure remains in `full-suite.log`; focused reruns have separate logs and do not turn
that run into a pass. The initial run overlapped other checks, but its precise timeout
cause is not established. This Linux direct-runner timeout is separate from the
confirmed Windows wrapper/descendant defect above. No pending, interrupted or
platform-skipped check is counted as passed.

[Gate CI run 40546275232](https://github.com/BytesAndCoffee/byteplan/actions/runs/40546275232)
completed all **15 jobs successfully** at the exact reviewed SHA: CPython 3.11–3.14 on
Linux/macOS/Windows, actual released-client compatibility, formatting/strict typing/runtime
checks and BytePlan consistency. Windows 3.12 job `122337643833` completed 1,733 passed,
nine skipped and three network cases deselected. Its two explicit native junction checks
also passed: control-directory cleanup and merge-driver installation confinement. These
do not test the newly identified Windows wrapper-timeout defect. Current CI does not
establish PyPy support or the separate runtime's entire advertised interpreter matrix.

Fresh exact-gate wheel/sdist builds and isolated installations completed successfully.
The artifact harness verified all 59 package source files, 64 wheel entries and 150 sdist
entries, with tracked checkout content/status unchanged before and after. Installed
CLI/API and public-result pickle/constructor checks, actual MCP stdio permissions and
queries, isolated Hatch default/explicit-write builds and separately installed inert
runtime checks all passed. No editable installation substituted for an artifact install.

| Exact-gate artifact | SHA-256 |
|---|---|
| `byteplan-1.0.0rc1-py3-none-any.whl` | `f708b6e840a928d8ead8c91430ca2f35188f0880f7237fa6fef5558c240edb95` |
| `byteplan-1.0.0rc1.tar.gz` | `928152390a52a01786abf1919db829193b645380609fb9233c7b9b405be54eec` |

Artifact commands, metadata, payload comparisons and smoke results are retained in
`/workspace/byteplan-rc1-evidence/artifacts-gate-a5de5c8/manifest.json`. These installations
ran on Python 3.12/Linux; platform coverage comes from the separately attributed CI.

The native Windows junction traversal observation remains unverified and is not a
confirmed finding or an outside-write claim. No product fix, semantic graph implementation,
tag, publication or final release approval is part of this review record.
