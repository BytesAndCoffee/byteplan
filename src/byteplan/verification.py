# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""``byteplan verify``: run a task's linked tests and keep the evidence.

* **Running.** ``[*runner, "-p", "_byteplan_verify_plugin", *test_files]`` runs as an argument
  list (never a shell) in the project root, in its own process group. Test *files* are
  passed rather than node IDs because pytest aborts the whole run on one unknown node ID;
  the plugin deselects everything that wasn't requested and reports which requests matched.
  A file that doesn't exist is ``not_found`` without running anything.
* **Outcomes.** ``passed``, ``failed``, ``skipped``, ``xfailed``, ``xpassed``, ``error``,
  ``not_found``, ``not_run`` or ``timeout`` per requested node (the most severe outcome of
  its items when it covers several, e.g. parametrizations). Only ``passed`` is positive
  evidence. A collection error in a test file is ``error`` for every request in that file.
* **Evidence** lives in ``.byteplan/verification.json``, written only by ``verify``. Per task:
  the fingerprint of its files at verification time, the run, and per-test results
  (outcome, duration in ms, up to 1 KB of failure text). Runs record argv, Python version,
  UTC time, Git HEAD and a dirty flag.
* **Freshness.** A task's fingerprint is a sha256 over its source file (while its annotation
  is present) and its linked test files. Results are ``stale`` when it changed. It can't see imported helpers; with
  ``stale_on = "head"`` any HEAD change or a dirty tree makes results stale instead.
* **Readiness** is derived, never stored, and never changes a task's status.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

from byteplan import jsonio
from byteplan.errors import ByteplanError, ConfigError
from byteplan.gitio import git
from byteplan.models import Presence
from byteplan.persistence import STATE_DIR, atomic_write_bytes

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence

    from byteplan.models import Task

STORE = f"{STATE_DIR}/verification.json"
STORE_VERSION = 1
PLUGIN_MODULE = "_byteplan_verify_plugin"
# Most severe first: a node covering several items takes the worst.
OUTCOMES = ("error", "failed", "timeout", "not_found", "not_run", "xpassed", "skipped", "xfailed", "passed")
_FAILING = frozenset({"failed", "error", "timeout"})
# After a timeout kill, how long to keep reading output. A descendant that escaped the kill
# can hold the pipe open indefinitely; verification must still end.
_KILL_GRACE = 5.0


class VerifyError(ByteplanError):
    """The test runner couldn't be started."""


@dataclass(frozen=True)
class TestResult:
    __test__ = False  # not a pytest test class

    outcome: str
    duration_ms: int = 0
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"outcome": self.outcome, "duration_ms": self.duration_ms}
        if self.message:
            data["message"] = self.message
        return data


@dataclass
class RunOutput:
    results: dict[str, TestResult]  # by requested node ID
    returncode: int | None  # None on timeout
    timed_out: bool = False
    output: str = ""  # the runner's combined stdout/stderr (tail)


# Fingerprints ----------------------------------------------------------------------------------


def task_files(task: Task) -> list[str]:
    """The files a task's evidence depends on: its linked test files, plus its source file while
    its annotation is there. Once the annotation is gone (presence ``missing``, e.g. a finished
    task whose TODO was removed), the old file says nothing about the work, so edits to it
    don't make the evidence stale."""
    files = {node.split("::", 1)[0] for node in task.linked_tests()}
    if task.source is not None and task.presence is not Presence.MISSING:
        files.add(task.source.path)
    return sorted(files)


def fingerprint(root: Path, files: Sequence[str], *, read: Callable[[str], bytes | None] | None = None) -> str:
    digest = hashlib.sha256()
    for rel in sorted(files):
        try:
            data = (root / rel).read_bytes() if read is None else read(rel)
            content = "missing" if data is None else hashlib.sha256(data).hexdigest()
        except OSError:
            content = "missing"
        digest.update(f"{rel}\0{content}\n".encode())
    return digest.hexdigest()


# The evidence store itself never makes evidence stale: writing or committing it would
# otherwise invalidate what was just recorded.
_NOT_STORE = f":(exclude){STORE}"


def git_state(root: Path) -> tuple[str | None, bool]:
    """``(HEAD, dirty)``, or ``(None, False)`` outside Git. Changes to the evidence store
    don't count as dirty."""
    try:
        head = git(["rev-parse", "HEAD"], root).strip()
        dirty = bool(git(["status", "--porcelain", "--", ".", _NOT_STORE], root).strip())
    except ConfigError:  # not a repository, no commits yet, or no git
        return None, False
    return head, dirty


def changed_since(root: Path, base: str, head: str) -> bool:
    """Whether anything but the evidence store differs between two commits (True if unknown)."""
    try:
        git(["diff", "--quiet", base, head, "--", ".", _NOT_STORE], root)
    except ConfigError:  # differences (exit 1), or an unknown commit
        return True
    return False


# Running pytest --------------------------------------------------------------------------------

_NOT_FOUND_HINT = (
    "run `byteplan scan` to refresh discovered test links; "
    "if this is a managed link, update it with `byteplan tests remove` / `byteplan tests add`"
)


def _plugin_source() -> bytes:
    return resources.files("byteplan").joinpath("_verify_plugin.py").read_bytes()


def run_tests(
    root: Path,
    nodes: Sequence[str],
    runner: Sequence[str],
    timeout: float,
    *,
    popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
) -> RunOutput:
    """Run the requested node IDs and return a result for every one of them."""
    results: dict[str, TestResult] = {}
    files: list[str] = []
    for node in dict.fromkeys(nodes):
        path = node.split("::", 1)[0]
        if not (root / path).is_file():
            results[node] = TestResult("not_found", message=f"{path} doesn't exist; {_NOT_FOUND_HINT}")
        elif path not in files:
            files.append(path)
    pending = [node for node in dict.fromkeys(nodes) if node not in results]
    if not pending:
        return RunOutput(results, returncode=0)

    with tempfile.TemporaryDirectory(prefix="byteplan-verify-") as scratch:
        plugin_dir = Path(scratch)
        (plugin_dir / f"{PLUGIN_MODULE}.py").write_bytes(_plugin_source())
        out = plugin_dir / "results.jsonl"
        env = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join([str(plugin_dir), *filter(None, [os.environ.get("PYTHONPATH")])]),
            "BYTEPLAN_VERIFY_NODES": json.dumps(pending),
            "BYTEPLAN_VERIFY_OUT": str(out),
            "BYTEPLAN_VERIFY_ROOT": str(root.resolve()),
        }
        argv = [*runner, "-p", PLUGIN_MODULE, *files]
        try:
            proc = popen(
                argv,
                cwd=root,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=sys.platform != "win32",
            )
        except OSError as exc:
            msg = f"can't start the test runner {argv[0]!r}: {exc.strerror or exc}"
            raise VerifyError(msg) from exc
        timed_out = False
        try:
            output, _ = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill(proc)
            try:
                output, _ = proc.communicate(timeout=_KILL_GRACE)
            except subprocess.TimeoutExpired:
                # Something the runner started still holds the output pipe. Stop reading:
                # the runner itself is gone, and its results file is what counts.
                output = b""
                if proc.stdout is not None:
                    with contextlib.suppress(OSError):
                        proc.stdout.close()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    proc.wait(timeout=_KILL_GRACE)
        records = _read_records(out)
    text = (output or b"").decode("utf-8", "replace")
    results.update(_aggregate(pending, records, timed_out=timed_out, returncode=proc.returncode))
    return RunOutput(results, None if timed_out else proc.returncode, timed_out, text[-4000:])


def _kill(proc: subprocess.Popen[bytes]) -> None:
    """Kill the runner and everything it started: its process group on POSIX, its process
    tree on Windows (a wrapper such as Hatch runs pytest as a child)."""
    if sys.platform != "win32":
        with contextlib.suppress(OSError):
            os.killpg(proc.pid, signal.SIGKILL)
    else:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],  # noqa: S607 - a Windows system tool
                capture_output=True,
                timeout=_KILL_GRACE,
                check=False,
            )
    with contextlib.suppress(OSError):
        proc.kill()


def _read_records(path: Path) -> list[dict[str, Any]]:
    records = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in lines:
        with contextlib.suppress(ValueError):
            record = json.loads(line)
            if isinstance(record, dict):
                records.append(record)
    return records


def _worst(outcomes: Sequence[str]) -> str:
    return min(outcomes, key=OUTCOMES.index)


def _aggregate(
    requested: Sequence[str], records: Sequence[Mapping[str, Any]], *, timed_out: bool, returncode: int | None
) -> dict[str, TestResult]:
    matched: dict[str, list[str]] = {}
    collect_errors: dict[str, str] = {}
    phases: dict[str, list[Mapping[str, Any]]] = {}
    for record in records:
        if "matched" in record:
            matched = {k: list(v) for k, v in record["matched"].items()}
        elif "collect" in record:
            if record.get("failed"):
                collect_errors[record["collect"]] = record.get("message", "")
        elif "node" in record:
            phases.setdefault(record["node"], []).append(record)
        elif record.get("done"):
            pass  # the session finished; nothing else to read

    item_results = {nodeid: _item_result(reports) for nodeid, reports in phases.items()}
    results: dict[str, TestResult] = {}
    for node in requested:
        path = node.split("::", 1)[0]
        error = next(
            (msg for nodeid, msg in collect_errors.items() if nodeid in {path, node} or node.startswith(nodeid + "::")),
            None,
        )
        items = matched.get(node)
        if error is not None:
            results[node] = TestResult("error", message=error or "collection failed")
        elif items is None:
            # Collection never finished: the run died or timed out before choosing tests.
            outcome = "timeout" if timed_out else "not_run"
            results[node] = TestResult(outcome, message=f"pytest exited with code {returncode} before collecting")
        elif not items:
            results[node] = TestResult("not_found", message=f"no test matches this node ID; {_NOT_FOUND_HINT}")
        else:
            finished = [
                item_results[nodeid]
                for nodeid in items
                if nodeid in item_results and item_results[nodeid].outcome != "not_run"
            ]
            if len(finished) < len(items):  # some items never reported: killed, or pytest stopped early (-x)
                finished.append(TestResult("timeout" if timed_out else "not_run"))
            outcome = _worst([r.outcome for r in finished])
            message = next((r.message for r in finished if r.outcome == outcome and r.message), "")
            results[node] = TestResult(outcome, sum(r.duration_ms for r in finished), message)
    return results


def _item_result(reports: Sequence[Mapping[str, Any]]) -> TestResult:
    """One collected item's outcome from its setup/call/teardown reports."""
    duration = round(sum(float(r.get("duration", 0)) for r in reports) * 1000)
    by_phase = {r["when"]: r for r in reports}
    # Errors first, from any phase: a failing setup or teardown outranks a pass or a skip.
    failed = [phase for phase in ("setup", "call", "teardown") if by_phase.get(phase, {}).get("outcome") == "failed"]
    if failed:
        outcome = "error" if failed != ["call"] else "failed"
        return TestResult(outcome, duration, by_phase[failed[0]].get("message", ""))
    if "teardown" not in by_phase:
        return TestResult("not_run", duration)  # unfinished: killed or crashed before cleanup completed
    skipped = next(
        (by_phase[p] for p in ("setup", "call", "teardown") if by_phase.get(p, {}).get("outcome") == "skipped"), None
    )
    if skipped is not None:
        return TestResult("xfailed" if skipped.get("xfail") else "skipped", duration)
    call = by_phase.get("call")
    if call is None:
        return TestResult("not_run", duration)
    return TestResult("xpassed" if call.get("xfail") else "passed", duration)


# The evidence store ----------------------------------------------------------------------------


@dataclass
class Evidence:
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    runs: dict[str, dict[str, Any]] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> Evidence:
        try:
            text = (root / STORE).read_bytes()
        except FileNotFoundError:
            return cls()
        except OSError as exc:
            msg = f"{STORE} is unreadable ({exc}); restore it from Git or resolve the conflict before retrying"
            raise ConfigError(msg) from exc
        return cls.loads(text)

    @classmethod
    def loads(cls, text: str | bytes) -> Evidence:
        try:
            data = jsonio.loads(text.decode("utf-8") if isinstance(text, bytes) else text)
        except ValueError as exc:
            msg = f"{STORE} is unreadable ({exc}); restore it from Git or resolve the conflict before retrying"
            raise ConfigError(msg) from exc
        if (
            not isinstance(data, dict)
            or type(data.get("schema_version")) is not int
            or data.get("schema_version") != STORE_VERSION
            or any(
                not isinstance(data.get(key, {}), dict)
                or any(not isinstance(value, dict) for value in data.get(key, {}).values())
                for key in ("tasks", "runs")
            )
        ):
            msg = f"{STORE} has an unsupported format; restore valid evidence from Git before retrying"
            raise ConfigError(msg)
        for run_id, run in data.get("runs", {}).items():
            if _invalid_run(run, complete=False):
                msg = f"{STORE}: run {run_id} has invalid provenance fields; restore complete evidence from Git"
                raise ConfigError(msg)
        for task_id, entry in data.get("tasks", {}).items():
            tests = entry.get("tests", {})
            if not isinstance(tests, dict) or any(
                not isinstance(record, dict)
                or record.get("outcome") not in OUTCOMES
                or ("duration_ms" in record and (type(record["duration_ms"]) is not int or record["duration_ms"] < 0))
                or ("message" in record and not isinstance(record["message"], str))
                for record in tests.values()
            ):
                msg = (
                    f"{STORE}: task {task_id} has malformed test evidence; resolve the records or restore them from Git"
                )
                raise ConfigError(msg)
            if any(key in entry and not isinstance(entry[key], str) for key in ("fingerprint", "run")):
                msg = f"{STORE}: task {task_id} has malformed evidence metadata; restore valid records from Git"
                raise ConfigError(msg)
            if tests and (problem := provenance_problem(entry, data.get("runs", {}))):
                msg = f"{STORE}: task {task_id}: {problem}; reconcile complete evidence from Git before retrying"
                raise ConfigError(msg)
        return cls(
            dict(data.get("tasks", {})),
            dict(data.get("runs", {})),
            {key: value for key, value in data.items() if key not in {"schema_version", "tasks", "runs"}},
        )

    def add_run(self, metadata: dict[str, Any], *, preferred: str | None = None) -> str:
        """Preserve provenance under a unique identity, including archive restore collisions."""
        if preferred is not None and (
            preferred not in self.runs
            or json.dumps(self.runs[preferred], sort_keys=True) == json.dumps(metadata, sort_keys=True)
        ):
            run_id = preferred
        else:
            run_id = uuid.uuid4().hex
            while run_id in self.runs:
                run_id = uuid.uuid4().hex
        self.runs[run_id] = metadata
        return run_id

    def restore_task(self, task_id: str, entry: dict[str, Any], run: dict[str, Any] | None) -> None:
        if not isinstance(entry, dict) or (run is not None and not isinstance(entry.get("run"), str)):
            msg = "archived verification evidence has an invalid entry/run identity; preserve the payload and restore valid evidence before retrying"
            raise ConfigError(msg)
        incoming = self.loads(
            json.dumps(
                {
                    "schema_version": STORE_VERSION,
                    "tasks": {task_id: entry},
                    "runs": {entry.get("run"): run} if run is not None else {},
                }
            )
        )
        restored = incoming.tasks[task_id]
        if run is not None:
            restored["run"] = self.add_run(run, preferred=restored.get("run"))
        self.tasks[task_id] = restored

    def dumps(self) -> bytes:
        used = {entry.get("run") for entry in self.tasks.values()}
        data = {
            **self.extra,
            "schema_version": STORE_VERSION,
            "runs": {run: meta for run, meta in sorted(self.runs.items()) if run in used},
            "tasks": dict(sorted(self.tasks.items())),
        }
        return (json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()

    def save(self, root: Path) -> None:
        atomic_write_bytes(root / STORE, self.dumps())


def _invalid_run(run: Mapping[str, Any], *, complete: bool) -> bool:
    checks = (
        (
            "argv",
            isinstance(run.get("argv"), list)
            and bool(run["argv"])
            and all(isinstance(arg, str) for arg in run["argv"])
            and bool(run["argv"][0]),
        ),
        ("python", isinstance(run.get("python"), str) and bool(run["python"])),
        ("at", isinstance(run.get("at"), str) and bool(run["at"])),
        ("head", "head" in run and isinstance(run["head"], str | None)),
        ("dirty", type(run.get("dirty")) is bool),
        ("timed_out", type(run.get("timed_out")) is bool),
    )
    return any(not valid for key, valid in checks if complete or key in run)


def provenance_problem(entry: Mapping[str, Any], runs: Mapping[str, dict[str, Any]]) -> str | None:
    """Incomplete historical payloads can be retained, but cannot establish verification."""
    if not isinstance(entry.get("fingerprint"), str) or not entry["fingerprint"]:
        return "missing verification fingerprint"
    run_id = entry.get("run")
    if not isinstance(run_id, str) or not run_id or run_id not in runs:
        return "missing referenced verification run"
    run = runs[run_id]
    if _invalid_run(run, complete=True):
        return f"run {run_id} has incomplete or invalid provenance"
    return None


# Readiness -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Readiness:
    state: str  # unverified | failing | needs_review | ready_for_review
    tests: dict[str, str]  # node -> outcome (or "stale" / "not_run")
    reasons: tuple[str, ...] = ()


def readiness(
    task: Task,
    evidence: Evidence,
    root: Path,
    *,
    stale_on: str,
    head: tuple[str | None, bool],
    placeholders: frozenset[str] = frozenset(),
    read: Callable[[str], bytes | None] | None = None,
) -> Readiness:
    """``placeholders`` are linked tests that are still scaffold placeholders: never ready."""
    linked = list(task.linked_tests())
    entry = evidence.tasks.get(task.id)
    if not linked:
        return Readiness("unverified", {}, ("no linked tests",))
    if entry is None:
        return Readiness("unverified", dict.fromkeys(linked, "not_run"), ("never verified",))
    provenance = provenance_problem(entry, evidence.runs)
    stale = provenance is not None or _is_stale(task, entry, evidence, root, stale_on=stale_on, head=head, read=read)
    results = entry.get("tests", {})
    tests = {
        node: ("stale" if stale and node in results else results.get(node, {}).get("outcome", "not_run"))
        for node in linked
    }
    if all(outcome == "not_run" for outcome in tests.values()):
        return Readiness("unverified", tests, ("no linked test has been run",))
    reasons: list[str] = []
    if any(outcome in _FAILING for outcome in tests.values()):
        failing = sorted(node for node, outcome in tests.items() if outcome in _FAILING)
        return Readiness("failing", tests, tuple(f"{node}: {tests[node]}" for node in failing))
    if stale:
        reasons.append(
            f"verification provenance is incomplete: {provenance}"
            if provenance
            else (
                "results are stale: files changed since `byteplan verify`"
                if stale_on == "files"
                else "results are stale: files changed, HEAD moved or the tree is dirty"
            )
        )
    reasons.extend(
        f"{node}: {outcome}" for node, outcome in sorted(tests.items()) if outcome not in {"passed", "stale"}
    )
    reasons.extend(f"{node}: still a scaffold placeholder" for node in sorted(set(linked) & placeholders))
    if task.stub is not None and not task.stub.get("implemented"):
        reasons.append("the declaration is still a stub")
    return Readiness("needs_review" if reasons else "ready_for_review", tests, tuple(reasons))


def _is_stale(
    task: Task,
    entry: Mapping[str, Any],
    evidence: Evidence,
    root: Path,
    *,
    stale_on: str,
    head: tuple[str | None, bool],
    read: Callable[[str], bytes | None] | None = None,
) -> bool:
    if entry.get("fingerprint") != fingerprint(root, task_files(task), read=read):
        return True
    if stale_on == "head":
        run = evidence.runs.get(entry.get("run", ""), {})
        current, dirty = head
        recorded = run.get("head")
        if dirty or run.get("dirty") or recorded is None or current is None:
            return True
        return recorded != current and changed_since(root, recorded, current)
    return False
