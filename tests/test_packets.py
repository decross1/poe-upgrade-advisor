from __future__ import annotations

import copy
import json
import fnmatch
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
        # 2026-08-03: Discord release-note renderer (mission leg 3 of #97),
        # render-only — wiring it to the live announce channel is an
        # operator-gated follow-up stage. Its check targets a test file the
        # packet itself creates; see _check_targets_unbuilt_scope below.
        "TASK-300-S1.json",
        # 2026-08-03: mission-resume repacketization (orchestrator ruling
        # 003c6e0b, issue #97). Parked PR #87 (TASK-102, issue #7) replays as
        # four budget-fit stages — code/CI first, frozen seed builds inert
        # until S5 flips the manifest. Parked PR #91 (TASK-210, issue #79)
        # replays as core pipeline + e2e snapshot suite. Registered by pm.
        "TASK-102-S2.json",
        "TASK-102-S3.json",
        "TASK-102-S4.json",
        "TASK-102-S5.json",
        "TASK-210-S2.json",
        "TASK-210-S3.json",
    }


def _check_targets_unbuilt_scope(command: str, packet: dict) -> bool:
    """True when a check names a path the packet itself is scoped to CREATE.

    A required check asserts POST-work state, so a packet that adds a test
    file declares a check that cannot pass until the work lands. Asserting
    such a check passes today would force someone to pre-create the agent's
    deliverable — hollowing out the task, which is exactly what the canary
    carve-out below exists to prevent. What IS meaningful is that the check
    is well-formed and its target is in the packet's own files_in_scope, so
    the work will bring it into existence.
    """
    scope = packet.get("files_in_scope") or []
    for token in shlex.split(command):
        if token.startswith("-") or "/" not in token:
            continue
        if (ROOT / token).exists():
            continue
        if any(fnmatch.fnmatch(token, glob) or token == glob for glob in scope):
            return True
    return False


def test_every_unique_example_required_check_exists_and_runs():
    commands = []
    unbuilt = set()
    for path in sorted((ROOT / "tasks/packets").glob("*.json")):
        packet = json.loads(path.read_text())
        for command in packet["required_checks"]:
            commands.append(command)
            if _check_targets_unbuilt_scope(command, packet):
                unbuilt.add(command)
    assert commands
    for command in dict.fromkeys(commands):
        if command in unbuilt:
            # Well-formed and in-scope; it runs once the work exists.
            assert shlex.split(command)[0] in {"python3", "npm"}
            continue
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
            # (docs/agent-org/canary-probe.md), so its correct verdict in the
            # repo DEPENDS ON LIFECYCLE STAGE: FAIL before the canary runs,
            # PASS once the canary's file lands. An earlier revision of this
            # test pinned only the pre-canary FAIL and turned CI red the
            # moment the canary succeeded — backend caught it on PR #98 and
            # correctly refused to weaken it. Assert the checker is RIGHT for
            # whichever state the repo is in, and pin both directions
            # unconditionally in scratch trees (the checker resolves paths
            # relative to cwd, so it is copied in).
            probe_in_repo = (ROOT / "docs/agent-org/canary-probe.md").is_file()
            if probe_in_repo:
                assert result.returncode == 0, (
                    f"probe exists but checker rejects it:\n{command}\n"
                    f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
                )
            else:
                assert result.returncode == 1 and "missing" in result.stdout, (
                    f"probe absent but checker did not report it missing:\n"
                    f"{command}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
                )

            def _run_in_scratch(probe_text: str | None):
                with tempfile.TemporaryDirectory() as scratch:
                    root = Path(scratch)
                    (root / "scripts").mkdir()
                    shutil.copy(ROOT / "scripts/check_canary_probe.py", root / "scripts")
                    if probe_text is not None:
                        probe = root / "docs/agent-org/canary-probe.md"
                        probe.parent.mkdir(parents=True)
                        probe.write_text(probe_text)
                    return subprocess.run(
                        argv, cwd=root, capture_output=True, text=True,
                        timeout=120, check=False,
                    )

            good = _run_in_scratch("# Canary probe\n\nvalid scratch probe\n")
            assert good.returncode == 0, (
                f"checker cannot pass a valid probe:\nSTDOUT:\n{good.stdout}"
            )
            missing = _run_in_scratch(None)
            assert missing.returncode == 1 and "missing" in missing.stdout, (
                f"checker does not fail on an absent probe:\nSTDOUT:\n{missing.stdout}"
            )
            bad = _run_in_scratch("# Wrong heading\n")
            assert bad.returncode == 1, (
                f"checker accepts a malformed probe:\nSTDOUT:\n{bad.stdout}"
            )
            continue
        assert result.returncode == 0, f"{command}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
