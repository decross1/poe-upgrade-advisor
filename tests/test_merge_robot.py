from __future__ import annotations

import fnmatch
import importlib
import re
import sys


def test_patterns_importable_without_merge_robot_token(monkeypatch):
    monkeypatch.delenv("MERGE_ROBOT_TOKEN", raising=False)
    sys.modules.pop("agents.merge_robot.patterns", None)
    patterns = importlib.import_module("agents.merge_robot.patterns")
    assert "agents/*" in patterns.PROTECTED


def test_security_patterns_cover_expected_paths_and_test_weakening():
    from agents.merge_robot.patterns import PROTECTED, TEST_SIG

    for path in ("agents/dispatch.py", ".github/workflows/ci.yml", "contracts/openapi.yaml"):
        assert any(fnmatch.fnmatch(path, pattern) for pattern in PROTECTED)
    assert not any(fnmatch.fnmatch("web/src/App.tsx", pattern) for pattern in PROTECTED)
    assert any(re.match(pattern, "+@pytest.mark.skip") for pattern in TEST_SIG)
    assert any(re.match(pattern, "-def test_gate():") for pattern in TEST_SIG)


def test_merge_robot_enforces_the_shared_pattern_objects(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/repo")
    monkeypatch.setenv("MERGE_ROBOT_TOKEN", "test-only")
    sys.modules.pop("agents.merge_robot.merge_robot", None)
    robot = importlib.import_module("agents.merge_robot.merge_robot")
    patterns = importlib.import_module("agents.merge_robot.patterns")
    assert robot.PROTECTED is patterns.PROTECTED
    assert robot.BANNED is patterns.BANNED
    assert robot.TEST_SIG is patterns.TEST_SIG
