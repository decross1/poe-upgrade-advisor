from __future__ import annotations

import io
import json
import sqlite3

import pytest

from agents.accounting import (
    AnalyticsTelemetry,
    AccountingBudgetLedger,
    provider_usage,
    read_invocations,
)
from agents.interfaces.budget import BudgetLedgerUnavailable
from agents.interfaces.states import DispatchDecision, SUPPRESSED_DECISIONS
from agents.interfaces.telemetry import INVOCATION_FIELDS, TELEMETRY_DEGRADED


def test_missing_provider_tokens_round_trip_as_none(tmp_path):
    path = tmp_path / "invocations.jsonl"
    telemetry = AnalyticsTelemetry(path)
    run_id = telemetry.start(task_id="TASK-21", role="backend", provider="codex")
    telemetry.finish(run_id, result_status="completed", success=True)

    records, errors = read_invocations(path)

    assert not errors
    assert len(records) == 1
    assert set(INVOCATION_FIELDS).issubset(records[0])
    assert records[0]["input_tokens"] is None
    assert records[0]["output_tokens"] is None
    assert records[0]["cached_input_tokens"] is None
    assert 0 not in (
        records[0]["input_tokens"],
        records[0]["output_tokens"],
        records[0]["cached_input_tokens"],
    )


def test_budget_failure_blocks_invocation_but_analytics_failure_does_not(tmp_path):
    ledger = AccountingBudgetLedger(tmp_path / "budget.sqlite3")
    ledger.db.close()
    invoked = False
    with pytest.raises(BudgetLedgerUnavailable):
        ledger.increment_attempt("message", "TASK-22", "pm")
        invoked = True
    assert not invoked

    blocked = tmp_path / "not-a-directory"
    blocked.write_text("x")
    report = tmp_path / "RUN-REPORT.md"
    stderr = io.StringIO()
    telemetry = AnalyticsTelemetry(blocked / "events.jsonl", run_report=report, stderr=stderr)
    run_id = telemetry.start(task_id="TASK-22")
    analytics_caller_continued = True
    assert run_id
    assert analytics_caller_continued
    assert telemetry.degraded
    assert TELEMETRY_DEGRADED in stderr.getvalue()
    assert TELEMETRY_DEGRADED in report.read_text()


def test_post_open_spend_write_operational_error_is_fail_closed(tmp_path):
    ledger = AccountingBudgetLedger(tmp_path / "budget.sqlite3")
    ledger.db.close()

    class BrokenConnection:
        def execute(self, sql, args=()):
            raise sqlite3.OperationalError("simulated full filesystem")

    ledger.db = BrokenConnection()
    with pytest.raises(BudgetLedgerUnavailable, match="write failed"):
        ledger.record_spend(role="pm", task_id="TASK-WRITE", run_id="run-write")


def test_crash_preserves_recoverable_incomplete_record(tmp_path):
    path = tmp_path / "events.jsonl"
    telemetry = AnalyticsTelemetry(path)
    run_id = telemetry.start(task_id="TASK-CRASH", files_modified=["server/calculator.py"])
    telemetry.crash(run_id, "worker disappeared")

    records, errors = read_invocations(path)

    assert not errors
    assert records[0]["task_id"] == "TASK-CRASH"
    assert records[0]["files_modified"] == ["server/calculator.py"]
    assert records[0]["result_status"] == "crashed"
    assert records[0]["crash_reason"] == "worker disappeared"
    assert records[0]["incomplete"] is True


def test_every_suppressed_decision_can_be_counted(tmp_path):
    path = tmp_path / "events.jsonl"
    telemetry = AnalyticsTelemetry(path)
    for decision in SUPPRESSED_DECISIONS:
        telemetry.suppressed(task_id="TASK-S", decision=decision.value, suppressed_reason="test")

    records, errors = read_invocations(path)

    assert not errors
    assert len(records) == len(SUPPRESSED_DECISIONS)
    assert {record["decision"] for record in records} == {
        decision.value for decision in SUPPRESSED_DECISIONS
    }
    assert all(record["result_status"] == "suppressed" for record in records)


def test_interim_jsonl_events_are_materialized_without_migration(tmp_path):
    path = tmp_path / "events.jsonl"
    events = [
        {"event": "start", "run_id": "old", "task_id": "TASK-OLD", "started_at": 2.0},
        {"event": "finish", "run_id": "old", "completed_at": 5.0, "input_tokens": None},
        {
            "event": "suppressed",
            "task_id": "TASK-EMPTY",
            "decision": DispatchDecision.SUPPRESSED_PREFLIGHT.value,
        },
    ]
    path.write_text("".join(json.dumps(event) + "\n" for event in events))

    records, errors = read_invocations(path)

    assert not errors
    assert records[0]["duration_seconds"] == 3.0
    assert records[0]["input_tokens"] is None
    assert records[1]["result_status"] == "suppressed"


def test_provider_json_usage_normalizes_known_fields_and_keeps_unknown_none():
    codex = provider_usage(
        "codex",
        {"usage": {"inputTokens": 12, "outputTokens": 3, "cachedInputTokens": 7}},
    )
    assert (codex["input_tokens"], codex["output_tokens"], codex["cached_input_tokens"]) == (
        12, 3, 7,
    )
    assert codex["cash_usd"] is None and codex["invocation_weight"] == 1.0
    claude = provider_usage(
        "claude",
        {"usage": {"input_tokens": 9, "output_tokens": 4}, "total_cost_usd": 0.25},
    )
    assert claude["input_tokens"] == 9 and claude["output_tokens"] == 4
    assert claude["cached_input_tokens"] is None
    assert claude["cash_usd"] == claude["cash_cost_usd"] == 0.25
    assert provider_usage(
        "codex", {"usage": {"input_tokens": 5, "output_tokens": 2}}
    )["input_tokens"] == 5


def test_unexpected_provider_usage_shape_is_none_and_degrades_loudly():
    stderr = io.StringIO()
    result = provider_usage("codex", {"usage": {"new_token_total": 99}}, stderr=stderr)
    assert all(value is None for value in result.values())
    assert TELEMETRY_DEGRADED in stderr.getvalue()
    assert "new_token_total" in stderr.getvalue()


def test_lane_a_raw_stdout_contract_parses_final_anthropic_and_openai_events():
    anthropic = "\n".join([
        json.dumps({"type": "system", "session_id": "s"}),
        json.dumps({
            "type": "result",
            "total_cost_usd": 0.42,
            "usage": {
                "input_tokens": 101,
                "output_tokens": 22,
                "cache_read_input_tokens": 80,
            },
        }),
    ])
    parsed = provider_usage("anthropic", anthropic)
    assert parsed == {
        "cash_usd": 0.42,
        "cash_cost_usd": 0.42,
        "input_tokens": 101,
        "output_tokens": 22,
        "cached_input_tokens": 80,
        "invocation_weight": 1.0,
    }

    openai = "\n".join([
        json.dumps({"type": "thread.started", "thread_id": "t"}),
        json.dumps({
            "type": "turn.completed",
            "usage": {
                "input_tokens": 55,
                "cached_input_tokens": 40,
                "output_tokens": 13,
            },
        }),
    ])
    parsed = provider_usage("openai", openai)
    assert parsed["input_tokens"] == 55
    assert parsed["cached_input_tokens"] == 40
    assert parsed["output_tokens"] == 13
    assert parsed["cash_usd"] is None
    assert parsed["invocation_weight"] == 1.0


def test_nonempty_raw_output_without_usage_degrades_loudly_and_never_zeroes():
    stderr = io.StringIO()
    result = provider_usage(
        "openai", json.dumps({"type": "turn.completed", "tokens": 12}), stderr=stderr
    )
    assert all(value is None for value in result.values())
    assert TELEMETRY_DEGRADED in stderr.getvalue()


def test_accounting_ledger_preserves_unknown_spend_and_records_decisions(tmp_path):
    ledger = AccountingBudgetLedger(tmp_path / "budget.sqlite3")
    ledger.record_spend(role="pm", task_id="TASK-U", run_id="unknown")
    aggregate = ledger.spend_since(since_ts=0)
    assert aggregate == {
        "invocations": 1,
        "cash_usd": None,
        "allowance_pct": None,
        "input_tokens": None,
        "output_tokens": None,
    }
    ledger.record_decision(
        role="pm", task_id="TASK-U", run_id="unknown", decision="deny", reason="daily cap"
    )
    assert ledger.db.execute(
        "SELECT decision, reason FROM governor_decisions"
    ).fetchone() == ("deny", "daily cap")
