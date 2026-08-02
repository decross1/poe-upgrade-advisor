from __future__ import annotations

import fnmatch
import importlib
import re
import sys

import pytest


def test_patterns_importable_without_merge_robot_token(monkeypatch):
    monkeypatch.delenv("MERGE_ROBOT_TOKEN", raising=False)
    sys.modules.pop("agents.merge_robot.patterns", None)
    patterns = importlib.import_module("agents.merge_robot.patterns")
    assert "agents/*" in patterns.PROTECTED


def _matches_test_change(line: str) -> bool:
    from agents.merge_robot.patterns import TEST_SIG

    return any(re.match(pattern, line) for pattern in TEST_SIG)


def test_security_patterns_cover_expected_paths():
    from agents.merge_robot.patterns import PROTECTED

    for path in ("agents/dispatch.py", ".github/workflows/ci.yml", "contracts/openapi.yaml"):
        assert any(fnmatch.fnmatch(path, pattern) for pattern in PROTECTED)
    assert not any(fnmatch.fnmatch("web/src/App.tsx", pattern) for pattern in PROTECTED)


@pytest.mark.parametrize(
    "line",
    [
        "+@pytest.mark.skip(reason='broken')",
        "+    it.skip('excluded', () => {})",
        "+test.skip('excluded', () => {})",
        "+  describe.skip('excluded', () => {})",
        "+xit('excluded', () => {})",
        "-def test_gate():",
        "-  it('works', () => {})",
    ],
)
def test_test_signatures_match_real_test_deletion_or_skip(line):
    assert _matches_test_change(line)


@pytest.mark.parametrize(
    "line",
    [
        "+sys.exit(main())",
        "+    sys.exit(1)",
        "+raise SystemExit(2)",
        "+os._exit(0)",
        "+p.exit(code)",
        "+runner.skip()",
    ],
)
def test_test_signatures_do_not_block_legitimate_exit_or_non_test_skip(line):
    assert not _matches_test_change(line)


def test_merge_robot_enforces_the_shared_pattern_objects(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/repo")
    monkeypatch.setenv("MERGE_ROBOT_TOKEN", "test-only")
    sys.modules.pop("agents.merge_robot.merge_robot", None)
    robot = importlib.import_module("agents.merge_robot.merge_robot")
    patterns = importlib.import_module("agents.merge_robot.patterns")
    assert robot.PROTECTED is patterns.PROTECTED
    assert robot.BANNED is patterns.BANNED
    assert robot.TEST_SIG is patterns.TEST_SIG


def _robot(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/repo")
    monkeypatch.setenv("MERGE_ROBOT_TOKEN", "test-only")
    sys.modules.pop("agents.merge_robot.merge_robot", None)
    return importlib.import_module("agents.merge_robot.merge_robot")


def test_stage_task_merges_with_refs_without_closing_parent(monkeypatch):
    robot = _robot(monkeypatch)
    issue = {
        "number": 79,
        "state": "open",
        "title": "TASK-210: multi-stage native runtime",
        "labels": [],
    }
    pr = {
        "title": "TASK-210-S1: Windows runtime",
        "body": "Refs #79",
        "head": {"ref": "frontend/task-210-s1"},
    }
    link = robot.resolve_task_link(pr, issue_loader=lambda path: issue)
    comment = robot.task_completion_comment(link, 91)
    assert link == {
        "kind": "stage",
        "task_id": "TASK-210-S1",
        "parent_task_id": "TASK-210",
        "issue": issue,
    }
    assert "remains open" in comment
    assert "close this task" not in comment.lower()
    assert "Fixes" not in pr["body"]


@pytest.mark.parametrize(
    ("pr", "issue_title", "message"),
    [
        (
            {"title": "TASK-210-S1: stage", "body": "Fixes #79", "head": {"ref": "stage"}},
            "TASK-210: parent",
            "stage PR must use Refs",
        ),
        (
            {"title": "TASK-210-S1: stage", "body": "Refs #79", "head": {"ref": "TASK-999-S1"}},
            "TASK-210: parent",
            "exactly one stage ID",
        ),
        (
            {"title": "TASK-999-S1: stage", "body": "Refs #79", "head": {"ref": "stage"}},
            "TASK-210: parent",
            "derives parent",
        ),
        (
            {"title": "normal", "body": "Fixes #79\nRefs #79", "head": {"ref": "normal"}},
            "TASK-210: parent",
            "exactly one",
        ),
    ],
)
def test_stage_task_link_rejects_ambiguous_or_parent_closing_forms(
    monkeypatch, pr, issue_title, message
):
    robot = _robot(monkeypatch)
    issue = {"number": 79, "state": "open", "title": issue_title, "labels": []}
    with pytest.raises(robot.TaskLinkError, match=message):
        robot.resolve_task_link(pr, issue_loader=lambda path: issue)
