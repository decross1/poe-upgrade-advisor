#!/usr/bin/env python3
"""Benchmark harness for the overlay stack decision (TASK-201 / ADR-0004).

Measures, per stack, on the machine it runs on:
  * cold start    : process spawn -> first verdict card painted (external wall
                    clock) and main-entry -> paint (reported by the app)
  * memory        : steady-state and peak process-tree RSS (+ PSS where the OS
                    exposes it) while idle and while rendering
  * render latency: trigger -> real platform clipboard read -> card painted,
                    split into clipboard_ms (host) and render_ms (renderer)

Protocol (stack-neutral, JSON lines on stdio):
  runner -> app : {"cmd":"render","seq":N,"fixture_name":"upgrade"}
                  {"cmd":"quit"}
  app -> runner : {"bench":"cold_start","seq":0,"main_to_paint_ms":X,...}
                  {"bench":"render","seq":N,"clipboard_ms":C,"render_ms":R}

Usage:
  python3 run_bench.py --stack electron --runs 15 --renders 30 \
      --headless --out results/<name>.json
  python3 run_bench.py --stack tauri --tauri-bin path/to/binary ...
  python3 run_bench.py compare results/a.json results/b.json

Stdlib only; no third-party deps.
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
FIXTURE_NAMES = ["upgrade", "sidegrade", "downgrade", "cant_evaluate"]
COLD_START_TIMEOUT_S = 45.0
RENDER_TIMEOUT_S = 15.0
QUIT_TIMEOUT_S = 10.0


# --------------------------------------------------------------------------
# process-tree memory sampling (Linux /proc; `ps` fallback elsewhere)
# --------------------------------------------------------------------------
def _pid_tree_pids_linux(root: int) -> list[int]:
    children: dict[int, list[int]] = {}
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as fh:
                parts = fh.read().rsplit(")", 1)[1].split()
            ppid = int(parts[1])
        except (OSError, IndexError, ValueError):
            continue
        children.setdefault(ppid, []).append(int(entry))
    out, stack = [], [root]
    while stack:
        pid = stack.pop()
        out.append(pid)
        stack.extend(children.get(pid, []))
    return out


def _mem_kb_linux(pids: list[int]) -> tuple[int, int]:
    """(rss_kb, pss_kb) summed over pids; pss=0 when unreadable."""
    rss = pss = 0
    for pid in pids:
        try:
            with open(f"/proc/{pid}/status") as fh:
                for line in fh:
                    if line.startswith("VmRSS:"):
                        rss += int(line.split()[1])
                        break
        except OSError:
            pass
        try:
            with open(f"/proc/{pid}/smaps_rollup") as fh:
                for line in fh:
                    if line.startswith("Pss:"):
                        pss += int(line.split()[1])
                        break
        except OSError:
            pass
    return rss, pss


def tree_memory_kb(root_pid: int) -> tuple[int, int] | None:
    if os.path.isdir("/proc"):
        return _mem_kb_linux(_pid_tree_pids_linux(root_pid))
    try:  # portable fallback: parent process only, RSS via ps
        out = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(root_pid)],
            check=True, capture_output=True, text=True,
        )
        return int(out.stdout.strip()), 0
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


class MemorySampler(threading.Thread):
    def __init__(self, root_pid: int, interval_s: float = 0.15) -> None:
        super().__init__(daemon=True)
        self.root_pid = root_pid
        self.interval_s = interval_s
        self.samples: list[tuple[float, int, int]] = []  # t, rss_kb, pss_kb
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            mem = tree_memory_kb(self.root_pid)
            if mem is not None:
                self.samples.append((time.perf_counter(), mem[0], mem[1]))
            time.sleep(self.interval_s)

    def halt(self) -> None:
        self._stop.set()


# --------------------------------------------------------------------------
# app process plumbing
# --------------------------------------------------------------------------
def _stdout_reader(stream, events: queue.Queue) -> None:
    for line in iter(stream.readline, ""):
        line = line.strip()
        if not line.startswith('{"bench"'):
            continue
        try:
            events.put((time.perf_counter(), json.loads(line)))
        except json.JSONDecodeError:
            continue


def launch_stack(stack: str, headless: bool, tauri_bin: str | None) -> subprocess.Popen:
    env = dict(os.environ)
    env["BENCH_FIXTURES_DIR"] = str(BENCH_DIR / "fixtures")
    popen_kwargs: dict = {}
    if os.name == "posix":
        popen_kwargs["preexec_fn"] = os.setsid  # own process group, clean kill

    if stack == "electron":
        electron_bin = BENCH_DIR / "electron" / "node_modules" / ".bin" / "electron"
        if not electron_bin.exists():
            sys.exit(
                "electron not installed; run: "
                f"npm install --prefix {BENCH_DIR / 'electron'}"
            )
        cmd = [str(electron_bin)]
        if headless:
            env["BENCH_HEADLESS"] = "1"
            # Sandbox flags must reach Chromium via argv/env: the setuid
            # helper check runs before any JS switch can apply.
            env["ELECTRON_DISABLE_SANDBOX"] = "1"
            cmd += [
                "--no-sandbox",
                "--ozone-platform=headless",
                "--disable-gpu",
                "--disable-dev-shm-usage",
            ]
        cmd.append(".")
        cwd = BENCH_DIR / "electron"
    elif stack == "tauri":
        if not tauri_bin:
            sys.exit("--tauri-bin is required for --stack tauri (see README)")
        cmd, cwd = [tauri_bin], BENCH_DIR / "tauri"
    else:
        sys.exit(f"unknown stack: {stack}")

    return subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        **popen_kwargs,
    )


def terminate_app(proc: subprocess.Popen) -> None:
    try:
        if proc.stdin:
            proc.stdin.write(json.dumps({"cmd": "quit"}) + "\n")
            proc.stdin.flush()
        proc.wait(timeout=QUIT_TIMEOUT_S)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


# --------------------------------------------------------------------------
# measurement
# --------------------------------------------------------------------------
def one_run(stack: str, headless: bool, renders: int, tauri_bin: str | None) -> dict:
    proc = launch_stack(stack, headless, tauri_bin)
    t_spawn = time.perf_counter()
    events: queue.Queue = queue.Queue()
    threading.Thread(
        target=_stdout_reader, args=(proc.stdout, events), daemon=True
    ).start()
    sampler = MemorySampler(proc.pid)
    sampler.start()

    def wait_for(pred, timeout_s: float) -> tuple[float, dict]:
        deadline = time.perf_counter() + timeout_s
        stash: list[tuple[float, dict]] = []
        try:
            while True:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    raise TimeoutError("bench event timeout")
                item = events.get(timeout=remaining)
                if pred(item[1]):
                    return item
                stash.append(item)
        finally:
            for it in stash:
                events.put(it)

    result: dict = {"ok": False, "renders": []}
    try:
        if proc.stdin is None:
            raise OSError("app stdin unavailable")

        def send(seq: int) -> None:
            fixture = FIXTURE_NAMES[seq % len(FIXTURE_NAMES)]
            proc.stdin.write(
                json.dumps({"cmd": "render", "seq": seq, "fixture_name": fixture}) + "\n"
            )
            proc.stdin.flush()

        send(0)  # cold-start paint (no clipboard read)
        t_cold, cold = wait_for(
            lambda e: e.get("bench") == "cold_start", COLD_START_TIMEOUT_S
        )
        result["cold_start_external_ms"] = (t_cold - t_spawn) * 1000.0
        result["cold_start_internal_ms"] = cold.get("main_to_paint_ms")

        t_steady_from = time.perf_counter()
        time.sleep(1.0)  # idle settle window -> steady-state memory baseline
        t_steady_to = time.perf_counter()

        for seq in range(1, renders + 1):
            send(seq)
            _t, rep = wait_for(
                lambda e, s=seq: e.get("bench") == "render" and e.get("seq") == s,
                RENDER_TIMEOUT_S,
            )
            result["renders"].append(
                {
                    "seq": seq,
                    "clipboard_ms": rep.get("clipboard_ms"),
                    "render_ms": rep.get("render_ms"),
                }
            )

        sampler.halt()
        samples = sampler.samples
        steady = [s for s in samples if t_steady_from <= s[0] <= t_steady_to]
        result["mem_steady_mb"] = (
            round(statistics.median(s[1] for s in steady) / 1024.0, 1) if steady else None
        )
        result["mem_steady_pss_mb"] = (
            round(statistics.median(s[2] for s in steady) / 1024.0, 1)
            if steady and any(s[2] for s in steady)
            else None
        )
        result["mem_peak_mb"] = (
            round(max(s[1] for s in samples) / 1024.0, 1) if samples else None
        )
        result["ok"] = True
    finally:
        sampler.halt()
        terminate_app(proc)
    return result


def percentile(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    ordered = sorted(xs)
    rank = max(0, min(len(ordered) - 1, round((p / 100.0) * (len(ordered) - 1))))
    return ordered[rank]


def summarize(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0}
    return {
        "n": len(xs),
        "min": round(min(xs), 2),
        "p50": round(percentile(xs, 50), 2),
        "p95": round(percentile(xs, 95), 2),
        "mean": round(statistics.fmean(xs), 2),
        "max": round(max(xs), 2),
    }


def do_run(args: argparse.Namespace) -> None:
    runs = []
    for i in range(args.runs):
        print(f"[run {i + 1}/{args.runs}]", flush=True)
        try:
            runs.append(one_run(args.stack, args.headless, args.renders, args.tauri_bin))
        except (TimeoutError, OSError) as exc:
            runs.append({"ok": False, "error": str(exc), "renders": []})
            print(f"  failed: {exc}", flush=True)

    good = [r for r in runs if r.get("ok")]
    cold_ext = [r["cold_start_external_ms"] for r in good]
    cold_int = [r["cold_start_internal_ms"] for r in good if r.get("cold_start_internal_ms")]
    render_ms = [
        rep["render_ms"] for r in good for rep in r["renders"] if rep.get("render_ms") is not None
    ]
    clip_ms = [
        rep["clipboard_ms"]
        for r in good
        for rep in r["renders"]
        if rep.get("clipboard_ms") is not None
    ]
    steady = [r["mem_steady_mb"] for r in good if r.get("mem_steady_mb")]
    steady_pss = [r["mem_steady_pss_mb"] for r in good if r.get("mem_steady_pss_mb")]
    peak = [r["mem_peak_mb"] for r in good if r.get("mem_peak_mb")]

    summary = {
        "stack": args.stack,
        "headless": bool(args.headless),
        "host": {
            "platform": sys.platform,
            "machine": os.uname().machine if hasattr(os, "uname") else "unknown",
            "cpu_count": os.cpu_count(),
        },
        "runs_requested": args.runs,
        "runs_ok": len(good),
        "renders_per_run": args.renders,
        "cold_start_external_ms": summarize(cold_ext),
        "cold_start_internal_ms": summarize(cold_int),
        "clipboard_read_ms": summarize(clip_ms),
        "render_ms": summarize(render_ms),
        "mem_steady_mb": summarize(steady),
        "mem_steady_pss_mb": summarize(steady_pss),
        "mem_peak_mb": summarize(peak),
    }
    report = {"summary": summary, "runs": runs}

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n")
        print(f"wrote {args.out}")
    print(json.dumps(summary, indent=2))


def do_compare(a_path: Path, b_path: Path) -> None:
    a = json.loads(a_path.read_text())["summary"]
    b = json.loads(b_path.read_text())["summary"]
    rows = [
        ("cold start p50 (ms)", "cold_start_external_ms", "p50"),
        ("cold start p95 (ms)", "cold_start_external_ms", "p95"),
        ("render p50 (ms)", "render_ms", "p50"),
        ("render p95 (ms)", "render_ms", "p95"),
        ("clipboard read p95 (ms)", "clipboard_read_ms", "p95"),
        ("steady RSS p50 (MB)", "mem_steady_mb", "p50"),
        ("peak RSS p50 (MB)", "mem_peak_mb", "p50"),
    ]
    print(f"| metric | {a['stack']} | {b['stack']} |")
    print("|---|---|---|")
    for label, key, stat in rows:
        va = a.get(key, {}).get(stat, "n/a")
        vb = b.get(key, {}).get(stat, "n/a")
        print(f"| {label} | {va} | {vb} |")


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "compare":
        ap = argparse.ArgumentParser(description="compare two result JSON files")
        ap.add_argument("files", nargs=2)
        ns = ap.parse_args(sys.argv[2:])
        do_compare(Path(ns.files[0]), Path(ns.files[1]))
        return

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stack", choices=["electron", "tauri"], required=True)
    ap.add_argument("--runs", type=int, default=10, help="cold-start repetitions")
    ap.add_argument("--renders", type=int, default=30, help="render triggers per run")
    ap.add_argument("--headless", action="store_true", help="no display server (electron ozone headless)")
    ap.add_argument("--tauri-bin", default=None, help="path to built tauri bench binary")
    ap.add_argument("--out", default=None, help="write results JSON here")
    do_run(ap.parse_args())


if __name__ == "__main__":
    main()
