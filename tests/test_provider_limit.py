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
    "Please try again in 12 minutes",
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


def test_dispatch_active_limit_suppresses_before_message_load(
        tmp_path, monkeypatch):
    """An active role cap is actionable before the message is loaded.

    The provider-limit gate deliberately precedes message parsing, so it cannot
    use a task ID that is only assigned after ``find_message`` succeeds.
    """
    mailroom = tmp_path / "mailroom"
    monkeypatch.setenv("POB_LEDGER_DIR", str(mailroom))
    pl.mark(mailroom, "backend", matched="session limit reached", cooldown=600)

    from agents.dispatch import dispatch

    outcome = dispatch("backend", "not-loaded", tmp_path, dry_run=True)

    assert outcome.decision == "suppressed_preflight"
    assert outcome.message_id == "not-loaded"
    assert outcome.task_id is None
