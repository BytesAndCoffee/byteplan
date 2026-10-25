# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Internal release orchestration delegated by Project."""

from __future__ import annotations

import contextlib
import dataclasses
import re
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from byteplan import gitio, normalize, scaffold, smoke, verification
from byteplan import release as release_lib
from byteplan._api_types import ReleaseReport, RestoreReport
from byteplan.config import (
    PYPROJECT,
    parse_pyproject_text,
    read_pyproject,
)
from byteplan.diagnostics import Code, Diagnostic, Location, Severity
from byteplan.errors import (
    ConfigError,
)
from byteplan.languages import Language, language_for
from byteplan.models import HistoryEvent, Presence, Representation
from byteplan.operations.common import _read_bytes, _requirement_name
from byteplan.persistence import (
    FileWrite,
    pending_journal,
    sha256,
    staged_dir,
)
from byteplan.scanner.source import decode_source, read_source
from byteplan.writeguard import project_target, valid_hash

if TYPE_CHECKING:
    from byteplan.api import Project
    from byteplan.registry import Registry


def stripped_release(self: Project, registry: Registry | None = None) -> dict[str, Any] | None:
    """The registry's ``release`` block while the tree is stripped for a release."""
    block = (registry or self.load_registry()).extra.get("release")
    return block if isinstance(block, dict) and block.get("state") == "stripped" else None


def refuse_while_stripped(self: Project, command: str) -> None:
    block = self.stripped_release()
    if block is not None:
        raise release_lib.ReleaseError(
            release_lib.STRIPPED,
            [f"the tree is stripped for release {block.get('version')}; `{command}` would edit stripped source"],
            "run `byteplan restore` first (or switch back to your development branch)",
        )


def release_version(self: Project, override: str | None) -> str:
    if override:
        return override
    pyproject = (
        read_pyproject(self.root)
        if self.snapshot is None
        else parse_pyproject_text(
            (self.snapshot.read(PYPROJECT) or b"").decode("utf-8"), f"{self.snapshot.label}:{PYPROJECT}"
        )
    )
    project = pyproject.get("project", {})
    if isinstance(project.get("version"), str):
        return str(project["version"])
    source = pyproject.get("tool", {}).get("hatch", {}).get("version", {}).get("path")
    if "version" in project.get("dynamic", []) and isinstance(source, str):
        data = _read_bytes(self.root / source) if self.snapshot is None else self.snapshot.read(source)
        text = (data or b"").decode("utf-8", "replace")
        match = re.search(r"""__version__\s*=\s*["']([^"']+)["']""", text)
        if match:
            return match.group(1)
    msg = "can't tell the version; pass --version"
    raise ConfigError(msg)


def release(
    self: Project,
    version: str | None = None,
    *,
    dry_run: bool = False,
    allow_dirty: bool = False,
    smoke_test: bool = False,
    offline: bool = False,
) -> ReleaseReport:
    """Strip for a release (see ``_strip_for_release``), then optionally smoke-test it.

    ``smoke_test`` builds a wheel from the stripped tree, installs it in isolation and
    imports it without ``byteplan_runtime``. If that fails, the strip is restored
    automatically, so a release is all-or-nothing, and ``ReleaseError`` reports why.
    """
    self._require_working_tree()
    report = self._strip_for_release(version, dry_run=dry_run, allow_dirty=allow_dirty)
    report = dataclasses.replace(report, warnings=(*report.warnings, *self._release_warnings()))
    if dry_run or not smoke_test:
        return report
    result = smoke.run_smoke(self.root, self.config.release, offline=offline)
    if not result.passed:
        self.restore()
        raise release_lib.ReleaseError(
            release_lib.SMOKE_FAILED,
            [f"the {result.stage} step failed; the strip was restored", *result.detail.strip().splitlines()[-25:]],
            "fix the problem (or drop --smoke-test) and release again",
        )
    with self._writing():
        registry_hash, registry = self._read_registry()
        block = dict(registry.extra.get("release", {}))
        block["smoke_test"] = "passed"
        registry.extra["release"] = block
        self._commit(self._registry_writes(registry_hash, registry))
    return dataclasses.replace(report, smoke_test="passed", smoke_imports=result.imports)


def release_warnings(self: Project) -> list[Diagnostic]:
    """``runtime_dependency_in_release`` and ``unfinished_scaffold_in_sdist``, for a stripped tree."""
    found: list[Diagnostic] = []
    dependencies = read_pyproject(self.root).get("project", {}).get("dependencies", [])
    if "byteplan-runtime" in {_requirement_name(d) for d in dependencies if isinstance(d, str)}:
        found.append(
            Diagnostic(
                Code.RUNTIME_DEPENDENCY_IN_RELEASE,
                Severity.WARNING,
                "byteplan-runtime is still in [project].dependencies, so the release depends on it anyway",
                hint="move it to a development dependency (a [dependency-groups] entry or a Hatch environment)",
            )
        )
    shipped = sdist_files(self.root)
    placeholders = sorted(
        node
        for path in shipped
        if path.endswith(".py") and (data := _read_bytes(self.root / path)) is not None
        for node in scaffold.placeholder_nodes(path, data.decode("utf-8", "replace"))
    )
    found.extend(
        Diagnostic(
            Code.UNFINISHED_SCAFFOLD_IN_SDIST,
            Severity.WARNING,
            f"{node} is an unfinished scaffold (it fails on purpose) and would ship in the sdist",
            locations=(Location(node.split("::", 1)[0]),),
            hint="finish the test, or exclude it from the sdist",
        )
        for node in placeholders
    )
    return found


def strip_for_release(
    self: Project, version: str | None = None, *, dry_run: bool = False, allow_dirty: bool = False
) -> ReleaseReport:
    """Strip BytePlan's runtime decorators and imports in place, recording each one.

    Never commits, tags, builds or resets, and never changes a task's status. Refuses (with
    nothing written) on a dirty tree, a pending journal, a blocked scan, an untagged
    ``@todo``, a decorator sharing a line, leftover runtime references, or an
    already-stripped tree.
    """
    version = self.release_version(version)
    if pending_journal(self.root) or (staged_dir(self.root) / "journal.json").exists():
        raise release_lib.ReleaseError(
            release_lib.NEEDS_REVIEW,
            ["an interrupted write is pending"],
            "finish it deliberately with `byteplan scan` (or `scan --staged --apply`), then release",
        )
    context = contextlib.nullcontext(()) if dry_run else self._writing()
    with context:
        registry_hash, registry = self._read_registry()
        block = self.stripped_release(registry)
        if block is not None:
            raise release_lib.ReleaseError(
                release_lib.STRIPPED, [f"already stripped for release {block.get('version')}"]
            )
        head, dirty = verification.git_state(self.root)
        if dirty and not allow_dirty:
            raise release_lib.ReleaseError(
                release_lib.NEEDS_REVIEW,
                ["the Git tree has uncommitted changes"],
                "commit or stash them so the strip is the only change, or pass --allow-dirty",
            )
        preview = self._scan(None, None, dry_run=True, recovered=())
        untagged = [p.tag for p in preview.proposals if p.tag.representation is Representation.DECORATOR]
        if preview.blocked or untagged:
            problems = [f"{t.location}: @todo(...) has no id=" for t in untagged] or [
                "the scan has blocking diagnostics"
            ]
            raise release_lib.ReleaseError(
                release_lib.UNTAGGED if untagged else release_lib.NEEDS_REVIEW, problems, "run `byteplan scan` first"
            )

        runtime_modules = self.config.annotations.runtime_modules
        files: dict[str, Any] = {}
        writes: list[FileWrite] = []
        stripped_tasks: dict[str, list[dict[str, Any]]] = defaultdict(list)
        python = [p for p in preview.scope.files if language_for(p) is Language.PYTHON]
        sources = {path: read_source(self.root, path) for path in python}
        consumers = release_lib.project_consumers({path: s.text for path, s in sources.items()})
        for path in python:
            source = sources[path]
            imported_here = {
                name: users - {path}
                for name, users in release_lib.consumers_of(consumers, release_lib.module_name(path)).items()
            }
            plan = release_lib.strip_file(
                path, source.text, runtime_modules, {n: u for n, u in imported_here.items() if u}
            )
            if plan is None or (not plan.decorators and not plan.imports):
                continue
            normalize.ensure_equivalent_without_runtime(path, source.text, plan.text, runtime_modules, everything=True)
            problem = release_lib.ensure_compiles(path, plan.text)
            if problem is not None:
                raise release_lib.ReleaseError(
                    release_lib.NEEDS_REVIEW, [f"{path}: the stripped file wouldn't compile ({problem})"]
                )
            data = dataclasses.replace(source, text=plan.text).encode()
            files[path] = {"sha256": sha256(data), "decorators": plan.decorators, "imports": plan.imports}
            writes.append(FileWrite(path, sha256(source.encode()), data))
            for entry in plan.decorators:
                if entry["kind"] == "todo":
                    for task_id in entry["task_ids"]:
                        stripped_tasks[task_id].append(
                            {k: entry[k] for k in ("line", "decl_line", "qualname", "index")} | {"path": path}
                        )

        now = self.clock()
        for task_id, entries in stripped_tasks.items():
            task = registry.tasks.get(task_id)
            if task is None:
                continue
            task.extra["stripped"] = entries
            task.history.append(HistoryEvent("stripped_for_release", now, old=str(task.presence), new=version))
            task.presence = Presence.STRIPPED
        registry.extra["release"] = {
            "state": "stripped",
            "version": version,
            "stripped_at": now,
            "smoke_test": "not_run",
            "files": files,
        }
        writes.extend(self._registry_writes(registry_hash, registry))
        warnings = [self._default_branch_warning()] if head is not None else []
        written = () if dry_run else tuple(self._commit(writes))
        return ReleaseReport(
            version,
            tuple(sorted(files)),
            sum(len(f["decorators"]) for f in files.values()),
            sum(len(f["imports"]) for f in files.values()),
            tuple(sorted(stripped_tasks)),
            dry_run,
            tuple(w for w in warnings if w is not None),
            written,
        )


def default_branch_warning(self: Project) -> Diagnostic | None:
    try:
        branch = gitio.git(["symbolic-ref", "--quiet", "--short", "HEAD"], self.root).strip()
    except ConfigError:
        return None
    try:
        default = gitio.git(["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"], self.root).strip()
        default = default.removeprefix("origin/")
    except ConfigError:
        default = ""
    if branch not in {default, "main", "master"} - {""}:
        return None
    return Diagnostic(
        Code.RELEASE_ON_DEFAULT_BRANCH,
        Severity.WARNING,
        f"releasing on {branch}: the strip will sit on your development branch",
        hint="release from a short-lived branch (`git switch -c release/<version>`) and switch back after",
    )


def _validate_restore_record(record: object) -> None:
    """Validate serialized blocks before any source file is read."""
    if not isinstance(record, dict) or not valid_hash(record.get("sha256")):
        msg = "invalid serialized release fingerprint"
        raise ValueError(msg)
    for kind in ("decorators", "imports"):
        blocks = record.get(kind)
        if not isinstance(blocks, list):
            msg = f"invalid serialized release {kind}"
            raise TypeError(msg)
        for block in blocks:
            if not isinstance(block, dict) or not isinstance(block.get("text"), str):
                msg = "invalid serialized release block"
                raise TypeError(msg)
            for key in ("line", "end_line"):
                if type(block.get(key)) is not int or block[key] < 1:
                    msg = "invalid serialized release line"
                    raise ValueError(msg)
            if block["end_line"] < block["line"]:
                msg = "invalid serialized release line range"
                raise ValueError(msg)
            if kind == "imports":
                if "anchor" not in block or (block["anchor"] is not None and not isinstance(block["anchor"], str)):
                    msg = "invalid serialized release import anchor"
                    raise ValueError(msg)
            elif (
                not isinstance(block.get("kind"), str)
                or block["kind"] not in {"todo", "verifies"}
                or not isinstance(block.get("qualname"), str)
                or not block["qualname"]
                or type(block.get("index")) is not int
                or block["index"] < 0
                or type(block.get("decl_line")) is not int
                or block["decl_line"] < 1
                or not isinstance(block.get("task_ids"), list)
                or any(not isinstance(value, str) for value in block["task_ids"])
            ):
                msg = "invalid serialized release decorator"
                raise ValueError(msg)


def _restore_targets(root: Path, files: dict[str, Any]) -> dict[str, Path]:
    # Validate the complete persisted target set before reading or changing any source.
    targets = {path: project_target(root, path) for path in files}
    if len({path.resolve(strict=False) for path in targets.values()}) != len(targets):
        msg = "duplicate serialized release targets"
        raise ValueError(msg)
    for path, record in files.items():
        if language_for(path) is not Language.PYTHON:
            msg = "invalid serialized Python release path"
            raise ValueError(msg)
        _validate_restore_record(record)
    return targets


def restore(self: Project, *, dry_run: bool = False, partial: bool = False) -> RestoreReport:
    """Put every recorded decorator and import back (see ``release``).

    A file that still hashes to its stripped content is restored byte for byte; a changed
    one by AST anchors. Unplaceable entries are ``restore_conflict``: nothing is written,
    unless ``partial``, which restores the rest and keeps those on record.
    """
    self._require_working_tree()
    context = contextlib.nullcontext(()) if dry_run else self._writing()
    with context:
        registry_hash, registry = self._read_registry()
        block = self.stripped_release(registry)
        if block is None:
            raise release_lib.ReleaseError(release_lib.STRIPPED, ["the tree isn't stripped for a release"])
        runtime_modules = self.config.annotations.runtime_modules
        conflicts: list[str] = []
        writes: list[FileWrite] = []
        remaining: dict[str, Any] = {}
        restored_decorators: list[dict[str, Any]] = []
        restored_imports = 0
        files = block.get("files", {})
        if not isinstance(files, dict):
            raise release_lib.ReleaseError(release_lib.CONFLICT, ["invalid serialized release file mapping"])
        try:
            targets = _restore_targets(self.root, files)
        except (ValueError, TypeError, OSError) as exc:
            raise release_lib.ReleaseError(release_lib.CONFLICT, [f"unsafe serialized release paths: {exc}"]) from exc
        for path, record in sorted(files.items()):
            current = _read_bytes(targets[path])
            if current is None:
                conflicts.append(f"{path} no longer exists")
                remaining[path] = record
                continue
            source = decode_source(path, current)
            left: dict[str, Any] = {}
            if sha256(current) == record.get("sha256"):
                text = release_lib.restore_fast(source.text, record)
            else:
                text, file_conflicts, left = release_lib.restore_anchored(path, source.text, record)
                conflicts += file_conflicts
            normalize.ensure_equivalent_without_runtime(path, source.text, text, runtime_modules, everything=True)
            problem = release_lib.ensure_compiles(path, text)
            if problem is not None:
                conflicts.append(f"{path}: the restored file wouldn't compile ({problem})")
                remaining[path] = record
                continue
            if left:
                remaining[path] = {**record, **left}
            placed = [d for d in record.get("decorators", []) if d not in left.get("decorators", [])]
            restored_decorators += placed
            restored_imports += len(record.get("imports", [])) - len(left.get("imports", []))
            writes.append(FileWrite(path, sha256(current), dataclasses.replace(source, text=text).encode()))
        if conflicts and not partial:
            raise release_lib.ReleaseError(
                release_lib.CONFLICT, conflicts, "fix the code, or `byteplan restore --partial`"
            )

        now = self.clock()
        back = sorted({task_id for d in restored_decorators if d["kind"] == "todo" for task_id in d["task_ids"]})
        still = {
            task_id
            for r in remaining.values()
            for d in r.get("decorators", [])
            if d["kind"] == "todo"
            for task_id in d["task_ids"]
        }
        for task_id in back:
            task = registry.tasks.get(task_id)
            if task is None or task_id in still:
                continue
            task.extra.pop("stripped", None)
            task.presence = Presence.PRESENT
            task.history.append(HistoryEvent("restored", now, new=block.get("version")))
        if remaining:
            registry.extra["release"] = {**block, "files": remaining}
        else:
            history = list(registry.extra.get("releases", []))
            history.append(
                {
                    "version": block.get("version"),
                    "stripped_at": block.get("stripped_at"),
                    "restored_at": now,
                    "decorators": sum(len(f.get("decorators", [])) for f in block.get("files", {}).values()),
                    "imports": sum(len(f.get("imports", [])) for f in block.get("files", {}).values()),
                }
            )
            registry.extra["releases"] = history[-20:]
            registry.extra.pop("release", None)
        writes.extend(self._registry_writes(registry_hash, registry))
        written = () if dry_run else tuple(self._commit(writes))
        return RestoreReport(
            tuple(sorted({w.path for w in writes if w.path not in {self.registry_rel, self.report_rel}})),
            len(restored_decorators),
            restored_imports,
            tuple(back),
            tuple(conflicts),
            bool(remaining),
            dry_run,
            written,
        )


def sdist_files(root: Path) -> list[str]:
    """Project-relative paths a Hatch sdist would include: Hatchling's own file selection when
    it's importable, otherwise (conservatively) every file under ``tests/``."""
    try:
        from hatchling.builders.sdist import SdistBuilder  # noqa: PLC0415 - optional, build-time only

        builder = SdistBuilder(str(root))
        return sorted(Path(f.relative_path).as_posix() for f in builder.recurse_included_files())
    except Exception:  # noqa: BLE001 - not a Hatch project, or Hatchling missing: fall back
        tests = root / "tests"
        return sorted(p.relative_to(root).as_posix() for p in tests.rglob("*.py")) if tests.is_dir() else []
