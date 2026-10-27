# Independent Windows fixture review

Verdict: PASS; no blocking finding. Reviewed only the uncommitted changes to `tests/test_gitwrite.py` and `tests/test_restore_existing_annotations.py` against `4cf857b9f71361ff222a879c4b6a7ce1c414a19a`. No source, canonical, documentation, Git metadata, commit, or PR changes were made by this review. Evidence-only copies and logs live beside this report.

Environment: Linux, Python 3.12.14, Git 2.52.0. Sourced `/workspace/byteplan-env.sh`; absolute `PYTHONPATH=/workspace/byteplan-rc1-review3-fixes/src:/workspace/byteplan-rc1-review3-fixes`. Interpreter `/workspace/.byteplan-data/hatch/env/virtual/byteplan/c1S_SeYs/hatch-test.py3.12/bin/python` (called `$PY` below). This is portable Linux reproduction and emulation, not native Windows verification. Root must refresh native Windows CI on the final committed head.

## Independent results

- Corrected entire two files under `core.autocrlf=true`: **139 passed** (97 Git + 42 restore), 92.95 seconds. `after-both-autocrlf.log`.
- Git original file copied directly using `git show 4cf857b:tests/test_gitwrite.py`, unchanged production source: **14 failed, 12 passed, 45 deselected**, 37.01 seconds. Every failure is the old text-mode blob versus CRLF worktree comparison. `before-git-autocrlf.log`.
- Restore original file copied directly using `git show 4cf857b:tests/test_restore_existing_annotations.py`, separate external cp1252 fixture plugin: **10 failed, 31 passed**, 25.68 seconds. Failures reproduce the old UTF-8 bytes decoded through cp1252 default assertion reads. `before-restore-cp1252.log`; external plugin retained as `cp1252_plugin.py`.
- Adversarial binary-reader check: two indexes contain distinct CRLF blobs; inherited `GIT_INDEX_FILE` deliberately selects main while `index_blob` receives alternate. Exact alternate CRLF returned, main CRLF independently returned, main index hash unchanged. Text-mode subprocess demonstrably produces LF from the same CRLF blob. `helper-and-assertion-audit.log`.
- AST audit: all 15 original restore test functions, including original parametrization (41 cases), are identical after removing only the explicit added `encoding="utf-8"` keywords. New Unicode proof is additional coverage. `helper-and-assertion-audit.log`.
- Fixture semantics check: omitted and explicit None decoder use cp1252; explicit UTF-8 positional and keyword decoder passes through; strict errors still raise and explicit replace/ignore errors work; monkeypatch context restores the original `Path.read_text`. `cp1252-scope.log`.
- `git diff --check -- tests/test_gitwrite.py tests/test_restore_existing_annotations.py`: exit 0.

## Review reasoning

Git binary helper uses binary stdout without decoding and pins `GIT_INDEX_FILE` after expanding inherited environment, so the explicit selected index wins. `gitwrite.index_path` resolves an environment-selected relative index against process cwd, and the tests pass its resulting absolute index to the reader. Linked worktree and selected-index cases retain exact main/default-index preservation checks. The `-text` unrelated file supplies actual CRLF blob bytes, preventing a text-mode helper from passing unnoticed.

Corrected source/registry expectations do not normalize actual worktree bytes before comparison. They first require LF in the raw blob and reject every CR byte in it, then require the entire worktree to equal that blob transformed with the explicitly configured LF or CRLF checkout policy. Missing, duplicated, or wrong newline bytes fail. Both LF and CRLF are exercised across every original object format, index view, and forward/rollback/recovery operation. Original rollback source byte equality, stage-entry equality, absent registry/journal checks, short-write interruptions, and unrelated executable-mode assertions remain. Added raw user-blob and unstaged worktree snapshots strengthen preservation coverage.

Restore fixture applies during tests of this module through pytest's function-scoped autouse fixture and monkeypatch cleanup. Although it patches the shared Path class during each test, teardown prevents leakage into other tests. It changes only omitted/None decoder behavior while forwarding explicit decoders and errors to the captured original reader. It deliberately models the legacy Windows decoding default, not a complete Windows environment or Path.read_text's future optional API surface. Current callers do not supply a newline keyword.

ProjectFactory.write(str) writes UTF-8 bytes via str.encode(); explicit UTF-8 fixture assertion reads therefore match their writer. Production `read_source` reads bytes and detects Python coding declarations with tokenize.detect_encoding, preserving raw newline information. The added Unicode test proves the simulated wrong default produces mojibake while production decodes/restores the correct UTF-8 text, exact bytes, alias, and description. The original Latin-1/CRLF exact-byte test remains unchanged except for explicitly reading its UTF-8 configuration file. I found no hidden production decoder/newline defect within this scope. The old native Windows failure log matches these two independently reproduced assertion defects.

## Commands

Run from `/workspace/byteplan-rc1-review3-fixes` after sourcing the environment and setting the PYTHONPATH above. `$E=/workspace/byteplan-rc1-evidence/review3-fixes/independent-windows-fixtures`.

```sh
GIT_CONFIG_GLOBAL=$E/autocrlf.gitconfig $PY -m pytest -q -o addopts= tests/test_gitwrite.py tests/test_restore_existing_annotations.py
GIT_CONFIG_GLOBAL=$E/autocrlf.gitconfig $PY -m pytest -q -o addopts= --confcutdir=$E/before $E/before/test_gitwrite.py -k 'task_28e56f or task_17f1f0'
PYTHONPATH=/workspace/byteplan-rc1-review3-fixes/src:/workspace/byteplan-rc1-review3-fixes:$E $PY -m pytest -q -o addopts= -p cp1252_plugin --confcutdir=$E/before $E/before/test_restore_existing_annotations.py
git diff --check -- tests/test_gitwrite.py tests/test_restore_existing_annotations.py
```

The before directory contains an unmodified copy of tests/conftest.py and the two original files; it is outside the reviewed checkout. Local config contains only `[core] autocrlf = true`. No global Git configuration was changed.

## Frozen input hashes (SHA-256)

- `tests/test_gitwrite.py`: `eaebfc4c91430097d2677ef44ed0d70c4f334f3055d12bf765e81b85ccb92143`
- `tests/test_restore_existing_annotations.py`: `4f97ca675c4265eaa93bb5761ecc35384bfe90f1b63414648c4398fd3848b3ab`

## Evidence hashes (SHA-256)

- `after-both-autocrlf.log`: `e0e9cdebde98caed50209e6f2d847f19c9e840f6168605aeb59c477bb9cdbeda`
- `before-git-autocrlf.log`: `7c785823ad1ada95b97a2de20ee7f1a4b79dc5efeffefa8018e26ae8c0a20587`
- `before-restore-cp1252.log`: `416fdadbdd24754d50f057839ed5f22ec61fab29024cde2fdd2f8afafff6fa71`
- `cp1252-scope.log`: `a13b69e1339623fd865e58ca80084600dc62058c5a70d8181515078c1062c6be`
- `helper-and-assertion-audit.log`: `e1a7698e07af52e2ab39ebf1fb168c75ed4bdf645fe55e1fe658fe4ae1033b00`
