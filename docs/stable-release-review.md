# Full-scope review: priorities for 1.0

Reassessed against `e0b6631`, after the MCP and integration changes. All eleven
findings remain applicable. Release priority reflects the effect on users and the
guarantees BytePlan makes, rather than the original review severity alone.

| Release priority | Task | Impact | Regression coverage |
| --- | --- | --- | --- |
| Blocker / high | `8c7f` | Scanning can modify a custom decorator and break imports. | Binding forms, nested namespaces, and a writing scan followed by import. |
| Blocker / high | `ff20` | Browsing an older branch can permanently erase local verification evidence. | Branch round trip, restoring evidence, and migration of the existing SQLite store. |
| Blocker / high | `ecf4` | Cleaning up a resolved task can delete an import consumed by another module. | Direct, relative, wildcard, and module attribute consumers. |
| Blocker / high | `5aae` | A scaffold can replace an existing conditional test and remove its coverage. | Execute the existing conditional test after generating the scaffold. |
| Blocker / high | `ed2b` | Staged reconciliation can invalidate an interrupted ordinary transaction. | Both hook modes refuse without writes, then ordinary recovery succeeds. |
| Blocker / high | `98d6` | Skipped or xfailed teardown can become passing acceptance evidence. | Real pytest fixture finalizers calling skip and xfail. |
| Required before stable / normal | `1e7f` | The explicit release guard permits runtime decorators with dynamic arguments. | Real wheel and sdist builds with dynamic todo and verifies arguments. |
| Required before stable / normal | `ac9d` | Nested projects cannot verify valid linked tests with an ancestor pytest root. | Passing tests and collection errors through a real pytest subprocess. |
| Required before stable / normal | `ae7a` | Incorrect Git ignore precedence silently omits included source. | Working-tree and index snapshots, including excluded-directory behavior. |
| Required before stable / normal | `a740` | A named pipe in scope can hang scans and commit hooks indefinitely. | Source selection and a complete scan with a FIFO present. |
| Follow-up / low | `30c3` | Duplicate repair fails on valid whitespace or string literal spelling. | Spaced, multiline, concatenated, and escaped IDs; title text stays intact. |

The low-priority repair fix is included because the change is small and directly
covered by regression tests. These fixes preserve task IDs and managed fields.
The archive migration retains existing records and evidence; versioned records
are selected by the hash in the committed archive index.

PR #43's review follow-up `ff72` is also required before stable: node-ID normalization
must preserve linked symlink names. Eight regression cases cover file and directory
aliases, project and ancestor pytest roots, and passing tests and collection errors.

Regression tests in `tests/test_stable_review.py` link back to each task with
`@verifies`. The committed task registry records release priorities and resolution
notes. Passing these regressions addresses this review's findings; the remaining
1.0 scope and release process still require their own assessment.
