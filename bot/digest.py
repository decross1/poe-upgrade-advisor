"""Weekly, player-facing Discord digest collection and rendering."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

MAX_DISCORD_MESSAGE = 1900
TASK_ID = re.compile(r"\bTASK-\d+[A-Z]?\b", re.IGNORECASE)
INTERNAL_REFERENCE = re.compile(
    r"\b(?:TASK|ADR|RFC)-\d+[A-Z]?\b", re.IGNORECASE
)
INTERNAL_REFERENCE_PARENTHETICAL = re.compile(
    r"\s*\([^()]*\b(?:TASK|ADR|RFC)-\d+[A-Z]?\b[^()]*\)",
    re.IGNORECASE,
)
INTERNAL_REFERENCE_SUFFIX = re.compile(
    r"\s*\+\s*(?:ADR|RFC)-\d+[A-Z]?(?:\s*\([^()]*\))?",
    re.IGNORECASE,
)
INTERNAL_WORDS = re.compile(
    r"\b(?:CI|PR|ADR|RFC|gate|backend|frontend|PM|merge robot)\b",
    re.IGNORECASE,
)
INTERNAL_DECISION = re.compile(
    r"\b(?:agent|backend|branch|CI|frontend|ledger|identity|phase|PM|protocol|"
    r"reassign|role:|sprint|task|tracked under|workflow|protected path|"
    r"human directive)\b",
    re.IGNORECASE,
)
INTERNAL_SHIPMENT = re.compile(
    r"\b(?:ADR|CI|file backlog|fixture mock|harden gates|ledger|lint|"
    r"server skeleton|status badge)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DigestData:
    shipped: tuple[str, ...] = ()
    decided: tuple[str, ...] = ()
    up_next: tuple[str, ...] = ()


def _run_json(command: list[str]) -> object:
    result = subprocess.run(
        command, check=True, capture_output=True, text=True, timeout=30
    )
    return json.loads(result.stdout)


def _player_text(value: str) -> str:
    value = INTERNAL_REFERENCE_SUFFIX.sub("", value)
    value = INTERNAL_REFERENCE_PARENTHETICAL.sub("", value)
    value = INTERNAL_REFERENCE.sub("", value)
    value = INTERNAL_WORDS.sub("", value)
    value = re.sub(r"^[\s:—–-]+|[\s:—–-]+$", "", value)
    value = re.sub(r"\s+", " ", value)
    return value if len(value) <= 180 else value[:177].rstrip() + "…"


def _task_entries(items: list[dict[str, object]]) -> dict[str, str]:
    entries: dict[str, str] = {}
    for item in items:
        title = str(item["title"])
        match = TASK_ID.search(title)
        if not match or match.group().upper() == "TASK-000":
            continue
        text = _player_text(title)
        if text:
            entries.setdefault(match.group().upper(), text)
    return entries


def _decision_text(value: str) -> str:
    first_sentence = value.strip().splitlines()[0].split(". ", 1)[0]
    first_sentence = re.sub(
        r",?\s*per human directive.*$", "", first_sentence, flags=re.IGNORECASE
    )
    if INTERNAL_DECISION.search(first_sentence):
        return ""
    return _player_text(first_sentence)


def collect_digest(repo: str, now: datetime | None = None) -> DigestData:
    """Collect the previous seven days using git and GitHub's CLI."""
    now = (now or datetime.now(UTC)).astimezone(UTC)
    since = now - timedelta(days=7)
    since_date = since.date().isoformat()
    since_iso = since.isoformat().replace("+00:00", "Z")

    prs = _run_json(
        [
            "gh", "pr", "list", "--repo", repo, "--state", "merged",
            "--search", f"merged:>={since_date}", "--limit", "100",
            "--json", "title,mergedAt",
        ]
    )
    issues = _run_json(
        [
            "gh", "issue", "list", "--repo", repo, "--state", "closed",
            "--search", f"closed:>={since_date}", "--limit", "100",
            "--json", "title,closedAt",
        ]
    )
    comment_pages = _run_json(
        [
            "gh", "api", "--paginate", "--slurp",
            f"repos/{repo}/issues/comments?since={since_iso}&per_page=100",
        ]
    )
    comments = [
        comment for page in comment_pages for comment in page
    ]
    open_issues = _run_json(
        [
            "gh", "issue", "list", "--repo", repo, "--state", "open",
            "--limit", "100", "--json", "title,labels",
        ]
    )
    adr_log = subprocess.run(
        [
            "git", "log", f"--since={since_iso}", "--format=%s",
            "--", "docs/adr",
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.splitlines()

    shipped_by_task = {
        task: text
        for task, text in _task_entries(prs).items()
        if not INTERNAL_SHIPMENT.search(text)
    }
    for task, text in _task_entries(issues).items():
        if not INTERNAL_SHIPMENT.search(text):
            shipped_by_task.setdefault(task, text)
    decisions = {
        text
        for comment in comments
        if str(comment.get("body", "")).startswith(("[DECISION]", "[GATE]"))
        if (text := _decision_text(str(comment["body"]).split("]", 1)[-1]))
    }
    decisions.update(
        text for subject in adr_log if (text := _decision_text(subject))
    )
    up_next_by_task = _task_entries(
        [
            item
            for item in open_issues
            if any(
                str(label.get("name", "")).startswith("role:")
                for label in item.get("labels", [])
            )
        ]
    )
    return DigestData(
        shipped=tuple(sorted(shipped_by_task.values())[:8]),
        decided=tuple(sorted(decisions)[:5]),
        up_next=tuple(sorted(up_next_by_task.values())[:5]),
    )


def render_digest(data: DigestData) -> str | None:
    """Render at most one Discord message, or nothing for an empty week."""
    if not data.shipped and not data.decided:
        return None

    sections = (
        ("Shipped", data.shipped),
        ("Decided", data.decided),
        ("Up next", data.up_next),
    )
    lines = ["**This week in PoE Upgrade Advisor**"]
    for heading, values in sections:
        if not values:
            continue
        lines.extend(("", f"**{heading}**"))
        for value in values:
            candidate = [*lines, f"• {value}"]
            if len("\n".join(candidate)) > MAX_DISCORD_MESSAGE:
                if len("\n".join([*lines, "• …"])) <= MAX_DISCORD_MESSAGE:
                    lines.append("• …")
                return "\n".join(lines)
            lines.append(f"• {value}")
    return "\n".join(lines)


def week_marker(now: datetime | None = None) -> str:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    year, week, _ = current.isocalendar()
    return f"{year}-W{week:02d}"


def digest_due(now: datetime | None = None) -> bool:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    return current.weekday() == 6 and current.hour >= 18
