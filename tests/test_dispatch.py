"""Tests for agents/dispatch.py — the single governed dispatcher (W1-2).

Numbered tests follow HANDOFF section 5. Every test runs against a tmp-path
mailroom (POB_LEDGER_DIR is set by an autouse fixture BEFORE any dispatch or
ledger call) and a tmp-path worktree carrying a minimal policy.yaml. No real
model is ever spawned: every invocation goes through --fake-agent executables
in tests/fakes/, or --dry-run. `budget_governor.subprocess` is replaced with
a recorder (as in the W1-1 characterisation tests) so `gh` is never run.
"""
from __future__ import annotations

import itertools
import json
import re
import sqlite3
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import agents.dispatch as dispatch_mod
from agents.dispatch import Outcome, dispatch, main
from agents.governor import budget_governor
from agents.governor.budget_governor import Governor
from agents.interfaces.budget import BudgetLedgerUnavailable, SqliteBudgetLedger
from agents.interfaces.run_budget import RunBudgetVerdict
from agents.interfaces.states import AckDecision, DispatchDecision
from agents.postmaster import ledger as ledger_mod

REPO_ROOT = Path(__file__).resolve().parents[1]
FAKES = Path(__file__).resolve().parent / "fakes"

INVOKE = DispatchDecision.INVOKE.value
SUPPRESSED_PREFLIGHT = DispatchDecision.SUPPRESSED_PREFLIGHT.value
SUPPRESSED_GOVERNOR = DispatchDecision.SUPPRESSED_GOVERNOR.value
SUPPRESSED_HALT = DispatchDecision.SUPPRESSED_HALT.value
DEAD_LETTERED_ATTEMPTS = DispatchDecision.DEAD_LETTERED_ATTEMPTS.value
ACK = AckDecision.ACK.value
ACK_DEAD_LETTER = AckDecision.ACK_DEAD_LETTER.value
RETAIN = AckDecision.RETAIN.value

_SEQ = itertools.count(1)


# ------------------------------------------------------------------ fixtures
@pytest.fixture(autouse=True)
def mailroom(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Tmp mailroom, wired in via POB_LEDGER_DIR before any dispatch call.

    Autouse: no test in this module can ever touch the real mailroom.
    """
    root = tmp_path / "mailroom"
    monkeypatch.setenv("POB_LEDGER_DIR", str(root))
    return root


@pytest.fixture(autouse=True)
def counter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Counter file the fake agents append to; one line per invocation."""
    fp = tmp_path / "invocations.count"
    monkeypatch.setenv("COUNTER_FILE", str(fp))
    return fp


@pytest.fixture(autouse=True)
def no_gh(monkeypatch: pytest.MonkeyPatch):
    """Replace budget_governor's subprocess so _dead_letter never runs gh.

    Mirrors the W1-1 characterisation suite. dispatch.py's own subprocess
    (the fake-agent call) is a different module attribute and stays real.
    """
    class _FakeSubprocess:
        def __init__(self) -> None:
            self.calls: list[tuple[list[str], dict]] = []

        def run(self, argv, **kwargs):
            self.calls.append((list(argv), dict(kwargs)))
            return SimpleNamespace(stdout="", stderr="", returncode=0)

    fake = _FakeSubprocess()
    monkeypatch.setattr(budget_governor, "subprocess", fake)
    return fake


def make_worktree(base: Path, *, per_day: dict[str, int] | None = None) -> Path:
    """Tmp worktree with a minimal policy.yaml (and no run_policy.yaml).

    backoff is zeroed so consecutive attempts in one test are not throttled;
    the breaker threshold (3) is above the green/org max_attempts (2) so the
    per-MESSAGE cap, not the per-task breaker, is what test 1 exercises.
    tasks/dead_letter/ is deliberately NOT pre-created: a fresh fan worktree
    does not have it, and the governor must create it rather than crash
    (regression cover for the FileNotFoundError found in W1-2 review).
    """
    wt = base / "wt"
    gov_dir = wt / "agents" / "governor"
    gov_dir.mkdir(parents=True)
    policy = {
        "per_task_max_invocations": 12,
        "per_day_max": per_day if per_day is not None
        else {"pm": 100, "backend": 100, "frontend": 100},
        "backoff": {"base_minutes": 0, "max_minutes": 0},
        "circuit_breaker_consecutive_failures": 3,
        "daily_reset_hour_utc": 4,
        "execution_classes": {
            "green": {"max_attempts": 2, "max_wall_clock_seconds": 60},
            "org": {"max_attempts": 2, "max_wall_clock_seconds": 60},
        },
    }
    (gov_dir / "policy.yaml").write_text(yaml.safe_dump(policy))
    return wt


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    return make_worktree(tmp_path)


# ------------------------------------------------------------------ helpers
def write_message(mailroom: Path, *, to_role: str = "backend",
                  from_role: str = "pm", task_id: str = "TASK-7",
                  intent: str = "TASK_ASSIGN", idempotency_key: str | None = None,
                  body: str = "Do the thing.", hop_count: int = 0) -> dict:
    """Write one schema-valid message JSON into <mailroom>/messages/."""
    msg_id = str(uuid.uuid4())
    msg = {
        "schema_version": "1.0",
        "message_id": msg_id,
        "idempotency_key": idempotency_key
        or f"{task_id}:{intent}:{msg_id[:8]}",
        "task_id": task_id,
        "from_role": from_role,
        "to_role": to_role,
        "intent": intent,
        "hop_count": hop_count,
        "max_hops": 6,
        "refs": {"issue": 1},
        "body_markdown": body,
    }
    ledger_mod.VALIDATOR.validate(msg)
    (mailroom / "messages").mkdir(parents=True, exist_ok=True)
    fp = (mailroom / "messages" /
          f"20260801T{next(_SEQ):06d}Z-{from_role}-to-{to_role}-{intent}-"
          f"{msg_id[:8]}.json")
    fp.write_text(json.dumps(msg, indent=2))
    return msg


def counter_lines(counter: Path) -> list[str]:
    return counter.read_text().splitlines() if counter.exists() else []


def tele_lines(mailroom: Path) -> list[dict]:
    fp = mailroom / "telemetry" / "invocations.jsonl"
    if not fp.exists():
        return []
    return [json.loads(ln) for ln in fp.read_text().splitlines() if ln.strip()]


def acked(mailroom: Path, role: str) -> set[str]:
    return ledger_mod.acked_ids(mailroom, role)


def governor_rows(mailroom: Path) -> list[tuple]:
    db = sqlite3.connect(mailroom / "governor" / dispatch_mod.GOVERNOR_DB)
    try:
        return db.execute(
            "SELECT role, task_id, success FROM ledger ORDER BY ts").fetchall()
    finally:
        db.close()


def fake(name: str) -> str:
    return str(FAKES / name)


# ------------------------------------------------------------------ test 1
def test_attempt_cap_dead_letters_and_acks(mailroom, worktree, counter):
    """Test 1 (HANDOFF section 5) — the per-MESSAGE attempt cap, the binding
    control from the incident this whole module exists for.

    Census, 2026-07-25..27: 1,408 invocations, every one rc=0, ~88%
    zero-yield; six unackable pm messages fanned 977 times; one message ran
    180 invocations over 6h13m until a human created HALT. An agent that
    cannot write a result must get exactly max_attempts invocations — never
    a 3rd, never a 181st — and then a durable dead-letter plus a dispatcher-
    side ack.
    """
    msg = write_message(mailroom)
    mid = msg["message_id"]

    out1 = dispatch("backend", mid, worktree, fake_agent=fake("no_result_agent.py"))
    assert out1.decision == INVOKE
    assert out1.invoked is True
    assert out1.ack == RETAIN
    assert out1.attempts == 1
    assert mid not in acked(mailroom, "backend")

    out2 = dispatch("backend", mid, worktree, fake_agent=fake("no_result_agent.py"))
    assert out2.decision == INVOKE
    assert out2.invoked is True
    assert out2.ack == RETAIN
    assert out2.attempts == 2
    assert len(counter_lines(counter)) == 2

    out3 = dispatch("backend", mid, worktree, fake_agent=fake("no_result_agent.py"))
    assert out3.decision == DEAD_LETTERED_ATTEMPTS
    assert out3.ack == ACK_DEAD_LETTER
    assert out3.invoked is False
    assert out3.attempts == 3
    assert out3.max_attempts == 2

    # Suppressed no-model decisions are recorded — Wave 1 exit criterion.
    sup = [r for r in tele_lines(mailroom)
           if r.get("event") == "suppressed"
           and r.get("suppressed_reason") == "dead_lettered_attempts"]
    assert len(sup) == 1
    assert sup[0]["message_id"] == mid

    out4 = dispatch("backend", mid, worktree, fake_agent=fake("no_result_agent.py"))
    assert out4.decision == SUPPRESSED_PREFLIGHT
    assert out4.reason == "message already acked"
    assert out4.invoked is False

    # EXACTLY max_attempts invocations, ever.
    assert len(counter_lines(counter)) == 2

    dl = mailroom / "dead_letter" / "TASK-7" / f"{mid}.json"
    assert dl.exists()
    record = json.loads(dl.read_text())
    assert "cap" in record["reason"]
    assert record["attempts"] == 3
    assert record["message_id"] == mid

    cursor = (mailroom / "cursors" / "backend.acked").read_text()
    assert mid in cursor.split()


# ------------------------------------------------------------------ test 8
def test_governor_allow_is_consulted_before_invocation(
        mailroom, worktree, counter, monkeypatch):
    """Test 8a — the invocation path calls governor.allow() BEFORE the model.

    The spy proves ordering by checking the counter file is still empty at
    allow() time.
    """
    calls: list[tuple] = []

    class SpyGovernor:
        def __init__(self, policy_path, db_path):
            pass

        def allow(self, role, task_id):
            calls.append(("allow", role, task_id, len(counter_lines(counter))))
            return True, "ok"

        def record(self, role, task_id, success):
            calls.append(("record", role, task_id, success))

    monkeypatch.setattr(dispatch_mod, "Governor", SpyGovernor)
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("good_agent.py"))

    assert out.invoked is True
    assert len(counter_lines(counter)) == 1
    allow_calls = [c for c in calls if c[0] == "allow"]
    assert len(allow_calls) == 1
    assert allow_calls[0] == ("allow", "backend", "TASK-7", 0)  # before invoke
    assert calls[0][0] == "allow"  # and before record()
    assert ("record", "backend", "TASK-7", True) in calls


def test_governor_deny_suppresses_with_zero_invocations(
        mailroom, worktree, counter, monkeypatch):
    """Test 8b — a governor denial yields SUPPRESSED_GOVERNOR, zero runs."""
    class DenyGovernor:
        def __init__(self, policy_path, db_path):
            pass

        def allow(self, role, task_id):
            return False, "per-task cap"

        def record(self, role, task_id, success):
            raise AssertionError("record() must not run on a suppressed path")

    monkeypatch.setattr(dispatch_mod, "Governor", DenyGovernor)
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("good_agent.py"))

    assert out.decision == SUPPRESSED_GOVERNOR
    assert out.reason == "per-task cap"
    assert out.ack == RETAIN
    assert out.invoked is False
    assert counter_lines(counter) == []
    assert msg["message_id"] not in acked(mailroom, "backend")
    # governor deny happens before step 6: no attempt was consumed.
    bl = SqliteBudgetLedger(mailroom / "governor" / dispatch_mod.BUDGET_DB)
    assert bl.attempts(msg["message_id"]) == 0
    sup = [r for r in tele_lines(mailroom) if r.get("event") == "suppressed"]
    assert len(sup) == 1
    assert sup[0]["suppressed_reason"] == "governor:per-task cap"


# ------------------------------------------------------------------ test 9
def test_org_task_is_governed_circuit_breaker(mailroom, worktree, counter):
    """Test 9 — ORG is governed; the W1-2 behaviour flip.

    The old governor exempted task_id == "ORG" from every check; org chatter
    is precisely the category that ran unbounded. Three pre-recorded
    consecutive failures in the same governor db dispatch uses must trip the
    breaker and suppress the invocation entirely.
    """
    (mailroom / "governor").mkdir(parents=True, exist_ok=True)
    gov = Governor(worktree / "agents" / "governor" / "policy.yaml",
                   mailroom / "governor" / dispatch_mod.GOVERNOR_DB)
    for _ in range(3):
        gov.record("backend", "ORG", False)

    msg = write_message(mailroom, task_id="ORG")
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("good_agent.py"))

    assert out.decision == SUPPRESSED_GOVERNOR
    assert "circuit breaker" in out.reason
    assert out.ack == RETAIN
    assert out.invoked is False
    assert counter_lines(counter) == []
    assert msg["message_id"] not in acked(mailroom, "backend")
    bl = SqliteBudgetLedger(mailroom / "governor" / dispatch_mod.BUDGET_DB)
    assert bl.attempts(msg["message_id"]) == 0
    sup = [r for r in tele_lines(mailroom) if r.get("event") == "suppressed"]
    assert len(sup) == 1
    assert sup[0]["suppressed_reason"].startswith("governor:")


# ----------------------------------------------------------------- test 10
def test_exit_code_zero_without_result_does_not_ack(mailroom, worktree, counter):
    """Test 10 — process exit 0 with no result file must not ack.

    Census: rc==0 carried zero bits of information — all 1,408 measured
    invocations exited 0 and ~88% produced nothing; six unackable pm
    messages fanned 977 times; one message ran 180 invocations over 6h13m.
    The only ack authority is a schema-valid result file.
    """
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("no_result_agent.py"))

    assert out.invoked is True
    assert out.exit_code == 0
    assert out.result_status is None
    assert out.ack == RETAIN
    assert msg["message_id"] not in acked(mailroom, "backend")
    assert len(counter_lines(counter)) == 1


# ----------------------------------------------------------------- test 11
def test_malformed_result_is_not_success(mailroom, worktree, counter):
    """Test 11 — malformed result JSON is an invalid attempt, not a success.

    Same census as test 10 (1,408 rc=0 invocations, ~88% zero-yield, 977
    fanned copies of six unackable messages, one message 180 invocations
    over 6h13m): the dispatcher must RETAIN and record a governor failure,
    exactly as if no file had been written.
    """
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("malformed_agent.py"))

    assert out.invoked is True
    assert out.exit_code == 0
    assert out.result_status is None
    assert out.ack == RETAIN
    assert "not valid JSON" in out.reason
    assert msg["message_id"] not in acked(mailroom, "backend")
    # governor.record was called with success=False.
    assert governor_rows(mailroom) == [("backend", "TASK-7", 0)]


# ----------------------------------------------------------------- test 16
def test_good_agent_end_to_end_via_main(mailroom, worktree, counter, capsys):
    """Test 16 — full happy path through the CLI with a well-behaved fake."""
    msg = write_message(mailroom)
    mid = msg["message_id"]

    rc = main(["--role", "backend", "--message-id", mid,
               "--worktree", str(worktree),
               "--fake-agent", fake("good_agent.py")])
    assert rc == 0

    out = Outcome(**json.loads(capsys.readouterr().out.strip().splitlines()[-1]))
    assert out.decision == INVOKE
    assert out.invoked is True
    assert out.ack == ACK
    assert out.result_status == "completed"
    assert out.exit_code == 0
    assert out.attempts == 1

    assert mid in acked(mailroom, "backend")
    assert len(counter_lines(counter)) == 1

    starts = [r for r in tele_lines(mailroom) if r["event"] == "start"
              and r.get("message_id") == mid]
    assert len(starts) == 1
    run_id = starts[0]["run_id"]
    finishes = [r for r in tele_lines(mailroom) if r["event"] == "finish"
                and r["run_id"] == run_id]
    assert len(finishes) == 1
    assert finishes[0]["result_status"] == "completed"
    assert finishes[0]["exit_code"] == 0
    assert finishes[0]["timed_out"] is False

    assert governor_rows(mailroom) == [("backend", "TASK-7", 1)]


# ------------------------------------------------------- ack semantics
def test_blocked_result_is_ackable(mailroom, worktree, counter):
    """A valid `blocked` result retires the message (is_ackable)."""
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("blocked_agent.py"))

    assert out.invoked is True
    assert out.ack == ACK
    assert out.result_status == "blocked"
    assert msg["message_id"] in acked(mailroom, "backend")
    # blocked is a valid outcome, not a completion: governor success is False.
    assert governor_rows(mailroom) == [("backend", "TASK-7", 0)]


def test_needs_retry_result_is_retained(mailroom, worktree, counter):
    """A valid `needs_retry` result is NOT ackable; only the cap retires it."""
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("needs_retry_agent.py"))

    assert out.invoked is True
    assert out.ack == RETAIN
    assert out.result_status == "needs_retry"
    assert msg["message_id"] not in acked(mailroom, "backend")


# ------------------------------------------------------------------- HALT
def test_halt_blocks_before_anything(mailroom, worktree, counter):
    """HALT suppresses before the budget ledger is even opened."""
    mailroom.mkdir(parents=True, exist_ok=True)
    (mailroom / "HALT").touch()
    msg = write_message(mailroom)

    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("good_agent.py"))

    assert out.decision == SUPPRESSED_HALT
    assert out.ack == RETAIN
    assert out.invoked is False
    assert not (mailroom / "governor").exists()  # no budget db created
    assert counter_lines(counter) == []
    assert msg["message_id"] not in acked(mailroom, "backend")
    lines = tele_lines(mailroom)
    assert len(lines) == 1
    assert lines[0]["event"] == "suppressed"
    assert lines[0]["suppressed_reason"] == "halt"


# ------------------------------------------------------------- fail-closed
def test_budget_ledger_unavailable_fails_closed(
        mailroom, worktree, counter, monkeypatch, capsys):
    """Cannot record spend => do not spend: exit 3, zero invocations."""
    def raise_unavailable(path):
        raise BudgetLedgerUnavailable("disk on fire")

    monkeypatch.setattr(dispatch_mod, "SqliteBudgetLedger", raise_unavailable)
    msg = write_message(mailroom)

    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("good_agent.py"))
    assert out.exit_code == 3
    assert out.decision == SUPPRESSED_GOVERNOR
    assert out.ack == RETAIN
    assert out.invoked is False
    assert counter_lines(counter) == []

    rc = main(["--role", "backend", "--message-id", msg["message_id"],
               "--worktree", str(worktree),
               "--fake-agent", fake("good_agent.py")])
    assert rc == 3
    assert counter_lines(counter) == []
    capsys.readouterr()  # drain the emitted JSON / stderr


# ------------------------------------------------------------- idempotency
def test_duplicate_idempotency_key_acked_without_invocation(
        mailroom, worktree, counter):
    """A duplicate idempotency_key invokes once; the copy retires for free."""
    key = "TASK-7:TASK_ASSIGN:dup-key-1"
    m1 = write_message(mailroom, idempotency_key=key)
    m2 = write_message(mailroom, idempotency_key=key)

    out1 = dispatch("backend", m1["message_id"], worktree,
                    fake_agent=fake("good_agent.py"))
    assert out1.ack == ACK
    assert len(counter_lines(counter)) == 1

    out2 = dispatch("backend", m2["message_id"], worktree,
                    fake_agent=fake("good_agent.py"))
    assert out2.decision == SUPPRESSED_PREFLIGHT
    assert out2.ack == ACK
    assert "duplicate" in out2.reason
    assert out2.invoked is False
    assert len(counter_lines(counter)) == 1  # still exactly one invocation
    assert m2["message_id"] in acked(mailroom, "backend")
    sup = [r for r in tele_lines(mailroom) if r.get("event") == "suppressed"]
    assert len(sup) == 1
    assert sup[0]["suppressed_reason"] == "duplicate_idempotency_key"


# ------------------------------------------------------------ unknown role
def test_unknown_role_is_denied_not_crashed(mailroom, tmp_path, counter):
    """A role the policy does not know is a governor denial, not a KeyError.

    (PM required this explicit test.)
    """
    wt = make_worktree(tmp_path, per_day={"pm": 100, "backend": 100})
    msg = write_message(mailroom, to_role="frontend")

    out = dispatch("frontend", msg["message_id"], wt,
                   fake_agent=fake("good_agent.py"))

    assert out.decision == SUPPRESSED_GOVERNOR
    assert "role not in policy" in out.reason
    assert out.ack == RETAIN
    assert out.invoked is False
    assert counter_lines(counter) == []


# -------------------------------------------------------------- run budget
class _DenyingRunBudget:
    def __init__(self, verdict: RunBudgetVerdict) -> None:
        self.verdict = verdict
        self.checks: list[dict] = []

    def check(self, *, role: str, task_id: str, tier: str) -> RunBudgetVerdict:
        self.checks.append({"role": role, "task_id": task_id, "tier": tier})
        return self.verdict

    def level(self) -> int:
        return self.verdict.degradation_level


def test_run_budget_reassignment_forwards_exactly_once(
        mailroom, worktree, counter, monkeypatch):
    """Run-budget deny with reassign_to forwards the work, retains the
    original, and never forwards twice."""
    stub = _DenyingRunBudget(RunBudgetVerdict(
        allowed=False, reason="pm throttled, backend has headroom",
        degradation_level=2, reassign_to="backend"))
    monkeypatch.setattr(dispatch_mod, "load_run_budget_port",
                        lambda *a, **k: stub)
    msg = write_message(mailroom, to_role="pm", from_role="backend")
    mid = msg["message_id"]

    out = dispatch("pm", mid, worktree, fake_agent=fake("good_agent.py"))

    assert out.decision == SUPPRESSED_GOVERNOR
    assert out.extra["reassigned_to"] == "backend"
    assert out.extra["degradation_level"] == 2
    assert out.invoked is False
    assert counter_lines(counter) == []
    assert mid not in acked(mailroom, "pm")  # original NOT acked

    msgs = ledger_mod.all_messages(mailroom)
    fwd = [m for m in msgs
           if m["idempotency_key"] == f"reassign:{mid}:backend"]
    assert len(fwd) == 1
    fwd = fwd[0]
    assert fwd["to_role"] == "backend"
    assert fwd["message_id"] != mid
    assert fwd["hop_count"] == msg["hop_count"] + 1
    assert fwd["body_markdown"].startswith("[REASSIGNED")
    ledger_mod.VALIDATOR.validate(fwd)

    sup = [r for r in tele_lines(mailroom) if r.get("event") == "suppressed"]
    assert len(sup) == 1
    assert sup[0]["degradation_level"] == 2
    assert sup[0]["suppressed_reason"].startswith("run_budget:")

    # Forward-once: a second dispatch forwards NOTHING new.
    out2 = dispatch("pm", mid, worktree, fake_agent=fake("good_agent.py"))
    assert out2.decision == SUPPRESSED_GOVERNOR
    assert len(ledger_mod.all_messages(mailroom)) == len(msgs)
    assert counter_lines(counter) == []


def test_run_budget_deny_without_reassign_suppresses(
        mailroom, worktree, counter, monkeypatch):
    """Run-budget deny with reassign_to=None suppresses without forwarding."""
    stub = _DenyingRunBudget(RunBudgetVerdict(
        allowed=False, reason="draining", degradation_level=5,
        reassign_to=None))
    monkeypatch.setattr(dispatch_mod, "load_run_budget_port",
                        lambda *a, **k: stub)
    msg = write_message(mailroom)

    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("good_agent.py"))

    assert out.decision == SUPPRESSED_GOVERNOR
    assert "run budget" in out.reason
    assert out.extra == {"degradation_level": 5}
    assert out.invoked is False
    assert counter_lines(counter) == []
    assert len(ledger_mod.all_messages(mailroom)) == 1  # no forward
    assert msg["message_id"] not in acked(mailroom, "backend")


# ---------------------------------------------------------------- dry run
def test_dry_run_consumes_nothing(mailroom, worktree, counter):
    """--dry-run decides INVOKE but writes no attempt, telemetry, or ack."""
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree, dry_run=True,
                   fake_agent=fake("good_agent.py"))

    assert out.decision == INVOKE
    assert out.extra.get("dry_run") is True
    assert out.attempts == 1  # prospective, read not written
    assert out.invoked is False

    bl = SqliteBudgetLedger(mailroom / "governor" / dispatch_mod.BUDGET_DB)
    assert bl.attempts(msg["message_id"]) == 0
    assert tele_lines(mailroom) == []
    assert not (mailroom / "telemetry" / "invocations.jsonl").exists()
    assert counter_lines(counter) == []
    assert msg["message_id"] not in acked(mailroom, "backend")


# ---------------------------------------------------------------- timeout
def test_wall_clock_timeout_is_recorded_and_retained(
        mailroom, worktree, counter, monkeypatch):
    """A run past max_wall_clock_seconds is killed, recorded as timed_out,
    and RETAINed — a timeout is an invalid attempt, never an ack."""
    monkeypatch.setattr(
        dispatch_mod, "resolve_budgets",
        lambda policy, packet, tier: {"max_attempts": 2,
                                      "max_wall_clock_seconds": 1})
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("sleeper_agent.py"))

    assert out.invoked is True
    assert out.ack == RETAIN
    assert out.result_status is None
    assert out.exit_code == -1  # killed: no return code
    assert "timeout" in out.reason
    assert msg["message_id"] not in acked(mailroom, "backend")
    assert len(counter_lines(counter)) == 1

    finishes = [r for r in tele_lines(mailroom) if r["event"] == "finish"]
    assert len(finishes) == 1
    assert finishes[0]["timed_out"] is True
    assert finishes[0]["exit_code"] is None


# ------------------------------------------------------- regression greps
def test_no_model_spawn_tokens_outside_dispatch():
    """agent_loop.sh contains no model command token; among agents/**/*.py
    only agents/dispatch.py may. This is the grep that stops model-spawn
    logic quietly reappearing in the supervisor in six weeks."""
    pat = re.compile(r"\b(claude|codex|kimi|qwen)\b")

    loop = (REPO_ROOT / "scripts" / "agent_loop.sh").read_text()
    assert not pat.search(loop), "model token reappeared in agent_loop.sh"

    dispatch_py = REPO_ROOT / "agents" / "dispatch.py"
    offenders = sorted(
        str(p.relative_to(REPO_ROOT))
        for p in (REPO_ROOT / "agents").rglob("*.py")
        if p != dispatch_py and pat.search(p.read_text())
    )
    assert offenders == [], f"model tokens outside dispatch.py: {offenders}"
    # dispatch.py itself IS the one sanctioned spawn site.
    assert pat.search(dispatch_py.read_text())


# ------------------------------------------------------- record-suppressed
def test_record_suppressed_writes_one_line_and_nothing_else(
        mailroom, counter, capsys):
    """--record-suppressed is the deterministic empty-inbox poll record:
    one telemetry line, no budget db, no agent, exit 0."""
    rc = main(["--role", "pm", "--record-suppressed", "empty_inbox"])
    assert rc == 0

    lines = tele_lines(mailroom)
    assert len(lines) == 1
    assert lines[0]["event"] == "suppressed"
    assert lines[0]["suppressed_reason"] == "empty_inbox"
    assert lines[0]["role"] == "pm"
    assert not (mailroom / "governor").exists()  # no budget db
    assert counter_lines(counter) == []  # no agent ran
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["decision"] == SUPPRESSED_PREFLIGHT


# ------------------------------------------- W1-2 review-fix regressions
def test_reassignment_refused_at_hop_cap(mailroom, worktree, counter,
                                         monkeypatch):
    """A forward at hop 5/6 would mint a 6/6 message nothing can reply to.

    Refuse with a surfaced reason and retain — never silently produce a
    dead-end message. (Live-queue precedent: message 67cefe20 sits at 5/6.)
    """
    stub = _DenyingRunBudget(RunBudgetVerdict(
        allowed=False, reason="pm throttled", degradation_level=2,
        reassign_to="backend"))
    monkeypatch.setattr(dispatch_mod, "load_run_budget_port",
                        lambda *a, **k: stub)
    msg = write_message(mailroom, to_role="pm", from_role="backend",
                        hop_count=5)
    mid = msg["message_id"]
    before = len(ledger_mod.all_messages(mailroom))

    out = dispatch("pm", mid, worktree, fake_agent=fake("good_agent.py"))

    assert out.decision == SUPPRESSED_GOVERNOR
    assert "REFUSED: hop cap" in out.reason
    assert out.extra["reassign_refused"] == "hop_cap"
    assert out.invoked is False
    assert counter_lines(counter) == []
    assert len(ledger_mod.all_messages(mailroom)) == before  # no forward
    assert mid not in acked(mailroom, "pm")  # retained, surfaced
    sup = [r for r in tele_lines(mailroom) if r.get("event") == "suppressed"]
    assert len(sup) == 1
    assert "reassign_refused_hop_cap" in sup[0]["suppressed_reason"]


def test_role_mismatch_is_suppressed_without_ack(mailroom, worktree, counter):
    """A message addressed to another role is neither run nor retired.

    Acking it would write the wrong cursor while the addressee still sees
    the message unacked — cross-role double processing.
    """
    msg = write_message(mailroom, to_role="backend")
    mid = msg["message_id"]

    out = dispatch("frontend", mid, worktree,
                   fake_agent=fake("good_agent.py"))

    assert out.decision == SUPPRESSED_PREFLIGHT
    assert "role mismatch" in out.reason
    assert out.invoked is False
    assert counter_lines(counter) == []
    assert mid not in acked(mailroom, "frontend")
    assert mid not in acked(mailroom, "backend")
    sup = [r for r in tele_lines(mailroom) if r.get("event") == "suppressed"]
    assert sup and sup[0]["suppressed_reason"] == "role_mismatch"


def test_dead_letter_carries_last_attempt_diagnostics(mailroom, worktree,
                                                      counter):
    """Plan step 7: the dead-letter carries reason + last stderr tail.

    The cap-tripping dispatch never invokes, so the evidence must come from
    the previous attempt's persisted diagnostics — an empty dead-letter
    gives pm-lite re-triage nothing to triage with.
    """
    msg = write_message(mailroom)
    mid = msg["message_id"]

    for _ in range(2):  # max_attempts for green
        out = dispatch("backend", mid, worktree,
                       fake_agent=fake("noisy_fail_agent.py"))
        assert out.ack == RETAIN
    out3 = dispatch("backend", mid, worktree,
                    fake_agent=fake("noisy_fail_agent.py"))

    assert out3.decision == DEAD_LETTERED_ATTEMPTS
    assert counter_lines(counter) == ["run", "run"]  # exactly max_attempts
    dl = json.loads(
        (mailroom / "dead_letter" / "TASK-7" / f"{mid}.json").read_text())
    assert "BOOM-MARKER-42" in dl["stderr_tail"]
    assert dl["last_exit_code"] == 1
    assert "attempt cap exceeded" in dl["reason"]


def test_unloadable_message_is_structured_not_traceback(mailroom, worktree,
                                                        counter, capsys):
    """A missing/ambiguous/invalid message suppresses; it never tracebacks."""
    out = dispatch("backend", "deadbeef", worktree,
                   fake_agent=fake("good_agent.py"))
    assert out.decision == SUPPRESSED_PREFLIGHT
    assert out.reason.startswith("message unloadable")
    assert counter_lines(counter) == []
    sup = [r for r in tele_lines(mailroom) if r.get("event") == "suppressed"]
    assert sup and sup[0]["suppressed_reason"] == "message_invalid"

    rc = main(["--role", "backend", "--message-id", "deadbeef",
               "--worktree", str(worktree)])
    assert rc == 0  # structured Outcome on stdout, not an exception
    emitted = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert emitted["decision"] == SUPPRESSED_PREFLIGHT


def test_governor_dead_letter_dir_created_in_fresh_worktree(
        mailroom, worktree, counter, no_gh):
    """tasks/dead_letter/ is untracked, so a fresh fan worktree lacks it.

    The governor must create it on first trip instead of crashing the
    dispatch path with FileNotFoundError (found in W1-2 review; the
    worktree fixture deliberately does not pre-create the directory).
    """
    assert not (worktree / "tasks").exists()
    (mailroom / "governor").mkdir(parents=True)  # dispatch's step 2 does this
    gov = Governor(worktree / "agents" / "governor" / "policy.yaml",
                   mailroom / "governor" / dispatch_mod.GOVERNOR_DB)
    for _ in range(3):
        gov.record("backend", "ORG", False)
    msg = write_message(mailroom, task_id="ORG", intent="SYNC")

    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("good_agent.py"))

    assert out.decision == SUPPRESSED_GOVERNOR
    assert counter_lines(counter) == []
    assert (worktree / "tasks" / "dead_letter" / "ORG.md").exists()


def test_spend_row_recorded_on_invocation(mailroom, worktree, counter):
    """Every invocation writes a spend row to the fail-closed ledger.

    Token/cash fields stay None until W2-1 enriches them — None, never
    zero: a missing count must not read as free.
    """
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("good_agent.py"))
    assert out.result_status == "completed"

    db = sqlite3.connect(mailroom / "governor" / dispatch_mod.BUDGET_DB)
    try:
        rows = db.execute(
            "SELECT role, task_id, cash_usd, success FROM spend").fetchall()
    finally:
        db.close()
    assert rows == [("backend", "TASK-7", None, 1)]
