# Independent whole-repository RC1 review: Claude

Reviewed revision: **a5de5c861382a61cf2ca38c093e8268f401f82c3**: the commit that first adds
[the gate instructions](../gate-check.md). Its parent is the baseline
`2c2b1ae2e38271097d9943155819055e2bf8db82`.

I reviewed a detached clone of that SHA and never modified it. I wrote this report and registered
the findings before reading any post-gate conclusions from Codex. Findings, regression tests and
task records are on the follow-up branch `review/rc1-a5de5c8-claude`, whose base is the gate SHA.

## Verdict

**Do not approve this revision for RC1.**

- **P1 (security, 53c751):** a transaction journal committed to the repository is "recovered" by
  ordinary write commands. That is an arbitrary file write inside the project tree, and with a
  project virtualenv it executes code.
- **P2 (source integrity, e3d6bd):** annotation cleanup can delete user text.
- **P3:** four polish and documentation findings.
- **No P0 was demonstrated.**

The registry, merge, ID, lock and scanner changes since the previous reviews held up under the
probes below.

## Findings

### 53c751: P1, a committed transaction journal is recovered by ordinary write commands

**Location:** `src/byteplan/persistence.py` `recover` (called by `Project._writing` before every
write). `gitwrite._recover_locked` has the same shape for the staged journal.

**Trigger:**
1. A repository commits `.byteplan/txn/journal.json` and `.byteplan/txn/0.stage`. A force-add
   gets past the `txn/` rule in `.byteplan/.gitignore`.
2. The journal entry targets an absent path, with `before: null` and `after` set to the stage's
   hash.
3. The user clones the repository and runs `byteplan scan`, or any write command such as
   `resolve`, `status`, a Hatch build with `write_source`, or `scan --staged --apply` for the
   staged variant.

`recover` validates the paths and hashes, then writes the payload. The CLI prints only
`completed an interrupted write to 1 file(s)`.

**Demonstration (installed rc1 wheel):** the journal targeted
`.venv/lib/python3.11/site-packages/sitecustomize.py`. After `python3 -m venv .venv` and
`byteplan scan` in the fresh clone, `.venv/bin/python -c "print('hello')"` printed
`PWNED: sitecustomize ran` first. The regression
`tests/test_persistence.py::test_a_journal_from_the_repository_is_never_recovered` is a strict
xfail that reproduces it with `.venv/planted.py`.

**Impact:**
- The README says "listing, searching and scanning never execute project code", and Addendum E
  item 7 lists untrusted repository inputs.
- Through this path, a plain scan of a cloned repository can create any absent file under the
  project root. That includes ignored or untracked paths the clone never contained, such as
  virtualenvs, `.env` files and tool configuration.
- Existing files are overwritten only when their hash is predictable.
- `.git/` is protected, and so are the MCP read-only server and Hatch check mode, which don't
  recover outside their allowed targets.

**Bounded fix:**
- Recover only journals this clone wrote. For example, record the journal's hash under the Git
  directory (`git rev-parse --git-path byteplan-txn`) when committing it, and require a match
  before recovery.
- Refuse a journal or stage that Git tracks.
- Limit recoverable targets to the registry, evidence store, report file and in-scope source
  files.
- Apply the same rules to the staged journal.

### e3d6bd: P2, cleanup indexes physical lines with `str.splitlines`

**Location:**
- `src/byteplan/cleanup.py` `_drop_unused_runtime_imports`.
- `src/byteplan/release.py` `_lines`, used by strip and restore.
- `src/byteplan/scaffold.py` `plan` (existing-file import insertion).

**Trigger:** `str.splitlines` also breaks at `\f`, `\v`, `\x1c`–`\x1e`, `\x85`, U+2028 and U+2029.
Python doesn't, so `ast` line numbers point at the wrong list entry. `edits.physical_lines`
exists to avoid exactly this.

**Demonstrations:**
- With `# note<U+2028>more words` above `from byteplan_runtime import todo`,
  `resolve --sync-source` produced `# note<U+2028>from byteplan_runtime import todo`. The
  user's comment text "more words" was deleted, and the import was merged into the comment.
  The AST and round-trip checks both pass, because a runtime import is allowed to disappear.
- With a form-feed page-break line above the import, cleanup removed the newline after `\f`,
  left the import in place, and still reported "unused runtime import" as removed.
- `byteplan release` refuses the first file with a false "@todo shares its line with other code".
- Scaffold insertion is caught by `ensure_only_added`, so it fails closed.
- The regression is
  `tests/test_cleanup.py::test_cleanup_removes_the_runtime_import_with_python_line_breaks`
  (strict xfail, both cases).

**Impact:** silent loss of user-authored text, and a false report, in an authorized source edit.
The trigger characters are uncommon, although form-feed page breaks do occur in older code.

**Bounded fix:** use `physical_lines` (or `line_offsets`) in all three modules, and keep the
regression.

### aaf7d7: P3, lock release unlinks whatever lock is present

`project_lock`'s `finally` unlinks `.byteplan/scan.lock` without checking that it is the lock
this process created. Suppose the lock is deleted by hand while its writer still runs, which the
new guidance invites when a writer is believed dead, and a second writer then takes it. When the
first writer exits, it removes the second writer's lock, so a third writer can run concurrently.

This is the same race that motivated removing automatic reclamation. The trigger requires a
mistaken manual deletion. Fix by comparing `st_dev`/`st_ino`, or a per-acquisition token, before
unlinking. Regression: `tests/test_persistence.py::test_lock_release_leaves_a_later_writers_lock`
(strict xfail).

### 7140aa: P3, CHANGELOG omits the user-visible changes from #53 and #54

`Unreleased` lists only #51 and #52. It is missing three changes:
- Stale locks are never reclaimed automatically. POSIX users previously had dead-PID locks
  removed; now they must delete them.
- Unclosed `[id` brackets now produce a `malformed_id` warning.
- Merge-driver installation now checks every destination first and quotes attribute patterns.

The `1.0.0rc1` section also still describes 67a65c as open.

### 971b9d: P3, the spec still describes case-insensitive tag discovery

`docs/spec.md` §3 and `docs/IMPLEMENTATION_PLAN.md` (the tag regex near line 187) predate 415a0f.
Now only the configured spelling matches bare; other spellings need `:` or `[id]`.

### e8bd84: P3, 15 diagnostic codes are undocumented

The compatibility policy makes diagnostic codes machine API, but 15 values of
`byteplan.diagnostics.Code` appear nowhere in the README. They include `malformed_id`,
`unregistered_id`, `pending_journal`, `release_stripped` and `scaffold_placeholder`.

### Not registered

`fd02a3` (record the frozen tag commit) duplicates `a70d` (RC1 readiness evidence), which the gate
names as the tracking task. I suggest dismissing `fd02a3` in favor of `a70d`. That's a lifecycle
decision for the owner, so I left it unchanged.

## Probes that found no defect

- **Unclosed-bracket grammar (#53):** Python, Markdown, JSONC line, block and string forms;
  `]` later in the text; brackets after whitespace. Valid tags are unchanged, and the unclosed
  form is diagnosed, never allocated.
- **Merge-driver attribute quoting (#53):** 13 adversarial basenames, checked with
  `git check-attr` (Git 2.51.0). They covered spaces, `[]*?`, a leading `#` or `!`, quotes,
  backslashes, tabs, leading or trailing spaces, and non-ASCII. Each matched only its own file;
  near-miss probes such as `axxb.md` for `a*b.md` stayed unspecified.
- **No automatic stale-lock reclaim (#54):**
  - A planted `scan.lock` with a dead PID blocks writes with the documented message.
  - `check` and `scan --dry-run` still work, and the lock stays untracked.
- **Six concurrent writing scans over 20 new TODOs:** one won, the other five failed cleanly with
  `locked`, and a final scan and `check` were clean. All 20 IDs were unique and registered.
- **Collision repair in a subdirectory project:** `git rev-parse --git-path index` is resolved
  against the project root correctly.
- **Docs and CLI:** the README command table and `byteplan --help` match exactly.
- **Config:** `report_file` and `registry` are confined to the project and to `.md`/`.json`.

## Commands and results at the gate SHA

All commands ran in a detached clone with CPython 3.11.0 on macOS.

| Check | Result |
|---|---|
| `hatch fmt --check` | 124 files already formatted |
| `hatch run types:check` | no issues in 123 source files |
| `byteplan check` | 159 files, 0 errors, 0 warnings, 0 info |
| `hatch test` (3.11) | 1,742 passed, 2 skipped, 3 deselected |
| `hatch test -m network` | 3 passed |
| Tree after the tests | clean |
| Scan dry run | +0 added, ~0 relocated, nothing written |
| `hatch build` | all four distributions built |
| Clean wheel install | `byteplan --version` reports 1.0.0rc1. `init`, preview, `scan`, `check` and `list` worked. MCP stdio: `initialize`, read-only `tools/list` (12 tools) and `missing` succeeded; `scan(apply=true)` was refused without `--allow-source-write`. A Hatchling build with `[tool.hatch.build.hooks.byteplan]` reported `byteplan check (wheel): 1 files, 2 tasks`. |
| Clean sdist install | succeeded. The sdist contains no `docs/reviews` or `rc1-next-steps.md`. The wheel metadata declares only the CPython implementation and `Requires-Python >=3.11`. |
| Gate CI run `40546275232` | all 15 jobs passed (CPython 3.11–3.14 on Linux, macOS and Windows, plus the released-client, quality and consistency jobs) |

Artifacts built at the gate SHA:

| File | SHA-256 |
|---|---|
| `byteplan-1.0.0rc1-py3-none-any.whl` | `f708b6e840a928d8ead8c91430ca2f35188f0880f7237fa6fef5558c240edb95` |
| `byteplan-1.0.0rc1.tar.gz` | `928152390a52a01786abf1919db829193b645380609fb9233c7b9b405be54eec` |
| `byteplan_runtime-0.1.0-py3-none-any.whl` | `ea09ff29453e3ddf99bcdb294f800be5cb4bc5d0276941dab213fdb33ebb1c94` |
| `byteplan_runtime-0.1.0.tar.gz` | `19de333d1e04862f449e7055a60ef635484bd8f718246b46efc9a94a19f8d22b` |

The runtime artifacts are byte-identical to the `b551870` reference build.

**Limits:**
- I ran the local suite only on CPython 3.11 on macOS; the other Python versions and Windows are
  CI evidence.
- I didn't run the released-client matrix locally.
- I reviewed the whole repository, reading most deeply the write paths, recovery, scanner grammar,
  merge, locking, cleanup and release. I skimmed reporting and the CLI formatting code.

## Reconciliation with the Codex review

This section was written after both initial reports were recorded. Commit `e612b67` holds the
initial report above, unchanged.

- **Overlap:** none. Codex's three P2s (515d45 scaffold bindings, 6698e7 Windows verify timeout,
  26756c snapshot path aliases) and these six findings are distinct. Codex's scaffold finding and
  e3d6bd both touch `scaffold.plan`, but for different causes: name shadowing versus
  physical-line indexing.
- **Blockers:** the reviewers disagree. Codex reports no P1. This review reports 53c751 as a
  P1 security blocker, so the gate's agreement condition (no unresolved blocker from either
  reviewer) is not met.
- **Artifacts:** both reviews built byte-identical wheel and sdist hashes at the gate SHA
  (`f708b6e8…db95`, `928152390…4eec`).
- **Local suite:** Codex's full Linux run had one timeout in
  `test__verify_plugin.py::test_verification_preserves_symlink_node_ids[passed-directory-False]`,
  which passed when rerun alone. This review's full macOS run passed that case. Neither result
  establishes the cause.
