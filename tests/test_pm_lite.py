from __future__ import annotations

import json
import os
import sqlite3
import uuid
from pathlib import Path
from types import SimpleNamespace

from agents.pm_lite.scheduler import PmLiteScheduler

NOW = 1_800_000_000.0


class TelemetrySpy:
    def __init__(self):
        self.suppressed_events = []

    def suppressed(self, **fields):
        self.suppressed_events.append(fields)


def _fixture(tmp_path: Path):
    repo = tmp_path / "repo"
    mailroom = tmp_path / "mailroom"
    for path in (
        repo / "agents/governor",
        repo / "tasks/packets",
        repo / "agents/merge_robot",
        mailroom / "messages",
        mailroom / "cursors",
        mailroom / "blocked",
        mailroom / "dead_letter",
        mailroom / "governor",
    ):
        path.mkdir(parents=True, exist_ok=True)
    (repo / "agents/governor/policy.yaml").write_text(
        "circuit_breaker_consecutive_failures: 3\n"
    )
    (repo / "agents/governor/run_policy.yaml").write_text(
        "per_day_max: {pm: 24, backend: 36, frontend: 36}\n"
    )
    telemetry = TelemetrySpy()
    merges = []
    scheduler = PmLiteScheduler(
        repo,
        mailroom,
        now=lambda: NOW,
        merge_runner=lambda pr: merges.append(pr),
        commit_probe=lambda task, since: False,
        config={"arbiter_fallback": "backend", "task_ttl_seconds": 86400},
        telemetry=telemetry,
    )
    return repo, mailroom, scheduler, telemetry, merges


def _message(
    *,
    task_id="TASK-1",
    to_role="pm",
    intent="STATUS",
    untrusted=False,
    refs=None,
    body="routine status",
):
    message = {
        "schema_version": "1.0",
        "message_id": str(uuid.uuid4()),
        "idempotency_key": f"{task_id}:{intent}:{uuid.uuid4().hex[:8]}",
        "task_id": task_id,
        "from_role": "backend",
        "to_role": to_role,
        "intent": intent,
        "hop_count": 0,
        "max_hops": 6,
        "refs": {"issue": 1} if refs is None else refs,
        "body_markdown": body,
    }
    if untrusted:
        message["untrusted"] = True
    return message


def _write_message(mailroom, message, *, mtime=NOW):
    path = mailroom / "messages" / f"{message['message_id']}.json"
    path.write_text(json.dumps(message))
    os.utime(path, (mtime, mtime))
    return path


def _packet(task_id, *, owner="backend", issue=1):
    return {
        "schema_version": "1.0",
        "task_id": task_id,
        "issue": issue,
        "owner_role": owner,
        "tier": "green",
        "objective": "Perform one bounded deterministic scheduler fixture task.",
        "files_in_scope": ["server/**"],
        "files_out_of_scope": ["contracts/**"],
        "required_checks": ["python3 -m pytest tests/test_pm_lite.py -q"],
        "acceptance_criteria": [{"id": "AC-1", "text": "The fixture passes."}],
        "budgets": {
            "max_attempts": 2,
            "max_files_modified": 2,
            "max_diff_lines": 100,
            "max_wall_clock_seconds": 600,
        },
    }


def _kinds(report):
    return [action.kind for action in report.actions]


def test_full_seeded_poll_makes_zero_model_invocations(tmp_path, monkeypatch):
    _, mailroom, scheduler, _, merges = _fixture(tmp_path)
    _write_message(mailroom, _message())
    called = []
    real_run = __import__("subprocess").run

    def no_model(command, *args, **kwargs):
        words = " ".join(command) if isinstance(command, list) else str(command)
        assert not any(model in words for model in ("claude", "codex", "kimi"))
        called.append(command)
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr("agents.pm_lite.scheduler.subprocess.run", no_model)
    events = [
        {"event_id": f"event-{kind}", "kind": kind, "payload": {"task_id": "TASK-1"}}
        for kind in (
            "issue_transition",
            "label_transition",
            "pr_readiness",
            "review_age",
            "ci_completion",
            "merge_eligibility",
            "budget",
            "health",
        )
    ]
    report = scheduler.poll(events=events, ready_prs=[{"number": 7}])
    assert report.model_invocations == 0
    assert merges == [7]
    assert not called
    assert "ledger_observed" in _kinds(report)
    assert _kinds(report).count("event_reduced") == len(events)
    assert "merge_robot_run" in _kinds(report)
    decisions = [
        json.loads(line)
        for line in (mailroom / "pm_lite/actions.jsonl").read_text().splitlines()
    ]
    assert decisions and all(item["body"].startswith("[DECISION]") for item in decisions)


def test_empty_queue_records_suppressed_decision_and_no_model_call(tmp_path):
    _, _, scheduler, telemetry, _ = _fixture(tmp_path)
    report = scheduler.poll(ready_prs=[])
    assert report.actions == ()
    assert report.model_invocations == 0
    assert telemetry.suppressed_events == [{
        "role": "pm",
        "task_id": "ORG",
        "decision": "suppressed_no_model",
        "suppressed_reason": "pm_lite:empty_queue",
    }]


def test_halt_suppresses_entire_cycle_without_touching_queue(tmp_path):
    _, mailroom, scheduler, telemetry, merges = _fixture(tmp_path)
    message = _message()
    _write_message(mailroom, message)
    (mailroom / "HALT").touch()
    report = scheduler.poll(
        events=[{"event_id": "health", "kind": "health", "payload": {}}],
        ready_prs=[{"number": 9}],
    )
    assert report.actions == () and report.model_invocations == 0
    assert not merges
    assert not (mailroom / "cursors/pm.acked").exists()
    assert telemetry.suppressed_events[-1]["suppressed_reason"] == "pm_lite:halt"


def test_routine_pm_message_is_acknowledged_without_model_work(tmp_path):
    _, mailroom, scheduler, telemetry, _ = _fixture(tmp_path)
    message = _message(task_id="TASK-4")
    _write_message(mailroom, message)
    report = scheduler.poll(ready_prs=[])
    assert "ledger_observed" in _kinds(report)
    assert message["message_id"] in (
        mailroom / "cursors/pm.acked"
    ).read_text().split()
    assert telemetry.suppressed_events[-1]["suppressed_reason"] == (
        "pm_lite:routine_message"
    )


def test_each_judgement_trigger_emits_exactly_once(tmp_path):
    _, _, scheduler, _, _ = _fixture(tmp_path)
    events = [
        {
            "event_id": f"judge-{kind}",
            "kind": kind,
            "payload": {"task_id": "TASK-1", "detail": f"{kind} needs judgement"},
        }
        for kind in (
            "untrusted_intake",
            "arbitration_request",
            "dead_letter",
            "adr_rfc",
        )
    ]
    first = scheduler.poll(events=events, ready_prs=[])
    second = scheduler.poll(events=events, ready_prs=[])
    judgements = [action for action in first.actions if action.kind == "judgement"]
    assert len(judgements) == 4
    assert {action.target_role for action in judgements} == {"pm"}
    assert not [action for action in second.actions if action.kind == "judgement"]
    routed = [
        json.loads(path.read_text())
        for path in (scheduler.mailroom / "messages").glob("*.json")
    ]
    assert len(routed) == 4
    assert all(message["idempotency_key"].startswith("pm-lite:judgement:") for message in routed)


def test_untrusted_arbitration_adr_and_dead_letter_sources_escalate(tmp_path):
    _, mailroom, scheduler, _, _ = _fixture(tmp_path)
    _write_message(
        mailroom,
        _message(intent="INTAKE_TICKET", untrusted=True, refs={}, body="outside request"),
    )
    _write_message(
        mailroom,
        _message(intent="ARBITRATION_REQUEST", body="review impasse"),
    )
    _write_message(
        mailroom,
        _message(intent="QUESTION", refs={"issue": 1, "adr": "0010"}, body="ADR ruling"),
    )
    dead = mailroom / "dead_letter/TASK-9/dead.json"
    dead.parent.mkdir(parents=True)
    dead.write_text(json.dumps({"task_id": "TASK-9", "reason": "three failures"}))
    report = scheduler.poll(ready_prs=[])
    assert len([a for a in report.actions if a.kind == "judgement"]) == 4


def test_changed_blocker_requeues_once_while_unchanged_only_suppresses(tmp_path):
    repo, mailroom, _, telemetry, _ = _fixture(tmp_path)
    changed = _message(task_id="TASK-1", to_role="backend")
    unchanged = _message(task_id="TASK-2", to_role="frontend")
    _write_message(mailroom, changed)
    _write_message(mailroom, unchanged)
    for role, task, message, fingerprint in (
        ("backend", "TASK-1", changed, "old"),
        ("frontend", "TASK-2", unchanged, "same"),
    ):
        path = mailroom / "blocked" / role / f"{task}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "schema_version": "1.0",
            "task_id": task,
            "role": role,
            "message_id": message["message_id"],
            "fingerprint": fingerprint,
        }))

    def preflight(message, **kwargs):
        fingerprint = "new" if message["task_id"] == "TASK-1" else "same"
        return SimpleNamespace(fingerprint=fingerprint)

    scheduler = PmLiteScheduler(
        repo,
        mailroom,
        now=lambda: NOW,
        preflight_fn=preflight,
        merge_runner=lambda pr: None,
        commit_probe=lambda task, since: False,
        config={},
        telemetry=telemetry,
    )
    report = scheduler.poll(ready_prs=[])
    assert _kinds(report).count("blocker_requeued") == 1
    messages = list((mailroom / "messages").glob("*.json"))
    assert len(messages) == 3
    assert telemetry.suppressed_events[-1]["suppressed_reason"] == (
        "pm_lite:unchanged_blocker"
    )


def test_changed_blocker_at_hop_cap_is_not_requeued(tmp_path):
    repo, mailroom, _, telemetry, _ = _fixture(tmp_path)
    original = _message(task_id="TASK-5", to_role="backend")
    original["hop_count"] = 5
    original["max_hops"] = 6
    _write_message(mailroom, original)
    blocked = mailroom / "blocked/backend/TASK-5.json"
    blocked.parent.mkdir(parents=True)
    blocked.write_text(json.dumps({
        "task_id": "TASK-5",
        "role": "backend",
        "message_id": original["message_id"],
        "fingerprint": "old",
    }))
    scheduler = PmLiteScheduler(
        repo,
        mailroom,
        now=lambda: NOW,
        preflight_fn=lambda message, **kwargs: SimpleNamespace(fingerprint="new"),
        merge_runner=lambda pr: None,
        config={},
        telemetry=telemetry,
    )
    report = scheduler.poll(ready_prs=[])
    assert "blocker_requeue_refused_hop_cap" in _kinds(report)
    assert len(list((mailroom / "messages").glob("*.json"))) == 1


def test_event_spool_is_reduced_once(tmp_path):
    _, mailroom, scheduler, _, _ = _fixture(tmp_path)
    events = mailroom / "pm_lite/events"
    events.mkdir(parents=True)
    (events / "ci-1.json").write_text(json.dumps({
        "kind": "ci_completion",
        "payload": {"task_id": "TASK-1", "status": "success"},
    }))
    first = scheduler.poll(ready_prs=[])
    second = scheduler.poll(ready_prs=[])
    assert _kinds(first).count("event_reduced") == 1
    assert "event_reduced" not in _kinds(second)


def test_merge_ready_age_over_four_hours_alarms_and_every_pr_runs(tmp_path):
    _, _, scheduler, _, merges = _fixture(tmp_path)
    clock = {"now": NOW}
    scheduler._now = lambda: clock["now"]
    ready = [{"number": 11}, {"number": 12}]
    scheduler.poll(ready_prs=ready)
    clock["now"] += 4 * 3600 + 1
    report = scheduler.poll(ready_prs=ready)
    assert merges == [11, 12, 11, 12]
    assert {a.payload["pr"] for a in report.actions if a.kind == "merge_ready_alarm"} == {
        11,
        12,
    }


def test_local_merge_pause_prevents_requesting_merge(tmp_path):
    _, mailroom, scheduler, _, merges = _fixture(tmp_path)
    pause = mailroom / "PAUSE_MERGES"
    pause.write_text("main red")
    report = scheduler.poll(ready_prs=[{"number": 11}])
    assert not merges
    assert "merge_suppressed" in _kinds(report)
    assert pause.read_text() == "main red"


def test_ttl_expiry_parks_task(tmp_path):
    _, mailroom, scheduler, _, _ = _fixture(tmp_path)
    message = _message(task_id="TASK-8")
    _write_message(mailroom, message, mtime=NOW - 86401)
    report = scheduler.poll(ready_prs=[])
    assert "task_parked" in _kinds(report)
    parked = json.loads((mailroom / "pm_lite/parked/TASK-8.json").read_text())
    assert parked["reason"] == "TTL expired after 86400s"


def test_stalled_task_three_invocations_no_commit_is_dead_lettered(tmp_path):
    _, mailroom, scheduler, _, _ = _fixture(tmp_path)
    db = sqlite3.connect(mailroom / "governor/governor_ledger.sqlite3")
    db.execute("CREATE TABLE ledger (ts REAL, role TEXT, task_id TEXT, success INTEGER)")
    db.executemany(
        "INSERT INTO ledger VALUES (?,?,?,?)",
        [(NOW - offset, "backend", "TASK-7", 0) for offset in (1, 2, 3)],
    )
    db.commit()
    db.close()
    report = scheduler.poll(ready_prs=[])
    assert "task_parked" in _kinds(report)
    dead = json.loads(
        (mailroom / "dead_letter/TASK-7/pm-lite-stall.json").read_text()
    )
    assert dead["attempts"] == 3
    assert "zero commits" in dead["reason"]


def test_arbiter_fallback_promotes_backend_when_pm_circuit_breaks(tmp_path):
    _, mailroom, scheduler, _, _ = _fixture(tmp_path)
    db = sqlite3.connect(mailroom / "governor/governor_ledger.sqlite3")
    db.execute("CREATE TABLE ledger (ts REAL, role TEXT, task_id TEXT, success INTEGER)")
    db.executemany(
        "INSERT INTO ledger VALUES (?,?,?,?)",
        [(NOW - offset, "pm", "TASK-3", 0) for offset in (1, 2, 3)],
    )
    db.commit()
    db.close()
    report = scheduler.poll(
        events=[{
            "event_id": "arbiter-event",
            "kind": "arbitration_request",
            "payload": {"task_id": "TASK-3", "detail": "round three impasse"},
        }],
        ready_prs=[],
    )
    assert "arbiter_promoted" in _kinds(report)
    judgement = next(a for a in report.actions if a.kind == "judgement")
    assert judgement.target_role == "backend"
    routed = [
        json.loads(path.read_text())
        for path in (mailroom / "messages").glob("*.json")
    ]
    assert len(routed) == 1 and routed[0]["to_role"] == "backend"


def test_ordered_backlog_assigns_only_dependency_ready_packet(tmp_path):
    repo, mailroom, scheduler, _, _ = _fixture(tmp_path)
    for task in ("TASK-1", "TASK-2"):
        (repo / f"tasks/packets/{task}.json").write_text(json.dumps(_packet(task)))
    state = mailroom / "pm_lite"
    state.mkdir()
    (state / "backlog.json").write_text(json.dumps([
        {"task_id": "TASK-1", "priority": 1, "depends_on": ["TASK-0"]},
        {"task_id": "TASK-2", "priority": 2, "depends_on": []},
    ]))
    report = scheduler.poll(ready_prs=[])
    assigned = next(a for a in report.actions if a.kind == "packet_assigned")
    assert assigned.task_id == "TASK-2"
    sent = [
        json.loads(path.read_text())
        for path in (mailroom / "messages").glob("*.json")
    ]
    assert [message["task_id"] for message in sent] == ["TASK-2"]


def test_stage_packet_assignment_preserves_exact_stage_identity(tmp_path):
    repo, mailroom, scheduler, _, _ = _fixture(tmp_path)
    stage = _packet("TASK-210-S1")
    stage["parent_task_id"] = "TASK-210"
    (repo / "tasks/packets/TASK-210-S1.json").write_text(json.dumps(stage))
    state = mailroom / "pm_lite"
    state.mkdir()
    (state / "backlog.json").write_text(json.dumps([
        {"task_id": "TASK-210-S1", "priority": 1, "depends_on": []},
    ]))
    report = scheduler.poll(ready_prs=[])
    assert "packet_assigned" in _kinds(report)
    messages = [
        json.loads(path.read_text())
        for path in (mailroom / "messages").glob("*.json")
    ]
    assert len(messages) == 1
    assert messages[0]["task_id"] == "TASK-210-S1"
