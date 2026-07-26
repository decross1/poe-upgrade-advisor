"""Review repro for TASK-404 PR #30 — falsifiable objection (a).

bot/README.md (this branch) documents the qualification rule as:
    "A feedback message qualifies when it contains at least 20
    non-whitespace characters."
The implementation (bot/feedback.py MIN_FEEDBACK_LENGTH) counts ALL
characters after .strip(), including interior whitespace, so whitespace-
padded noise that the documented rule rejects still files an issue.
"""
import asyncio
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.feedback import FeedbackProcessor


class Filer:
    def __init__(self):
        self.calls = []

    async def __call__(self, title, body, quarantined):
        self.calls.append((title, body, quarantined))
        return len(self.calls)


def test_documented_nonwhitespace_qualification_rule():
    filer = Filer()
    target = FeedbackProcessor(99, sqlite3.connect(":memory:"), filer,
                               clock=lambda: 10_000)
    msg = SimpleNamespace(
        id=1,
        content="a a a a a a a a a a a",  # 21 chars stripped, 11 non-whitespace
        jump_url="https://discord.com/channels/1/99/1",
        author=SimpleNamespace(id=10, bot=False, __str__=lambda self: "user"),
        channel=SimpleNamespace(id=99, __str__=lambda self: "feedback"),
    )
    asyncio.run(target.process(msg))
    # Documented rule (README): 11 non-whitespace chars < 20 -> must NOT file.
    assert filer.calls == [], (
        "whitespace-padded noise filed an issue; README's documented "
        "'20 non-whitespace characters' rule is not what the code enforces"
    )
