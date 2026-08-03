"""Review reproductions for PR #102's merge-gate metadata."""

from __future__ import annotations

import importlib
import sys


def _robot(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/repo")
    monkeypatch.setenv("MERGE_ROBOT_TOKEN", "test-only")
    sys.modules.pop("agents.merge_robot.merge_robot", None)
    return importlib.import_module("agents.merge_robot.merge_robot")


def test_pr102_has_one_structurally_valid_task_link(monkeypatch):
    robot = _robot(monkeypatch)
    pr = {
        "title": "ORG: repacketize parked PRs #87/#91 as budget-fit stages",
        "body": "Task: ORG -- issue #97. Refs #7, #79.",
        "head": {"ref": "role/org-repacketize-parked-prs"},
    }
    issues = {
        7: {"number": 7, "state": "open", "title": "TASK-102: corpus"},
        79: {"number": 79, "state": "open", "title": "TASK-210: overlay"},
        97: {"number": 97, "state": "open", "title": "ORG MISSION"},
    }

    robot.resolve_task_link(
        pr,
        issue_loader=lambda path: issues[int(path.rsplit("/", 1)[1])],
    )


def test_pr102_protected_packet_changes_are_authorized():
    from agents.merge_robot.patterns import matches_protected

    changed_paths = [
        "tasks/packets/TASK-102-S2.json",
        "tasks/packets/TASK-102-S3.json",
        "tasks/packets/TASK-102-S4.json",
        "tasks/packets/TASK-102-S5.json",
        "tasks/packets/TASK-210-S2.json",
        "tasks/packets/TASK-210-S3.json",
        "tasks/BACKLOG.md",
        "tests/test_packets.py",
    ]
    issue_97_labels: set[str] = set()
    unauthorized = [
        path
        for path in changed_paths
        if matches_protected(path) and "protected-change" not in issue_97_labels
    ]

    assert not unauthorized, f"protected paths lack authorization: {unauthorized}"
