# BytePlan

<!-- Generated from .byteplan/tasks.json by BytePlan; don't edit. `byteplan scan` and the commit hook keep it current. -->

**9 open** · 31 closed (resolved 31)

## Open

| ID | Status | Kind | Priority | Assignee | Where | Title |
|---|---|---|---|---|---|---|
| `de66` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1550`](docs/IMPLEMENTATION_PLAN.md#L1550) | Phase 6c (optional): acceptance criteria and dependencies |
| `f853` | open | TODO | normal | - | [`docs/IMPLEMENTATION_PLAN.md:1553`](docs/IMPLEMENTATION_PLAN.md#L1553) | Phase 9: MCP server |
| `93dd` | open | TODO | normal | - | [`docs/IMPLEMENTATION_PLAN.md:1557`](docs/IMPLEMENTATION_PLAN.md#L1557) | Phase 10: integration |
| `75b4` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1561`](docs/IMPLEMENTATION_PLAN.md#L1561) | Phase 11 (optional): spec section 14 phase 5 items |
| `9054` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1564`](docs/IMPLEMENTATION_PLAN.md#L1564) | Phase 11b (optional): Git reporting |
| `15df` | open | TODO | normal | - | [`docs/IMPLEMENTATION_PLAN.md:1567`](docs/IMPLEMENTATION_PLAN.md#L1567) | Phase 12: assignment model (Addendum D stages D0-D2, D4) |
| `ec99` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1571`](docs/IMPLEMENTATION_PLAN.md#L1571) | Phase 13 (optional): relay-for-github |
| `a6b2` | open | TODO | normal | - | [`src/byteplan/config.py:291`](src/byteplan/config.py#L291) | Support detect.placeholder_assignments |
| `46b6` | open | TODO | normal | - | [`src/byteplan/scanner/comments.py:70`](src/byteplan/scanner/comments.py#L70) | Recognize Google-style `TODO(owner): ...` tags |

## Closed

| ID | Status | Kind | Title |
|---|---|---|---|
| `0413` | resolved | TODO | Phase 8: release stripping |
| `0591` | resolved | FIXME | Refuse decorator arguments whose evaluation stripping would skip |
| `0c28` | resolved | FIXME | Don't count @pytest.mark.byteplan links as decorators that need stripping |
| `14ff` | resolved | TODO | Phase 7: cleanup |
| `205d` | resolved | FIXME | Check for a pending journal before the write context recovers it |
| `2533` | resolved | FIXME | Keep every module an import alias may refer to, across scopes |
| `2887` | resolved | TODO | Phase 6b: test scaffolding |
| `34da` | resolved | FIXME | Respect enclosing scopes before stripping a decorator |
| `4518` | resolved | FIXME | An escaping package exposes every submodule imported under it |
| `478d` | resolved | FIXME | Resolve relative imports before deciding whether they import the runtime |
| `4d48` | resolved | FIXME | Keep decorators pending when their runtime import can't be restored |
| `4fb5` | resolved | TODO | Update the status line for the next release |
| `6639` | resolved | FIXME | Keep runtime imports that __all__ re-exports |
| `6b83` | resolved | FIXME | Keep sync's top-level JSON fields when only cleanup runs |
| `82b3` | resolved | TODO | Phase 5: runtime and normalization |
| `8b28` | resolved | FIXME | Treat an imported module that escapes attribute access as consuming all its names |
| `90c6` | resolved | FIXME | Don't propose stub tasks for declarations whose @todo is stripped for a release |
| `9185` | resolved | FIXME | Keep the space between words around an inline Markdown comment |
| `9b40` | resolved | TODO | Phase 6a: acceptance tests |
| `9f8d` | resolved | FIXME | Check the current source even when a stripped release is on record |
| `a703` | resolved | FIXME | Refuse wildcard runtime imports, whose bindings can't be proven unused |
| `aedf` | resolved | FIXME | Check every runtime import, not just decorator bindings, before skipping a file |
| `b68c` | resolved | FIXME | Restore an unanchored import below the current docstring and __future__ imports |
| `baeb` | resolved | FIXME | Count every __all__ assignment form as an export |
| `c242` | resolved | FIXME | Check the current binding before restoring a decorator |
| `c449` | resolved | FIXME | Treat __all__ mutations the export collector can't resolve as exporting everything |
| `c8db` | resolved | FIXME | Keep runtime imports that other modules consume through re-exports |
| `cc54` | resolved | FIXME | Detect a runtime module imported through its parent package |
| `fb23` | resolved | FIXME | Keep a restored runtime import above every use of its names |
| `fb9c` | resolved | FIXME | Track escapes of dotted module expressions like `alias = pkg.reexport` |
| `fd44` | resolved | FIXME | Keep anchored imports below a __future__ import added since the release |
