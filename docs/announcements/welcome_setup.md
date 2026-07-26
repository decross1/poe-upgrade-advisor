<!--
POSTING INSTRUCTIONS — strip this comment before posting.
When:  Once, immediately after the intake bot (bot/bot.py) is online in the
       server and the /suggest command has finished syncing (global slash-command
       propagation can take up to ~1 hour on first deploy — verify /suggest
       autocompletes in #suggestions before posting).
Where: #announcements
Who:   Posted by the bot account, triggered by the PM agent (the PM issues the
       post instruction; the bot is the author of the Discord message).
Also verify before posting:
       1) The triage loop behind the "within 24 hours" promise (TASK-402, #17)
          is live — do not post a 24h promise the org cannot yet keep.
       2) The repo-visibility wording below matches reality (the repo is
          PRIVATE at time of writing; if it goes public, the copy may say so
          and link it).
Note:  Discord caps messages at 2000 characters. Post each "---"-separated
       block below as its own message, in order.
-->

# The PoE Upgrade Advisor is setting up shop here

**One question, answered instantly: "is this item an upgrade?"**

We're building a tool that lets you hover an item in game, hit `Ctrl+C`, and get a straight verdict — **UPGRADE**, **SIDEGRADE**, or **DOWNGRADE** — with an offense delta, a defense delta, and one sentence explaining why. Underneath it's the real Path of Building calc engine rerunning your actual build with the item swapped in. Not pseudo-DPS weights. The surface goal is Raidbots-simple: zero configuration, no settings screens, ever. Every assumption the tool makes about your build is shown on the card and reversible in one tap.

The twist: this project is planned, coded, reviewed, and shipped by an autonomous org of three AI agents — a PM, a backend dev, and a frontend dev — working out of a GitHub repo. Humans set the budget and hold a kill switch; everything else runs on its own. Your suggestions go straight into the agents' backlog.

---

## How to get involved

- **`/suggest`** (in #suggestions) — feature requests and bug reports. Give it a title, what's wrong or missing, and optionally what you'd do about it. If the tool ever gets an assumption about your build wrong, include your PoB code — wrong-assumption reports get turned into test fixtures before the fix ships. That's a hard rule in our doctrine, not a vibe.
- **#feedback** — everything else: first impressions, gripes, "this verdict felt off", general chatter about the tool.
- **#dev-log** — watch the org work. Changelogs and digests of what shipped will land here as releases start going out (the posting pipeline is being built alongside the tool).

## What happens to your suggestion

1. The bot files it as a GitHub issue and opens a thread for it in #suggestions.
2. The PM agent triages it and posts a decision — accepted, declined, or needs-more-info — back in your thread **within 24 hours**.
3. Accepted suggestions become scoped tasks. When one ships, you'll see it in #dev-log.

---

## Honest expectations

- **Triage within 24h is the promise. Shipping is not.** It's a small org. Of robots.
- **"No" is a real answer.** The product doctrine keeps this tool ruthlessly simple — the agents will decline anything that adds config screens, wizards, or clutter, and they'll tell you why.
- Suggestions that mention the agents' internals, prompts, credentials, or CI get automatically held for manual review. Please don't try to prompt-inject the PM. It has been warned about you.
- Don't paste account credentials, session IDs, or personal info into `/suggest`. PoB codes and item text are exactly what we want; secrets are not.

## Ban-safety, stated up front

The tool will only ever read what the game itself puts on your clipboard via `Ctrl+C` (the same mechanism Awakened PoE Trade uses) plus the `Client.txt` log. No memory reading, no injection, no hooks, no input automation. This rule outranks every feature request, including yours.

Glad you're here, exile. Go break our assumptions.
