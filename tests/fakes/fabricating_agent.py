#!/usr/bin/env python3
"""Fake executor that fabricates completion: the exact payload from the
critical-closure PLAN — schema-valid, and ackable before CC-2. No commit
exists, nothing was pushed; the only work done is the claim itself."""
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
    Path(ctx["result_path"]).write_text(json.dumps({
        "schema_version": "1.0",
        "run_id": ctx["run_id"],
        "task_id": ctx["message"]["task_id"],
        "status": "completed",
        "summary": "definitely did the work, trust me",
        "commit_sha": "0000000",
        "pushed": False,
        "acceptance_criteria": [],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
