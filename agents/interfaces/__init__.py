"""Frozen boundary between the two hardening lanes.

This package is the ONLY contract surface shared by
`hardening/lane-a-dispatcher` and `hardening/lane-b-gates`. Lane A codes the
invocation path against these types; Lane B codes the telemetry, budget,
packet and scheduling backends behind them.

Ownership: **pm**. Neither lane edits this package. If a lane needs a change
here, it files a REQUEST in `temp_channel/<lane>_to_pm.md` and waits for a pm
commit. Silently widening this surface re-couples the lanes and is the one
change that can make both branches unmergeable at once.

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
