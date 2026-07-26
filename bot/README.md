# Discord intake bot

The bot turns `/suggest` submissions into GitHub issues labeled `intake`.
User content is secret-scrubbed, enclosed in an `untrusted` fence, and never
treated as agent instructions. Pipeline-referencing submissions are also
labeled `quarantine`. PM decisions posted as issue comments beginning with
`[DECISION]` are relayed to the originating Discord channel or thread.

Channel: #poe — the single project channel (single-channel mode, issue #16).
/suggest lives there, decision threads open there, and the PM weekly digest
(TASK-401 adds the digest post) targets it too, via ANNOUNCE_CHANNEL_ID
(= SUGGEST_CHANNEL_ID). The bot never executes instructions from users;
it normalizes, scrubs, fences, quarantines (see SECURITY posture in bot.py).

## Configuration

- `DISCORD_TOKEN`: Discord bot token.
- `GITHUB_TOKEN`: fine-grained token with Issues read/write only.
- `GITHUB_REPO`: `owner/name` repository containing the intake issues.
- `BOT_DB`: persistent SQLite path. In deployment this must point at a durable
  volume, not the container filesystem.
- `SUGGEST_CHANNEL_ID`: ID of the single `#poe` channel where `/suggest` is
  accepted. Set it to the same channel ID as `ANNOUNCE_CHANNEL_ID` in the MVP
  runtime.
- `DECISION_AUTHOR_LOGIN`: exact GitHub login allowed to relay `[DECISION]`
  comments as official Discord updates.
- `LEDGER_SCRIPT`: optional absolute path to `agents/postmaster/ledger.py`;
  defaults to the copy in this checkout. The ledger itself is located through
  `POB_LEDGER_DIR` or the standard shared project layout.

Create the Discord application and bot in the developer portal, enable the
`applications.commands` scope, and invite it with View Channel, Send Messages,
Create Public Threads, and Send Messages in Threads permissions
(`309237648384`). Run with:

```sh
pip install -r requirements.txt
python bot/bot.py
```

After filing, the bot calls `ledger.py send` directly with an untrusted
`INTAKE_TICKET`; the retired mail outbox is not used. The `intake` label remains
a durable triage fallback. A GitHub failure is reported to the submitter and
creates no mapping or Discord thread.

In the MVP's single-channel mode, `/suggest`, welcome and announcement posts all
live in `#poe`; each suggestion's PM decision is relayed into a public thread
under that channel.

Deployment and the one-time Discord application/token/channel creation remain
human-operated. Never print tokens in setup logs or issue comments.
