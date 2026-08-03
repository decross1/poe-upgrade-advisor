"""Discord release-note collection and rendering for merged mission work.

RENDER ONLY: this module never imports discord, opens a connection, or
posts anything. Wiring it to the live announce channel is a separate,
operator-gated stage (Doctrine S2).
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

MAX_DISCORD_MESSAGE = 1900
TASK_ID = re.compile(r"\bTASK-\d+(?:-S\d+)?\b", re.IGNORECASE)
ISSUE_REF = re.compile(r"#\d+")
MERGE_PREFIX = re.compile(r"^Merge\s+(?:pull request #\d+\s+(?:from|of)\s+\S+\s*)?", re.IGNORECASE)
SEPARATORS = re.compile(r"^[\s:—–-]+|[\s:—–-]+$")


@dataclass(frozen=True)
class ReleaseEntry:
    task_id: str | None
    summary: str
    refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReleaseData:
    since_ref: str
    until_ref: str
    entries: tuple[ReleaseEntry, ...] = ()


def _entry_from_commit(subject: str, body: str) -> ReleaseEntry | None:
    subject = subject.strip()
    if not subject:
        return None
    task = TASK_ID.search(subject)
    task_id = task.group().upper() if task else None
    summary = MERGE_PREFIX.sub("", subject)
    if task_id:
        summary = TASK_ID.sub("", summary, count=1)
    summary = ISSUE_REF.sub("", summary)
    summary = SEPARATORS.sub("", summary)
    summary = re.sub(r"\s+", " ", summary)
    summary = re.sub(r"\s*\(\s*\)\s*$", "", summary).strip()
    if not summary:
        return None
    if len(summary) > 140:
        summary = summary[:137].rstrip() + "…"
    refs = tuple(dict.fromkeys(ISSUE_REF.findall(subject + "\n" + body)))
    return ReleaseEntry(task_id=task_id, summary=summary, refs=refs)


def collect_release(repo: str, since_ref: str, until_ref: str) -> ReleaseData:
    """Collect merged commits in `since_ref..until_ref` from the git repo at `repo`."""
    output = subprocess.run(
        [
            "git", "-C", repo, "log",
            "--format=%s%x1f%b%x1e", f"{since_ref}..{until_ref}",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout
    entries: list[ReleaseEntry] = []
    seen: set[str] = set()
    for record in output.split("\x1e"):
        record = record.strip("\n")
        if not record.strip():
            continue
        subject, _, body = record.partition("\x1f")
        entry = _entry_from_commit(subject, body)
        if entry is None:
            continue
        if entry.task_id and entry.task_id in seen:
            continue
        if entry.task_id:
            seen.add(entry.task_id)
        entries.append(entry)
    return ReleaseData(since_ref=since_ref, until_ref=until_ref, entries=tuple(entries))


def render_release(data: ReleaseData) -> str | None:
    """Render at most one Discord message, or None when nothing merged."""
    if not data.entries:
        return None

    lines = ["**New in PoE Upgrade Advisor**"]
    for entry in data.entries:
        bullet = f"**{entry.task_id}** {entry.summary}" if entry.task_id else entry.summary
        if entry.refs:
            bullet += " (" + ", ".join(entry.refs) + ")"
        candidate = [*lines, f"• {bullet}"]
        if len("\n".join(candidate)) > MAX_DISCORD_MESSAGE:
            if len("\n".join([*lines, "• …"])) <= MAX_DISCORD_MESSAGE:
                lines.append("• …")
            return "\n".join(lines)
        lines.append(f"• {bullet}")
    return "\n".join(lines)
