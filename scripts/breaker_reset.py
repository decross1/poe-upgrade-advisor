#!/usr/bin/env python3
"""Clear a tripped circuit breaker for one (role, task_id), auditably.

L-11 (2026-08-03, observed live). `Governor.allow` trips at
`circuit_breaker_consecutive_failures` and denies from then on: the streak in
`_consecutive_failures` is only broken by a `success` row, and a task that
cannot invoke can never produce one. The latch is deliberate — a tripped
breaker means "this task needs redesign, not another attempt" — but nothing
existed to record that the redesign HAPPENED, so a task killed by a defect in
the gate itself stayed dead after the defect was fixed. That is what happened
to pm/ORG: three refusals caused by the L-10 branch-pattern contradiction.

This is the redesign-complete signal, and it is deliberately not silent:

  * the governor ledger's schema is (ts, role, task_id, success) with nowhere
    to say WHY, so the reason goes to `mailroom/governor/admin_actions.jsonl`
    — append-only, next to the ledger it explains;
  * the ledger row it writes is marked in that log as an ADMIN RESET, not a
    task success, so anyone auditing success rates can subtract it;
  * `--reason` is required. A reset without a stated cause is the thing this
    org treats as adversarial.

Usage:
  python3 scripts/breaker_reset.py --role pm --task ORG \
      --reason "L-10 branch-pattern defect fixed at 32975c9; failures were
                caused by the gate, not the agent"
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

GOVERNOR_DB = "governor_ledger.sqlite3"
ADMIN_LOG = "admin_actions.jsonl"


def find_mailroom(start: Path) -> Path:
    for ancestor in (start, *start.parents):
        if (ancestor / "mailroom").is_dir():
            return ancestor / "mailroom"
    raise SystemExit("no mailroom/ ancestor found")


def consecutive_failures(db: sqlite3.Connection, role: str, task: str) -> int:
    rows = db.execute(
        "SELECT success FROM ledger WHERE role=? AND task_id=? "
        "ORDER BY ts DESC LIMIT 10", (role, task)).fetchall()
    n = 0
    for (s,) in rows:
        if s:
            break
        n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--role", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--reason", required=True,
                    help="why the redesign is complete; recorded durably")
    ap.add_argument("--actor", default="orchestrator")
    ap.add_argument("--mailroom", default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not a.reason.strip():
        raise SystemExit("--reason must not be empty")

    mailroom = (Path(a.mailroom) if a.mailroom
                else find_mailroom(Path(__file__).resolve().parent))
    db_path = mailroom / "governor" / GOVERNOR_DB
    if not db_path.exists():
        raise SystemExit(f"no governor ledger at {db_path}")

    db = sqlite3.connect(db_path)
    before = consecutive_failures(db, a.role, a.task)
    if before == 0:
        print(f"no failure streak for {a.role}/{a.task}; nothing to reset")
        db.close()
        return 0

    ts = time.time()
    record = {
        "ts": ts, "action": "circuit_breaker_reset", "actor": a.actor,
        "role": a.role, "task_id": a.task,
        "consecutive_failures_cleared": before, "reason": a.reason.strip(),
        "note": ("the ledger row written by this action is an ADMIN RESET, "
                 "not a task success; subtract it when computing success "
                 "rates"),
    }
    if a.dry_run:
        print(json.dumps(record, indent=2))
        db.close()
        return 0

    with (mailroom / "governor" / ADMIN_LOG).open("a") as f:
        f.write(json.dumps(record) + "\n")
    db.execute("INSERT INTO ledger (ts, role, task_id, success) VALUES (?,?,?,1)",
               (ts, a.role, a.task))
    db.commit()
    after = consecutive_failures(db, a.role, a.task)
    db.close()
    print(f"reset {a.role}/{a.task}: streak {before} -> {after}; "
          f"recorded in mailroom/governor/{ADMIN_LOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
