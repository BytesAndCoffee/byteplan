# Independent final initializer and narrowed-scan correction recheck

The original initialization alias P1 and narrowed duplicate identity P2 remain corrected. The additional reserved-lock descendant P2 demonstrated in `../independent-b/SUPPLEMENT.md` is also corrected at the exact hashes below. No additional issue was confirmed in this scoped recheck. This supplements the historical proof; it does not replace or erase it.

Source checkout: `/workspace/byteplan-rc1-review3-fixes`; base HEAD observed as `378e722797d57b0bae257ca0f7fd2ad8d746547d`, with uncommitted corrections. Other restoration/release work was active. No entire-tree freeze, integrated revision approval, lifecycle disposition, complete suite result, native Windows result, CI status, or release approval is asserted here.

## Bound source

All 12 file hashes in `start-hashes.txt` and `end-hashes.txt` match. The first four exactly match the owner's `../init/source-sha256.txt`:

| File | SHA-256 |
|---|---|
| `src/byteplan/operations/initialize.py` | `3e6952a4d9e6b732731131ae21c0f4ee5658cd8f8557e3972fce2fb4cdcccfd4` |
| `src/byteplan/writeguard.py` | `50aab5c8497696f92dee354880563ba8aa5ff1abc6a4273494cc4a8e844c461a` |
| `tests/test_initialize.py` | `0ab35f93938ca1660040086198f5eb58b58cc8c0fdd11d0141a999e3d78c3597` |
| `tests/test_persistence.py` | `a6c3a6a0bd4f0058d82388cb72c88591eac26b7db8e4f24f59cb92e9a014181a` |
| `src/byteplan/operations/scan.py` | `b022a298343596b85e628529ffa07242671a0147e7bfcab9e8e1e79da2e5c756` |
| `tests/test_scan.py` | `a6c2044b1fbd2032ccba78f5a46cc07a19e6b307e2496f6082688997df4b0a7a` |
| `tests/test_narrowed_allocation.py` | `e27b43087ce407a0c480f5a2ba609906047552da66e528cff72d486a12b0ee7a` |

The hash files additionally bind API, CLI, persistence, configuration and registry dependencies. Those endpoint checks do not certify all imported modules or the entire working tree as frozen.

## Independent checks

- **45 passed in 2.27s**, `private-regressions.log`: reran the 19 retained original private init/narrow checks, the seven retained amended lock checks, and 19 freshly authored cases in `test_final_lock.py`.
- The fresh cases reject registry targets, shim targets and a shared persistence commit with an earlier innocent planned write. Each exercises direct lock descendants, a resolved parent alias into the reserved path, a lexical reserved-path alias into an ordinary directory, mixed case and portable trailing-dot/space normalization. Refusal preserves the complete fixture's modes, bytes, directories and symlink identities; no earlier planned file or initializer shim/state/configuration write is made.
- Four successful fresh cases use an ordinary path and the three lock lookalikes `.byteplan/scan.lock.backup`, top-level `scan.lock`, and `pkg/.byteplan/scan.lock`. Each initializes, performs an actual writing scan allocating a task, then reinitializes without actions or fixture changes. The retained private cases also exercise ordinary confined registry/shim parent aliases.
- `repro_lock_descendant_recheck.py` retains the original standalone reproduction's project/configuration/shim trigger with safe-refusal assertions. `original-lock-probe-recheck.log` confirms `ConfigError`, complete fixture preservation, and absence of both `.byteplan` and `pkg` creation. The historical reproduction and its original failure log remain untouched.
- **169 passed in 14.60s**, `regressions.log`: initializer, scan, narrowed allocation, configuration, CLI and API facade contract regression files. These include snapshot source views, allocation namespace checks, duplicate blocking and compatibility behaviors for narrowed observation.
- **Strict mypy succeeded for seven source/test files**, `types.log`.

The two added guard comparisons reserve lexical and resolved normalized `scan.lock` prefixes, parallel to the existing transaction subtree restriction. The original initializer preflight remains intact. The original private external-control-alias checks still refuse through Python and CLI with no private-tree change; the original narrowed duplicate checks still block copied identities with and without allocation and in dry-run/write modes, preserving registry task objects and private files. Legitimate narrowed moves preserve unobserved task state and unrelated parse tolerance. As recorded previously, pure narrowed observation without allocation checks prior canonical paths of apparent moves; it does not certify every unrelated file duplicate-free.

## Reproduction and limits

All commands sourced `/workspace/byteplan-env.sh`, ran from the source checkout and set `PYTHONPATH=/workspace/byteplan-rc1-review3-fixes/src`. Runtime: Linux CPython 3.12; tests use `/workspace/.byteplan-data/hatch/env/virtual/byteplan/c1S_SeYs/hatch-test.py3.12/bin/python`; mypy uses the sibling `types/bin/python`. `python -B` and pytest `-p no:cacheprovider` were used. Private test fixtures and new evidence are under this directory. No source, generated project artifacts, project documentation, registry, Git state or PR was changed by this reviewer.

The first scoped regression invocation used the nonexistent filename `tests/test_facade_contract.py`; it collected no tests and is preserved in `initial-regressions-command-error.log`. The corrected invocation used `tests/test_api_facade_contract.py` and completed successfully as recorded above.

Exact principal selections:

```text
python -B -m pytest -q -p no:cacheprovider /workspace/byteplan-rc1-evidence/review3-fixes/independent-b/test_independent_b.py /workspace/byteplan-rc1-evidence/review3-fixes/independent-b/test_lock_descendant_safe.py /workspace/byteplan-rc1-evidence/review3-fixes/independent-init-final/test_final_lock.py --basetemp=/workspace/byteplan-rc1-evidence/review3-fixes/independent-init-final/private-fixtures
python -B -m pytest -q -p no:cacheprovider tests/test_initialize.py tests/test_scan.py tests/test_narrowed_allocation.py tests/test_config.py tests/test_cli.py tests/test_api_facade_contract.py
python -B -m mypy src/byteplan/operations/initialize.py src/byteplan/writeguard.py src/byteplan/operations/scan.py tests/test_initialize.py tests/test_persistence.py tests/test_scan.py tests/test_narrowed_allocation.py
```

Native Windows junction behavior remains unexecuted here. Filesystem replacement races and unrelated restoration/release changes are outside this review. Root owns combined-suite verification, CI, canonical evidence/lifecycle updates and the next integrated commit/PR gate.
