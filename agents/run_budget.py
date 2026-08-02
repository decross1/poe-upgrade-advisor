"""Fail-closed aggregate run budget and role-throttling policy."""
from __future__ import annotations

import math
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml

from agents.accounting import AccountingBudgetLedger
from agents.interfaces.budget import BudgetLedgerUnavailable
from agents.interfaces.policy import PolicyError, load_policy
from agents.interfaces.run_budget import RunBudgetVerdict

OPERATING_MODES = frozenset({"canary", "supervised", "unattended-7d", "unattended-10d"})
SUPERVISED_MODES = frozenset({"canary", "supervised"})


@dataclass(frozen=True)
class DistressState:
    main_red_hours: float = 0.0
    dead_letter_count: int = 0


class UnconfiguredRunBudget:
    """Safe integration state: missing aggregate policy denies every invoke."""

    def __init__(self, reason: str) -> None:
        self.reason = reason

    def check(self, *, role: str, task_id: str, tier: str) -> RunBudgetVerdict:
        return RunBudgetVerdict(False, self.reason, degradation_level=1)

    def level(self) -> int:
        return 1


def _day_start(timestamp: float, reset_hour: int) -> float:
    now = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    reset = now.replace(hour=reset_hour, minute=0, second=0, microsecond=0)
    if now < reset:
        reset -= timedelta(days=1)
    return reset.timestamp()


class RunBudget:
    """Aggregate allowance/cash ceiling backed by the fail-closed ledger."""

    def __init__(
        self,
        policy: dict[str, Any],
        ledger: AccountingBudgetLedger,
        *,
        now=time.time,
        run_started_at: float | None = None,
        distress: DistressState | None = None,
        operating_mode: str = "unattended-10d",
    ) -> None:
        self.policy = policy
        self.ledger = ledger
        self._now = now
        self.run_started_at = run_started_at if run_started_at is not None else now()
        self.distress = distress or DistressState()
        self.operating_mode = (
            operating_mode if operating_mode in OPERATING_MODES else "unattended-10d"
        )
        self._level = 0

    def level(self) -> int:
        return self._level

    @property
    def run(self) -> dict[str, Any]:
        return self.policy.get("run") or {}

    def _role_config(self, role: str) -> dict[str, Any] | None:
        configured = (self.policy.get("roles") or {}).get(role)
        if configured is not None:
            return configured
        defaults = {
            "pm": {"budget": "claude", "allowance_owner": "pm"},
            "backend": {"budget": "codex", "allowance_owner": "backend"},
            "frontend": {"budget": "codex", "allowance_owner": "backend"},
        }
        return defaults.get(role)

    def _roles_for_budget(self, budget: str) -> tuple[str, ...]:
        known = set(self.policy.get("roles") or {}) | {"pm", "backend", "frontend"}
        return tuple(sorted(
            role for role in known
            if (self._role_config(role) or {}).get("budget") == budget
        ))

    def _latest_allowance(self, owner: str) -> dict[str, Any] | None:
        return self.ledger.latest_allowance(owner)

    def _allowance_consumed(self, owner: str) -> float:
        """Consumption since this run began, spanning provider weekly resets."""
        row = self.ledger._x(
            """SELECT SUM(allowance_delta_pct)
               FROM allowance_calibrations WHERE role=? AND ts>=?""",
            (owner, self.run_started_at),
        ).fetchone()
        return float(row[0] or 0.0)

    def _spend(
        self,
        *,
        roles: tuple[str, ...],
        since: float = 0.0,
        task_id: str | None = None,
        field: str,
        measured_only: bool = False,
    ) -> tuple[int, float | None, int]:
        if field not in {"cash_usd", "allowance_pct"}:
            raise ValueError(f"unsupported spend field: {field}")
        placeholders = ",".join("?" for _ in roles)
        where = [f"role IN ({placeholders})", "ts >= ?"]
        args: list[Any] = [*roles, since]
        if task_id is not None:
            where.append("task_id = ?")
            args.append(task_id)
        if measured_only:
            where.append(f"{field} IS NOT NULL")
        row = self.ledger._x(
            f"""SELECT COUNT(*), SUM({field}),
                       SUM(CASE WHEN {field} IS NULL THEN 1 ELSE 0 END)
                FROM spend WHERE {' AND '.join(where)}""",
            tuple(args),
        ).fetchone()
        return int(row[0]), row[1], int(row[2] or 0)

    def _role_invocations(self, role: str, since: float) -> int:
        row = self.ledger._x(
            "SELECT COUNT(*) FROM spend WHERE role=? AND ts>=?", (role, since)
        ).fetchone()
        return int(row[0])

    def _allowance_stale(self, reading: dict[str, Any] | None, now: float) -> bool:
        if reading is None:
            return True
        max_age = float(self.run.get("allowance_stale_hours", 30)) * 3600
        return now - float(reading["ts"]) > max_age

    def _allowance_diagnostic(
        self, *, owner: str, budget: str, reading: dict[str, Any] | None
    ) -> str:
        state = "missing (no reading has ever been recorded)" if reading is None else "stale"
        command = (
            "python3 scripts/agent_metrics.py record-allowance "
            f"--role {owner} --pct <0-100>"
        )
        return f"{budget} allowance reading {state}; record one with: {command}"

    def _missing_allowance_blocks(self) -> bool:
        return self.operating_mode not in SUPERVISED_MODES

    def _carry_forward(
        self,
        *,
        roles: tuple[str, ...],
        field: str,
        base_daily: float,
        day_start: float,
    ) -> float:
        carry_days = min(2, max(0, int(self.run.get("carry_forward_days", 0))))
        carry = 0.0
        for days_ago in range(1, carry_days + 1):
            start = day_start - days_ago * 86400
            end = start + 86400
            placeholders = ",".join("?" for _ in roles)
            row = self.ledger._x(
                f"""SELECT SUM({field}), SUM(CASE WHEN {field} IS NULL THEN 1 ELSE 0 END)
                    FROM spend WHERE role IN ({placeholders}) AND ts>=? AND ts<?""",
                (*roles, start, end),
            ).fetchone()
            if int(row[1] or 0):
                continue
            used = float(row[0] or 0.0)
            carry += max(0.0, base_daily - used)
        return min(carry, base_daily * 2)

    def _reserve_unlocked(self, now: float) -> bool:
        reserve = self.run.get("reserve") or {}
        day = math.floor(max(0.0, now - self.run_started_at) / 86400) + 1
        if day >= int(reserve.get("unlock_after_day", 10**9)):
            return True
        return self.distress.main_red_hours > 6 or self.distress.dead_letter_count > 4

    def _reassignment(self, role: str, now: float) -> str | None:
        action = (self.run.get("on_role_disabled") or {}).get(role) or {}
        target = action.get("reassign_to") or action.get("promote")
        if not isinstance(target, str) or target == role:
            return None
        config = self._role_config(target)
        if config is None:
            return None
        day_start = _day_start(now, int(self.policy.get("daily_reset_hour_utc", 4)))
        daily_max = (self.policy.get("per_day_max") or {}).get(target)
        if daily_max is not None and self._role_invocations(target, day_start) >= int(daily_max):
            return None
        budget = str(config.get("budget"))
        if budget in {"claude", "codex"}:
            reading = self._latest_allowance(str(config.get("allowance_owner", target)))
            cap = ((self.run.get("budgets") or {}).get(budget) or {}).get("pct_weekly_total")
            if (self._allowance_stale(reading, now) and self._missing_allowance_blocks()) or (
                reading is not None
                and cap is not None
                and float(reading["pct"]) >= float(cap)
            ):
                return None
        return target

    def _verdict(
        self,
        *,
        allowed: bool,
        reason: str,
        level: int,
        role: str,
        task_id: str,
        reassign_to: str | None = None,
    ) -> RunBudgetVerdict:
        self._level = level
        self.ledger.record_decision(
            role=role,
            task_id=task_id,
            decision="allow" if allowed else "deny",
            reason=reason,
        )
        return RunBudgetVerdict(allowed, reason, level, reassign_to)

    def check(self, *, role: str, task_id: str, tier: str) -> RunBudgetVerdict:
        now = float(self._now())
        config = self._role_config(role)
        if config is None:
            return self._verdict(
                allowed=False, reason=f"unknown role: {role}", level=1,
                role=role, task_id=task_id,
            )
        reset_hour = int(self.policy.get("daily_reset_hour_utc", 4))
        day_start = _day_start(now, reset_hour)
        budget_name = str(config.get("budget"))
        budget = ((self.run.get("budgets") or {}).get(budget_name) or {})
        roles = self._roles_for_budget(budget_name)
        allowance_warning: str | None = None

        if budget_name in {"claude", "codex"}:
            owner = str(config.get("allowance_owner", role))
            reading = self._latest_allowance(owner)
            if self._allowance_stale(reading, now):
                diagnostic = self._allowance_diagnostic(
                    owner=owner, budget=budget_name, reading=reading
                )
                if self._missing_allowance_blocks():
                    return self._verdict(
                        allowed=False,
                        reason=f"unattended mode denies invocation: {diagnostic}",
                        level=1, role=role, task_id=task_id,
                        reassign_to=self._reassignment(role, now),
                    )
                allowance_warning = (
                    f"WARNING ({self.operating_mode} allows bounded invocation): "
                    f"{diagnostic}"
                )
            total_cap = float(budget["pct_weekly_total"])
            if self._allowance_consumed(owner) >= total_cap:
                return self._verdict(
                    allowed=False,
                    reason=f"{budget_name} total cap reached",
                    level=4 if role == "pm" else 3,
                    role=role, task_id=task_id,
                    reassign_to=self._reassignment(role, now),
                )
            task_cap = float(budget["per_task_pct"])
            _, task_used, task_unknown = self._spend(
                roles=roles, task_id=task_id, field="allowance_pct"
            )
            if task_unknown:
                return self._verdict(
                    allowed=False, reason="task allowance usage unknown", level=1,
                    role=role, task_id=task_id,
                )
            if float(task_used or 0.0) >= task_cap:
                return self._verdict(
                    allowed=False, reason=f"{budget_name} per-task cap reached", level=1,
                    role=role, task_id=task_id,
                )
            daily_base = float(budget["pct_weekly_per_day"])
            daily_limit = daily_base + self._carry_forward(
                roles=roles, field="allowance_pct", base_daily=daily_base,
                day_start=day_start,
            )
            _, daily_used, daily_unknown = self._spend(
                roles=roles, since=day_start, field="allowance_pct"
            )
            if daily_unknown:
                return self._verdict(
                    allowed=False, reason="daily allowance usage unknown", level=1,
                    role=role, task_id=task_id,
                    reassign_to=self._reassignment(role, now),
                )
            if float(daily_used or 0.0) >= daily_limit:
                return self._verdict(
                    allowed=False, reason=f"{budget_name} daily cap; throttle role",
                    level=1, role=role, task_id=task_id,
                    reassign_to=self._reassignment(role, now),
                )

        if tier in {"red", "frontier", "frontier_cash"}:
            cash = ((self.run.get("budgets") or {}).get("frontier_cash") or {})
            cash_roles = tuple(sorted((self.policy.get("per_day_max") or {}).keys()))
            _, total_used, total_unknown = self._spend(
                roles=cash_roles, field="cash_usd"
            )
            if total_unknown:
                return self._verdict(
                    allowed=False, reason="frontier cash total usage unknown", level=1,
                    role=role, task_id=task_id,
                )
            total = float(cash["total_usd"])
            reserve = float((self.run.get("reserve") or {}).get("cash_usd", 0.0))
            effective_total = total if self._reserve_unlocked(now) else total - reserve
            if float(total_used or 0.0) >= effective_total:
                return self._verdict(
                    allowed=False, reason="frontier cash total cap reached", level=3,
                    role=role, task_id=task_id,
                )
            _, task_cash, task_cash_unknown = self._spend(
                roles=cash_roles, task_id=task_id, field="cash_usd"
            )
            if task_cash_unknown:
                return self._verdict(
                    allowed=False, reason="frontier cash task usage unknown", level=1,
                    role=role, task_id=task_id,
                )
            if float(task_cash or 0.0) >= float(cash["per_task_usd"]):
                return self._verdict(
                    allowed=False, reason="frontier cash per-task cap reached", level=3,
                    role=role, task_id=task_id,
                )
            daily_base = float(cash["per_day_usd"])
            daily_limit = daily_base + self._carry_forward(
                roles=cash_roles, field="cash_usd", base_daily=daily_base,
                day_start=day_start,
            )
            _, daily_cash, daily_cash_unknown = self._spend(
                roles=cash_roles, since=day_start, field="cash_usd"
            )
            if daily_cash_unknown:
                return self._verdict(
                    allowed=False, reason="frontier cash daily usage unknown", level=1,
                    role=role, task_id=task_id,
                )
            if float(daily_cash or 0.0) >= daily_limit:
                return self._verdict(
                    allowed=False, reason="frontier cash daily cap; throttle role", level=1,
                    role=role, task_id=task_id,
                    reassign_to=self._reassignment(role, now),
                )

        daily_max = (self.policy.get("per_day_max") or {}).get(role)
        if daily_max is None:
            return self._verdict(
                allowed=False, reason=f"no daily cap for role: {role}", level=1,
                role=role, task_id=task_id,
            )
        if self._role_invocations(role, day_start) >= int(daily_max):
            return self._verdict(
                allowed=False, reason="daily invocation cap; throttle role", level=1,
                role=role, task_id=task_id,
                reassign_to=self._reassignment(role, now),
            )
        return self._verdict(
            allowed=True,
            reason=(
                f"{allowance_warning}; within run budget"
                if allowance_warning else "within run budget"
            ),
            level=0,
            role=role, task_id=task_id,
        )


def _find_project_root(start: Path) -> Path:
    for ancestor in (start, *start.parents):
        if (ancestor / "agents/governor").is_dir() and (ancestor / "mailroom").is_dir():
            return ancestor
        if (ancestor / "worktrees").is_dir() and (ancestor / "mailroom").is_dir():
            return ancestor
    return start


def _run_started_at(
    ledger: AccountingBudgetLedger, *, run_id: str, now: float
) -> float:
    """Persist run identity in the fail-closed store across dispatcher loads."""
    ledger._x(
        """CREATE TABLE IF NOT EXISTS run_state (
             run_id TEXT PRIMARY KEY, started_at REAL NOT NULL, status TEXT NOT NULL)"""
    )
    ledger._x(
        "INSERT OR IGNORE INTO run_state VALUES (?,?,?)",
        (run_id, now, "active"),
    )
    row = ledger._x(
        "SELECT started_at FROM run_state WHERE run_id=?", (run_id,)
    ).fetchone()
    if row is None:
        raise sqlite3.DatabaseError(f"run state missing after insert: {run_id}")
    return float(row[0])


def _operating_mode(mailroom: Path) -> str:
    """Read the operator-selected readiness mode, defaulting safely unattended."""
    path = mailroom / "readiness.yaml"
    try:
        state = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return "unattended-10d"
    if not isinstance(state, dict):
        return "unattended-10d"
    mode = state.get("operating_mode")
    return str(mode) if mode in OPERATING_MODES else "unattended-10d"


def load() -> RunBudget | UnconfiguredRunBudget:
    """Load the production port; missing policy is a denial, never unbounded."""
    code_root = Path(__file__).resolve().parents[1]
    project = _find_project_root(code_root)
    policy_path = code_root / "agents/governor/run_policy.yaml"
    if not policy_path.is_file():
        return UnconfiguredRunBudget("run policy absent; aggregate headroom unproven")
    try:
        # Parse once here for a focused error, then use the frozen merge loader
        # so Lane A daily caps and Lane B aggregate policy remain one contract.
        yaml.safe_load(policy_path.read_text(encoding="utf-8"))
        policy = load_policy(code_root / "agents/governor")
    except (OSError, yaml.YAMLError, PolicyError) as exc:
        return UnconfiguredRunBudget(f"run policy unreadable: {exc}")
    mailroom = project / "mailroom"
    try:
        ledger = AccountingBudgetLedger(mailroom / "governor/budget_ledger.sqlite3")
        run_id = str((policy.get("run") or {}).get("id") or "")
        if not run_id:
            return UnconfiguredRunBudget("run policy has no run.id")
        started_at = _run_started_at(ledger, run_id=run_id, now=time.time())
    except BudgetLedgerUnavailable as exc:
        return UnconfiguredRunBudget(f"budget ledger unavailable: {exc}")
    return RunBudget(
        policy,
        ledger,
        run_started_at=started_at,
        operating_mode=_operating_mode(mailroom),
    )
