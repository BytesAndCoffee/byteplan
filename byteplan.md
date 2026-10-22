# BytePlan

<!-- Generated from .byteplan/tasks.json by BytePlan; don't edit. `byteplan scan` and the commit hook keep it current. -->

**30 open** · 8 closed (resolved 8)

## Open

| ID | Status | Kind | Priority | Assignee | Where | Title |
|---|---|---|---|---|---|---|
| `de66` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1550`](docs/IMPLEMENTATION_PLAN.md#L1550) | Phase 6c (optional): acceptance criteria and dependencies |
| `0413` | open | TODO | normal | - | [`docs/IMPLEMENTATION_PLAN.md:1553`](docs/IMPLEMENTATION_PLAN.md#L1553) | Phase 8: release stripping |
| `f853` | open | TODO | normal | - | [`docs/IMPLEMENTATION_PLAN.md:1557`](docs/IMPLEMENTATION_PLAN.md#L1557) | Phase 9: MCP server |
| `93dd` | open | TODO | normal | - | [`docs/IMPLEMENTATION_PLAN.md:1561`](docs/IMPLEMENTATION_PLAN.md#L1561) | Phase 10: integration |
| `75b4` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1565`](docs/IMPLEMENTATION_PLAN.md#L1565) | Phase 11 (optional): spec section 14 phase 5 items |
| `9054` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1568`](docs/IMPLEMENTATION_PLAN.md#L1568) | Phase 11b (optional): Git reporting |
| `15df` | open | TODO | normal | - | [`docs/IMPLEMENTATION_PLAN.md:1571`](docs/IMPLEMENTATION_PLAN.md#L1571) | Phase 12: assignment model (Addendum D stages D0-D2, D4) |
| `ec99` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1575`](docs/IMPLEMENTATION_PLAN.md#L1575) | Phase 13 (optional): relay-for-github |
| `90c6` | open | FIXME | normal | - | [`src/byteplan/api.py:416`](src/byteplan/api.py#L416) | Don't propose stub tasks for declarations whose @todo is stripped for a release |
| `205d` | open | FIXME | normal | - | [`src/byteplan/api.py:1174`](src/byteplan/api.py#L1174) | Check for a pending journal before the write context recovers it |
| `4d48` | open | FIXME | normal | - | [`src/byteplan/api.py:1322`](src/byteplan/api.py#L1322) | Keep decorators pending when their runtime import can't be restored |
| `a6b2` | open | TODO | normal | - | [`src/byteplan/config.py:291`](src/byteplan/config.py#L291) | Support detect.placeholder_assignments |
| `aedf` | open | FIXME | normal | - | [`src/byteplan/release.py:98`](src/byteplan/release.py#L98) | Check every runtime import, not just decorator bindings, before skipping a file |
| `34da` | open | FIXME | normal | - | [`src/byteplan/release.py:111`](src/byteplan/release.py#L111) | Respect enclosing scopes before stripping a decorator |
| `0591` | open | FIXME | normal | - | [`src/byteplan/release.py:139`](src/byteplan/release.py#L139) | Refuse decorator arguments whose evaluation stripping would skip |
| `c8db` | open | FIXME | normal | - | [`src/byteplan/release.py:172`](src/byteplan/release.py#L172) | Keep runtime imports that other modules consume through re-exports |
| `2533` | open | FIXME | normal | - | [`src/byteplan/release.py:258`](src/byteplan/release.py#L258) | Keep every module an import alias may refer to, across scopes |
| `4518` | open | FIXME | normal | - | [`src/byteplan/release.py:272`](src/byteplan/release.py#L272) | An escaping package exposes every submodule imported under it |
| `8b28` | open | FIXME | normal | - | [`src/byteplan/release.py:277`](src/byteplan/release.py#L277) | Treat an imported module that escapes attribute access as consuming all its names |
| `fb9c` | open | FIXME | normal | - | [`src/byteplan/release.py:287`](src/byteplan/release.py#L287) | Track escapes of dotted module expressions like `alias = pkg.reexport` |
| `cc54` | open | FIXME | normal | - | [`src/byteplan/release.py:305`](src/byteplan/release.py#L305) | Detect a runtime module imported through its parent package |
| `478d` | open | FIXME | normal | - | [`src/byteplan/release.py:333`](src/byteplan/release.py#L333) | Resolve relative imports before deciding whether they import the runtime |
| `a703` | open | FIXME | normal | - | [`src/byteplan/release.py:361`](src/byteplan/release.py#L361) | Refuse wildcard runtime imports, whose bindings can't be proven unused |
| `baeb` | open | FIXME | normal | - | [`src/byteplan/release.py:373`](src/byteplan/release.py#L373) | Count every __all__ assignment form as an export |
| `c449` | open | FIXME | normal | - | [`src/byteplan/release.py:377`](src/byteplan/release.py#L377) | Treat __all__ mutations the export collector can't resolve as exporting everything |
| `fb23` | open | FIXME | normal | - | [`src/byteplan/release.py:460`](src/byteplan/release.py#L460) | Keep a restored runtime import above every use of its names |
| `c242` | open | FIXME | normal | - | [`src/byteplan/release.py:467`](src/byteplan/release.py#L467) | Check the current binding before restoring a decorator |
| `b68c` | open | FIXME | normal | - | [`src/byteplan/release.py:532`](src/byteplan/release.py#L532) | Restore an unanchored import below the current docstring and __future__ imports |
| `fd44` | open | FIXME | normal | - | [`src/byteplan/release.py:541`](src/byteplan/release.py#L541) | Keep anchored imports below a __future__ import added since the release |
| `46b6` | open | TODO | normal | - | [`src/byteplan/scanner/comments.py:70`](src/byteplan/scanner/comments.py#L70) | Recognize Google-style `TODO(owner): ...` tags |

## Closed

| ID | Status | Kind | Title |
|---|---|---|---|
| `14ff` | resolved | TODO | Phase 7: cleanup |
| `2887` | resolved | TODO | Phase 6b: test scaffolding |
| `4fb5` | resolved | TODO | Update the status line for the next release |
| `6639` | resolved | FIXME | Keep runtime imports that __all__ re-exports |
| `6b83` | resolved | FIXME | Keep sync's top-level JSON fields when only cleanup runs |
| `82b3` | resolved | TODO | Phase 5: runtime and normalization |
| `9185` | resolved | FIXME | Keep the space between words around an inline Markdown comment |
| `9b40` | resolved | TODO | Phase 6a: acceptance tests |
