"""Tests for agents/anti_loop.py and its dispatch integration (W2-4).

Measured motivation, cited throughout: ~50 invocations of one task produced
an identical error signature with zero new evidence and no strategy change —
error-signature comparison alone would have caught it on attempt 2. The wider
census: 1,408 invocations over three days, ~88% zero-yield.

Same harness rules as the sibling suites: autouse tmp mailroom via
POB_LEDGER_DIR, PREFLIGHT=0 by default (degraded-budget tests re-enable it
per-test with a stubbed `gh`), budget_governor.subprocess replaced with a
recorder, no network, no real models — every invocation is a fake agent from
tests/fakes/. Anti-loop dispatch tests that need real git state use the
recovery-style tmp origin + clone (policy committed as a tracked file).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import agents.dispatch as dispatch_mod
import agents.preflight as preflight_mod
from agents.anti_loop import (
    TIER_ESCALATION,
    WINDOW,
    AntiLoopController,
    AttemptState,
    Verdict,
    banned_patterns,
    consume_strategy_note,
    error_signature,
    fingerprint,
    normalize_action,
    normalize_error,
    pending_strategy_note,
    prohibited_files,
    tier_override,
    token_jaccard,
)
# Aliased: a bare `test_weakening` in this namespace would be COLLECTED as a
# test by pytest (the very false-positive class the anchored TEST_SIG fixes).
from agents.anti_loop import test_weakening as weakening_hits
from agents.dispatch import dispatch
from agents.governor import budget_governor
from agents.interfaces.budget import SqliteBudgetLedger
from agents.interfaces.states import DispatchDecision
from agents.merge_robot.patterns import BANNED
from tests.test_dispatch import (
    ACK,
    ACK_DEAD_LETTER,
    DEAD_LETTERED_ATTEMPTS,
    INVOKE,
    RETAIN,
    SUPPRESSED_GOVERNOR,
    SUPPRESSED_PREFLIGHT,
    acked,
    counter_lines,
    fake,
    governor_rows,
    make_worktree,
    tele_lines,
    write_message,
)
from tests.test_recovery import clone_worktree, make_origin

CIRCUIT_BROKEN = DispatchDecision.CIRCUIT_BROKEN.value


# ------------------------------------------------------------------ fixtures

@pytest.fixture(autouse=True)
def always_allow_run_budget(monkeypatch: pytest.MonkeyPatch):
    """Pin the run-budget port to AlwaysAllow for dispatch-unit tests.

    Lane B's real agents.run_budget (integrated at b9293a8) fail-closes when
    allowance readings are missing or stale — correct for production, but
    run-level state these unit tests deliberately do not model. Tests that
    exercise run-budget denial install their own stub per-test, which
    overrides this pin.
    """
    from agents.interfaces.run_budget import AlwaysAllow
    monkeypatch.setenv("RUN_BUDGET", "0")  # reaches subprocess children too
    monkeypatch.setattr(dispatch_mod, "load_run_budget_port",
                        lambda *a, **k: AlwaysAllow(warn=lambda m: None))

@pytest.fixture(autouse=True)
def completion_proofs_pass(monkeypatch: pytest.MonkeyPatch):
    """Pin the CC-2 completion proofs to all-pass — this module exercises
    the anti-loop controller, not completion verification; the fakes'
    completion claims are fixtures. Real-proof coverage:
    tests/test_completion.py."""
    monkeypatch.setattr(dispatch_mod, "verify_completion",
                        lambda res, **kw: [])


@pytest.fixture(autouse=True)
def mailroom(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Tmp mailroom via POB_LEDGER_DIR, set BEFORE any dispatch/controller
    call. Autouse: no test here can ever touch the real mailroom."""
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
def no_preflight(monkeypatch: pytest.MonkeyPatch):
    """Default: dispatch semantics with preflight off (its suite stubs gh).

    The degraded-budget tests OVERRIDE this per-test with PREFLIGHT=1 plus a
    monkeypatched `preflight._gh_cli` — degraded means the stub returns None,
    never that a real network call failed.
    """
    monkeypatch.setenv("PREFLIGHT", "0")


@pytest.fixture(autouse=True)
def anti_loop_on(monkeypatch: pytest.MonkeyPatch):
    """The controller is under test: make sure an outer ANTI_LOOP=0 cannot
    silently turn it off (the disable test sets the flag explicitly)."""
    monkeypatch.delenv("ANTI_LOOP", raising=False)


@pytest.fixture(autouse=True)
def no_gh(monkeypatch: pytest.MonkeyPatch):
    """Replace budget_governor's subprocess so _dead_letter never runs gh."""
    class _FakeSubprocess:
        def __init__(self) -> None:
            self.calls: list[tuple[list[str], dict]] = []

        def run(self, argv, **kwargs):
            self.calls.append((list(argv), dict(kwargs)))
            return SimpleNamespace(stdout="", stderr="", returncode=0)

    rec = _FakeSubprocess()
    monkeypatch.setattr(budget_governor, "subprocess", rec)
    return rec


@pytest.fixture
def worktree(tmp_path: Path) -> Path:
    """Non-git minimal worktree (test_dispatch idiom) for tests that do not
    need git state — the dispatcher's git probes fail soft to empty."""
    return make_worktree(tmp_path)


@pytest.fixture
def git_worktree(tmp_path: Path) -> Path:
    """Recovery-style REAL git clone with the governor policy committed."""
    return clone_worktree(make_origin(tmp_path), tmp_path / "wt")


# ------------------------------------------------------------------ helpers
def assess_fresh(mailroom: Path, task_id: str, state: AttemptState,
                 **kw) -> Verdict:
    """One assessment through a FRESH controller instance, as production
    does: the fan worktrees are throwaway, so state must round-trip disk."""
    return AntiLoopController(mailroom, task_id).assess(state, **kw)


def spend_rows(mailroom: Path) -> list[tuple]:
    db = sqlite3.connect(mailroom / "governor" / dispatch_mod.BUDGET_DB)
    try:
        return db.execute(
            "SELECT cash_usd, allowance_pct, input_tokens, output_tokens, "
            "success FROM spend ORDER BY ts").fetchall()
    finally:
        db.close()


IMPORT_ERROR = ("ImportError: cannot import name 'compute' from "
                "'engine.calc' in worker")


def identical_state(tier: str = "green") -> AttemptState:
    """A zero-signal attempt; equal instances fingerprint identically."""
    return AttemptState(
        last_error=IMPORT_ERROR,
        files_changed=["engine/calc.py"],
        lines_changed=4,
        tests_run=["python3 -m pytest tests/test_calc.py -q"],
        proposed_next_action="Patch the config loader to silence the import "
                             "error",
        tier=tier,
    )


# ---------------------------------------------------------- public surface
def test_public_surface_and_ladder_constants(mailroom):
    """The interface the dispatcher (and Lane B) codes against: every name
    importable, the window and the escalation ladder pinned. Red has nowhere
    to go but the dead-letter queue."""
    assert WINDOW == 6
    assert TIER_ESCALATION == {"green": "yellow", "org": "yellow",
                               "yellow": "red"}
    assert token_jaccard("a b c", "a b c") == 1.0
    assert token_jaccard("a b", "x y") == 0.0
    assert normalize_error("") == ""
    assert normalize_action("Fix THE import") == "fix the import"
    v = Verdict("continue", "r")
    assert (v.strategy_note, v.next_tier) == (None, None)
    # consume on absent state is a no-op, not a crash.
    consume_strategy_note(mailroom, "TASK-0")
    assert tier_override(mailroom, "TASK-0") is None
    assert pending_strategy_note(mailroom, "TASK-0") is None


# ------------------------------------------------------------------ test 17
def test_17_repeated_fingerprint_escalates_not_same_tier_retry(
        mailroom, git_worktree, counter):
    """Test 17 (W2-4) — a repeated failure fingerprint escalates a tier
    instead of buying another same-tier retry.

    Census: ~50 invocations of one task produced an identical error
    signature with zero new evidence — signature comparison alone would have
    caught it on attempt 2 (the wider record: 1,408 invocations, ~88%
    zero-yield). Three identical fingerprints must yield escalate_tier
    green->yellow, the override must be durable, and the NEXT dispatch must
    actually run at the escalated class.
    """
    v1 = assess_fresh(mailroom, "TASK-7", identical_state())
    assert v1.action == "continue"
    assert "first_attempt" in v1.reason

    v2 = assess_fresh(mailroom, "TASK-7", identical_state())
    assert v2.action == "force_strategy_change"
    assert v2.strategy_note and "LOOP DETECTED" in v2.strategy_note

    v3 = assess_fresh(mailroom, "TASK-7", identical_state())
    assert v3.action == "escalate_tier"
    assert v3.next_tier == "yellow" == TIER_ESCALATION["green"]
    assert tier_override(mailroom, "TASK-7") == "yellow"

    # The escalated class is what the next invocation RUNS at, not a note:
    # spy resolve_budgets and read the telemetry task_class.
    seen_tiers: list[str] = []
    real_resolve = dispatch_mod.resolve_budgets

    def spy(policy, packet, tier):
        seen_tiers.append(tier)
        return real_resolve(policy, packet, tier)

    dispatch_mod.resolve_budgets = spy
    try:
        msg = write_message(mailroom)
        out = dispatch("backend", msg["message_id"], git_worktree,
                       fake_agent=fake("good_agent.py"))
    finally:
        dispatch_mod.resolve_budgets = real_resolve

    assert out.decision == INVOKE
    assert out.invoked is True
    assert seen_tiers == ["yellow"]
    starts = [r for r in tele_lines(mailroom) if r["event"] == "start"
              and r.get("message_id") == msg["message_id"]]
    assert len(starts) == 1
    assert starts[0]["task_class"] == "yellow"


# ------------------------------------------------------------------ test 18
def test_18_prohibited_file_modification_terminates_immediately(
        mailroom, git_worktree, counter):
    """Test 18 (W2-4) — a prohibited-file modification is a circuit breaker:
    immediate terminate, no retry, and the agent's own 'completed' claim is
    pre-empted.

    The fake edits agents/governor/policy.yaml (PROTECTED `agents/*`) inside
    a REAL git clone and writes a VALID completed result that does not
    mention the file — the breaker must believe git, not the agent. Context:
    the census this module answers (1,408 invocations, ~88% zero-yield; ~50
    identical-signature repeats of one task, catchable on attempt 2) was
    only survivable because nothing hostile happened; a protected-path write
    acked as success would be worse than waste.
    """
    assert prohibited_files(["agents/governor/policy.yaml"], None) \
        == ["agents/governor/policy.yaml"]

    msg = write_message(mailroom)
    mid = msg["message_id"]
    out = dispatch("backend", mid, git_worktree,
                   fake_agent=fake("protected_touch_agent.py"))

    assert out.decision == CIRCUIT_BROKEN
    assert out.ack == ACK_DEAD_LETTER
    assert out.invoked is True
    assert out.result_status == "completed"  # the claim that did NOT win
    assert "prohibited" in out.reason

    dl = mailroom / "dead_letter" / "TASK-7" / f"{mid}.json"
    assert dl.exists()
    record = json.loads(dl.read_text())
    assert "prohibited" in record["reason"]
    assert "agents/governor/policy.yaml" in record["reason"]

    assert mid in acked(mailroom, "backend")            # retired, durably
    assert governor_rows(mailroom) == [("backend", "TASK-7", 0)]
    assert spend_rows(mailroom)[-1][-1] == 0            # success=0, never 1
    assert len(counter_lines(counter)) == 1             # it ran exactly once


# ------------------------------------------------------------------ test 19
def test_19_green_retry_cap_and_no_plain_continue_on_zero_signal(
        mailroom, worktree, counter):
    """Test 19 (W2-4) — the retry cap per tier: green gets 2 attempts, never
    a 3rd at the same tier.

    Census: ~50 invocations of one task with an identical error signature
    and zero new evidence — signature comparison alone would have caught it
    on attempt 2; overall 1,408 invocations, ~88% zero-yield. Two layers
    enforce the cap: the W1-2 per-message attempt cap dead-letters attempt 3
    without invoking (exactly 2 counter lines, ever), and the controller
    never answers two zero-signal identical attempts with a plain same-tier
    continue — the 2nd is already force_strategy_change.
    """
    msg = write_message(mailroom)
    mid = msg["message_id"]

    for want_attempt in (1, 2):
        out = dispatch("backend", mid, worktree,
                       fake_agent=fake("no_result_agent.py"))
        assert out.decision == INVOKE
        assert out.ack == RETAIN
        assert out.attempts == want_attempt
    out3 = dispatch("backend", mid, worktree,
                    fake_agent=fake("no_result_agent.py"))
    assert out3.decision == DEAD_LETTERED_ATTEMPTS
    assert out3.ack == ACK_DEAD_LETTER
    assert out3.invoked is False
    assert out3.max_attempts == 2
    assert counter_lines(counter) == ["invoked", "invoked"]  # exactly 2 ever

    # Controller layer: zero-signal repeat is a loop on attempt 2, not a
    # retry — same-tier continue is never the answer.
    v1 = assess_fresh(mailroom, "TASK-19", identical_state())
    assert v1.action == "continue"
    v2 = assess_fresh(mailroom, "TASK-19", identical_state())
    assert v2.action == "force_strategy_change"
    assert v2.action != "continue"
    assert tier_override(mailroom, "TASK-19") is None  # no silent escalation


# -------------------------------------------------------- acceptEdits replay
def test_acceptedits_replay_stops_within_two_attempts(
        mailroom, worktree, counter):
    """The retrofit test that matters most — the acceptEdits incident end to
    end. An agent whose Bash is blocked emits an IDENTICAL PermissionError
    every time and can never write a result: in production that ran ~50
    invocations of one task with an identical error signature and zero new
    evidence (one message: 180 invocations over 6h13m), part of a census of
    1,408 invocations at ~88% zero-yield. Error-signature comparison alone
    would have caught it on attempt 2.

    Replayed under the full dispatcher: total invocations are EXACTLY
    max_attempts (2); the 2nd attempt leaves a pending strategy note (the
    controller flagged the loop); the 3rd dispatch dead-letters and acks
    WITHOUT invoking; the 4th suppresses as already-acked. Never a 3rd
    invocation, never a 181st.
    """
    msg = write_message(mailroom)
    mid = msg["message_id"]

    out1 = dispatch("backend", mid, worktree,
                    fake_agent=fake("permission_error_agent.py"))
    assert out1.decision == INVOKE
    assert out1.ack == RETAIN
    assert out1.exit_code == 1
    assert pending_strategy_note(mailroom, "TASK-7") is None  # 1st: no loop yet

    out2 = dispatch("backend", mid, worktree,
                    fake_agent=fake("permission_error_agent.py"))
    assert out2.decision == INVOKE
    assert out2.ack == RETAIN
    note = pending_strategy_note(mailroom, "TASK-7")
    assert note is not None and "LOOP DETECTED" in note  # controller saw it

    out3 = dispatch("backend", mid, worktree,
                    fake_agent=fake("permission_error_agent.py"))
    assert out3.decision == DEAD_LETTERED_ATTEMPTS
    assert out3.ack == ACK_DEAD_LETTER
    assert out3.invoked is False
    assert mid in acked(mailroom, "backend")
    dl = mailroom / "dead_letter" / "TASK-7" / f"{mid}.json"
    assert dl.exists()
    assert "PermissionError" in json.loads(dl.read_text())["stderr_tail"]

    out4 = dispatch("backend", mid, worktree,
                    fake_agent=fake("permission_error_agent.py"))
    assert out4.decision == SUPPRESSED_PREFLIGHT
    assert out4.reason == "message already acked"
    assert out4.invoked is False

    assert counter_lines(counter) == ["invoked", "invoked"]  # 2. Not 3. Not 181.


# --------------------------------------------------------- A-B-A oscillation
def test_aba_oscillation_dead_letters_even_with_distinct_fingerprints(
        mailroom):
    """A worktree hash returning to a previously seen value is a loop even
    when every fingerprint differs — thrash between two states is not
    progress."""
    s1 = AttemptState(last_error="error alpha", files_changed=["a.py"],
                      lines_changed=2, worktree_hash="aaaa111122223333")
    s2 = AttemptState(last_error="error beta", files_changed=["b.py"],
                      lines_changed=2, worktree_hash="bbbb444455556666")
    s3 = AttemptState(last_error="error gamma", files_changed=["c.py"],
                      lines_changed=2, worktree_hash="aaaa111122223333")
    assert assess_fresh(mailroom, "TASK-31", s1).action == "continue"
    assert assess_fresh(mailroom, "TASK-31", s2).action == "continue"
    v3 = assess_fresh(mailroom, "TASK-31", s3)
    assert v3.action == "dead_letter"
    assert "A-B-A" in v3.reason
    assert "aaaa1111" in v3.reason


# ------------------------------------------------------------- progress path
def test_failing_test_count_decrease_is_progress_at_same_tier(mailroom):
    """A strictly decreasing failing-test count is progress: continue at the
    same tier, no strategy forcing, no escalation."""
    s1 = AttemptState(last_error="2 failed: test_a test_b",
                      files_changed=["x.py", "y.py"], lines_changed=10,
                      tests_run=["python3 -m pytest -q"], failing_tests=2)
    s2 = AttemptState(last_error="2 failed: test_a test_b",  # same signature
                      files_changed=["x.py"], lines_changed=10,
                      tests_run=["python3 -m pytest -q"], failing_tests=1)
    assert assess_fresh(mailroom, "TASK-32", s1).action == "continue"
    v2 = assess_fresh(mailroom, "TASK-32", s2)
    assert v2.action == "continue"
    assert "failing_tests_decreased" in v2.reason
    assert v2.next_tier is None
    assert tier_override(mailroom, "TASK-32") is None


# ------------------------------------------------------------ test weakening
def test_test_weakening_terminates_and_anchored_negative_does_not(mailroom):
    """'+    it.skip(' in a diff is validation weakening: immediate
    terminate. NEGATIVE control: '+    sys.exit(main())' must NOT trip —
    before TEST_SIG was anchored (db8f77b) the unanchored `xit(`/`.skip(`
    entries matched the `xit(` inside every `sys.exit(` call, a false
    positive that would terminate honest work; the anchored patterns
    (`^\\+\\s*(it|test|describe)\\.skip\\(`, `^\\+\\s*xit\\(`) only fire on
    an added line that IS a skip."""
    weak_diff = ("--- a/tests/test_x.spec.js\n+++ b/tests/test_x.spec.js\n"
                 "+    it.skip('flaky, disabled to go green', () => {\n")
    assert weakening_hits(weak_diff), "anchored TEST_SIG must catch it.skip("
    v = assess_fresh(mailroom, "TASK-33", identical_state(),
                     diff_text=weak_diff)
    assert v.action == "terminate"
    assert "weakening" in v.reason

    honest_diff = ("--- a/cli.py\n+++ b/cli.py\n"
                   "+    sys.exit(main())\n")
    assert weakening_hits(honest_diff) == []
    v2 = assess_fresh(mailroom, "TASK-34", identical_state(),
                      diff_text=honest_diff)
    assert v2.action != "terminate"


# ------------------------------------------------------------ banned pattern
def test_banned_pattern_in_diff_terminates(mailroom):
    """A merge-robot BANNED pattern appearing in the added diff terminates.
    One representative entry, READ from the imported list (never a local
    copy — two divergent copies of a security list is how one quietly stops
    matching)."""
    rep = next(p for p in BANNED if "WriteProcessMemory" in p)
    assert rep  # the representative still exists in the shared list
    diff = ("--- a/injector.py\n+++ b/injector.py\n"
            "+    kernel32.WriteProcessMemory(handle, addr, buf, n, None)\n")
    hits = banned_patterns(diff)
    assert hits and "WriteProcessMemory" in hits[0]
    v = assess_fresh(mailroom, "TASK-35", identical_state(), diff_text=diff)
    assert v.action == "terminate"
    assert "banned pattern" in v.reason


# ------------------------------------------------------------- cost breaker
def test_cost_exceeding_value_usd_terminates(mailroom):
    """Spending more than the task is worth is an immediate stop, not a
    retry decision."""
    packet = {"budgets": {"value_usd": 1.5}}
    state = identical_state()
    state.cost_usd = 2.25
    v = assess_fresh(mailroom, "TASK-36", state, packet=packet)
    assert v.action == "terminate"
    assert "exceeds value_usd" in v.reason

    # At or under value: not a trip.
    state2 = identical_state()
    state2.cost_usd = 1.5
    v2 = assess_fresh(mailroom, "TASK-37", state2, packet=packet)
    assert v2.action != "terminate"


# ------------------------------------------------------- regression breaker
def test_previously_passing_test_now_failing_terminates(mailroom):
    """A previously-passing required check failing again is a breaker.
    _regression_check writes the baseline on the green attempt and flags the
    regression on the next; the controller turns the flag into terminate."""
    cmd = "python3 -m pytest tests/test_calc.py -q"
    green = {"tests": [{"command": cmd, "exit_code": 0}]}
    red = {"tests": [{"command": cmd, "exit_code": 1}]}

    assert dispatch_mod._regression_check(mailroom, "TASK-38", green) is False
    baseline = json.loads(
        (mailroom / "governor" / "test_baseline" / "TASK-38.json").read_text())
    assert cmd in baseline
    assert dispatch_mod._regression_check(mailroom, "TASK-38", red) is True

    v = assess_fresh(mailroom, "TASK-38", identical_state(),
                     previously_passing_now_failing=True)
    assert v.action == "terminate"
    assert "previously-passing" in v.reason


# ---------------------------------------------------------------- fingerprint
def test_fingerprint_stable_under_noise_distinct_under_change(mailroom):
    """The fingerprint must not rotate on volatile noise (timestamps, tmp
    paths, hex addresses, line numbers) — a fingerprint that never repeats
    detects nothing — and must rotate on real change (different error class,
    different files)."""
    e1 = ("Traceback at 2026-08-01T09:15:02Z: File "
          "/tmp/fan-1a2b/wt/server/app.py, line 212, in handler "
          "ValueError: bad input at 0x7fded00 (ts 1722500000123)")
    e2 = ("Traceback at 2026-08-02T23:59:59Z: File "
          "/tmp/fan-9z8y/wt/server/app.py, line 999, in handler "
          "ValueError: bad input at 0x1a2b3c (ts 1722599999999)")
    assert normalize_error(e1) == normalize_error(e2)
    assert error_signature(e1) == error_signature(e2)

    base = dict(files_changed=["server/app.py"], lines_changed=3,
                tests_run=["python3 -m pytest -q"],
                proposed_next_action="fix the handler input validation")
    fp1 = fingerprint(AttemptState(last_error=e1, **base))
    fp2 = fingerprint(AttemptState(last_error=e2, **base))
    assert fp1 == fp2  # noise-stable

    e3 = e1.replace("ValueError: bad input", "KeyError: 'session'")
    fp3 = fingerprint(AttemptState(last_error=e3, **base))
    assert fp3 != fp1  # different error class is a different failure

    other_files = dict(base, files_changed=["server/routes.py"])
    fp4 = fingerprint(AttemptState(last_error=e1, **other_files))
    assert fp4 != fp1  # different files touched is a different attempt


# ------------------------------------------------------------- strategy note
def test_strategy_note_names_forbidden_approach_lands_in_prompt_once(
        mailroom, worktree, counter, tmp_path, monkeypatch):
    """The force-strategy-change note must (a) name the loop and forbid the
    prior approach, (b) reach the next prompt verbatim, (c) be consumed —
    injected once, not forever."""
    assess_fresh(mailroom, "TASK-7", identical_state())
    v2 = assess_fresh(mailroom, "TASK-7", identical_state())
    assert v2.action == "force_strategy_change"

    note = pending_strategy_note(mailroom, "TASK-7")
    assert note is not None
    assert "LOOP DETECTED on TASK-7" in note
    assert "FORBIDDEN" in note
    # It names the forbidden approach (normalised verb+target, not prose).
    assert normalize_action("Patch the config loader to silence the import "
                            "error") in note

    ctx_copy = tmp_path / "ctx-copy.json"
    monkeypatch.setenv("CTX_COPY_FILE", str(ctx_copy))
    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("prompt_capture_agent.py"))
    assert out.decision == INVOKE
    assert out.invoked is True

    ctx = json.loads(ctx_copy.read_text())  # the ctx the fake agent received
    assert note in ctx["prompt"]
    assert ctx["prompt"].endswith(note)  # appended to the base prompt
    assert pending_strategy_note(mailroom, "TASK-7") is None  # consumed


# ------------------------------------------------------------- feature flag
def test_anti_loop_flag_zero_disables_state_escalation_and_breakers(
        mailroom, tmp_path, counter, monkeypatch):
    """ANTI_LOOP=0 is the W2-4 rollback path: three identical failing
    attempts behave exactly pre-W2-4 — no state file, no escalation, no
    breaker, no circuit-broken outcome. (Cap raised to 3 so all three
    actually invoke.)"""
    monkeypatch.setenv("ANTI_LOOP", "0")
    wt = tmp_path / "wt0"
    gov = wt / "agents" / "governor"
    gov.mkdir(parents=True)
    (gov / "policy.yaml").write_text(yaml.safe_dump({
        "per_task_max_invocations": 12,
        "per_day_max": {"pm": 100, "backend": 100, "frontend": 100},
        "backoff": {"base_minutes": 0, "max_minutes": 0},
        "circuit_breaker_consecutive_failures": 5,
        "daily_reset_hour_utc": 4,
        "execution_classes": {
            "green": {"max_attempts": 3, "max_wall_clock_seconds": 60},
            "org": {"max_attempts": 3, "max_wall_clock_seconds": 60},
        },
    }))
    msg = write_message(mailroom)
    mid = msg["message_id"]

    for _ in range(3):
        out = dispatch("backend", mid, wt,
                       fake_agent=fake("permission_error_agent.py"))
        assert out.decision == INVOKE
        assert out.ack == RETAIN

    assert len(counter_lines(counter)) == 3
    assert not (mailroom / "governor" / "anti_loop").exists()  # no state
    assert tier_override(mailroom, "TASK-7") is None
    assert pending_strategy_note(mailroom, "TASK-7") is None
    assert not (mailroom / "dead_letter").exists()  # no breaker fired
    for rec in tele_lines(mailroom):
        assert "anti_loop" not in rec


# ---------------------------------------------------------- degraded budget
def test_degraded_budget_exhausts_then_probe_gates_resumption(
        mailroom, worktree, counter, monkeypatch):
    """PM-agreed degraded budget (W2-4): 10 consecutive invocations on
    degraded preflight checks exhaust the budget; the 11th costs zero and
    probes gh instead; a successful probe resets the streak and lets work
    resume. Degrade-to-idle-with-reason, self-resuming — never a halt.

    PREFLIGHT is ENABLED here (unlike the module default) with
    `preflight._gh_cli` stubbed: gh returning None is what 'degraded' means.
    """
    monkeypatch.setenv("PREFLIGHT", "1")
    monkeypatch.setattr(preflight_mod, "_gh_cli", lambda *a: None)

    for i in range(10):
        msg = write_message(mailroom, task_id=f"TASK-10{i}")
        out = dispatch("backend", msg["message_id"], worktree,
                       fake_agent=fake("good_agent.py"))
        assert out.invoked is True
        assert out.ack == ACK
        assert dispatch_mod._degraded_streak(mailroom) == i + 1
    assert len(counter_lines(counter)) == 10

    # 11th: budget exhausted, probe still failing => zero-cost suppression.
    msg11 = write_message(mailroom, task_id="TASK-111")
    out11 = dispatch("backend", msg11["message_id"], worktree,
                     fake_agent=fake("good_agent.py"))
    assert out11.decision == SUPPRESSED_GOVERNOR
    assert "degraded budget exhausted" in out11.reason
    assert out11.invoked is False
    assert len(counter_lines(counter)) == 10          # NO invocation
    assert msg11["message_id"] not in acked(mailroom, "backend")  # retained
    bl = SqliteBudgetLedger(mailroom / "governor" / dispatch_mod.BUDGET_DB)
    assert bl.attempts(msg11["message_id"]) == 0      # no attempt consumed
    sup = [r for r in tele_lines(mailroom)
           if r.get("suppressed_reason") == "degraded_budget"]
    assert len(sup) == 1
    assert sup[0]["degraded_checks"] == ["issue_state"]
    assert dispatch_mod._degraded_streak(mailroom) == 10  # unchanged

    # gh recovers: the probe succeeds => streak resets, work resumes.
    def gh_probe_ok(*args):
        return "ok" if args[:2] == ("auth", "status") else None

    monkeypatch.setattr(preflight_mod, "_gh_cli", gh_probe_ok)
    out_resume = dispatch("backend", msg11["message_id"], worktree,
                          fake_agent=fake("good_agent.py"))
    assert out_resume.invoked is True
    assert out_resume.ack == ACK
    assert len(counter_lines(counter)) == 11
    # Reset to 0 at the probe, then +1 because this run was itself degraded.
    assert dispatch_mod._degraded_streak(mailroom) == 1


def test_clean_invocation_resets_partial_degraded_streak(
        mailroom, worktree, counter, monkeypatch):
    """PM ask, verbatim requirement: a monotonic counter must never halt a
    healthy org. A CLEAN (non-degraded) invocation resets a partial streak
    to 0 — accumulated unrelated blips do not add up to a stop."""
    monkeypatch.setenv("PREFLIGHT", "1")

    def gh_ok(*args):
        if args[:2] == ("issue", "view"):
            return json.dumps({"state": "OPEN", "labels": [], "title": "t"})
        return "ok"

    monkeypatch.setattr(preflight_mod, "_gh_cli", gh_ok)
    dispatch_mod._set_degraded_streak(mailroom, 7)

    msg = write_message(mailroom)
    out = dispatch("backend", msg["message_id"], worktree,
                   fake_agent=fake("good_agent.py"))
    assert out.invoked is True
    assert out.ack == ACK
    assert len(counter_lines(counter)) == 1
    assert dispatch_mod._degraded_streak(mailroom) == 0  # reset, not 8


def test_18b_lying_files_modified_claim_cannot_launder_protected_edit(
        mailroom, git_worktree, counter, monkeypatch):
    """W2-4 review defect 2, the explicit-lie variant: the agent edits
    agents/governor/policy.yaml but CLAIMS files_modified=["README.md"].

    The claim-first version of _assess_anti_loop fed the claim to the
    prohibited-file breaker and acked the tampered result as a completed
    success. The breaker must see git truth; a claim can add paths, never
    subtract them.
    """
    monkeypatch.setenv("CLAIM_FILES", '["README.md"]')
    msg = write_message(mailroom)

    out = dispatch("backend", msg["message_id"], git_worktree,
                   fake_agent=fake("protected_touch_agent.py"))

    assert out.decision == "circuit_broken"
    assert out.ack == "ack_dead_letter"
    assert "prohibited files modified" in out.reason
    assert "agents/governor/policy.yaml" in out.reason
    assert msg["message_id"] in acked(mailroom, "backend")
    dl = (mailroom / "dead_letter" / msg["task_id"] /
          f"{msg['message_id']}.json")
    assert dl.exists()
    rows = governor_rows(mailroom)
    assert rows and rows[-1][2] == 0  # never recorded as success


def test_fingerprint_distinct_when_only_strategy_changes():
    """Guard for the normalize_action component of the composite fingerprint
    (PM's W2-4 VERIFY: this mutation SURVIVED — dropping it left 45 green).

    'Strategy materially changed' is a PROGRESS signal (audit 8.3). If a
    future edit drops proposed_next_action from the hash, an agent that
    legitimately changes approach after a failure fingerprints identical to
    its previous attempt and gets escalated or dead-lettered as a loop —
    the controller would punish exactly the behaviour it exists to reward,
    and it would look like the controller working.

    Same error, same files, same tests, DIFFERENT strategy => distinct.
    (The inverse — identical everything => identical fingerprint — is
    pinned by the ladder tests.)
    """
    base = dict(last_error="PermissionError: Bash denied",
                files_changed=["server/app.py"],
                tests_run=["pytest tests -q"],
                recent_tool_calls=["Bash", "Read"])
    retry = AttemptState(**base,
                         proposed_next_action="retry the same edit again")
    decompose = AttemptState(**base,
                             proposed_next_action="decompose into three "
                                                  "smaller patches")
    assert fingerprint(retry) != fingerprint(decompose)
    # And each component-equal pair still collides (stability half).
    assert fingerprint(retry) == fingerprint(AttemptState(
        **base, proposed_next_action="retry the same edit again"))


# --- L-4b: the breaker is the SECOND reader of PROTECTED (2026-08-03) -----


def test_prohibited_files_lets_pm_author_packets():
    """Orchestrator ruling L-4, second site. Proof #12 in completion.py and
    this breaker both read merge_robot's PROTECTED. Fixing only #12 left pm
    still dead-lettering here — observed live on message d09a9fd8. The two
    readers must stay in step."""
    from agents.anti_loop import prohibited_files

    assert prohibited_files(["tasks/packets/TASK-999-S2.json"], None,
                            role="pm") == []


def test_prohibited_files_packet_authorship_is_pm_only():
    from agents.anti_loop import prohibited_files

    for role in ("backend", "frontend", None):
        assert prohibited_files(["tasks/packets/TASK-1.json"], None,
                                role=role) == ["tasks/packets/TASK-1.json"]


def test_pm_authorization_does_not_extend_past_packets():
    """Every other protected glob still terminates for pm."""
    from agents.anti_loop import prohibited_files

    for path in ("agents/dispatch.py", "AGENTS.md", ".github/workflows/ci.yml",
                 "PRODUCT_DOCTRINE.md", "scripts/check_invariants.py"):
        assert prohibited_files([path], None, role="pm") == [path]


def test_packet_out_of_scope_still_beats_role_authorization():
    """A packet may forbid what a role is otherwise authorized to touch —
    deny still wins."""
    from agents.anti_loop import prohibited_files

    packet = {"files_out_of_scope": ["tasks/packets/**"]}
    assert prohibited_files(["tasks/packets/TASK-1.json"], packet,
                            role="pm") == ["tasks/packets/TASK-1.json"]
