#!/usr/bin/env python3
"""Fake executor that asks for another go: schema-valid `needs_retry` result.
needs_retry is deliberately NOT ackable; only the attempt cap retires it."""
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
        "status": "needs_retry",
        "summary": "fake agent made partial progress, retry wanted",
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
