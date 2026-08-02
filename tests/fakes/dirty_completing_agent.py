#!/usr/bin/env python3
"""Fake executor that dirties the tree and exits 0 quickly, writing NO result.

The dangerous-normal case: rc=0, no result file, and real work that exists
only in the throwaway worktree. Dispatch step 12 must bundle it before any
supervisor considers removal.
"""
import json
import os
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) > 1:
        json.loads(Path(sys.argv[1]).read_text())  # ctx must be readable JSON
    wt = Path.cwd()
    tracked = wt / "tracked.txt"
    tracked.write_text(tracked.read_text() + "quick dirty edit\n")
    (wt / "untracked-note.txt").write_text("uncommitted scratch\n")
    counter = os.environ.get("COUNTER_FILE")
    if counter:
        with open(counter, "a") as f:
            f.write("invoked\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
