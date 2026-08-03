from __future__ import annotations

from agents.accounting import AccountingBudgetLedger
from agents.run_budget import (
    DistressState,
    RunBudget,
    UnconfiguredRunBudget,
    _day_start,
    _operating_mode,
    _run_started_at,
    load,
)

NOW = 1_800_000_000.0


def test_read_only_loader_refuses_implicit_live_mailroom_resolution(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("read-only loader must not discover the live mailroom")

    monkeypatch.setattr("agents.run_budget._find_project_root", forbidden)
    budget = load(read_only=True)
    assert isinstance(budget, UnconfiguredRunBudget)
    assert "explicit mailroom" in budget.reason


def test_read_only_loader_and_check_leave_explicit_ledger_unchanged(tmp_path):
    mailroom = tmp_path / "mailroom"
    (mailroom / "governor").mkdir(parents=True)
    (mailroom / "readiness.yaml").write_text("operating_mode: canary\n")
    writable = load(mailroom=mailroom)
    assert isinstance(writable, RunBudget)
    writable.ledger.db.close()
    ledger_path = mailroom / "governor/budget_ledger.sqlite3"
    before = (
        ledger_path.stat().st_size,
        ledger_path.stat().st_mtime_ns,
        ledger_path.read_bytes(),
    )

    read_only = load(read_only=True, mailroom=mailroom)
    assert isinstance(read_only, RunBudget)
    read_only.check(role="pm", task_id="TASK-X", tier="green")
    read_only.ledger.db.close()

    assert (
        ledger_path.stat().st_size,
        ledger_path.stat().st_mtime_ns,
        ledger_path.read_bytes(),
    ) == before


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


def test_missing_or_stale_allowance_denies_unattended_with_actionable_reason(tmp_path):
    ledger = _ledger(tmp_path)
    budget = RunBudget(
        _policy(), ledger, now=lambda: NOW, operating_mode="unattended-7d"
    )
    missing = budget.check(role="pm", task_id="TASK-X", tier="green")
    assert not missing.allowed
    assert "no reading has ever been recorded" in missing.reason
    assert "scripts/agent_metrics.py record-allowance --role pm" in missing.reason
    _reading(ledger, "pm", 10.0, ts=NOW - 31 * 3600)
    verdict = budget.check(role="pm", task_id="TASK-X", tier="green")
    assert not verdict.allowed
    assert "reading stale" in verdict.reason
    assert verdict.degradation_level == 1


def test_missing_allowance_warns_and_allows_bounded_supervised_modes(tmp_path):
    for mode in ("canary", "supervised"):
        ledger = _ledger(tmp_path / mode)
        verdict = RunBudget(
            _policy(), ledger, now=lambda: NOW, operating_mode=mode
        ).check(role="pm", task_id="TASK-X", tier="green")
        assert verdict.allowed
        assert f"WARNING ({mode} allows bounded invocation)" in verdict.reason
        assert "no reading has ever been recorded" in verdict.reason
        assert "record-allowance --role pm --pct <0-100>" in verdict.reason


def test_stale_allowance_warns_and_allows_supervised_mode(tmp_path):
    ledger = _ledger(tmp_path)
    _reading(ledger, "backend", 10.0, ts=NOW - 31 * 3600)
    verdict = RunBudget(
        _policy(), ledger, now=lambda: NOW, operating_mode="supervised"
    ).check(role="backend", task_id="TASK-X", tier="green")
    assert verdict.allowed
    assert "WARNING (supervised allows bounded invocation)" in verdict.reason
    assert "codex allowance reading stale" in verdict.reason
    assert "record-allowance --role backend --pct <0-100>" in verdict.reason


def test_supervised_allowance_warning_does_not_bypass_other_caps(tmp_path):
    ledger = _ledger(tmp_path)
    day = _day_start(NOW, 4)
    _spend(ledger, ts=day + 1, role="pm", pct=0.1)
    _spend(ledger, ts=day + 2, role="pm", pct=0.1)
    verdict = RunBudget(
        _policy(), ledger, now=lambda: NOW, operating_mode="canary"
    ).check(role="pm", task_id="TASK-X", tier="green")
    assert not verdict.allowed
    assert verdict.reason == "daily invocation cap; throttle role"


def test_operating_mode_reads_readiness_state_and_defaults_unattended(tmp_path):
    assert _operating_mode(tmp_path) == "unattended-10d"
    (tmp_path / "readiness.yaml").write_text("operating_mode: canary\n")
    assert _operating_mode(tmp_path) == "canary"
    (tmp_path / "readiness.yaml").write_text("operating_mode: typo\n")
    assert _operating_mode(tmp_path) == "unattended-10d"


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


def test_unknown_frontier_cash_refuses_to_certify_total_headroom(tmp_path):
    """L-16 + operator ruling 2026-08-03 ("only monitor real token spend for
    kimi; use the provider's return messages as the exhaustion signal").

    Unknown frontier cash is the same class of ignorance as a missing
    allowance reading, and now takes the same mode-aware path: unattended
    DENIES, canary/supervised warn and allow bounded invocation. It had been
    the only one of the four unknown-spend branches still hard-denying, and
    it blocked every red-tier task in the mission — both parked-PR replays
    are red. KNOWN spend over a cap still denies in every mode (pinned by
    test_frontier_cash_total_cap_still_denies_when_known below)."""
    ledger = _ledger(tmp_path)
    _reading(ledger, "backend", 10.0)
    _spend(
        ledger,
        ts=NOW - 10,
        role="backend",
        task="TASK-OTHER",
        cash=None,
        pct=0.1,
    )
    denied = RunBudget(
        _policy(), ledger, now=lambda: NOW, operating_mode="unattended-7d"
    ).check(role="backend", task_id="TASK-NEW", tier="red")
    assert not denied.allowed
    assert "frontier cash total usage unknown" in denied.reason

    allowed = RunBudget(
        _policy(), ledger, now=lambda: NOW, operating_mode="canary"
    ).check(role="backend", task_id="TASK-NEW", tier="red")
    assert allowed.allowed
    assert "frontier cash" in allowed.reason and "unknown" in allowed.reason


def test_frontier_cash_total_cap_still_denies_when_known(tmp_path):
    """The L-16 relaxation must not weaken a cap: MEASURED cash over the
    frontier total denies in canary too."""
    policy = _kimi_policy()  # frontend on kimi => a cash-denominated role
    ledger = _ledger(tmp_path)
    _spend(ledger, ts=NOW - 86400 * 3, role="frontend", task="TASK-A",
           cash=60.0, pct=None)
    verdict = RunBudget(
        policy, ledger, now=lambda: NOW, operating_mode="canary"
    ).check(role="frontend", task_id="TASK-B", tier="red")
    assert not verdict.allowed
    assert "cap" in verdict.reason


def test_subscription_spend_does_not_consume_the_frontier_pool(tmp_path):
    """L-16's core point. pm's claude cash_usd is a subscription EQUIVALENT
    the CLI reports, not metered dollars. Summing it into frontier_cash blew
    the $4.20/day cap in the first hour of live operation and hard-blocked
    every red-tier mission task. Only cash-denominated roles count."""
    policy = _kimi_policy()
    ledger = _ledger(tmp_path)
    start = _day_start(NOW, 4)
    _spend(ledger, ts=start + 1, role="pm", task="ORG", cash=30.28, pct=None)
    verdict = RunBudget(
        policy, ledger, now=lambda: NOW, operating_mode="canary"
    ).check(role="frontend", task_id="TASK-NEW", tier="red")
    assert verdict.allowed, (
        "pm's subscription-equivalent spend must not consume frontier cash: "
        f"{verdict.reason}"
    )


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


# --- L-1: unknown allowance_pct is mode-aware everywhere ------------------


def test_unknown_task_allowance_is_mode_aware(tmp_path):
    """2026-08-03 orchestrator ruling. A NULL allowance_pct on a prior spend
    row is the same ignorance the missing-reading branch already treats
    mode-aware (W2-3). Denying it unconditionally gave every task exactly one
    invocation and then a permanent stall — observed live on TASK-999-S1."""
    ledger = _ledger(tmp_path)
    _reading(ledger, "backend", 20.0)
    _spend(ledger, ts=NOW - 60, role="backend", task="TASK-A", cash=None, pct=None)

    allowed = RunBudget(
        _policy(), ledger, now=lambda: NOW, operating_mode="canary"
    ).check(role="backend", task_id="TASK-A", tier="green")
    assert allowed.allowed
    # The same NULL row trips both the per-task and daily branches; the later
    # warning supersedes the earlier one in `reason` (they are one class).
    assert "allowance usage unknown" in allowed.reason

    denied = RunBudget(
        _policy(), ledger, now=lambda: NOW, operating_mode="unattended-7d"
    ).check(role="backend", task_id="TASK-A", tier="green")
    assert not denied.allowed
    assert "task allowance usage unknown" in denied.reason  # per-task fires first


def test_known_allowance_over_cap_still_denies_in_canary(tmp_path):
    """The L-1 relaxation must not weaken a cap: KNOWN spend over the
    per-task cap denies in every mode, canary included."""
    ledger = _ledger(tmp_path)
    _reading(ledger, "backend", 20.0)
    _spend(ledger, ts=NOW - 60, role="backend", task="TASK-A", cash=None, pct=99.0)
    verdict = RunBudget(
        _policy(), ledger, now=lambda: NOW, operating_mode="canary"
    ).check(role="backend", task_id="TASK-A", tier="green")
    assert not verdict.allowed
    assert "per-task cap reached" in verdict.reason


# --- kimi cash wall (2026-08-03 operator ruling: frontend on kimi) --------


def _kimi_policy() -> dict:
    p = _policy()
    p["roles"]["frontend"] = {"budget": "kimi", "allowance_owner": "frontend"}
    p["run"]["budgets"]["kimi"] = {
        "total_usd": 50.0, "per_day_usd": 10.0, "per_task_usd": 1.5,
    }
    return p


def test_kimi_total_cap_denies_frontend_tier_independent(tmp_path):
    """The $50 wall holds for GREEN work — unlike frontier_cash, the kimi
    budget is role-keyed, not tier-keyed."""
    ledger = _ledger(tmp_path)
    _spend(ledger, ts=NOW - 3 * 86400, role="frontend", task="TASK-A", cash=30.0, pct=None)
    _spend(ledger, ts=NOW - 3 * 86400 + 1, role="frontend", task="TASK-B", cash=20.0, pct=None)
    verdict = RunBudget(
        _kimi_policy(), ledger, now=lambda: NOW, operating_mode="canary"
    ).check(role="frontend", task_id="TASK-C", tier="green")
    assert not verdict.allowed
    assert "kimi cash total cap" in verdict.reason


def test_kimi_per_task_cap_denies(tmp_path):
    ledger = _ledger(tmp_path)
    _spend(ledger, ts=NOW - 60, role="frontend", task="TASK-A", cash=1.5, pct=None)
    verdict = RunBudget(
        _kimi_policy(), ledger, now=lambda: NOW, operating_mode="canary"
    ).check(role="frontend", task_id="TASK-A", tier="green")
    assert not verdict.allowed
    assert "kimi cash per-task cap" in verdict.reason


def test_kimi_daily_cap_throttles(tmp_path):
    ledger = _ledger(tmp_path)
    start = _day_start(NOW, 4)
    for i, task in enumerate(("TASK-A", "TASK-B", "TASK-C")):
        _spend(ledger, ts=start + 1 + i, role="frontend", task=task, cash=10.0, pct=None)
    verdict = RunBudget(
        _kimi_policy(), ledger, now=lambda: NOW, operating_mode="canary"
    ).check(role="frontend", task_id="TASK-D", tier="green")
    assert not verdict.allowed
    assert "kimi cash daily cap" in verdict.reason


def test_kimi_unknown_spend_is_mode_aware(tmp_path):
    """Usage parser is next-cycle work: canary/supervised warn and allow
    bounded invocation (provider-side limit is the backstop); unattended
    denies — the W2-3 semantics."""
    ledger = _ledger(tmp_path)
    _spend(ledger, ts=NOW - 60, role="frontend", task="TASK-A", cash=None, pct=None)
    allowed = RunBudget(
        _kimi_policy(), ledger, now=lambda: NOW, operating_mode="canary"
    ).check(role="frontend", task_id="TASK-B", tier="green")
    assert allowed.allowed
    assert "kimi cash usage" in allowed.reason  # warning folded into reason
    denied = RunBudget(
        _kimi_policy(), ledger, now=lambda: NOW, operating_mode="unattended-7d"
    ).check(role="frontend", task_id="TASK-B", tier="green")
    assert not denied.allowed
    assert "kimi cash usage unknown" in denied.reason


def test_kimi_missing_budget_block_fails_closed(tmp_path):
    p = _kimi_policy()
    del p["run"]["budgets"]["kimi"]
    verdict = RunBudget(p, _ledger(tmp_path), now=lambda: NOW).check(
        role="frontend", task_id="TASK-A", tier="green"
    )
    assert not verdict.allowed
    assert "kimi budget not configured" in verdict.reason
