# Discord intake bot

The bot turns `/suggest` submissions into GitHub issues labeled `intake`.
User content is secret-scrubbed, enclosed in an `untrusted` fence, and never
treated as agent instructions. Pipeline-referencing submissions are also
labeled `quarantine`. PM decisions posted as issue comments beginning with
`[DECISION]` are relayed to the originating Discord channel or thread.

Channel: #poe — the single project channel (single-channel mode, issue #16).
/suggest lives there, decision threads open there, and the weekly digest
targets it too, via ANNOUNCE_CHANNEL_ID
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
- `ANNOUNCE_CHANNEL_ID`: ID where release announcements and the Sunday 18:00
  UTC digest are posted. Release announcements are at most 1900 characters.
- `RELEASE_SINCE_REF`: required starting git ref when no release range has yet
  been recorded. Operators must set it in the bot runtime. If it is unset, each
  cycle logs a skip and never announces the repository's whole history.
- `RELEASE_ANNOUNCE_REF`: git ref to announce through; defaults to `main` and is
  resolved to an immutable commit SHA before the range is reserved.
- `RELEASE_ANNOUNCE_POLL_SECONDS`: release-check interval; defaults to 300
  seconds and values below 60 are raised to 60.
- `RELEASE_REPO_PATH`: optional path to the git checkout used for release-note
  collection; defaults to the repository containing `bot/bot.py`.
- The weekly digest collects the prior seven days of shipped work and decisions
  using `git` and `gh`, then records a durable ISO-week marker in `BOT_DB`.
  Empty weeks post nothing.
- `GITHUB_REPO` and the runtime's authenticated `gh` CLI must allow read access
  to pull requests, issues, and comments for digest collection.
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

Release ranges are recorded in the `release_announce` table in `BOT_DB`, keyed
by their resolved end SHA. The bot polls periodically and reserves a range only
after GitHub reports at least one check for that SHA and every check is
completed with a successful, neutral, or skipped conclusion. Missing GitHub
configuration, no checks, pending or failed checks, API errors, and malformed
responses all fail closed: the cycle posts and reserves nothing, so a later
green tip still includes the unannounced range. A row is reserved before
Discord is called and is marked posted only after the send returns. This chooses
at-most-once delivery: after an ambiguous send failure the range is not retried,
because a missed announcement is less disruptive than making players read a
duplicate. Keep `BOT_DB` on durable storage or that guarantee cannot survive a
restart.

The first non-empty release announcement after the overlay shipped carries a
one-shot player headline that corrects the earlier release note and explains
how to start and control the bundled overlay. Its reservation is stored in the
`release_announce.includes_overlay` column alongside `includes_v0`; startup
idempotently adds that column to existing `BOT_DB` databases so prior rows are
preserved. Empty ranges do not consume the headline.

A non-bot message in the announcement channel gets a short nudge to use
`/suggest`, the only intake path. The bot never reads message content and runs
with default Discord intents; the privileged Message Content intent is neither
needed nor enabled. Nudges are limited to once per user per six hours in a
bounded 1,024-user in-memory record. A restart clears that record, so it may
produce at most one early re-nudge per user.

Deployment and the one-time Discord application/token/channel creation remain
human-operated. Never print tokens in setup logs or issue comments.
