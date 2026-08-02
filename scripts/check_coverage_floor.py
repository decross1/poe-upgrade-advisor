#!/usr/bin/env python3
"""Fail when measured Python coverage is below the recorded floor."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage", type=Path, default=Path("coverage.json"))
    parser.add_argument(
        "--floor",
        type=Path,
        default=Path("agents/merge_robot/coverage_floor.json"),
    )
    args = parser.parse_args()

    measured = float(json.loads(args.coverage.read_text())["totals"]["percent_covered"])
    floor = float(json.loads(args.floor.read_text())["floor"])
    print(f"coverage: {measured:.2f}% (required: {floor:.2f}%)")
    if measured < floor:
        print(f"COVERAGE-GATE-FAILED: {measured:.2f}% is below {floor:.2f}%")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
