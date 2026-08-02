#!/usr/bin/env python3
"""Fake agent that fails loudly: counter line, stderr marker, no result."""
import os
import sys
from pathlib import Path

counter = Path(os.environ["COUNTER_FILE"])
with counter.open("a") as f:
    f.write("run\n")
print("BOOM-MARKER-42: simulated tooling failure (Bash unavailable)",
      file=sys.stderr)
sys.exit(1)
