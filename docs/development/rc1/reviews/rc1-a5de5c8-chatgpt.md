# Independent RC1 review: ChatGPT (focused, non-Codex)

Review target: `a5de5c861382a61cf2ca38c093e8268f401f82c3` (the RC1 gate).

This is a third, focused review supplied by the project owner. Its reviewer could not clone or
run the repository; it read source through the GitHub connector and reproduced the underlying
filesystem operations in isolation. It is not one of the two whole-repository gate reviews.
The report is recorded below as received. Claude registered its findings after checking each one
through BytePlan's own code at the gate SHA.

## Registration and verification

| Report ID | Task | Severity | Verified through BytePlan code |
|---|---|---|---|
| BP-IND-01 | 6944ec | P2 | `tests/test_gitwrite.py::test_index_swap_never_writes_through_a_planted_scratch_link`: a symlink at `<index>.byteplan-scratch` makes `gitwrite._swap_index` overwrite a file outside the repository with Git index bytes. Strict xfail. |
| BP-IND-02 | bbe04c | P3 | `tests/test_archive.py::test_a_comment_naming_the_archive_store_is_not_an_ignore_rule`: after `Project._ignore_archive_store` with `# archive.sqlite is a local cache` in `.byteplan/.gitignore`, `git check-ignore` still reports the store as not ignored. Strict xfail. |

Severity follows the report. BP-IND-01 needs write access to the Git directory, which a clone does
not carry. That keeps it P2 for ordinary local use, as the report argues, unlike 53c751, whose
trigger is committed content.

## Report as received

### Scope and limitations

Reviewed the frozen SHA through the GitHub connector, including the RC1 gate/readiness documents
and selected source paths involving filesystem boundaries, journal/recovery transactions, staged
Git reconciliation, registry merging, archive management, release/restore, verification,
configuration, scanning and MCP permissions. Inspected relevant test sources.

The environment could not clone the repository or install BytePlan (the container could not
resolve github.com). Consequently, the whole repository was **not** executed, the full suite was
**not** rerun, and these are independently reproduced *focused operations*, not end-to-end
BytePlan integration tests. No changes were made to the repository. This report has not consulted
either reviewer's final current-gate verdict.

### BP-IND-01: P2, predictable index scratch path follows symlinks

**Location:** `src/byteplan/gitwrite.py:362-371, 417-423`
**Class:** filesystem safety; external-file overwrite
**Status:** independently reproduced at the Python filesystem-operation level; full BytePlan
invocation not run.

`_swap_index` chooses `index.with_name(index.name + ".byteplan-scratch")` and calls
`shutil.copyfile(index, scratch)` without a symlink or preexistence check. The destination is
therefore not confined to the Git metadata directory if a pre-existing scratch symlink points
somewhere else.

Minimal reproduction (isolated temporary Git repository):

```python
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess, shutil

with TemporaryDirectory() as temp:
    root = Path(temp)
    subprocess.run(["git", "init", "-q", str(root / "repo")], check=True)
    repo = root / "repo"
    (repo / "example.txt").write_text("example\n")
    subprocess.run(["git", "-C", str(repo), "add", "example.txt"], check=True)
    index = repo / ".git" / "index"
    scratch = index.with_name(index.name + ".byteplan-scratch")
    victim = root / "unrelated.txt"
    victim.write_text("important unrelated content\n")
    scratch.symlink_to(victim)
    shutil.copyfile(index, scratch)
    assert victim.read_bytes() == index.read_bytes()
```

**Observed:** the unrelated file was overwritten with Git index bytes, destroying its sentinel
content. This is precisely the unsafe copy operation used in `_swap_index`; the end-to-end trigger
remains to be exercised.

**Recommendation:** use an exclusively created, unique scratch file in the index directory (for
example `tempfile.mkstemp`) and write the original index bytes through that file descriptor.
Reject or prevent aliases, and make sure cleanup removes only the file created by the current
invocation. Add a regression using an existing symlink at the old scratch filename, asserting
that the outside target is unchanged.

**Severity:** P2 for normal local workspaces; reconsider as P1 if adversarial or shared `.git`
metadata is in scope.

### BP-IND-02: P3, archive ignore rule falsely satisfied by a comment

**Location:** `src/byteplan/operations/archive.py:265-270`
**Class:** unintentional staging of archive data
**Status:** independently reproduced with Git and the matching membership test.

`ignore_archive_store` uses `if archive_store.STORE not in current.split()` to decide whether
`.byteplan/.gitignore` already ignores `archive.sqlite`. A line like
`# archive.sqlite is a local cache` contains the exact word but is a Git comment, not an ignore
rule.

Minimal reproduction:

```bash
git init repo
mkdir -p repo/.byteplan
printf 'txn/\nscan.lock\n# archive.sqlite is a local cache\n' > repo/.byteplan/.gitignore
touch repo/.byteplan/archive.sqlite
git -C repo check-ignore -q .byteplan/archive.sqlite
# exits 1: the SQLite archive is not ignored
```

**Observed:** BytePlan's membership test evaluates true while Git reports the archive as not
ignored. A subsequent `git add .` could therefore stage the local archive.

**Recommendation:** add the `archive.sqlite` ignore rule unconditionally (duplicates are harmless),
or parse `.gitignore` semantics rather than comparing whitespace-delimited tokens. Add a regression
with a comment mentioning the filename.

**Severity:** P3, unless the project promises that the local archive can never enter the Git index
automatically.

### Positive observations

- The ordinary transaction writer uses exclusive temporary file creation, before/after hashes,
  fsyncs and a recovery journal.
- The project lock no longer reclaims stale locks automatically, preventing the earlier unsafe
  lock handoff pattern.
- Persisted journal paths and copies undergo strict validation for aliases and protected
  repository metadata.
- Staged reconciliation explicitly checks for unstaged modifications and maintains a rollback
  journal.
- Registry merge logic preserves reserved IDs and detects incompatible concurrent task updates.
- Release stripping validates AST-level equivalence, compiles resulting files and records
  restoration metadata.
- MCP source and test operations are gated by distinct permissions, though this does not
  constitute an exhaustive security proof.

### Verdict

**No P0/P1 was independently demonstrated in the inspected paths**, but absence of a found blocker
is not proof of whole-repository safety. I recommend fixing or explicitly triaging BP-IND-01 before
RC1 approval. BP-IND-02 can be treated as a low-priority safety fix. The release gate's required
full-repository, same-SHA independent pair, exact-SHA CI, artifact checks and explicit human
approval remain separate and unfulfilled by this focused review.
