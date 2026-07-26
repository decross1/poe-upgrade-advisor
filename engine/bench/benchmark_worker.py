#!/usr/bin/env python3
"""Measure warm JSON-RPC diff latency against the TASK-101 budget."""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import statistics
import subprocess
import sys
import time


ROOT = pathlib.Path(__file__).resolve().parents[2]


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", required=True, type=pathlib.Path)
    parser.add_argument("--item", required=True, type=pathlib.Path)
    parser.add_argument("--preset", required=True, choices=("mapping", "bossing"))
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=5)
    args = parser.parse_args()
    if args.samples < 1 or args.warmup < 1:
        parser.error("--samples and --warmup must be positive")

    worker = subprocess.Popen(
        [sys.executable, ROOT / "engine" / "pobcalc", "serve"],
        cwd=ROOT,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )
    assert worker.stdin and worker.stdout and worker.stderr
    latencies: list[float] = []
    try:
        for index in range(args.warmup + args.samples):
            request = {
                "jsonrpc": "2.0",
                "id": index,
                "method": "diff",
                "params": {
                    "build": str(args.build.resolve()),
                    "item": str(args.item.resolve()),
                    "preset": args.preset,
                },
            }
            started = time.perf_counter()
            worker.stdin.write(json.dumps(request, separators=(",", ":")) + "\n")
            worker.stdin.flush()
            response = json.loads(worker.stdout.readline())
            elapsed_ms = (time.perf_counter() - started) * 1000
            if "error" in response:
                raise RuntimeError(response["error"]["message"])
            if index >= args.warmup:
                latencies.append(elapsed_ms)
    finally:
        worker.stdin.close()
        worker.wait(timeout=10)
        worker.stdout.close()
        worker.stderr.close()

    result = {
        "samples": len(latencies),
        "min_ms": min(latencies),
        "median_ms": statistics.median(latencies),
        "p95_ms": percentile(latencies, 0.95),
        "max_ms": max(latencies),
        "budget_ms": 150,
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if result["p95_ms"] < result["budget_ms"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
