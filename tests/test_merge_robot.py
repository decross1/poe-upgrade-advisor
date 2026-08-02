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
