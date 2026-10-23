# BytePlan

<!-- Generated from .byteplan/tasks.json by BytePlan; don't edit. `byteplan scan` and the commit hook keep it current. -->

**8 open** · 43 closed (resolved 43)

## Open

| ID | Status | Kind | Priority | Assignee | Where | Title |
|---|---|---|---|---|---|---|
| `de66` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1595`](docs/IMPLEMENTATION_PLAN.md#L1595) | Phase 6c (optional): acceptance criteria and dependencies |
| `93dd` | open | TODO | normal | - | [`docs/IMPLEMENTATION_PLAN.md:1598`](docs/IMPLEMENTATION_PLAN.md#L1598) | Phase 10: integration |
| `75b4` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1602`](docs/IMPLEMENTATION_PLAN.md#L1602) | Phase 11 (optional): spec section 14 phase 5 items |
| `9054` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1605`](docs/IMPLEMENTATION_PLAN.md#L1605) | Phase 11b (optional): Git reporting |
| `15df` | open | TODO | normal | - | [`docs/IMPLEMENTATION_PLAN.md:1608`](docs/IMPLEMENTATION_PLAN.md#L1608) | Phase 12: assignment model (Addendum D stages D0-D2, D4) |
| `ec99` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1612`](docs/IMPLEMENTATION_PLAN.md#L1612) | Phase 13 (optional): relay-for-github |
| `a6b2` | open | TODO | normal | - | [`src/byteplan/config.py:302`](src/byteplan/config.py#L302) | Support detect.placeholder_assignments |
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
| `205d` | resolved | FIXME | Check for a pending journal before the write context recovers it |
| `2533` | resolved | FIXME | Keep every module an import alias may refer to, across scopes |
| `2887` | resolved | TODO | Phase 6b: test scaffolding |
| `34da` | resolved | FIXME | Respect enclosing scopes before stripping a decorator |
| `3d3a` | resolved | FIXME | the archive index is read from the working tree even when checking a Git snapshot |
| `4518` | resolved | FIXME | An escaping package exposes every submodule imported under it |
| `478d` | resolved | FIXME | Resolve relative imports before deciding whether they import the runtime |
| `4d48` | resolved | FIXME | Keep decorators pending when their runtime import can't be restored |
| `4fb5` | resolved | TODO | Update the status line for the next release |
| `6639` | resolved | FIXME | Keep runtime imports that __all__ re-exports |
| `6b83` | resolved | FIXME | Keep sync's top-level JSON fields when only cleanup runs |
| `71c4` | resolved | FIXME | the evidence's run metadata isn't archived, so a restore loses it |
| `7ff8` | resolved | FIXME | resolve(sync_source=true) removes the annotation without apply=true |
| `82b3` | resolved | TODO | Phase 5: runtime and normalization |
| `86e1` | resolved | FIXME | a cached row isn't checked against the index's sha256, so a stale record is returned |
| `8b28` | resolved | FIXME | Treat an imported module that escapes attribute access as consuming all its names |
| `90c6` | resolved | FIXME | Don't propose stub tasks for declarations whose @todo is stripped for a release |
| `9185` | resolved | FIXME | Keep the space between words around an inline Markdown comment |
| `9b40` | resolved | TODO | Phase 6a: acceptance tests |
| `9f8d` | resolved | FIXME | Check the current source even when a stripped release is on record |
| `a067` | resolved | FIXME | top-level native extension modules (.so/.pyd) are left out of smoke imports |
| `a703` | resolved | FIXME | Refuse wildcard runtime imports, whose bindings can't be proven unused |
| `aedf` | resolved | FIXME | Check every runtime import, not just decorator bindings, before skipping a file |
| `b68c` | resolved | FIXME | Restore an unanchored import below the current docstring and __future__ imports |
| `b865` | resolved | FIXME | an archived task's readiness ignores the evidence archived with it |
| `baeb` | resolved | FIXME | Count every __all__ assignment form as an export |
| `c242` | resolved | FIXME | Check the current binding before restoring a decorator |
| `c449` | resolved | FIXME | Treat __all__ mutations the export collector can't resolve as exporting everything |
| `c8db` | resolved | FIXME | Keep runtime imports that other modules consume through re-exports |
| `cc54` | resolved | FIXME | Detect a runtime module imported through its parent package |
| `def0` | resolved | FIXME | scan paths resolve against the server's cwd, not the served project's root |
| `e7d9` | resolved | FIXME | ours always wins, so a one-sided re-archive (new sha256) is lost when merged into the other side |
| `f853` | resolved | TODO | Phase 9: MCP server |
| `fb23` | resolved | FIXME | Keep a restored runtime import above every use of its names |
| `fb9c` | resolved | FIXME | Track escapes of dotted module expressions like `alias = pkg.reexport` |
| `fd44` | resolved | FIXME | Keep anchored imports below a __future__ import added since the release |
| `ff3a` | resolved | FIXME | @verifies links to archived tasks are reported as unknown task references |
