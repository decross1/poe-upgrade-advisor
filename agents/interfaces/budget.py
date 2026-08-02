"""Budget ledger port — **fail-closed**.

If spend cannot be recorded, spend does not happen. An unattended run that
keeps invoking while its ledger is unwritable has no ceiling at all, which is
exactly how $150 of credits disappeared with nothing to read afterwards.

Contrast `telemetry.py`, which is fail-open. HANDOFF section 3.5.
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any, Protocol, runtime_checkable


class BudgetLedgerUnavailable(RuntimeError):
    """The ledger cannot be read or written. Callers MUST NOT invoke a model."""


@runtime_checkable
class BudgetLedgerPort(Protocol):
    """Durable spend and attempt accounting.

    Every method raises `BudgetLedgerUnavailable` rather than degrading. The
    dispatcher treats that exception as "do not invoke".
    """

    def attempts(self, message_id: str) -> int:
        """Attempts already made for this ledger message."""

    def increment_attempt(self, message_id: str, task_id: str, role: str) -> int:
        """Record that an attempt is ABOUT to start. Returns the new count.

        Must be called *before* invoking. Counting after the fact cannot bound
        an agent that never returns a result — the failure mode this exists
        for.
        """

    def record_spend(
        self,
        *,
        role: str,
        task_id: str,
        run_id: str,
        cash_usd: float | None = None,
        allowance_pct: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        success: bool = False,
    ) -> None:
        """Durably record one invocation's cost."""

    def spend_since(self, *, since_ts: float, role: str | None = None) -> dict[str, Any]:
        """Aggregate spend, for daily/run caps and the degradation ladder."""


class SqliteBudgetLedger:
    """Default fail-closed backend on the existing governor SQLite file.

    Interim implementation so Lane A is never blocked; Lane B extends it with
    run-level and allowance accounting behind the same Protocol.
    """

    _SCHEMA = (
        """CREATE TABLE IF NOT EXISTS attempts (
             message_id TEXT PRIMARY KEY, task_id TEXT, role TEXT,
             n INTEGER NOT NULL DEFAULT 0, first_ts REAL, last_ts REAL)""",
        """CREATE TABLE IF NOT EXISTS spend (
             ts REAL, role TEXT, task_id TEXT, run_id TEXT,
             cash_usd REAL, allowance_pct REAL,
             input_tokens INTEGER, output_tokens INTEGER, success INTEGER)""",
    )

    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only
        try:
            if read_only:
                if not self.path.is_file():
                    raise BudgetLedgerUnavailable(
                        f"read-only budget ledger absent: {self.path}"
                    )
                uri = f"{self.path.resolve().as_uri()}?mode=ro&immutable=1"
                self.db = sqlite3.connect(uri, uri=True, isolation_level=None)
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(self.path, isolation_level=None)
            self.db.execute("PRAGMA journal_mode=WAL")
            for stmt in self._SCHEMA:
                self.db.execute(stmt)
        except (sqlite3.Error, OSError) as e:
            raise BudgetLedgerUnavailable(f"cannot open budget ledger {self.path}: {e}") from e

    def _x(self, sql: str, args: tuple = ()):
        try:
            return self.db.execute(sql, args)
        except sqlite3.Error as e:
            raise BudgetLedgerUnavailable(f"budget ledger write failed: {e}") from e

    def attempts(self, message_id: str) -> int:
        row = self._x("SELECT n FROM attempts WHERE message_id=?", (message_id,)).fetchone()
        return row[0] if row else 0

    def increment_attempt(self, message_id: str, task_id: str, role: str) -> int:
        if self.read_only:
            raise BudgetLedgerUnavailable("read-only budget ledger cannot increment attempts")
        now = time.time()
        self._x(
            """INSERT INTO attempts (message_id, task_id, role, n, first_ts, last_ts)
               VALUES (?,?,?,1,?,?)
               ON CONFLICT(message_id) DO UPDATE SET n = n + 1, last_ts = excluded.last_ts""",
            (message_id, task_id, role, now, now),
        )
        return self.attempts(message_id)

    def record_spend(
        self,
        *,
        role: str,
        task_id: str,
        run_id: str,
        cash_usd: float | None = None,
        allowance_pct: float | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        success: bool = False,
    ) -> None:
        if self.read_only:
            raise BudgetLedgerUnavailable("read-only budget ledger cannot record spend")
        self._x(
            "INSERT INTO spend VALUES (?,?,?,?,?,?,?,?,?)",
            (time.time(), role, task_id, run_id, cash_usd, allowance_pct,
             input_tokens, output_tokens, int(success)),
        )

    def spend_since(self, *, since_ts: float, role: str | None = None) -> dict[str, Any]:
        """Aggregate spend, keeping *unknown* distinct from *zero*.

        `SUM()` over an all-NULL column is NULL, and wrapping it in
        `COALESCE(..., 0)` reports "we spent nothing" for "we do not know what
        we spent". That is the single failure this whole accounting layer
        exists to prevent, so it is not done here.

        Returns `cash_usd`/`allowance_pct` as the sum of the values that ARE
        known, or `None` when none is, plus a count of rows contributing no
        figure. A caller that cannot tolerate unknowns must check
        `*_unknown_rows` and refuse to certify headroom rather than treating
        the sum as complete.
        """
        sql = ("SELECT COUNT(*), SUM(cash_usd), SUM(allowance_pct), "
               "       SUM(cash_usd IS NULL), SUM(allowance_pct IS NULL) "
               "FROM spend WHERE ts >= ?")
        args: tuple = (since_ts,)
        if role is not None:
            sql += " AND role = ?"
            args += (role,)
        n, cash, pct, cash_unknown, pct_unknown = self._x(sql, args).fetchone()
        return {
            "invocations": n,
            "cash_usd": cash,
            "allowance_pct": pct,
            "cash_usd_unknown_rows": cash_unknown or 0,
            "allowance_pct_unknown_rows": pct_unknown or 0,
            "complete": n > 0 and not (cash_unknown or 0) and not (pct_unknown or 0),
        }
