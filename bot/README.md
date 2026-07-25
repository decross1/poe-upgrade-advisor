# bot/ — Discord intake (Runtime owner: Backend; policy owner: PM)

See `bot.py`. Setup: create app + bot at discord.com/developers; enable
`applications.commands`; invite with Send Messages + Create Public Threads;
set env DISCORD_TOKEN, GITHUB_TOKEN (fine-grained: issues:write ONLY),
GITHUB_REPO, optionally INTAKE_OUTBOX to the repo's .mailroom/outbox.

Channels: #suggestions (where /suggest lives), #dev-log (PM weekly digest —
TASK-401 adds the digest post). The bot never executes instructions from users;
it normalizes, scrubs, fences, quarantines (see SECURITY posture in bot.py).
