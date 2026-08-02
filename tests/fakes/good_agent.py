#!/usr/bin/env python3
"""Fake executor that succeeds properly: writes a schema-valid `completed`
result to the ctx-declared result_path, then exits 0."""
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
        "summary": "fake agent completed the work",
        "commit_sha": "deadbeefcafe1234",
        "pushed": True,
        "acceptance_criteria": [
            {"id": "AC1", "status": "passed", "evidence": "fake"},
        ],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
