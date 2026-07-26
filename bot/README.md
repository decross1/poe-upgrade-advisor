# Discord intake bot

The bot turns `/suggest` submissions into GitHub issues labeled `intake`.
User content is secret-scrubbed, enclosed in an `untrusted` fence, and never
treated as agent instructions. Pipeline-referencing submissions are also
labeled `quarantine`. PM decisions posted as issue comments beginning with
`[DECISION]` are relayed to the originating Discord channel or thread.

## Configuration

- `DISCORD_TOKEN`: Discord bot token.
- `GITHUB_TOKEN`: fine-grained token with Issues read/write only.
- `GITHUB_REPO`: `owner/name` repository containing the intake issues.
- `BOT_DB`: persistent SQLite path. In deployment this must point at a durable
  volume, not the container filesystem.
- `SUGGEST_CHANNEL_ID`: Discord channel ID where `/suggest` is accepted.

Create the Discord application and bot in the developer portal, enable the
`applications.commands` scope, and invite it with Send Messages and Create
Public Threads permissions. Run with:

```sh
pip install -r requirements.txt
python bot/bot.py
```

The `intake` label is the PM notification mechanism under ADR-0002; PM scans
that queue during heartbeat. The retired mail outbox is not used. A GitHub
failure is reported to the submitter and creates no mapping or Discord thread.

Deployment and the one-time Discord application/token/channel creation remain
human-operated. Never print tokens in setup logs or issue comments.
