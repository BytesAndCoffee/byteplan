# Independent final annotation/literal restore review

Result: no confirmed defect in this bounded review. Both earlier production-shaped reproductions now restore safely: a hotfix that already contains the original annotation/import is reused once, and a moved annotation preserves its exact literal AST and scanner description.

Reviewed `/workspace/byteplan-rc1-review3-fixes/src/byteplan/release.py`, `src/byteplan/operations/release.py`, and `tests/test_restore_existing_annotations.py`. No source, repository tests, generated documentation, Git metadata, PR, tag, or publication changes were made. This review wrote only disposable fixtures, its probe, logs, and report under this evidence directory. Other reviewers ran concurrently.

## Freeze identity

Initial `start.sha256` identified release.py as `77ac42b35506be1ff376e32807679c3622605dc48364a890d2ea12badf79c8c6`. The owner then explicitly announced a one-line post-freeze correction: the insertion AST postcondition uses existing `_parse("<restore>", placed)` instead of bare `ast.parse(placed)`, suppressing unrelated SyntaxWarning consistently. Inspected that change and restarted both checks. Earlier successful outputs are retained in `focused-interim.log` and `probe-interim.log`; they are not the final proof.

Final `final-start.sha256` and `end.sha256` agree exactly:

```text
84f55d4e866e1a519c2722737a5adcafbbdd97350959a822f574fb1822a7d683  src/byteplan/release.py
d98c1b12a3086f944215a72bb3af5992f716228b2a59f7f184a63586d9cce543  src/byteplan/operations/release.py
0e047f396834a4ea0ebe48166091e69d36ff26ffc29ac38cdfeb9cb6935fa45e  tests/test_restore_existing_annotations.py
```

`probe.log` additionally records the imported module's absolute path and final SHA-256 from inside the fresh Python process.

## Exact commands

Working directory: `/workspace/byteplan-rc1-review3-fixes`.

```sh
source /workspace/byteplan-env.sh
PYTHONPATH=/workspace/byteplan-rc1-review3-fixes/src /workspace/.byteplan-data/hatch/env/virtual/byteplan/c1S_SeYs/hatch-test.py3.12/bin/python -m pytest -q tests/test_restore_existing_annotations.py > /workspace/byteplan-rc1-evidence/review3-fixes/independent-literal-final/focused.log 2>&1
PYTHONPATH=/workspace/byteplan-rc1-review3-fixes/src /workspace/.byteplan-data/hatch/env/virtual/byteplan/c1S_SeYs/hatch-test.py3.12/bin/python -u /workspace/byteplan-rc1-evidence/review3-fixes/independent-literal-final/probe.py > /workspace/byteplan-rc1-evidence/review3-fixes/independent-literal-final/probe.log 2>&1
sha256sum src/byteplan/release.py src/byteplan/operations/release.py tests/test_restore_existing_annotations.py > /workspace/byteplan-rc1-evidence/review3-fixes/independent-literal-final/end.sha256
cmp /workspace/byteplan-rc1-evidence/review3-fixes/independent-literal-final/final-start.sha256 /workspace/byteplan-rc1-evidence/review3-fixes/independent-literal-final/end.sha256
```

Both Python commands exited 0; final focused run: 41 tests passed. Hash comparison exited 0.

## Independent probe evidence

`probe.py` exercises the public Project release/restore/check flow in newly initialized disposable projects, independently of repository test fixtures:

- Original duplicate-hotfix reproduction: existing import and decorator survive byte-for-byte with the changed function body; one task identity; clean check; release authority clears.
- 16 annotation moves between module and conditional nesting, using spaces and tabs in both directions. Unicode runtime alias, triple quoted multiline text, raw multiline strings, backslash continued strings, and adjacent string literals with comments. Assert full annotation AST equality, exact STRING token spellings, unchanged scanner description, all annotation comments, changed body, exactly one tag, clean check, and consumed release authority. Dry-run snapshots remain identical while authority persists.
- Original multiline indentation reproduction is the first literal in the module-to-spaces move. Its previously changed `first\nsecond\n    third` description is now exact after restoration.
- Latin-1 with CRLF tests actual annotation/import insertion into a moved declaration. Encoding, every line ending, annotation AST, and check remain valid.
- A copied identity in another configured source conflicts even with the unchanged stripped source fast path. Full and dry-run restore preserve the snapshot; partial restore retains both decorator and import authority; removing the duplicate allows retry.
- A deleted import anchor conflicts before mutation, retains import authority during partial restore, and succeeds after the anchor is repaired.
- An unrelated invalid escape in hotfixed source succeeds with `SyntaxWarning` configured as an error, exercising the final one-line correction.

The probe originally asserted that a whole adjacent-literal expression retained inter-token indentation verbatim. That assertion was too broad for a moved expression: whitespace between tokens should follow the new indentation. It was corrected to exact STRING token spellings plus full AST equality. This was a harness correction, not a product defect or weaker literal-content assertion.

## Repository regression scope and limits

The 41 focused tests additionally cover exact existing annotations/imports, semantic formatting reuse, larger imports, partial import overlap, aliases, class-local shadowing, competing annotation identity/title, duplicate annotation/import, stack order, reassigned/reimported/function-bound runtime names, import placement, syntax errors, global comment/decorator identity collisions, unreadable unrelated Python, partial-file recovery, retries after import authority was consumed, custom runtime configuration, and fail-closed AST preservation with retained authority.

This is bounded Python 3.12 evidence for the three requested files and these restore flows; it is not an exhaustive proof over all Python syntax or encodings. Byte-valued descriptions were deliberately excluded from the independent public API matrix because registry descriptions are text. The combined full suite, project-wide style/types, other release defects, and publication decisions belong to the parent review; this report makes no claim that those independently passed.
