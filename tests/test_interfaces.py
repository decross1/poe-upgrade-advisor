"""Tests for the frozen lane boundary (agents/interfaces).

Owned by pm. Neither lane edits this file; a lane that needs different
behaviour here files a REQUEST in temp_channel.
"""
from __future__ import annotations

import json

import pytest

from agents.interfaces import (
    AckDecision,
    BudgetLedgerUnavailable,
    DispatchDecision,
    JsonlTelemetry,
    PacketError,
    ResultError,
    SqliteBudgetLedger,
    TelemetryPort,
    TaskState,
    load_packet,
    load_result,
    load_policy,
    resolve_budgets,
    validate_result,
)
from agents.interfaces.packet import out_of_scope, parent_of
from agents.interfaces.policy import PolicyError
from agents.interfaces.result import is_ackable
from agents.interfaces.telemetry import TELEMETRY_DEGRADED


# --------------------------------------------------------------- result

def _completed(**over):
    base = {
        "schema_version": "1.0",
        "run_id": "run-abcdef12",
        "task_id": "TASK-210-S1",
        "status": "completed",
        "summary": "did the thing",
        "commit_sha": "abc1234",
        "pushed": True,
        "acceptance_criteria": [{"id": "AC-1", "status": "passed", "evidence": "test_x"}],
    }
    base.update(over)
    return base


def test_valid_completed_result_round_trips():
    assert validate_result(_completed())["task_id"] == "TASK-210-S1"


def test_completed_without_commit_evidence_is_invalid():
    """Exit 0 plus a cheerful summary is not completion."""
    bad = _completed()
    del bad["commit_sha"]
    with pytest.raises(ResultError):
        validate_result(bad)


def test_blocked_requires_reason_and_resume_condition():
    with pytest.raises(ResultError):
        validate_result({
            "schema_version": "1.0", "run_id": "run-abcdef12",
            "task_id": "TASK-1", "status": "blocked", "summary": "stuck",
        })
    ok = validate_result({
        "schema_version": "1.0", "run_id": "run-abcdef12",
        "task_id": "TASK-1", "status": "blocked", "summary": "stuck",
        "blocked_reason": "MERGE_ROBOT_TOKEN absent",
        "resume_condition": "secret MERGE_ROBOT_TOKEN exists",
    })
    assert ok["resume_condition"]


def test_unknown_status_is_rejected():
    with pytest.raises(ResultError):
        validate_result(_completed(status="probably_fine"))


def test_extra_fields_are_rejected():
    with pytest.raises(ResultError):
        validate_result(_completed(definitely_done=True))


@pytest.mark.parametrize("payload", ["", "not json", "[]", "null"])
def test_absent_empty_and_malformed_results_all_raise_result_error(tmp_path, payload):
    p = tmp_path / ".agent-result.json"
    with pytest.raises(ResultError):
        load_result(p)  # absent
    p.write_text(payload)
    with pytest.raises(ResultError):
        load_result(p)


def test_load_result_accepts_a_good_file(tmp_path):
    p = tmp_path / ".agent-result.json"
    p.write_text(json.dumps(_completed()))
    assert load_result(p)["status"] == "completed"


def test_needs_retry_is_never_ackable_on_its_own():
    """Only the dispatcher-side attempt cap may retire a needs_retry message."""
    assert not is_ackable({"status": "needs_retry"})
    for s in ("completed", "blocked", "terminated", "dead_lettered"):
        assert is_ackable({"status": s})


# --------------------------------------------------------------- packet

def _packet(**over):
    base = {
        "schema_version": "1.0",
        "task_id": "TASK-210-S1",
        "parent_task_id": "TASK-210",
        "owner_role": "frontend",
        "tier": "green",
        "objective": "Add a retry affordance to VerdictCard",
        "files_in_scope": ["web/src/components/VerdictCard.tsx"],
        "files_out_of_scope": ["web/src/generated/**", "contracts/**"],
        "required_checks": ["npm --prefix web run test:ui -- VerdictCard"],
        "acceptance_criteria": [{"id": "AC-1", "text": "retry shows only on error"}],
        "budgets": {
            "max_attempts": 2, "max_files_modified": 2,
            "max_diff_lines": 120, "max_wall_clock_seconds": 900,
        },
    }
    base.update(over)
    return base


def test_valid_packet_round_trips(tmp_path):
    p = tmp_path / "TASK-210-S1.json"
    p.write_text(json.dumps(_packet()))
    assert load_packet(p)["tier"] == "green"


def test_packet_without_scope_or_checks_is_rejected():
    """'Fix the app' must not be executable."""
    for missing in ("files_in_scope", "required_checks", "acceptance_criteria", "budgets"):
        bad = _packet()
        del bad[missing]
        with pytest.raises(PacketError):
            load_packet_obj(bad)


def load_packet_obj(obj):
    from agents.interfaces import validate_packet
    return validate_packet(obj)


def test_packet_rejects_empty_scope():
    with pytest.raises(PacketError):
        load_packet_obj(_packet(files_in_scope=[]))


def test_stage_identity_is_derived_from_the_id():
    assert parent_of("TASK-210-S1") == "TASK-210"
    assert parent_of("TASK-210-S12") == "TASK-210"
    assert parent_of("TASK-210") is None
    assert parent_of("ORG") is None


def test_out_of_scope_denies_explicit_globs_and_unlisted_files():
    pkt = _packet()
    changed = [
        "web/src/components/VerdictCard.tsx",   # allowed
        "web/src/generated/api.ts",             # explicitly denied
        "server/app.py",                        # not in scope at all
    ]
    assert out_of_scope(changed, pkt) == ["web/src/generated/api.ts", "server/app.py"]


def test_deny_wins_over_a_broad_allow_glob():
    """A permissive files_in_scope cannot launder a forbidden path."""
    pkt = _packet(files_in_scope=["**", "web/**"], files_out_of_scope=["contracts/**"])
    assert out_of_scope(["contracts/openapi.yaml"], pkt) == ["contracts/openapi.yaml"]


# --------------------------------------------------------------- telemetry

def test_jsonl_telemetry_records_start_finish_and_suppressed(tmp_path):
    t = JsonlTelemetry(tmp_path / "telemetry.jsonl")
    assert isinstance(t, TelemetryPort)
    rid = t.start(task_id="TASK-1", role="backend")
    t.finish(rid, result_status="completed")
    t.suppressed(task_id="TASK-2", decision=DispatchDecision.SUPPRESSED_PREFLIGHT.value)
    lines = [json.loads(x) for x in (tmp_path / "telemetry.jsonl").read_text().splitlines()]
    assert [x["event"] for x in lines] == ["start", "finish", "suppressed"]
    assert lines[2]["decision"] == "suppressed_preflight"


def test_telemetry_is_fail_open_and_says_so(tmp_path, capsys):
    """A telemetry outage degrades loudly; it does not stop the org."""
    blocked = tmp_path / "afile"
    blocked.write_text("not a directory")
    t = JsonlTelemetry(blocked / "sub" / "telemetry.jsonl")
    t.start(task_id="TASK-1")          # must not raise
    assert t.degraded
    assert TELEMETRY_DEGRADED in capsys.readouterr().err


# --------------------------------------------------------------- budget

def test_attempts_increment_before_invoke_and_persist(tmp_path):
    led = SqliteBudgetLedger(tmp_path / "budget.sqlite3")
    assert led.attempts("m1") == 0
    assert led.increment_attempt("m1", "TASK-1", "pm") == 1
    assert led.increment_attempt("m1", "TASK-1", "pm") == 2
    assert SqliteBudgetLedger(tmp_path / "budget.sqlite3").attempts("m1") == 2


def test_budget_ledger_is_fail_closed(tmp_path):
    """Unwritable spend accounting must raise, never silently continue."""
    blocked = tmp_path / "afile"
    blocked.write_text("not a directory")
    with pytest.raises(BudgetLedgerUnavailable):
        SqliteBudgetLedger(blocked / "sub" / "budget.sqlite3")


def test_spend_since_aggregates_by_role(tmp_path):
    led = SqliteBudgetLedger(tmp_path / "budget.sqlite3")
    led.record_spend(role="pm", task_id="TASK-1", run_id="r1", cash_usd=1.5, success=True)
    led.record_spend(role="backend", task_id="TASK-2", run_id="r2", cash_usd=0.5)
    assert led.spend_since(since_ts=0)["cash_usd"] == 2.0
    assert led.spend_since(since_ts=0, role="pm")["invocations"] == 1


def test_unknown_spend_never_aggregates_to_zero(tmp_path):
    """Unknown cost must not read as free.

    The original implementation used COALESCE(SUM(cash_usd), 0), which reports
    "spent nothing" for "we do not know what we spent" — the one failure this
    layer exists to prevent, shipped in the module that defines the rule.
    Found by adversarial verification of W2-1, in pm's own frozen interface.
    """
    led = SqliteBudgetLedger(tmp_path / "budget.sqlite3")
    led.record_spend(role="pm", task_id="TASK-1", run_id="r1")   # cost unknown
    led.record_spend(role="pm", task_id="TASK-1", run_id="r2")   # cost unknown

    agg = led.spend_since(since_ts=0)
    assert agg["invocations"] == 2
    assert agg["cash_usd"] is None, "two unknown-cost invocations must not sum to 0"
    assert agg["cash_usd_unknown_rows"] == 2
    assert agg["complete"] is False


def test_partial_unknown_spend_is_flagged_not_silently_summed(tmp_path):
    """A known $5 plus two unknowns is not '$5 spent'."""
    led = SqliteBudgetLedger(tmp_path / "budget.sqlite3")
    led.record_spend(role="pm", task_id="TASK-1", run_id="r1")
    led.record_spend(role="pm", task_id="TASK-1", run_id="r2")
    led.record_spend(role="pm", task_id="TASK-1", run_id="r3", cash_usd=5.0)

    agg = led.spend_since(since_ts=0)
    assert agg["cash_usd"] == 5.0            # what is known
    assert agg["cash_usd_unknown_rows"] == 2  # and what is not
    assert agg["complete"] is False, "a caller must be able to refuse to certify headroom"


def test_fully_known_spend_reports_complete(tmp_path):
    led = SqliteBudgetLedger(tmp_path / "budget.sqlite3")
    led.record_spend(role="pm", task_id="TASK-1", run_id="r1", cash_usd=1.0, allowance_pct=2.0)
    agg = led.spend_since(since_ts=0)
    assert agg["complete"] is True
    assert agg["cash_usd"] == 1.0 and agg["allowance_pct"] == 2.0


# --------------------------------------------------------------- policy

def _write_policies(d, task: dict, run: dict | None = None):
    import yaml
    d.mkdir(parents=True, exist_ok=True)
    (d / "policy.yaml").write_text(yaml.safe_dump(task))
    if run is not None:
        (d / "run_policy.yaml").write_text(yaml.safe_dump(run))


def test_policy_merges_both_lane_files(tmp_path):
    _write_policies(
        tmp_path / "governor",
        {"per_task_max_invocations": 12, "execution_classes": {"green": {"max_attempts": 2}}},
        {"per_day_max": {"pm": 24}, "run": {"target_days": 7}},
    )
    p = load_policy(tmp_path / "governor")
    assert p["per_task_max_invocations"] == 12 and p["run"]["target_days"] == 7


def test_policy_refuses_a_key_defined_by_both_lanes(tmp_path):
    _write_policies(
        tmp_path / "governor",
        {"per_task_max_invocations": 12},
        {"per_task_max_invocations": 999},
    )
    with pytest.raises(PolicyError, match="lane boundary"):
        load_policy(tmp_path / "governor")


def test_packet_budgets_may_tighten_but_never_loosen():
    """A task cannot buy itself more room than its tier allows."""
    policy = {"execution_classes": {"green": {"max_diff_lines": 150, "max_attempts": 2}}}
    tightened = resolve_budgets(policy, {"tier": "green", "budgets": {"max_diff_lines": 60}})
    assert tightened["max_diff_lines"] == 60
    loosened = resolve_budgets(policy, {"tier": "green", "budgets": {"max_diff_lines": 5000,
                                                                    "max_attempts": 99}})
    assert loosened["max_diff_lines"] == 150
    assert loosened["max_attempts"] == 2


def test_real_repo_policy_loads():
    """The committed policy must satisfy the loader both lanes use."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    assert load_policy(root / "agents" / "governor")["per_task_max_invocations"] >= 1


# --------------------------------------------------------------- states

def test_suppressed_decisions_cover_everything_but_invoke():
    from agents.interfaces.states import SUPPRESSED_DECISIONS
    assert DispatchDecision.INVOKE not in SUPPRESSED_DECISIONS
    assert len(SUPPRESSED_DECISIONS) == len(DispatchDecision) - 1


def test_state_values_are_stable_strings():
    """These strings are persisted in telemetry; renaming one is a migration."""
    assert TaskState.RECOVERY_REQUIRED.value == "recovery_required"
    assert AckDecision.ACK_DEAD_LETTER.value == "ack_dead_letter"


# --------------------------------------------------------------- run budget

def test_absent_run_budget_allows_but_announces_itself_loudly():
    """No aggregate ceiling must never be mistaken for a configured one."""
    from agents.interfaces import AlwaysAllow, RunBudgetPort

    seen = []
    rb = AlwaysAllow(warn=seen.append)
    assert isinstance(rb, RunBudgetPort)
    v = rb.check(role="backend", task_id="TASK-1", tier="green")
    assert v.allowed and v.degradation_level == 0
    assert seen and AlwaysAllow.MARKER in seen[0]


def test_absent_run_budget_warns_once_not_per_call():
    from agents.interfaces import AlwaysAllow

    seen = []
    rb = AlwaysAllow(warn=seen.append)
    for _ in range(5):
        rb.check(role="pm", task_id="ORG", tier="green")
    assert len(seen) == 1


def test_run_budget_verdict_carries_reassignment():
    """Throttling a role must be able to move its work, not just stop it."""
    from agents.interfaces import RunBudgetVerdict

    v = RunBudgetVerdict(False, "frontend daily cap", degradation_level=1,
                         reassign_to="backend")
    assert not v.allowed and v.reassign_to == "backend"


def test_fail_open_survives_a_dead_stderr(tmp_path):
    """One root cause fails the sink AND the log — telemetry must still not raise.

    agent_loop.sh redirects stderr into a log file on the same disk as the
    telemetry sink, so a full filesystem takes out both. The obvious
    `print(..., file=stderr)` inside the except block is itself fail-CLOSED and
    lets the exception escape, halting the org on an analytics failure. Found
    by adversarial verification of W2-1, in pm's own frozen interface.
    """
    class DeadStderr:
        def write(self, *a, **k): raise OSError(28, "No space left on device")
        def flush(self, *a, **k): raise OSError(28, "No space left on device")

    blocked = tmp_path / "afile"
    blocked.write_text("not a directory")
    t = JsonlTelemetry(blocked / "sub" / "t.jsonl", stderr=DeadStderr())

    rid = t.start(task_id="TASK-1")        # none of these may raise
    t.finish(rid, result_status="completed")
    t.suppressed(task_id="TASK-1")
    t.crash(rid, "worker died")
    assert t.degraded is True


def test_a_torn_line_loses_one_record_not_two(tmp_path):
    """A short write leaves no trailing newline; the next append must not fuse."""
    p = tmp_path / "t.jsonl"
    p.write_text('{"event": "start", "run_id": "torn"')   # truncated, no newline
    t = JsonlTelemetry(p)
    t.suppressed(task_id="TASK-2", decision="suppressed_halt")

    lines = p.read_text().splitlines()
    good = [x for x in lines if x.strip() and _parses(x)]
    assert len(good) == 1, f"the healthy record was swallowed: {lines!r}"
    assert json.loads(good[0])["task_id"] == "TASK-2"


def _parses(s: str) -> bool:
    try:
        json.loads(s)
        return True
    except json.JSONDecodeError:
        return False
