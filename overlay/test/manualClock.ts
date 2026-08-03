import type { DiffFlowClock } from "../src/diffFlow";

interface PendingTimer {
  at: number;
  callback: () => void;
}

/** Deterministic timer boundary: advances only diffFlow-owned timers, never I/O. */
export class ManualClock implements DiffFlowClock {
  private nowMs = 0;
  private nextHandle = 1;
  private readonly timers = new Map<number, PendingTimer>();

  setTimeout(callback: () => void, delayMs: number): number {
    const handle = this.nextHandle++;
    this.timers.set(handle, {
      at: this.nowMs + Math.max(0, delayMs),
      callback,
    });
    return handle;
  }

  clearTimeout(handle: unknown): void {
    if (typeof handle === "number") this.timers.delete(handle);
  }

  pendingCount(): number {
    return this.timers.size;
  }

  advanceBy(elapsedMs: number): void {
    if (elapsedMs < 0) throw new Error("manual clock cannot move backwards");
    const target = this.nowMs + elapsedMs;
    while (true) {
      const due = [...this.timers.entries()]
        .filter(([, timer]) => timer.at <= target)
        .sort(([leftHandle, left], [rightHandle, right]) =>
          left.at - right.at || leftHandle - rightHandle,
        )[0];
      if (due === undefined) break;
      const [handle, timer] = due;
      this.timers.delete(handle);
      this.nowMs = timer.at;
      timer.callback();
    }
    this.nowMs = target;
  }
}
