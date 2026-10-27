# Independent review of Git installer and malformed-ID corrections

Reviewed product commit: `c0e1cb67a87b64f5365963ea75333a46f05359fe` in `/workspace/byteplan-rc1-review4-fixes`, comparing the relevant code against `6953417c81872197ea4f82223f36f49494418270`. The parent committed the stable correction files while this review was running; the reviewed payload hashes below identify the exact contents independently of later administrative commits.

## Verdict

The affected corrections for `e86b8e`, `9e4d1c` and `668a6c` pass this focused independent review. No additional confirmed blocking defect was found in the inspected delta. This is not a whole-repository review, a final common-SHA approval, or proof that all RC1 gates are complete. Root coordinates the full suite, typing, packaging, canonical task verification and platform CI separately.

## Git installation write authority — e86b8e

Inspected `gitio.py:143–230`, the existing `writeguard` contracts, configuration path handling, and all new installation regressions. The installer validates the lexical `.byteplan` control directory before planning writes, so the original external-directory alias path is refused before even the registry's attributes file is created. It validates every metadata target and attributes destination, including parents and existing file type, and reads every existing attributes payload before the first attributes/config mutation. Unsafe paths become an actionable `ConfigError`.

The complete plan rejects duplicate metadata authority and equal/ancestor collisions among metadata and attributes files. This covers the newly identified overlap variants: registry under the fixed archive index path, registry equal to archive index, report below the registry file, and nested attributes-as-directory layouts. Canonical aggregation preserves both rules when ordinary confined parent aliases lead to the same attributes file. Protected VCS/transaction/lock paths and aliased/nonregular attributes targets are rejected.

Actual focused tests assert no outside file changes and no partial root/config changes for the demonstrated known-unsafe refusal cases. The native Windows junction case is present and uses a real junction without requiring symlink privilege, but was skipped on this Linux host; no native Windows result is claimed here.

This correction is bounded preflight, not an all-files transaction for integration installation or a claim to eliminate adversarial concurrent filesystem replacement after validation. The actual public install signature, driver names/commands and custom confined registry behavior remain intact.

## Literal Git attributes patterns — 9e4d1c

Inspected `gitio.py:127–140` and actual Git matching tests. The new encoder escapes glob metacharacters and leading comment/negation characters, then preserves those escapes through Git's C-string decoding. Spaces, quotes, tab/newline/control syntax and UTF-8 names are treated as Git attribute pattern data rather than shell text.

The focused tests run real `git check-attr -z` for configured paths and wildcard lookalikes, preserving existing CRLF attributes bytes and checking repeat-install byte idempotence. The actual divergent-branch merge with a spaced registry/report succeeds, retains both independent tasks and uses the generated-report driver. I additionally reran that real merge under a command-scoped Git global configuration with `core.autocrlf=true`; it passed, providing a bounded check against the prior Windows newline-fixture class of failure. That is not a substitute for native platform CI.

Existing arbitrary attributes content is preserved; the installer does not infer ownership of older manually authored or previously generated rules and erase them. This review does not claim a general Git attributes policy migration.

## Malformed persistent-ID brackets — 668a6c

Inspected shared comment grammar/diagnostics in `comments.py:79–131`, Markdown comment/link consumers, JSON comment handling, the JSON tagged-string grammar in `jsonc.py:250–287`, and the new tests. The otherwise recognized task opener with an unclosed bracket remains recognizable only long enough to produce `malformed_id`; it never produces an annotation, ID slot or guessed identity. Closed valid IDs still take their existing validation path. JSON valid string annotations still require their colon, and string-value scanning remains opt-in/configurable as before.

Actual cases cover Python, Markdown HTML/link comments, JSONC line/block comments and configured JSON string values; diagnostic locations and recovery hints; legacy/six/long IDs; case-sensitive prose rules from PR #51; unsupported owner syntax; Python strings, Markdown fenced/front-matter exclusions, keys and ignore suppressions; and malformed lines after existing task descriptions. Public writing/preview scans preserve malformed source bytes and do not allocate replacement tasks. An existing registered identity remains reserved with its history and open lifecycle retained, even though its malformed source no longer constitutes a present annotation; BOM/CRLF preservation is asserted.

The new warning follows the existing malformed-ID diagnostic/exit policy; it does not add an implicit source repair or lifecycle decision. No source editing transformation, new persistent-ID contract, registry schema or public exception redesign is introduced by this scanner delta.

## Actual commands and results

Using the prepared Python 3.12 interpreter and absolute `PYTHONPATH=/workspace/byteplan-rc1-review4-fixes/src`:

```text
python -m pytest -q tests/test_merge_install_safety.py tests/test_malformed_annotation_ids.py
65 passed, 1 skipped in 11.98s; exit 0
```

Log: `independent-git-scanner-tests.log`. The skip is the explicitly native Windows junction case.

The additional single-case rerun uses `GIT_CONFIG_GLOBAL` pointing only to the retained `independent-autocrlf.conf` containing `core.autocrlf=true`:

```text
python -m pytest -q tests/test_merge_install_safety.py::test_spaced_registry_and_report_use_their_drivers_in_a_real_divergent_merge
1 passed in 3.40s; exit 0
```

Log: `independent-git-autocrlf.log`. No user/global Git settings were edited. No source, tests, canonical registry/evidence or commits were changed by this reviewer. No process signals were sent and no broad suite was duplicated.

## Reviewed payload hashes

| File | SHA-256 |
|---|---|
| `src/byteplan/gitio.py` | `6915577982f2c396e7385b1465976fd3895a6ccba0c445c334c067d74b4c6d70` |
| `src/byteplan/scanner/comments.py` | `598b61d4c040bfa3e43abec5d22b5bfc8abba1e91005042fd3a636555af6eaf7` |
| `src/byteplan/scanner/jsonc.py` | `dc3e858ddefc33a126be1d40470d0c8a92872dfb7f5960e98c68bc0107fb0454` |
| `tests/test_merge_install_safety.py` | `267c6ce0fa14880ee57bf4e2aeeec6a3ab2a4be78e6bf9a7a1e808b58cf9ca83` |
| `tests/test_malformed_annotation_ids.py` | `62b0c2df263eaddf238a295770de73a585a657223aca6f1b8800da96b5cc5ba8` |

Limits: this is an affected-area correctness/safety review, not exhaustive filesystem scheduling, arbitrary Git configurations, native Windows/macOS execution, installed artifact validation or a new independent whole-repository release verdict.
