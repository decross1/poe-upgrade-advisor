from __future__ import annotations

from agents.degradation import (
    DegradationController,
    DegradationSignals,
    RunReportData,
    arbiter_after_circuit_break,
    evaluate,
)


def _signals_for(level: int) -> DegradationSignals:
    return {
        0: DegradationSignals(),
        1: DegradationSignals(route_over_schedule=True),
        2: DegradationSignals(low_cost_exhausted=True),
        3: DegradationSignals(frontier_warning=True),
        4: DegradationSignals(pm_constrained=True),
        5: DegradationSignals(hard_stop_near=True),
        6: DegradationSignals(budgets_exhausted=True),
    }[level]


def test_each_ladder_level_enters_and_exits_on_recovery(tmp_path):
    ticks = iter(range(100, 200))
    controller = DegradationController(tmp_path / "mailroom", now=lambda: next(ticks))
    observed = []
    for level in range(6):
        observed.append(controller.step(_signals_for(level)).level)
        if level:
            assert controller.step(DegradationSignals()).level == 0
    assert observed == [0, 1, 2, 3, 4, 5]
    assert controller.level() == 0
    assert not (tmp_path / "mailroom/HALT").exists()


def test_highest_trigger_wins_and_stale_allowance_degrades():
    verdict = evaluate(DegradationSignals(
        allowance_unknown_or_stale=True,
        frontier_warning=True,
        dead_letters_elevated=True,
    ))
    assert verdict.level == 5
    assert "allowance unknown or stale" in verdict.reasons


def test_level_six_writes_complete_report_before_halt(tmp_path):
    mailroom = tmp_path / "mailroom"
    controller = DegradationController(mailroom, now=lambda: 123.0)
    data = RunReportData(
        budget_by_role_day={"pm": {"day-1": {"allowance_pct": 8.5}}},
        tasks_landed=["TASK-1"],
        dead_letters=[{"task_id": "TASK-2", "last_error_fingerprint": "abc123"}],
        open_prs=[{"number": 77, "head": "deadbee", "state": "open"}],
    )
    verdict = controller.step(DegradationSignals(telemetry_lost=True), report_data=data)
    report = (mailroom / "RUN-REPORT.md").read_text()

    assert verdict.level == 6
    assert (mailroom / "HALT").is_file()
    for heading in (
        "Budget consumed per role per day",
        "Tasks landed",
        "Dead letters and last error signatures",
        "Pull requests left open",
        "Degradation-level history",
    ):
        assert heading in report
    for evidence in ("8.5", "TASK-1", "abc123", "deadbee", "telemetry loss"):
        assert evidence in report


def test_ten_day_simulation_drives_full_ladder_and_recovers(tmp_path):
    controller = DegradationController(tmp_path / "mailroom", now=lambda: 1.0)
    timeline = [0, 1, 1, 2, 3, 4, 5, 4, 2, 0]
    actual = [controller.step(_signals_for(level)).level for level in timeline]
    assert actual == timeline
    assert controller.level() == 0


def test_arbiter_fallback_promotes_backend_when_pm_circuit_breaks():
    config = {"arbiter_fallback": "backend"}
    assert arbiter_after_circuit_break(config, circuit_broken={"pm"}) == "backend"
    assert arbiter_after_circuit_break(config, circuit_broken=set()) == "pm"
    assert arbiter_after_circuit_break(config, circuit_broken={"pm", "backend"}) is None
