# Codex independent whole-repository RC1 review

Reviewed revision: `d29ac93bbbf57e9216a2c10694b307409399c734`.

Verdict: **changes required; RC1 is not approval-ready**. Two P1 safety/data-integrity defects and two P2 reliability findings were independently reproduced. These conclusions were recorded before consulting Claude's current review. No tag or release was created.

This verdict describes the frozen revision above. [Subsequent corrections](rc1-review4-corrections.md)
implement all four findings with real regressions, recorded verification and explicit task
resolution. The original analysis below remains historical evidence; affected reviews do not
replace the final common-SHA whole-repository release gate.

## R1 — P1: stale-lock reclamation permits successful competing writes to lose a task

Location: `src/byteplan/persistence.py:143–147`; unconditional release at `:156–158` has the same ownership assumption.

`project_lock` reads a dead PID, checks its liveness, then unconditionally unlinks the pathname. A competing writer can remove the original stale file and acquire a live lock between that check and unlink. The first writer then deletes the second writer's live lock and both enter the protected read/plan/write section.

Two deterministic, temporary-only probes use real filesystem lock operations. The first pauses the first writer's stale-PID liveness check until the second writer holds its replacement lock, proving overlap. The second additionally pauses the second transaction immediately before its real atomic target write, after its optimistic hash check and payload read. Both actual `persistence.commit` calls then return success. Input and output registries are validated with the schema-2 registry loader:

```text
base IDs: ['aaaa']
first successful commit IDs: ['aaaa', 'bbbb']
second successful commit IDs: ['aaaa', 'cccc']
failures: []
final IDs: ['aaaa', 'cccc']
pending journal: False
```

The successfully written task `bbbb` is silently lost. Instrumentation changes scheduling only; it does not fake lock acquisition, fingerprints, payloads or write outcomes. The parent reviewer independently reran both demonstrations. The same filesystem schedule is possible between separate processes. The proved stale-PID reclaim trigger applies on POSIX; the current Windows liveness implementation does not automatically reclaim locks.

This is a release blocker because BytePlan's own writer exclusion fails and actual successful task loss is demonstrated. Use a reclamation protocol that cannot unlink a newer owner's lock, or fail closed on stale locks and require deliberate cleanup while no writer runs. A second PID/inode comparison immediately before unlink is insufficient by itself because it leaves another check-to-unlink race. Test complete competing transactions, preservation of both valid task updates or an explicit safe conflict, and retained recovery authority.

## R2 — P1: merge-driver installation writes outside the project through a state-directory alias

Location: `src/byteplan/gitio.py:126–158`.

Create a temporary Git project with `registry = "records/tasks.json"`, an outside temporary directory containing `.gitattributes` with `important.bin -text`, and a project `.byteplan` directory symlink to that outside directory. Run the public command `byteplan git install-merge-driver --project ROOT`.

Observed: exit 0; the outside file gains `archive.json merge=byteplan-archive`. The command also creates `records/.gitattributes` and writes local Git driver settings. `_add_attribute` calls raw `atomic_write_bytes` without validating the state directory or destination boundaries. The custom registry allows project loading without traversing `.byteplan` first. The parent independently reran this CLI reproduction.

The demonstrated extent is an appended rule in a fixed external `.gitattributes`, not arbitrary-byte overwrite, registry loss or deletion. It is a release-blocking write-authority violation: integration installation modifies a destination outside the project without refusal or outside-target notice. Preflight every attributes destination, the lexical state-directory identity and unsafe/nonregular/conflicting/protected parents before the first attributes/config mutation. Reuse existing guards and preserve installation idempotence. Test no outside changes and no partial local/config changes on refusal, including native Windows aliases where available. Explicit Git `core.hooksPath` behavior is a separate contract.

## R3 — P2: supported filenames containing spaces receive no merge-driver association

Location: `src/byteplan/gitio.py:129`.

Configure `registry = "records/tasks with space.json"` and `report_file = "task plan.md"`, then install the merge driver. Installation reports success but inserts those names directly as unquoted patterns. Actual Git lookup shows:

```text
records/tasks with space.json: merge: unspecified
task plan.md: merge: unspecified
.byteplan/archive.json: merge: byteplan-archive
```

Both the independent interface reviewer and parent reproduced this with the public CLI and `git check-attr`. Use Git attributes pattern/quoting rules rather than shell quoting, and test actual matching plus repeat installation. Consider literal glob characters in the fix; only spaces were demonstrated here. This is P2 supported-path reliability, not demonstrated data loss: plain Git can still fail with an explicit conflict. Accept for pre-RC1 correction alongside R2, without treating the custom driver as mandatory for correctness.

## R4 — P2: unclosed persistent-ID brackets silently hide intended task annotations

Location: `src/byteplan/scanner/comments.py:79–88`; the shared grammar is used by Python, Markdown and JSON-comment scanners.

`# TODO[123456: broken identity`, `<!-- TODO[123456: broken identity -->`, and a JSONC `// TODO[123456: broken identity` each produce zero tasks and zero diagnostics. An initialized temporary Python project containing the first example also returns `byteplan check --format json` with an empty diagnostics list and exit 0. No project source is imported by the probe.

The optional bracket expression requires a closing `]`; when it is absent, the whole tag match fails before `tag_annotation` can issue `malformed_id`. This is distinct from intentionally unsupported owner-style TODO syntax and from closed-bracket IDs already diagnosed by validation. It violates the Addendum E compatibility acceptance criterion that malformed annotations must not silently drop tasks. Add a bounded malformed-ID diagnostic for an otherwise recognized task opener; never allocate an identity into malformed syntax or infer its intended identity. Preserve prose/fenced-code/string exclusions and exercise the shared scanners. P2 reliability/compatibility; accept for pre-RC1 correction rather than assert demonstrated lifecycle data loss.

## Coverage and independence

The parent coordinated this single whole-repository review. Independent code inspections covered persistence/identity/merges/archive and CLI/API/MCP/Hatch/runtime/packaging; the parent inspected verification/provenance/freshness, source decoding/edit validation, annotation/scanner/normalization/cleanup, release/restore, integration workflows and scripts. Cross-platform branches, documented compatibility boundaries, module cohesion and deferred graph/Assignment scope were inspected. This is one Codex review with delegated area inspections, not two whole-repository approvals.

Claude's current review and its conclusions were not consulted before these findings were recorded. The interface reviewer disclosed that an overbroad documentation search returned excerpts from historical `378e722` reviews; neither integration finding came from those excerpts, and current Claude conclusions remained unread. A source-review worker failed before delivering a report; the parent covered source safety directly and does not count that failed worker as completed independent coverage.

Reviewed source remains frozen in a detached checkout. Registrations and this report live on a separate branch and do not change the reviewed product revision. Findings remain open until explicit implementation, regression verification and resolution. No full-release approval or automatic publication follows from a green test suite.

## Validation evidence

Evidence directory: `/workspace/byteplan-rc1-evidence/codex-d29ac93/`.

- Current-code stale-lock overlap and real committed-task-loss probes: reproduced; original and parent confirmation logs retained.
- Current-code external-attributes alias and spaced-path CLI probes: reproduced; original and parent confirmation logs retained.
- Shared-scanner malformed-ID probe and initialized-project check: reproduced. The first project probe omitted initialization and failed; that failed log is retained, and the corrected initialized run is separate.
- Strict typing: passed, 120 source files.
- Ruff lint/format: passed, 121 files already formatted.
- Wheel and source-distribution builds: passed from the clean reviewed checkout. No new installed-artifact harness run is claimed.
- Actual previously released-client interoperability: 2 passed, including published older clients and the schema-version refusal boundary. The separate Hatch isolated-build network test also passed (1 passed, 28 deselected).
- Separate inert-runtime suite: 10 passed.
- Full cross-platform CI: [run 40525400497](https://github.com/BytesAndCoffee/byteplan/actions/runs/40525400497), all 15 jobs passed on PR #52 head `f0848fe837d2bae4159d95e4f8a7849a0f5ab4ca`. The only tree difference from the reviewed `d29ac93` is generated `byteplan.md`; code, tests, scripts, configuration and workflows are identical. The matrix covers CPython 3.11–3.14 on Linux/macOS/Windows, released clients, quality/runtime and consistency. Windows 3.12 reports 1,663 passed, 5 skipped and 3 network cases deselected; its separate native directory-junction regression actually reports PASSED. Job summaries, the source-difference proof and the bounded native log excerpt are retained separately.
- Local full core suite: no completed local pass is claimed. The first run was interrupted after 93 passes by a review worker mistakenly signalling the parent's PID while stopping its duplicate run. This was a review coordination error, not a product test failure. A fresh rerun was subsequently stopped deliberately after 369 passes and 3 network deselections (564.44 seconds, exit 2) after confirming the completed 15-job CI matrix on the identical product tree and the independently reproduced release blockers. Both partial logs remain; neither is represented as a complete suite pass.
- Duplicate area runs were deliberately stopped to remove redundant load and are not counted as complete passes.

Native Windows/macOS checks were not executed locally by this review; the CI attribution above records the actual tested SHA and its generated-report-only difference. No installed-artifact or additional release-readiness approval is inferred from these checks. Release-blocking findings prevent approval despite the green existing matrix. Readiness documentation was consulted only after the initial independent findings were recorded, then corrected to reflect these blockers and Addendum E's required common-SHA reviews.
