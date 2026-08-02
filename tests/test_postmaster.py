from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path

from agents.postmaster import postmaster


class RecordingGovernor:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.allow_calls: list[tuple[str, str]] = []
        self.records: list[tuple[str, str, bool]] = []

    def allow(self, role: str, task_id: str) -> tuple[bool, str]:
        self.allow_calls.append((role, task_id))
        return self.allowed, "ok" if self.allowed else "test block"

    def record(self, role: str, task_id: str, success: bool) -> None:
        self.records.append((role, task_id, success))


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "mailroom"
    (root / "messages").mkdir(parents=True)
    (root / "cursors").mkdir()
    return root


def _state(tmp_path: Path) -> postmaster.State:
    return postmaster.State(tmp_path / "postmaster.sqlite3")


def _message(message_id: str = "11111111-1111-4111-8111-111111111111") -> dict:
    return {
        "schema_version": "1.0",
        "message_id": message_id,
        "idempotency_key": "TASK-5:STATUS:test-message",
        "task_id": "TASK-5",
        "from_role": "pm",
        "to_role": "backend",
        "intent": "STATUS",
        "hop_count": 0,
        "max_hops": 6,
        "refs": {"issue": 5},
        "body_markdown": "Exercise the ledger daemon.",
    }


def _write_message(root: Path, payload: dict) -> None:
    (root / "messages" / f"test-{payload['message_id']}.json").write_text(
        json.dumps(payload)
    )


def _counter_agent(tmp_path: Path) -> tuple[Path, Path]:
    counter = tmp_path / "agent-runs.txt"
    script = tmp_path / "counter_agent.py"
    script.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        f"counter = Path({str(counter)!r})\n"
        "counter.write_text(counter.read_text() + 'run\\n' if counter.exists() else 'run\\n')\n"
        "assert 'INBOUND MESSAGE' in Path(sys.argv[1]).read_text()\n"
    )
    return script, counter


def _config(tmp_path: Path, script: Path, *, heartbeat: bool = False) -> dict:
    return {
        "heartbeat_seconds": 1800,
        "agent_timeout_seconds": 10,
        "roles": {
            "backend": {
                "worktree": str(tmp_path),
                "heartbeat": heartbeat,
                "cli_command": (
                    f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} "
                    "{prompt_file}"
                ),
            }
        },
    }


def test_ledger_message_is_governed_spawned_acked_and_deduplicated(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    payload = _message()
    _write_message(root, payload)
    script, counter = _counter_agent(tmp_path)
    cfg = _config(tmp_path, script)
    state = _state(tmp_path)
    governor = RecordingGovernor()

    postmaster.process_role(cfg, "backend", state, governor, root)
    postmaster.process_role(cfg, "backend", state, governor, root)

    assert counter.read_text().splitlines() == ["run"]
    assert governor.allow_calls == [("backend", "TASK-5")]
    assert governor.records == [("backend", "TASK-5", True)]
    assert postmaster.acked_ids(root, "backend") == {payload["message_id"]}
    assert state.seen(payload["idempotency_key"])


def test_governor_block_keeps_message_unacked(tmp_path: Path) -> None:
    root = _root(tmp_path)
    payload = _message()
    _write_message(root, payload)
    script, counter = _counter_agent(tmp_path)
    state = _state(tmp_path)
    governor = RecordingGovernor(allowed=False)

    postmaster.process_role(
        _config(tmp_path, script), "backend", state, governor, root
    )

    assert not counter.exists()
    assert postmaster.acked_ids(root, "backend") == set()
    assert not state.seen(payload["idempotency_key"])
    assert governor.records == []


def test_shared_halt_prevents_poll_and_spawn(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _write_message(root, _message())
    (root / "HALT").touch()
    script, counter = _counter_agent(tmp_path)
    governor = RecordingGovernor()

    postmaster.process_role(
        _config(tmp_path, script), "backend", _state(tmp_path), governor, root
    )

    assert not counter.exists()
    assert governor.allow_calls == []


def test_headless_heartbeat_spawn_can_reply_through_ledger(
    tmp_path: Path,
) -> None:
    root = _root(tmp_path)
    ledger_script = Path(postmaster.__file__).with_name("ledger.py")
    fake_agent = tmp_path / "reply_agent.py"
    fake_agent.write_text(
        "from pathlib import Path\n"
        "import subprocess\n"
        "import sys\n"
        "prompt = Path(sys.argv[1]).read_text()\n"
        "assert 'Heartbeat: check your assigned issues' in prompt\n"
        f"subprocess.run([{sys.executable!r}, {str(ledger_script)!r}, 'send', "
        "'--from-role', 'backend', '--to', 'pm', '--intent', 'SYNC', "
        "'--task', 'ORG', '--body', 'Heartbeat complete.', "
        "'--hops', '1', '--idempotency', 'heartbeat-smoke-reply'], check=True)\n"
    )
    governor = RecordingGovernor()

    postmaster.process_role(
        _config(tmp_path, fake_agent, heartbeat=True),
        "backend",
        _state(tmp_path),
        governor,
        root,
    )

    replies = [
        message
        for message in postmaster.all_messages(root)
        if message["to_role"] == "pm"
    ]
    assert len(replies) == 1
    assert replies[0]["body_markdown"] == "Heartbeat complete."
    assert replies[0]["hop_count"] == 1
    assert governor.records == [("backend", "ORG", True)]
    assert (root / "runs" / "backend-last-run.log").exists()
