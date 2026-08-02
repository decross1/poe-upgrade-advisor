"""Characterisation tests for agents/governor/budget_governor.py.

These pin the module's behaviour TODAY, including behaviour that is slated to
change (the ORG exemption, see W1-2) and behaviour that merely looks odd (the
dead no-op in _day_start). They never modify production code.

All filesystem work is under tmp_path; subprocess is always replaced with a
recorder so no gh/git process is ever spawned by the code under test.
"""
from __future__ import annotations

import sqlite3
import time as real_time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from agents.governor import budget_governor

UTC = timezone.utc


# ------------------------------------------------------------------ helpers
def _ts(*args: int) -> float:
    return datetime(*args, tzinfo=UTC).timestamp()


def _write_policy(root: Path, **overrides) -> Path:
    policy = {
        "per_task_max_invocations": 5,
        "circuit_breaker_consecutive_failures": 3,
        "backoff": {"base_minutes": 10, "max_minutes": 60},
        "per_day_max": {"backend": 10, "pm": 10},
        "daily_reset_hour_utc": 4,
    }
    policy.update(overrides)
    policy = {k: v for k, v in policy.items() if v is not None}
    path = root / "agents" / "governor" / "policy.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(policy))
    (root / "tasks" / "dead_letter").mkdir(parents=True, exist_ok=True)
    return path


def _governor(tmp_path: Path, **overrides) -> budget_governor.Governor:
    policy_path = _write_policy(tmp_path, **overrides)
    return budget_governor.Governor(policy_path, tmp_path / "ledger.sqlite3")


class _Clock:
    """Stands in for the whole `time` module inside budget_governor."""

    def __init__(self, now: float) -> None:
        self.now = now

    def time(self) -> float:
        return self.now


def _freeze_clock(monkeypatch: pytest.MonkeyPatch, now: float) -> _Clock:
    clock = _Clock(now)
    monkeypatch.setattr(budget_governor, "time", clock)
    return clock


def _freeze_now(monkeypatch: pytest.MonkeyPatch, instant: datetime) -> None:
    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is UTC  # the module always asks for UTC
            return instant

    monkeypatch.setattr(budget_governor, "datetime", _FrozenDatetime)


class _FakeSubprocess:
    """Stands in for the `subprocess` module; records calls, spawns nothing."""

    def __init__(self) -> None:
        self.stdout = ""
        self.calls: list[tuple[list[str], dict]] = []

    def run(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        return SimpleNamespace(stdout=self.stdout, stderr="", returncode=0)


@pytest.fixture(autouse=True)
def fake_subprocess(monkeypatch: pytest.MonkeyPatch) -> _FakeSubprocess:
    fake = _FakeSubprocess()
    monkeypatch.setattr(budget_governor, "subprocess", fake)
    return fake


def _dead_letters(tmp_path: Path) -> list[str]:
    return sorted(p.name for p in (tmp_path / "tasks" / "dead_letter").iterdir())


# ------------------------------------------------------------------ __init__
def test_repo_root_is_two_parents_above_policy_dir(tmp_path: Path) -> None:
    g = _governor(tmp_path)
    assert g.repo == tmp_path.resolve()


def test_init_creates_ledger_table(tmp_path: Path) -> None:
    g = _governor(tmp_path)
    assert g.db.execute("SELECT COUNT(*) FROM ledger").fetchone() == (0,)


# ----------------------------------------------------------------- _day_start
# The PM flagged line 39 (`rs = rs.replace(day=rs.day)`): it is a dead no-op,
# but the arithmetic that follows — fromtimestamp(rs.timestamp() - 86400) —
# is functionally CORRECT in UTC, including across month boundaries. The
# four tests below pin the concrete expected instants.
def test_day_start_after_reset_hour_is_today_at_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = _governor(tmp_path)
    _freeze_now(monkeypatch, datetime(2026, 8, 15, 10, 30, tzinfo=UTC))
    assert g._day_start() == _ts(2026, 8, 15, 4)


def test_day_start_before_reset_hour_is_yesterday_at_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = _governor(tmp_path)
    _freeze_now(monkeypatch, datetime(2026, 8, 15, 3, 59, tzinfo=UTC))
    assert g._day_start() == _ts(2026, 8, 14, 4)


def test_day_start_month_boundary_aug_1_maps_to_jul_31(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = _governor(tmp_path)
    _freeze_now(monkeypatch, datetime(2026, 8, 1, 2, 0, tzinfo=UTC))
    # subtracting 86400 s handles the month rollover correctly
    assert g._day_start() == _ts(2026, 7, 31, 4)


def test_day_start_at_exact_reset_instant_is_today(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = _governor(tmp_path)
    _freeze_now(monkeypatch, datetime(2026, 8, 15, 4, 0, tzinfo=UTC))
    # now < rs is False at the exact reset instant -> today's reset
    assert g._day_start() == _ts(2026, 8, 15, 4)


def test_day_start_defaults_to_reset_hour_4_when_policy_omits_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    g = _governor(tmp_path, daily_reset_hour_utc=None)
    _freeze_now(monkeypatch, datetime(2026, 8, 15, 12, 0, tzinfo=UTC))
    assert g._day_start() == _ts(2026, 8, 15, 4)


# --------------------------------------------------- _consecutive_failures
def test_consecutive_failures_counts_newest_first_until_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = _freeze_clock(monkeypatch, 1_000_000.0)
    g = _governor(tmp_path)
    for i, success in enumerate([False, True, False, False]):  # oldest -> newest
        clock.now = 1_000_000.0 + i
        g.record("backend", "TASK-2", success)
    # newest-first: F, F, then the success breaks the count
    assert g._consecutive_failures("backend", "TASK-2") == 2


def test_consecutive_failures_zero_when_newest_row_is_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = _freeze_clock(monkeypatch, 1_000_000.0)
    g = _governor(tmp_path)
    for i, success in enumerate([False, False, True]):
        clock.now = 1_000_000.0 + i
        g.record("backend", "TASK-2", success)
    assert g._consecutive_failures("backend", "TASK-2") == 0


def test_consecutive_failures_window_is_capped_at_10(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = _freeze_clock(monkeypatch, 1_000_000.0)
    g = _governor(tmp_path)
    for i in range(12):
        clock.now = 1_000_000.0 + i
        g.record("backend", "TASK-2", False)
    # 12 straight failures, but LIMIT 10 caps the count
    assert g._consecutive_failures("backend", "TASK-2") == 10


def test_last_failure_ts_is_none_without_any_failure(tmp_path: Path) -> None:
    g = _governor(tmp_path)
    g.record("backend", "TASK-1", True)
    assert g._last_failure_ts("backend", "TASK-1") is None


# ------------------------------------------------------------------ record
def test_record_inserts_ts_role_task_and_success_as_int(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _freeze_clock(monkeypatch, 123.5)
    g = _governor(tmp_path)
    g.record("backend", "TASK-1", True)
    g.record("pm", "ORG", False)
    rows = g.db.execute("SELECT * FROM ledger ORDER BY role").fetchall()
    assert rows == [(123.5, "backend", "TASK-1", 1), (123.5, "pm", "ORG", 0)]


# ------------------------------------------------------------------- allow
def test_org_is_subject_to_per_task_cap_breaker_and_backoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_subprocess: _FakeSubprocess,
) -> None:
    # W1-2 flipped the pinned W1-1 behaviour (see d897de2 for the before-
    # state): the `if task_id != "ORG":` exemption is deleted. 16 of 57
    # commits were org-plumbing and the measured 2026-07-27 cascade was
    # org-adjacent heartbeat traffic — unbounded ORG chatter is the failure
    # mode. 6 straight ORG failures now trip the breaker (3) exactly like
    # any TASK id, and dead-letter with the needs-redesign label attempt.
    clock = _freeze_clock(monkeypatch, _ts(2026, 8, 15, 5, 0))
    _freeze_now(monkeypatch, datetime(2026, 8, 15, 12, 0, tzinfo=UTC))
    g = _governor(tmp_path, per_day_max={"backend": 100, "pm": 10})
    for i in range(6):
        clock.now = _ts(2026, 8, 15, 5, 0) + i
        g.record("backend", "ORG", False)

    allowed, reason = g.allow("backend", "ORG")
    assert allowed is False
    assert reason in {"per-task cap", "circuit breaker tripped"}
    assert _dead_letters(tmp_path) == ["ORG.md"]
    assert len(fake_subprocess.calls) == 1  # gh label attempt, stubbed


def test_org_is_subject_to_the_per_task_cap_specifically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_subprocess: _FakeSubprocess,
) -> None:
    """The breaker must not be able to satisfy this test on the cap's behalf.

    PM's W1-2 mutation probe restored `used = 0 if task_id == "ORG"` (ORG
    exempt from the per-task cap ONLY) and the whole suite passed: the
    flipped ORG test recorded 6 failures, so the breaker (3) always fired
    first and its reason satisfied a disjunctive assertion. Here the cap is
    driven with SUCCESSES so `_consecutive_failures` stays 0 and nothing but
    the cap can produce the denial — asserted as the exact tuple.
    """
    g = _governor(tmp_path, per_day_max={"backend": 1000, "pm": 10})
    for _ in range(5):  # per_task_max_invocations
        g.record("backend", "ORG", True)

    assert g.allow("backend", "ORG") == (False, "per-task cap")
    assert _dead_letters(tmp_path) == ["ORG.md"]
    assert len(fake_subprocess.calls) == 1


def test_org_is_still_subject_to_daily_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Daily cap applied to ORG before W1-2 and still does; since W1-2 it is
    # one of four checks (per-task cap, breaker, backoff, daily) rather than
    # the only one.
    clock = _freeze_clock(monkeypatch, _ts(2026, 8, 15, 5, 0))
    _freeze_now(monkeypatch, datetime(2026, 8, 15, 12, 0, tzinfo=UTC))
    g = _governor(tmp_path, per_day_max={"backend": 2, "pm": 10})
    for i in range(2):
        clock.now = _ts(2026, 8, 15, 5, 0) + i
        g.record("backend", "ORG", True)
    assert g.allow("backend", "ORG") == (False, "daily cap")
    assert _dead_letters(tmp_path) == []  # daily cap never dead-letters


def test_per_task_cap_counts_successes_and_failures_and_dead_letters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_subprocess: _FakeSubprocess,
) -> None:
    clock = _freeze_clock(monkeypatch, 1_000_000.0)
    g = _governor(tmp_path)  # per_task_max_invocations = 5
    # 3 successes + 2 failures: ALL rows count toward the lifetime cap
    for i, success in enumerate([True, True, True, False, False]):
        clock.now = 1_000_000.0 + i
        g.record("backend", "TASK-7", success)

    assert g.allow("backend", "TASK-7") == (False, "per-task cap")

    dl = tmp_path / "tasks" / "dead_letter" / "TASK-7.md"
    body = dl.read_text()
    assert "# Dead-letter: TASK-7" in body
    assert "- role: backend" in body
    assert "- reason: per-task cap 5 reached" in body
    # gh is invoked with the issue number derived by stripping "TASK-"
    assert len(fake_subprocess.calls) == 1
    argv, kwargs = fake_subprocess.calls[0]
    assert argv == ["gh", "issue", "edit", "7", "--add-label", "needs-redesign"]
    assert kwargs == {"cwd": tmp_path.resolve(), "capture_output": True}


def test_dead_letter_is_idempotent_second_call_skips_gh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_subprocess: _FakeSubprocess,
) -> None:
    clock = _freeze_clock(monkeypatch, 1_000_000.0)
    g = _governor(tmp_path)
    for i in range(5):
        clock.now = 1_000_000.0 + i
        g.record("backend", "TASK-7", True)

    assert g.allow("backend", "TASK-7") == (False, "per-task cap")
    body = (tmp_path / "tasks" / "dead_letter" / "TASK-7.md").read_text()

    assert g.allow("backend", "TASK-7") == (False, "per-task cap")
    assert (tmp_path / "tasks" / "dead_letter" / "TASK-7.md").read_text() == body
    assert len(fake_subprocess.calls) == 1  # gh not re-invoked


def test_circuit_breaker_trips_at_threshold_and_dead_letters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_subprocess: _FakeSubprocess,
) -> None:
    clock = _freeze_clock(monkeypatch, 1_000_000.0)
    g = _governor(tmp_path)  # breaker threshold = 3, cap = 5
    for i in range(3):
        clock.now = 1_000_000.0 + i
        g.record("backend", "TASK-8", False)

    assert g.allow("backend", "TASK-8") == (False, "circuit breaker tripped")
    body = (tmp_path / "tasks" / "dead_letter" / "TASK-8.md").read_text()
    assert "- reason: 3 consecutive failures" in body
    assert fake_subprocess.calls[0][0] == [
        "gh", "issue", "edit", "8", "--add-label", "needs-redesign",
    ]


def test_backoff_denies_with_countdown_then_allows_after_wait(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t0 = _ts(2026, 8, 15, 10, 0)
    clock = _freeze_clock(monkeypatch, t0)
    _freeze_now(monkeypatch, datetime(2026, 8, 15, 12, 0, tzinfo=UTC))
    g = _governor(tmp_path)  # base 10 min => wait 600 s for 1 failure
    g.record("backend", "TASK-9", False)

    clock.now = t0 + 100
    assert g.allow("backend", "TASK-9") == (False, "backoff 500s remaining")

    clock.now = t0 + 600  # elapsed == wait: not strictly less, so allowed
    assert g.allow("backend", "TASK-9") == (True, "ok")
    assert _dead_letters(tmp_path) == []


def test_backoff_doubles_per_failure_and_caps_at_max_minutes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    t0 = _ts(2026, 8, 15, 5, 0)
    clock = _freeze_clock(monkeypatch, t0)
    _freeze_now(monkeypatch, datetime(2026, 8, 15, 12, 0, tzinfo=UTC))
    g = _governor(
        tmp_path,
        per_task_max_invocations=20,
        circuit_breaker_consecutive_failures=10,
    )
    for i in range(5):  # cf=5 => min(10 * 2**4, 60) = 60 min = 3600 s
        clock.now = t0 + i
        g.record("backend", "TASK-11", False)

    last = t0 + 4
    clock.now = last + 3599
    assert g.allow("backend", "TASK-11") == (False, "backoff 1s remaining")
    clock.now = last + 3600
    assert g.allow("backend", "TASK-11") == (True, "ok")


def test_daily_cap_counts_all_role_rows_since_day_start_including_org(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = _freeze_clock(monkeypatch, _ts(2026, 8, 15, 3, 0))
    _freeze_now(monkeypatch, datetime(2026, 8, 15, 12, 0, tzinfo=UTC))
    g = _governor(tmp_path, per_day_max={"backend": 2, "pm": 10})

    # before today's 04:00 reset — must NOT count toward the daily cap
    g.record("backend", "TASK-1", True)
    clock.now = _ts(2026, 8, 15, 5, 0)
    g.record("backend", "ORG", True)  # ORG rows DO count toward the daily cap

    clock.now = _ts(2026, 8, 15, 12, 0)
    assert g.allow("backend", "TASK-30") == (True, "ok")  # 1 of 2 used

    clock.now = _ts(2026, 8, 15, 6, 0)
    g.record("backend", "TASK-2", False)  # any task, same role: counts

    clock.now = _ts(2026, 8, 15, 12, 0)
    assert g.allow("backend", "TASK-30") == (False, "daily cap")
    # the cap is per-role: pm is untouched
    assert g.allow("pm", "TASK-30") == (True, "ok")
    assert _dead_letters(tmp_path) == []  # daily cap never dead-letters


def test_allow_raises_keyerror_for_role_missing_from_per_day_max(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # pins current behaviour; see W1-2 / REQUEST — an unconfigured role
    # crashes the governor instead of being denied or defaulted.
    _freeze_now(monkeypatch, datetime(2026, 8, 15, 12, 0, tzinfo=UTC))
    g = _governor(tmp_path)
    with pytest.raises(KeyError):
        g.allow("unknown-role", "ORG")


# ---------------------------------------------------------------- watchdog
def _seed_watchdog_ledger(tmp_path: Path) -> Path:
    ledger = tmp_path / "ledger.sqlite3"
    db = sqlite3.connect(ledger)
    db.execute(
        "CREATE TABLE ledger (ts REAL, role TEXT, task_id TEXT, success INTEGER)"
    )
    now = real_time.time()
    rows = [
        # TASK-3: 3 invocations in window -> watchdog candidate
        (now - 100, "backend", "TASK-3", 0),
        (now - 200, "backend", "TASK-3", 1),
        (now - 300, "backend", "TASK-3", 0),
        # ORG: 4 in window but excluded by the SQL (task_id != 'ORG')
        (now - 50, "backend", "ORG", 1),
        (now - 51, "backend", "ORG", 1),
        (now - 52, "backend", "ORG", 0),
        (now - 53, "backend", "ORG", 1),
        # TASK-4: only 2 in window, below the HAVING >= 3 threshold
        (now - 60, "backend", "TASK-4", 0),
        (now - 61, "backend", "TASK-4", 0),
        # TASK-5: 3 rows but all outside the 12 h window
        (now - 13 * 3600, "backend", "TASK-5", 0),
        (now - 14 * 3600, "backend", "TASK-5", 0),
        (now - 15 * 3600, "backend", "TASK-5", 0),
    ]
    db.executemany("INSERT INTO ledger VALUES (?,?,?,?)", rows)
    db.commit()
    db.close()
    return ledger


def test_watchdog_parks_stalled_task_and_ignores_org_and_low_counts(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
    capsys: pytest.CaptureFixture,
) -> None:
    _write_policy(tmp_path)
    ledger = _seed_watchdog_ledger(tmp_path)
    fake_subprocess.stdout = ""  # git log finds no commits -> stall

    budget_governor.watchdog(tmp_path, ledger, hours=12)

    assert _dead_letters(tmp_path) == ["TASK-3.md"]
    body = (tmp_path / "tasks" / "dead_letter" / "TASK-3.md").read_text()
    assert "- reason: 3 invocations in 12h with zero commits" in body
    assert capsys.readouterr().out == "parked TASK-3 (backend): stall\n"
    # exactly one git-log probe (TASK-3 only), then the gh label call
    argvs = [argv for argv, _ in fake_subprocess.calls]
    assert argvs == [
        ["git", "log", "--all", "--oneline", "--since=12 hours ago",
         "--grep=TASK-3:"],
        ["gh", "issue", "edit", "3", "--add-label", "needs-redesign"],
    ]
    git_kwargs = fake_subprocess.calls[0][1]
    assert git_kwargs == {"cwd": tmp_path, "capture_output": True, "text": True}


def test_watchdog_leaves_task_alone_when_commits_exist(
    tmp_path: Path,
    fake_subprocess: _FakeSubprocess,
    capsys: pytest.CaptureFixture,
) -> None:
    _write_policy(tmp_path)
    ledger = _seed_watchdog_ledger(tmp_path)
    fake_subprocess.stdout = "abc1234 TASK-3: real progress\n"

    budget_governor.watchdog(tmp_path, ledger, hours=12)

    assert _dead_letters(tmp_path) == []
    assert capsys.readouterr().out == ""
    assert [argv for argv, _ in fake_subprocess.calls] == [
        ["git", "log", "--all", "--oneline", "--since=12 hours ago",
         "--grep=TASK-3:"],
    ]
