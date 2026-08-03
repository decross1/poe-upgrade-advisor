#!/usr/bin/env python3
"""Mechanical pass condition for the canary probe file (TASK-999-S1).

The canary's single required check, per the reconstructed base contract §16
as ratified 2026-08-03 (audit disposition R4: this script replaces the
argv-exact ``python3 -c`` allowlist exception). The CC-1 command policy
allowlists exactly the string ``python3 scripts/check_canary_probe.py``.

Checks, all mechanical:
  1. ``docs/agent-org/canary-probe.md`` exists;
  2. its first line is exactly ``# Canary probe``;
  3. it is at most 30 lines.

Exit 0 on pass, 1 on any failure. Read-only; writes nothing anywhere.
"""

from __future__ import annotations

import pathlib
import sys

PROBE = pathlib.Path("docs/agent-org/canary-probe.md")
MAX_LINES = 30
REQUIRED_FIRST_LINE = "# Canary probe"


def check(probe: pathlib.Path = PROBE) -> int:
    if not probe.exists():
        print(f"FAIL {probe}: missing")
        return 1
    lines = probe.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0].rstrip() != REQUIRED_FIRST_LINE:
        got = lines[0].rstrip() if lines else "<empty file>"
        print(f"FAIL {probe}: first line must be {REQUIRED_FIRST_LINE!r}, got {got!r}")
        return 1
    if len(lines) > MAX_LINES:
        print(f"FAIL {probe}: {len(lines)} lines exceeds {MAX_LINES}")
        return 1
    print(f"OK {probe}: {len(lines)} lines")
    return 0


if __name__ == "__main__":
    sys.exit(check())
