"""Config-gated passive #feedback intake listener."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from collections.abc import Awaitable, Callable

try:
    from bot.intake import fenced_body, quarantine_check, scrub
except ModuleNotFoundError:  # Support `cd bot && python bot.py`.
    from intake import fenced_body, quarantine_check, scrub

MIN_FEEDBACK_LENGTH = 20
RATE_LIMIT_PER_HOUR = 3
RATE_WINDOW_SECONDS = 3600

IssueFiler = Callable[[str, str, bool], Awaitable[int]]


class FeedbackProcessor:
    def __init__(self, channel_id: int | None, connection: sqlite3.Connection,
                 file_issue: IssueFiler, *, clock: Callable[[], float] = time.time,
                 logger: logging.Logger | None = None):
        self.channel_id = channel_id
        self.db = connection
        self.file_issue = file_issue
        self.clock = clock
        self.log = logger or logging.getLogger(__name__)
        self._lock = asyncio.Lock()
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS feedback_messages "
            "(message_id INTEGER PRIMARY KEY, author_id INTEGER, created REAL)"
        )
        self.db.commit()

    async def process(self, message: object) -> int | None:
        """File one issue for a qualifying message, otherwise return ``None``."""
        if self.channel_id is None or getattr(message.channel, "id", None) != self.channel_id:
            return None
        if getattr(message.author, "bot", False):
            return None

        content = getattr(message, "content", "").strip()
        if len(content) < MIN_FEEDBACK_LENGTH:
            return None

        message_id = int(message.id)
        author_id = int(message.author.id)
        now = self.clock()
        async with self._lock:
            if self.db.execute(
                    "SELECT 1 FROM feedback_messages WHERE message_id=?", (message_id,)
            ).fetchone():
                return None
            cutoff = now - RATE_WINDOW_SECONDS
            count = self.db.execute(
                "SELECT COUNT(*) FROM feedback_messages "
                "WHERE author_id=? AND created>=?", (author_id, cutoff)
            ).fetchone()[0]
            if count >= RATE_LIMIT_PER_HOUR:
                self.log.warning("feedback rate limit exceeded for user %s", author_id)
                return None
            self.db.execute(
                "INSERT INTO feedback_messages(message_id, author_id, created) VALUES(?,?,?)",
                (message_id, author_id, now),
            )
            self.db.commit()

        channel = str(message.channel)
        jump_link = str(message.jump_url)
        quarantined = quarantine_check(content)
        body = fenced_body(
            author=str(message.author), content=content, channel=channel,
            jump_link=jump_link,
        )
        title = f"FEEDBACK: {scrub(content, limit=72)}"
        try:
            return await self.file_issue(title, body, quarantined)
        except Exception:
            async with self._lock:
                self.db.execute(
                    "DELETE FROM feedback_messages WHERE message_id=?", (message_id,)
                )
                self.db.commit()
            self.log.exception("failed to file feedback message %s", message_id)
            return None
