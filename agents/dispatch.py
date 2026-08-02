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
)
from agents.interfaces.states import AckDecision, DispatchDecision  # noqa: E402
from agents.interfaces.telemetry import JsonlTelemetry  # noqa: E402
from agents.postmaster import ledger as ledger_mod  # noqa: E402
from agents import preflight as preflight_mod  # noqa: E402
from jsonschema import ValidationError  # noqa: E402

RESULT_SCHEMA_REL = "agents/interfaces/schemas/result.schema.json"
STDERR_TAIL_LINES = 200
PREPASS_TIMEOUT = 300

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


def load_run_budget_port(warn=None):
    """Lane B's `agents.run_budget.load()` if present, else AlwaysAllow."""
    try:
        import agents.run_budget as rb  # noqa: PLC0415 — deliberate late bind
    except ImportError:
        return run_budget_iface.AlwaysAllow(warn=warn)
    loader = getattr(rb, "load", None)
    if loader is None:
        return run_budget_iface.AlwaysAllow(warn=warn)
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
        f"needs_retry|terminated; \"completed\" requires commit_sha, pushed, "
        f"and acceptance_criteria). Do NOT acknowledge the ledger message — "
        f"the dispatcher owns acknowledgment; an exit code of 0 means nothing "
        f"without a valid result file."
    )


def role_command(role: str, prompt: str, mailroom: Path) -> list[str]:
    """The model CLI for a role. This is the ONLY place a model is spawned."""
    if role == "pm":
        return ["env", "-u", "ANTHROPIC_API_KEY", "claude", "-p", prompt,
                "--dangerously-skip-permissions", "--add-dir", str(mailroom)]
    return ["codex", "exec", "--dangerously-bypass-approvals-and-sandbox",
            "-m", os.environ.get("CODEX_MODEL", "gpt-5.6-sol"),
            "-c", f"model_reasoning_effort={os.environ.get('CODEX_EFFORT', 'high')}",
            prompt]


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
    child. Returns (rc, stderr_tail, timed_out, halted); rc None on kill.
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

    timed_out = halted = False
    try:
        try:
            proc = subprocess.Popen(cmd, cwd=worktree, stdout=out_f,
                                    stderr=err_f, text=True)
        except FileNotFoundError as e:
            return 127, str(e), False, False
        next_ckpt = started = time.time()
        next_ckpt += recovery_mod.CHECKPOINT_INTERVAL
        while True:
            rc = proc.poll()
            if rc is not None:
                break
            now = time.time()
            if got_term["flag"]:
                _stop("sigterm", proc)
                rc, timed_out = None, True
                break
            if (mailroom / "HALT").exists():
                _stop("halt", proc)
                rc, halted = None, True
                break
            if now - started >= wall_cap:
                _stop("timeout", proc)
                rc, timed_out = None, True
                break
            if now >= next_ckpt:
                recovery_mod.write_checkpoint(worktree, mailroom,
                                              task_id=task_id, run_id=run_id)
                next_ckpt = now + recovery_mod.CHECKPOINT_INTERVAL
            time.sleep(0.1)
        return rc, _stderr_tail(), timed_out, halted
    finally:
        signal.signal(signal.SIGTERM, prev_handler)
        out_f.close()
        err_f.close()


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

    # 2 — budget ledger, fail-closed. Cannot record spend => do not spend.
    try:
        bl = SqliteBudgetLedger(mailroom / "governor" / BUDGET_DB)
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

    # 5 — per-task governor. A role the policy does not know is a denial, not
    # a crash (the raw governor raises KeyError — pinned in W1-1).
    gov = Governor(worktree / "agents" / "governor" / "policy.yaml",
                   mailroom / "governor" / GOVERNOR_DB)
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
    port = load_run_budget_port()
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

    # 9 — deterministic prepass: packet-declared T0 commands, zero tokens.
    prepass_results = []
    for cmd in (packet or {}).get("deterministic_prepass", []) or []:
        try:
            pr = subprocess.run(cmd, shell=True, cwd=worktree,
                                capture_output=True, text=True,
                                timeout=PREPASS_TIMEOUT)
            prepass_results.append({"cmd": cmd, "rc": pr.returncode})
        except subprocess.TimeoutExpired:
            prepass_results.append({"cmd": cmd, "rc": None,
                                    "timeout": PREPASS_TIMEOUT})

    # 10 — the model call, wall-clock capped.
    prompt = build_prompt(role, msg, run_id, mailroom)
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
        cmd = role_command(role, prompt, mailroom)
    started = time.time()
    rc, stderr_tail, timed_out, halted = _run_capped(
        cmd, worktree, mailroom, wall_cap=wall_cap, task_id=task_id,
        run_id=run_id, role=role)
    duration = time.time() - started

    # 11 — the result file is the only truth. rc==0 carried zero bits of
    # information across 1,408 measured invocations; it is not consulted for
    # the ack decision at all.
    result_status: str | None = None
    result_error: str | None = None
    success = False
    ack = AckDecision.RETAIN
    res: dict | None = None
    try:
        res = load_result(worktree / RESULT_FILENAME)
        result_status = res["status"]
        if is_ackable(res):
            ack = AckDecision.ACK
            ack_message(mailroom, role, message_id)
            success = result_status == "completed"
        # needs_retry: actionable, retained; step 7 retires it at the cap.
    except ResultError as e:
        result_error = str(e)
        if timed_out:
            result_error = f"timeout after {wall_cap}s; {result_error}"

    # 12 — recovery: any unsaved work in the tree (dirty or unpushed) gets a
    # verified bundle before the supervisor may consider removal (W1-4).
    from agents.recovery import inspect_worktree  # noqa: PLC0415
    inspect_worktree(worktree, mailroom, task_id=task_id, run_id=run_id,
                     acked=(ack is not AckDecision.RETAIN), role=role,
                     exit_code=rc, stderr_tail=stderr_tail)

    # Persist this attempt's diagnostics so a later cap-trip dead-letter has
    # evidence to carry (the trip itself never invokes).
    _write_attempt_diag(mailroom, message_id, {
        "run_id": run_id, "attempt": attempts, "exit_code": rc,
        "timed_out": timed_out, "stderr_tail": stderr_tail,
        "error_fingerprint": (res or {}).get("error_fingerprint"),
        "result_error": result_error, "ts": time.time(),
    })

    # 13 / 14 — record and close. Spend recording is fail-closed by design,
    # but at this point the spend has already happened: log loudly and let
    # the NEXT invocation's fail-closed open refuse instead.
    gov.record(role, task_id, success)
    try:
        bl.record_spend(role=role, task_id=task_id, run_id=run_id,
                        success=success)
    except BudgetLedgerUnavailable as e:
        print(f"WARNING: spend record failed after invocation: {e}",
              file=sys.stderr)
    tele.finish(run_id, result_status=result_status, result_error=result_error,
                exit_code=rc, timed_out=timed_out, halted=halted,
                duration_seconds=round(duration, 3),
                attempt_number=attempts, prepass=prepass_results,
                completed_at=time.time())
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
