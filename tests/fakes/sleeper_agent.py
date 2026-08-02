#!/usr/bin/env python3
"""Fake executor that outlives its wall-clock cap. The timeout test
monkeypatches resolve_budgets to max_wall_clock_seconds=1, so the dispatcher
kills this process ~1s in; the 3s sleep is never completed. The counter line
is flushed BEFORE sleeping so the invocation is still observable."""
import json
import os
import sys
import time
from pathlib import Path


def main() -> int:
    json.loads(Path(sys.argv[1]).read_text())
    counter = os.environ.get("COUNTER_FILE")
    if counter:
        with open(counter, "a") as f:
            f.write("invoked\n")
    time.sleep(3)  # dispatcher's 1s cap kills us long before this returns
    return 0


if __name__ == "__main__":
    sys.exit(main())
