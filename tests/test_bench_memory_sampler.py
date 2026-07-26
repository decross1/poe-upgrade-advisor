"""Regression guard for issue #37 (follow-up to TASK-201, PR #35).

MemorySampler must not shadow threading.Thread._stop (a CPython-internal
method invoked after fork / on interpreter shutdown — shadowing it emits an
ignored-exception warning). The sampler's stop event is _stop_sampling; the
public control surface is halt().
"""
import importlib.util
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "run_bench", ROOT / "overlay" / "bench" / "run_bench.py"
)
run_bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run_bench)

MemorySampler = run_bench.MemorySampler


def test_sampler_does_not_shadow_thread__stop() -> None:
    assert "_stop" not in MemorySampler.__dict__
    assert MemorySampler._stop is threading.Thread._stop
    assert isinstance(MemorySampler(0)._stop_sampling, threading.Event)


def test_sampler_halt_stops_run_loop() -> None:
    sampler = MemorySampler(root_pid=0, interval_s=0.01)  # pid 0: no samples needed
    sampler.start()
    time.sleep(0.05)
    sampler.halt()
    sampler.join(timeout=2)
    assert not sampler.is_alive()
