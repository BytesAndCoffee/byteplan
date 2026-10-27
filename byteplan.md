# BytePlan

<!-- Generated from .byteplan/tasks.json by BytePlan; don't edit. `byteplan scan` and the commit hook keep it current. -->

**18 open** · 98 closed (resolved 98)

## Open

| ID | Status | Kind | Priority | Assignee | Where | Title |
|---|---|---|---|---|---|---|
| `a70d` | in_progress | TODO | high | - | [`docs/spec-addendum-e.md:395`](docs/spec-addendum-e.md#L395) | RC1 approval-ready release report and artifact/platform validation |
| `de66` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1692`](docs/IMPLEMENTATION_PLAN.md#L1692) | Phase 6c (optional): acceptance criteria and dependencies |
| `75b4` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1695`](docs/IMPLEMENTATION_PLAN.md#L1695) | Phase 11 (optional): spec section 14 phase 5 items |
| `9054` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1698`](docs/IMPLEMENTATION_PLAN.md#L1698) | Phase 11b (optional): Git reporting |
| `15df` | open | TODO | normal | - | [`docs/IMPLEMENTATION_PLAN.md:1701`](docs/IMPLEMENTATION_PLAN.md#L1701) | Phase 12: assignment model (Addendum D stages D0-D2, D4) |
| `ec99` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1705`](docs/IMPLEMENTATION_PLAN.md#L1705) | Phase 13 (optional): relay-for-github |
| `a933` | open | TODO | low | - | [`docs/spec-addendum-e.md:218`](docs/spec-addendum-e.md#L218) | 1.5 semantic graph schema, identity and provenance design |
| `e4af` | open | TODO | low | - | [`docs/spec-addendum-e.md:235`](docs/spec-addendum-e.md#L235) | 1.5 repository symbol indexing and task-to-symbol associations |
| `3644` | open | TODO | low | - | [`docs/spec-addendum-e.md:239`](docs/spec-addendum-e.md#L239) | 1.5 deterministic incremental graph cache and invalidation |
| `1fe7` | open | TODO | low | - | [`docs/spec-addendum-e.md:243`](docs/spec-addendum-e.md#L243) | 1.5 partial-index reliability, uncertainty and bounded queries |
| `680a` | open | TODO | low | - | [`docs/spec-addendum-e.md:264`](docs/spec-addendum-e.md#L264) | 2.0 cross-module dependency and change-impact analysis |
| `cdcb` | open | TODO | low | - | [`docs/spec-addendum-e.md:268`](docs/spec-addendum-e.md#L268) | 2.0 verification intelligence with traceable recommendations |
| `4d69` | open | TODO | low | - | [`docs/spec-addendum-e.md:272`](docs/spec-addendum-e.md#L272) | 2.0 Assignment and specification traceability |
| `595f` | open | TODO | low | - | [`docs/spec-addendum-e.md:276`](docs/spec-addendum-e.md#L276) | 2.0 bounded MCP graph operations and portable visualization design |
| `c053` | open | TODO | high | - | [`docs/spec-addendum-e.md:363`](docs/spec-addendum-e.md#L363) | RC1 freeze one integrated revision for two independent whole-repository reviews |
| `a6b2` | open | TODO | normal | - | [`src/byteplan/config.py:309`](src/byteplan/config.py#L309) | Support detect.placeholder_assignments |
| `67a65c` | open | FIXME | low | - | [`src/byteplan/scaffold.py:333`](src/byteplan/scaffold.py#L333) | Separate first-party runtime imports from pytest in new scaffold files |
| `46b6` | open | TODO | normal | - | [`src/byteplan/scanner/comments.py:70`](src/byteplan/scanner/comments.py#L70) | Recognize Google-style `TODO(owner): ...` tags |

## Closed

| ID | Status | Kind | Title |
|---|---|---|---|
| `0413` | resolved | TODO | Phase 8: release stripping |
| `0591` | resolved | FIXME | Refuse decorator arguments whose evaluation stripping would skip |
| `0b12` | resolved | FIXME | relative find_links paths resolve against the scratch dir, not the project root |
| `0c28` | resolved | FIXME | Don't count @pytest.mark.byteplan links as decorators that need stripping |
| `12ce1c` | resolved | FIXME | Validate initialization write targets before any filesystem side effects. |
| `14ff` | resolved | TODO | Phase 7: cleanup |
| `17f1f0` | resolved | FIXME | Complete and validate index-lock writes before publishing the index. |
| `181f` | resolved | FIXME | history simplification skips merged branches' intermediate registry records |
| `1b81` | resolved | TODO | RC1 source-safety and first-run preview audit |
| `1e7f` | resolved | FIXME | [P2] Enforce require_stripped for runtime decorators with dynamic arguments |
| `205d` | resolved | FIXME | Check for a pending journal before the write context recovers it |
| `237cb5` | resolved | FIXME | Preserve unknown nested metadata when combining branch task records. |
| `2533` | resolved | FIXME | Keep every module an import alias may refer to, across scopes |
| `2650ec` | resolved | FIXME | Verify merge preservation across Git checkout newline conversion. |
| `279e27` | resolved | FIXME | Reject positive verification claims without complete provenance and matching file fingerprints. |
| `2887` | resolved | TODO | Phase 6b: test scaffolding |
| `28e56f` | resolved | FIXME | Use the repository object format when removing staged entries during recovery. |
| `30c3` | resolved | FIXME | [P3] Locate decorator IDs by their AST value span during duplicate repair |
| `34da` | resolved | FIXME | Respect enclosing scopes before stripping a decorator |
| `3844` | resolved | TODO | RC1 behavior-preserving decomposition of the public Project facade |
| `38e8db` | resolved | FIXME | Refuse import of archived identities and preserve their authoritative lifecycle and evidence. |
| `3b20` | resolved | FIXME | RC1 remove stale unknown-field-loss claim from completed Phase 4d |
| `3d3a` | resolved | FIXME | the archive index is read from the working tree even when checking a Git snapshot |
| `3d5bb4` | resolved | FIXME | Reserve unregistered embedded IDs outside narrowed targets before allocation. |
| `3f50` | resolved | FIXME | [P2] Normalize the test directory before excluding test-side tasks |
| `4518` | resolved | FIXME | An escaping package exposes every submodule imported under it |
| `478d` | resolved | FIXME | Resolve relative imports before deciding whether they import the runtime |
| `4842` | resolved | TODO | RC1 authoritative storage decision based on measured collaboration and integrity risk |
| `492312` | resolved | FIXME | Keep archived evidence bound to its original run when live run identities collide. |
| `4d48` | resolved | FIXME | Keep decorators pending when their runtime import can't be restored |
| `4fb5` | resolved | TODO | Update the status line for the next release |
| `50ad66` | resolved | FIXME | Preserve external evidence and archive-index edits during archived task restoration |
| `5aae` | resolved | FIXME | [P2] Collect occupied test names inside module-level control-flow blocks |
| `5ff6` | resolved | FIXME | [P2] Report scaffold encoding and filesystem failures per task |
| `62edd5` | resolved | FIXME | Confine serialized transaction and restore targets before filesystem side effects. |
| `631761` | resolved | FIXME | Reject or safely reuse annotations already present during anchored release restoration. |
| `6639` | resolved | FIXME | Keep runtime imports that __all__ re-exports |
| `67df` | resolved | FIXME | [P2] Keep inserted imports after all future imports |
| `6b83` | resolved | FIXME | Keep sync's top-level JSON fields when only cleanup runs |
| `6d434f` | resolved | FIXME | Preserve opaque evidence metadata across ordinary verification and archive writes. |
| `71c4` | resolved | FIXME | the evidence's run metadata isn't archived, so a restore loses it |
| `765f23` | resolved | FIXME | Validate archive-index schema and records while preserving supported opaque metadata. |
| `7ff8` | resolved | FIXME | resolve(sync_source=true) removes the annotation without apply=true |
| `81cc04` | resolved | FIXME | Enforce per-operation source permission and apply authority during transaction recovery. |
| `82b3` | resolved | TODO | Phase 5: runtime and normalization |
| `86e1` | resolved | FIXME | a cached row isn't checked against the index's sha256, so a stale record is returned |
| `8756` | resolved | TODO | RC1 schema boundary and transactional migration for expanded persistent IDs |
| `8aeb` | resolved | TODO | RC1 public compatibility contract and documentation audit |
| `8b28` | resolved | FIXME | Treat an imported module that escapes attribute access as consuming all its names |
| `8c7f` | resolved | FIXME | [P1] Detect module-level bindings through control flow before editing decorators |
| `90c6` | resolved | FIXME | Don't propose stub tasks for declarations whose @todo is stripped for a release |
| `9185` | resolved | FIXME | Keep the space between words around an inline Markdown comment |
| `932b36` | resolved | FIXME | Tell agents to restart the MCP server when the registry schema is newer than it |
| `93dd` | resolved | TODO | Phase 10: integration |
| `98d6` | resolved | FIXME | [P2] Include teardown skips and xfails in the verification outcome |
| `9b40` | resolved | TODO | Phase 6a: acceptance tests |
| `9c60` | resolved | TODO | List only active missing tasks by default |
| `9f8d` | resolved | FIXME | Check the current source even when a stripped release is on record |
| `a067` | resolved | FIXME | top-level native extension modules (.so/.pyd) are left out of smoke imports |
| `a4bf` | resolved | FIXME | [P2] Report source-decoding failures without aborting the scan |
| `a703` | resolved | FIXME | Refuse wildcard runtime imports, whose bindings can't be proven unused |
| `a740` | resolved | FIXME | [P2] Require regular files before selecting sources for scanning |
| `ac9d` | resolved | FIXME | [P2] Compare collected node IDs relative to the BytePlan project root |
| `ae7a` | resolved | FIXME | [P2] Apply nested gitignore negations with Git's precedence rules |
| `aedf` | resolved | FIXME | Check every runtime import, not just decorator bindings, before skipping a file |
| `af82fd` | resolved | FIXME | Keep a committed copy of current evidence before moving it to the ignored archive |
| `b29c72` | resolved | FIXME | Refresh or explain stale discovered links when a linked test is not found |
| `b55f` | resolved | FIXME | Insert scaffold imports in sorted position |
| `b68c` | resolved | FIXME | Restore an unanchored import below the current docstring and __future__ imports |
| `b865` | resolved | FIXME | an archived task's readiness ignores the evidence archived with it |
| `baeb` | resolved | FIXME | Count every __all__ assignment form as an export |
| `be8e` | resolved | FIXME | Annotate scaffolded tests with -> None |
| `c242` | resolved | FIXME | Check the current binding before restoring a decorator |
| `c26d29` | resolved | FIXME | Detach disposable Git metadata without deleting Windows read-only object files |
| `c35e66` | resolved | FIXME | Keep snapshot queries bound to their selected data and reject mutation before side effects |
| `c449` | resolved | FIXME | Treat __all__ mutations the export collector can't resolve as exporting everything |
| `c8db` | resolved | FIXME | Keep runtime imports that other modules consume through re-exports |
| `c978` | resolved | FIXME | RC1 persistent identity compatibility: remove four-character-only assumptions |
| `c993` | resolved | FIXME | Retry report generation when main advances before the push |
| `cc54` | resolved | FIXME | Detect a runtime module imported through its parent package |
| `cda4d1` | resolved | FIXME | Confine archive cache and SQLite sidecar paths before implicit writes. |
| `ce72` | resolved | TODO | Summarize scan results by default instead of listing every annotation |
| `d45d` | resolved | TODO | Return only the scaffolded test, not the whole target file |
| `d78b89` | resolved | FIXME | Reject cross-scope duplicate identities before narrowed task reconciliation writes. |
| `dcd417` | resolved | FIXME | Validate all staged recovery copy hashes before forward or rollback side effects. |
| `def0` | resolved | FIXME | scan paths resolve against the server's cwd, not the served project's root |
| `e7d9` | resolved | FIXME | ours always wins, so a one-sided re-archive (new sha256) is lost when merged into the other side |
| `ecf4` | resolved | FIXME | [P2] Preserve runtime imports consumed by other project modules during cleanup |
| `ed2b` | resolved | FIXME | [P2] Refuse staged writes while an ordinary transaction journal is pending |
| `edc2` | resolved | FIXME | RC1 plain-Git merge and conflicting-evidence validation |
| `ee606e` | resolved | FIXME | [P1] Merge registries across the v1->v2 migration instead of conflicting |
| `f853` | resolved | TODO | Phase 9: MCP server |
| `fb23` | resolved | FIXME | Keep a restored runtime import above every use of its names |
| `fb9c` | resolved | FIXME | Track escapes of dotted module expressions like `alias = pkg.reexport` |
| `fd44` | resolved | FIXME | Keep anchored imports below a __future__ import added since the release |
| `ff20` | resolved | FIXME | [P2] Retain archived payloads by task ID and record hash |
| `ff3a` | resolved | FIXME | @verifies links to archived tasks are reported as unknown task references |
| `ff72` | resolved | FIXME | Preserve pytest's symlink spelling when normalizing node IDs |
