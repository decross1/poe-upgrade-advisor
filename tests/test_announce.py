import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from test_bot import load_bot_module


def configure_release(monkeypatch):
    monkeypatch.setenv("RELEASE_SINCE_REF", "start")
    monkeypatch.setenv("RELEASE_ANNOUNCE_REF", "release")
    monkeypatch.setenv("RELEASE_REPO_PATH", "/repo")
    monkeypatch.setenv("ANNOUNCE_CHANNEL_ID", "987654321012345678")
    monkeypatch.setenv("DISCORD_TOKEN", "ghp_" + "d" * 36)
    monkeypatch.setenv("GITHUB_TOKEN", "sk-" + "g" * 32)


def test_announcement_reserves_range_scrubs_and_only_sends_once(
    tmp_path, monkeypatch
):
    configure_release(monkeypatch)
    module = load_bot_module(tmp_path, monkeypatch)
    channel = SimpleNamespace(send=AsyncMock())
    module.bot.get_channel = lambda channel_id: (
        channel if channel_id == 987654321012345678 else None
    )
    internal = (
        f"{module.os.environ['DISCORD_TOKEN']} "
        f"{module.os.environ['GITHUB_TOKEN']} "
        f"{module.os.environ['BOT_DB']} "
        f"{module.os.environ['ANNOUNCE_CHANNEL_ID']} "
        "5e192569-bd21-45af-9586-92f569fc5794 "
        "TASK-300-S2:TASK_ASSIGN:announce-wiring-v1 "
        "tasks/packets/TASK-300-S2.json backend"
    )

    with (
        patch.object(
            module, "resolve_release_ref", side_effect=["end-1", "end-1", "end-2"]
        ) as resolve,
        patch.object(module, "collect_release", return_value=object()) as collect,
        patch.object(
            module, "render_release", side_effect=[f"release notes {internal}", "later"]
        ),
        patch.object(module, "scrub", wraps=module.scrub) as scrubber,
    ):
        assert asyncio.run(module.bot.announce_release_once())
        assert not asyncio.run(module.bot.announce_release_once())
        assert asyncio.run(module.bot.announce_release_once())

    assert resolve.call_args_list[0].args == ("/repo", "release")
    assert collect.call_args_list[0].args == ("/repo", "start", "end-1")
    assert collect.call_args_list[1].args == ("/repo", "end-1", "end-2")
    assert channel.send.await_count == 2
    first = channel.send.await_args_list[0].args[0]
    later = channel.send.await_args_list[1].args[0]
    assert len(first) <= 1900
    assert "v0 is live" in first
    assert "real in-game Ctrl+C item" in first
    assert "item you paste yourself" in first
    assert "in-game overlay" in first
    assert "mods actually drove the delta" in first
    assert "/suggest" in first and "/suggest" in later
    assert "v0 is live" not in later
    for forbidden in (
        module.os.environ["DISCORD_TOKEN"],
        module.os.environ["GITHUB_TOKEN"],
        module.os.environ["BOT_DB"],
        module.os.environ["ANNOUNCE_CHANNEL_ID"],
        "5e192569-bd21-45af-9586-92f569fc5794",
        "TASK-300-S2:TASK_ASSIGN:announce-wiring-v1",
        "tasks/packets/TASK-300-S2.json",
        "backend",
    ):
        assert forbidden not in first
    assert scrubber.call_count == 2
    rows = list(
        module.bot.db.execute(
            "SELECT range_end, range_start, posted_at, includes_v0 "
            "FROM release_announce ORDER BY rowid"
        )
    )
    assert [(row[0], row[1], row[3]) for row in rows] == [
        ("end-1", "start", 1),
        ("end-2", "end-1", 0),
    ]
    assert all(row[2] is not None for row in rows)


def test_send_failure_is_reserved_and_never_reannounced(tmp_path, monkeypatch):
    configure_release(monkeypatch)
    module = load_bot_module(tmp_path, monkeypatch)
    channel = SimpleNamespace(send=AsyncMock(side_effect=RuntimeError("offline")))
    module.bot.get_channel = lambda _channel_id: channel

    with (
        patch.object(module, "resolve_release_ref", return_value="end"),
        patch.object(module, "collect_release", return_value=object()),
        patch.object(module, "render_release", return_value="release notes"),
    ):
        with pytest.raises(RuntimeError, match="offline"):
            asyncio.run(module.bot.announce_release_once())
        assert not asyncio.run(module.bot.announce_release_once())

    channel.send.assert_awaited_once()
    assert module.bot.db.execute(
        "SELECT posted_at FROM release_announce WHERE range_end='end'"
    ).fetchone() == (None,)


@pytest.mark.parametrize("empty_kind", ["same_ref", "empty_render"])
def test_empty_ranges_record_marker_without_sending(
    empty_kind, tmp_path, monkeypatch
):
    configure_release(monkeypatch)
    monkeypatch.delenv("RELEASE_ANNOUNCE_REF")
    module = load_bot_module(tmp_path, monkeypatch)
    channel = SimpleNamespace(send=AsyncMock())
    module.bot.get_channel = lambda _channel_id: channel
    until = "start" if empty_kind == "same_ref" else "end"

    with (
        patch.object(module, "resolve_release_ref", return_value=until) as resolve,
        patch.object(module, "collect_release", return_value=object()) as collect,
        patch.object(module, "render_release", return_value=None),
    ):
        assert not asyncio.run(module.bot.announce_release_once())

    resolve.assert_called_once_with("/repo", "main")
    if empty_kind == "same_ref":
        collect.assert_not_called()
    else:
        collect.assert_called_once_with("/repo", "start", "end")
    channel.send.assert_not_awaited()
    assert module.bot.db.execute(
        "SELECT range_start, includes_v0 FROM release_announce WHERE range_end=?",
        (until,),
    ).fetchone() == ("start", 0)


def test_missing_initial_ref_logs_once_and_does_not_resolve(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.delenv("RELEASE_SINCE_REF", raising=False)
    module = load_bot_module(tmp_path, monkeypatch)

    with patch.object(module, "resolve_release_ref") as resolve:
        assert not asyncio.run(module.bot.announce_release_once())

    resolve.assert_not_called()
    assert capsys.readouterr().out.splitlines() == [
        "release announcement skipped: RELEASE_SINCE_REF is unset"
    ]
    assert list(module.bot.db.execute("SELECT * FROM release_announce")) == []


def test_composer_caps_long_release_but_keeps_footer(tmp_path, monkeypatch):
    module = load_bot_module(tmp_path, monkeypatch)

    message = module.compose_release_announcement("x" * 3000, True)

    assert len(message) == 1900
    assert "v0 is live" in message
    assert message.endswith(module.SUGGEST_FOOTER)
