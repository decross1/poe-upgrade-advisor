"""Task, dispatch, and acknowledgment states.

These enums are the vocabulary both lanes use in telemetry, ledgers and logs.
String values are persisted, so they are API: renaming one is a schema change.
"""
from __future__ import annotations

from enum import Enum


class TaskState(str, Enum):
    """Durable, idempotent task lifecycle (restart program, Part II)."""

    QUEUED = "queued"
    PREFLIGHT = "preflight"
    BLOCKED_NO_MODEL = "blocked_no_model"
    DETERMINISTIC_EXECUTION = "deterministic_execution"
    EXECUTING = "executing"
    VALIDATING = "validating"
    NO_PROGRESS = "no_progress"
    NARROWING = "narrowing"
    ESCALATING = "escalating"
    REVIEWING = "reviewing"
    READY_TO_MERGE = "ready_to_merge"
    COMPLETED = "completed"
    DEAD_LETTERED = "dead_lettered"
    TERMINATED = "terminated"
    RECOVERY_REQUIRED = "recovery_required"


class DispatchDecision(str, Enum):
    """What the dispatcher decided to do with one ledger message."""

    INVOKE = "invoke"
    SUPPRESSED_PREFLIGHT = "suppressed_preflight"
    SUPPRESSED_GOVERNOR = "suppressed_governor"
    SUPPRESSED_HALT = "suppressed_halt"
    SUPPRESSED_UNCHANGED_BLOCKER = "suppressed_unchanged_blocker"
    DEAD_LETTERED_ATTEMPTS = "dead_lettered_attempts"
    CIRCUIT_BROKEN = "circuit_broken"


#: Decisions that must be counted as "a poll happened and cost zero model tokens".
#: The Wave 1 exit criterion "zero model calls on an empty inbox / unchanged
#: blocker" is measured as: every non-INVOKE decision is recorded.
SUPPRESSED_DECISIONS = frozenset(
    d for d in DispatchDecision if d is not DispatchDecision.INVOKE
)


class AckDecision(str, Enum):
    """Whether the ledger message may be retired.

    The ack decision is made by the DISPATCHER and must never depend on the
    agent being functional — that is the correction that fixes the ~50-burned-
    invocation incident (HANDOFF section 2.3). An agent that cannot execute
    Bash cannot write a result, cannot write a blocked state, and cannot ack;
    only a dispatcher-side attempt cap can retire its message.
    """

    ACK = "ack"
    ACK_DEAD_LETTER = "ack_dead_letter"
    RETAIN = "retain"
