#!/usr/bin/env python3
"""Fake executor that dirties its worktree, then outlives every cap.

Models the 2026-07-26 incident shape: real work sitting uncommitted in a
throwaway worktree when the kill arrives. It edits a tracked file, drops an
untracked file carrying a fake secret, then sleeps far past any test cap so
the dispatcher must stop it (timeout / SIGTERM / HALT) while the work is
still unsaved. The `.dirty-marker` file is written LAST so a test that polls
for it knows the tree is already dirty when the marker appears.
"""
import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    if len(sys.argv) > 1:
        json.loads(Path(sys.argv[1]).read_text())  # ctx must be readable JSON
    wt = Path.cwd()
    tracked = wt / "tracked.txt"
    tracked.write_text(tracked.read_text() + "agent edit: unsaved work\n")
    (wt / "untracked-note.txt").write_text(
        "scratch work\npassword=hunter2secret\n")
    counter = os.environ.get("COUNTER_FILE")
    if counter:
        with open(counter, "a") as f:
            f.write("invoked\n")
    (wt / ".dirty-marker").write_text("dirty\n")
    time.sleep(30)  # the supervisor must kill us long before this returns
    return 0


if __name__ == "__main__":
    sys.exit(main())
