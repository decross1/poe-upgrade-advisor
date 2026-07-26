"""Review regressions for TASK-209 lane C (PR #82)."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_windows_cleanroom_checks_launcher_stderr():
    script = (
        ROOT / "scripts" / "cleanroom_windows_check.ps1"
    ).read_text(encoding="utf-8")
    stub_log_capture = script.split(
        "$exited = $Process.WaitForExit", 1
    )[1].split('if ($log -match "engine could not start")', 1)[0]

    assert "ReadAllText($outLog)" in stub_log_capture
    assert "ReadAllText($errLog)" in stub_log_capture, (
        "launch.py reports SystemExit failures on stderr, but stub-mode "
        "clean-room validation only searches stdout"
    )


def test_launch_announcement_remains_windows_only():
    announcement = (
        ROOT / "docs" / "announcements" / "mvp_launch.md"
    ).read_text(encoding="utf-8")

    assert "## Install & run (Windows)" in announcement
    assert "latest Windows build (`.zip`)" in announcement
    assert "Windows 10/11 x86-64" in announcement
    assert "the Windows build is days away" not in announcement
    assert "poe-upgrade-advisor-v0-8eaa2a4.tar.gz" not in announcement
