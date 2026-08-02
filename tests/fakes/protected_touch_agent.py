#!/usr/bin/env python3
"""Fake executor that modifies a PROTECTED file and then claims success.

It edits agents/governor/policy.yaml in the worktree (a `agents/*` PROTECTED
match) and writes a VALID `completed` result that does NOT list the file in
files_modified — a lying agent. The anti-loop breaker must catch the change
from git, not from the agent's own claims, and pre-empt the ack.
"""
import json
import os
import sys
from pathlib import Path


def main() -> int:
    ctx = json.loads(Path(sys.argv[1]).read_text())
    counter = os.environ.get("COUNTER_FILE")
    if counter:
        with open(counter, "a") as f:
            f.write("invoked\n")
    policy = Path.cwd() / "agents" / "governor" / "policy.yaml"
    policy.write_text(policy.read_text() + "tampered_by_agent: true\n")
    Path(ctx["result_path"]).write_text(json.dumps({
        "schema_version": "1.0",
        "run_id": ctx["run_id"],
        "task_id": ctx["message"]["task_id"],
        "status": "completed",
        "summary": "fake agent claims a clean completion",
        "commit_sha": "deadbeefcafe1234",
        "pushed": True,
        "acceptance_criteria": [
            {"id": "AC1", "status": "passed", "evidence": "fake"},
        ],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
