"""Review reproduction for PR #104's merge-gate metadata."""

from __future__ import annotations

import importlib
import sys


def _robot(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/repo")
    monkeypatch.setenv("MERGE_ROBOT_TOKEN", "test-only")
    sys.modules.pop("agents.merge_robot.merge_robot", None)
    return importlib.import_module("agents.merge_robot.merge_robot")


def test_pr104_has_one_structurally_valid_task_link(monkeypatch):
    robot = _robot(monkeypatch)
    pr = {
        "title": "ORG: rule PR #102 superseded; record L-19",
        "body": "Refs #97, #24, #7, #79.",
        "head": {"ref": "pm/ORG-pr102-superseded"},
    }
    issues = {
        7: {"number": 7, "state": "open", "title": "TASK-102: corpus"},
        24: {"number": 24, "state": "open", "title": "TASK-007: merge robot"},
        79: {"number": 79, "state": "open", "title": "TASK-210: overlay"},
        97: {"number": 97, "state": "open", "title": "ORG MISSION"},
    }

    robot.resolve_task_link(
        pr,
        issue_loader=lambda path: issues[int(path.rsplit("/", 1)[1])],
    )
