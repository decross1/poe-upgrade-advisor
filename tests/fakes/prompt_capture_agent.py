#!/usr/bin/env python3
"""Fake executor that snapshots the dispatcher-provided ctx (which carries the
exact prompt) to $CTX_COPY_FILE, then completes properly. Used to prove a
pending anti-loop strategy note was embedded in the prompt the agent saw.
"""
import json
import os
import shutil
import sys
from pathlib import Path


def main() -> int:
    ctx_path = Path(sys.argv[1])
    ctx = json.loads(ctx_path.read_text())
    counter = os.environ.get("COUNTER_FILE")
    if counter:
        with open(counter, "a") as f:
            f.write("invoked\n")
    copy_to = os.environ.get("CTX_COPY_FILE")
    if copy_to:
        shutil.copyfile(ctx_path, copy_to)
    Path(ctx["result_path"]).write_text(json.dumps({
        "schema_version": "1.0",
        "run_id": ctx["run_id"],
        "task_id": ctx["message"]["task_id"],
        "status": "completed",
        "summary": "fake agent completed after reading the strategy note",
        "commit_sha": "deadbeefcafe1234",
        "pushed": True,
        "acceptance_criteria": [
            {"id": "AC1", "status": "passed", "evidence": "fake"},
        ],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
