"""Tests for agents/preflight.py — zero-token no-op suppression (W1-3).

Numbered tests follow the W1-3 table in the Lane A plan. Every preflight call
injects a gh stub (a plain callable returning canned JSON) and every dispatch
integration test monkeypatches `agents.preflight._gh_cli`; an autouse fixture
replaces `_gh_cli` with a raiser so that any path that would reach the real
`gh` CLI fails the test loudly instead of touching the network. All dispatch
tests run against a tmp-path mailroom (POB_LEDGER_DIR autouse fixture, the
tests/test_dispatch.py pattern) and a tmp-path worktree with a minimal
policy.yaml; models are only ever `--fake-agent` executables.
"""
from __future__ import annotations

import itertools
import json
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import agents.preflight as preflight_mod
from agents.dispatch import dispatch, main
from agents.governor import budget_governor
from agents.interfaces.states import AckDecision, DispatchDecision
from agents.postmaster import ledger as ledger_mod
from agents.preflight import (
    REJECT_LABELS,
    PreflightVerdict,
    blocker_fingerprint,
    clear_block,
    normalize,
    preflight,
    read_block,
    record_block,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
FAKES = Path(__file__).resolve().parent / "fakes"

INVOKE = DispatchDecision.INVOKE.value
SUPPRESSED_PREFLIGHT = DispatchDecision.SUPPRESSED_PREFLIGHT.value
SUPPRESSED_UNCHANGED_BLOCKER = DispatchDecision.SUPPRESSED_UNCHANGED_BLOCKER.value
ACK = AckDecision.ACK.value

HEX16 = re.compile(r"^[0-9a-f]{16}$")
_SEQ = itertools.count(1)


# ------------------------------------------------------------------ fixtures
@pytest.fixture(autouse=True)
def always_allow_run_budget(monkeypatch: pytest.MonkeyPatch):
    """Pin the run-budget port to AlwaysAllow (and RUN_BUDGET=0 for any
    child process): Lane B's real agents.run_budget fail-closes on missing
    allowance state, which preflight-unit tests do not model."""
    import agents.dispatch as dispatch_mod
    from agents.interfaces.run_budget import AlwaysAllow
    monkeypatch.setenv("RUN_BUDGET", "0")
    monkeypatch.setattr(dispatch_mod, "load_run_budget_port",
                        lambda *a, **k: AlwaysAllow(warn=lambda m: None))


@pytest.fixture(autouse=True)
def mailroom(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Tmp mailroom via POB_LEDGER_DIR before any dispatch or ledger call.

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
def preflight_default_on(monkeypatch: pytest.MonkeyPatch):
    """PREFLIGHT stays unset (default-on); ambient env must not flip it."""
    monkeypatch.delenv(preflight_mod.FLAG, raising=False)


@pytest.fixture(autouse=True)
def no_real_gh(monkeypatch: pytest.MonkeyPatch):
    """Any preflight gh use not explicitly stubbed fails LOUDLY, offline.

    Direct preflight() calls inject `gh=`; dispatch-integration tests
    monkeypatch `agents.preflight._gh_cli` with their stub (overriding this
    raiser). Nothing in this module can reach the real gh CLI.
    """
    def _boom(*args: str):
        raise AssertionError(f"real gh CLI path reached: gh {' '.join(args)}")

    monkeypatch.setattr(preflight_mod, "_gh_cli", _boom)


@pytest.fixture(autouse=True)
def no_gh_in_governor(monkeypatch: pytest.MonkeyPatch):
    """budget_governor's subprocess replaced so _dead_letter never runs gh.

    Mirrors tests/test_dispatch.py; dispatch.py's own subprocess (the
    fake-agent call) is a different module attribute and stays real.
    """
    class _FakeSubprocess:
        def __init__(self) -> None:
            self.calls: list[tuple[list[str], dict]] = []

        def run(self, argv, **kwargs):
            self.calls.append((list(argv), dict(kwargs)))
            return SimpleNamespace(stdout="", stderr="", returncode=0)

    fake_sub = _FakeSubprocess()
    monkeypatch.setattr(budget_governor, "subprocess", fake_sub)
    return fake_sub


def make_worktree(base: Path) -> Path:
    """Tmp worktree with a minimal policy.yaml (test_dispatch.py idiom)."""
    wt = base / "wt"
    gov_dir = wt / "agents" / "governor"
    gov_dir.mkdir(parents=True)
    policy = {
        "per_task_max_invocations": 12,
        "per_day_max": {"pm": 100, "backend": 100, "frontend": 100},
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
                  intent: str = "TASK_ASSIGN", refs: dict | None = None,
                  body: str = "Do the thing.") -> dict:
    """Write one schema-valid message JSON into <mailroom>/messages/."""
    msg_id = str(uuid.uuid4())
    msg = {
        "schema_version": "1.0",
        "message_id": msg_id,
        "idempotency_key": f"{task_id}:{intent}:{msg_id[:8]}",
        "task_id": task_id,
        "from_role": from_role,
        "to_role": to_role,
        "intent": intent,
        "hop_count": 0,
        "max_hops": 6,
        "refs": refs if refs is not None else {"issue": 1},
        "body_markdown": body,
    }
    ledger_mod.VALIDATOR.validate(msg)
    (mailroom / "messages").mkdir(parents=True, exist_ok=True)
    fp = (mailroom / "messages" /
          f"20260802T{next(_SEQ):06d}Z-{from_role}-to-{to_role}-{intent}-"
          f"{msg_id[:8]}.json")
    fp.write_text(json.dumps(msg, indent=2))
    return msg


def make_msg(*, task_id: str = "TASK-7", to_role: str = "backend",
             intent: str = "TASK_ASSIGN", refs: dict | None = None) -> dict:
    """Minimal in-memory message for DIRECT preflight() calls."""
    return {"message_id": str(uuid.uuid4()), "task_id": task_id,
            "to_role": to_role, "intent": intent,
            "refs": refs if refs is not None else {"issue": 1}}


def issue_payload(state: str = "OPEN", labels: tuple[str, ...] = (),
                  title: str = "a task") -> dict:
    return {"state": state, "labels": [{"name": n} for n in labels],
            "title": title}


def pr_payload(state: str = "OPEN", head: str = "a" * 40,
               approved_at: str | None = None,
               labels: tuple[str, ...] = ()) -> dict:
    reviews = ([{"state": "APPROVED", "commit": {"oid": approved_at}}]
               if approved_at else [])
    return {"state": state, "reviews": reviews, "headRefOid": head,
            "labels": [{"name": n} for n in labels]}


def gh_stub(issue: dict | None = None, pr: dict | None = None,
            calls: list | None = None):
    """Canned-JSON gh callable. None for a payload => that check DEGRADED."""
    def stub(*args: str) -> str | None:
        if calls is not None:
            calls.append(args)
        if args[0] == "issue":
            return json.dumps(issue) if issue is not None else None
        if args[0] == "pr":
            return json.dumps(pr) if pr is not None else None
        return None
    return stub


def counter_lines(counter: Path) -> list[str]:
    return counter.read_text().splitlines() if counter.exists() else []


def tele_lines(mailroom: Path) -> list[dict]:
    fp = mailroom / "telemetry" / "invocations.jsonl"
    if not fp.exists():
        return []
    return [json.loads(ln) for ln in fp.read_text().splitlines() if ln.strip()]


def acked(mailroom: Path, role: str) -> set[str]:
    return ledger_mod.acked_ids(mailroom, role)


def fake(name: str) -> str:
    return str(FAKES / name)


def block_path(mailroom: Path, role: str, task_id: str) -> Path:
    return mailroom / "blocked" / role / f"{task_id}.json"


# ------------------------------------------------------------------ test 2 *
def test_agent_loop_empty_inbox_is_deterministic_and_model_free():
    """Test 2 (static half) — an empty inbox produces ZERO model calls.

    On the 2026-07 record: TASK-007 rechecked 6x against one unchanged
    missing secret; 5 duplicate review verdicts at the same head SHA;
    4 stops on closed/shelved issues; >=15 zero-yield invocations from
    one role. The v2 loop invoked a model on every 4th empty poll — 82 such
    invocations measured, every one rc=0 and zero-yield. The v3 empty-inbox
    branch must call dispatch.py --record-suppressed, and agent_loop.sh must
    contain no model-CLI token at all (the W1-2 grep).
    """
    loop = (REPO_ROOT / "scripts" / "agent_loop.sh").read_text()

    # W1-2 grep: no model command token anywhere in the supervisor.
    assert not re.search(r"\b(claude|codex|kimi|qwen)\b", loop), \
        "model token reappeared in agent_loop.sh"

    # The empty-inbox branch is a deterministic dispatch.py call.
    joined = loop.replace("\\\n", " ")  # collapse line continuations
    assert re.search(
        r"python3 agents/dispatch\.py --role \"\$ROLE\"\s+"
        r"--record-suppressed empty_inbox", joined), \
        "empty-inbox branch no longer records via dispatch.py"


def test_record_suppressed_empty_inbox_writes_one_line_and_no_budget_db(
        mailroom, counter, capsys):
    """Test 2 (behavioural half) — the empty-inbox poll record costs nothing.

    On the 2026-07 record: TASK-007 rechecked 6x against one unchanged
    missing secret; 5 duplicate review verdicts at the same head SHA;
    4 stops on closed/shelved issues; >=15 zero-yield invocations from
    one role. main --record-suppressed writes exactly one suppressed telemetry
    line, creates no budget db, and runs no agent.
    """
    rc = main(["--role", "pm", "--record-suppressed", "empty_inbox"])
    assert rc == 0

    lines = tele_lines(mailroom)
    assert len(lines) == 1
    assert lines[0]["event"] == "suppressed"
    assert lines[0]["suppressed_reason"] == "empty_inbox"
    assert lines[0]["role"] == "pm"
    assert not (mailroom / "governor").exists()  # no budget db created
    assert counter_lines(counter) == []          # no agent ran
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["decision"] == SUPPRESSED_PREFLIGHT


# ------------------------------------------------------------------ test 3 *
def test_unchanged_blocker_second_message_suppressed_zero_calls(
        mailroom, worktree, counter, monkeypatch):
    """Test 3 — an unchanged blocker fingerprint means ZERO repeat calls.

    On the 2026-07 record: TASK-007 rechecked 6x against one unchanged
    missing secret; 5 duplicate review verdicts at the same head SHA;
    4 stops on closed/shelved issues; >=15 zero-yield invocations from
    one role. TASK-007 is the motivating case here. Message 1 blocks
    (SUPPRESSED_PREFLIGHT, acked,
    durable record at check_count 1); message 2 for the same task against the
    same stubbed state is SUPPRESSED_UNCHANGED_BLOCKER, acked, check_count 2,
    and the fake-agent counter stays untouched.
    """
    monkeypatch.setattr(preflight_mod, "_gh_cli",
                        gh_stub(issue=issue_payload(state="CLOSED")))
    m1 = write_message(mailroom)
    m2 = write_message(mailroom)  # same TASK-7, fresh idempotency key

    out1 = dispatch("backend", m1["message_id"], worktree,
                    fake_agent=fake("good_agent.py"))
    assert out1.decision == SUPPRESSED_PREFLIGHT
    assert out1.ack == ACK
    assert m1["message_id"] in acked(mailroom, "backend")
    rec1 = json.loads(block_path(mailroom, "backend", "TASK-7").read_text())
    assert rec1["check_count"] == 1
    assert HEX16.match(rec1["fingerprint"])
    assert out1.extra["fingerprint"] == rec1["fingerprint"]

    out2 = dispatch("backend", m2["message_id"], worktree,
                    fake_agent=fake("good_agent.py"))
    assert out2.decision == SUPPRESSED_UNCHANGED_BLOCKER
    assert out2.ack == ACK
    assert out2.invoked is False
    assert m2["message_id"] in acked(mailroom, "backend")
    assert out2.extra["fingerprint"] == rec1["fingerprint"]

    rec2 = json.loads(block_path(mailroom, "backend", "TASK-7").read_text())
    assert rec2["check_count"] == 2
    assert rec2["fingerprint"] == rec1["fingerprint"]
    assert rec2["first_seen"] == rec1["first_seen"]
    assert rec2["message_id"] == m2["message_id"]

    # ZERO model invocations across both polls.
    assert counter_lines(counter) == []

    sup = [r for r in tele_lines(mailroom) if r.get("event") == "suppressed"]
    assert len(sup) == 2
    assert sup[0]["suppressed_reason"].startswith("preflight:")
    assert sup[1]["suppressed_reason"] == "unchanged_blocker"
    assert sup[1]["fingerprint"] == rec1["fingerprint"]
    assert sup[1]["check_count"] == 2


# ------------------------------------------------------------------ test 4 *
@pytest.mark.parametrize(("state", "labels", "expect"), [
    ("CLOSED", (), "is CLOSED"),
    ("OPEN", ("parked",), "parked"),
    ("OPEN", ("shelved",), "shelved"),
])
def test_closed_parked_shelved_issue_blocks_with_zero_invocations(
        mailroom, worktree, counter, monkeypatch, state, labels, expect):
    """Test 4 — a closed / parked / shelved issue never reaches a model.

    On the 2026-07 record: TASK-007 rechecked 6x against one unchanged
    missing secret; 5 duplicate review verdicts at the same head SHA;
    4 stops on closed/shelved issues; >=15 zero-yield invocations from
    one role. Each such stop dispatched a model against a task that could
    not move. The block is decided by the injected gh stub alone — zero
    invocations.
    """
    monkeypatch.setattr(preflight_mod, "_gh_cli",
                        gh_stub(issue=issue_payload(state=state,
                                                    labels=labels)))
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("good_agent.py"))

    assert out.decision == SUPPRESSED_PREFLIGHT
    assert out.ack == ACK
    assert out.invoked is False
    assert expect in out.reason
    assert counter_lines(counter) == []
    assert msg["message_id"] in acked(mailroom, "backend")
    assert block_path(mailroom, "backend", "TASK-7").exists()


# ------------------------------------------------------------------ test 5 *
def test_approved_review_at_same_head_blocks_zero_invocations(
        mailroom, worktree, counter, monkeypatch):
    """Test 5 — an approved review at the same head SHA is a no-op.

    On the 2026-07 record: TASK-007 rechecked 6x against one unchanged
    missing secret; 5 duplicate review verdicts at the same head SHA;
    4 stops on closed/shelved issues; >=15 zero-yield invocations from
    one role. A REVIEW_REQUEST whose PR already carries an APPROVED review at the
    current headRefOid blocks with "review already complete" and invokes
    nothing.
    """
    head = "a" * 40
    monkeypatch.setattr(
        preflight_mod, "_gh_cli",
        gh_stub(pr=pr_payload(head=head, approved_at=head)))
    msg = write_message(mailroom, intent="REVIEW_REQUEST", refs={"pr": 2})

    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("good_agent.py"))

    assert out.decision == SUPPRESSED_PREFLIGHT
    assert "review already complete" in out.reason
    assert out.ack == ACK
    assert out.invoked is False
    assert counter_lines(counter) == []
    assert msg["message_id"] in acked(mailroom, "backend")
    rec = json.loads(block_path(mailroom, "backend", "TASK-7").read_text())
    assert rec["resume_condition"] == "new head SHA on PR #2"


def test_approved_review_at_different_head_passes():
    """Test 5 (converse) — an approval at an OLD head SHA does not block.

    On the 2026-07 record: TASK-007 rechecked 6x against one unchanged
    missing secret; 5 duplicate review verdicts at the same head SHA;
    4 stops on closed/shelved issues; >=15 zero-yield invocations from
    one role. The suppression must only fire at the SAME head SHA: new commits
    since the approval mean the review genuinely needs redoing.
    """
    msg = make_msg(intent="REVIEW_REQUEST", refs={"pr": 2})
    verdict = preflight(msg, gh=gh_stub(
        pr=pr_payload(head="b" * 40, approved_at="a" * 40)))

    assert verdict.ok is True
    assert verdict.reason == "ok"
    assert verdict.degraded_checks == []
    assert HEX16.match(verdict.fingerprint)


def test_merged_pr_blocks():
    """Check 7 — a task whose PR is already MERGED is complete: no model."""
    msg = make_msg(refs={"pr": 2})
    verdict = preflight(msg, gh=gh_stub(pr=pr_payload(state="MERGED")))

    assert verdict.ok is False
    assert "already merged" in verdict.reason
    assert verdict.resume_condition == "superseding work only"


# ------------------------------------------------------------------ test 7
def test_protected_scope_without_label_blocks():
    """Test 7 — packet scope touching agents/* without protected-change.

    The PROTECTED list is imported from agents.merge_robot.patterns; a scope
    that touches it without the authorising label is a missing prerequisite,
    blocked before any invocation.
    """
    packet = {"files_in_scope": ["agents/dispatch.py", "docs/notes.md"]}
    verdict = preflight(make_msg(), packet=packet,
                        gh=gh_stub(issue=issue_payload()))

    assert verdict.ok is False
    assert "protected paths" in verdict.reason
    assert "agents/dispatch.py" in verdict.reason
    assert "protected-change" in verdict.reason
    assert verdict.resume_condition == "protected-change label on #1"
    assert verdict.degraded_checks == []  # patterns import worked


def test_protected_scope_with_label_passes():
    """Test 7 (converse) — the protected-change label authorises the scope."""
    packet = {"files_in_scope": ["agents/dispatch.py"]}
    verdict = preflight(
        make_msg(), packet=packet,
        gh=gh_stub(issue=issue_payload(labels=("protected-change",))))

    assert verdict.ok is True
    assert verdict.reason == "ok"


# ------------------------------------------------------------------ test 12
def test_blocked_dispatch_persists_resume_condition_and_acks(
        mailroom, worktree, counter, monkeypatch):
    """Test 12 — a block persists the full durable record AND acks.

    Retaining a blocked message means redelivery forever — the exact failure
    W1-3 fixes. The record (the cross-lane pm-lite contract) carries the
    state; the cursor retires the message.
    """
    monkeypatch.setattr(preflight_mod, "_gh_cli",
                        gh_stub(issue=issue_payload(state="CLOSED")))
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("good_agent.py"))

    assert out.decision == SUPPRESSED_PREFLIGHT
    assert out.ack == ACK

    rec = json.loads(block_path(mailroom, "backend", "TASK-7").read_text())
    assert rec["schema_version"] == "1.0"
    assert rec["task_id"] == "TASK-7"
    assert rec["role"] == "backend"
    assert rec["message_id"] == msg["message_id"]
    assert rec["blocked_reason"] == "issue #1 is CLOSED"
    assert rec["resume_condition"] == "issue #1 reopened"
    assert HEX16.match(rec["fingerprint"])
    assert rec["fingerprint"] == out.extra["fingerprint"]
    assert rec["first_seen"].endswith("Z")
    assert rec["last_checked"].endswith("Z")
    assert rec["check_count"] == 1
    assert out.extra["resume_condition"] == "issue #1 reopened"

    # ...AND the message is retired: cursor membership, both views.
    assert msg["message_id"] in acked(mailroom, "backend")
    cursor = (mailroom / "cursors" / "backend.acked").read_text()
    assert msg["message_id"] in cursor.split()
    assert counter_lines(counter) == []


# ------------------------------------------------- changed fingerprint
def test_changed_fingerprint_clears_record_and_invokes(
        mailroom, worktree, counter, monkeypatch):
    """A CHANGED blocker fingerprint lets the task through.

    Block once on a closed issue, then the stubbed state flips to OPEN with
    no labels: the blocker moved, the durable record is cleared, and the
    task is invoked.
    """
    state = {"issue": issue_payload(state="CLOSED")}

    def stub(*args: str) -> str | None:
        return json.dumps(state["issue"]) if args[0] == "issue" else None

    monkeypatch.setattr(preflight_mod, "_gh_cli", stub)
    m1 = write_message(mailroom)
    m2 = write_message(mailroom)

    out1 = dispatch("backend", m1["message_id"], worktree,
                    fake_agent=fake("good_agent.py"))
    assert out1.decision == SUPPRESSED_PREFLIGHT
    assert block_path(mailroom, "backend", "TASK-7").exists()
    assert counter_lines(counter) == []

    state["issue"] = issue_payload(state="OPEN")  # the blocker moved
    out2 = dispatch("backend", m2["message_id"], worktree,
                    fake_agent=fake("good_agent.py"))

    assert out2.decision == INVOKE
    assert out2.invoked is True
    assert out2.ack == ACK
    assert out2.result_status == "completed"
    assert len(counter_lines(counter)) == 1  # the task actually ran
    assert not block_path(mailroom, "backend", "TASK-7").exists()  # CLEARED
    assert m2["message_id"] in acked(mailroom, "backend")


# ---------------------------------------------------- fingerprint stability
def test_normalize_strips_volatile_noise():
    """normalize() maps equal blockers with different noise to equal text."""
    s1 = ("boom at 2026-08-02T06:00:00Z in /tmp/pytest-1/wt/mod.py:41, "
          "line 41, addr 0x7fab91")
    s2 = ("boom at 2026-07-30 01:02:03 in /tmp/other-9/zz/mod.py:99, "
          "line 7, addr 0xdeadbeef")
    assert normalize(s1) == normalize(s2)
    assert "2026" not in normalize(s1)
    assert "/tmp/" not in normalize(s1)
    assert "0x" not in normalize(s1)

    # Epoch timestamps are volatile too.
    assert normalize("failed at 1722550000") == normalize("failed at 1723990000")
    # And None-ish input is tolerated.
    assert normalize("") == ""


def test_fingerprint_stable_across_volatile_noise():
    """One logical blocker => one fingerprint, whatever the noise says.

    A fingerprint embedding a timestamp or tmp path never repeats and the
    unchanged-blocker check becomes decorative — so timestamps, tmp paths,
    line numbers, and hex addresses must all wash out.
    """
    fp1 = blocker_fingerprint(
        issue_state="OPEN", labels=["blocked"], head_sha=None,
        missing_prerequisites=[
            "secret absent since 2026-08-02T00:00:00Z at /tmp/a1/x.log:12"],
        resume_condition="retry after 2026-08-02T06:00:00Z "
                         "see /tmp/b2/y.log:99 addr 0x7f01")
    fp2 = blocker_fingerprint(
        issue_state="OPEN", labels=["blocked"], head_sha=None,
        missing_prerequisites=[
            "secret absent since 2026-08-03T18:30:11Z at /tmp/zz9/other.log:7"],
        resume_condition="retry after 2026-09-01 04:05:06 "
                         "see /tmp/qq/w.log:1 addr 0xdeadbeef")
    assert fp1 == fp2
    assert HEX16.match(fp1)

    # Label ORDER is not a different blocker either.
    fp_ab = blocker_fingerprint(issue_state="OPEN", labels=["a", "b"],
                                head_sha=None, missing_prerequisites=[],
                                resume_condition=None)
    fp_ba = blocker_fingerprint(issue_state="OPEN", labels=["b", "a"],
                                head_sha=None, missing_prerequisites=[],
                                resume_condition=None)
    assert fp_ab == fp_ba


def test_fingerprint_differs_for_genuinely_different_blockers():
    """A genuinely different blocker must NOT collide."""
    base = dict(issue_state="OPEN", labels=["blocked"], head_sha="a" * 40,
                missing_prerequisites=["tool:gh"],
                resume_condition="labels ['blocked'] removed from #7")
    fp = blocker_fingerprint(**base)

    assert blocker_fingerprint(**{**base, "labels": ["parked"]}) != fp
    assert blocker_fingerprint(**{**base, "head_sha": "b" * 40}) != fp
    assert blocker_fingerprint(**{**base, "issue_state": "CLOSED"}) != fp
    assert blocker_fingerprint(
        **{**base, "missing_prerequisites": ["tool:docker"]}) != fp


# ------------------------------------------------------------- feature flag
def test_preflight_flag_zero_disables_module(
        mailroom, worktree, counter, monkeypatch):
    """PREFLIGHT=0 is the rollback path: dispatch invokes despite a blocker."""
    monkeypatch.setenv(preflight_mod.FLAG, "0")
    monkeypatch.setattr(preflight_mod, "_gh_cli",
                        gh_stub(issue=issue_payload(state="CLOSED")))
    msg = write_message(mailroom)

    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("good_agent.py"))

    assert out.decision == INVOKE
    assert out.invoked is True
    assert out.result_status == "completed"
    assert len(counter_lines(counter)) == 1
    assert not (mailroom / "blocked").exists()  # no record written either


# ------------------------------------------------------------ role mismatch
def test_role_mismatch_inside_preflight():
    """preflight() itself refuses a message addressed to another role."""
    def raising_gh(*args: str):
        raise AssertionError("gh must not be consulted on a role mismatch")

    verdict = preflight(make_msg(to_role="backend"), gh=raising_gh,
                        role="frontend")

    assert verdict.ok is False
    assert "role mismatch" in verdict.reason
    assert "backend" in verdict.reason
    assert HEX16.match(verdict.fingerprint)


# ------------------------------------------------------------ gh degraded
def test_gh_unavailable_is_degraded_never_blocked():
    """gh returning None degrades the check — surfaced, never a block."""
    msg = make_msg(intent="REVIEW_REQUEST", refs={"issue": 1, "pr": 2})
    verdict = preflight(msg, gh=lambda *args: None)

    assert verdict.ok is True
    assert "issue_state" in verdict.degraded_checks
    assert "pr_state" in verdict.degraded_checks


# -------------------------------------------------------------- check 8
def test_precondition_issue_state_expect_mismatch_blocks():
    """Check 8 — packet preconditions use the SCHEMA shape: an array of
    typed check objects (the field the audit says pays for the schema)."""
    packet = {"preconditions": [{"check": "issue_state", "expect": "OPEN"}]}
    verdict = preflight(make_msg(),
                        packet=packet,
                        gh=gh_stub(issue=issue_payload(state="CLOSED")))
    assert verdict.ok is False  # built-in closed-issue check fires first
    packet = {"preconditions": [{"check": "issue_state",
                                 "expect": "CLOSED"}]}
    verdict = preflight(make_msg(), packet=packet,
                        gh=gh_stub(issue=issue_payload(state="OPEN")))
    assert verdict.ok is False
    assert "precondition issue_state" in verdict.reason


def test_precondition_issue_labels_require_and_forbid():
    packet = {"preconditions": [
        {"check": "issue_labels", "require": ["approved-for-run"]}]}
    v = preflight(make_msg(), packet=packet,
                  gh=gh_stub(issue=issue_payload()))
    assert v.ok is False
    assert "missing ['approved-for-run']" in v.reason

    packet = {"preconditions": [
        {"check": "issue_labels", "forbid": ["wip"]}]}
    v = preflight(make_msg(), packet=packet,
                  gh=gh_stub(issue=issue_payload(labels=("wip",))))
    assert v.ok is False
    assert "forbidden ['wip']" in v.reason

    v = preflight(make_msg(), packet=packet,
                  gh=gh_stub(issue=issue_payload()))
    assert v.ok is True


def test_precondition_labels_for_scope_require_if_touching():
    packet = {"files_in_scope": ["server/app.py"],
              "preconditions": [
                  {"check": "labels_for_scope",
                   "require_if_touching": {"server/*": "backend-approved"}}]}
    v = preflight(make_msg(), packet=packet,
                  gh=gh_stub(issue=issue_payload()))
    assert v.ok is False
    assert "labels_for_scope" in v.reason
    v = preflight(make_msg(), packet=packet,
                  gh=gh_stub(issue=issue_payload(
                      labels=("backend-approved",))))
    assert v.ok is True


def test_precondition_resource_lock_and_baseline_checks(tmp_path):
    """resource_lock forbid blocks on a held lock; baseline_checks is
    surfaced as degraded (dispatcher packet enforcement runs commands,
    W2-5), never silently dropped."""
    mailroom = tmp_path / "mailroom"
    (mailroom / "locks").mkdir(parents=True)
    (mailroom / "locks" / "resource-corpus.lock").touch()
    packet = {"preconditions": [
        {"check": "resource_lock", "forbid": ["corpus"]},
        {"check": "baseline_checks", "require": ["pytest -q"]}]}
    v = preflight(make_msg(), packet=packet,
                  gh=gh_stub(issue=issue_payload()),
                  blocked_dir=mailroom / "blocked", role="backend")
    assert v.ok is False
    assert "resource_lock" in v.reason

    (mailroom / "locks" / "resource-corpus.lock").unlink()
    v = preflight(make_msg(), packet=packet,
                  gh=gh_stub(issue=issue_payload()),
                  blocked_dir=mailroom / "blocked", role="backend")
    assert v.ok is True
    assert "precondition:baseline_checks" in v.degraded_checks


def test_pr_reject_label_blocks():
    """A message referencing only a parked PR stops like a parked issue —
    _pr_view fetched labels all along; now they are read (W1-3 review
    fix)."""
    v = preflight(make_msg(refs={"pr": 9}),
                  gh=gh_stub(pr=pr_payload(labels=("parked",))))
    assert v.ok is False
    assert "PR #9 labelled ['parked']" in v.reason


def test_degraded_gh_blocks_protected_scope_but_not_unprotected():
    """ASYMMETRIC degradation policy (PM-agreed): BOTH directions asserted,
    so a future edit can neither soften the protected block nor turn it
    into a blanket block.

    Direction 1: gh degraded + scope matching a PROTECTED glob => BLOCK
    (label state unverifiable; false pass would burn invocations on
    unmergeable work and soften an authorisation control).
    Direction 2: gh degraded + scope NOT matching => still passes, with
    issue_state surfaced as degraded (a transient outage must not write
    durable blocks for ordinary work).
    The outage-era block is cheap: its fingerprint is stable, so re-checks
    suppress at zero cost, and gh recovery changes the fingerprint.
    """
    protected = {"files_in_scope": ["agents/dispatch.py"]}
    v = preflight(make_msg(), packet=protected, gh=gh_stub(issue=None))
    assert v.ok is False
    assert "unverifiable" in v.reason
    assert v.resume_condition == "gh issue label state readable again"

    unprotected = {"files_in_scope": ["web/src/App.tsx"]}
    v2 = preflight(make_msg(), packet=unprotected, gh=gh_stub(issue=None))
    assert v2.ok is True
    assert "issue_state" in v2.degraded_checks

    # Same degraded gh, same protected scope, fingerprints equal across
    # volatile noise: the outage block suppresses repeats for free.
    v3 = preflight(make_msg(), packet=protected, gh=gh_stub(issue=None))
    assert v3.fingerprint == v.fingerprint


# ------------------------------------------------------------ record_block
def test_record_block_bumps_unchanged_fingerprint(tmp_path):
    """Same fingerprint => bump check_count/last_checked, keep first_seen."""
    blocked = tmp_path / "blocked"
    v = PreflightVerdict(ok=False, reason="MERGE_ROBOT_TOKEN secret absent",
                         resume_condition="gh secret list contains "
                                          "MERGE_ROBOT_TOKEN",
                         fingerprint="ab" * 8)

    rec1 = record_block(blocked, "pm", task_id="TASK-9", message_id="m-1",
                        verdict=v)
    assert rec1["schema_version"] == "1.0"
    assert rec1["check_count"] == 1
    assert rec1["first_seen"] == rec1["last_checked"]

    rec2 = record_block(blocked, "pm", task_id="TASK-9", message_id="m-2",
                        verdict=v)
    assert rec2["check_count"] == 2
    assert rec2["first_seen"] == rec1["first_seen"]      # kept
    assert rec2["last_checked"] >= rec1["last_checked"]  # bumped
    assert rec2["message_id"] == "m-2"

    on_disk = read_block(blocked, "pm", "TASK-9")
    assert on_disk == rec2
    assert (blocked / "pm" / "TASK-9.json").exists()

    clear_block(blocked, "pm", "TASK-9")
    assert read_block(blocked, "pm", "TASK-9") is None
    clear_block(blocked, "pm", "TASK-9")  # idempotent


def test_record_block_rewrites_on_changed_fingerprint(tmp_path):
    """A NEW fingerprint is a new blocker: the record restarts at 1."""
    blocked = tmp_path / "blocked"
    v1 = PreflightVerdict(ok=False, reason="issue #9 is CLOSED",
                          resume_condition="issue #9 reopened",
                          fingerprint="ab" * 8)
    v2 = PreflightVerdict(ok=False, reason="issue #9 labelled ['parked']",
                          resume_condition="labels ['parked'] removed from #9",
                          fingerprint="cd" * 8)

    record_block(blocked, "pm", task_id="TASK-9", message_id="m-1", verdict=v1)
    record_block(blocked, "pm", task_id="TASK-9", message_id="m-2", verdict=v1)
    rec = record_block(blocked, "pm", task_id="TASK-9", message_id="m-3",
                       verdict=v2)

    assert rec["check_count"] == 1                       # NOT 3
    assert rec["fingerprint"] == "cd" * 8
    assert rec["blocked_reason"] == "issue #9 labelled ['parked']"
    assert rec["resume_condition"] == "labels ['parked'] removed from #9"
    assert rec["message_id"] == "m-3"
    assert read_block(blocked, "pm", "TASK-9") == rec


# ------------------------------------------------------------ reject labels
@pytest.mark.parametrize("label", sorted(REJECT_LABELS))
def test_reject_labels_each_block(label):
    """Every REJECT_LABEL on an OPEN issue blocks, with resume condition."""
    verdict = preflight(
        make_msg(), gh=gh_stub(issue=issue_payload(labels=(label,))))

    assert verdict.ok is False
    assert label in verdict.reason
    assert verdict.resume_condition == f"labels ['{label}'] removed from #1"


def test_reject_labels_set_matches_spec():
    """The label set is EXACTLY the W1-3 check-2 list — no drift either way."""
    assert REJECT_LABELS == {"needs-redesign", "blocked", "blocked:human",
                             "quarantine", "parked", "shelved", "deferred"}
