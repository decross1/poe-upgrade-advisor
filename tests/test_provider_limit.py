"""A provider session cap must stop the ROLE, loudly, before spending.

Operator ruling 2026-08-03: run until the session caps hit, expecting
feedback. There was none — grep for session/rate/quota across agents/
returned one unrelated ENOSPC comment. The 2026-07-27 record is what that
absence costs: the CLI printed "You've hit your session limit" and exited
rc=0, so the dispatcher saw only a missing result file.
"""

import json
import time

import pytest

from agents import provider_limit as pl


# --- detection: the phrases providers actually emit when refusing ---------


@pytest.mark.parametrize("text", [
    "You've hit your session limit. Please try again later.",
    "Youve hit your session limit",
    "ERROR: usage limit reached for this account",
    "session limit reached",
    "quota exceeded",
    "insufficient_quota",
    "429 Too Many Requests",
    "Too Many Requests",
    "rate limit exceeded, try again in 60s",
])
def test_detects_real_refusals(text):
    assert pl.detect(text) is not None


@pytest.mark.parametrize("text", [
    "",
    None,
    '{"role":"assistant","content":"ok"}',
    "wrote 2 bytes to probe.txt",
    "tests/test_run_budget.py::test_kimi_daily_cap_throttles PASSED",
    # The narrowness that matters: an agent discussing limits in prose, or
    # editing this very module, must not quiet its own role.
    "I considered the per-day rate limit design but did not change it.",
    "the docstring mentions a session limit policy in passing",
])
def test_does_not_trip_on_ordinary_output(text):
    assert pl.detect(text) is None


def test_scans_every_stream():
    assert pl.detect(None, "", "quota exceeded") is not None


# --- marker lifecycle ------------------------------------------------------


def test_mark_then_active_then_expiry(tmp_path):
    now = 1_000_000.0
    pl.mark(tmp_path, "pm", matched="session limit reached", cooldown=600,
            now=now)
    live = pl.active(tmp_path, "pm", now=now + 10)
    assert live is not None
    assert live["matched"] == "session limit reached"
    assert live["seconds_remaining"] == 590

    # After expiry: not active, and the marker is cleaned up so a later
    # dispatch is not gated by a stale file.
    assert pl.active(tmp_path, "pm", now=now + 601) is None
    assert not pl.marker_path(tmp_path, "pm").exists()


def test_marker_is_role_scoped(tmp_path):
    pl.mark(tmp_path, "pm", matched="quota exceeded")
    assert pl.active(tmp_path, "pm") is not None
    assert pl.active(tmp_path, "backend") is None


def test_absent_marker_does_not_block(tmp_path):
    """Deliberately NOT fail-closed: a missing marker means proceed. A false
    positive here silently idles a healthy role, which is worse than the
    bounded waste it prevents."""
    assert pl.active(tmp_path, "frontend") is None


def test_corrupt_marker_does_not_block_forever(tmp_path):
    path = pl.marker_path(tmp_path, "pm")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    assert pl.active(tmp_path, "pm") is None


def test_operator_can_clear_by_deleting(tmp_path):
    pl.mark(tmp_path, "pm", matched="quota exceeded", cooldown=99999)
    assert pl.active(tmp_path, "pm") is not None
    pl.marker_path(tmp_path, "pm").unlink()
    assert pl.active(tmp_path, "pm") is None


def test_marker_is_readable_by_a_human(tmp_path):
    p = pl.mark(tmp_path, "backend", matched="session limit reached",
                run_id="abc123")
    data = json.loads(p.read_text())
    assert data["role"] == "backend"
    assert data["run_id"] == "abc123"
    assert "Delete this file" in data["note"]
    assert data["expires_at"] > time.time()


# --- the dispatcher honours it before spending ----------------------------


def test_dispatch_gate_precedes_invocation():
    """The gate sits at step 1.5 — after HALT, before the budget ledger and
    long before the model call, so a capped provider costs zero."""
    import inspect

    from agents import dispatch

    src = inspect.getsource(dispatch.dispatch)
    gate = src.index("provider_limit_mod.active")
    invoke = src.index("_run_capped")
    assert gate < invoke, "provider-limit gate must precede the model call"
    assert src.index('mailroom / "HALT"') < gate, "HALT still comes first"


@pytest.mark.parametrize("text", [
    "please try again later",
    "If the build fails, please try again later.",
    "see docs; please try again later",
    "Transient network error — please try again later",
    # Moved here from the positive list when the pattern narrowed: a bare
    # "try again in N minutes" carries no limit word, and after a false
    # positive cost six hours of the only working role, ambiguity resolves
    # toward NOT quieting a healthy role.
    "Please try again in 12 minutes",
])
def test_bare_try_again_is_not_a_cap(text):
    """L-23 (2026-08-03). A bare "please try again later" pattern quieted the
    frontend role for SIX HOURS moments after that role produced the mission's
    first accepted product code — and it was the only uncapped role, so the
    org would have sat idle until 13:00Z on a phrase that appears in ordinary
    prose. Exactly the false positive L-14's own docstring warned about, in
    L-14's own pattern list. It means a cap only alongside an explicit
    limit/quota word."""
    assert pl.detect(text) is None


@pytest.mark.parametrize("text", [
    "rate limit exceeded, please try again later",
    "You have exceeded your quota. Please try again in 10 minutes",
    "at capacity — please try again shortly",
])
def test_try_again_with_a_limit_word_is_a_cap(text):
    assert pl.detect(text) is not None


@pytest.mark.parametrize("matched,minutes", [
    ("429 The engine is currently overloaded, please try again", 5),
    ("503 Service Unavailable", 5),
    ("the server is busy", 5),
    ("temporarily unavailable", 5),
    ("You've hit your session limit", 45),
    ("quota exceeded", 45),
    ("usage limit reached", 45),
])
def test_cooldown_matches_the_kind_of_refusal(matched, minutes):
    """L-25: a transient overload is not an exhausted quota. kimi returned a
    429 'engine overloaded' seconds after COMPLETING a task, and the flat 6h
    cooldown parked the org's only working role — pm and backend were both
    quota-capped — for six hours over a capacity blip.

    L-30 (2026-08-03) revised the OTHER arm of this from a flat 6h to the
    first rung of an escalating ladder. The operator reported codex at 2% and
    claude at 5% of WEEKLY limits while both roles sat parked: these are
    rolling session windows, not exhausted quotas. Measured — backend capped
    13:03Z, probed 16:10Z, came back immediately. 6h is still the ladder's
    top rung for a provider that keeps refusing; see the escalation test."""
    assert pl.cooldown_for(matched) == minutes * 60


def test_repeated_refusals_escalate_but_a_clean_run_resets(tmp_path):
    """The ladder self-calibrates: park briefly, probe, and only lengthen the
    park if the provider refuses again. A probe costs zero tokens — the gate
    suppresses before invoking — so guessing the window is unnecessary."""
    now = 1_000_000.0
    expected = [45 * 60, 90 * 60, 3 * 3600, 6 * 3600, 6 * 3600]
    for want in expected:
        pl.mark(tmp_path, "backend", matched="You've hit your session limit",
                now=now)
        marker = json.loads(pl.marker_path(tmp_path, "backend").read_text())
        assert marker["cooldown_seconds"] == want, expected
        # Refused again right after the park ended: the window had not cleared.
        now += want + 60

    # A role that worked normally for a while starts the ladder over, so one
    # bad afternoon cannot keep it on 6h parks for the rest of the run.
    now += 2 * 3600
    pl.mark(tmp_path, "backend", matched="You've hit your session limit",
            now=now)
    assert json.loads(
        pl.marker_path(tmp_path, "backend").read_text()
    )["cooldown_seconds"] == 45 * 60


def test_a_transient_blip_never_escalates(tmp_path):
    """L-25 still holds inside L-30: an overload is a capacity blip, not a
    limit, so repeated ones must not walk the ladder up to six hours."""
    now = 1_000_000.0
    for _ in range(4):
        pl.mark(tmp_path, "frontend", matched="429 engine is overloaded",
                now=now)
        assert json.loads(
            pl.marker_path(tmp_path, "frontend").read_text()
        )["cooldown_seconds"] == pl.TRANSIENT_COOLDOWN_SECONDS
        now += pl.TRANSIENT_COOLDOWN_SECONDS + 30


def test_escalation_state_survives_marker_expiry(tmp_path):
    """The marker is deleted on expiry; if the streak lived only there, the
    ladder would reset every park and never escalate."""
    now = 1_000_000.0
    pl.mark(tmp_path, "pm", matched="quota exceeded", now=now)
    assert pl.active(tmp_path, "pm", now=now + 45 * 60 + 1) is None
    assert not pl.marker_path(tmp_path, "pm").exists()

    pl.mark(tmp_path, "pm", matched="quota exceeded", now=now + 45 * 60 + 60)
    assert json.loads(
        pl.marker_path(tmp_path, "pm").read_text()
    )["cooldown_seconds"] == 90 * 60


def test_mark_applies_the_proportional_cooldown(tmp_path):
    now = 1_000_000.0
    pl.mark(tmp_path, "frontend", matched="429 engine is overloaded", now=now)
    live = pl.active(tmp_path, "frontend", now=now + 1)
    assert live["cooldown_seconds"] == pl.TRANSIENT_COOLDOWN_SECONDS
    assert pl.active(tmp_path, "frontend", now=now + 301) is None

    # A first quota refusal now parks for the ladder's FIRST rung, not the
    # flat 6h this originally asserted (L-30). The distinction the L-25 test
    # was written to protect still holds and is what matters here: a
    # transient blip is parked for minutes, a limit for substantially longer,
    # and the two are never conflated.
    pl.mark(tmp_path, "pm", matched="quota exceeded", now=now)
    parked = pl.active(tmp_path, "pm", now=now + 301)["cooldown_seconds"]
    assert parked == pl.ESCALATING_COOLDOWNS[0]
    assert parked > pl.TRANSIENT_COOLDOWN_SECONDS
    assert pl.ESCALATING_COOLDOWNS[-1] == pl.DEFAULT_COOLDOWN_SECONDS
