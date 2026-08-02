"""Telemetry port — **fail-open**.

Analytics must never be able to stop the org. If the store cannot be written,
emit `TELEMETRY-DEGRADED` loudly and keep working; the run report surfaces it.
Spend accounting that *must not* be lost lives in `budget.py`, which is
fail-closed. HANDOFF section 3.5.

Lane A calls this port. Lane B replaces `JsonlTelemetry` with the real backend
behind the same Protocol; the call sites do not change.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

TELEMETRY_DEGRADED = "TELEMETRY-DEGRADED"

#: Fields every invocation record carries. Absent provider data is `None`,
#: never omitted and never zero — a missing token count must not read as free.
INVOCATION_FIELDS = (
    "run_id", "task_id", "parent_task_id", "role", "task_class", "decision",
    "model", "model_tier", "provider", "reasoning_effort",
    "started_at", "completed_at", "duration_seconds",
    "input_tokens", "output_tokens", "cached_input_tokens",
    "cash_cost_usd", "allowance_pct_estimated", "allowance_pct_source",
    "invocation_weight",
    "tool_calls", "files_inspected", "files_modified",
    "lines_added", "lines_deleted", "test_runs", "attempt_number",
    "result_status", "commit_sha", "pushed",
    "error_fingerprint_before", "error_fingerprint_after",
    "acceptance_criteria_passed", "acceptance_criteria_failed",
    "accepted", "rolled_back", "suppressed_reason",
)


@runtime_checkable
class TelemetryPort(Protocol):
    """What the dispatcher needs from telemetry. Fail-open on every method."""

    def start(self, **fields: Any) -> str:
        """Open an invocation record. Returns its `run_id`."""

    def finish(self, run_id: str, **fields: Any) -> None:
        """Close an invocation record. Merges `fields` into the open record."""

    def suppressed(self, **fields: Any) -> None:
        """Record a decision that cost zero model tokens.

        This is not optional bookkeeping: "empty inbox produced no model call"
        is only provable because the non-call was written down.
        """

    def crash(self, run_id: str, reason: str) -> None:
        """Mark an open record unrecoverable-in-place but preserved."""


class NullTelemetry:
    """Discards everything. For tests that are not asserting on telemetry."""

    def start(self, **fields: Any) -> str:
        return fields.get("run_id") or uuid.uuid4().hex

    def finish(self, run_id: str, **fields: Any) -> None:
        return None

    def suppressed(self, **fields: Any) -> None:
        return None

    def crash(self, run_id: str, reason: str) -> None:
        return None


class JsonlTelemetry:
    """Append-only JSONL default backend. Fail-open by construction.

    Every write is one line; a torn line loses one record, not the file. This
    is the interim implementation so Lane A is never blocked on Lane B; Lane B
    replaces it behind `TelemetryPort`.
    """

    def __init__(self, path: str | Path, stderr=None) -> None:
        self.path = Path(path)
        self._stderr = stderr if stderr is not None else sys.stderr
        self.degraded = False

    def _emit(self, record: dict) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a") as f:
                f.write(json.dumps(record, default=str) + "\n")
                f.flush()
                os.fsync(f.fileno())
        except Exception as e:  # noqa: BLE001 — fail-open is the whole point
            self.degraded = True
            print(f"{TELEMETRY_DEGRADED}: {type(e).__name__}: {e}", file=self._stderr)

    def start(self, **fields: Any) -> str:
        run_id = fields.pop("run_id", None) or uuid.uuid4().hex
        self._emit({"event": "start", "run_id": run_id, **fields})
        return run_id

    def finish(self, run_id: str, **fields: Any) -> None:
        self._emit({"event": "finish", "run_id": run_id, **fields})

    def suppressed(self, **fields: Any) -> None:
        self._emit({"event": "suppressed", **fields})

    def crash(self, run_id: str, reason: str) -> None:
        self._emit({"event": "crash", "run_id": run_id, "reason": reason})
