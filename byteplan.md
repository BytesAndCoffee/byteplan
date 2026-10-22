# BytePlan

<!-- Generated from .byteplan/tasks.json by BytePlan; don't edit. `byteplan scan` and the commit hook keep it current. -->

**19 open** · 8 closed (resolved 8)

## Open

| ID | Status | Kind | Priority | Assignee | Where | Title |
|---|---|---|---|---|---|---|
| `de66` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1532`](docs/IMPLEMENTATION_PLAN.md#L1532) | Phase 6c (optional): acceptance criteria and dependencies |
| `0413` | open | TODO | normal | - | [`docs/IMPLEMENTATION_PLAN.md:1536`](docs/IMPLEMENTATION_PLAN.md#L1536) | Phase 8: release stripping |
| `f853` | open | TODO | normal | - | [`docs/IMPLEMENTATION_PLAN.md:1540`](docs/IMPLEMENTATION_PLAN.md#L1540) | Phase 9: MCP server |
| `93dd` | open | TODO | normal | - | [`docs/IMPLEMENTATION_PLAN.md:1544`](docs/IMPLEMENTATION_PLAN.md#L1544) | Phase 10: integration |
| `75b4` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1548`](docs/IMPLEMENTATION_PLAN.md#L1548) | Phase 11 (optional): spec section 14 phase 5 items |
| `9054` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1551`](docs/IMPLEMENTATION_PLAN.md#L1551) | Phase 11b (optional): Git reporting |
| `15df` | open | TODO | normal | - | [`docs/IMPLEMENTATION_PLAN.md:1554`](docs/IMPLEMENTATION_PLAN.md#L1554) | Phase 12: assignment model (Addendum D stages D0-D2, D4) |
| `ec99` | open | TODO | low | - | [`docs/IMPLEMENTATION_PLAN.md:1558`](docs/IMPLEMENTATION_PLAN.md#L1558) | Phase 13 (optional): relay-for-github |
| `90c6` | open | FIXME | normal | - | [`src/byteplan/api.py:412`](src/byteplan/api.py#L412) | Don't propose stub tasks for declarations whose @todo is stripped for a release |
| `205d` | open | FIXME | normal | - | [`src/byteplan/api.py:1098`](src/byteplan/api.py#L1098) | Check for a pending journal before the write context recovers it |
| `4d48` | open | FIXME | normal | - | [`src/byteplan/api.py:1234`](src/byteplan/api.py#L1234) | Keep decorators pending when their runtime import can't be restored |
| `a6b2` | open | TODO | normal | - | [`src/byteplan/config.py:266`](src/byteplan/config.py#L266) | Support detect.placeholder_assignments |
| `aedf` | open | FIXME | normal | - | [`src/byteplan/release.py:96`](src/byteplan/release.py#L96) | Check every runtime import, not just decorator bindings, before skipping a file |
| `34da` | open | FIXME | normal | - | [`src/byteplan/release.py:108`](src/byteplan/release.py#L108) | Respect enclosing scopes before stripping a decorator |
| `c8db` | open | FIXME | normal | - | [`src/byteplan/release.py:159`](src/byteplan/release.py#L159) | Keep runtime imports that other modules consume through re-exports |
| `a703` | open | FIXME | normal | - | [`src/byteplan/release.py:281`](src/byteplan/release.py#L281) | Refuse wildcard runtime imports, whose bindings can't be proven unused |
| `c242` | open | FIXME | normal | - | [`src/byteplan/release.py:368`](src/byteplan/release.py#L368) | Check the current binding before restoring a decorator |
| `b68c` | open | FIXME | normal | - | [`src/byteplan/release.py:403`](src/byteplan/release.py#L403) | Restore an unanchored import below the current docstring and __future__ imports |
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
