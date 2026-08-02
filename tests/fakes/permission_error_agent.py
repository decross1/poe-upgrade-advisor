#!/usr/bin/env python3
"""Fake executor replaying the acceptEdits incident: Bash is blocked, so the
agent emits the SAME PermissionError on stderr every single time, writes no
result file, and exits non-zero. Byte-identical output per invocation — zero
new evidence, no strategy change, exactly what ran ~50 times in production.
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
    print("PermissionError: [Errno 13] Bash tool denied by acceptEdits "
          "permission mode; cannot run 'python3 agents/postmaster/ledger.py'",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
