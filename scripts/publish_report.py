# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Regenerate ``report_file`` on the report branch and push it (``.github/workflows/report.yml``)."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from byteplan.api import Project

MESSAGE = "Regenerate byteplan.md"


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],  # noqa: S607 - git from PATH, like every Git call here
        cwd=root,
        capture_output=True,
        text=True,
        check=check,
    )


def publish(root: Path, remote: str = "origin", branch: str = "main", attempts: int = 5) -> str:
    """``"unchanged"`` or ``"pushed"``.

    Each attempt starts from the remote branch's latest commit and regenerates from its
    registry. Another merge landing first rejects the push (non-fast-forward), so the
    next attempt picks that merge up instead of leaving the report stale.
    """
    for _ in range(attempts):
        _git(root, "fetch", "-q", remote, branch)
        _git(root, "reset", "-q", "--hard", "FETCH_HEAD")
        project = Project.open(root)
        if not project.write_report():
            return "unchanged"
        _git(root, "commit", "-qm", MESSAGE, "--", str(project.report_rel))
        if _git(root, "push", "-q", remote, f"HEAD:{branch}", check=False).returncode == 0:
            return "pushed"
    msg = f"publish_report: {remote}/{branch} kept moving; gave up after {attempts} attempts"
    raise SystemExit(msg)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path.cwd())
    parser.add_argument("--remote", default="origin")
    parser.add_argument("--branch", default="main")
    args = parser.parse_args(argv)
    print(f"publish_report: {publish(args.project, args.remote, args.branch)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
