#!/usr/bin/env python3
"""Fake executor that writes garbage: literally "{ not json" to result_path,
then exits 0. Malformed output is an invalid attempt, not a success."""
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
    Path(ctx["result_path"]).write_text("{ not json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
