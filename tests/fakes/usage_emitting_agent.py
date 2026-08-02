#!/usr/bin/env python3
"""Fake executor for the W2-1 capture seam: prints a realistic claude
`--output-format stream-json` transcript (JSONL) on stdout — ending with the
result event that carries the usage object — AND writes a valid `completed`
result file. Proves usage capture and the result contract coexist: stdout is
machine-readable while `.agent-result.json` stays the only ack authority.
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
    # Realistic stream-json shape ([E] field names — observed, not documented).
    print(json.dumps({"type": "system", "subtype": "init",
                      "session_id": "sess-fake-1", "model": "claude-x"}))
    print(json.dumps({"type": "assistant", "message": {
        "role": "assistant", "content": [{"type": "text", "text": "done"}]}}))
    print(json.dumps({
        "type": "result", "subtype": "success", "is_error": False,
        "duration_ms": 8214, "num_turns": 5, "session_id": "sess-fake-1",
        "total_cost_usd": 0.0421,
        "usage": {"input_tokens": 51234, "output_tokens": 2211,
                  "cache_read_input_tokens": 40960},
    }))
    Path(ctx["result_path"]).write_text(json.dumps({
        "schema_version": "1.0",
        "run_id": ctx["run_id"],
        "task_id": ctx["message"]["task_id"],
        "status": "completed",
        "summary": "fake agent completed while emitting stream-json usage",
        "commit_sha": "deadbeefcafe1234",
        "pushed": True,
        "acceptance_criteria": [
            {"id": "AC1", "status": "passed", "evidence": "fake"},
        ],
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
