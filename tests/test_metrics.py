from __future__ import annotations

import json

import pytest

from agents.accounting import AnalyticsTelemetry, AccountingBudgetLedger, read_invocations
from scripts.agent_metrics import (
    accepted_cost,
    filter_records,
    main,
    record_allowance,
    summarize,
    wasted_runs,
)


def _seed(path):
    telemetry = AnalyticsTelemetry(path)
    telemetry.start(
        run_id="accepted",
        task_id="TASK-210-S1",
        role="pm",
        task_class="code",
        model="gpt-5",
        model_tier="frontier",
        started_at=200.0,
        duration_seconds=20.0,
        invocation_weight=2.0,
        files_inspected=["server/calculator.py"],
        accepted=True,
        cash_cost_usd=1.25,
    )
    telemetry.finish("accepted", completed_at=220.0, result_status="completed")
    telemetry.start(
        run_id="wasted",
        task_id="TASK-OTHER",
        role="backend",
        task_class="docs",
        model_tier="balanced",
        started_at=50.0,
        duration_seconds=5.0,
        invocation_weight=1.0,
        files_modified=["docs/guide.md"],
        accepted=False,
        rolled_back=True,
        allowance_pct_estimated=0.5,
    )
    telemetry.finish("wasted", completed_at=55.0, result_status="completed")
    telemetry.suppressed(
        run_id="suppressed",
        task_id="TASK-EMPTY",
        role="frontend",
        model_tier="frontier",
        started_at=210.0,
        decision="suppressed_preflight",
        suppressed_reason="empty_inbox",
    )
    return read_invocations(path)[0]


def test_task_model_module_since_and_summary_queries(tmp_path):
    records = _seed(tmp_path / "events.jsonl")

    assert [r["run_id"] for r in filter_records(records, task="TASK-210-S1")] == ["accepted"]
    assert {r["run_id"] for r in filter_records(records, model="frontier")} == {
        "accepted", "suppressed"
    }
    assert [r["run_id"] for r in filter_records(records, module="server.calculator")] == [
        "accepted"
    ]
    assert {r["run_id"] for r in filter_records(records, since_ts=100.0)} == {
        "accepted", "suppressed"
    }
    assert summarize(records)["suppressed"] == 1
    assert [r["run_id"] for r in wasted_runs(records)] == ["wasted"]


def test_accepted_cost_refuses_incomplete_inputs_and_labels_estimates():
    with pytest.raises(ValueError, match="lack both cash cost and allowance estimate"):
        accepted_cost([{"run_id": "missing", "accepted": True, "task_class": "code"}], "task_class")

    result = accepted_cost(
        [
            {"run_id": "cash", "accepted": True, "task_class": "code", "cash_cost_usd": 1.5},
            {
                "run_id": "allowance",
                "accepted": True,
                "task_class": "code",
                "allowance_pct_estimated": 0.75,
            },
        ],
        "task_class",
    )
    assert result["label"].startswith("ESTIMATE")
    assert result["groups"]["code"] == {
        "accepted_runs": 2,
        "cash_cost_usd": 1.5,
        "allowance_pct_estimated": 0.75,
    }
    cash_only = accepted_cost(
        [{"run_id": "cash", "accepted": True, "role": "backend", "cash_cost_usd": 1.0}],
        "role",
    )
    assert cash_only["groups"]["backend"]["allowance_pct_estimated"] is None


def test_record_allowance_derives_factor_and_backfills_invocations(tmp_path):
    telemetry_path = tmp_path / "events.jsonl"
    telemetry = AnalyticsTelemetry(telemetry_path)
    ledger = AccountingBudgetLedger(tmp_path / "budget.sqlite3")
    baseline = record_allowance(
        ledger=ledger, telemetry=telemetry, records=[], role="pm", pct=10.0, ts=100.0
    )
    assert baseline["pct_per_weighted_second"] is None

    telemetry.start(
        run_id="one", role="pm", started_at=110.0, duration_seconds=20.0,
        invocation_weight=2.0, accepted=True,
    )
    telemetry.finish("one", completed_at=130.0)
    telemetry.start(
        run_id="two", role="pm", started_at=140.0, duration_seconds=10.0,
        invocation_weight=1.0, accepted=True,
    )
    telemetry.finish("two", completed_at=150.0)
    records = read_invocations(telemetry_path)[0]

    result = record_allowance(
        ledger=ledger, telemetry=telemetry, records=records, role="pm", pct=15.0, ts=200.0
    )

    assert result["weighted_seconds"] == 50.0
    assert result["allowance_delta_pct"] == 5.0
    assert result["pct_per_weighted_second"] == 0.1
    assert result["backfilled_invocations"] == 2
    backfilled = read_invocations(telemetry_path)[0]
    assert [r["allowance_pct_estimated"] for r in backfilled] == [4.0, 1.0]
    assert all(r["allowance_pct_source"] == "manual_daily_reading" for r in backfilled)


def test_weekly_allowance_reset_is_positive_new_cycle_usage(tmp_path):
    ledger = AccountingBudgetLedger(tmp_path / "budget.sqlite3")
    assert ledger.record_allowance(
        role="pm", pct=90.0, source="manual_daily_reading", weighted_seconds=1.0, ts=100.0
    )["allowance_delta_pct"] is None
    reset = ledger.record_allowance(
        role="pm", pct=7.0, source="manual_daily_reading", weighted_seconds=14.0, ts=200.0
    )
    assert reset["cycle_reset"] is True
    assert reset["allowance_delta_pct"] == 7.0
    assert reset["pct_per_weighted_second"] == 0.5


def test_cli_commands_emit_json_and_incomplete_cost_exits_two(tmp_path, capsys):
    mailroom = tmp_path / "mailroom"
    telemetry_path = mailroom / "telemetry/invocations.jsonl"
    telemetry = AnalyticsTelemetry(telemetry_path)
    telemetry.start(run_id="incomplete", task_id="TASK-X", accepted=True, started_at=1.0)
    telemetry.finish("incomplete", completed_at=2.0)

    assert main(["--mailroom", str(mailroom), "task", "TASK-X"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["task_id"] == "TASK-X"
    assert main(["--mailroom", str(mailroom), "accepted-cost", "--group-by", "task_class"]) == 2
    assert "accepted-cost unavailable" in capsys.readouterr().err


def test_every_required_cli_query_form_runs(tmp_path, capsys):
    mailroom = tmp_path / "mailroom"
    records = _seed(mailroom / "telemetry/invocations.jsonl")
    assert records
    prefix = ["--mailroom", str(mailroom)]
    commands = [
        ["summary", "--since", "7d"],
        ["task", "TASK-210-S1"],
        ["model", "frontier"],
        ["module", "server.calculator"],
        ["wasted-runs"],
        ["accepted-cost", "--group-by", "task_class"],
        ["record-allowance", "--role", "pm", "--pct", "34"],
    ]
    for command in commands:
        assert main(prefix + command) == 0
        json.loads(capsys.readouterr().out)
