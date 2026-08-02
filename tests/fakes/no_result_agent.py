#!/usr/bin/env python3
"""Fake executor that produces nothing: exits 0, writes NO result file.

Models the measured census failure mode: rc=0 carried zero bits of
information across 1,408 invocations. The dispatcher must treat this run
as an invalid attempt (count it, never ack on it).
"""
import json
import os
import sys
from pathlib import Path


def main() -> int:
    json.loads(Path(sys.argv[1]).read_text())  # ctx must be readable JSON
    counter = os.environ.get("COUNTER_FILE")
    if counter:
        with open(counter, "a") as f:
            f.write("invoked\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
