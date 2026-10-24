# RC1 A4 merge acceptance

This assessment covers plain-Git merge compatibility (`edc2`) and the schema-1/schema-2
merge improvement (`ee606e`) on the compatibility branch after `8e82980`. It is a focused
acceptance review, not either final independent whole-repository review.

## Contract and disposition

Keep the custom registry driver recommended and optional. A successful automatic merge must
retain compatible authoritative work; competing lifecycle values, identity collisions, rewritten
history or incompatible extension metadata require explicit conflict resolution. Ordinary Git
may conflict even when the custom driver can combine records safely. The conflict itself is
not data loss: the original records and evidence remain recoverable in the branch commits.

The v1-to-v2 migration changes a compatibility boundary rather than task semantics. The driver
can therefore combine supported versions using schema 2, retaining legacy identities and newer
six-character identities. The supported migration is explicit and transactional before writing
expanded annotations. Unsupported/future schemas and schema-1 records containing expanded IDs
are rejected by the driver loader, which validates each input independently before merging.
Do not generalize the current version-selection rule to a future semantic schema migration
without revisiting those migration semantics and tests.

## Acceptance evidence map

| Requirement | Coverage and observed assertion |
|---|---|
| Independent tasks on divergent branches | `test_merge.py::test_driver_merges_parallel_tasks` combines distinct records; its plain-Git control conflicts explicitly. |
| Independently migrated branches / one migrated side | `test_rc1_merge_acceptance.py::test_divergent_git_merge_across_schema_migration` covers both branch orientations, either or both branches migrated, driver enabled/disabled (8 cases). The shared legacy task retains both histories and independent status/priority edits, a legacy addition and a six-character addition survive, reservations are unioned, and committed evidence remains unchanged. Driver cases must succeed; plain Git may preserve an explicit conflict. |
| Colliding task identities | `test_compatibility.py::test_divergent_branch_identity_collisions_fail_explicitly` checks both driver settings and both original records in Git. `test_collision_recovery.py::test_premerge_rekey_preserves_both_original_records` exercises explicit recovery with old/new IDs and LF/CRLF checkout conversion. |
| Independent history and lifecycle updates | `test_merge_integrity.py::test_real_git_histories_and_lifecycle_states` covers driver/plain Git, LF/CRLF and independent/competing lifecycle updates. Successful merges retain event prefixes and all appended events; competing states conflict. Unit cases in `test_merge.py` reject rewritten history. |
| Verification evidence conflicts | `test_merge_integrity.py::test_real_git_verification_evidence_merge` covers independent and same-task runs with both driver settings. Success retains task entries and their exact run metadata; failure remains detectable and both original payloads remain in Git. `test_collision_recovery.py::test_rekey_then_merge_preserves_both_branches_evidence` adds identity-recovery coverage. |
| Malformed JSON, markers, duplicate keys and partial resolutions | `test_compatibility.py::test_check_rejects_inconsistent_merge_records_without_writes` exercises task/evidence/archive JSON. `test_rc1_merge_acceptance.py::test_driver_rejects_invalid_migration_inputs` covers each driver input with future schema, incomplete JSON, Git markers, duplicate keys and expanded identities under schema 1 (15 cases); driver returns failure and preserves base/theirs. |
| Syntactically valid but incomplete manual resolution | `test_rc1_merge_acceptance.py::test_valid_json_partial_resolution_reports_discarded_task` removes one registry record while retaining its annotation. Working-tree check reports an actionable unregistered-ID diagnostic; staged and committed checks fail. All checks preserve files/index and the complete original record remains recoverable from the preceding commit. |
| Correct selected snapshot | `test_compatibility.py::test_staged_check_validates_staged_evidence_not_worktree` rejects damaged staged evidence even when the working-tree copy is valid. Snapshot consistency cases cover registry/source agreement independently of the working tree. |
| Extension metadata and evidence integrity | `test_merge_integrity.py` covers nested test/source/stub extensions, independent changes, competing values, null/absent deletions and actual driver roundtrips. `test_evidence_integrity.py` rejects incomplete provenance and preserves run identity, archived evidence and opaque metadata. |

## Operational limits and recovery

The registry driver does not merge the separate evidence store semantically; ordinary Git may
need manual resolution there. Preserve task entries together with every referenced run and
extension field. `byteplan check` rejects malformed or internally incomplete payloads, while
readiness requires matching current fingerprints and valid provenance. A historical pass is
not a substitute for fresh verification after relevant changes.

Working-tree checks retain their existing configurable policy: an unregistered source identity
is reported, but is not necessarily a nonzero exit. Use `byteplan check --staged`,
`byteplan check --commit HEAD`, or `[tool.byteplan.check] require_reconciled = true` when
requiring source/registry consistency. This is a compatibility policy, not an implicit
source-writing reconciliation. Checks do not mutate source, registry or index.

The merge driver's intentional fallback may write ordinary conflict markers into its `ours`
file before returning failure; this differs from read-only checking. Do not claim that a failed
driver leaves its output untouched. Base and incoming inputs remain unchanged and Git retains
the original branches. Preserve needed resolution work before using Git to abort a merge;
BytePlan's identity-repair command itself does not abort, stage or switch branches.

A manually chosen, structurally valid lifecycle value cannot reveal an unrecorded human
intention from the losing side. Review competing obligations and retain their histories/evidence
when resolving conflicts. Automated checks validate the resulting repository state; they do
not certify that an arbitrary manual choice fulfilled both branches' intent.

## Validation result

The focused matrix passed **233 cases in 110.64 seconds** on Linux/Python 3.12, running
`test_merge.py`, `test_merge_integrity.py`, `test_rc1_merge_acceptance.py`,
`test_compatibility.py`, `test_collision_recovery.py` and `test_evidence_integrity.py`.
The new acceptance file contributes 24 cases. Strict typing and the repository's Ruff
lint/format checks pass for that file. Log: `/tmp/rc1-a4-acceptance.log` in the execution
workspace. Cross-platform CI for the final increment remains required.

The command used an absolute `PYTHONPATH` pointing at this checkout's `src` so Git-driver
subprocesses operating in temporary repositories also exercised the new implementation.
An initial relative `PYTHONPATH=src` invocation instead imported the preceding editable
checkout in those subprocesses and correctly failed the four new driver migration cases;
that environment-selection issue is not a product regression.

No unresolved release blocker was demonstrated in this focused matrix. Task closure still
requires fresh linked verification and explicit resolution through BytePlan; this documentation
does not itself close `edc2` or replace either final release review.
