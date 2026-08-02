"""Boundary between the two hardening lanes.

This package is the ONLY contract surface shared by
`hardening/lane-a-dispatcher` and `hardening/lane-b-gates`. Lane A codes the
invocation path against these types; Lane B codes the telemetry, budget,
packet and scheduling backends behind them.

Ownership: per-file, ruled by pm 2026-08-02 (critical-closure program). The
previous blanket freeze ("neither lane edits this package") is LIFTED — it made
this the least-owned, least-reliable surface in the repo; three defects
accumulated here precisely because nobody owned it.

    states.py, result.py, schemas/result.schema.json   -> Lane A
    telemetry.py, budget.py, run_budget.py, policy.py,
    packet.py, schemas/task_packet.schema.json         -> Lane B
    __init__.py (this file, re-exports)                -> pm

The non-owning lane files a REQUEST in `temp_channel/<lane>_to_pm.md` for
changes it needs across the seam; the owning lane appends a HANDOFF to the
other lane's inbound file when it changes a surface the other imports.

Design rules that must survive any future edit:

1. Ports are Protocols, not base classes — a lane may not inherit behaviour
   across the seam.
2. Every port ships a working default here, so neither lane is ever blocked on
   the other landing first.
3. The budget port is **fail-closed** (cannot write -> do not invoke); the
   telemetry port is **fail-open** (cannot write -> degrade loudly, keep
   working). A full disk must not halt a 10-day unattended run, and an
   unrecorded spend must not be allowed to happen. HANDOFF section 3.5.
"""

from .states import AckDecision, DispatchDecision, TaskState
from .result import RESULT_SCHEMA_PATH, ResultError, load_result, validate_result
from .packet import PACKET_SCHEMA_PATH, PacketError, load_packet, validate_packet
from .telemetry import JsonlTelemetry, NullTelemetry, TelemetryPort, TELEMETRY_DEGRADED
from .budget import BudgetLedgerPort, BudgetLedgerUnavailable, SqliteBudgetLedger
from .run_budget import AlwaysAllow, RunBudgetPort, RunBudgetVerdict
from .policy import load_policy, resolve_budgets

__all__ = [
    "AckDecision",
    "DispatchDecision",
    "TaskState",
    "RESULT_SCHEMA_PATH",
    "ResultError",
    "load_result",
    "validate_result",
    "PACKET_SCHEMA_PATH",
    "PacketError",
    "load_packet",
    "validate_packet",
    "JsonlTelemetry",
    "NullTelemetry",
    "TelemetryPort",
    "TELEMETRY_DEGRADED",
    "BudgetLedgerPort",
    "BudgetLedgerUnavailable",
    "SqliteBudgetLedger",
    "AlwaysAllow",
    "RunBudgetPort",
    "RunBudgetVerdict",
    "load_policy",
    "resolve_budgets",
]
