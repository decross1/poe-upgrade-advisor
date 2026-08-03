import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def load_release_notes():
    path = Path(__file__).parents[1] / "release_notes.py"
    spec = importlib.util.spec_from_file_location("release_notes", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def git_log_output(*commits):
    return "".join(f"{subject}\x1f{body}\x1e\n" for subject, body in commits)


def collect_with(module, output):
    with patch.object(
        module.subprocess, "run", return_value=SimpleNamespace(stdout=output)
    ) as run:
        data = module.collect_release("/repo", "v1", "v2")
    command = run.call_args.args[0]
    assert command[:3] == ["git", "-C", "/repo"]
    assert "v1..v2" in command
    return data


def test_multi_commit_range_collects_and_renders():
    module = load_release_notes()
    output = git_log_output(
        (
            "Merge TASK-210-S3: clipboard-to-verdict pipeline snapshots",
            "Fixes #94\nPR #112",
        ),
        (
            "TASK-300-S1: render release notes for merged mission work",
            "Refs #97",
        ),
    )

    data = collect_with(module, output)
    message = module.render_release(data)

    assert data.entries[0].task_id == "TASK-210-S3"
    assert data.entries[0].summary == "clipboard-to-verdict pipeline snapshots"
    assert data.entries[0].refs == ("#94", "#112")
    assert message is not None
    assert message.startswith("**New in PoE Upgrade Advisor**")
    assert "**TASK-210-S3** clipboard-to-verdict pipeline snapshots (#94, #112)" in message
    assert "**TASK-300-S1** render release notes for merged mission work (#97)" in message
    assert len(message) <= 1900


def test_empty_range_returns_none():
    module = load_release_notes()

    data = collect_with(module, "")

    assert data.entries == ()
    assert module.render_release(data) is None


def test_render_truncates_past_max_discord_message():
    module = load_release_notes()
    data = module.ReleaseData(
        since_ref="v1",
        until_ref="v2",
        entries=tuple(
            module.ReleaseEntry(task_id=f"TASK-{100 + index}", summary="x" * 120)
            for index in range(40)
        ),
    )

    message = module.render_release(data)

    assert message is not None
    assert len(message) <= 1900
    assert message.endswith("• …")


def test_commit_without_task_id_renders_summary_only():
    module = load_release_notes()
    output = git_log_output(
        ("polish verdict card spacing", ""),
    )

    data = collect_with(module, output)
    message = module.render_release(data)

    assert data.entries[0].task_id is None
    assert message is not None
    assert "• polish verdict card spacing" in message
    assert "**TASK" not in message
