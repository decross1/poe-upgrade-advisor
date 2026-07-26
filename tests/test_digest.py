import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


def load_digest():
    path = Path(__file__).parents[1] / "bot" / "digest.py"
    spec = importlib.util.spec_from_file_location("digest", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_sample_week_renders_player_facing_template():
    module = load_digest()
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "digest_sample_week.json").read_text()
    )

    message = module.render_digest(module.DigestData(**fixture))

    assert message is not None
    assert "**Shipped**" in message
    assert "**Decided**" in message
    assert "**Up next**" in message
    assert len(message) <= 1900


def test_empty_week_posts_nothing_even_with_up_next():
    module = load_digest()

    assert module.render_digest(module.DigestData(up_next=("Future work",))) is None


def test_renderer_truncates_to_one_discord_message():
    module = load_digest()
    data = module.DigestData(
        shipped=tuple(f"Change {index} " + "x" * 100 for index in range(50))
    )

    message = module.render_digest(data)

    assert message is not None
    assert len(message) <= 1900
    assert message.endswith("• …")


def test_schedule_and_week_marker_use_utc():
    module = load_digest()
    before = datetime(2026, 7, 26, 17, 59, tzinfo=UTC)
    due = datetime(2026, 7, 26, 18, 0, tzinfo=UTC)

    assert not module.digest_due(before)
    assert module.digest_due(due)
    assert module.week_marker(due) == "2026-W30"


def test_collection_deduplicates_tasks_and_filters_org_jargon():
    module = load_digest()
    responses = [
        [{"title": "TASK-204: one-tap assumption override"}],
        [
            {"title": "TASK-204: duplicate closed issue"},
            {"title": "TASK-002: harden CI gates"},
        ],
        [
            [
                {"body": "[DECISION] Single-channel mode, per human directive"},
                {"body": "[DECISION] Backend agent reassigned to TASK-101"},
            ]
        ],
        [
            {
                "title": "TASK-101: validate upgrade math",
                "labels": [{"name": "role:backend"}],
            }
        ],
    ]

    with (
        patch.object(module, "_run_json", side_effect=responses),
        patch.object(
            module.subprocess,
            "run",
            return_value=SimpleNamespace(stdout=""),
        ),
    ):
        data = module.collect_digest(
            "owner/repo", datetime(2026, 7, 26, 18, tzinfo=UTC)
        )

    assert data.shipped == ("one-tap assumption override",)
    assert data.decided == ("Single-channel mode",)
    assert data.up_next == ("validate upgrade math",)


def test_player_text_drops_internal_adr_suffix_without_marker_residue():
    module = load_digest()

    assert (
        module._player_text(
            "Overlay shell shipped + ADR-0004 (Tauri provisional fallback)"
        )
        == "Overlay shell shipped"
    )


def test_player_text_drops_parenthetical_task_reference_without_dangling_words():
    module = load_digest()

    assert (
        module._player_text(
            "Overlay shell shipped (Tauri leg of TASK-201)"
        )
        == "Overlay shell shipped"
    )
