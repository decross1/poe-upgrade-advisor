#!/usr/bin/env python3
"""Fake executor that IGNORES the ctx-injected result_path and writes
`.agent-result.json` into its own cwd (the worktree — dispatch runs the
agent there). CC-3 P2: the sweep keys off the worktree path contract, not
off how the agent resolved it, so the tree must still come out clean."""
import json
import os
import sys
from pathlib import Path


def main() -> int:
    ctx = json.loads(Path(sys.argv[1]).read_text())
    counter = os.environ.get("COUNTER_FILE")
    if counter:
        with open(counter, "a") as f:
            f.write("invoked\n")
    # Deliberately NOT ctx["result_path"]:
    (Path.cwd() / ".agent-result.json").write_text(json.dumps({
        "schema_version": "1.0",
        "run_id": ctx["run_id"],
        "task_id": ctx["message"]["task_id"],
        "status": "completed",
        "summary": "rogue writer used cwd, not the injected path",
        "commit_sha": "deadbeefcafe1234",
        "pushed": True,
        "acceptance_criteria": [
            {"id": "AC1", "status": "passed", "evidence": "fake"},
        ],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
