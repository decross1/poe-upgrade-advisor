from __future__ import annotations

import copy
import json
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from agents.interfaces.packet import PacketError, out_of_scope
from agents.packets.normalize import (
    ConfirmationRequired,
    normalize_issue,
    packet_preview,
)
from agents.packets.validate import (
    PROTECTED_REVIEW,
    validate_all,
    validate_path,
    validate_semantics,
)

ROOT = Path(__file__).resolve().parents[1]


def _packet(**overrides):
    packet = {
        "schema_version": "1.0",
        "task_id": "TASK-210-S1",
        "parent_task_id": "TASK-210",
        "owner_role": "frontend",
        "tier": "green",
        "objective": "Add a bounded and mechanically verifiable interaction.",
        "files_in_scope": ["web/src/components/Card.tsx"],
        "files_out_of_scope": ["contracts/**"],
        "required_checks": ["python3 -m pytest tests/test_packets.py -q"],
        "acceptance_criteria": [{"id": "AC-1", "text": "Focused tests pass."}],
        "budgets": {
            "max_attempts": 2,
            "max_files_modified": 2,
            "max_diff_lines": 120,
            "max_wall_clock_seconds": 600,
        },
    }
    packet.update(overrides)
    return packet


def test_packet_input_mutation_guard():
    packet = _packet()
    required = (
        "schema_version", "task_id", "owner_role", "tier", "objective",
        "files_in_scope", "files_out_of_scope", "required_checks",
        "acceptance_criteria", "budgets",
    )
    for field in required:
        mutant = copy.deepcopy(packet)
        del mutant[field]
        with pytest.raises(PacketError):
            validate_semantics(mutant)
    with pytest.raises(PacketError, match="ambiguous stage identity"):
        validate_semantics(_packet(parent_task_id="TASK-999"))


def test_oversized_or_ambiguous_packet_is_rejected(tmp_path):
    oversized = _packet(files_in_scope=[f"web/src/{index}.ts" for index in range(26)])
    with pytest.raises(PacketError, match="oversized"):
        validate_semantics(oversized)
    with pytest.raises(PacketError, match="both allows and forbids"):
        validate_semantics(_packet(files_in_scope=["web/**"], files_out_of_scope=["web/**"]))
    huge = tmp_path / "TASK-1.json"
    huge.write_text(" " * (64 * 1024 + 1))
    with pytest.raises(PacketError, match="oversized"):
        validate_path(huge)


def test_incomplete_packet_fails_before_any_model_invocation():
    invoked = False
    packet = _packet()
    del packet["required_checks"]
    with pytest.raises(PacketError):
        validate_semantics(packet)
        invoked = True
    assert not invoked


def test_out_of_scope_remains_a_hard_denial():
    packet = validate_semantics(_packet())
    assert out_of_scope(["server/app.py"], packet) == ["server/app.py"]


def test_legacy_issue_normalizes_only_with_explicit_confirmation():
    issue = {"number": 79, "title": "TASK-210-S1: bounded stage"}
    preview = packet_preview(issue)
    assert preview["files_in_scope"] == []
    with pytest.raises(ConfirmationRequired):
        normalize_issue(
            issue,
            confirmed_by=None,
            owner_role="frontend",
            tier="green",
            files_in_scope=["web/**"],
            files_out_of_scope=["contracts/**"],
            required_checks=["python3 -m pytest tests/test_packets.py -q"],
            acceptance=["The bounded stage passes its focused tests."],
        )
    packet = normalize_issue(
        issue,
        confirmed_by="pm",
        owner_role="frontend",
        tier="green",
        files_in_scope=["web/**"],
        files_out_of_scope=["contracts/**"],
        required_checks=["python3 -m pytest tests/test_packets.py -q"],
        acceptance=["The bounded stage passes its focused tests."],
    )
    assert packet["parent_task_id"] == "TASK-210"


@pytest.mark.parametrize(
    "protected_scope",
    ["agents/packets/**", "tasks/packets/archive/**"],
)
def test_protected_scope_forces_frontier_route_and_review_policy(protected_scope):
    with pytest.raises(PacketError, match="protected-path"):
        validate_semantics(_packet(files_in_scope=[protected_scope]))
    protected = _packet(
        files_in_scope=[protected_scope],
        tier="red",
        routing={
            "reasoning_effort": "high",
            "review_only_if": [PROTECTED_REVIEW],
        },
    )
    assert validate_semantics(protected)["tier"] == "red"


def test_every_example_packet_validates():
    paths = validate_all(ROOT)
    assert {path.name for path in paths} == {
        "TASK-901-S1.json", "TASK-902-S1.json", "TASK-903-S1.json",
        "TASK-904-S1.json",
        # 2026-08-03: the ratified canary packet (base contract §16.3
        # Packet B + R4 check). Its check asserts POST-work state — see the
        # canary carve-out in the check-runner test below.
        "TASK-999-S1.json",
    }


def test_every_unique_example_required_check_exists_and_runs():
    commands = []
    for path in sorted((ROOT / "tasks/packets").glob("*.json")):
        commands.extend(json.loads(path.read_text())["required_checks"])
    assert commands
    for command in dict.fromkeys(commands):
        argv = shlex.split(command)
        assert argv and (argv[0] in {"python3", "npm"})
        # A packet check must be RUNNABLE, but this test runs in a Python-only
        # job. Shelling `npm run test` there fails on a missing toolchain, not
        # on a bad packet — it reports red for a reason unrelated to the thing
        # under test. Execute what this environment can; assert the rest is
        # well-formed and its workspace exists, and leave actually running the
        # npm suites to web-test / overlay-test, which are required checks.
        if argv[0] == "npm":
            assert "--prefix" in argv, f"npm check must name its workspace: {command}"
            workspace = argv[argv.index("--prefix") + 1]
            assert (ROOT / workspace).is_dir(), f"packet names a missing workspace: {command}"
            if not (ROOT / workspace / "node_modules").is_dir():
                continue
        result = subprocess.run(
            argv, cwd=ROOT, capture_output=True, text=True, timeout=120, check=False
        )
        if argv[-1] == "scripts/check_canary_probe.py":
            # The canary's check asserts the canary TASK's outcome
            # (docs/agent-org/canary-probe.md), which by design does not
            # exist until the canary agent creates it. Before the work, the
            # correct verdict is a clean FAIL — asserting rc==0 here would
            # force someone to pre-create the probe file and hollow out the
            # canary. Pin BOTH directions instead: a deterministic FAIL in
            # the repo, and a PASS against a valid probe in a scratch tree
            # (checker copied, since it resolves paths relative to cwd).
            assert result.returncode == 1 and "missing" in result.stdout, (
                f"{command}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
            with tempfile.TemporaryDirectory() as scratch:
                root = Path(scratch)
                (root / "scripts").mkdir()
                shutil.copy(ROOT / "scripts/check_canary_probe.py", root / "scripts")
                probe = root / "docs/agent-org/canary-probe.md"
                probe.parent.mkdir(parents=True)
                probe.write_text("# Canary probe\n\nvalid scratch probe\n")
                good = subprocess.run(
                    argv, cwd=root, capture_output=True, text=True,
                    timeout=120, check=False,
                )
                assert good.returncode == 0, (
                    f"checker cannot pass even against a valid probe:\n"
                    f"STDOUT:\n{good.stdout}\nSTDERR:\n{good.stderr}"
                )
            continue
        assert result.returncode == 0, f"{command}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
