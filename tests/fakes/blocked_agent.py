#!/usr/bin/env python3
"""Fake executor that blocks legitimately: schema-valid `blocked` result with
blocked_reason + resume_condition (both required by the result schema)."""
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
        "status": "blocked",
        "summary": "fake agent is blocked",
        "blocked_reason": "upstream API credential absent",
        "resume_condition": "credential present in environment",
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
