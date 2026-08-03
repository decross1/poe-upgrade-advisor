#!/usr/bin/env python3
"""Budget Governor v0 — the deterministic spend firewall (ARCHITECTURE.md §Failure machinery).

Consulted by the postmaster before every agent invocation. Enforces:
  - per-task lifetime invocation caps (per role)
  - per-day per-role caps
  - exponential backoff after failures
  - circuit breaker: N consecutive failures on a task -> dead-letter + needs-redesign

Also provides a stall watchdog CLI:
  python budget_governor.py watchdog --repo /path/to/repo
finds tasks with recent invocations but no new commits and parks them.
"""
from __future__ import annotations
import argparse, sqlite3, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agents.interfaces.policy import load_policy  # noqa: E402


class Governor:
    def __init__(self, policy_path: Path, ledger_path: Path, *, read_only: bool = False):
        # Merged view of policy.yaml (Lane A keys) + run_policy.yaml (Lane B:
        # per_day_max, daily_reset_hour_utc since pm's atomic move 7d95d79).
        # load_policy raises on a key defined in both files, so the lane
        # boundary stays a test failure rather than a silent overwrite.
        self.policy = load_policy(Path(policy_path).parent)
        self.read_only = read_only
        ledger_path = Path(ledger_path)
        if read_only:
            if ledger_path.is_file():
                uri = f"{ledger_path.resolve().as_uri()}?mode=ro&immutable=1"
                self.db = sqlite3.connect(uri, uri=True)
            else:
                self.db = None
        else:
            self.db = sqlite3.connect(ledger_path)
            self.db.execute(
                """CREATE TABLE IF NOT EXISTS ledger (
                     ts REAL, role TEXT, task_id TEXT, success INTEGER)"""
            )
            self.db.commit()
        self.repo = Path(policy_path).resolve().parents[2]  # repo root
        cb = self.policy.get("circuit_breaker_consecutive_failures", 0)
        if cb > 10:
            import sys
            print(f"WARNING: circuit_breaker_consecutive_failures={cb} "
                  f"exceeds the LIMIT 10 window in _consecutive_failures — "
                  f"the breaker can never trip at this setting",
                  file=sys.stderr)

    # ------------------------------------------------------------ queries
    def _day_start(self) -> float:
        now = datetime.now(timezone.utc)
        rs = now.replace(hour=self.policy.get("daily_reset_hour_utc", 4),
                         minute=0, second=0, microsecond=0)
        if now < rs:
            rs = rs.replace(day=rs.day)  # today’s reset already covers; else subtract a day
            rs = rs.fromtimestamp(rs.timestamp() - 86400, tz=timezone.utc)
        return rs.timestamp()

    def _count(self, q: str, args: tuple) -> int:
        if self.db is None:
            return 0
        return self.db.execute(q, args).fetchone()[0]

    def _consecutive_failures(self, role: str, task_id: str) -> int:
        # LIMIT 10 caps the observable streak: a breaker threshold above 10
        # can NEVER trip (12 straight failures count as 10). Pinned in the
        # W1-1 characterisation suite; __init__ warns when a policy crosses
        # the coupling. W2-4's anti-loop controller is the deeper defence.
        rows = [] if self.db is None else self.db.execute(
            "SELECT success FROM ledger WHERE role=? AND task_id=? ORDER BY ts DESC LIMIT 10",
            (role, task_id)).fetchall()
        n = 0
        for (s,) in rows:
            if s: break
            n += 1
        return n

    def _last_failure_ts(self, role: str, task_id: str) -> float | None:
        if self.db is None:
            return None
        r = self.db.execute(
            "SELECT ts FROM ledger WHERE role=? AND task_id=? AND success=0 ORDER BY ts DESC LIMIT 1",
            (role, task_id)).fetchone()
        return r[0] if r else None

    # ------------------------------------------------------------ decisions
    def allow(self, role: str, task_id: str) -> tuple[bool, str]:
        # ORG is deliberately NOT exempt. 16 of 57 commits were org-plumbing,
        # and the measured 2026-07-27 cascade ran under task_id=ORG-adjacent
        # heartbeats: unbounded org chatter is the failure mode, not an edge
        # case. ORG's caps come from the same per-task machinery; its tier
        # budgets live in execution_classes.org (policy.yaml).
        p = self.policy
        used = self._count(
            "SELECT COUNT(*) FROM ledger WHERE role=? AND task_id=?", (role, task_id))
        if used >= p["per_task_max_invocations"]:
            self._dead_letter(role, task_id, f"per-task cap {used} reached")
            return False, "per-task cap"
        cf = self._consecutive_failures(role, task_id)
        if cf >= p["circuit_breaker_consecutive_failures"]:
            self._dead_letter(role, task_id, f"{cf} consecutive failures")
            return False, "circuit breaker tripped"
        if cf > 0:
            wait = min(p["backoff"]["base_minutes"] * (2 ** (cf - 1)),
                       p["backoff"]["max_minutes"]) * 60
            last = self._last_failure_ts(role, task_id) or 0
            if time.time() - last < wait:
                return False, f"backoff {int(wait - (time.time()-last))}s remaining"
        today = self._count(
            "SELECT COUNT(*) FROM ledger WHERE role=? AND ts>=?", (role, self._day_start()))
        if today >= p["per_day_max"][role]:
            return False, "daily cap"
        return True, "ok"

    def record(self, role: str, task_id: str, success: bool) -> None:
        if self.read_only:
            raise OSError("read-only governor cannot record")
        self.db.execute("INSERT INTO ledger VALUES (?,?,?,?)",
                        (time.time(), role, task_id, int(success)))
        self.db.commit()

    # ------------------------------------------------------------ actions
    def _dead_letter(self, role: str, task_id: str, reason: str) -> None:
        if self.read_only:
            return
        dl = self.repo / "tasks" / "dead_letter" / f"{task_id}.md"
        if dl.exists():
            return
        # tasks/dead_letter/ is untracked, so a fresh (fan) worktree does not
        # have it — without this the first breaker/cap trip in a throwaway
        # checkout raises FileNotFoundError instead of parking the task.
        dl.parent.mkdir(parents=True, exist_ok=True)
        dl.write_text(
            f"# Dead-letter: {task_id}\n\n- role: {role}\n- reason: {reason}\n"
            f"- parked: {datetime.now(timezone.utc).isoformat()}\n\n"
            "PM: re-triage fresh — decompose, rewrite acceptance criteria, or reject.\n")
        subprocess.run(  # best-effort label; requires gh auth in env
            ["gh", "issue", "edit", task_id.replace("TASK-", ""),
             "--add-label", "needs-redesign"],
            cwd=self.repo, capture_output=True)


# ---------------------------------------------------------------- watchdog
def watchdog(repo: Path, ledger: Path, hours: int = 12) -> None:
    """Park tasks burning invocations without advancing commits."""
    db = sqlite3.connect(ledger)
    since = time.time() - hours * 3600
    rows = db.execute(
        "SELECT role, task_id, COUNT(*) FROM ledger WHERE ts>=? AND task_id!='ORG' "
        "GROUP BY role, task_id HAVING COUNT(*)>=3", (since,)).fetchall()
    for role, task_id, n in rows:
        log = subprocess.run(
            ["git", "log", "--all", "--oneline", f"--since={hours} hours ago",
             f"--grep={task_id}:"], cwd=repo, capture_output=True, text=True)
        if not log.stdout.strip():
            g = Governor(repo / "agents" / "governor" / "policy.yaml", ledger)
            g._dead_letter(role, task_id, f"{n} invocations in {hours}h with zero commits")
            print(f"parked {task_id} ({role}): stall")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    w = sub.add_parser("watchdog")
    w.add_argument("--repo", required=True)
    w.add_argument("--hours", type=int, default=12)
    a = ap.parse_args()
    if a.cmd == "watchdog":
        watchdog(Path(a.repo),
                 Path(a.repo) / "agents" / "governor" / "ledger.sqlite3", a.hours)
