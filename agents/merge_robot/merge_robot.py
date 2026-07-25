#!/usr/bin/env python3
"""Merge Robot v0 — deterministic gatekeeper. Runs in GitHub Actions with the
MERGE_ROBOT_TOKEN (the only token with merge rights). See SPEC.md; conditions
are numbered to match.

Requires: pip install requests
Env: GITHUB_REPOSITORY, MERGE_ROBOT_TOKEN, PR_NUMBER (or sweeps all labeled PRs)
"""
from __future__ import annotations
import fnmatch, json, os, re, sys
import requests

API = "https://api.github.com"
REPO = os.environ["GITHUB_REPOSITORY"]
TOK = os.environ["MERGE_ROBOT_TOKEN"]
H = {"Authorization": f"Bearer {TOK}", "Accept": "application/vnd.github+json"}

PROTECTED = ["agents/*", ".github/*", "contracts/*", "PRODUCT_DOCTRINE.md",
             "AGENTS.md", "engine/corpus/*", "scripts/check_invariants.py"]
BANNED = [r"WriteProcessMemory", r"ReadProcessMemory", r"SendInput\b",
          r"keybd_event", r"mouse_event", r"CreateRemoteThread",
          r"OpenProcess\(", r"pathofexile\.com/(?!api/)"]
TEST_SIG = [r"^-\s*def test_", r"^-\s*it\(", r"^-\s*test\(",
            r"^\+.*@pytest\.mark\.skip", r"^\+.*\.skip\(", r"^\+.*xit\("]
REQUIRED_CHECKS = {"lint", "test", "contracts", "doctrine-invariants",
                   "assumptions-fixtures"}


def gh(path: str, **kw):
    r = requests.get(f"{API}{path}", headers=H, **kw); r.raise_for_status(); return r.json()


def fail(pr: int, cond: str) -> None:
    requests.post(f"{API}/repos/{REPO}/issues/{pr}/comments", headers=H,
                  json={"body": f"MERGE BLOCKED — failed condition: {cond}"})
    requests.delete(f"{API}/repos/{REPO}/issues/{pr}/labels/ready-to-merge", headers=H)
    print(f"PR #{pr}: BLOCKED — {cond}"); sys.exit(0)


def check_pr(pr_number: int) -> None:
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
    approved = [r for r in reviews if r["state"] == "APPROVED"
                and "EVIDENCE-SHA256:" in (r.get("body") or "")
                and r["user"]["login"] != author]
    if not approved:
        fail(pr_number, "(2/3) no evidence-bearing approval from a non-author identity")

    # 4 — linked TASK issue
    m = re.search(r"Fixes #(\d+)", pr.get("body") or "")
    if not m:
        fail(pr_number, "(4) PR body missing 'Fixes #<issue>'")
    issue = gh(f"/repos/{REPO}/issues/{m.group(1)}")
    if "TASK-" not in issue["title"]:
        fail(pr_number, "(4) linked issue is not a TASK")
    labels = {l["name"] for l in issue["labels"]}

    # 5/6/7 — diff inspection
    files = gh(f"/repos/{REPO}/pulls/{pr_number}/files", params={"per_page": 300})
    for f in files:
        if any(fnmatch.fnmatch(f["filename"], p) for p in PROTECTED) \
                and "protected-change" not in labels:
            fail(pr_number, f"(5) protected path {f['filename']} without protected-change label")
        patch = f.get("patch", "") or ""
        for pat in BANNED:
            if re.search(pat, patch):
                fail(pr_number, f"(6) banned pattern '{pat}' in {f['filename']}")
        if "test-change-authorized" not in labels:
            for line in patch.splitlines():
                if any(re.match(sig, line) for sig in TEST_SIG):
                    fail(pr_number, f"(7) test deletion/skip in {f['filename']}")

    # 8 — coverage ratchet (artifact written by CI to check-run output; best-effort v0)
    floor_path = "agents/merge_robot/coverage_floor.json"
    try:
        floor = json.load(open(floor_path))["floor"]
        cov_run = next((r for r in runs if r["name"] == "test"), None)
        summary = (cov_run or {}).get("output", {}).get("summary") or ""
        mm = re.search(r"COVERAGE:\s*([\d.]+)", summary)
        if mm and float(mm.group(1)) < floor - 0.1:
            fail(pr_number, f"(8) coverage {mm.group(1)} below floor {floor}")
    except FileNotFoundError:
        pass  # ratchet activates once the first floor file is committed

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
                  json={"body": f"PR #{pr_number} merged by robot. "
                                "Author: close this task if acceptance criteria are met."})
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
