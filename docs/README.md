# BytePlan documentation

Start with the [project README](../README.md): installation, the task lifecycle, every command,
configuration, Git and Hatch integration, and the MCP server.

## Guides: for people and agents using BytePlan

| Guide | What it covers |
|---|---|
| [CI and Git hooks](guide/ci.md) | Read-only checks in pre-commit and CI, IDs at commit time, and keeping `report_file` current on `main` |
| [Compatibility policy](guide/compatibility-policy.md) | What 1.x keeps stable: CLI, Python API, configuration, decorators, MCP, Hatch and Git |
| [Migration and recovery](guide/migration.md) | Upgrading registries to schema 2, behavior of older clients, merge and collision recovery |
| [Source safety](guide/source-safety.md) | Which commands write, how to adopt BytePlan safely, and the limits of crash recovery |
| [Storage](guide/storage.md) | The registry, evidence and archive files, what is authoritative, and how each is recovered |

## Development: for contributors

These are design and process records, kept on GitHub and excluded from the sdist.

- [Specification](development/spec.md) and addenda [A](development/spec-addendum-a.md),
  [B](development/spec-addendum-b.md), [C](development/spec-addendum-c.md),
  [D](development/spec-addendum-d.md) and [E](development/spec-addendum-e.md) (RC1 hardening and the
  1.5/2.0 roadmap)
- [Implementation plan](development/IMPLEMENTATION_PLAN.md), including the remaining phases as tasks
- [API architecture](development/api-architecture.md): the public facade and its internal operations
- [RC1 release records](development/rc1/readiness.md): the readiness report, the review gate and
  findings, and the [review reports](development/rc1/reviews/)

See [CONTRIBUTING](../CONTRIBUTING.md) for how BytePlan tracks its own development.
