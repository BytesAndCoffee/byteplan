# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@icloud.com>
#
# SPDX-License-Identifier: MIT
"""Command-line entry point. Subcommands are added phase by phase."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from byteplan.__about__ import __version__

if TYPE_CHECKING:
    from collections.abc import Sequence

EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="byteplan",
        description="Plan in code. Track in one place.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_subparsers(dest="command", metavar="COMMAND")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
