#!/usr/bin/env python3
"""Anti-loop controller v1 — stop paying for the same failure twice (W2-4).

Measured motivation: ~50 invocations of one task produced an identical error
signature with zero new evidence and no strategy change. Error-signature
comparison alone would have caught it on attempt 2 and saved ~48 invocations.
The wider census: 1,408 invocations over three days, ~88% zero-yield.

Progress signals — an attempt counts as progress if ANY holds:
  - error signature changed (normalised sha256 differs from previous)
  - failing-test count strictly decreased
  - patch became more targeted (files_modified x lines_changed strictly
    smaller)
  - new evidence acquired (>=1 new tool-return content hash)
  - strategy materially changed (token Jaccard over stated plans < 0.75)
  - acceptance criteria advanced (satisfied required_checks strictly more)

Zero signals across two consecutive attempts is not a retry — it is a loop.

Fingerprint (audit section 8.4), over a rolling window of the last 6 per task:
  2 identical  -> force a strategy change (re-prompt naming the loop,
                  forbidding the prior approach)
  3 identical  -> escalate a tier
  4 identical, or any fingerprint recurring after an escalation
               -> dead-letter with needs-redesign

A-B-A oscillation: a working-tree hash returning to a previously seen value is
a loop even when fingerprints differ.

Circuit breakers — immediate stop, no retry:
  - cost exceeds value_usd (budget ledger)
  - prohibited file modified (packet files_out_of_scope + merge-robot
    PROTECTED)
  - test deletion / skip / validation weakening (merge-robot TEST_SIG)
  - banned pattern (merge-robot BANNED)
  - previously-passing test now fails (baseline comparison)
  - repeated fingerprint after escalation

PROTECTED / BANNED / TEST_SIG are IMPORTED from
`agents.merge_robot.patterns` — never copied. Two divergent copies of a
security pattern list is how one of them quietly stops matching.

State is per-task JSON under `<mailroom>/governor/anti_loop/<task_id>.json`
(the fan worktrees are throwaway; state must outlive them).
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from agents.merge_robot.patterns import BANNED, PROTECTED, TEST_SIG

WINDOW = 6

#: Escalation ladder between execution classes. Red has nowhere to go but the
#: dead-letter queue.
TIER_ESCALATION = {"green": "yellow", "org": "yellow", "yellow": "red"}

_VOLATILE = (
    re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?"),
    re.compile(r"\b\d{9,13}\b"),
    re.compile(r"/(?:tmp|var/folders)/[\w./-]+"),
    re.compile(r"0x[0-9a-fA-F]+"),
    re.compile(r"(?<=[:,]) ?line \d+", re.I),
    re.compile(r":\d+(?::\d+)?\b"),
)


def normalize_error(text: str) -> str:
    """Error text with paths, line numbers, timestamps, addresses stripped."""
    out = text or ""
    for rx in _VOLATILE:
        out = rx.sub("<x>", out)
    return " ".join(out.split())


def normalize_action(text: str) -> str:
    """Verb + target, not prose: lowercase, volatile-stripped, first 12
    tokens. Enough to distinguish 'fix the import in server/app.py' from
    'rewrite the calculator', which is what the fingerprint needs."""
    return " ".join(normalize_error((text or "").lower()).split()[:12])


def error_signature(text: str) -> str:
    return hashlib.sha256(normalize_error(text).encode()).hexdigest()[:16]


def token_jaccard(a: str, b: str) -> float:
    ta, tb = set((a or "").lower().split()), set((b or "").lower().split())
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


@dataclass
class AttemptState:
    """What one attempt looked like, as the dispatcher observed it."""

    last_error: str = ""
    files_changed: list[str] = field(default_factory=list)
    lines_changed: int = 0
    tests_run: list[str] = field(default_factory=list)
    failing_tests: int | None = None
    proposed_next_action: str = ""
    recent_tool_calls: list[str] = field(default_factory=list)
    tool_evidence_hashes: list[str] = field(default_factory=list)
    criteria_passed: int | None = None
    stated_plan: str = ""
    worktree_hash: str = ""
    tier: str = "green"
    cost_usd: float | None = None


def fingerprint(state: AttemptState) -> str:
    """Audit section 8.4, verbatim structure."""
    return hashlib.sha256("|".join([
        normalize_error(state.last_error),
        ",".join(sorted(state.files_changed)),
        ",".join(sorted(state.tests_run)),
        normalize_action(state.proposed_next_action),
        ",".join(state.recent_tool_calls[-8:]),
    ]).encode()).hexdigest()[:16]


@dataclass
class Verdict:
    #: continue | force_strategy_change | escalate_tier | dead_letter |
    #: terminate
    action: str
    reason: str
    #: For force_strategy_change: text the next prompt must include.
    strategy_note: str | None = None
    #: For escalate_tier: the class the next attempt runs at.
    next_tier: str | None = None


# ------------------------------------------------------------ breakers
#: Protected globs a specific role is authorized to write through the
#: governed path. L-4 (2026-08-03): CC-4 protected `tasks/packets/*` so a TASK
#: agent cannot rewrite the constraints it is judged against — kept in full —
#: but authoring packets IS pm's planning job (SPEC.md: only the PM identity
#: applies `protected-change`). This breaker and completion proof #12 are two
#: independent readers of the same list; fixing only #12 left pm still
#: dead-lettering here, which is this org's standing question in miniature —
#: what ELSE reads the thing this gate reads? Keep the two in step.
ROLE_AUTHORIZED_PROTECTED: dict[str, tuple[str, ...]] = {
    "pm": ("tasks/packets/*",),
}


def prohibited_files(changed: list[str], packet: dict | None,
                     role: str | None = None,
                     intent: str | None = None) -> list[str]:
    """Deny wins; PROTECTED is the floor a packet cannot loosen.

    `role` may clear ONLY the globs listed for it in
    ROLE_AUTHORIZED_PROTECTED. Normally a packet's own `files_out_of_scope`
    still beats that authorization — a packet can forbid what a role is
    otherwise allowed to touch, because the agent AGREED to that packet as
    the description of its own work.

    L-27 (2026-08-03) is the case where that reasoning does not hold. On a
    review intent the agent is judging someone ELSE's work, and the packet in
    hand is the BUILDER's. Its `files_out_of_scope` binds the builder; it has
    no authority over what the reviewer's own role may do. Observed live: pm
    handling a REVIEW_REQUEST for TASK-210-S3 authored the NEXT packet,
    `tasks/packets/TASK-210-S5.json` — pm's core routing job, explicitly
    role-authorized above — and was dead-lettered, because the S3 builder
    packet denies `tasks/packets/**`. pm could not route while holding any
    task message, which is the same category error as L-26 one gate over.

    So for a review intent, role authorization is not defeated by the
    builder's deny-list. PROTECTED still binds everyone; a role still only
    clears the globs listed for IT; every non-review intent is unchanged.
    """
    from agents.completion import (  # noqa: PLC0415
        NON_BUILD_INTENTS,
        REVIEW_EVIDENCE_GLOBS,
    )

    packet_deny = list((packet or {}).get("files_out_of_scope") or [])
    authorized = ROLE_AUTHORIZED_PROTECTED.get(role or "", ())
    deny = packet_deny + list(PROTECTED)
    hits = sorted({f for f in changed
                   for g in deny if fnmatch.fnmatch(f, g)})
    reviewing = intent in NON_BUILD_INTENTS

    # L-33 (2026-08-03): the coordination-evidence paths are admitted HERE
    # too, not only in completion proof #11. L-32 added tasks/BACKLOG.md to
    # #11 and stopped there — so pm updating the backlog passed the proof and
    # was then terminated by THIS breaker, which runs first. That is L-4's
    # lesson for the third time: PROTECTED has more than one reader, and a fix
    # that reaches one of them leaves the role still dead-lettering. L-32's
    # own commit message restated the lesson while only half-applying it.
    #
    # Note this clears the path for ANY role on a coordination intent, not
    # just pm: a reviewer writing docs/agent-org/ and a triager writing the
    # backlog are the same case, and neither path is PROTECTED, so #12 is
    # unaffected either way.
    if reviewing and hits:
        hits = [f for f in hits
                if not any(fnmatch.fnmatch(f, g)
                           for g in REVIEW_EVIDENCE_GLOBS)]

    if not authorized:
        return hits
    return [f for f in hits
            if (not reviewing
                and any(fnmatch.fnmatch(f, g) for g in packet_deny))
            or not any(fnmatch.fnmatch(f, g) for g in authorized)]


def test_weakening(diff_text: str) -> list[str]:
    """Lines matching merge-robot TEST_SIG in the added side of a diff."""
    hits = []
    for rx in TEST_SIG:
        pat = re.compile(rx) if isinstance(rx, str) else rx
        for line in (diff_text or "").splitlines():
            if pat.search(line):
                hits.append(line.strip()[:120])
    return hits


def banned_patterns(diff_text: str) -> list[str]:
    hits = []
    for rx in BANNED:
        pat = re.compile(rx) if isinstance(rx, str) else rx
        for line in (diff_text or "").splitlines():
            if pat.search(line):
                hits.append(line.strip()[:120])
    return hits


# ---------------------------------------------- pre-invocation helpers
def _state_path(mailroom: str | Path, task_id: str) -> Path:
    return Path(mailroom) / "governor" / "anti_loop" / f"{task_id}.json"


def _read_state(mailroom: str | Path, task_id: str) -> dict:
    try:
        return json.loads(_state_path(mailroom, task_id).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def tier_override(mailroom: str | Path, task_id: str) -> str | None:
    """The escalated execution class for a task, if any. Read-only."""
    return _read_state(mailroom, task_id).get("current_tier")


def pending_strategy_note(mailroom: str | Path, task_id: str) -> str | None:
    """The LOOP DETECTED note the next prompt must carry, if any."""
    return _read_state(mailroom, task_id).get("pending_note")


def consume_strategy_note(mailroom: str | Path, task_id: str) -> None:
    """Called once the note has been embedded in a prompt."""
    p = _state_path(mailroom, task_id)
    state = _read_state(mailroom, task_id)
    if state.get("pending_note"):
        state["pending_note"] = None
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(state, indent=2))
        except OSError:
            pass


# ------------------------------------------------------------ controller
class AntiLoopController:
    """Per-task loop detection over durable state."""

    def __init__(self, mailroom: str | Path, task_id: str) -> None:
        self.path = Path(mailroom) / "governor" / "anti_loop" / f"{task_id}.json"
        self.task_id = task_id
        try:
            self.state = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            self.state = {"attempts": [], "escalations": 0,
                          "post_escalation_fps": [], "tree_hashes": []}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=2))

    # -------------------------------------------------- progress signals
    def progress_signals(self, cur: AttemptState) -> list[str]:
        prev = self.state["attempts"][-1] if self.state["attempts"] else None
        if prev is None:
            return ["first_attempt"]
        signals = []
        if error_signature(cur.last_error) != prev.get("error_sig"):
            signals.append("error_signature_changed")
        if (cur.failing_tests is not None
                and prev.get("failing_tests") is not None
                and cur.failing_tests < prev["failing_tests"]):
            signals.append("failing_tests_decreased")
        cur_size = len(cur.files_changed) * max(cur.lines_changed, 1)
        prev_size = prev.get("patch_size")
        if prev_size is not None and cur.files_changed \
                and cur_size < prev_size:
            signals.append("patch_more_targeted")
        new_evidence = set(cur.tool_evidence_hashes) - set(
            h for a in self.state["attempts"]
            for h in a.get("evidence_hashes", []))
        if new_evidence:
            signals.append("new_evidence")
        if token_jaccard(cur.stated_plan, prev.get("stated_plan", "")) < 0.75:
            signals.append("strategy_changed")
        if (cur.criteria_passed is not None
                and prev.get("criteria_passed") is not None
                and cur.criteria_passed > prev["criteria_passed"]):
            signals.append("criteria_advanced")
        return signals

    # -------------------------------------------------- assessment
    def assess(self, cur: AttemptState, packet: dict | None = None,
               diff_text: str = "",
               previously_passing_now_failing: bool = False,
               role: str | None = None,
               intent: str | None = None) -> Verdict:
        """Assess one finished attempt. Persists it to the rolling window."""
        # Immediate circuit breakers — no retry, no window arithmetic.
        bad = prohibited_files(cur.files_changed, packet, role=role,
                               intent=intent)
        if bad:
            return self._record_and(cur, Verdict(
                "terminate", f"prohibited files modified: {bad}"))
        weak = test_weakening(diff_text)
        if weak:
            return self._record_and(cur, Verdict(
                "terminate", f"test weakening detected: {weak[:3]}"))
        banned = banned_patterns(diff_text)
        if banned:
            return self._record_and(cur, Verdict(
                "terminate", f"banned pattern: {banned[:3]}"))
        if previously_passing_now_failing:
            return self._record_and(cur, Verdict(
                "terminate", "previously-passing test now fails"))
        value = (packet or {}).get("budgets", {}).get("value_usd")
        if value is not None and cur.cost_usd is not None \
                and cur.cost_usd > value:
            return self._record_and(cur, Verdict(
                "terminate",
                f"cost {cur.cost_usd} exceeds value_usd {value}"))

        fp = fingerprint(cur)

        # Recurrence after an escalation is a dead-letter regardless of count.
        if self.state["escalations"] > 0 \
                and fp in self.state["post_escalation_fps"]:
            return self._record_and(cur, Verdict(
                "dead_letter",
                f"fingerprint {fp} recurred after escalation"))

        # A-B-A oscillation: the tree came back to a state it already had.
        if cur.worktree_hash and \
                cur.worktree_hash in self.state["tree_hashes"]:
            return self._record_and(cur, Verdict(
                "dead_letter",
                f"A-B-A oscillation: worktree hash {cur.worktree_hash[:12]} "
                f"seen before"))

        window = self.state["attempts"][-(WINDOW - 1):]
        identical = sum(1 for a in window if a.get("fingerprint") == fp) + 1

        signals = self.progress_signals(cur)
        no_progress_streak = self.state.get("no_progress_streak", 0)
        if not signals:
            no_progress_streak += 1
        else:
            no_progress_streak = 0

        verdict: Verdict
        if identical >= 4:
            verdict = Verdict("dead_letter",
                              f"{identical} identical fingerprints in the "
                              f"last {WINDOW}")
        elif identical == 3:
            nxt = TIER_ESCALATION.get(cur.tier)
            if nxt is None:
                verdict = Verdict("dead_letter",
                                  f"3 identical fingerprints at terminal "
                                  f"tier {cur.tier}")
            else:
                verdict = Verdict("escalate_tier",
                                  f"3 identical fingerprints; {cur.tier} -> "
                                  f"{nxt}", next_tier=nxt)
        elif identical == 2 or no_progress_streak >= 2:
            why = (f"2 identical fingerprints ({fp})" if identical == 2 else
                   "zero progress signals across two consecutive attempts")
            verdict = Verdict(
                "force_strategy_change", why,
                strategy_note=(
                    f"LOOP DETECTED on {self.task_id}: {why}. The previous "
                    f"approach — {normalize_action(cur.proposed_next_action) or 'unstated'} — "
                    f"is FORBIDDEN this attempt. State a different strategy "
                    f"before acting, name what evidence you will gather that "
                    f"you did not gather last time, and if none exists, "
                    f"return status=needs_retry with escalation_reason."))
        else:
            verdict = Verdict("continue", "progress: " + ",".join(signals))

        return self._record_and(cur, verdict, fp=fp, signals=signals,
                                streak=no_progress_streak)

    def _record_and(self, cur: AttemptState, verdict: Verdict,
                    fp: str | None = None, signals: list[str] | None = None,
                    streak: int = 0) -> Verdict:
        fp = fp or fingerprint(cur)
        self.state["attempts"] = (self.state["attempts"] + [{
            "ts": time.time(),
            "fingerprint": fp,
            "error_sig": error_signature(cur.last_error),
            "failing_tests": cur.failing_tests,
            "patch_size": len(cur.files_changed) * max(cur.lines_changed, 1)
            if cur.files_changed else None,
            "evidence_hashes": cur.tool_evidence_hashes,
            "stated_plan": cur.stated_plan,
            "criteria_passed": cur.criteria_passed,
            "tier": cur.tier,
            "action": verdict.action,
        }])[-WINDOW:]
        if cur.worktree_hash:
            self.state["tree_hashes"] = (
                self.state["tree_hashes"] + [cur.worktree_hash])[-WINDOW * 2:]
        self.state["no_progress_streak"] = streak
        if verdict.action == "escalate_tier":
            self.state["escalations"] += 1
            self.state["post_escalation_fps"] = []
            self.state["current_tier"] = verdict.next_tier
        elif self.state["escalations"] > 0:
            self.state["post_escalation_fps"] = list(
                set(self.state["post_escalation_fps"]) | {fp})
        if verdict.action == "force_strategy_change":
            self.state["pending_note"] = verdict.strategy_note
        self._save()
        return verdict
