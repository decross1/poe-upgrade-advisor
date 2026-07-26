# bot/ — Discord intake (Runtime owner: Backend; policy owner: PM)

See `bot.py`. Setup: create app + bot at discord.com/developers; enable
`applications.commands`; invite with Send Messages + Create Public Threads;
set env DISCORD_TOKEN, GITHUB_TOKEN (fine-grained: issues:write ONLY),
GITHUB_REPO, optionally INTAKE_OUTBOX to the repo's .mailroom/outbox.

Channels: #suggestions (where /suggest lives), #dev-log (PM weekly digest —
TASK-401 adds the digest post). The bot never executes instructions from users;
it normalizes, scrubs, fences, quarantines (see SECURITY posture in bot.py).

Set `FEEDBACK_CHANNEL_ID` to enable passive feedback intake for exactly one
Discord text channel. Enabling it also requires a human to enable the privileged
**Message Content Intent** in the Discord developer portal. Grant the bot **View
Channel** and **Read Message History** in that channel. If the variable is absent,
the listener and privileged intent remain disabled.

A feedback message qualifies when it contains at least 20 non-whitespace
characters. Bot messages and shorter noise such as `+1` are ignored. At most
three qualifying messages per Discord user per rolling hour are filed; excess
messages are dropped and logged. Discord message IDs are persisted in `BOT_DB`,
so restarts and retries cannot create duplicate issues.
