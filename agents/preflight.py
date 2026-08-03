#!/usr/bin/env python3
"""Preflight v1 — zero-token no-op suppression (W1-3).

Kills the largest observed waste class: invocations that were never going to
produce anything. On the 2026-07 record: TASK-007 rechecked 6 times against an
unchanged missing secret, 5 duplicate review verdicts at the same head SHA,
4 stops on closed or shelved issues, >=15 zero-yield invocations from one role.

Every check here is deterministic and costs zero model tokens. `gh` may be
consulted (network, no model); tests inject a stub.

Blocked state persists OUTSIDE the conversation, in
`<mailroom>/blocked/<role>/<task_id>.json` — the cross-lane contract pm-lite
re-queues from:

    {
      "schema_version": "1.0",
      "task_id": "TASK-007",
      "role": "pm",
      "message_id": "<uuid>",
      "blocked_reason": "MERGE_ROBOT_TOKEN secret absent",
      "resume_condition": "gh secret list contains MERGE_ROBOT_TOKEN",
      "fingerprint": "a1b2c3d4e5f60718",
      "first_seen": "2026-08-02T00:00:00Z",
      "last_checked": "2026-08-02T06:00:00Z",
      "check_count": 6
    }

On a preflight block the dispatcher persists this record and ACKS the message.
Retaining it would mean redelivery forever — the exact failure being fixed;
the durable record, not the queue, carries the state. A later message for the
same task re-checks: unchanged fingerprint => bump `last_checked`/
`check_count`, zero model calls; changed fingerprint => the blocker moved —
clear the record and let the task through.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

#: Labels that mean "do not invoke a model for this task".
REJECT_LABELS = {"needs-redesign", "blocked", "blocked:human", "quarantine",
                 "parked", "shelved", "deferred"}

#: Feature flag: PREFLIGHT=0 disables the whole module (dispatch honours it).
FLAG = "PREFLIGHT"

# Volatile noise stripped before fingerprinting. A fingerprint that embeds a
# timestamp or a tmp path never repeats, and the unchanged-blocker check
# becomes decorative.
_VOLATILE = (
    re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"),
    re.compile(r"\b\d{9,13}\b"),                  # epoch seconds / millis
    re.compile(r"/(?:tmp|var/folders)/[\w./-]+"),  # tmp paths
    re.compile(r"0x[0-9a-fA-F]+"),                 # hex addresses
    re.compile(r"(?<=[:,]) ?line \d+", re.I),
    re.compile(r":\d+(?::\d+)?\b"),                # file:line(:col)
)


def normalize(text: str) -> str:
    """Strip volatile noise so equal blockers hash equal."""
    out = text or ""
    for rx in _VOLATILE:
        out = rx.sub("<x>", out)
    return " ".join(out.split())


def blocker_fingerprint(*, issue_state: str, labels: list[str],
                        head_sha: str | None,
                        missing_prerequisites: list[str],
                        resume_condition: str | None) -> str:
    """sha256 over the normalised blocker tuple, truncated to 16 hex."""
    tup = "|".join([
        normalize(issue_state),
        ",".join(sorted(normalize(label) for label in labels)),
        head_sha or "",
        ",".join(sorted(normalize(m) for m in missing_prerequisites)),
        normalize(resume_condition or ""),
    ])
    return hashlib.sha256(tup.encode()).hexdigest()[:16]


@dataclass
class PreflightVerdict:
    ok: bool
    reason: str
    resume_condition: str | None = None
    fingerprint: str = ""
    #: True when this exact blocker was already recorded (unchanged
    #: fingerprint) — the dispatcher records SUPPRESSED_UNCHANGED_BLOCKER.
    repeat_unchanged: bool = False
    #: Checks that could not run (missing patterns import, no gh) — surfaced,
    #: never silently skipped.
    degraded_checks: list[str] = field(default_factory=list)


def _gh_cli(*args: str) -> str | None:
    """Default gh runner. Returns stdout, or None when gh is unusable."""
    if shutil.which("gh") is None:
        return None
    try:
        p = subprocess.run(["gh", *args], capture_output=True, text=True,
                           timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout if p.returncode == 0 else None


def _issue_view(gh, issue: int) -> dict | None:
    out = gh("issue", "view", str(issue), "--json", "state,labels,title")
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def _pr_view(gh, pr: int) -> dict | None:
    out = gh("pr", "view", str(pr), "--json",
             "state,reviews,headRefOid,labels")
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def _protected_globs():
    """merge_robot's PROTECTED list, imported — never copied.

    Lane B's `agents/merge_robot/patterns.py` (e932f32) makes this importable
    without MERGE_ROBOT_TOKEN. Until that commit reaches this base the check
    is DEGRADED and says so; a silently skipped security check is worse than
    a loud one.
    """
    try:
        from agents.merge_robot.patterns import PROTECTED  # noqa: PLC0415
        return list(PROTECTED)
    except ImportError:
        return None


def _packet_preconditions(packet: dict, *, issue_state: str,
                          labels: list[str], head_sha: str | None,
                          missing: list[str], degraded: list[str],
                          blocked_dir, issue,
                          labels_fetched: bool = True,
                          ) -> tuple[str | None, str | None]:
    """Evaluate `packet["preconditions"]` — schema shape: array of
    {check, expect, require, forbid, require_if_touching, ...} objects.

    Returns (reason, resume) — (None, None) when everything passes. Checks
    that need state this run could not fetch, or that preflight does not
    evaluate yet (`baseline_checks` — running arbitrary commands belongs to
    the dispatcher's packet enforcement, W2-5), are surfaced in `degraded`,
    never silently dropped.
    """
    import fnmatch  # noqa: PLC0415
    scope = packet.get("files_in_scope") or []
    for pc in packet.get("preconditions") or []:
        check = pc.get("check")
        if check == "issue_state":
            want = pc.get("expect") or "OPEN"
            if issue_state == "UNKNOWN":
                degraded.append("precondition:issue_state")
            elif issue_state != want:
                return (f"precondition issue_state: {issue_state} != {want}",
                        f"issue #{issue} state becomes {want}")
        elif check == "issue_labels":
            if not labels_fetched:
                degraded.append("precondition:issue_labels")
                continue
            need = set(pc.get("require") or []) - set(labels)
            hit = set(pc.get("forbid") or []) & set(labels)
            if need:
                missing.extend(sorted(need))
                return (f"precondition issue_labels: missing {sorted(need)}",
                        f"labels {sorted(need)} on #{issue}")
            if hit:
                return (f"precondition issue_labels: forbidden {sorted(hit)}",
                        f"labels {sorted(hit)} removed from #{issue}")
        elif check == "labels_for_scope":
            for glob, label in (pc.get("require_if_touching") or {}).items():
                touched = [f for f in scope if fnmatch.fnmatch(f, glob)]
                if touched and label not in labels:
                    missing.append(label)
                    return (f"precondition labels_for_scope: {touched} "
                            f"require label {label}",
                            f"label {label} on #{issue}")
        elif check == "review_not_complete_at_head":
            # The built-in same-SHA skip (check 5) already enforces this for
            # REVIEW_REQUEST; declaring it on other intents has no extra
            # state to consult here.
            continue
        elif check == "blocker_fingerprint":
            continue  # built-in check 6 is the implementation
        elif check == "resource_lock":
            root = Path(blocked_dir).parent if blocked_dir else None
            if root is None:
                degraded.append("precondition:resource_lock")
                continue
            held = [name for name in (pc.get("forbid") or [])
                    if (root / "locks" / f"resource-{name}.lock").exists()]
            if held:
                return (f"precondition resource_lock: held {sorted(held)}",
                        f"locks released: {sorted(held)}")
        elif check == "baseline_checks":
            degraded.append("precondition:baseline_checks")
    return None, None


def preflight(message: dict, packet: dict | None = None, gh=None,
              blocked_dir: str | Path | None = None,
              role: str | None = None) -> PreflightVerdict:
    """Run every zero-token check for one message. No model call, ever.

    `gh` is a callable `gh(*args) -> stdout|None`; None uses the real CLI.
    `blocked_dir` enables the unchanged-blocker suppression (check 6) and is
    where `record_block`/`clear_block` persist state.
    """
    gh = gh or _gh_cli
    role = role or message.get("to_role")
    task_id = message["task_id"]
    labels: list[str] = []
    labels_fetched = True   # False once an issue/PR view fails (L-19)
    issue_state = "UNKNOWN"
    head_sha: str | None = None
    missing: list[str] = []
    degraded: list[str] = []
    reason: str | None = None
    resume: str | None = None

    # 4 — role match (cheap; dispatch also guards).
    if message.get("to_role") != role:
        return PreflightVerdict(
            ok=False,
            reason=f"role mismatch: addressed to {message.get('to_role')}",
            fingerprint=blocker_fingerprint(
                issue_state="role-mismatch", labels=[], head_sha=None,
                missing_prerequisites=[], resume_condition=None))

    refs = message.get("refs") or {}
    issue = refs.get("issue")
    pr = refs.get("pr")

    # 1 / 2 / 7 — issue exists, open, and not carrying a reject label.
    if issue is not None:
        info = _issue_view(gh, issue)
        if info is None:
            # L-19 (2026-08-03, observed live): `labels` stays [] when the
            # issue view fails for ANY reason — gh missing, unauthenticated,
            # network, timeout — and the issue_labels precondition below then
            # read "could not look" as "the label is not there", BLOCKED the
            # task and ACKED the message, silently discarding real mission
            # work (TASK-210-S2, the overlay, on a transient failure while
            # #79 carried the required label the whole time). issue_state
            # already handled this correctly via UNKNOWN -> degraded; the
            # label check had no equivalent. This is §5's recurring shape:
            # a gate reading from a place that may not have been written.
            degraded.append("issue_state")
            labels_fetched = False
        else:
            issue_state = info.get("state", "UNKNOWN")
            labels = [l["name"] if isinstance(l, dict) else str(l)
                      for l in info.get("labels", [])]
            if issue_state != "OPEN":
                reason = f"issue #{issue} is {issue_state}"
                resume = f"issue #{issue} reopened"
            else:
                hit = REJECT_LABELS & set(labels)
                if hit:
                    reason = f"issue #{issue} labelled {sorted(hit)}"
                    resume = f"labels {sorted(hit)} removed from #{issue}"

    # 5 / 7 — PR state; a review already approved at the same head SHA is a
    # no-op (5 duplicate verdicts on record). PR reject labels count too — a
    # message referencing only a parked PR must stop exactly like a parked
    # issue.
    if reason is None and pr is not None:
        info = _pr_view(gh, pr)
        if info is None:
            degraded.append("pr_state")
        else:
            head_sha = info.get("headRefOid")
            pr_labels = [l["name"] if isinstance(l, dict) else str(l)
                         for l in info.get("labels", [])]
            labels = sorted(set(labels) | set(pr_labels))
            hit = REJECT_LABELS & set(pr_labels)
            if info.get("state") == "MERGED":
                reason = f"PR #{pr} already merged"
                resume = "superseding work only"
            elif hit:
                reason = f"PR #{pr} labelled {sorted(hit)}"
                resume = f"labels {sorted(hit)} removed from PR #{pr}"
            elif message.get("intent") == "REVIEW_REQUEST":
                approved = [r for r in info.get("reviews", [])
                            if r.get("state") == "APPROVED"
                            and r.get("commit", {}).get("oid") == head_sha]
                if approved:
                    reason = (f"review already complete at {str(head_sha)[:8]}"
                              f" on PR #{pr}")
                    resume = f"new head SHA on PR #{pr}"

    # 3 — protected-change authorisation, when the packet's scope touches a
    # protected path. List is IMPORTED from merge_robot patterns, not copied.
    # ASYMMETRIC degradation policy (PM-agreed, 2026-08-02): read-only state
    # (issue_state/pr_state) degrades freely, but an authorisation check on
    # a PROTECTED scope blocks when the label state is unverifiable — a
    # false block delays one task; a false pass burns invocations on work
    # that cannot merge and softens an authorisation control. The block is
    # cheap under an outage: its fingerprint is stable (UNKNOWN state), so
    # re-checks are zero-cost SUPPRESSED_UNCHANGED_BLOCKER, and gh recovery
    # changes the fingerprint, which auto-clears or re-blocks on the real
    # label state.
    if reason is None and packet is not None:
        globs = _protected_globs()
        if globs is None:
            degraded.append("protected_change")
        else:
            import fnmatch  # noqa: PLC0415
            scope = (packet.get("files_in_scope") or [])
            touched = sorted({f for f in scope
                              for g in globs if fnmatch.fnmatch(f, g)})
            if touched and "issue_state" in degraded:
                reason = (f"packet scope touches protected paths {touched} "
                          f"but label state is unverifiable (gh degraded)")
                resume = "gh issue label state readable again"
                missing.append("label-verification")
            elif touched and "protected-change" not in labels:
                reason = (f"packet scope touches protected paths {touched} "
                          f"without protected-change authorisation")
                resume = f"protected-change label on #{issue}"
                missing.append("protected-change label")

    # 8 — packet-declared preconditions, evaluated per the packet schema:
    # an ARRAY of typed check objects (the field the audit says pays for the
    # whole schema). Built-in checks above are the floor a packet cannot
    # weaken; these only add.
    if reason is None and packet is not None:
        reason, resume = _packet_preconditions(
            packet, issue_state=issue_state, labels=labels,
            labels_fetched=labels_fetched,
            head_sha=head_sha, missing=missing, degraded=degraded,
            blocked_dir=blocked_dir, issue=issue)

    fp = blocker_fingerprint(issue_state=issue_state, labels=labels,
                             head_sha=head_sha, missing_prerequisites=missing,
                             resume_condition=resume)

    if reason is None:
        # Clear any stale block: the blocker either never existed or moved.
        if blocked_dir and role:
            clear_block(blocked_dir, role, task_id)
        return PreflightVerdict(ok=True, reason="ok", fingerprint=fp,
                                degraded_checks=degraded)

    # 6 — unchanged-blocker suppression against the durable record.
    repeat = False
    if blocked_dir and role:
        prior = read_block(blocked_dir, role, task_id)
        if prior and prior.get("fingerprint") == fp:
            repeat = True
        elif prior:
            clear_block(blocked_dir, role, task_id)  # blocker moved

    return PreflightVerdict(ok=False, reason=reason, resume_condition=resume,
                            fingerprint=fp, repeat_unchanged=repeat,
                            degraded_checks=degraded)


# ------------------------------------------------------------ blocked records
def _block_path(blocked_dir: str | Path, role: str, task_id: str) -> Path:
    return Path(blocked_dir) / role / f"{task_id}.json"


def read_block(blocked_dir: str | Path, role: str, task_id: str) -> dict | None:
    p = _block_path(blocked_dir, role, task_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def record_block(blocked_dir: str | Path, role: str, *, task_id: str,
                 message_id: str, verdict: PreflightVerdict) -> dict:
    """Write or bump the durable blocked record. Returns the record."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds") \
        .replace("+00:00", "Z")
    p = _block_path(blocked_dir, role, task_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    prior = read_block(blocked_dir, role, task_id)
    if prior and prior.get("fingerprint") == verdict.fingerprint:
        prior["last_checked"] = now
        prior["check_count"] = int(prior.get("check_count", 0)) + 1
        prior["message_id"] = message_id
        p.write_text(json.dumps(prior, indent=2))
        return prior
    rec = {
        "schema_version": "1.0",
        "task_id": task_id,
        "role": role,
        "message_id": message_id,
        "blocked_reason": verdict.reason,
        "resume_condition": verdict.resume_condition,
        "fingerprint": verdict.fingerprint,
        "first_seen": now,
        "last_checked": now,
        "check_count": 1,
    }
    p.write_text(json.dumps(rec, indent=2))
    return rec


def clear_block(blocked_dir: str | Path, role: str, task_id: str) -> None:
    p = _block_path(blocked_dir, role, task_id)
    try:
        p.unlink(missing_ok=True)
    except OSError:
        pass
