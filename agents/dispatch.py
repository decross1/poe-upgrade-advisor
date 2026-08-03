#!/usr/bin/env python3
"""Dispatch v1 — the single governed entry point for one ledger message (W1-2).

Every model invocation in the org travels this path. `scripts/agent_loop.sh`
remains the process supervisor (flock, nohup, timeout, markers, worktrees) and
calls this once per message; nothing else may spawn a model.

Why this exists, measured: over 2026-07-25..27 the loop made 1,408 invocations,
every single one exited rc=0, and ~88% produced nothing. Six pm messages that
could not self-ack (Bash was blocked, and the ack instruction lived in the
agent's prompt) account for 977 of pm's 980 invocations — one message ran
6h13m at ~2-minute intervals, 180 times, until a human created HALT.

The two corrections that bound that failure:
  - the attempt ledger increments BEFORE the model is invoked (an agent that
    never returns anything is still counted), and
  - the ack decision belongs to the dispatcher, never to the agent — a hard
    per-MESSAGE attempt cap dead-letters and acks. Per-task caps do not bound
    this: 12-per-task would still have allowed 72 invocations across those six
    messages.

Order of operations (numbers match the Lane A plan):
   1  HALT check                  -> SUPPRESSED_HALT, exit 0, no ack
   2  open budget ledger          -> unavailable => exit 3, DO NOT INVOKE
   3  load + schema-validate message (+ duplicate idempotency suppression)
   4  preflight                   -> optional module, feature flag PREFLIGHT
   5  governor.allow              -> deny: SUPPRESSED_GOVERNOR, retain, exit 0
   5.5 run_budget.check           -> deny: reassign or suppress, retain, exit 0
   6  attempts = increment_attempt(message)      <-- BEFORE invoke
   7  attempts > max_attempts     -> dead-letter + ACK, exit 0
   8  telemetry.start
   9  deterministic prepass (packet-declared T0 commands)
  10  invoke the model, wall-clock capped
  11  validate .agent-result.json -> ack / retain
  12  recovery check (hook; full implementation is W1-4)
  13  governor.record
  14  telemetry.finish
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from agents.governor.budget_governor import Governor  # noqa: E402
from agents.interfaces import run_budget as run_budget_iface  # noqa: E402
from agents.interfaces.budget import (  # noqa: E402
    BudgetLedgerUnavailable,
    SqliteBudgetLedger,
)
from agents.interfaces.packet import PacketError, load_packet, packet_path  # noqa: E402
from agents.interfaces.policy import load_policy, resolve_budgets  # noqa: E402
from agents.interfaces.result import (  # noqa: E402
    RESULT_FILENAME,
    ResultError,
    is_ackable,
    load_result,
    sweep_result,
)
from agents.checks import (  # noqa: E402
    checks_telemetry,
    failed_checks_reason,
    provisioning_ok,
    run_commands,
    run_provisioning,
    validate_packet_commands,
)
from agents.completion import (  # noqa: E402
    Proof,
    breaks,
    persist_bundle,
    proofs_telemetry,
    refusal,
    verify_completion,
)
from agents.interfaces.states import (  # noqa: E402
    AckDecision,
    DispatchDecision,
    DispatcherTerminalStatus,
)
from agents.interfaces.telemetry import JsonlTelemetry  # noqa: E402
from agents.postmaster import ledger as ledger_mod  # noqa: E402
from agents import preflight as preflight_mod  # noqa: E402
from agents import provider_limit as provider_limit_mod  # noqa: E402
from jsonschema import ValidationError  # noqa: E402

RESULT_SCHEMA_REL = "agents/interfaces/schemas/result.schema.json"
STDERR_TAIL_LINES = 200
PREPASS_TIMEOUT = 300

#: Intents whose handling actually EXECUTES the task packet — the only ones
#: the CC-1 pre-invoke command gate should block on (L-8). Everything else
#: (ANSWER, SYNC, STATUS, REVIEW_VERDICT, ARBITRATION_RULING, QUESTION,
#: INTAKE_TICKET, BOOTSTRAP) is governance traffic that never runs
#: required_checks; blocking it on a bad packet makes the packet's own
#: correction undeliverable.
WORK_INTENTS = frozenset({"TASK_ASSIGN", "REVIEW_REQUEST"})

#: Where dispatcher state lives, all under the mailroom (shared across the
#: throwaway fan worktrees — repo-relative state would vanish with them):
#:   <mailroom>/governor/budget_ledger.sqlite3    fail-closed attempts + spend
#:   <mailroom>/governor/governor_ledger.sqlite3  governor decision history
#:   <mailroom>/telemetry/invocations.jsonl       fail-open analytics
#:   <mailroom>/dead_letter/<task>/<message>.json durable dead-letters
BUDGET_DB = "budget_ledger.sqlite3"
GOVERNOR_DB = "governor_ledger.sqlite3"


@dataclass
class Outcome:
    """What the dispatcher decided, printable as JSON for --dry-run/logs."""

    decision: str
    ack: str = AckDecision.RETAIN.value
    reason: str = ""
    message_id: str = ""
    task_id: str = ""
    role: str = ""
    attempts: int = 0
    max_attempts: int = 0
    exit_code: int = 0
    invoked: bool = False
    result_status: str | None = None
    extra: dict = field(default_factory=dict)

    def emit(self) -> None:
        print(json.dumps(asdict(self), default=str))


def _tail(text: str, lines: int = STDERR_TAIL_LINES) -> str:
    return "\n".join(text.splitlines()[-lines:])


def mailroom_root() -> Path:
    return ledger_mod.ledger_root()


def find_message(root: Path, message_id: str) -> dict:
    """Locate one message by full id or unique prefix; schema-validate it."""
    hits = [m for m in ledger_mod.all_messages(root)
            if m.get("message_id", "").startswith(message_id)]
    if len(hits) != 1:
        raise ValueError(f"message id '{message_id}' matches {len(hits)} messages")
    msg = hits[0]
    ledger_mod.VALIDATOR.validate(msg)
    return msg


def ack_message(root: Path, role: str, message_id: str) -> None:
    """Retire a message: append its full id to the role cursor, idempotently.

    Mirrors `ledger.cmd_ack` semantics exactly — newline-delimited full UUIDs,
    append-only, never rewrites.
    """
    if message_id in ledger_mod.acked_ids(root, role):
        return
    with (root / "cursors" / f"{role}.acked").open("a") as f:
        f.write(message_id + "\n")


def load_run_budget_port(
    warn=None,
    *,
    read_only: bool = False,
    mailroom: Path | None = None,
):
    """Lane B's `agents.run_budget.load()` if present, else AlwaysAllow.

    RUN_BUDGET=0 is the dispatch-side rollback flag (W2-3 'set all caps to
    infinity'): it forces AlwaysAllow, whose one-time RUN-BUDGET-ABSENT
    marker keeps the unbounded state visible.
    """
    if os.environ.get("RUN_BUDGET", "1") == "0":
        return run_budget_iface.AlwaysAllow(warn=warn)
    try:
        import agents.run_budget as rb  # noqa: PLC0415 — deliberate late bind
    except ImportError:
        return run_budget_iface.AlwaysAllow(warn=warn)
    loader = getattr(rb, "load", None)
    if loader is None:
        return run_budget_iface.AlwaysAllow(warn=warn)
    if read_only:
        return loader(read_only=True, mailroom=mailroom)
    return loader()


def resolve_tier(task_id: str, packet: dict | None) -> str:
    if packet and packet.get("tier"):
        return packet["tier"]
    return "org" if task_id == "ORG" else "green"


def build_prompt(role: str, msg: dict, run_id: str, mailroom: Path) -> str:
    id8 = msg["message_id"][:8]
    return (
        f"You are the {role} agent of the PoE Upgrade Advisor org, invoked "
        f"headlessly to process EXACTLY ONE ledger message. Startup reads, in "
        f"order: AGENTS.md, agents/roles/{role}.md, PRODUCT_DOCTRINE.md. Your "
        f"message: run 'python3 agents/postmaster/ledger.py show --id {id8}' "
        f"and handle ONLY that message per the AGENTS.md work protocol. You "
        f"are in a detached throwaway worktree at origin/main — create your "
        f"task branch from here and push it; commits not pushed are lost. "
        f"Other {role} invocations run in parallel on OTHER messages: do not "
        f"touch their tasks, do not process other inbox messages. When "
        f"finished (completed, blocked, or unable to proceed), write "
        f"{RESULT_FILENAME} in the worktree root conforming to "
        f"{RESULT_SCHEMA_REL} (schema_version \"1.0\", run_id \"{run_id}\", "
        f"task_id \"{msg['task_id']}\", status one of completed|blocked|"
        f"needs_retry; \"completed\" requires commit_sha, pushed, branch, "
        f"and acceptance_criteria, and the dispatcher VERIFIES the claim — "
        f"the commit must exist, the branch must be pushed to origin with "
        f"your commit at its tip, or the message is retained). Do NOT "
        f"acknowledge the ledger message — the dispatcher owns "
        f"acknowledgment; an exit code of 0 means nothing without a valid "
        f"result file."
    )


def resolve_effort(role: str, packet: dict | None) -> str:
    """CC-5 effort precedence (pm ruling, PLAN 18:55Z):

        packet `routing.reasoning_effort`  >  CODEX_EFFORT  >  built-in high

    CODEX_EFFORT stays a LIVE operator knob (mailroom/effort.env, sourced
    by agent_loop.sh with `set -a`) for packets that do not set the field.
    The pm role's claude CLI carries no effort flag — `not_applicable`,
    never a faked flag the CLI lacks.
    """
    if role == "pm":
        return "not_applicable"
    packet_effort = ((packet or {}).get("routing") or {}).get(
        "reasoning_effort")
    if packet_effort:
        return packet_effort
    return os.environ.get("CODEX_EFFORT", "high")


def role_command(role: str, prompt: str, mailroom: Path,
                 packet: dict | None = None) -> list[str]:
    """The model CLI for a role. This is the ONLY place a model is spawned.

    Machine-readable output is enabled on both CLIs (Lane B W2-1 seam): the
    final usage object is recovered from stdout and fed to accounting —
    subscription-capacity draw must never be disguised as zero cost.

    CC-5: the packet is finally in scope at the spawn site — before this,
    `routing.reasoning_effort` was schema surface the dispatcher never
    read and every invocation ran at the env/default rung.
    """
    if role == "pm":
        # --verbose is REQUIRED by the claude CLI when combining -p with
        # --output-format stream-json (verified live 2026-08-03: without it
        # the CLI exits in ~1s with a usage error — the first real pm
        # invocation found this; every prior run was a fake).
        #
        # --model is REQUIRED for a different reason (L-18, 2026-08-03): it
        # was absent, so pm took the CLI's ambient default and every pm
        # invocation of the first live session ran on Fable rather than
        # Opus. pm is the planning and judgment role — decomposition,
        # verification, arbitration — and it is the one role whose model
        # choice is a policy decision, not an inherited default. Pinning it
        # here means a change to the operator's own CLI config can never
        # silently retier the org's judgment. PM_MODEL overrides.
        return ["env", "-u", "ANTHROPIC_API_KEY", "claude", "-p", prompt,
                "--model", os.environ.get("PM_MODEL", "opus"),
                "--output-format", "stream-json", "--verbose",
                "--dangerously-skip-permissions", "--add-dir", str(mailroom)]
    if role == "frontend":
        # 2026-08-03 operator ruling: frontend is the kimi CLI (metered
        # provider). Spend is governed by run_policy's `kimi` cash budget —
        # run_budget.check's kimi branch — with the Kimi-console limit as
        # the provider-side backstop. kimi has no reasoning-effort flag;
        # KIMI_MODEL overrides config.toml's default_model when set.
        # NOTE: prompt mode is autonomous by itself — this CLI REJECTS
        # --auto/--yolo combined with --prompt (verified live 2026-08-03:
        # headless tool execution worked with neither flag).
        cmd = ["kimi", "--output-format", "stream-json"]
        kimi_model = os.environ.get("KIMI_MODEL")
        if kimi_model:
            cmd += ["-m", kimi_model]
        return cmd + ["--prompt", prompt]
    return ["codex", "exec", "--json",
            "--dangerously-bypass-approvals-and-sandbox",
            "-m", os.environ.get("CODEX_MODEL", "gpt-5.6-sol"),
            "-c", f"model_reasoning_effort={resolve_effort(role, packet)}",
            prompt]


def _provider_usage(role: str, stdout_tail: str) -> dict:
    """Lane B's usage parser, guarded until agents.accounting integrates.

    Contract (converged, PM 06:50): provider_usage(provider, str|dict) —
    Lane B's parser accepts the raw stdout tail directly and both provider
    vocabularies. Returns a dict with any of cash_usd / input_tokens /
    output_tokens / cached_input_tokens / allowance_pct_estimated /
    allowance_pct_source / invocation_weight — or None. Absent data stays
    None, never zero.

    Returns (usage_dict, parse_error): every failure mode — module
    unimportable (a packaging break once accounting is on main), parser
    exception, unknown shape — is loud on stderr AND carried into the
    telemetry finish event, so a dead pipeline is queryable, never a
    silent None-forever.
    """
    if not stdout_tail.strip():
        return {}, None
    provider = "anthropic" if role == "pm" else "openai"
    try:
        from agents.accounting import provider_usage  # noqa: PLC0415
    except ImportError as e:
        # With accounting on main this can only be a packaging break — the
        # silent version of this branch would record None-forever and look
        # identical to "the provider reported nothing" (PM, 06:50).
        msg = f"accounting module unimportable: {e}"
        print(f"TELEMETRY-DEGRADED: {msg}", file=sys.stderr)
        return {}, msg
    try:
        return provider_usage(provider, stdout_tail) or {}, None
    except Exception as e:  # noqa: BLE001 — fail-open, loudly
        msg = f"provider usage parse failed: {type(e).__name__}: {e}"
        print(f"TELEMETRY-DEGRADED: {msg}", file=sys.stderr)
        return {}, msg


def write_dead_letter(root: Path, *, task_id: str, role: str, message_id: str,
                      reason: str, attempts: int, exit_code: int | None,
                      stderr_tail: str, fingerprint: str | None) -> Path:
    """Durable dead-letter under the mailroom.

    NOT under the repo: the fan worktrees are throwaway, so a repo-relative
    dead-letter (what `budget_governor._dead_letter` writes) evaporates with
    the worktree. pm-lite re-triages from this directory.
    """
    d = root / "dead_letter" / task_id
    d.mkdir(parents=True, exist_ok=True)
    fp = d / f"{message_id}.json"
    if fp.exists():
        return fp
    fp.write_text(json.dumps({
        "schema_version": "1.0",
        # CC-2/A7: terminal statuses are authored HERE, by the control
        # plane — the agent-result schema can no longer express them.
        "status": DispatcherTerminalStatus.DEAD_LETTERED.value,
        "task_id": task_id,
        "role": role,
        "message_id": message_id,
        "reason": reason,
        "attempts": attempts,
        "last_exit_code": exit_code,
        "stderr_tail": stderr_tail,
        "error_fingerprint": fingerprint,
        "created_at": time.time(),
        "dead_lettered_by": "dispatch",
    }, indent=2))
    return fp


def _diag_path(root: Path, message_id: str) -> Path:
    return root / "governor" / "attempt_diag" / f"{message_id}.json"


def _read_attempt_diag(root: Path, message_id: str) -> dict:
    p = _diag_path(root, message_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _write_attempt_diag(root: Path, message_id: str, diag: dict) -> None:
    """Best-effort per-message diagnostics of the most recent attempt."""
    try:
        p = _diag_path(root, message_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(diag, default=str))
    except OSError:
        pass  # diagnostics, not accounting — never blocks the path


def _run_capped(cmd: list[str], worktree: Path, mailroom: Path, *,
                wall_cap: int, task_id: str, run_id: str,
                role: str) -> tuple[int | None, str, bool, bool]:
    """Run the agent process under supervision (W1-4).

    A poll loop instead of subprocess.run(timeout=...), because three things
    must happen DURING the invocation, not after it:
      - a checkpoint (current patches, rewritten in place) every 300 s, so a
        hard kill loses at most 5 minutes — one ~45-minute invocation lost
        everything to a timeout kill on 2026-07-26;
      - a HALT re-check: the operator's kill switch must stop in-flight work
        at the next poll tick, not after INVOKE_TIMEOUT more seconds;
      - a SIGTERM handler (the supervisor's `timeout` sends one): bundle
        before dying, never after.
    Each abnormal stop writes a full recovery bundle BEFORE terminating the
    child. Returns (rc, stdout_tail, stderr_tail, stop_reason) where
    stop_reason is one of None (child exited), "timeout", "sigterm",
    "halt" — each distinct in telemetry; a supervisor SIGTERM is not a
    wall-clock timeout. rc is None on any abnormal stop. stdout_tail
    carries the CLI's machine-readable usage payload (W2-1 seam).
    """
    import signal  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    from agents import recovery as recovery_mod  # noqa: PLC0415

    got_term = {"flag": False}

    def _on_term(signum, frame):
        got_term["flag"] = True

    prev_handler = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGTERM, _on_term)
    out_f = tempfile.TemporaryFile("w+")
    err_f = tempfile.TemporaryFile("w+")

    def _stderr_tail() -> str:
        try:
            err_f.seek(0)
            return _tail(err_f.read())
        except (OSError, ValueError):
            return ""

    def _stop(trigger: str, proc) -> None:
        recovery_mod.write_bundle(worktree, mailroom, task_id=task_id,
                                  run_id=run_id, role=role, trigger=trigger,
                                  stderr_tail=_stderr_tail())
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    def _stdout_tail() -> str:
        try:
            out_f.seek(0)
            return _tail(out_f.read())
        except (OSError, ValueError):
            return ""

    stop_reason: str | None = None
    try:
        try:
            proc = subprocess.Popen(cmd, cwd=worktree, stdout=out_f,
                                    stderr=err_f, text=True)
        except FileNotFoundError as e:
            return 127, "", str(e), None
        next_ckpt = started = time.time()
        next_ckpt += recovery_mod.CHECKPOINT_INTERVAL
        while True:
            rc = proc.poll()
            if rc is not None:
                break
            now = time.time()
            if got_term["flag"]:
                _stop("sigterm", proc)
                rc, stop_reason = None, "sigterm"
                break
            if (mailroom / "HALT").exists():
                _stop("halt", proc)
                rc, stop_reason = None, "halt"
                break
            if now - started >= wall_cap:
                _stop("timeout", proc)
                rc, stop_reason = None, "timeout"
                break
            if now >= next_ckpt:
                recovery_mod.write_checkpoint(worktree, mailroom,
                                              task_id=task_id, run_id=run_id)
                next_ckpt = now + recovery_mod.CHECKPOINT_INTERVAL
            time.sleep(0.1)
        return rc, _stdout_tail(), _stderr_tail(), stop_reason
    finally:
        signal.signal(signal.SIGTERM, prev_handler)
        out_f.close()
        err_f.close()


def _assess_anti_loop(mailroom: Path, worktree: Path, *, task_id: str,
                      tier: str, packet: dict | None, res: dict | None,
                      result_error: str | None, stderr_tail: str,
                      role: str | None = None):
    """Build an AttemptState from what this invocation left behind and let
    the controller judge it. Result fields win where a valid result exists;
    git supplies the diff either way (the breakers must see what actually
    changed, not what the agent claims changed)."""
    import hashlib  # noqa: PLC0415

    from agents import anti_loop as al  # noqa: PLC0415

    def _git(*args: str) -> str:
        try:
            p = subprocess.run(["git", "-C", str(worktree), *args],
                               capture_output=True, text=True, timeout=60)
            return p.stdout if p.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""

    diff_text = _git("diff", "HEAD")
    status = _git("status", "--porcelain")
    # The breakers see what ACTUALLY changed, never what the agent claims
    # changed: git status supplies every touched path (including untracked
    # files, which numstat misses), and the result's files_modified claim
    # can only ADD paths, never subtract them. W2-4 review reproduced an
    # agent editing agents/governor/policy.yaml while claiming
    # files_modified=["README.md"] — the claim-first version acked that as
    # a completed success.
    git_files: list[str] = []
    for ln in status.splitlines():
        path = ln[3:].strip()
        if " -> " in path:  # rename: "R  old -> new" — the new path counts
            path = path.split(" -> ", 1)[1]
        if path:
            git_files.append(path)
    lines_changed = 0
    for ln in _git("diff", "HEAD", "--numstat").splitlines():
        parts = ln.split("\t")
        if len(parts) == 3:
            for n in parts[:2]:
                if n.isdigit():
                    lines_changed += int(n)
    claimed = list((res or {}).get("files_modified") or [])
    files_changed = sorted(set(git_files) | set(claimed))
    if not lines_changed and res:
        lines_changed = (res.get("lines_added") or 0) + \
            (res.get("lines_deleted") or 0)
    tests = (res or {}).get("tests") or []
    criteria = (res or {}).get("acceptance_criteria") or []
    state = al.AttemptState(
        last_error=result_error or stderr_tail or "",
        files_changed=files_changed,
        lines_changed=lines_changed,
        tests_run=[t.get("command", "") for t in tests],
        failing_tests=sum(1 for t in tests if t.get("exit_code") != 0)
        if tests else None,
        proposed_next_action=(res or {}).get("escalation_reason")
        or (res or {}).get("blocked_reason")
        or ((res or {}).get("summary") or "")[-200:],
        criteria_passed=sum(1 for c in criteria
                            if c.get("status") == "passed")
        if criteria else None,
        stated_plan=(res or {}).get("summary") or "",
        worktree_hash=hashlib.sha256(
            (status + diff_text).encode()).hexdigest()[:16]
        if (status or diff_text) else "",
        tier=tier,
        cost_usd=None,
    )
    ctrl = al.AntiLoopController(mailroom, task_id)
    return ctrl.assess(state, packet=packet, diff_text=diff_text,
                       previously_passing_now_failing=_regression_check(
                           mailroom, task_id, res),
                       role=role)


def _regression_check(mailroom: Path, task_id: str,
                      res: dict | None) -> bool:
    """A previously-passing required check now failing is a breaker trip.

    Baseline: <mailroom>/governor/test_baseline/<task_id>.json — commands
    observed green on an earlier attempt. Updated with this attempt's green
    commands after comparison.
    """
    p = mailroom / "governor" / "test_baseline" / f"{task_id}.json"
    try:
        baseline = set(json.loads(p.read_text()))
    except (OSError, json.JSONDecodeError):
        baseline = set()
    tests = (res or {}).get("tests") or []
    now_red = {t.get("command") for t in tests if t.get("exit_code") != 0}
    now_green = {t.get("command") for t in tests if t.get("exit_code") == 0}
    regressed = bool(baseline & now_red)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(sorted(baseline | now_green)))
    except OSError:
        pass
    return regressed


#: Consecutive degraded-preflight invocations allowed before dispatch stops
#: spending on unverifiable work and probes for gh recovery instead
#: (PM-agreed option 2). Clean invocations reset the counter — accumulated
#: unrelated blips must never halt a healthy org.
DEGRADED_STREAK_LIMIT = 10


def _degraded_streak(mailroom: Path) -> int:
    try:
        return int(json.loads(
            (mailroom / "governor" / "degraded_streak.json").read_text()
        )["count"])
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return 0


def _set_degraded_streak(mailroom: Path, count: int) -> None:
    try:
        p = mailroom / "governor" / "degraded_streak.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"count": count, "updated_at": time.time()}))
    except OSError:
        pass


def run_preflight(msg: dict, packet: dict | None, *, role: str,
                  mailroom: Path, dry_run: bool):
    """W1-3 preflight. Feature flag PREFLIGHT=0 disables (rollback path).

    On a dry run the blocked-records directory is withheld so preflight
    cannot write (clear/bump) — a dry run stays pure read-only, at the cost
    of not reporting repeat_unchanged in its printed decision.
    """
    if os.environ.get(preflight_mod.FLAG, "1") == "0":
        return None
    return preflight_mod.preflight(
        msg, packet=packet, role=role,
        blocked_dir=None if dry_run else mailroom / "blocked")


def dispatch(role: str, message_id: str, worktree: Path, *,
             dry_run: bool = False, fake_agent: str | None = None) -> Outcome:
    mailroom = mailroom_root()
    tele = JsonlTelemetry(mailroom / "telemetry" / "invocations.jsonl")

    # 1 — HALT. Checked before anything else, including the budget ledger:
    # a halted org must not fail-closed its way into noise.
    if (mailroom / "HALT").exists():
        out = Outcome(decision=DispatchDecision.SUPPRESSED_HALT.value,
                      reason="mailroom/HALT is set", message_id=message_id,
                      role=role)
        if not dry_run:
            tele.suppressed(role=role, message_id=message_id,
                            suppressed_reason="halt")
        return out

    # 1.5 — provider session/rate cap for this ROLE. A cap belongs to the
    # provider, not the message: once detected (below, post-invoke), every
    # dispatch for the role is suppressed here, BEFORE spending, until the
    # marker expires. Without this the 2026-07-27 shape recurs — the CLI
    # says "You've hit your session limit", exits rc=0, and each queued
    # message burns its attempts against a provider that is refusing.
    #
    # No task_id is reported here and that is not an omission: the gate sits
    # ahead of the message load (step 3), so the message — and therefore its
    # task — is not yet known. A cap is role-scoped; reading the message to
    # decorate the suppression record would be work done on behalf of a
    # provider that is already refusing.
    limit = provider_limit_mod.active(mailroom, role)
    if limit is not None:
        out = Outcome(
            decision=DispatchDecision.SUPPRESSED_PREFLIGHT.value,
            reason=(f"provider limit for {role}: {limit.get('matched')!r} "
                    f"({limit['seconds_remaining']}s remaining; "
                    f"rm mailroom/blocked/provider-limit-{role}.json to retry)"),
            message_id=message_id, role=role,
            extra={"provider_limit": limit})
        if not dry_run:
            tele.suppressed(role=role, message_id=message_id,
                            suppressed_reason="provider_limit")
        return out

    # 2 — budget ledger, fail-closed. Cannot record spend => do not spend.
    try:
        bl = SqliteBudgetLedger(
            mailroom / "governor" / BUDGET_DB,
            read_only=dry_run,
        )
    except BudgetLedgerUnavailable as e:
        print(f"budget ledger unavailable, refusing to invoke: {e}",
              file=sys.stderr)
        return Outcome(decision=DispatchDecision.SUPPRESSED_GOVERNOR.value,
                       reason=f"budget ledger unavailable: {e}",
                       message_id=message_id, role=role, exit_code=3)

    # 3 — the message itself. Unloadable (absent, ambiguous, schema-invalid)
    # is a structured suppression, not a traceback: the poll loop must keep
    # its zero-model-call guarantee even against a poison message.
    try:
        msg = find_message(mailroom, message_id)
    except (ValueError, ValidationError) as e:
        out = Outcome(decision=DispatchDecision.SUPPRESSED_PREFLIGHT.value,
                      reason=f"message unloadable: {e}", message_id=message_id,
                      role=role)
        if not dry_run:
            tele.suppressed(role=role, message_id=message_id,
                            suppressed_reason="message_invalid")
        return out
    message_id = msg["message_id"]
    task_id = msg["task_id"]

    # A message addressed to another role is not ours to run OR to retire —
    # acking it here would write into the wrong cursor while the addressee
    # still sees it unacked (cross-role double processing).
    if msg["to_role"] != role:
        out = Outcome(decision=DispatchDecision.SUPPRESSED_PREFLIGHT.value,
                      reason=f"role mismatch: message is addressed to "
                             f"{msg['to_role']}, dispatcher runs as {role}",
                      message_id=message_id, task_id=task_id, role=role)
        if not dry_run:
            tele.suppressed(role=role, task_id=task_id, message_id=message_id,
                            suppressed_reason="role_mismatch")
        return out

    acked = ledger_mod.acked_ids(mailroom, role)
    if message_id in acked:
        out = Outcome(decision=DispatchDecision.SUPPRESSED_PREFLIGHT.value,
                      reason="message already acked", message_id=message_id,
                      task_id=task_id, role=role)
        if not dry_run:
            tele.suppressed(role=role, task_id=task_id, message_id=message_id,
                            suppressed_reason="already_acked")
        return out

    # Duplicate idempotency key already processed => this copy retires without
    # an invocation ("a duplicate idempotency_key invokes once").
    dup = [m for m in ledger_mod.all_messages(mailroom)
           if m.get("idempotency_key") == msg["idempotency_key"]
           and m.get("message_id") != message_id
           and m.get("message_id") in acked]
    if dup:
        out = Outcome(decision=DispatchDecision.SUPPRESSED_PREFLIGHT.value,
                      ack=AckDecision.ACK.value,
                      reason=f"duplicate of acked {dup[0]['message_id'][:8]}",
                      message_id=message_id, task_id=task_id, role=role)
        if not dry_run:
            ack_message(mailroom, role, message_id)
            tele.suppressed(role=role, task_id=task_id, message_id=message_id,
                            suppressed_reason="duplicate_idempotency_key")
        return out

    # Packet, when one exists for the task. Legacy messages have none.
    packet = None
    ppath = packet_path(worktree, task_id)
    if ppath.exists():
        try:
            packet = load_packet(ppath)
        except PacketError as e:
            # An unreadable packet is a blocked task, not a free-form one.
            out = Outcome(decision=DispatchDecision.SUPPRESSED_PREFLIGHT.value,
                          reason=f"packet invalid: {e}", message_id=message_id,
                          task_id=task_id, role=role)
            if not dry_run:
                tele.suppressed(role=role, task_id=task_id,
                                message_id=message_id,
                                suppressed_reason="packet_invalid")
            return out
        # CC-1 pre-invoke gate: a packet carrying a command the ratified
        # policy rejects fails HERE, before any model spend — same standing
        # as a schema-invalid packet. The runner enforces again at
        # execution (defense in depth).
        #
        # L-8 (2026-08-03, observed live): gate WORK-BEARING messages only.
        # This gate is about not spending an invocation on a packet whose
        # checks cannot legally run. A governance message — the ANSWER that
        # says "this packet is superseded", a SYNC, a STATUS — never executes
        # required_checks, so blocking it buys nothing and costs everything:
        # an invalid packet made its own task's mailbox UNDELIVERABLE,
        # including the very ruling that would retire the packet. That is a
        # deadlock only out-of-band intervention can break. The orchestrator's
        # superseded-ruling for TASK-999-S2 was suppressed by the exact packet
        # it was superseding.
        cmd_violations = (validate_packet_commands(packet)
                          if msg.get("intent") in WORK_INTENTS else [])
        if cmd_violations:
            out = Outcome(decision=DispatchDecision.SUPPRESSED_PREFLIGHT.value,
                          reason="packet command policy: "
                                 + "; ".join(cmd_violations),
                          message_id=message_id, task_id=task_id, role=role)
            if not dry_run:
                tele.suppressed(role=role, task_id=task_id,
                                message_id=message_id,
                                suppressed_reason="packet_command_policy")
            return out

    # 4 — preflight: every zero-token reason not to invoke. On a block the
    # message is ACKED and the durable blocked record carries the state —
    # retaining it would mean redelivery forever, the failure being fixed.
    verdict = run_preflight(msg, packet, role=role, mailroom=mailroom,
                            dry_run=dry_run)
    if verdict is not None and not verdict.ok:
        decision = (DispatchDecision.SUPPRESSED_UNCHANGED_BLOCKER
                    if verdict.repeat_unchanged
                    else DispatchDecision.SUPPRESSED_PREFLIGHT)
        out = Outcome(decision=decision.value, ack=AckDecision.ACK.value,
                      reason=verdict.reason, message_id=message_id,
                      task_id=task_id, role=role,
                      extra={"fingerprint": verdict.fingerprint,
                             "resume_condition": verdict.resume_condition,
                             "degraded_checks": verdict.degraded_checks})
        if not dry_run:
            rec = preflight_mod.record_block(
                mailroom / "blocked", role, task_id=task_id,
                message_id=message_id, verdict=verdict)
            ack_message(mailroom, role, message_id)
            tele.suppressed(role=role, task_id=task_id, message_id=message_id,
                            suppressed_reason=(
                                "unchanged_blocker" if verdict.repeat_unchanged
                                else f"preflight:{verdict.reason}"),
                            fingerprint=verdict.fingerprint,
                            check_count=rec["check_count"])
        return out

    # PM-agreed degraded budget (W2-4): consecutive invocations that ran with
    # degraded preflight checks are counted; past the limit, dispatch stops
    # spending on unverifiable work and probes for gh recovery instead —
    # degrade-to-idle-with-reason, self-resuming, never a halt. A clean
    # invocation resets the counter (accumulated unrelated blips must never
    # stop a healthy org).
    degraded_run = bool(verdict is not None and verdict.degraded_checks)
    if degraded_run and not dry_run \
            and _degraded_streak(mailroom) >= DEGRADED_STREAK_LIMIT:
        probe = preflight_mod._gh_cli("auth", "status")
        if probe is None:
            out = Outcome(
                decision=DispatchDecision.SUPPRESSED_GOVERNOR.value,
                reason=f"degraded budget exhausted: "
                       f"{DEGRADED_STREAK_LIMIT} consecutive degraded "
                       f"invocations and the gh probe is still failing",
                message_id=message_id, task_id=task_id, role=role,
                extra={"degraded_checks": verdict.degraded_checks})
            tele.suppressed(role=role, task_id=task_id,
                            message_id=message_id,
                            suppressed_reason="degraded_budget",
                            degraded_checks=verdict.degraded_checks)
            return out
        _set_degraded_streak(mailroom, 0)

    # 5 — per-task governor. A role the policy does not know is a denial, not
    # a crash (the raw governor raises KeyError — pinned in W1-1).
    gov = Governor(
        worktree / "agents" / "governor" / "policy.yaml",
        mailroom / "governor" / GOVERNOR_DB,
        read_only=dry_run,
    )
    try:
        allowed, reason = gov.allow(role, task_id)
    except KeyError as e:
        allowed, reason = False, f"role not in policy: {e}"
    except OSError as e:
        # e.g. the governor's repo-side dead-letter write failing in an
        # unexpected checkout — an authorisation error must deny, not crash.
        allowed, reason = False, f"governor error: {e}"
    if not allowed:
        out = Outcome(decision=DispatchDecision.SUPPRESSED_GOVERNOR.value,
                      reason=reason, message_id=message_id, task_id=task_id,
                      role=role)
        if not dry_run:
            tele.suppressed(role=role, task_id=task_id, message_id=message_id,
                            suppressed_reason=f"governor:{reason}")
        return out

    # 5.5 — aggregate run budget (Lane B port; AlwaysAllow until it lands).
    policy = load_policy(worktree / "agents" / "governor")
    tier = resolve_tier(task_id, packet)
    port = load_run_budget_port(
        read_only=dry_run,
        mailroom=mailroom if dry_run else None,
    )
    rbv = port.check(role=role, task_id=task_id, tier=tier)
    if not rbv.allowed:
        if rbv.reassign_to and msg["hop_count"] + 1 >= msg["max_hops"]:
            # Refuse, retain, surface. A forward at hop 5/6 mints a 6/6
            # message that nothing can reply to — a dead-end wearing a
            # reassignment's clothes. (Live queue precedent: 67cefe20 sits at
            # 5/6 today.) The retained original costs zero model tokens per
            # poll; pm re-triages from the surfaced reason.
            out = Outcome(decision=DispatchDecision.SUPPRESSED_GOVERNOR.value,
                          reason=f"run budget: {rbv.reason}; reassignment to "
                                 f"{rbv.reassign_to} REFUSED: hop cap "
                                 f"({msg['hop_count']}/{msg['max_hops']})",
                          message_id=message_id, task_id=task_id, role=role,
                          extra={"reassign_refused": "hop_cap",
                                 "degradation_level": rbv.degradation_level})
            if not dry_run:
                tele.suppressed(role=role, task_id=task_id,
                                message_id=message_id,
                                suppressed_reason=f"run_budget:{rbv.reason}:"
                                                  "reassign_refused_hop_cap",
                                degradation_level=rbv.degradation_level)
            return out
        if rbv.reassign_to:
            # Forward the work to the role with spare capacity; retain the
            # original (its owner is throttled; preflight retires it once the
            # forwarded copy completes). Idempotency key makes this a
            # forward-once.
            fwd_key = f"reassign:{message_id}:{rbv.reassign_to}"
            already = any(m.get("idempotency_key") == fwd_key
                          for m in ledger_mod.all_messages(mailroom))
            if not dry_run and not already:
                fwd = dict(msg)
                fwd["message_id"] = str(uuid.uuid4())
                fwd["idempotency_key"] = fwd_key
                fwd["to_role"] = rbv.reassign_to
                fwd["hop_count"] = msg["hop_count"] + 1
                fwd["body_markdown"] = (
                    f"[REASSIGNED from {role} at degradation level "
                    f"{rbv.degradation_level}: {rbv.reason}]\n\n"
                    + msg["body_markdown"])
                ledger_mod.VALIDATOR.validate(fwd)
                ts = ledger_mod.datetime.now(ledger_mod.timezone.utc).strftime(
                    "%Y%m%dT%H%M%S%fZ")
                fp = (mailroom / "messages" /
                      f"{ts}-{role}-to-{rbv.reassign_to}-{fwd['intent']}-"
                      f"{fwd['message_id'][:8]}.json")
                with fp.open("x") as f:
                    json.dump(fwd, f, indent=2)
            out = Outcome(decision=DispatchDecision.SUPPRESSED_GOVERNOR.value,
                          reason=f"run budget: {rbv.reason}; reassigned to "
                                 f"{rbv.reassign_to}",
                          message_id=message_id, task_id=task_id, role=role,
                          extra={"reassigned_to": rbv.reassign_to,
                                 "degradation_level": rbv.degradation_level})
        else:
            out = Outcome(decision=DispatchDecision.SUPPRESSED_GOVERNOR.value,
                          reason=f"run budget: {rbv.reason}",
                          message_id=message_id, task_id=task_id, role=role,
                          extra={"degradation_level": rbv.degradation_level})
        if not dry_run:
            tele.suppressed(role=role, task_id=task_id, message_id=message_id,
                            suppressed_reason=f"run_budget:{rbv.reason}",
                            degradation_level=rbv.degradation_level)
        return out

    # Anti-loop tier escalation wins over the packet/default class (W2-4):
    # a task escalated to yellow must not quietly run green again.
    if os.environ.get("ANTI_LOOP", "1") != "0":
        from agents import anti_loop as anti_loop_mod  # noqa: PLC0415
        escalated = anti_loop_mod.tier_override(mailroom, task_id)
        if escalated:
            tier = escalated
    budgets = resolve_budgets(policy, packet, tier)
    max_attempts = int(budgets.get("max_attempts", 2))

    if dry_run:
        # Everything except state writes and the model call. Prospective
        # attempt count is read, not written — a dry run must cost nothing
        # and consume nothing.
        return Outcome(decision=DispatchDecision.INVOKE.value,
                       reason="dry run: would invoke",
                       message_id=message_id, task_id=task_id, role=role,
                       attempts=bl.attempts(message_id) + 1,
                       max_attempts=max_attempts,
                       extra={"tier": tier, "dry_run": True})

    # 6 — count the attempt BEFORE invoking. An agent that never returns a
    # result is still an attempt; counting afterwards cannot bound it.
    attempts = bl.increment_attempt(message_id, task_id, role)

    # 7 — the per-MESSAGE hard cap. This is the line that turns "180
    # invocations of one message over 6h13m" into "max_attempts, then a
    # durable dead-letter and an ack".
    if attempts > max_attempts:
        # The invocation that trips the cap never runs, so its diagnostics
        # come from the sidecar the PREVIOUS attempt persisted (below, after
        # step 11) — otherwise every dead-letter would carry empty evidence
        # and pm-lite re-triage would have nothing to triage with.
        diag = _read_attempt_diag(mailroom, message_id)
        dl = write_dead_letter(mailroom, task_id=task_id, role=role,
                               message_id=message_id,
                               reason=f"attempt cap exceeded: attempt "
                                      f"{attempts} > max {max_attempts} "
                                      f"for tier {tier}",
                               attempts=attempts,
                               exit_code=diag.get("exit_code"),
                               stderr_tail=diag.get("stderr_tail", ""),
                               fingerprint=diag.get("error_fingerprint"))
        ack_message(mailroom, role, message_id)
        gov.record(role, task_id, False)
        tele.suppressed(role=role, task_id=task_id, message_id=message_id,
                        suppressed_reason="dead_lettered_attempts",
                        attempt_number=attempts, dead_letter=str(dl))
        return Outcome(decision=DispatchDecision.DEAD_LETTERED_ATTEMPTS.value,
                       ack=AckDecision.ACK_DEAD_LETTER.value,
                       reason="attempt cap exceeded", message_id=message_id,
                       task_id=task_id, role=role, attempts=attempts,
                       max_attempts=max_attempts,
                       extra={"dead_letter": str(dl)})

    # 8 — telemetry opens the invocation record.
    run_id = tele.start(task_id=task_id, role=role, message_id=message_id,
                        decision=DispatchDecision.INVOKE.value,
                        attempt_number=attempts, task_class=tier,
                        started_at=time.time())

    # 8.2 — record the worktree base BEFORE the agent runs (proof #6): the
    # SHA the worktree was created from, observed while the tree is still
    # the creation state. Ancestry against it catches orphan branches and
    # history rewrites; absence fails #6 closed.
    try:
        _bp = subprocess.run(["git", "-C", str(worktree), "rev-parse",
                              "HEAD"], capture_output=True, text=True,
                             timeout=30)
        base_sha = _bp.stdout.strip() if _bp.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        base_sha = None

    # 8.5 — dependency provisioning (A2 amendment): dispatcher-owned and
    # privileged — derived from the packet's commands, never expressible in
    # them (npm ci is banned in packets, yet npm checks cannot run without
    # node_modules in a fresh worktree). Deliberately BELOW the step-6/7
    # attempt accounting: a provisioning failure is a counted attempt, so a
    # broken lockfile dead-letters at the cap instead of looping un-metered.
    # Not charged against the packet's wall-clock cap; timed + telemetered.
    provisioning = run_provisioning(packet, worktree, mailroom)
    if provisioning and not provisioning_ok(provisioning):
        err = "dependency provisioning failed: " + "; ".join(
            f"{r['cmd']!r} rc={r['rc']}" for r in provisioning
            if r.get("rc") != 0)
        tele.finish(run_id, result_error=err, provisioning=provisioning,
                    attempt_number=attempts, completed_at=time.time())
        return Outcome(decision=DispatchDecision.INVOKE.value,
                       ack=AckDecision.RETAIN.value, reason=err,
                       message_id=message_id, task_id=task_id, role=role,
                       attempts=attempts, max_attempts=max_attempts,
                       invoked=False, extra={"provisioning": provisioning})

    # 9 — deterministic prepass: packet-declared T0 commands, zero tokens.
    # CC-1: runs under the packet COMMAND POLICY (shlex-parsed, bans
    # enforced, no shell) via the same runner as required_checks — the old
    # shell=True runner that swallowed exit codes is gone. Prepass stays
    # informational (T0 signal, not a gate); its rc is recorded, branched
    # on only by telemetry consumers.
    prepass_results = [
        {"cmd": r.cmd, "rc": r.rc, "policy": r.policy,
         **({"timeout": PREPASS_TIMEOUT} if r.timed_out else {})}
        for r in run_commands(
            (packet or {}).get("deterministic_prepass") or [],
            worktree, timeout=PREPASS_TIMEOUT, context="prepass")
    ]

    # 10 — the model call, wall-clock capped. A pending anti-loop strategy
    # note is embedded (and consumed): the re-prompt names the loop and
    # forbids the prior approach.
    prompt = build_prompt(role, msg, run_id, mailroom)
    if os.environ.get("ANTI_LOOP", "1") != "0":
        from agents import anti_loop as anti_loop_mod  # noqa: PLC0415
        note = anti_loop_mod.pending_strategy_note(mailroom, task_id)
        if note:
            prompt = f"{prompt}\n\n{note}"
            anti_loop_mod.consume_strategy_note(mailroom, task_id)
    wall_cap = int(budgets.get("max_wall_clock_seconds", 1200))
    if fake_agent:
        # Context goes to a tempfile, not the worktree: the dispatcher must
        # not be the thing that dirties the tree it supervises.
        import tempfile  # noqa: PLC0415
        ctxf = tempfile.NamedTemporaryFile(
            "w", prefix=f"dispatch-ctx-{run_id[:8]}-", suffix=".json",
            delete=False)
        json.dump({
            "message": msg, "run_id": run_id, "attempt": attempts,
            "result_path": str(worktree / RESULT_FILENAME),
            "schema_path": str(_REPO_ROOT / RESULT_SCHEMA_REL),
            "prompt": prompt,
        }, ctxf)
        ctxf.close()
        cmd = [fake_agent, ctxf.name]
    else:
        cmd = role_command(role, prompt, mailroom, packet)
    started = time.time()
    rc, stdout_tail, stderr_tail, stop_reason = _run_capped(
        cmd, worktree, mailroom, wall_cap=wall_cap, task_id=task_id,
        run_id=run_id, role=role)
    duration = time.time() - started
    timed_out = stop_reason == "timeout"
    halted = stop_reason == "halt"
    # Usage parsing runs for fake agents too: the fake harness is how the
    # capture seam is proven without a live invocation (PM constraint).
    # usage_parse_error rides the telemetry finish event so "usage never
    # parsed" is queryable in invocations.jsonl, not buried in stderr.
    usage, usage_parse_error = _provider_usage(role, stdout_tail)
    # Provider refusal detection. The CLI exits rc=0 on a session cap, so
    # this reads its OUTPUT, not its status — the org's founding lesson
    # applied to the provider itself. One detection quiets the whole role.
    provider_refusal = provider_limit_mod.detect(stdout_tail, stderr_tail)
    if provider_refusal and not dry_run:
        marker = provider_limit_mod.mark(
            mailroom, role, matched=provider_refusal, run_id=run_id)
        print(f"PROVIDER LIMIT [{role}]: {provider_refusal!r} — role quiet "
              f"until the marker expires ({marker})", file=sys.stderr)
    # Degraded-budget accounting: this invocation happened; whether it ran
    # on degraded checks decides the streak.
    _set_degraded_streak(mailroom,
                         _degraded_streak(mailroom) + 1 if degraded_run
                         else 0)

    # 11 — the result file is the only truth. rc==0 carried zero bits of
    # information across 1,408 measured invocations; it is not consulted for
    # the ack decision at all.
    result_status: str | None = None
    result_error: str | None = None
    success = False
    ack = AckDecision.RETAIN
    res: dict | None = None
    completion_proofs: list | None = None
    proofs: list = []
    required_checks_tele: list | None = None
    try:
        res = load_result(worktree / RESULT_FILENAME)
        result_status = res["status"]
    except ResultError as e:
        result_error = str(e)
        if stop_reason == "timeout":
            result_error = f"timeout after {wall_cap}s; {result_error}"
        elif stop_reason:
            result_error = f"stopped ({stop_reason}); {result_error}"

    # 11.2 — CC-3: sweep the result artifact into the durable run record
    # BEFORE cleanliness is evaluated anywhere — proof #7, the anti-loop
    # changed-file set (11.5), the step-12 recovery inspection, and the
    # supervisor's clean-tree removal guard all judge by what is in the
    # tree. The agent writes the file in-worktree (contract unchanged);
    # from the read onward its lifecycle is the dispatcher's. Valid or
    # invalid it is evidence, so it moves — never deleted — to
    # mailroom/runs/<run_id>/.
    sweep_result(worktree, mailroom, run_id)

    if res is not None and is_ackable(res):
        # Decision only — applied AFTER the anti-loop assessment, which
        # may pre-empt it: a "completed" result that modified a
        # prohibited file terminates instead of acking as success.
        if result_status == "completed":
            # 11.05 — CC-1: the packet's required_checks are AUTHORITATIVE
            # and the DISPATCHER runs them itself, after the agent returns
            # and before any ack. A failing check beats a "completed"
            # self-report. Per-check rc rides telemetry; the runner never
            # swallows one. (The command policy governs THESE commands and
            # the prepass only — never the agent's own tools.)
            declared = (packet or {}).get("required_checks") or []
            check_results = run_commands(declared, worktree)
            # Absent stays None, never zero-length: "no packet declared
            # checks" and "checks ran" must be distinguishable.
            required_checks_tele = (checks_telemetry(check_results)
                                    if declared else None)
            checks_refused = failed_checks_reason(check_results)

            # 11.1 — CC-2: "completed" is a CLAIM. The dispatcher runs the
            # ratified proofs #1–#14 (agents/completion.py; #15 is the
            # accounting-before-ack ordering, satisfied below) before any
            # ack applies. The fabricated payload {"status": "completed",
            # "pushed": false, "commit_sha": "0000000", ...} was ackable
            # here on the agent's word alone. COMPLETION_PROOFS=0 is the
            # operator rollback lever (ANTI_LOOP idiom); default ON — it
            # does NOT disable the required checks above.
            proof_refused = None
            if os.environ.get("COMPLETION_PROOFS", "1") != "0":
                proofs = verify_completion(
                    res, worktree=worktree, mailroom=mailroom,
                    run_id=run_id, packet=packet, base_sha=base_sha,
                    check_results=check_results if declared else None,
                    attempts=attempts, duration_seconds=duration,
                    usage=usage, role=role, intent=msg.get("intent"))
                completion_proofs = proofs_telemetry(proofs)
                proof_refused = refusal(proofs)

                # #12/#13 (and a known-spend ceiling breach): CIRCUIT
                # BREAK — terminate via the dead-letter path, dispatcher-
                # authored status, never ack-as-success and never a plain
                # retain-and-retry.
                broken = breaks(proofs)
                if broken:
                    reason = "completion proof circuit break: " + "; ".join(
                        f"#{p.number} {p.proof_id}: {p.detail}"
                        for p in broken)
                    persist_bundle(mailroom, run_id, proofs,
                                   extra={"circuit_break": True})
                    dl = write_dead_letter(
                        mailroom, task_id=task_id, role=role,
                        message_id=message_id, reason=reason,
                        attempts=attempts, exit_code=rc,
                        stderr_tail=stderr_tail, fingerprint=None)
                    ack_message(mailroom, role, message_id)
                    gov.record(role, task_id, False)
                    try:
                        bl.record_spend(role=role, task_id=task_id,
                                        run_id=run_id, success=False,
                                        cash_usd=usage.get("cash_usd"),
                                        allowance_pct=usage.get(
                                            "allowance_pct_estimated"),
                                        input_tokens=usage.get(
                                            "input_tokens"),
                                        output_tokens=usage.get(
                                            "output_tokens"))
                    except BudgetLedgerUnavailable as e:
                        print(f"WARNING: spend record failed: {e}",
                              file=sys.stderr)
                    tele.finish(run_id, result_status=result_status,
                                result_error=reason,
                                completion_proofs=completion_proofs,
                                required_checks=required_checks_tele,
                                provisioning=provisioning or None,
                                usage_parse_error=usage_parse_error,
                                exit_code=rc, stop_reason=stop_reason,
                                duration_seconds=round(duration, 3),
                                attempt_number=attempts,
                                completed_at=time.time(), **usage)
                    return Outcome(
                        decision=DispatchDecision.CIRCUIT_BROKEN.value,
                        ack=AckDecision.ACK_DEAD_LETTER.value,
                        reason=reason, message_id=message_id,
                        task_id=task_id, role=role, attempts=attempts,
                        max_attempts=max_attempts,
                        exit_code=rc if rc is not None else -1,
                        invoked=True, result_status=result_status,
                        extra={"dead_letter": str(dl)})

            refused = "; ".join(
                r for r in (checks_refused, proof_refused) if r) or None
            if refused:
                result_error = refused
            else:
                ack = AckDecision.ACK
                success = True
        else:  # blocked — ackable, never a success
            ack = AckDecision.ACK
    # needs_retry: actionable, retained; step 7 retires it at the cap.

    # 11.5 — anti-loop controller (W2-4): every one of ~50 measured
    # invocations of one task produced an identical error signature with
    # zero new evidence; signature comparison alone would have caught it on
    # attempt 2. Breakers terminate BEFORE any ack applies.
    if os.environ.get("ANTI_LOOP", "1") != "0":
        anti = _assess_anti_loop(mailroom, worktree, task_id=task_id,
                                 tier=tier, packet=packet, res=res,
                                 result_error=result_error,
                                 stderr_tail=stderr_tail, role=role)
        if anti.action in ("terminate", "dead_letter"):
            dl = write_dead_letter(
                mailroom, task_id=task_id, role=role, message_id=message_id,
                reason=f"anti-loop {anti.action}: {anti.reason}",
                attempts=attempts, exit_code=rc, stderr_tail=stderr_tail,
                fingerprint=None)
            ack_message(mailroom, role, message_id)
            gov.record(role, task_id, False)
            try:
                # Same explicit field mapping as the normal path: the usage
                # dict's vocabulary is wider than record_spend's signature,
                # and a splat crashes AFTER the ack but BEFORE the spend row
                # lands — spend happened, record lost (W2-4 review).
                bl.record_spend(role=role, task_id=task_id, run_id=run_id,
                                success=False,
                                cash_usd=usage.get("cash_usd"),
                                allowance_pct=usage.get(
                                    "allowance_pct_estimated"),
                                input_tokens=usage.get("input_tokens"),
                                output_tokens=usage.get("output_tokens"))
            except BudgetLedgerUnavailable as e:
                print(f"WARNING: spend record failed: {e}", file=sys.stderr)
            tele.finish(run_id, result_status=result_status,
                        anti_loop=anti.action, anti_loop_reason=anti.reason,
                        usage_parse_error=usage_parse_error,
                        completion_proofs=completion_proofs,
                        required_checks=required_checks_tele,
                        provisioning=provisioning or None,
                        exit_code=rc, stop_reason=stop_reason,
                        duration_seconds=round(duration, 3),
                        attempt_number=attempts, completed_at=time.time(),
                        **usage)
            return Outcome(decision=DispatchDecision.CIRCUIT_BROKEN.value,
                           ack=AckDecision.ACK_DEAD_LETTER.value,
                           reason=f"anti-loop {anti.action}: {anti.reason}",
                           message_id=message_id, task_id=task_id, role=role,
                           attempts=attempts, max_attempts=max_attempts,
                           exit_code=rc if rc is not None else -1,
                           invoked=True, result_status=result_status,
                           extra={"dead_letter": str(dl)})
        if anti.action == "escalate_tier":
            tele.suppressed(role=role, task_id=task_id,
                            message_id=message_id,
                            suppressed_reason=f"anti_loop:escalated:"
                                              f"{anti.next_tier}",
                            attempt_number=attempts)
        # force_strategy_change / continue: state persisted by the
        # controller; the next attempt reads the note and the tier.

    # 11.9 — proof #15: accounting BEFORE ack, fail-closed. For a verified
    # completion the spend row, governor row, telemetry finish row and the
    # persisted proof bundle all exist before the message is retired; a
    # ledger write failure refuses the ack (RETAIN) rather than acking
    # unremembered work.
    accounted = False
    if ack is AckDecision.ACK and success:
        try:
            bl.record_spend(role=role, task_id=task_id, run_id=run_id,
                            success=True,
                            cash_usd=usage.get("cash_usd"),
                            allowance_pct=usage.get(
                                "allowance_pct_estimated"),
                            input_tokens=usage.get("input_tokens"),
                            output_tokens=usage.get("output_tokens"))
            spend_err = None
        except BudgetLedgerUnavailable as e:
            spend_err = str(e)
        if spend_err is None:
            gov.record(role, task_id, True)
            if proofs:
                p15 = Proof(15, "accounting_before_ack", True,
                            "spend row, governor row and telemetry finish "
                            "written before ack; bundle persisted")
                proofs = [p15 if p.number == 15 else p for p in proofs]
                completion_proofs = proofs_telemetry(proofs)
            tele.finish(run_id, result_status=result_status,
                        result_error=None,
                        usage_parse_error=usage_parse_error,
                        completion_proofs=completion_proofs,
                        required_checks=required_checks_tele,
                        provisioning=provisioning or None,
                        exit_code=rc, timed_out=timed_out, halted=halted,
                        stop_reason=stop_reason,
                        duration_seconds=round(duration, 3),
                        attempt_number=attempts, prepass=prepass_results,
                        completed_at=time.time(), **usage)
            if proofs:
                persist_bundle(mailroom, run_id, proofs,
                               extra={"acked": True})
            ack_message(mailroom, role, message_id)
            accounted = True
        else:
            ack = AckDecision.RETAIN
            success = False
            result_error = ("completion refused: #15 accounting_before_ack: "
                            f"spend row could not be written before ack: "
                            f"{spend_err}")
            if proofs:
                p15 = Proof(15, "accounting_before_ack", False,
                            f"spend row not writable before ack: {spend_err}")
                proofs = [p15 if p.number == 15 else p for p in proofs]
                completion_proofs = proofs_telemetry(proofs)
    elif ack is AckDecision.ACK:
        ack_message(mailroom, role, message_id)

    # A refused completion's bundle is evidence too.
    if proofs and not accounted:
        persist_bundle(mailroom, run_id, proofs, extra={"acked": False})

    # 12 — recovery: any unsaved work in the tree (dirty or unpushed) gets a
    # verified bundle before the supervisor may consider removal (W1-4).
    from agents.recovery import inspect_worktree  # noqa: PLC0415
    inspect_worktree(worktree, mailroom, task_id=task_id, run_id=run_id,
                     role=role, exit_code=rc, stderr_tail=stderr_tail)

    # Persist this attempt's diagnostics so a later cap-trip dead-letter has
    # evidence to carry (the trip itself never invokes).
    _write_attempt_diag(mailroom, message_id, {
        "run_id": run_id, "attempt": attempts, "exit_code": rc,
        "timed_out": timed_out, "stderr_tail": stderr_tail,
        "error_fingerprint": (res or {}).get("error_fingerprint"),
        "result_error": result_error, "ts": time.time(),
    })

    # 13 / 14 — record and close (non-success and blocked paths; a verified
    # completion already accounted at 11.9, before its ack). Spend recording
    # is fail-closed by design, but at this point the spend has already
    # happened: log loudly and let the NEXT invocation's fail-closed open
    # refuse instead.
    if not accounted:
        gov.record(role, task_id, success)
        try:
            bl.record_spend(role=role, task_id=task_id, run_id=run_id,
                            success=success,
                            cash_usd=usage.get("cash_usd"),
                            allowance_pct=usage.get(
                                "allowance_pct_estimated"),
                            input_tokens=usage.get("input_tokens"),
                            output_tokens=usage.get("output_tokens"))
        except BudgetLedgerUnavailable as e:
            print(f"WARNING: spend record failed after invocation: {e}",
                  file=sys.stderr)
        tele.finish(run_id, result_status=result_status,
                    result_error=result_error,
                    usage_parse_error=usage_parse_error,
                    completion_proofs=completion_proofs,
                    required_checks=required_checks_tele,
                    provisioning=provisioning or None,
                    exit_code=rc, timed_out=timed_out, halted=halted,
                    stop_reason=stop_reason,
                    duration_seconds=round(duration, 3),
                    attempt_number=attempts, prepass=prepass_results,
                    completed_at=time.time(), **usage)
    return Outcome(decision=DispatchDecision.INVOKE.value, ack=ack.value,
                   reason=result_error or (result_status or ""),
                   message_id=message_id, task_id=task_id, role=role,
                   attempts=attempts, max_attempts=max_attempts,
                   exit_code=rc if rc is not None else -1, invoked=True,
                   result_status=result_status,
                   extra={"halted": halted} if halted else {})


def record_suppressed(role: str, reason: str) -> Outcome:
    """Deterministic empty-inbox poll record — replaces the model heartbeat.

    The old heartbeat invoked a model on every 4th empty poll (82 heartbeat
    invocations measured). An empty inbox now costs zero tokens and writes
    one telemetry line proving the poll happened.
    """
    mailroom = mailroom_root()
    tele = JsonlTelemetry(mailroom / "telemetry" / "invocations.jsonl")
    tele.suppressed(role=role, suppressed_reason=reason,
                    decision=DispatchDecision.SUPPRESSED_PREFLIGHT.value)
    return Outcome(decision=DispatchDecision.SUPPRESSED_PREFLIGHT.value,
                   reason=reason, role=role)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="governed dispatcher (one message)")
    ap.add_argument("--role", required=True, choices=["pm", "backend", "frontend"])
    ap.add_argument("--message-id")
    ap.add_argument("--worktree", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--fake-agent")
    ap.add_argument("--record-suppressed", metavar="REASON",
                    help="write a suppressed-decision telemetry record and exit"
                         " (deterministic empty-inbox poll; no model, no state)")
    a = ap.parse_args(argv)

    if a.record_suppressed:
        record_suppressed(a.role, a.record_suppressed).emit()
        return 0
    if not a.message_id or not a.worktree:
        ap.error("--message-id and --worktree are required to dispatch")
    out = dispatch(a.role, a.message_id, a.worktree.resolve(),
                   dry_run=a.dry_run, fake_agent=a.fake_agent)
    out.emit()
    return out.exit_code if out.exit_code == 3 else 0


if __name__ == "__main__":
    sys.exit(main())
