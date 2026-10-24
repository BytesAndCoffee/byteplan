# BytePlan 1.0 public compatibility policy

This document defines the compatibility boundary for the 1.0 release and its release
candidates. It does not declare the current alpha release or an unreviewed checkout ready for
production. [Addendum E](spec-addendum-e.md) retains the RC1 acceptance and approval gates.

Within 1.x, supported public interfaces keep their existing names, accepted arguments,
return meanings and safety defaults. New optional arguments, configuration options, diagnostic
codes and output fields may be added. Consumers must tolerate additional JSON object fields
and diagnostic codes; human-readable prose, whitespace and presentation are not machine APIs.
Correctness fixes may reject malformed input or invalidate unsupported verification claims;
they must explain recovery and preserve valid authoritative work.

## Stable interfaces

| Surface | 1.0 compatibility commitment | Limits |
|---|---|---|
| Source annotations and task identity | Python task comments and supported stub discovery, Markdown task comments, JSON/JSONC annotations, configured tags, suppressions, `@todo` and `@verifies`. Existing four-character lowercase hexadecimal IDs remain valid; new allocations have six characters; longer supported IDs remain valid. Persisted references use the complete identity. Exact lookup wins before unambiguous UI prefixes. | IDs are project-local, not globally unique. Collisions require explicit reconciliation. Static discovery does not import the project; uncertain dynamic decorators and unsafe edits produce diagnostics. Stub detection remains a documented heuristic. |
| Authoritative task lifecycle | Managed status, labels, assignee, priority, notes and history; permanent reservations; explicit resolution; source presence distinct from lifecycle; verification and evidence freshness rules. Unknown supported extension fields round-trip. | Removing an annotation or passing a test does not resolve a task. A recorded historical pass is not fresh evidence after relevant changes. Missing archived evidence cannot be reconstructed as a passing result. |
| Registry and migration | Versioned registry/evidence validation, deterministic serialization, explicit journaled migration, source-editing guards and recoverable writes. Existing valid tasks, history and evidence survive supported migrations. Unsupported future schemas fail visibly. | Compatibility does not mean every older binary can read newer schemas. Upgrade clients before migration and incompatible annotations. Physical indexes/caches are distinct from authoritative task records; see the [storage decision](rc1-compatibility.md#intended-authoritative-storage-contract). |
| CLI | The documented command names, flags, defaults and exit meanings in the [command reference](../README.md#commands), including advanced scan/sync/scaffold/verify, repair, migration, archive and release/restore operations. `--format json` preserves existing field names/types/meanings; diagnostics remain on stderr. | Text/table/Markdown layout, generated test names and exact diagnostic wording can improve. Parse structured fields and exit codes instead. New JSON fields and findings may appear. |
| Python API | `byteplan.api.Project`, its existing public methods/properties and supported signatures, result types and exception semantics; details below. | Private methods, implementation dependencies and arbitrary imported names are not extension APIs. The required RC1 decomposition preserves existing behavior and tested patch targets even where they are internal. |
| Configuration | Documented `[tool.byteplan]` sections and options, defaults, accepted values, project-relative path rules and strict unknown-key rejection. `byteplan.config.Config`, its section dataclasses, and `load_config` support programmatic configuration and the documented custom Hatch integration. | A future optional feature may require new configuration. Unknown options still fail rather than silently doing nothing. No interface promises that unsupported settings such as `placeholder_assignments=true` will work. |
| Runtime decorators | `byteplan_runtime.todo(title, /, *, id=None, kind="TODO", description="", test=None, tests=())` and `verifies(*ids)` retain their parameters and inert identity behavior. Generated runtime shims provide the same decorators. | Runtime markers do not validate or register tasks. Scanner acceptance is static and separately checked. `byteplan-runtime` remains a separately versioned distribution with its own supported Python versions. `byteplan.api` does not export runtime decorators. |
| MCP protocol | The documented stdio entry points, existing tool names/arguments, resources, structured result fields and permissions in the [MCP reference](../README.md#mcp-server-for-ai-agents). Source-writing tools preview unless `apply=true`; source writes and project-code execution require their documented permissions. | Additional tools/result fields may be introduced. Protocol consumers must negotiate capabilities and handle unavailable tools. Restart/reconnect long-running servers after upgrading or checking out code they need to load. A restart cannot add unsupported schema support to an old installation. |
| Hatch and Git integration | Hatchling `byteplan` build-hook entry point and documented hook settings; supported custom-hook example; published pre-commit hook IDs, direct-hook modes, staged snapshot semantics and merge-driver command contracts. | Hatch builds check without source writes by default. Installing hooks/drivers changes per-clone configuration explicitly. Ordinary Git may produce explicit conflicts; no merge driver can choose competing authoritative states on a user's behalf. Reinstall a driver after recreating its Python environment. |
| Documented extension points | Custom runtime modules via `annotations.runtime_modules`, manual pytest node links, configured pytest runner and scaffold options, release smoke commands, `report_file`/`report_branch`, and the custom Hatch integration. | These are configuration/integration contracts, not a general scanner, storage or lifecycle plugin API. User-provided runners and smoke commands execute project code only when their execution is requested. |

Advanced shipped commands are included in this boundary. Their optional nature does not make
task identity, source safety or authoritative state experimental.

## Python API inventory

Import the facade from `byteplan.api`, data models from `byteplan.models`, configuration from
`byteplan.config` and exceptions from `byteplan.errors`. `Project.open()` discovers the project
from the current directory; an explicit start is a `pathlib.Path`. `Project.open_snapshot()`
provides a read-only index or commit view, and `close()` releases its Git reader. The supported
`Project(config, clock=..., snapshot=..., notices=...)` constructor and existing methods retain
their signatures during decomposition.

Snapshot projects support scanning, checking, active-registry queries, reports and recorded
verification queries using the selected Git data. They reject mutation and test execution
before side effects. Source-operation and archive previews that require working-tree state,
and archived-task/cache reconciliation, require a normal working-tree `Project`. File-mode
freshness uses selected source/test bytes. Commit-mode HEAD freshness uses the selected commit;
an index snapshot cannot establish committed HEAD freshness and reports that uncertainty
instead of claiming verification from the current working tree.

| Group | Public methods and properties retained |
|---|---|
| Construction and context | `open`, `open_snapshot`, `close`, `config`, `clock`, `snapshot`, `root`, `enforce_consistency` |
| Registry and reports | `load_registry`, `registry_rel`, `report_rel`, `maintains_report`, `render_report`, `write_report`, `migrate`, `exit_code` |
| Discovery and queries | `scan`, `check`, `report`, `list_tasks`, `get_task` |
| Lifecycle and repair | `set_status`, `edit_task`, `import_task`, `reassign` |
| Verification and scaffolding | `runner`, `readiness`, `verify`, `ready`, `link_tests`, `unlink_tests`, `scaffold_test` |
| Source operations | `runtime_module`, `sync`, `cleanup`, `stripped_release`, `release_version`, `release`, `restore` |
| Archive | `archive_index_rel`, `archive_index`, `archived_task`, `archive`, `restore_archived`, `reconcile_archive` |

The facade also retains `init_project`, `shim_module_name` and the `UNSET`
sentinel used to distinguish omitted edits from explicitly cleared fields. Public result imports
remain available: `Proposal`, `ScanReport`, `TaskVerification`, `VerifyReport`, `ScaffoldResult`,
`ReleaseReport`, `RestoreReport`, `CleanupReport`, `SyncReport`, `ArchiveReport`, `ReconcileReport`,
`RepairResult` and `InitResult`. Existing result fields, their types and meanings are preserved;
new fields need backward-compatible defaults. Existing task/model enum values, diagnostic
code/severity values and the `Diagnostic`/`Location` structured fields are part of returned data.

The public `byteplan.errors` hierarchy remains available: `ByteplanError`, `ConfigError`,
`RegistryError`, `SourceError`, `ScanError`, `IdExhaustedError`, `TaskNotFoundError`, `EditError`,
`LockedError`, `ConcurrentModificationError` and `JournalConflictError`. Their existing structured
attributes remain usable. Error messages may gain actionable detail. At the CLI, these exceptions
map to exit 2; policy findings map to exit 1 and successful execution to exit 0. Findings and successful
verification are separate from explicit task resolution.

The facade refactor must inspect monkey-patching before moving dependencies. For example,
`tests/test_persistence.py` currently patches `byteplan.api.commit`; preserving that behavior is
a required refactor regression, not a promise that every name imported into `api.py` becomes a
permanent plugin hook. Subclassing private operations, replacing internal module globals, direct
mutation of serialized registry dictionaries and local SQLite tables are outside the supported
extension boundary. Use supported operations for writes.

## Experimental embedding and deferred architecture

**Experimental Python MCP embedding:** `byteplan.mcp_server.build_server` and `Permissions`
are available for in-process use, but their SDK-specific return objects, server registration
internals and Python embedding lifecycle may change with the optional MCP SDK. Use the stable
stdio interface for integrations that need the 1.x protocol contract. This designation does not
weaken the permissions, source-safety or registry guarantees when using an embedded server.

Generated scaffold template bytes, automatic symbol attachment details, discovery heuristics
and internal module organization are implementation details. Valid test links, syntax safety,
non-passing placeholder behavior and documented scaffold options remain covered by the stable
contract. Correcting a heuristic may change which candidates are reported; it must not silently
resolve or discard their existing task records.

Assignments, Relay and the repository-wide semantic graph are proposed future architecture,
not shipped experimental commands. [Addendum D](spec-addendum-d.md) and
[Addendum E](spec-addendum-e.md) contain design candidates, not present public interfaces or
committed graph query names. Graph foundations target 1.5; graph intelligence and relevant
Assignment traceability target 2.0. None is required to write a TODO or included in RC1.

## Start small and opt in deliberately

Start with comments, `init`, `scan --dry-run`, a reviewed writing `scan` and the committed
registry. `check` is read-only. Existing schema-1 repositories must explicitly migrate before
new expanded identities are written. Stage or commit the migration boundary before staged
allocation. The [migration procedure and released-client matrix](rc1-compatibility.md)
describe upgrade and recovery limits.

Adopt decorators, acceptance links, scaffolding, hooks, MCP and release stripping as needed.
CLI `scan` normally writes, while `sync` normally previews. CLI scaffold, migration, repair,
archive, release and restore commands have their documented dry-run options; do not infer
preview behavior from their names. MCP has separate permissions and preview defaults.
Default Hatch checks do not opt a project into source rewriting. Hook installation is optional;
its default reconcile mode writes IDs at commit time, while check/scan modes support validation
or preview workflows. Read the [hook guide](ci.md) before enabling writes in existing projects.

Ruff/Hatch's TD004 rule expects a colon immediately after `TODO`, so `TODO[id]:` needs the
documented `lint.extend-ignore = ["TD004"]` setting. This does not require changing annotations
or disabling other lint rules. See [Linters](../README.md#linters). No automatic linter-config
rewrite is part of initialization.

## Review and change procedure

Compatibility changes need an explicit rationale, affected-interface inventory and regression
evidence. Schema changes need a migration and an older-client failure boundary, preserving
tasks/history/evidence and documenting recovery. Additive fields must not create conflicting
sources of truth. Breaking a stable 1.x interface requires a major-version boundary; normal
deprecation guidance should precede removal where feasible.

The RC1 API extraction is behavior-preserving: capture imports, signatures, result shapes,
exceptions, patch targets and CLI/MCP/Hatch/Git behavior before extraction, then compare after
it. See the [facade and internal operations architecture](api-architecture.md) for the module
boundaries and preserved constructor annotation/pickle identities. Final whole-repository reviews and the readiness report must assess this policy against the
same frozen revision. A policy document and passing individual tests do not substitute for
those release gates.
