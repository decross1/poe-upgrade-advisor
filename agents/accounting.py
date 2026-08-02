"""Durable budget accounting and fail-open invocation analytics.

The two stores intentionally have opposite failure modes.  Budget writes raise
``BudgetLedgerUnavailable``; analytics writes report ``TELEMETRY-DEGRADED``
and allow the caller to continue.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import sys
import time
import uuid
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from agents.interfaces.budget import BudgetLedgerUnavailable, SqliteBudgetLedger
from agents.interfaces.telemetry import INVOCATION_FIELDS, TELEMETRY_DEGRADED

ALLOWANCE_SOURCES = frozenset({"manual_daily_reading", "proxy", "provider"})


class AccountingBudgetLedger(SqliteBudgetLedger):
    """Run, decision, and allowance accounting on the fail-closed ledger."""

    _ACCOUNTING_SCHEMA = (
        """CREATE TABLE IF NOT EXISTS governor_decisions (
             ts REAL NOT NULL, role TEXT NOT NULL, task_id TEXT,
             run_id TEXT, decision TEXT NOT NULL, reason TEXT)""",
        """CREATE TABLE IF NOT EXISTS allowance_readings (
             id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
             role TEXT NOT NULL, pct REAL NOT NULL, source TEXT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS allowance_calibrations (
             id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
             role TEXT NOT NULL, source TEXT NOT NULL,
             prior_ts REAL, prior_pct REAL, pct REAL NOT NULL,
             allowance_delta_pct REAL, weighted_seconds REAL,
             pct_per_weighted_second REAL)""",
    )

    def __init__(self, path: str | Path) -> None:
        super().__init__(path)
        for statement in self._ACCOUNTING_SCHEMA:
            self._x(statement)

    def record_decision(
        self,
        *,
        role: str,
        decision: str,
        task_id: str | None = None,
        run_id: str | None = None,
        reason: str | None = None,
        ts: float | None = None,
    ) -> None:
        self._x(
            "INSERT INTO governor_decisions VALUES (?,?,?,?,?,?)",
            (time.time() if ts is None else ts, role, task_id, run_id, decision, reason),
        )

    def record_allowance(
        self,
        *,
        role: str,
        pct: float,
        source: str,
        weighted_seconds: float | None,
        ts: float | None = None,
    ) -> dict[str, float | str | None]:
        """Record a cumulative provider reading and derive its calibration.

        ``weighted_seconds`` is the sum of invocation duration multiplied by
        invocation weight since the previous reading.  A first reading is a
        baseline and therefore has no calibration factor.
        """
        if source not in ALLOWANCE_SOURCES:
            raise ValueError(f"invalid allowance source: {source}")
        if (
            isinstance(pct, bool)
            or not isinstance(pct, (int, float))
            or not math.isfinite(pct)
            or not 0 <= pct <= 100
        ):
            raise ValueError("allowance percentage must be between 0 and 100")
        if weighted_seconds is not None and (
            isinstance(weighted_seconds, bool)
            or not isinstance(weighted_seconds, (int, float))
            or not math.isfinite(weighted_seconds)
            or weighted_seconds < 0
        ):
            raise ValueError("weighted_seconds must be a finite non-negative number or None")
        now = time.time() if ts is None else ts
        try:
            self.db.execute("BEGIN IMMEDIATE")
            prior = self._x(
                "SELECT ts, pct FROM allowance_readings WHERE role=? ORDER BY ts DESC, id DESC LIMIT 1",
                (role,),
            ).fetchone()
            self._x(
                "INSERT INTO allowance_readings (ts, role, pct, source) VALUES (?,?,?,?)",
                (now, role, pct, source),
            )
            prior_ts = prior[0] if prior else None
            prior_pct = prior[1] if prior else None
            # Dashboard percentages reset at the provider's weekly boundary.
            # A decrease therefore starts a new cycle; it is not negative use.
            delta = None
            if prior_pct is not None:
                delta = pct - prior_pct if pct >= prior_pct else pct
            factor = None
            if delta is not None and weighted_seconds is not None and weighted_seconds > 0:
                factor = delta / weighted_seconds
            self._x(
                """INSERT INTO allowance_calibrations
                   (ts, role, source, prior_ts, prior_pct, pct,
                    allowance_delta_pct, weighted_seconds, pct_per_weighted_second)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (now, role, source, prior_ts, prior_pct, pct, delta, weighted_seconds, factor),
            )
            self.db.execute("COMMIT")
        except BaseException as exc:
            try:
                if self.db.in_transaction:
                    self.db.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            if isinstance(exc, BudgetLedgerUnavailable):
                raise
            if isinstance(exc, (sqlite3.Error, OSError)):
                raise BudgetLedgerUnavailable(
                    f"budget ledger write failed: {exc}"
                ) from exc
            raise
        return {
            "role": role,
            "source": source,
            "prior_ts": prior_ts,
            "prior_pct": prior_pct,
            "pct": pct,
            "allowance_delta_pct": delta,
            "cycle_reset": prior_pct is not None and pct < prior_pct,
            "weighted_seconds": weighted_seconds,
            "pct_per_weighted_second": factor,
        }

    def latest_allowance(self, role: str) -> dict[str, Any] | None:
        row = self._x(
            """SELECT ts, role, pct, source FROM allowance_readings
               WHERE role=? ORDER BY ts DESC, id DESC LIMIT 1""",
            (role,),
        ).fetchone()
        return dict(zip(("ts", "role", "pct", "source"), row)) if row else None

    def spend_since(self, *, since_ts: float, role: str | None = None) -> dict[str, Any]:
        """Aggregate without converting unknown cost or allowance to zero."""
        where = " WHERE ts >= ?"
        args: tuple[Any, ...] = (since_ts,)
        if role is not None:
            where += " AND role = ?"
            args += (role,)
        row = self._x(
            """SELECT COUNT(*),
                      SUM(cash_usd), COUNT(cash_usd),
                      SUM(allowance_pct), COUNT(allowance_pct),
                      SUM(input_tokens), COUNT(input_tokens),
                      SUM(output_tokens), COUNT(output_tokens)
               FROM spend""" + where,
            args,
        ).fetchone()
        (
            rows,
            cash,
            cash_known,
            allowance,
            allowance_known,
            input_tokens,
            input_known,
            output_tokens,
            output_known,
        ) = row
        return {
            "invocations": rows,
            "cash_usd": cash,
            "cash_usd_known_rows": cash_known,
            "cash_usd_unknown_rows": rows - cash_known,
            "allowance_pct": allowance,
            "allowance_pct_known_rows": allowance_known,
            "allowance_pct_unknown_rows": rows - allowance_known,
            "input_tokens": input_tokens,
            "input_tokens_known_rows": input_known,
            "input_tokens_unknown_rows": rows - input_known,
            "output_tokens": output_tokens,
            "output_tokens_known_rows": output_known,
            "output_tokens_unknown_rows": rows - output_known,
            "complete": rows > 0 and cash_known == rows and allowance_known == rows,
        }


def empty_invocation() -> dict[str, Any]:
    """Return the canonical record shape with unknown measurements as None."""
    return {field: None for field in INVOCATION_FIELDS}


class AnalyticsTelemetry:
    """Append-only, interface-compatible analytics backend.

    Start and suppressed records carry the entire canonical schema.  Finish
    events remain deltas so they cannot erase start-time values with ``None``.
    ``read_invocations`` materializes both this format and the interim Lane A
    ``JsonlTelemetry`` format.
    """

    def __init__(self, path: str | Path, *, run_report: str | Path | None = None, stderr=None) -> None:
        self.path = Path(path)
        self.run_report = Path(run_report) if run_report is not None else None
        self._stderr = stderr if stderr is not None else sys.stderr
        self.degraded = False

    def _degrade(self, exc: BaseException) -> None:
        self.degraded = True
        marker = f"{TELEMETRY_DEGRADED}: {type(exc).__name__}: {exc}"
        print(marker, file=self._stderr)
        if self.run_report is not None:
            try:
                self.run_report.parent.mkdir(parents=True, exist_ok=True)
                with self.run_report.open("a", encoding="utf-8") as report:
                    report.write(f"\n{marker}\n")
            except Exception as report_exc:  # noqa: BLE001 - both sinks are fail-open
                print(
                    f"{TELEMETRY_DEGRADED}: run report unavailable: {report_exc}",
                    file=self._stderr,
                )

    def _emit(self, record: dict[str, Any]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, default=str, sort_keys=True) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except Exception as exc:  # noqa: BLE001 - analytics is deliberately fail-open
            self._degrade(exc)

    def start(self, **fields: Any) -> str:
        record = empty_invocation()
        record.update(fields)
        run_id = record.get("run_id") or uuid.uuid4().hex
        record.update(event="start", run_id=run_id)
        if record["started_at"] is None:
            record["started_at"] = time.time()
        self._emit(record)
        return run_id

    def finish(self, run_id: str, **fields: Any) -> None:
        if "completed_at" not in fields:
            fields["completed_at"] = time.time()
        self._emit({"event": "finish", "run_id": run_id, **fields})

    def suppressed(self, **fields: Any) -> None:
        record = empty_invocation()
        record.update(fields)
        record["event"] = "suppressed"
        record["run_id"] = record.get("run_id") or uuid.uuid4().hex
        record["started_at"] = record.get("started_at") or time.time()
        record["completed_at"] = record.get("completed_at") or record["started_at"]
        record["duration_seconds"] = record.get("duration_seconds") or 0.0
        record["result_status"] = record.get("result_status") or "suppressed"
        self._emit(record)

    def crash(self, run_id: str, reason: str) -> None:
        self._emit({
            "event": "crash",
            "run_id": run_id,
            "completed_at": time.time(),
            "result_status": "crashed",
            "crash_reason": reason,
        })

    def backfill_allowance(self, run_id: str, *, pct: float, source: str) -> None:
        """Append a calibrated allowance estimate without rewriting history."""
        if source not in ALLOWANCE_SOURCES:
            raise ValueError(f"invalid allowance source: {source}")
        self._emit({
            "event": "allowance_backfill",
            "run_id": run_id,
            "allowance_pct_estimated": pct,
            "allowance_pct_source": source,
        })


def read_events(path: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Read valid append-only events, retaining diagnostics for torn lines."""
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return events, errors
    except OSError as exc:
        return events, [str(exc)]
    for number, line in enumerate(lines, 1):
        try:
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TypeError("event is not an object")
            events.append(value)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            errors.append(f"line {number}: {exc}")
    return events, errors


def read_invocations(path: str | Path) -> tuple[list[dict[str, Any]], list[str]]:
    """Materialize invocation records from append-only event deltas."""
    events, errors = read_events(path)
    records: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for event in events:
        run_id = event.get("run_id") or uuid.uuid4().hex
        if run_id not in records:
            records[run_id] = empty_invocation()
            records[run_id]["run_id"] = run_id
            order.append(run_id)
        record = records[run_id]
        kind = event.get("event")
        for key, value in event.items():
            if key not in {"event", "crash_reason"}:
                record[key] = value
        if kind == "crash":
            record["result_status"] = "crashed"
            record["crash_reason"] = event.get("crash_reason") or event.get("reason")
            record["incomplete"] = True
        elif kind == "suppressed":
            record["result_status"] = record.get("result_status") or "suppressed"
            record["suppressed"] = True
        elif kind == "finish":
            record["incomplete"] = False
    for record in records.values():
        if (
            record.get("duration_seconds") is None
            and isinstance(record.get("started_at"), (int, float))
            and isinstance(record.get("completed_at"), (int, float))
        ):
            record["duration_seconds"] = max(
                0.0, float(record["completed_at"]) - float(record["started_at"])
            )
        if "incomplete" not in record:
            record["incomplete"] = record.get("completed_at") is None
    return [records[run_id] for run_id in order], errors


def weighted_seconds(records: Iterable[dict[str, Any]], *, role: str, since_ts: float) -> float | None:
    """Return invocation-weighted duration, or None when inputs are incomplete."""
    total = 0.0
    found = False
    for record in records:
        if record.get("role") != role or (record.get("started_at") or 0) <= since_ts:
            continue
        if record.get("result_status") == "suppressed" or record.get("suppressed"):
            continue
        duration = record.get("duration_seconds")
        weight = record.get("invocation_weight")
        if duration is None or weight is None:
            return None
        total += float(duration) * float(weight)
        found = True
    return total if found else 0.0


def _json_documents(payload: str | dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        return [payload]
    text = payload.strip()
    if not text:
        return []
    try:
        whole = json.loads(text)
        if isinstance(whole, dict):
            return [whole]
    except json.JSONDecodeError:
        pass
    documents: list[dict[str, Any]] = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            documents.append(value)
    return documents


def _usage_envelopes(documents: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    found: list[tuple[dict[str, Any], dict[str, Any]]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("usage", "tokenUsage"):
                usage = value.get(key)
                if isinstance(usage, dict):
                    found.append((usage, value))
            for key, child in value.items():
                if key not in {"usage", "tokenUsage"}:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    for document in documents:
        walk(document)
    return found


def provider_usage(
    provider: str, payload: str | dict[str, Any], *, stderr=None
) -> dict[str, int | float | None]:
    """Normalize raw Claude/Codex JSON output for the dispatcher seam.

    Lane A passes the last 200 stdout lines using provider names
    ``anthropic`` and ``openai``.  Dict input and legacy provider aliases are
    retained for direct callers and fixtures.
    """
    sink = stderr if stderr is not None else sys.stderr
    documents = _json_documents(payload)
    envelopes = _usage_envelopes(documents)
    aliases = {
        "anthropic": "anthropic", "claude": "anthropic",
        "openai": "openai", "codex": "openai",
    }
    normalized_provider = aliases.get(provider.lower())
    empty = {
        "cash_usd": None,
        "cash_cost_usd": None,
        "input_tokens": None,
        "output_tokens": None,
        "cached_input_tokens": None,
        "invocation_weight": None,
    }
    if normalized_provider is None or not envelopes:
        if (isinstance(payload, str) and payload.strip()) or documents:
            print(
                f"{TELEMETRY_DEGRADED}: no recognized {provider} usage envelope",
                file=sink,
            )
        return empty

    usage, envelope = envelopes[-1]
    if normalized_provider == "openai":
        cash = usage.get("cash_usd", usage.get("cashCostUsd"))
        result = {
            "cash_usd": cash,
            "cash_cost_usd": cash,
            "input_tokens": usage.get("input_tokens", usage.get("inputTokens")),
            "output_tokens": usage.get("output_tokens", usage.get("outputTokens")),
            "cached_input_tokens": usage.get(
                "cached_input_tokens", usage.get("cachedInputTokens")
            ),
            "invocation_weight": 1.0,
        }
    else:
        cash = envelope.get("total_cost_usd", envelope.get("totalCostUsd"))
        result = {
            "cash_usd": cash,
            "cash_cost_usd": cash,
            "input_tokens": usage.get("input_tokens", usage.get("inputTokens")),
            "output_tokens": usage.get("output_tokens", usage.get("outputTokens")),
            "cached_input_tokens": usage.get(
                "cache_read_input_tokens",
                usage.get("cached_input_tokens", usage.get("cachedInputTokens")),
            ),
            "invocation_weight": 1.0,
        }
    measured = tuple(key for key in result if key != "invocation_weight")
    if usage and all(result[key] is None for key in measured):
        result["invocation_weight"] = None
        keys = ",".join(sorted(str(key) for key in usage))
        print(
            f"{TELEMETRY_DEGRADED}: unexpected {provider} usage schema keys={keys}",
            file=sink,
        )
    return result
