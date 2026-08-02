from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from scripts.check_agent_readiness import evaluate, find_mailroom

ROOT = Path(__file__).resolve().parents[1]


def _packet(task_id: str = "TASK-1") -> dict:
    return {
        "schema_version": "1.0", "task_id": task_id, "owner_role": "backend",
        "tier": "green", "objective": "Exercise readiness fixtures",
        "files_in_scope": ["server/**"], "files_out_of_scope": ["contracts/**"],
        "required_checks": ["python3 -m pytest tests -q"],
        "acceptance_criteria": [{"id": "AC-1", "text": "fixture validates"}],
        "budgets": {"max_attempts": 2, "max_files_modified": 2,
                    "max_diff_lines": 100, "max_wall_clock_seconds": 600},
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    root, mailroom = tmp_path / "repo", tmp_path / "mailroom"
    for path in (
        root / "agents/governor", root / "agents/merge_robot", root / "agents",
        root / ".github/workflows", root / "scripts", root / "tasks/packets",
        mailroom / "locks/running", mailroom / "governor", mailroom / "telemetry",
        mailroom / "messages", mailroom / "cursors",
    ):
        path.mkdir(parents=True, exist_ok=True)
    (mailroom / "HALT").touch()
    (root / "agents/governor/policy.yaml").write_text("per_task_max_invocations: 2\n")
    (root / "agents/governor/run_policy.yaml").write_text("{}\n")
    (root / "agents/dispatch.py").write_text("# deterministic dispatcher\n")
    (root / "agents/recovery.py").write_text(
        "def verify_bundle(path):\n"
        "    return (path / 'metadata.json').is_file() and (path / 'working.patch').is_file()\n"
    )
    (root / "scripts/agent_loop.sh").write_text("python3 agents/dispatch.py\n")
    (root / ".github/workflows/ci.yml").write_text(yaml.safe_dump({"jobs": {"web-test": {}, "overlay-test": {}, "coverage-floor": {}}}))
    (root / "agents/merge_robot/merge_robot.py").write_text("REQUIRED_CHECKS = {'web-test', 'overlay-test', 'coverage-floor'}\n")
    (root / "agents/merge_robot/coverage_floor.json").write_text('{"floor": 60.0}')
    (root / "tasks/packets/TASK-1.json").write_text(json.dumps(_packet()))

    worktrees = []
    for role in ("pm", "backend", "frontend"):
        wt = tmp_path / role
        wt.mkdir()
        subprocess.run(["git", "init", "-q", str(wt)], check=True)
        worktrees.append(str(wt))
    cli = tmp_path / "fake-model-cli"
    cli.write_text("#!/bin/sh\nexit 0\n")
    cli.chmod(0o755)
    state = {
        "operating_mode": "canary",
        "budget_ledger_path": str(mailroom / "governor/budget.sqlite3"),
        "telemetry_path": str(mailroom / "telemetry/invocations.jsonl"),
        "model_clis": {role: {"command": str(cli), "authenticated": True}
                       for role in ("pm", "backend", "frontend")},
        "github": {"authenticated": True, "scopes_sufficient": True},
        "worktrees": worktrees,
    }
    (mailroom / "readiness.yaml").write_text(yaml.safe_dump(state))
    return root, mailroom


def _by_name(checks):
    return {check.name: check for check in checks}


def test_default_mailroom_discovery_walks_above_worktrees(tmp_path):
    mailroom = tmp_path / "mailroom"
    root = tmp_path / "worktrees/lane-b"
    mailroom.mkdir()
    root.mkdir(parents=True)
    assert find_mailroom(root) == mailroom


def test_missing_config_fails_complete_canary_passes_and_no_model_call(tmp_path, monkeypatch):
    root, mailroom = _fixture(tmp_path)
    real_run = subprocess.run
    commands = []

    def recording_run(command, *args, **kwargs):
        commands.append(command)
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    monkeypatch.setattr("scripts.check_agent_readiness.shutil.which", lambda command: f"/bin/{command}")
    checks = evaluate(root, mailroom, "canary")
    assert not [check for check in checks if check.verdict == "fail"]
    assert all(Path(command[0]).name not in {"claude", "codex", "kimi"} for command in commands)

    (mailroom / "readiness.yaml").unlink()
    missing = evaluate(root, mailroom, "canary")
    assert _by_name(missing)["model_clis"].verdict == "fail"


def test_requested_mode_must_match_shared_budget_mode(tmp_path, monkeypatch):
    root, mailroom = _fixture(tmp_path)
    monkeypatch.setattr("scripts.check_agent_readiness.shutil.which", lambda _: "/bin/true")
    assert _by_name(evaluate(root, mailroom, "canary"))["operating_mode"].verdict == "pass"
    mismatch = _by_name(evaluate(root, mailroom, "supervised"))["operating_mode"]
    assert mismatch.verdict == "fail"
    assert "requested 'supervised'" in mismatch.detail


def test_stale_running_marker_fails(tmp_path, monkeypatch):
    root, mailroom = _fixture(tmp_path)
    monkeypatch.setattr("scripts.check_agent_readiness.shutil.which", lambda command: f"/bin/{command}")
    (mailroom / "locks/running/backend-deadbeef").write_text("999999999")
    assert _by_name(evaluate(root, mailroom, "canary"))["stale_markers"].verdict == "fail"


def test_unacked_messages_fail_until_the_role_cursor_contains_the_id(tmp_path, monkeypatch):
    root, mailroom = _fixture(tmp_path)
    monkeypatch.setattr("scripts.check_agent_readiness.shutil.which", lambda command: f"/bin/{command}")
    message_id = "11111111-1111-1111-1111-111111111111"
    (mailroom / "messages/one.json").write_text(json.dumps({
        "message_id": message_id, "to_role": "pm",
    }))
    check = _by_name(evaluate(root, mailroom, "canary"))["unacked_messages"]
    assert check.verdict == "fail"
    assert "'pm': 1" in check.detail
    (mailroom / "cursors/pm.acked").write_text(message_id + "\n")
    assert _by_name(evaluate(root, mailroom, "canary"))["unacked_messages"].verdict == "pass"


def test_unresolved_recovery_bundle_fails_until_valid_resolution(tmp_path, monkeypatch):
    root, mailroom = _fixture(tmp_path)
    monkeypatch.setattr("scripts.check_agent_readiness.shutil.which", lambda command: f"/bin/{command}")
    bundle = mailroom / "recovery/TASK-1/run-1"
    bundle.mkdir(parents=True)
    (bundle / "metadata.json").write_text(json.dumps({
        "schema_version": "1.0", "dirty": True, "unpushed_commit_count": 0,
    }))
    (bundle / "working.patch").write_text("diff")
    check = _by_name(evaluate(root, mailroom, "canary"))["recovery"]
    assert check.verdict == "fail"
    assert "RECOVERY_REQUIRED" in check.detail
    (bundle / "resolution.json").write_text(json.dumps({
        "schema_version": "1.0", "resolved_by": "pm", "method": "applied",
        "ts": "2026-08-02T00:00:00Z", "note": "restored",
    }))
    assert _by_name(evaluate(root, mailroom, "canary"))["recovery"].verdict == "pass"


def test_recovery_check_fails_closed_without_verifier_or_with_missing_worktree(tmp_path, monkeypatch):
    root, mailroom = _fixture(tmp_path)
    monkeypatch.setattr("scripts.check_agent_readiness.shutil.which", lambda command: f"/bin/{command}")
    (root / "agents/recovery.py").unlink()
    check = _by_name(evaluate(root, mailroom, "canary"))["recovery"]
    assert check.verdict == "fail"
    assert "not-yet-verifiable" in check.detail

    (root / "agents/recovery.py").write_text("def verify_bundle(path): return True\n")
    bundle = mailroom / "recovery/TASK-2/run-2"
    bundle.mkdir(parents=True)
    (bundle / "metadata.json").write_text(json.dumps({
        "schema_version": "1.0", "dirty": False, "unpushed_commit_count": 1,
        "worktree": str(tmp_path / "gone"),
    }))
    check = _by_name(evaluate(root, mailroom, "canary"))["recovery"]
    assert check.verdict == "fail"
    assert "worktree missing" in check.detail


def test_malformed_recovery_metadata_is_a_named_failure_not_a_crash(tmp_path, monkeypatch):
    root, mailroom = _fixture(tmp_path)
    monkeypatch.setattr("scripts.check_agent_readiness.shutil.which", lambda command: f"/bin/{command}")
    bundle = mailroom / "recovery/TASK-3/run-3"
    bundle.mkdir(parents=True)
    (bundle / "metadata.json").write_text(json.dumps({
        "schema_version": "1.0", "dirty": False, "unpushed_commit_count": "many",
    }))
    check = _by_name(evaluate(root, mailroom, "canary"))["recovery"]
    assert check.verdict == "fail"
    assert "unpushed_commit_count invalid" in check.detail


def test_live_loop_lock_fails(tmp_path, monkeypatch):
    root, mailroom = _fixture(tmp_path)
    monkeypatch.setattr("scripts.check_agent_readiness.shutil.which", lambda command: f"/bin/{command}")
    lock = (mailroom / "locks/backend.lock").open("a+")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert _by_name(evaluate(root, mailroom, "canary"))["loop_locks"].verdict == "fail"
    finally:
        lock.close()


def test_unwritable_budget_ledger_is_fail_closed(tmp_path, monkeypatch):
    root, mailroom = _fixture(tmp_path)
    monkeypatch.setattr("scripts.check_agent_readiness.shutil.which", lambda command: f"/bin/{command}")
    state = yaml.safe_load((mailroom / "readiness.yaml").read_text())
    blocked = tmp_path / "blocked"
    blocked.mkdir(mode=0o500)
    state["budget_ledger_path"] = str(blocked / "budget.sqlite3")
    (mailroom / "readiness.yaml").write_text(yaml.safe_dump(state))
    assert _by_name(evaluate(root, mailroom, "canary"))["budget_ledger"].verdict == "fail"


def test_merge_automation_warns_canary_and_fails_unattended(tmp_path, monkeypatch):
    root, mailroom = _fixture(tmp_path)
    monkeypatch.setattr("scripts.check_agent_readiness.shutil.which", lambda command: f"/bin/{command}")
    assert _by_name(evaluate(root, mailroom, "canary"))["merge_automation"].verdict == "warn"
    assert _by_name(evaluate(root, mailroom, "unattended-7d"))["merge_automation"].verdict == "fail"


def test_placeholder_coverage_floor_is_not_reported_active(tmp_path, monkeypatch):
    root, mailroom = _fixture(tmp_path)
    monkeypatch.setattr(
        "scripts.check_agent_readiness.shutil.which", lambda command: f"/bin/{command}"
    )
    (root / "agents/merge_robot/coverage_floor.json").write_text('{"floor": 0.0}')
    check = _by_name(evaluate(root, mailroom, "canary"))["coverage_floor"]
    assert check.verdict == "warn"
    assert "inactive" in check.detail


def test_mode_matrix_escalates_only_at_the_documented_boundary(tmp_path, monkeypatch):
    root, mailroom = _fixture(tmp_path)
    monkeypatch.setattr("scripts.check_agent_readiness.shutil.which", lambda command: f"/bin/{command}")
    canary = _by_name(evaluate(root, mailroom, "canary"))
    supervised = _by_name(evaluate(root, mailroom, "supervised"))
    seven = _by_name(evaluate(root, mailroom, "unattended-7d"))
    ten = _by_name(evaluate(root, mailroom, "unattended-10d"))
    assert canary["frontend_ci"].verdict == "pass"
    assert canary["merge_automation"].verdict == "warn"
    assert supervised["merge_automation"].verdict == "warn"
    assert seven["merge_automation"].verdict == "fail"
    assert seven["reserve_budget"].verdict == "skip"
    assert ten["reserve_budget"].verdict == "fail"


def test_dispatcher_check_ignores_historical_model_commands_in_comments(tmp_path, monkeypatch):
    root, mailroom = _fixture(tmp_path)
    monkeypatch.setattr("scripts.check_agent_readiness.shutil.which", lambda command: f"/bin/{command}")
    (root / "scripts/agent_loop.sh").write_text(
        "# legacy: codex exec and claude -p\npython3 agents/dispatch.py\n"
    )
    assert _by_name(evaluate(root, mailroom, "canary"))["dispatcher"].verdict == "pass"


def test_always_allow_run_budget_fails_unattended(tmp_path, monkeypatch):
    root, mailroom = _fixture(tmp_path)
    monkeypatch.setattr("scripts.check_agent_readiness.shutil.which", lambda command: f"/bin/{command}")
    (root / "agents/run_budget.py").write_text("from agents.interfaces.run_budget import AlwaysAllow\ndef load(): return AlwaysAllow()\n")
    assert _by_name(evaluate(root, mailroom, "unattended-7d"))["run_budget"].verdict == "fail"


def test_arbiter_fallback_requires_actual_pm_lite_consumer(tmp_path, monkeypatch):
    root, mailroom = _fixture(tmp_path)
    monkeypatch.setattr(
        "scripts.check_agent_readiness.shutil.which", lambda command: f"/bin/{command}"
    )
    assert _by_name(evaluate(root, mailroom, "supervised"))[
        "arbiter_fallback"
    ].verdict == "fail"
    scheduler = root / "agents/pm_lite/scheduler.py"
    scheduler.parent.mkdir(parents=True)
    scheduler.write_text(
        "def _load_live_config(): pass\n"
        "def _circuit_broken_roles(): pass\n"
        "arbiter_after_circuit_break(config)\n"
    )
    assert _by_name(evaluate(root, mailroom, "supervised"))[
        "arbiter_fallback"
    ].verdict == "pass"


def test_json_cli_lists_every_check_and_unknown_mode_fails(tmp_path, monkeypatch):
    root, mailroom = _fixture(tmp_path)
    env = {**os.environ, "PATH": os.environ["PATH"]}
    command = [sys.executable, str(ROOT / "scripts/check_agent_readiness.py"),
               "--mode", "canary", "--root", str(root), "--mailroom", str(mailroom), "--json"]
    run = subprocess.run(command, text=True, capture_output=True, env=env, check=False)
    payload = json.loads(run.stdout)
    assert isinstance(payload["checks"], list)
    assert {"name", "verdict", "detail"} == set(payload["checks"][0])

    bad = subprocess.run(command[:2] + ["--mode", "mystery"], text=True, capture_output=True, check=False)
    assert bad.returncode != 0
