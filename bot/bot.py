#!/usr/bin/env python3
"""Discord intake bot v0 (L4 product loop, front half + relay).

Security posture (ARCHITECTURE.md §Security):
- ZERO repo write access beyond creating `intake`-labeled issues.
- All user text is normalized, secret-scrubbed, and fenced as UNTRUSTED data.
- Auto-quarantine tickets that reference the pipeline itself.
- Decisions flow back: PM posts an issue comment starting with [DECISION];
  the relay task posts it into the origin Discord thread.

Env: DISCORD_TOKEN, GITHUB_TOKEN (issues:write only), GITHUB_REPO ("owner/name"),
     INTAKE_OUTBOX (path to repo .mailroom/outbox, optional — postmaster mails PM),
     SUGGEST_CHANNEL_ID (forum or text channel id), FEEDBACK_CHANNEL_ID (optional)
Run: pip install discord.py requests ; python bot.py
"""
from __future__ import annotations
import asyncio, json, os, sqlite3, uuid
import discord
from discord import app_commands
import requests

try:
    from bot.feedback import FeedbackProcessor
    from bot.intake import fenced_body, quarantine_check, scrub
except ModuleNotFoundError:  # Support `cd bot && python bot.py`.
    from feedback import FeedbackProcessor
    from intake import fenced_body, quarantine_check, scrub

GH_API = "https://api.github.com"
REPO = os.environ["GITHUB_REPO"]
GH_HEADERS = {"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
              "Accept": "application/vnd.github+json"}

db = sqlite3.connect(os.environ.get("BOT_DB", "bot_state.sqlite3"))
db.execute("CREATE TABLE IF NOT EXISTS map (issue INTEGER PRIMARY KEY, channel INTEGER,"
           " thread INTEGER, last_relayed_comment INTEGER DEFAULT 0)")
db.commit()


def file_issue(title: str, body: str, quarantined: bool) -> int:
    labels = ["intake"] + (["quarantine"] if quarantined else [])
    r = requests.post(f"{GH_API}/repos/{REPO}/issues", headers=GH_HEADERS,
                      json={"title": f"INTAKE: {scrub(title)[:80]}",
                            "body": body, "labels": labels})
    r.raise_for_status()
    return r.json()["number"]


async def file_issue_async(title: str, body: str, quarantined: bool) -> int:
    return await asyncio.to_thread(file_issue, title, body, quarantined)


def write_outbox(issue: int, title: str, thread_ref: str) -> None:
    """Optional: nudge PM by mail via the postmaster outbox (if repo-local)."""
    outbox = os.environ.get("INTAKE_OUTBOX")
    if not outbox:
        return
    payload = {
        "schema_version": "1.0", "message_id": str(uuid.uuid4()),
        "idempotency_key": f"intake:{issue}",
        "task_id": "ORG", "from_role": "intake", "to_role": "pm",
        "intent": "INTAKE_TICKET", "hop_count": 0, "max_hops": 6,
        "refs": {"issue": issue, "discord_thread": thread_ref},
        "body_markdown": f"New intake #{issue}: {scrub(title)[:100]}. Triage per pm.md.",
        "untrusted": True,
    }
    with open(os.path.join(outbox, f"intake-{issue}.json"), "w") as f:
        json.dump(payload, f, indent=2)


class Bot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = bool(os.environ.get("FEEDBACK_CHANNEL_ID"))
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        feedback_channel = os.environ.get("FEEDBACK_CHANNEL_ID")
        self.feedback = FeedbackProcessor(
            int(feedback_channel) if feedback_channel else None,
            db,
            file_issue_async,
        )

    async def on_message(self, message: discord.Message):
        await self.feedback.process(message)

    async def setup_hook(self):
        await self.tree.sync()
        self.loop.create_task(self.relay_decisions())

    async def relay_decisions(self):
        """Poll intake issues for PM [DECISION] comments and post to origin threads."""
        import asyncio
        await self.wait_until_ready()
        while not self.is_closed():
            for issue, channel_id, thread_id, last in db.execute(
                    "SELECT issue, channel, thread, last_relayed_comment FROM map"):
                try:
                    comments = requests.get(
                        f"{GH_API}/repos/{REPO}/issues/{issue}/comments",
                        headers=GH_HEADERS).json()
                    for c in comments:
                        if c["id"] > last and c["body"].startswith("[DECISION]"):
                            ch = self.get_channel(thread_id or channel_id)
                            if ch:
                                await ch.send(
                                    f"**Update on suggestion #{issue}:**\n"
                                    f"{c['body'][len('[DECISION]'):].strip()[:1800]}")
                            db.execute("UPDATE map SET last_relayed_comment=? WHERE issue=?",
                                       (c["id"], issue))
                            db.commit()
                except Exception as e:
                    print("relay error:", e)
            await asyncio.sleep(300)


bot = Bot()


@bot.tree.command(name="suggest", description="Suggest a feature or report a wrong verdict/assumption")
@app_commands.describe(title="One-line summary",
                       problem="What's wrong or missing (for wrong assumptions: paste your PoB code!)",
                       proposal="Optional: what you'd like to see")
async def suggest(interaction: discord.Interaction, title: str, problem: str,
                  proposal: str = ""):
    q = quarantine_check(title, problem, proposal)
    body = fenced_body(
        author=str(interaction.user), content=problem,
        proposal=proposal, channel=str(interaction.channel),
        jump_link=str(interaction.channel_id),
    )
    issue = await file_issue_async(title, body, q)
    thread_id = interaction.channel_id
    # In a forum/text channel, create a thread so the decision has a home
    try:
        if isinstance(interaction.channel, discord.TextChannel):
            th = await interaction.channel.create_thread(
                name=f"#{issue} {title[:60]}", type=discord.ChannelType.public_thread)
            thread_id = th.id
    except Exception:
        pass
    db.execute("INSERT OR REPLACE INTO map (issue, channel, thread) VALUES (?,?,?)",
               (issue, interaction.channel_id, thread_id))
    db.commit()
    write_outbox(issue, title, str(thread_id))
    note = " (held for review)" if q else ""
    await interaction.response.send_message(
        f"Logged as intake **#{issue}**{note}. The PM agent triages on its next "
        "heartbeat and the decision will be posted here — accepted ideas get task "
        "links so you can watch them ship.", ephemeral=False)


if __name__ == "__main__":
    bot.run(os.environ["DISCORD_TOKEN"])
