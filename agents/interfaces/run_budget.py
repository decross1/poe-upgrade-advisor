"""Run-level budget port — the aggregate circuit breaker.

Per-task budgets are primary; run budgets are secondary but not optional. A
task-level ceiling cannot stop a run from spending its entire ten-day
allowance in three days, which is exactly the observed pattern: $150 of
credits exhausted by day 3, forcing an emergency model switch mid-run.

Direction: **Lane B implements, Lane A calls.** The dispatcher consults this
after the governor and before incrementing the attempt ledger.

Degradation, not halting. Every halt is an intervention event, and an
unattended run is defined by the absence of interventions. The ladder throttles
a role, reassigns its queue to a role with spare capacity, reduces parallelism,
restricts to the critical path, drains, and only then halts — writing a run
report rather than stopping silently.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RunBudgetVerdict:
    """Answer to "may this role spend right now, and at what posture?"."""

    allowed: bool
    reason: str
    #: 0 nominal · 1 route throttled · 2 low-cost tier gone · 3 frontier
    #: constrained · 4 judgment constrained · 5 drain · 6 halt
    degradation_level: int = 0
    #: Role to hand this task to instead, when the owner is throttled but the
    #: work is still affordable elsewhere. `None` means "queue it for later".
    reassign_to: str | None = None


@runtime_checkable
class RunBudgetPort(Protocol):
    def check(self, *, role: str, task_id: str, tier: str) -> RunBudgetVerdict:
        """Aggregate daily/run/reserve check for one prospective invocation."""

    def level(self) -> int:
        """Current degradation level, 0-6."""


class AlwaysAllow:
    """Default until Lane B lands `agents/run_budget.py`.

    Deliberately noisy: an unattended run with no aggregate ceiling has no
    ceiling at all, so this must never be mistaken for a configured budget.
    `check_agent_readiness.py --mode unattended-7d` MUST fail while this is the
    active implementation.
    """

    MARKER = "RUN-BUDGET-ABSENT"

    def __init__(self, warn=None) -> None:
        self._warned = False
        self._warn = warn

    def check(self, *, role: str, task_id: str, tier: str) -> RunBudgetVerdict:
        if not self._warned:
            self._warned = True
            msg = (f"{self.MARKER}: no run budget configured; "
                   f"aggregate spend is unbounded. Canary/supervised only.")
            if self._warn is not None:
                self._warn(msg)
            else:
                import sys
                print(msg, file=sys.stderr)
        return RunBudgetVerdict(True, self.MARKER, degradation_level=0)

    def level(self) -> int:
        return 0
