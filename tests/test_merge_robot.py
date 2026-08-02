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


def test_pause_merges_gate_is_read_only_and_precedes_remote_inspection(
    monkeypatch, tmp_path
):
    robot = _robot(monkeypatch)
    pause = tmp_path / "PAUSE_MERGES"
    pause.write_text("main is red\n")
    monkeypatch.setenv("PAUSE_MERGES_PATH", str(pause))
    observed = {}

    def blocked(pr, reason):
        observed.update(pr=pr, reason=reason)
        raise RuntimeError("blocked")

    monkeypatch.setattr(robot, "fail", blocked)
    monkeypatch.setattr(
        robot, "gh", lambda path, **kw: pytest.fail("remote inspection must not run")
    )
    with pytest.raises(RuntimeError, match="blocked"):
        robot.check_pr(42)
    assert observed == {
        "pr": 42,
        "reason": f"(0) PAUSE_MERGES active at {pause}",
    }
    assert pause.read_text() == "main is red\n"


def test_github_merge_pause_issue_blocks_when_local_state_is_absent(
    monkeypatch, tmp_path
):
    robot = _robot(monkeypatch)
    calls = []

    def issues(path, **kwargs):
        calls.append((path, kwargs))
        return [{"number": 123, "title": "Main is red"}]

    reason = robot.pause_merges_reason(tmp_path / "absent", issue_loader=issues)
    assert reason == "merge-pause active: #123 Main is red"
    assert calls == [(
        "/repos/example/repo/issues",
        {"params": {"labels": "merge-pause", "state": "open"}},
    )]


@pytest.mark.parametrize(
    ("loader", "detail"),
    [
        (lambda path, **kwargs: (_ for _ in ()).throw(OSError("offline")), "offline"),
        (lambda path, **kwargs: {"status": 503}, "invalid GitHub response"),
        (lambda path, **kwargs: [{}], "malformed issue response"),
    ],
)
def test_github_merge_pause_transport_fails_closed(
    monkeypatch, tmp_path, loader, detail
):
    robot = _robot(monkeypatch)
    reason = robot.pause_merges_reason(tmp_path / "absent", issue_loader=loader)
    assert reason is not None
    assert "unreachable" in reason and detail in reason


def test_both_pause_transports_clear_allows_merge_inspection(monkeypatch, tmp_path):
    robot = _robot(monkeypatch)
    assert robot.pause_merges_reason(
        tmp_path / "absent", issue_loader=lambda path, **kwargs: []
    ) is None


def test_default_pause_path_finds_shared_mailroom_from_fan_worktree(
    monkeypatch, tmp_path
):
    robot = _robot(monkeypatch)
    shared = tmp_path / "project/mailroom"
    worktree = tmp_path / "project/worktrees/lane-b"
    shared.mkdir(parents=True)
    worktree.mkdir(parents=True)
    pause = shared / "PAUSE_MERGES"
    pause.write_text("main is red\n")
    monkeypatch.delenv("PAUSE_MERGES_PATH", raising=False)
    monkeypatch.chdir(worktree)
    assert robot.pause_merges_reason(
        issue_loader=lambda path, **kwargs: pytest.fail("local pause must short-circuit")
    ) == f"PAUSE_MERGES active at {pause}"


def test_pause_merges_reader_fails_closed_when_present_state_is_unreadable(
    monkeypatch, tmp_path
):
    robot = _robot(monkeypatch)
    pause = tmp_path / "PAUSE_MERGES"
    pause.write_text("main is red\n")
    original = robot.Path.read_text

    def unreadable(self, *args, **kwargs):
        if self == pause:
            raise OSError("simulated unreadable state")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(robot.Path, "read_text", unreadable)
    reason = robot.pause_merges_reason(
        pause, issue_loader=lambda path, **kwargs: pytest.fail("unreadable is paused")
    )
    assert reason is not None
    assert "unreadable" in reason and "simulated unreadable state" in reason
    assert pause.is_file()


def test_absent_pause_state_does_not_get_created(monkeypatch, tmp_path):
    robot = _robot(monkeypatch)
    pause = tmp_path / "PAUSE_MERGES"
    assert robot.pause_merges_reason(
        pause, issue_loader=lambda path, **kwargs: []
    ) is None
    assert not pause.exists()


@pytest.mark.parametrize(
    ("reviews", "expected"),
    [
        ([{"state": "COMMENTED", "user": {"login": "reviewer"}}],
         "(2) no APPROVED review"),
        ([{"state": "APPROVED", "body": "looks good",
           "user": {"login": "reviewer"}}],
         "(3) APPROVED review lacks EVIDENCE-SHA256"),
        ([{"state": "APPROVED", "body": "EVIDENCE-SHA256:abc",
           "user": {"login": "author"}}],
         "(3) evidence-bearing approval is author-only"),
    ],
)
def test_approval_gate_diagnoses_each_distinct_failure(
    monkeypatch, reviews, expected
):
    robot = _robot(monkeypatch)
    assert robot.approval_failure(reviews, "author") == expected


def test_approval_gate_accepts_evidenced_non_author(monkeypatch):
    robot = _robot(monkeypatch)
    reviews = [{
        "state": "APPROVED",
        "body": "execution proof EVIDENCE-SHA256:abc",
        "user": {"login": "reviewer"},
    }]
    assert robot.approval_failure(reviews, "author") is None


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
