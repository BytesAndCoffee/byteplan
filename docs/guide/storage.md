# RC1 authoritative storage decision and validation

Task `4842`; Addendum E A3, with archive durability defect `af82fd`.
Assessment baseline: `8e829805d2e950d31c1e2a6c746aa215ea143dc6`.
This decision does not introduce a physical layout migration or semantic graph implementation.

## Decision and authority contract

Retain the deterministic JSON task registry with embedded lifecycle history for 1.0. Its
schema-v2 compatibility boundary protects the expanded persistent-ID contract. Continue to
store current verification results and run provenance separately in committed
`.byteplan/verification.json`. A future physical layout change requires an explicit schema,
migration, recovery and interoperability decision; task identity must survive such a change.

| Record | Authority and persistence | Recovery and merge contract |
|---|---|---|
| `.byteplan/tasks.json` | Active task identities, managed fields, source observations and append-only lifecycle events. | Deterministic JSON; conservative semantic driver, or explicit plain-Git conflicts. Rebuildable observations do not authorize discarding managed metadata or history. |
| `.byteplan/verification.json` | Current per-task test results, source fingerprints, referenced run provenance and opaque extensions. | Commit evidence with the work. Current writes may supersede older results and prune unused runs; Git history preserves previously committed payloads. It is not an append-only event database. |
| `.byteplan/archive.json` | Committed index selecting each archived task record by canonical SHA-256; IDs remain permanently reserved. | Recover the exact task record from full Git history. Competing hashes require reconciliation, not arbitrary selection. The index does not contain test evidence. |
| `.byteplan/archive.sqlite` | Local compressed archive payloads: task records and any evidence/run retained by the originating clone. | Task records are rebuildable from committed registry versions. Verification is not automatically reconstructed in another clone. Preserve Git history and back up local storage when required; outside Git this can be the only archived copy. |
| External issue mappings | When introduced, managed authoritative metadata with canonical task IDs. No new integration schema is committed by this decision. | Preserve unknown same-schema fields. Future Assignment relationships must have explicit ownership, conflict and migration rules. |
| Reports, indexes and future graph cache | Derived views, not another owner of lifecycle state, identity or verification. | Rebuild from authoritative inputs. Graph uncertainty must never become evidence that work is verified. Graph implementation remains deferred beyond 1.0. |

Persist exact IDs in records and external mappings. UI prefixes are lookup conveniences;
neither task paths nor source line numbers become identity. Keeping record/history/evidence
roles separate allows later Assignment and graph work without forcing a storage redesign now.

## Alternatives considered

| Layout | Benefits | Collaboration, integrity and migration costs | RC1 disposition |
|---|---|---|---|
| Embedded lifecycle history | One task record carries its managed state and events; current transaction, migration and archive paths already support it. Stable ordering makes repeated serialization byte-identical. | Registry-wide parse/write cost; parallel additions or nearby edits can conflict under ordinary Git. Notes stored in historical edits contribute to growth. Conservative conflicts remain acceptable. | Retain. Validate successful merges preserve work and failed merges are explicit; do not rewrite historical events merely to reduce file size. |
| Separate append-only history | Could reduce routine task-file churn and permit independent historical processing. | Concurrent appends still conflict under plain Git. Requires event identities, cross-file transaction/reconciliation rules and evidence references, with a migration that preserves old clients' rejection boundary. | No measured RC1 benefit sufficient to justify migration. Revisit when collaboration or measured scale requires it. |
| Individual task records, history separated where useful | Independent task edits less often touch the same Git file; bounded per-record reads could improve large-scale queries. | More files, cross-record identity/reservation consistency, atomic multi-file updates, archive migration and ordinary-Git rename/deletion rules. Does not itself solve competing lifecycle values, task collisions or evidence conflicts. | No material current need demonstrated. Any future design must preserve exact identity, history and external mapping semantics. |

The semantic driver remains recommended, not a prerequisite for correctness. Plain Git may
require explicit conflicts for independently created tasks or competing histories/evidence.
See the [compatibility report](migration.md#merge-and-collision-recovery) and the
real-Git acceptance matrix in `tests/test_merge_integrity.py` and
`tests/test_collision_recovery.py`. A smaller file would not make a silently selected lifecycle
state safe; merge validation matters independently of layout.

## Measurements

At the assessment baseline the registry has **100 tasks, 541 lifecycle events and 335,233
bytes**. Replacing every history list with an empty list in memory and serializing through
the existing registry removes 181,252 bytes, **54.07%** of the file. This measures the
serialized history contribution, including its indentation, rather than summing event text
lengths. The remaining serialized metadata is 153,981 bytes. Notes and historical managed
edits legitimately repeat authored information; this measurement is not authorization to
delete or compress their meaning.

`scripts/benchmark_registry.py` constructs 1,000 and 10,000 deterministic synthetic tasks,
five events per task, source bindings, managed test links, labels and notes. Synthetic IDs
are format fixtures, not allocations in a repository. It validates parse/serialize round-trip
identity and reversed insertion-order identity, then merges different managed fields on
different tasks and checks both survive. It never edits a repository or writes a registry.

Measurements on Linux x86-64, CPython 3.12.14, three timed repetitions per operation:

| Synthetic tasks / events | JSON bytes | Parse and validate, median | Serialize, median | Exact lookup, median | Filter and sort, median | Three-way merge, median | Parse allocation peak |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1,000 / 5,000 | 2,115,647 | 63.092 ms | 93.784 ms | 0.001 ms | 0.113 ms | 61.709 ms | 7.493 MiB |
| 10,000 / 50,000 | 21,193,847 | 1,280.120 ms | 1,427.227 ms | 0.001 ms | 3.984 ms | 2,017.085 ms | 75.164 MiB |

Both sizes produced byte-identical round trips and insertion-order-independent output.
Synthetic history accounted for approximately 49.7% of serialized bytes. The larger case
shows a meaningful interactive cost, but no failure or loss requiring an RC1 migration.
These are bounded, single-machine observations under a shared development workload, not
latency guarantees. Timing excludes synthetic construction and merge-input deep copies;
the merge operates on already parsed dictionaries. `tracemalloc` measures incremental
Python allocations while parsing, excluding the previously allocated JSON input, and is
not process RSS. Filesystem, scanning, Git history traversal, archive compression and
network costs are not benchmarked. Deep or unusually large extension payloads can cost more.

Reproduce from the repository root, with the development environment active:

```console
git show 8e829805d2e950d31c1e2a6c746aa215ea143dc6:.byteplan/tasks.json > /tmp/byteplan-registry-baseline.json
PYTHONPATH=src python scripts/benchmark_registry.py --sizes 1000 10000 --repeats 3 --registry /tmp/byteplan-registry-baseline.json
```

Do not make a wall-clock benchmark a flaky CI correctness threshold. Reassess layout when
representative repositories show unacceptable measured operation cost, conflict frequency,
or an integrity risk that cannot be addressed within the existing contract.

## Confirmed archive durability flaw and bounded correction

The audit reproduced a distinct defect from the already documented absence of automatic
remote evidence reconciliation:

1. Resolve and remove a task annotation; scan and commit its complete closed task record.
2. Run verification after that commit, producing a new passing result and run provenance.
3. Archive the task before committing this evidence.

Before correction, archiving succeeded because only the task record was checked against
HEAD. It removed the uncommitted result from `.byteplan/verification.json`, leaving the sole
copy in ignored `archive.sqlite`. Deleting or losing that workspace lost evidence that had
never existed in Git. The same path was reachable through automatic archival during a writing
scan. This is a P1 durability defect, not a reason to redesign the whole registry.

The correction applies the same eligibility rule to direct, preview and automatic archival:
inside Git, the task record, its current evidence entry (if any), and that entry's referenced
run must match HEAD before removing them from the committed-file paths. Staging is not a
commit. Comparison uses canonical JSON so an opaque extension changing from `true` to `1`
does not count as equality. Unknown fields are included; unrelated tasks' evidence changes
do not delay an otherwise eligible task. Task records use the same type-sensitive check so
the archived record's hash can be recovered exactly from Git.

Git failures never grant the standalone-project exception when repository metadata or an
explicit `GIT_DIR`, `GIT_COMMON_DIR` or `GIT_WORK_TREE` selector is present. This includes
malformed configuration, unavailable Git, linked-worktree gitfiles and bare-repository metadata.
A plain, actually empty `.git` directory is ignored: it contains no repository metadata or
durable objects, and some execution sandboxes place such an empty marker in shared ancestors.
Files, symlinks, nonempty directories and uninspectable metadata do not receive that exception.
Invalid committed registry containers or schemas fail validation rather than being confused
with the outside-Git sentinel.

Evidence and archive-index transaction hashes come from the exact bytes parsed for the
archive plan. An external edit during Git reads or after index parsing is therefore detected
before canonical files are changed; rereading a newer baseline would otherwise authorize
overwriting unseen evidence. This closes the demonstrated reread-baseline gaps, not every
possible filesystem race between a hash check and atomic replacement.

An entry with no tests is still authored metadata and requires preservation. Tasks without
an evidence entry retain their existing archive behavior. Eligible tasks waiting for a
commit are returned through the existing `ArchiveReport.uncommitted`/CLI JSON field, without
changing the public return shape. CLI output tells the user to commit task records and current
verification evidence, including run metadata, then retry. Outside Git the existing local
archive/restore behavior remains; back up the SQLite store and working evidence because Git
cannot provide durability there.

Focused regressions in `tests/test_rc1_storage.py` verify:

- No writes when the only evidence copy is uncommitted, for preview and direct archive.
- Staged result, opaque entry, opaque run and run-provenance changes wait for a commit.
- Boolean/integer changes in unknown task fields cannot create an unrecoverable record hash.
- Metadata-only evidence is preserved; unrelated evidence changes do not block a task.
- Automatic archive keeps uncommitted evidence; non-Git archive/restore retains local payloads.
- A fresh clone recovers the exact task record without inventing absent verification.
- Git discovery failures and malformed committed registries fail safely; worktree, bare and
  explicit-selector contexts cannot bypass the guard. Empty sandbox markers retain standalone behavior.
- External evidence/index edits during planning are retained and produce transaction conflicts;
  unreadable current evidence keeps an actionable domain error.

The existing archive/evidence tests continue to assert local round-trip preservation and
run-ID collision handling. Three fixture setups now explicitly commit the evidence before
archiving; none of their preservation assertions were relaxed.

## Historical evidence recovery and known limits

In the originating clone, `archive --restore ID` restores the cached task, result and run
without claiming old fingerprints are fresh. In another clone, `archive --reconcile` or
`show ID` recovers the task record selected by the index's SHA. It does **not** recover the
verification payload automatically; readiness remains unverified until evidence is supplied
or tests are run. Absence of evidence must never be interpreted as a passing result.

After fetching full history, inspect the committed verification payload that predates the
archival change, for example `git show REV:.byteplan/verification.json`. Retain its task
entry and referenced run together when preserving an audit copy. The cross-clone regression
compares the recovered Git payload to the complete original entry and provenance; old
evidence is still available even though current reconciliation does not import it. Prefer
restoring the task and reverifying for a fresh result. Do not overwrite the current shared
evidence file wholesale with an old version: that can discard other tasks' newer results.

Shallow clones or rewritten/unavailable history may not contain the selected record. Fetch
the necessary history and retry; the existing command reports missing records explicitly.
The evidence safeguard prevents new local-only archival in Git repositories, but cannot
retroactively recover evidence already archived without a committed copy. Preserve existing
local SQLite archives until their contents have been audited or backed up.

## Restore transaction integrity follow-up

Task `50ad66` records an inherited P1 restore defect identified during the separate API
decomposition review. Before correction, `archive --restore ID` parsed verification and
archive-index data, then read those files again for transaction hashes. An external edit
between the reads became an accepted baseline even though the restore plan had never seen
it. Restoration could silently discard authored evidence or changes to another archive entry.

Restoration now captures each input's bytes once and uses those same bytes for parsing and
the transaction hash. It captures the index before lazy record lookup and checks that the
restored task and cached evidence refer to the same selected record. Competing input edits
raise the existing concurrency error while preserving external work, including a verification
file created after the plan observed its absence. Unreadable files produce actionable
configuration errors before canonical writes. Task lifecycle/history and evidence fingerprints
remain unchanged by restoration; colliding run identities still retain both provenance records.

Independent review also reproduced a P1 false-verification case through a supported workflow:
verify an archived identity again, then restore its task record. The older cached entry
replaced the current canonical result and could prune its referenced run. When a test fails
because its environment changed while its source bytes remain unchanged, the old passing
fingerprint still matches and restoration could incorrectly report `ready_for_review`.
Restoration now imports cached evidence
only when the current canonical store has no entry for that identity. Any existing entry wins,
including empty or metadata-only entries, equal entries, stale results and fresh failures.
No timestamp or pass/fail comparison chooses an authority. In that case the evidence file is
not rewritten at all, preserving its exact bytes, opaque fields, unreferenced historical runs
and external edits. The older payload remains available in the local archive and committed
Git history. Restoration still leaves task lifecycle decisions explicit.

`tests/test_restore_integrity.py` covers evidence/index edits, cache reconciliation, concurrent
file creation, an archive version changing and changing back during lookup, unreadable inputs,
opaque metadata, run collisions and stale evidence. The original evidence and index race
regressions fail against `0be125e` before the correction. This remains a bounded compatibility
fix with no storage-layout or public-signature change; it is integrated separately from the
behavior-preserving API decomposition.

The resulting contract supports ordinary Git collaboration and future mappings/Assignments
without a physical layout migration. Final independent repository reviews still need to
assess this implementation and its documented limits before RC1 approval.
