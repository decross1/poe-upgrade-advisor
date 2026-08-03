#!/usr/bin/env python3
"""Deterministic pre-restart readiness gate.

The checker never invokes a model. Runtime facts that cannot be proven without
spending (provider authentication, GitHub identity separation, shakedown
completion) must be recorded in ``mailroom/readiness.yaml`` by an operator or
deterministic provisioning step.
"""
from __future__ import annotations

import argparse
import ast
import fcntl
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.interfaces.packet import PacketError, load_packet
from agents.interfaces.policy import PolicyError, load_policy

MODES = ("canary", "supervised", "unattended-7d", "unattended-10d")
ROLES = ("pm", "backend", "frontend")


@dataclass(frozen=True)
class Check:
    name: str
    verdict: str
    detail: str


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        value = yaml.safe_load(path.read_text()) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a mapping")
    return value


def find_mailroom(root: Path) -> Path:
    """Find the project mailroom without assuming a particular worktree depth."""
    for ancestor in (root, *root.parents):
        candidate = ancestor / "mailroom"
        if candidate.is_dir() and (ancestor / "worktrees").is_dir():
            return candidate
    return root.parent / "mailroom"


def _severity(mode: str, name: str) -> str:
    warn_canary = {"frontend_ci", "coverage_floor", "merge_automation", "run_budget"}
    supervised = {"task_packets", "arbiter_fallback"}
    unattended = {"degradation", "ready_queue", "shakedown"}
    ten_day = {"reserve_budget"}
    if name in warn_canary:
        if mode == "canary":
            return "warn"
        if name in {"merge_automation", "run_budget"} and mode == "supervised":
            return "warn"
        return "fail"
    if name in supervised:
        return "fail" if mode != "canary" else "skip"
    if name in unattended:
        return "fail" if mode.startswith("unattended") else "skip"
    if name in ten_day:
        return "fail" if mode == "unattended-10d" else "skip"
    return "fail"


def _result(mode: str, name: str, ok: bool, detail: str) -> Check:
    if ok:
        return Check(name, "pass", detail)
    severity = _severity(mode, name)
    return Check(name, severity, detail)


def _writable(path: Path) -> tuple[bool, str]:
    parent = path if path.is_dir() else path.parent
    if not parent.exists():
        return False, f"parent missing: {parent}"
    try:
        mode = parent.stat().st_mode
    except OSError as exc:
        return False, str(exc)
    if not mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        return False, f"no write bit on {parent}"
    if not os.access(parent, os.W_OK):
        return False, f"not writable: {parent}"
    return True, f"writable: {parent}"


def _locks_free(mailroom: Path) -> tuple[bool, str]:
    held = []
    errors = []
    handles = []
    try:
        for role in ROLES:
            path = mailroom / "locks" / f"{role}.lock"
            if not path.exists():
                continue
            try:
                handle = path.open("r+")
            except OSError as exc:
                errors.append(f"{role}: {exc}")
                continue
            handles.append(handle)
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                held.append(role)
        if errors:
            return False, f"unreadable role locks: {errors}"
        return not held, "all role locks free" if not held else f"held locks: {held}"
    finally:
        for handle in handles:
            handle.close()


def _unacked_messages(mailroom: Path) -> tuple[bool, str]:
    acked = {}
    errors = []
    for role in ROLES:
        cursor = mailroom / "cursors" / f"{role}.acked"
        try:
            acked[role] = set(cursor.read_text().split()) if cursor.exists() else set()
        except OSError as exc:
            acked[role] = set()
            errors.append(f"{cursor.name}: {exc}")
    counts = {role: 0 for role in ROLES}
    for path in sorted((mailroom / "messages").glob("*.json")):
        try:
            message = json.loads(path.read_text())
            role = message["to_role"]
            message_id = message["message_id"]
            if role in counts and message_id not in acked[role]:
                counts[role] += 1
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append(f"{path.name}: {exc}")
    total = sum(counts.values())
    ok = total == 0 and not errors
    if errors:
        return False, f"unreadable ledger messages: {errors}"
    return ok, "no unacked messages" if ok else f"unacked messages: {counts}"


def _recovery_state(root: Path, mailroom: Path) -> tuple[bool, str]:
    verifier_path = root / "agents/recovery.py"
    if not verifier_path.is_file():
        return False, "not-yet-verifiable: agents/recovery.py is not integrated"
    spec = importlib.util.spec_from_file_location("_readiness_recovery", verifier_path)
    if spec is None or spec.loader is None:
        return False, "not-yet-verifiable: cannot load recovery verifier"
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        verify_bundle = module.verify_bundle
    except (AttributeError, ImportError, OSError) as exc:
        return False, f"not-yet-verifiable: {exc}"

    unresolved = []
    invalid = []
    for metadata_path in sorted((mailroom / "recovery").glob("*/*/metadata.json")):
        bundle = metadata_path.parent
        try:
            metadata = json.loads(metadata_path.read_text())
        except (OSError, ValueError) as exc:
            invalid.append(f"{bundle}: metadata invalid: {exc}")
            continue
        if metadata.get("schema_version") != "1.0":
            invalid.append(f"{bundle}: metadata schema invalid")
            continue
        try:
            unpushed = int(metadata.get("unpushed_commit_count", 0))
        except (TypeError, ValueError):
            invalid.append(f"{bundle}: unpushed_commit_count invalid")
            continue
        needs_recovery = metadata.get("dirty") is True or unpushed > 0
        if not needs_recovery:
            continue
        resolution_path = bundle / "resolution.json"
        if resolution_path.exists():
            try:
                resolution = json.loads(resolution_path.read_text())
                if resolution.get("schema_version") == "1.0" and resolution.get("method") in {
                    "applied", "discarded", "pushed", "merged",
                }:
                    continue
                invalid.append(f"{bundle}: resolution invalid")
                continue
            except (OSError, ValueError):
                invalid.append(f"{bundle}: resolution invalid")
                continue
        try:
            verified = bool(verify_bundle(bundle))
        except Exception as exc:  # noqa: BLE001 - verifier failure must fail closed
            invalid.append(f"{bundle}: verifier error: {exc}")
            continue
        if not verified:
            invalid.append(f"{bundle}: bundle incomplete")
            continue
        worktree = metadata.get("worktree")
        if worktree and not Path(worktree).is_dir():
            invalid.append(f"{bundle}: unresolved worktree missing: {worktree}")
            continue
        unresolved.append(str(bundle.relative_to(mailroom / "recovery")))
    if invalid:
        return False, "; ".join(invalid)
    if unresolved:
        return False, f"RECOVERY_REQUIRED: {unresolved}"
    return True, "no unresolved verified recovery bundles"


def _process_started_at(pid: int, proc_root: Path = Path("/proc")) -> float | None:
    """Return process start epoch, or None when procfs cannot corroborate it."""
    try:
        stat_tail = (proc_root / str(pid) / "stat").read_text().rsplit(")", 1)[1]
        start_ticks = int(stat_tail.split()[19])
        boot_line = next(
            line for line in (proc_root / "stat").read_text().splitlines()
            if line.startswith("btime ")
        )
        boot_epoch = int(boot_line.split()[1])
        return boot_epoch + start_ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration):
        return None


def _marker_process_is_live(marker: Path, pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    started_at = _process_started_at(pid)
    if started_at is None:
        return True
    # A process born after the marker is a reused PID, not the marker owner.
    return started_at <= marker.stat().st_mtime + 1.0


def _stale_markers(mailroom: Path) -> tuple[bool, str]:
    stale = []
    for marker in sorted((mailroom / "locks" / "running").glob("*")):
        try:
            pid = int(marker.read_text().strip())
            live = _marker_process_is_live(marker, pid)
        except (ValueError, OSError):
            live = False
        if not live:
            stale.append(marker.name)
    return not stale, "no stale markers" if not stale else f"stale markers: {stale}"


def _required_checks(root: Path) -> set[str]:
    tree = ast.parse((root / "agents/merge_robot/merge_robot.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "REQUIRED_CHECKS"
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            return set(value)
    return set()


def _worktrees_clean(state: dict[str, Any]) -> tuple[bool, str]:
    entries = state.get("worktrees") or []
    if not entries:
        return False, "no worktrees recorded"
    bad = []
    for raw in entries:
        path = Path(raw)
        if not path.is_dir() or not os.access(path, os.W_OK):
            bad.append(f"{path}: missing/unwritable")
            continue
        try:
            run = subprocess.run(
                [
                    "git", "--no-optional-locks", "-C", str(path),
                    "status", "--porcelain",
                ],
                text=True,
                capture_output=True,
                check=False,
                env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
            )
        except OSError as exc:
            bad.append(f"{path}: git status failed: {exc}")
            continue
        if run.returncode or run.stdout.strip():
            bad.append(f"{path}: not a clean git worktree")
    return not bad, "all worktrees clean and writable" if not bad else "; ".join(bad)


def _model_clis(state: dict[str, Any]) -> tuple[bool, str]:
    configured = state.get("model_clis") or {}
    bad = []
    for role in ROLES:
        item = configured.get(role) or {}
        command = item.get("command")
        if not command or shutil.which(str(command)) is None:
            bad.append(f"{role}: CLI missing")
        elif item.get("authenticated") is not True:
            bad.append(f"{role}: authentication unproven")
    return not bad, "model CLIs present; auth recorded" if not bad else "; ".join(bad)


def _packets(root: Path) -> tuple[bool, str, int]:
    paths = sorted((root / "tasks" / "packets").glob("*.json"))
    errors = []
    ready = 0
    for path in paths:
        try:
            packet = load_packet(path)
            ready += int(packet.get("ready", True))
        except PacketError as exc:
            errors.append(f"{path.name}: {exc}")
    ok = bool(paths) and not errors
    detail = f"{len(paths)} valid packet(s)" if ok else ("; ".join(errors) or "no packets")
    return ok, detail, ready


def evaluate(root: Path, mailroom: Path, mode: str, environ: dict[str, str] | None = None) -> list[Check]:
    if mode not in MODES:
        raise ValueError(f"unknown mode: {mode}")
    env = os.environ if environ is None else environ
    try:
        state = _read_yaml(mailroom / "readiness.yaml")
        state_error = ""
    except ValueError as exc:
        state, state_error = {}, str(exc)

    checks: list[Check] = []
    configured_mode = state.get("operating_mode")
    checks.append(_result(
        mode,
        "operating_mode",
        configured_mode == mode,
        f"operating mode recorded as {configured_mode!r}; requested {mode!r}",
    ))
    halt = (mailroom / "HALT").is_file()
    checks.append(_result(mode, "halt", halt, "HALT is set" if halt else "HALT is absent"))
    ok, detail = _locks_free(mailroom)
    checks.append(_result(mode, "loop_locks", ok, detail))
    ok, detail = _stale_markers(mailroom)
    checks.append(_result(mode, "stale_markers", ok, detail))
    ok, detail = _unacked_messages(mailroom)
    checks.append(_result(mode, "unacked_messages", ok, detail))
    ok, detail = _recovery_state(root, mailroom)
    checks.append(_result(mode, "recovery", ok, detail))

    try:
        policy = load_policy(root / "agents" / "governor")
        checks.append(_result(mode, "policy", True, "task and run policy parse"))
    except PolicyError as exc:
        policy = {}
        checks.append(_result(mode, "policy", False, str(exc)))

    budget_path = Path(state.get("budget_ledger_path", mailroom / "governor/budget_ledger.sqlite3"))
    ok, detail = _writable(budget_path)
    checks.append(_result(mode, "budget_ledger", ok, detail))
    telemetry_path = Path(state.get("telemetry_path", mailroom / "telemetry/invocations.jsonl"))
    ok, detail = _writable(telemetry_path)
    checks.append(_result(mode, "telemetry", ok, detail))
    ok, detail = _model_clis(state)
    checks.append(_result(mode, "model_clis", ok, detail if not state_error else state_error))

    github = state.get("github") or {}
    gh_ok = bool(shutil.which("gh")) and github.get("authenticated") is True \
        and github.get("scopes_sufficient") is True
    checks.append(_result(mode, "github_auth", gh_ok, "gh auth and scopes recorded" if gh_ok else "gh auth/scopes unproven"))
    ok, detail = _worktrees_clean(state)
    checks.append(_result(mode, "worktrees", ok, detail))

    dispatch = root / "agents/dispatch.py"
    loop = (root / "scripts/agent_loop.sh").read_text() if (root / "scripts/agent_loop.sh").exists() else ""
    executable_lines = "\n".join(
        line for line in loop.splitlines() if not line.lstrip().startswith("#")
    )
    bare = any(token in executable_lines for token in ("claude -p", "codex exec", "kimi --"))
    checks.append(_result(mode, "dispatcher", dispatch.is_file() and not bare,
                          "dispatch selected; launcher has no bare model command" if dispatch.is_file() and not bare
                          else "dispatch missing or launcher still invokes a model directly"))

    try:
        ci = _read_yaml(root / ".github/workflows/ci.yml")
        required = _required_checks(root)
        jobs = set(ci.get("jobs") or {})
        frontend_ok = {"web-test", "overlay-test"} <= required <= jobs
    except (ValueError, OSError, SyntaxError):
        frontend_ok = False
    checks.append(_result(mode, "frontend_ci", frontend_ok, "frontend CI jobs are required" if frontend_ok else "frontend CI gates incomplete"))
    try:
        floor = float(json.loads((root / "agents/merge_robot/coverage_floor.json").read_text())["floor"])
    except (OSError, ValueError, KeyError, TypeError):
        floor = 0.0
    checks.append(_result(
        mode,
        "coverage_floor",
        floor >= 60.0,
        f"coverage floor={floor}" if floor >= 60.0 else f"coverage floor inactive: {floor}",
    ))

    packets_ok, packet_detail, ready_count = _packets(root)
    checks.append(_result(mode, "task_packets", packets_ok, packet_detail))
    scheduler = root / "agents/pm_lite/scheduler.py"
    try:
        scheduler_source = scheduler.read_text(encoding="utf-8")
    except OSError:
        scheduler_source = ""
    arbiter_wired = (
        "arbiter_after_circuit_break(" in scheduler_source
        and "_load_live_config(" in scheduler_source
        and "_circuit_broken_roles(" in scheduler_source
    )
    checks.append(_result(
        mode,
        "arbiter_fallback",
        arbiter_wired,
        "arbiter fallback consumed from live config"
        if arbiter_wired
        else "arbiter fallback only declared or absent",
    ))
    merge_ok = bool(env.get("MERGE_ROBOT_TOKEN") or github.get("token_present")) \
        and github.get("branch_protection") is True and github.get("distinct_merge_identity") is True
    checks.append(_result(mode, "merge_automation", merge_ok,
                          "token, protection, and distinct identity recorded" if merge_ok else "merge automation incomplete"))

    budget_source = root / "agents/run_budget.py"
    budget_ok = budget_source.is_file() and "def load(" in budget_source.read_text() \
        and "AlwaysAllow" not in budget_source.read_text()
    checks.append(_result(mode, "run_budget", budget_ok, "configured run budget loader" if budget_ok else "RUN-BUDGET-ABSENT"))
    degradation_ok = bool(policy.get("degradation")) and (root / "agents/degradation.py").is_file()
    checks.append(_result(mode, "degradation", degradation_ok, "degradation ladder configured" if degradation_ok else "degradation ladder absent"))
    checks.append(_result(mode, "ready_queue", ready_count >= 40, f"dependency-ready packets={ready_count}, required=40"))
    checks.append(_result(mode, "shakedown", state.get("shakedown_passed") is True,
                          "shakedown evidence recorded" if state.get("shakedown_passed") is True else "shakedown evidence absent"))
    reserve = ((policy.get("run") or {}).get("reserve") or {})
    reserve_ok = bool(reserve) and state.get("reserve_unspent") is True
    checks.append(_result(mode, "reserve_budget", reserve_ok,
                          "reserve defined and unspent" if reserve_ok else "reserve missing or spent"))
    return checks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", required=True, choices=MODES)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--mailroom", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    mailroom = (args.mailroom or find_mailroom(root)).resolve()
    checks = evaluate(root, mailroom, args.mode)
    ready = not any(check.verdict == "fail" for check in checks)
    if args.json:
        print(json.dumps({"mode": args.mode, "ready": ready, "checks": [asdict(c) for c in checks]}, indent=2))
    else:
        for check in checks:
            print(f"{check.verdict.upper():5} {check.name}: {check.detail}")
        print(f"READINESS: {'READY' if ready else 'NOT READY'} ({args.mode})")
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
