# BytePlan in CI and Git hooks

BytePlan checks that the committed backlog describes the committed code. The same rules run in
three places, and all of them are read-only:

| Where | Command | What it checks |
|---|---|---|
| pre-commit | `byteplan check --staged` | exactly what's staged (the Git index), never the working tree |
| CI | `byteplan check --commit HEAD` | the checked-out commit |
| locally | `byteplan check` | the working tree (add `require_reconciled = true` to apply the same rules) |

`--staged` and `--commit` always apply the **consistency rules**. Each of these fails with exit
code 1:

| Code | Meaning | Fix |
|---|---|---|
| `new_unregistered` | a TODO, stub or `@todo` has no ID yet | `byteplan scan`, then stage or commit the source and `.byteplan/tasks.json` |
| `registry_not_staged` | the registry isn't in the snapshot, or IDs in staged code are registered only in the working tree | `git add .byteplan/tasks.json` |
| `registry_out_of_sync` | the snapshot's registry doesn't reflect its code (moved, retitled, missing or reappeared tasks) | `byteplan scan`, then stage or commit the registry |
| `unregistered_id` | an ID in the code is in no registry | restore the registry entry, or remove the copied `[id]` |
| duplicate IDs | as for `byteplan check` | `byteplan repair --reassign PATH:LINE` |

These are informational and don't fail the check by default:
- **`position_drift`:** only line numbers differ, e.g. after code was inserted above a TODO. Set
  `fail_on_position_drift = true` to make it fail.
- **`working_tree_changed_but_not_staged`:** the working-tree registry has changes you haven't
  staged.
- **`staged_config_mismatch`:** your unstaged `pyproject.toml` has different BytePlan settings. The
  staged ones are used.

**Edge cases:**
- **Resolved and removed together:** a task that's resolved in the staged registry while its
  annotation is removed in staged code is simply finished; it isn't a problem.
- **Unmerged index:** an index with unresolved merge conflicts can't be checked (exit 2).

**Never as a side effect:** hooks and CI checks don't run tests, import your code, use the network
or modify anything.

## Adding IDs at commit time

`byteplan scan --staged --apply` gives new TODOs in the commit their IDs before the commit is
finalized. It updates both the index and the working tree, and refuses partially staged files.
`byteplan git install-hooks` installs it as the pre-commit hook; that's the default mode, and
`--mode check` gives validation only. See the README section "IDs at commit time".

## pre-commit framework

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/BytesAndCoffee/byteplan
    rev: v0.1.0
    hooks:
      - id: byteplan-reconcile   # add IDs (formatter-style: annotates, fails, commit again)
      - id: byteplan-check       # then validate
```

The hook runs in pre-commit's own isolated environment with only BytePlan installed. It never
imports your project. Run `pre-commit run byteplan-scan-preview --hook-stage manual` to see what a
scan would change in the staged snapshot.

## Direct Git hook (without the framework)

```console
$ byteplan git install-hooks             # or --mode scan for the preview
$ byteplan git hooks-status
```

`install-hooks` honours `core.hooksPath`, records the current Python interpreter's absolute path,
and **refuses to overwrite a pre-commit hook it didn't write**. If you already have one, add
`python -m byteplan check --staged` to it yourself. Hooks can always be skipped with
`git commit --no-verify`, which is why CI is the place to enforce the rules.

## GitHub Actions

```yaml
# .github/workflows/byteplan.yml
name: BytePlan consistency
on:
  pull_request:
  push:
    branches: [main]
permissions:
  contents: read
jobs:
  byteplan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install "byteplan==0.1.0"
      - run: byteplan check --commit HEAD --format json
```

CI never writes source. It fails with findings, and `--format json` gives one machine-readable
object on stdout (diagnostics also go to stderr in text form). For a monorepo, add
`--project path/to/project`.

## Keeping the report current on main

With a `report_file`, pull requests that both change tasks conflict on it under GitHub's text
merge (GitHub doesn't run BytePlan's merge drivers). Set `report_branch = "main"` so that only
`main` maintains it, then regenerate it after each merge:

```yaml
# .github/workflows/report.yml
name: Regenerate byteplan.md
on:
  push:
    branches: [main]
    paths: [".byteplan/tasks.json", "pyproject.toml"]
permissions:
  contents: write
concurrency:
  group: byteplan-report
jobs:
  report:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install "byteplan==0.1.0"
      - run: byteplan report --write
      - run: |
          git diff --quiet -- byteplan.md && exit 0
          git config user.name "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git commit -qm "Regenerate byteplan.md" -- byteplan.md
          git push
```

Pushes made with the workflow's `GITHUB_TOKEN` don't trigger further workflow runs. If `main`
is protected against direct pushes, use a token or app that's allowed to bypass it.
