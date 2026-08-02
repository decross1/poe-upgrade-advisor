from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _coverage_run(tmp_path: Path, measured: float, floor: float) -> subprocess.CompletedProcess:
    coverage = tmp_path / "coverage.json"
    recorded = tmp_path / "floor.json"
    coverage.write_text(json.dumps({"totals": {"percent_covered": measured}}))
    recorded.write_text(json.dumps({"floor": floor}))
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts/check_coverage_floor.py"),
         "--coverage", str(coverage), "--floor", str(recorded)],
        text=True,
        capture_output=True,
        check=False,
    )


def test_coverage_floor_blocks_regression_and_accepts_floor(tmp_path):
    assert _coverage_run(tmp_path, 67.89, 67.9).returncode == 1
    assert _coverage_run(tmp_path, 67.9, 67.9).returncode == 0
    assert _coverage_run(tmp_path, 68.0, 67.9).returncode == 0


def test_committed_coverage_floor_is_active_and_achievable():
    """Assert the ratchet's PROPERTIES, never its literal value.

    A ratchet only moves up. Pinning the exact number means every coverage
    improvement breaks a test, which creates standing pressure not to raise the
    floor — the gate would be held down by its own guard. Assert instead that
    it is active, not vestigial, and derived from a tree that actually achieves
    it.
    """
    floor = json.loads(
        (ROOT / "agents/merge_robot/coverage_floor.json").read_text()
    )["floor"]
    assert floor > 0.0, "an inert floor is the defect this gate was built to fix"
    assert floor >= 60.0, "below the pre-program baseline is a weakening"
    assert floor <= 100.0


def test_required_checks_have_real_ci_jobs(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/repo")
    monkeypatch.setenv("MERGE_ROBOT_TOKEN", "test-only")
    sys.modules.pop("agents.merge_robot.merge_robot", None)
    from agents.merge_robot.merge_robot import REQUIRED_CHECKS

    workflow = yaml.load(
        (ROOT / ".github/workflows/ci.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    jobs = set(workflow["jobs"])
    previous = {"lint", "test", "contracts", "doctrine-invariants", "assumptions-fixtures"}
    assert REQUIRED_CHECKS >= previous
    assert {"web-test", "overlay-test", "coverage-floor"} <= REQUIRED_CHECKS
    assert REQUIRED_CHECKS <= jobs


def test_ci_collects_packaging_tests_and_upstream_sync_is_not_a_noop():
    ci = yaml.load((ROOT / ".github/workflows/ci.yml").read_text(), Loader=yaml.BaseLoader)
    test_steps = ci["jobs"]["test"]["steps"]
    assert any("pytest tests packaging" in step.get("run", "") for step in test_steps)

    upstream = yaml.load(
        (ROOT / ".github/workflows/upstream-sync.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    steps = upstream["jobs"]["bump"]["steps"]
    corpus = next(step for step in steps if step.get("name", "").startswith("run corpus"))
    assert "engine/tests" in corpus["run"]
    assert "if [ -f" not in corpus["run"]
