# Contributing to BytePlan

BytePlan tracks its own development. Planned work, review findings and follow-ups are BytePlan
tasks in this repository's registry, and they go through the same lifecycle the
[README](README.md#a-tasks-life-end-to-end) describes.

## Setup

```console
$ git clone https://github.com/BytesAndCoffee/byteplan && cd byteplan
$ hatch run byteplan git install-hooks         # new TODOs get IDs at commit time
$ hatch run byteplan git install-merge-driver  # merge tasks.json / archive.json by task ID
```

Both are per clone (local Git config). With the [pre-commit](https://pre-commit.com) framework,
`.pre-commit-config.yaml` runs the same hooks instead.

| Task | Command |
|---|---|
| Tests | `hatch test` · `hatch test --all` (Python 3.11–3.14) |
| Lint / format | `hatch fmt` · `hatch fmt --check` |
| Types | `hatch run types:check` (mypy `--strict`) |
| BytePlan on itself | `hatch run byteplan scan` · `hatch run byteplan check` |

CI runs the tests on ubuntu, macOS and Windows, lint and types, and
`byteplan check --commit HEAD`.

## Tracking work

What's in scope is `[tool.byteplan]` in `pyproject.toml`: both packages' sources, `scripts/`,
`tests/` and Markdown.

1. **Write the TODO or FIXME** where the work is. Phases still to build are HTML-comment TODOs at
   the end of [the implementation plan](docs/IMPLEMENTATION_PLAN.md).
2. **`hatch run byteplan scan`** (or commit) gives it an ID. In Python files outside `tests/`, the scan also scaffolds
   an acceptance test (`[tool.byteplan.tests.scaffold] auto = true`): a strict-xfail
   placeholder linked with `@verifies("ID")`, so CI stays green until the work is done.
3. **Implement it, and turn the placeholder into the real test.** It must keep `@verifies`. A
   placeholder that starts passing fails as xpass. If the real test belongs elsewhere, delete
   the placeholder and put `@verifies("ID")` on the real test (or `byteplan tests add`).
4. **`hatch run byteplan verify ID`** records the results in `.byteplan/verification.json`.
   Commit that file with the change.
5. **`hatch run byteplan resolve ID --sync-source --note "..."`** once the task is fully
   satisfied and its tests are fresh passes. This also removes the annotation.

BytePlan never resolves anything by itself: a deleted TODO is `missing`, and passing tests only
make a task `ready_for_review`.

**Review findings** (from Codex or anyone else) each become a FIXME at the flagged line, with the
review comment's URL on the next line, then follow the steps above. Reply on the review thread
with the task ID and the evidence.

## Generated files

Never edit these by hand; BytePlan commands write them:
- `.byteplan/tasks.json`: the registry.
- `.byteplan/verification.json`: verification evidence.
- `.byteplan/archive.json`: the index of archived tasks.
- `byteplan.md`: the readable task list.

Only `main` regenerates `byteplan.md` (`report_branch = "main"`). After a merge,
`.github/workflows/report.yml` regenerates it and pushes the result, so pull requests never
conflict on it.

If a pull request conflicts on `tasks.json` on GitHub (two branches reserving neighbouring IDs),
merge `main` into the branch locally. With the merge driver installed, the registry merges by
task ID.

## For AI agents

`hatch run byteplan mcp --allow-registry-write` serves this registry over MCP (stdio). The
default Hatch environment includes the `mcp` extra. With Claude Code, point it at that
environment's `byteplan`:

```console
$ claude mcp add byteplan -- "$(hatch env find)/bin/byteplan" mcp --project "$PWD" --allow-registry-write
```

Agents follow the same workflow. They resolve a task only when its linked tests are fresh
passes, and the evidence is committed.
