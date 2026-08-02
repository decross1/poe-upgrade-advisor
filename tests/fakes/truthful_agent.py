#!/usr/bin/env python3
"""Fake executor whose completion claim is TRUE by construction: it creates
a real commit on a real task branch in its worktree (cwd), pushes it to
origin, and writes a result naming the actual SHA and branch. The CC-2
proofs must pass this one — verification that refuses honest work is as
broken as verification that acks fabricated work."""
import json
import os
import subprocess
import sys
from pathlib import Path


def _git(*args: str) -> str:
    p = subprocess.run(["git", *args], capture_output=True, text=True,
                       timeout=60)
    if p.returncode != 0:
        raise SystemExit(f"truthful_agent git {args} failed: {p.stderr}")
    return p.stdout.strip()


def main() -> int:
    ctx = json.loads(Path(sys.argv[1]).read_text())
    counter = os.environ.get("COUNTER_FILE")
    if counter:
        with open(counter, "a") as f:
            f.write("invoked\n")
    branch = os.environ.get("TRUTHFUL_BRANCH", "task/TASK-7-S1")
    _git("checkout", "-q", "-b", branch)
    Path("agent-work.txt").write_text("real work, really committed\n")
    _git("add", "agent-work.txt")
    _git("commit", "-q", "-m", "real work")
    sha = _git("rev-parse", "HEAD")
    _git("push", "-q", "origin", branch)
    Path(ctx["result_path"]).write_text(json.dumps({
        "schema_version": "1.0",
        "run_id": ctx["run_id"],
        "task_id": ctx["message"]["task_id"],
        "status": "completed",
        "summary": "did real work on a real branch and pushed it",
        "commit_sha": sha,
        "pushed": True,
        "branch": branch,
        "acceptance_criteria": [
            {"id": "AC1", "status": "passed", "evidence": "agent-work.txt"},
        ],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
