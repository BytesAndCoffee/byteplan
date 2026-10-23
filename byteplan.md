# BytePlan

<!-- Generated from .byteplan/tasks.json by BytePlan; don't edit. `byteplan scan` and the commit hook keep it current. -->

**7 open** · 66 closed (resolved 66)

## Open

| ID | Status | Kind | Priority | Assignee | Where | Title |
|---|---|---|---|---|---|---|
| `de66` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1609`](docs/IMPLEMENTATION_PLAN.md#L1609) | Phase 6c (optional): acceptance criteria and dependencies |
| `75b4` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1612`](docs/IMPLEMENTATION_PLAN.md#L1612) | Phase 11 (optional): spec section 14 phase 5 items |
| `9054` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1615`](docs/IMPLEMENTATION_PLAN.md#L1615) | Phase 11b (optional): Git reporting |
| `15df` | open | TODO | normal | - | [`docs/IMPLEMENTATION_PLAN.md:1618`](docs/IMPLEMENTATION_PLAN.md#L1618) | Phase 12: assignment model (Addendum D stages D0-D2, D4) |
| `ec99` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1622`](docs/IMPLEMENTATION_PLAN.md#L1622) | Phase 13 (optional): relay-for-github |
| `a6b2` | open | TODO | normal | - | [`src/byteplan/config.py:309`](src/byteplan/config.py#L309) | Support detect.placeholder_assignments |
| `46b6` | open | TODO | normal | - | [`src/byteplan/scanner/comments.py:70`](src/byteplan/scanner/comments.py#L70) | Recognize Google-style `TODO(owner): ...` tags |

## Closed

| ID | Status | Kind | Title |
|---|---|---|---|
| `0413` | resolved | TODO | Phase 8: release stripping |
| `0591` | resolved | FIXME | Refuse decorator arguments whose evaluation stripping would skip |
| `0b12` | resolved | FIXME | relative find_links paths resolve against the scratch dir, not the project root |
| `0c28` | resolved | FIXME | Don't count @pytest.mark.byteplan links as decorators that need stripping |
| `14ff` | resolved | TODO | Phase 7: cleanup |
| `181f` | resolved | FIXME | history simplification skips merged branches' intermediate registry records |
| `1e7f` | resolved | FIXME | [P2] Enforce require_stripped for runtime decorators with dynamic arguments |
| `205d` | resolved | FIXME | Check for a pending journal before the write context recovers it |
| `2533` | resolved | FIXME | Keep every module an import alias may refer to, across scopes |
| `2887` | resolved | TODO | Phase 6b: test scaffolding |
| `30c3` | resolved | FIXME | [P3] Locate decorator IDs by their AST value span during duplicate repair |
| `34da` | resolved | FIXME | Respect enclosing scopes before stripping a decorator |
| `3d3a` | resolved | FIXME | the archive index is read from the working tree even when checking a Git snapshot |
| `3f50` | resolved | FIXME | [P2] Normalize the test directory before excluding test-side tasks |
| `4518` | resolved | FIXME | An escaping package exposes every submodule imported under it |
| `478d` | resolved | FIXME | Resolve relative imports before deciding whether they import the runtime |
| `4d48` | resolved | FIXME | Keep decorators pending when their runtime import can't be restored |
| `4fb5` | resolved | TODO | Update the status line for the next release |
| `5aae` | resolved | FIXME | [P2] Collect occupied test names inside module-level control-flow blocks |
| `5ff6` | resolved | FIXME | [P2] Report scaffold encoding and filesystem failures per task |
| `6639` | resolved | FIXME | Keep runtime imports that __all__ re-exports |
| `67df` | resolved | FIXME | [P2] Keep inserted imports after all future imports |
| `6b83` | resolved | FIXME | Keep sync's top-level JSON fields when only cleanup runs |
| `71c4` | resolved | FIXME | the evidence's run metadata isn't archived, so a restore loses it |
| `7ff8` | resolved | FIXME | resolve(sync_source=true) removes the annotation without apply=true |
| `82b3` | resolved | TODO | Phase 5: runtime and normalization |
| `86e1` | resolved | FIXME | a cached row isn't checked against the index's sha256, so a stale record is returned |
| `8b28` | resolved | FIXME | Treat an imported module that escapes attribute access as consuming all its names |
| `8c7f` | resolved | FIXME | [P1] Detect module-level bindings through control flow before editing decorators |
| `90c6` | resolved | FIXME | Don't propose stub tasks for declarations whose @todo is stripped for a release |
| `9185` | resolved | FIXME | Keep the space between words around an inline Markdown comment |
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
| `b55f` | resolved | FIXME | Insert scaffold imports in sorted position |
| `b68c` | resolved | FIXME | Restore an unanchored import below the current docstring and __future__ imports |
| `b865` | resolved | FIXME | an archived task's readiness ignores the evidence archived with it |
| `baeb` | resolved | FIXME | Count every __all__ assignment form as an export |
| `be8e` | resolved | FIXME | Annotate scaffolded tests with -> None |
| `c242` | resolved | FIXME | Check the current binding before restoring a decorator |
| `c449` | resolved | FIXME | Treat __all__ mutations the export collector can't resolve as exporting everything |
| `c8db` | resolved | FIXME | Keep runtime imports that other modules consume through re-exports |
| `c993` | resolved | FIXME | Retry report generation when main advances before the push |
| `cc54` | resolved | FIXME | Detect a runtime module imported through its parent package |
| `ce72` | resolved | TODO | Summarize scan results by default instead of listing every annotation |
| `d45d` | resolved | TODO | Return only the scaffolded test, not the whole target file |
| `def0` | resolved | FIXME | scan paths resolve against the server's cwd, not the served project's root |
| `e7d9` | resolved | FIXME | ours always wins, so a one-sided re-archive (new sha256) is lost when merged into the other side |
| `ecf4` | resolved | FIXME | [P2] Preserve runtime imports consumed by other project modules during cleanup |
| `ed2b` | resolved | FIXME | [P2] Refuse staged writes while an ordinary transaction journal is pending |
| `f853` | resolved | TODO | Phase 9: MCP server |
| `fb23` | resolved | FIXME | Keep a restored runtime import above every use of its names |
| `fb9c` | resolved | FIXME | Track escapes of dotted module expressions like `alias = pkg.reexport` |
| `fd44` | resolved | FIXME | Keep anchored imports below a __future__ import added since the release |
| `ff20` | resolved | FIXME | [P2] Retain archived payloads by task ID and record hash |
| `ff3a` | resolved | FIXME | @verifies links to archived tasks are reported as unknown task references |
| `ff72` | resolved | FIXME | Preserve pytest's symlink spelling when normalizing node IDs |
