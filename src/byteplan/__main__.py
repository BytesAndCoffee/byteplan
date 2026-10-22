# SPDX-FileCopyrightText: 2026-present Michael Yazdani <yazdmich@gmail.com>
#
# SPDX-License-Identifier: MIT
"""``python -m byteplan``: used by the Git merge driver so it doesn't depend on $PATH."""

from byteplan.cli import main

raise SystemExit(main())
