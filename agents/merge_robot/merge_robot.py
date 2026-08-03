#!/usr/bin/env python3
"""Merge Robot v0 — deterministic gatekeeper. Runs in GitHub Actions with the
MERGE_ROBOT_TOKEN (the only token with merge rights). See SPEC.md; conditions
are numbered to match.

Requires: pip install requests
Env: GITHUB_REPOSITORY, MERGE_ROBOT_TOKEN, PR_NUMBER (or sweeps all labeled PRs)
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import requests

from agents.interfaces.packet import parent_of
from agents.merge_robot.patterns import (
    BANNED,
    PROTECTED,
    TEST_SIG,
    matches_protected,
)

API = "https://api.github.com"
REPO = os.environ["GITHUB_REPOSITORY"]
TOK = os.environ["MERGE_ROBOT_TOKEN"]
H = {"Authorization": f"Bearer {TOK}", "Accept": "application/vnd.github+json"}

REQUIRED_CHECKS = {"lint", "test", "contracts", "doctrine-invariants",
                   "assumptions-fixtures", "web-test", "overlay-test",
                   "coverage-floor", "packet-validation"}


def gh(path: str, **kw):
    r = requests.get(f"{API}{path}", headers=H, **kw); r.raise_for_status(); return r.json()


def fail(pr: int, cond: str) -> None:
    requests.post(f"{API}/repos/{REPO}/issues/{pr}/comments", headers=H,
                  json={"body": f"MERGE BLOCKED — failed condition: {cond}"})
    requests.delete(f"{API}/repos/{REPO}/issues/{pr}/labels/ready-to-merge", headers=H)
    print(f"PR #{pr}: BLOCKED — {cond}"); sys.exit(0)


def _default_pause_merges_path() -> Path:
    """Resolve the shared mailroom when invoked from a fan worktree."""
    starts = (Path.cwd(), Path(__file__).resolve().parent)
    visited: set[Path] = set()
    for start in starts:
        for directory in (start, *start.parents):
            if directory in visited:
                continue
            visited.add(directory)
            mailroom = directory / "mailroom"
            if mailroom.is_dir():
                return mailroom / "PAUSE_MERGES"
    return Path.cwd() / "mailroom/PAUSE_MERGES"


def pause_merges_reason(
    path: str | Path | None = None, *, issue_loader=None
) -> str | None:
    """Return a fail-closed reason when the local merge pause is active.

    The local file protects on-box schedulers. An open GitHub issue labelled
    ``merge-pause`` is the authoritative transport visible to hosted runners.
    """
    configured = path if path is not None else os.environ.get("PAUSE_MERGES_PATH")
    pause_path = Path(configured) if configured else _default_pause_merges_path()
    try:
        if not pause_path.is_file():
            local_reason = None
        else:
            pause_path.read_text(encoding="utf-8")
            local_reason = f"PAUSE_MERGES active at {pause_path}"
    except OSError as exc:
        return f"PAUSE_MERGES state unreadable at {pause_path}: {exc}"
    if local_reason is not None:
        return local_reason

    loader = gh if issue_loader is None else issue_loader
    try:
        issues = loader(
            f"/repos/{REPO}/issues",
            params={"labels": "merge-pause", "state": "open"},
        )
    except Exception as exc:  # noqa: BLE001 - merge authority fails closed
        return f"merge-pause state unreachable: {type(exc).__name__}: {exc}"
    if not isinstance(issues, list):
        return "merge-pause state unreachable: invalid GitHub response"
    if issues:
        issue = issues[0]
        if not isinstance(issue, dict) or "number" not in issue or "title" not in issue:
            return "merge-pause state unreachable: malformed issue response"
        return f"merge-pause active: #{issue['number']} {issue['title']}"
    return None


def approval_failure(reviews: list[dict], author: str) -> str | None:
    """Diagnose conditions 2/3 without collapsing distinct operator actions."""
    approved = [review for review in reviews if review.get("state") == "APPROVED"]
    if not approved:
        return "(2) no APPROVED review"
    evidenced = [
        review
        for review in approved
        if "EVIDENCE-SHA256:" in (review.get("body") or "")
    ]
    if not evidenced:
        return "(3) APPROVED review lacks EVIDENCE-SHA256"
    if not any((review.get("user") or {}).get("login") != author for review in evidenced):
        return "(3) evidence-bearing approval is author-only"
    return None


class TaskLinkError(ValueError):
    """Condition 4 cannot identify one structurally valid task link."""


def _task_id_from_title(title: str) -> str:
    match = re.search(r"\bTASK-[0-9]+(?:-S[0-9]+)?\b", title)
    if not match:
        raise TaskLinkError("linked issue title has no well-formed TASK id")
    return match.group(0)


def resolve_task_link(pr: dict, issue_loader=gh) -> dict:
    """Resolve whole-task ``Fixes`` or structurally checked stage ``Refs``."""
    body = pr.get("body") or ""
    fixes = re.findall(r"(?i)\bFixes\s+#(\d+)\b", body)
    refs = re.findall(r"(?i)\bRefs\s+#(\d+)\b", body)
    if len(fixes) + len(refs) != 1:
        raise TaskLinkError("PR must contain exactly one Fixes #N or Refs #N task link")
    stage_ids = set(re.findall(
        r"\bTASK-[0-9]+-S[0-9]+\b",
        " ".join((pr.get("title") or "", ((pr.get("head") or {}).get("ref") or ""))),
    ))
    issue_number = int((fixes or refs)[0])
    issue = issue_loader(f"/repos/{REPO}/issues/{issue_number}")
    if issue.get("state", "open") != "open":
        raise TaskLinkError("linked TASK issue is not open")
    issue_task_id = _task_id_from_title(issue.get("title") or "")

    if fixes:
        if stage_ids:
            raise TaskLinkError("stage PR must use Refs, never Fixes that closes its parent")
        return {
            "kind": "task",
            "task_id": issue_task_id,
            "parent_task_id": None,
            "issue": issue,
        }

    if len(stage_ids) != 1:
        raise TaskLinkError("Refs task link requires exactly one stage ID in PR title or branch")
    stage_id = next(iter(stage_ids))
    derived_parent = parent_of(stage_id)
    if derived_parent != issue_task_id:
        raise TaskLinkError(
            f"stage {stage_id} derives parent {derived_parent}, not linked {issue_task_id}"
        )
    return {
        "kind": "stage",
        "task_id": stage_id,
        "parent_task_id": derived_parent,
        "issue": issue,
    }


def task_completion_comment(link: dict, pr_number: int) -> str:
    if link["kind"] == "stage":
        return (
            f"Stage {link['task_id']} completed by merged PR #{pr_number}. "
            f"Parent {link['parent_task_id']} remains open for later stages."
        )
    return (
        f"PR #{pr_number} merged by robot for {link['task_id']}. "
        "Author: close this task if acceptance criteria are met."
    )


def check_pr(pr_number: int) -> None:
    pause_reason = pause_merges_reason()
    if pause_reason is not None:
        fail(pr_number, f"(0) {pause_reason}")
    pr = gh(f"/repos/{REPO}/pulls/{pr_number}")
    sha, author = pr["head"]["sha"], pr["user"]["login"]

    # 1 — required checks green
    runs = gh(f"/repos/{REPO}/commits/{sha}/check-runs")["check_runs"]
    ok = {r["name"] for r in runs if r["conclusion"] == "success"}
    missing = REQUIRED_CHECKS - ok
    if missing:
        fail(pr_number, f"(1) checks not green: {sorted(missing)}")

    # 2+3 — evidence-bearing approval from a different identity
    reviews = gh(f"/repos/{REPO}/pulls/{pr_number}/reviews")
    approval_problem = approval_failure(reviews, author)
    if approval_problem is not None:
        fail(pr_number, approval_problem)

    # 4 — whole-task Fixes or structurally derived stage Refs (ADR-0008)
    try:
        task_link = resolve_task_link(pr)
    except TaskLinkError as exc:
        fail(pr_number, f"(4) {exc}")
    issue = task_link["issue"]
    labels = {l["name"] for l in issue["labels"]}

    # 5/6/7 — diff inspection
    files = gh(f"/repos/{REPO}/pulls/{pr_number}/files", params={"per_page": 300})
    for f in files:
        if matches_protected(f["filename"]) and "protected-change" not in labels:
            fail(pr_number, f"(5) protected path {f['filename']} without protected-change label")
        patch = f.get("patch", "") or ""
        for pat in BANNED:
            if re.search(pat, patch):
                fail(pr_number, f"(6) banned pattern '{pat}' in {f['filename']}")
        if "test-change-authorized" not in labels:
            for line in patch.splitlines():
                if any(re.match(sig, line) for sig in TEST_SIG):
                    fail(pr_number, f"(7) test deletion/skip in {f['filename']}")

    # 8 is enforced directly by the required coverage-floor CI job.

    # 9 — mergeability, then merge
    if pr.get("mergeable_state") == "behind":
        requests.put(f"{API}/repos/{REPO}/pulls/{pr_number}/update-branch",
                     headers=H, json={})
        print(f"PR #{pr_number}: rebased; will re-check next sweep"); return
    r = requests.put(f"{API}/repos/{REPO}/pulls/{pr_number}/merge", headers=H,
                     json={"merge_method": "squash"})
    r.raise_for_status()
    requests.post(f"{API}/repos/{REPO}/issues/{pr_number}/comments", headers=H,
                  json={"body": "MERGED by robot: all conditions verified (SPEC.md)."})
    requests.post(f"{API}/repos/{REPO}/issues/{issue['number']}/comments", headers=H,
                  json={"body": task_completion_comment(task_link, pr_number)})
    print(f"PR #{pr_number}: MERGED")


def main() -> None:
    if os.environ.get("PR_NUMBER"):
        check_pr(int(os.environ["PR_NUMBER"])); return
    prs = gh(f"/repos/{REPO}/pulls", params={"state": "open", "per_page": 100})
    for pr in prs:
        if any(l["name"] == "ready-to-merge" for l in pr["labels"]):
            try:
                check_pr(pr["number"])
            except SystemExit:
                continue


if __name__ == "__main__":
    main()
