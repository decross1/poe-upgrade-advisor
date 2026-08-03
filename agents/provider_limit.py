"""Detect a provider session/rate cap and stop the ROLE, not just the message.

Operator ruling 2026-08-03: "use as much as possible until the session caps
hit (i assume we will get some feedback)". Before this module there was no
such feedback anywhere in the control plane — grep for session/rate/quota
across agents/ returned only an unrelated ENOSPC comment.

What actually happens without it is measured, not hypothetical. On
2026-07-27 six pm workers hit the Claude session cap; the CLI printed
"You've hit your session limit" and exited **rc=0**. The dispatcher saw a
missing result file, retained the message, and the loop came back — the org's
founding lesson (exit 0 is not success) wearing a different hat. Per-message
attempt caps bound the damage now, but every queued message would still burn
its attempts against a provider that is refusing, and the operator would see
a pile of retentions rather than one clear reason.

The cap is a property of the PROVIDER, not of the message, so the response is
role-scoped: one detection writes a durable marker and every later dispatch
for that role is suppressed BEFORE the model is invoked (zero spend) until
the marker expires. The marker is a plain JSON file an operator can read,
`rm` to retry immediately, or leave to expire on its own.

Deliberately NOT fail-closed on absence: no marker means dispatch proceeds.
A false positive here would silently idle a healthy role, so the patterns
below are narrow and matched against the model CLI's own output only.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

#: Default quiet period after a detected cap — operator ruling 2026-08-03:
#: "shut the org down for ~6 hours, and bring back up with the assumption
#: that session limits will resume". Encoding it here rather than in a human
#: procedure is the point: the role goes quiet and comes back on its own,
#: whether or not anyone is watching. Override via `mark(..., cooldown=...)`.
DEFAULT_COOLDOWN_SECONDS = 6 * 3600

#: Narrow on purpose — each is a phrase a provider CLI emits when it is
#: REFUSING work, not merely reporting usage. Anchored to whole phrases so
#: "rate limit" inside an agent's prose (e.g. editing this very file) does not
#: trip it; see `detect`'s scan-the-tail-only contract.
PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"you'?ve hit your session limit", re.I),
    re.compile(r"\bsession limit reached\b", re.I),
    re.compile(r"\busage limit reached\b", re.I),
    re.compile(r"\bquota (?:exceeded|exhausted)\b", re.I),
    re.compile(r"\brate[ _-]?limit(?:ed|ing)?\b.{0,40}\b(?:exceeded|reached|try again)", re.I),
    re.compile(r"\b429\b.{0,30}too many requests", re.I),
    re.compile(r"\btoo many requests\b", re.I),
    re.compile(r"\binsufficient[_ ]quota\b", re.I),
    # Not a cap, but the same failure SHAPE and worth the same treatment:
    # a misconfigured model id makes every invocation for the role fail in
    # ~3s, burning one attempt per message until each dead-letters. Observed
    # live 2026-08-03: KIMI_MODEL was set to the bare alias "kimi-k3" from an
    # operator setup note, but the CLI requires the configured id
    # "moonshot-ai/kimi-k3", and the org's FIRST kimi invocation — the
    # overlay task — died on it. Quieting the role surfaces one clear reason
    # instead of a queue of silent dead-letters.
    re.compile(r"is not configured in config\.toml", re.I),
    re.compile(r"\bmodel .{0,60}\bnot (?:found|configured|available)\b", re.I),
    # NOT a standalone "please try again later" — that phrase appears in
    # ordinary prose, docs and error text, and on 2026-08-03 it quieted the
    # frontend role for 6h on a bare match, moments after that role produced
    # the mission's first accepted product code. It only means a cap when it
    # accompanies an explicit limit/quota word.
    re.compile(r"(?:limit|quota|capacity|too many).{0,80}please try again", re.I),
    re.compile(r"please try again.{0,40}(?:limit|quota|capacity)", re.I),
)


def detect(*streams: str | None) -> str | None:
    """Return the matched phrase if any stream shows a provider refusal.

    Streams are the model CLI's own stdout/stderr tails. Returns the matched
    text (for the durable record) or None.
    """
    for stream in streams:
        if not stream:
            continue
        for pattern in PATTERNS:
            m = pattern.search(stream)
            if m:
                return m.group(0)[:200]
    return None


#: A transient overload is not an exhausted quota, and treating them alike is
#: expensive in exactly the wrong direction. L-25 (2026-08-03): kimi returned
#: "429 The engine is currently overloaded, please try again" seconds after
#: completing a task, and the flat 6h cooldown parked the org's ONLY working
#: role — pm and backend were both quota-capped — for six hours over a
#: momentary capacity blip. Match the wait to the kind of refusal.
TRANSIENT_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\boverloaded\b", re.I),
    re.compile(r"\b(?:temporarily|currently) unavailable\b", re.I),
    re.compile(r"\bserver is busy\b", re.I),
    re.compile(r"\b(?:503|502|504)\b", re.I),
)

#: Wait for a transient refusal: long enough to stop hammering a busy
#: provider, short enough that a blip costs minutes rather than a shift.
TRANSIENT_COOLDOWN_SECONDS = 300


def cooldown_for(matched: str) -> int:
    """Seconds to quiet a role, chosen by the KIND of refusal it hit."""
    for pattern in TRANSIENT_PATTERNS:
        if pattern.search(matched or ""):
            return TRANSIENT_COOLDOWN_SECONDS
    return DEFAULT_COOLDOWN_SECONDS


def marker_path(mailroom: Path, role: str) -> Path:
    return Path(mailroom) / "blocked" / f"provider-limit-{role}.json"


def mark(mailroom: Path, role: str, *, matched: str, run_id: str | None = None,
         cooldown: int | None = None,
         now: float | None = None) -> Path:
    """Record the cap durably and start the role's quiet period."""
    ts = time.time() if now is None else now
    if cooldown is None:
        cooldown = cooldown_for(matched)
    path = marker_path(mailroom, role)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "role": role,
        "detected_at": ts,
        "expires_at": ts + cooldown,
        "cooldown_seconds": cooldown,
        "matched": matched,
        "run_id": run_id,
        "note": ("Provider refused work for this role. Every dispatch for it "
                 "is suppressed BEFORE invoking (zero spend) until "
                 "expires_at. Delete this file to retry immediately."),
    }, indent=2) + "\n")
    return path


def active(mailroom: Path, role: str, *, now: float | None = None) -> dict | None:
    """The live marker for `role`, or None. Expired markers are removed.

    Unreadable/corrupt markers are treated as absent rather than as a block:
    a malformed file must not be able to idle a healthy role forever.
    """
    path = marker_path(mailroom, role)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text())
        expires = float(data.get("expires_at", 0))
    except (OSError, ValueError, TypeError):
        return None
    ts = time.time() if now is None else now
    if ts >= expires:
        try:
            path.unlink()
        except OSError:
            pass
        return None
    data["seconds_remaining"] = int(expires - ts)
    return data
