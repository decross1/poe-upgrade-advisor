from __future__ import annotations

from agents.accounting import AccountingBudgetLedger
from agents.run_budget import (
    DistressState,
    RunBudget,
    UnconfiguredRunBudget,
    _day_start,
    _run_started_at,
)


NOW = 1_800_000_000.0


def _policy() -> dict:
    return {
        "per_day_max": {"pm": 2, "backend": 4, "frontend": 2},
        "daily_reset_hour_utc": 4,
        "roles": {
            "pm": {"budget": "claude", "allowance_owner": "pm"},
            "backend": {"budget": "codex", "allowance_owner": "backend"},
            "frontend": {"budget": "codex", "allowance_owner": "backend"},
        },
        "run": {
            "budgets": {
                "frontier_cash": {
                    "total_usd": 50.0, "per_day_usd": 4.2, "per_task_usd": 0.25,
                },
                "claude": {
                    "pct_weekly_per_day": 9.0, "pct_weekly_total": 95.0,
                    "per_task_pct": 1.5,
                },
                "codex": {
                    "pct_weekly_per_day": 11.0, "pct_weekly_total": 120.0,
                    "per_task_pct": 2.0,
                },
            },
            "reserve": {"cash_usd": 8.0, "unlock_after_day": 8},
            "carry_forward_days": 2,
            "allowance_stale_hours": 30,
            "on_daily_cap": "throttle_role",
            "on_total_cap": "disable_role",
            "on_role_disabled": {
                "frontend": {"reassign_to": "backend"},
                "pm": {"promote": "backend"},
            },
        },
    }


def _ledger(tmp_path) -> AccountingBudgetLedger:
    return AccountingBudgetLedger(tmp_path / "budget.sqlite3")


def _reading(ledger, role, pct, ts=NOW - 60):
    ledger.record_allowance(
        role=role, pct=pct, source="manual_daily_reading", weighted_seconds=1.0, ts=ts
    )


def _spend(ledger, *, ts, role, task="TASK-X", cash=None, pct=0.1):
    ledger._x(
        "INSERT INTO spend VALUES (?,?,?,?,?,?,?,?,?)",
        (ts, role, task, f"{role}-{ts}-{task}", cash, pct, None, None, 1),
    )


def test_daily_cap_throttles_and_reassigns_without_halt(tmp_path):
    ledger = _ledger(tmp_path)
    _reading(ledger, "backend", 20.0)
    start = _day_start(NOW, 4)
    _spend(ledger, ts=start + 1, role="frontend")
    _spend(ledger, ts=start + 2, role="frontend")
    budget = RunBudget(_policy(), ledger, now=lambda: NOW)

    verdict = budget.check(role="frontend", task_id="TASK-NEW", tier="green")

    assert not verdict.allowed
    assert "daily invocation cap" in verdict.reason
    assert verdict.degradation_level == 1
    assert verdict.reassign_to == "backend"
    assert not (tmp_path / "HALT").exists()


def test_total_cap_disables_role_before_per_task_cap(tmp_path):
    ledger = _ledger(tmp_path)
    _reading(ledger, "pm", 0.0, ts=NOW - 120)
    _reading(ledger, "pm", 95.0, ts=NOW - 60)
    budget = RunBudget(_policy(), ledger, now=lambda: NOW, run_started_at=NOW - 180)

    verdict = budget.check(role="pm", task_id="TASK-UNUSED", tier="green")

    assert not verdict.allowed
    assert verdict.reason == "claude total cap reached"
    assert "per-task" not in verdict.reason


def test_total_allowance_cap_spans_weekly_reset(tmp_path):
    ledger = _ledger(tmp_path)
    _reading(ledger, "backend", 0.0, ts=NOW - 300)
    _reading(ledger, "backend", 90.0, ts=NOW - 200)
    _reading(ledger, "backend", 30.0, ts=NOW - 100)
    budget = RunBudget(_policy(), ledger, now=lambda: NOW, run_started_at=NOW - 400)
    verdict = budget.check(role="backend", task_id="TASK-NEW", tier="green")
    assert budget._allowance_consumed("backend") == 120.0
    assert not verdict.allowed
    assert verdict.reason == "codex total cap reached"


def test_missing_or_stale_allowance_never_reads_as_headroom(tmp_path):
    ledger = _ledger(tmp_path)
    budget = RunBudget(_policy(), ledger, now=lambda: NOW)
    assert not budget.check(role="pm", task_id="TASK-X", tier="green").allowed
    _reading(ledger, "pm", 10.0, ts=NOW - 31 * 3600)
    verdict = budget.check(role="pm", task_id="TASK-X", tier="green")
    assert not verdict.allowed
    assert "missing or stale" in verdict.reason
    assert verdict.degradation_level == 1


def test_carry_forward_accumulates_but_is_capped_at_two_days(tmp_path):
    ledger = _ledger(tmp_path)
    _reading(ledger, "backend", 30.0)
    day = _day_start(NOW, 4)
    policy = _policy()
    policy["run"]["carry_forward_days"] = 99
    budget = RunBudget(policy, ledger, now=lambda: NOW)
    roles = ("backend", "frontend")
    assert budget._carry_forward(
        roles=roles, field="allowance_pct", base_daily=11.0, day_start=day
    ) == 22.0
    _spend(ledger, ts=day - 86400 + 1, role="backend", pct=6.0)
    assert budget._carry_forward(
        roles=roles, field="allowance_pct", base_daily=11.0, day_start=day
    ) == 16.0


def test_reserve_unlocks_by_day_or_distress(tmp_path):
    ledger = _ledger(tmp_path)
    policy = _policy()
    locked = RunBudget(policy, ledger, now=lambda: NOW, run_started_at=NOW - 6 * 86400)
    assert not locked._reserve_unlocked(NOW)
    day_unlock = RunBudget(policy, ledger, now=lambda: NOW, run_started_at=NOW - 7 * 86400)
    assert day_unlock._reserve_unlocked(NOW)
    red = RunBudget(
        policy, ledger, now=lambda: NOW, run_started_at=NOW,
        distress=DistressState(main_red_hours=6.1),
    )
    dead = RunBudget(
        policy, ledger, now=lambda: NOW, run_started_at=NOW,
        distress=DistressState(dead_letter_count=5),
    )
    assert red._reserve_unlocked(NOW)
    assert dead._reserve_unlocked(NOW)


def test_locked_reserve_blocks_cash_that_distress_can_unlock(tmp_path):
    ledger = _ledger(tmp_path)
    _reading(ledger, "backend", 10.0)
    old = _day_start(NOW, 4) - 3 * 86400
    _spend(ledger, ts=old, role="backend", task="TASK-OLD", cash=42.0, pct=0.1)
    policy = _policy()
    locked = RunBudget(
        policy, ledger, now=lambda: NOW, run_started_at=NOW - 6 * 86400
    ).check(role="backend", task_id="TASK-NEW", tier="red")
    unlocked = RunBudget(
        policy, ledger, now=lambda: NOW, run_started_at=NOW - 6 * 86400,
        distress=DistressState(main_red_hours=6.1),
    ).check(role="backend", task_id="TASK-NEW", tier="red")
    assert not locked.allowed and "cash total cap" in locked.reason
    assert unlocked.allowed


def test_unknown_spend_measurement_refuses_to_certify_headroom(tmp_path):
    ledger = _ledger(tmp_path)
    _reading(ledger, "backend", 10.0)
    ledger._x(
        "INSERT INTO spend VALUES (?,?,?,?,?,?,?,?,?)",
        (NOW - 10, "backend", "TASK-X", "unknown", None, None, None, None, 1),
    )
    verdict = RunBudget(_policy(), ledger, now=lambda: NOW).check(
        role="backend", task_id="TASK-X", tier="green"
    )
    assert not verdict.allowed
    assert "usage unknown" in verdict.reason


def test_unconfigured_loader_state_denies_instead_of_allowing():
    verdict = UnconfiguredRunBudget("missing").check(
        role="pm", task_id="TASK-X", tier="green"
    )
    assert not verdict.allowed
    assert verdict.degradation_level == 1


def test_run_start_is_durable_across_dispatcher_loads(tmp_path):
    ledger = _ledger(tmp_path)
    assert _run_started_at(ledger, run_id="run-a", now=100.0) == 100.0
    assert _run_started_at(ledger, run_id="run-a", now=999.0) == 100.0
    assert _run_started_at(ledger, run_id="run-b", now=999.0) == 999.0
