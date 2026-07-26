# Runbook: Setup-Complete Checklist (pm heartbeat)

Owner: pm. This runbook defines the mechanically-checkable conditions the pm
heartbeat evaluates to declare "everything is set up" and fire the two launch
notifications. Two gates:

- **GATE-DISCORD** — the community intake loop is live end-to-end.
- **GATE-MVP** — the vertical-slice MVP (verdict card + contract mock) is on `main`.

A gate **passes** iff every one of its checks passes. Checks are read-only; the
only writes happen in the firing rules at the end, and each firing action is
latched (safe to re-evaluate on every heartbeat).

## Evaluation semantics

- Run every command with `bash`, cwd = the pm clone root:
  `~/projects/poe-discord-proj/poe-upgrade-advisor`. `gh` infers the repo
  (`decross1/poe-upgrade-advisor`) from the git remote.
- Non-zero exit, or output not matching the stated PASS criterion, means FAIL.
  A FAIL is not an error condition — it means "not set up yet"; the heartbeat
  simply re-evaluates next cycle.
- Evaluate in order: Preflight → GATE-DISCORD → GATE-MVP. If Preflight fails,
  evaluate nothing and fire nothing.
- GATE-MVP may never fire before GATE-DISCORD has fired (its announcement needs
  the working bot and channel).

### Normative conventions (defined by this runbook)

Copy these into the relevant task acceptance criteria; the checks below assume them.

| Convention | Requirement |
|---|---|
| Bot launch | The bot is started as `python3 bot/bot.py` (relative to a clone root) or by absolute path — its cmdline must contain `bot/bot.py`. |
| Env vars | `DISCORD_TOKEN`, `ANNOUNCE_CHANNEL_ID` (numeric channel id of `#poe`, the single project channel — single-channel mode per issue #16; same value as `SUGGEST_CHANNEL_ID`), optional `DISCORD_GUILD_ID`, optional `MOCK_PORT` (default `47791`, per `contracts/openapi.yaml`). |
| Doc-post marker | Every doc the bot posts to Discord ends with a final line `[doc:<basename>]`, e.g. `[doc:welcome_setup]`. This is the idempotency latch the heartbeat greps for. |
| Announce docs | Announcement sources live at `docs/announcements/welcome_setup.md` and `docs/announcements/mvp_launch.md`. Each begins with an HTML `POSTING INSTRUCTIONS` comment (stripped before posting, per the comment itself) and is posted as one Discord message per `---`-separated block, in order; every block must be ≤ 1900 chars (Discord caps a message at 2000). The `[doc:<basename>]` marker is appended to the **final** block only. |
| Snapshot naming | TASK-203 commits one snapshot artifact per verdict state under `overlay/` (or `web/`); each filename contains `snap` and the state name (case-insensitive): `UPGRADE`, `SIDEGRADE`, `DOWNGRADE`, `CANT_EVALUATE`. |
| MVP task set | `TASK-202 TASK-203 TASK-301`. PR titles contain their task id (AGENTS.md definition of done). TASK-301 (#13, web Tier-2 drivers + Tier-3 raw breakdown) is in the set because `mvp_launch.md` promises "one more tap opens the full breakdown" — the gate must not announce a feature that is not on `main`. PM updates this list here if MVP scope changes (e.g. a dedicated mock-server task). |
| Bot permissions | In `#poe` the bot needs Send Messages and Read Message History (history is required by the marker checks). |

## Preflight

**P1 — HALT is clear.** Kill switch honored: with HALT set, evaluate nothing, fire nothing.

```bash
test ! -f "${POB_LEDGER_DIR:-$HOME/projects/poe-discord-proj/mailroom}/HALT" && echo PASS
```
PASS: prints `PASS`.

**P2 — required env + GitHub auth present.**

```bash
for v in DISCORD_TOKEN ANNOUNCE_CHANNEL_ID; do [ -n "${!v}" ] || echo "MISSING $v"; done
gh auth status >/dev/null 2>&1 && echo PASS
```
PASS: no `MISSING` lines and `PASS` printed.

**P3 — remote state is fresh** (M-checks read `origin/main`).

```bash
git fetch -q origin && echo PASS
```
PASS: prints `PASS`.

## GATE-DISCORD

**D1 — bot process is running on this box.**

```bash
pgrep -af 'bot/bot\.py'
```
PASS: exit 0 and at least one line showing a live `python… bot/bot.py` process.

**D2 — bot is present in the guild.**

```bash
# strict (DISCORD_GUILD_ID set):
curl -sf -H "Authorization: Bot $DISCORD_TOKEN" https://discord.com/api/v10/users/@me/guilds \
  | jq -e --arg g "$DISCORD_GUILD_ID" 'any(.[]; .id == $g)'
# fallback (DISCORD_GUILD_ID unset): bot is in at least one guild
curl -sf -H "Authorization: Bot $DISCORD_TOKEN" https://discord.com/api/v10/users/@me/guilds \
  | jq -e 'length >= 1'
```
PASS: prints `true`, exit 0. (401/403 or `false` = FAIL: token bad or bot not invited.)

**D3 — a `/suggest` round-trip produced an intake issue.**

```bash
gh issue list --label intake --state all --json number --jq 'length'
```
PASS: prints an integer ≥ 1. (Quarantined tickets still carry the `intake` label and count — the round-trip is what is being proven.)

**D4 — the same round-trip produced a ledger `INTAKE_TICKET` addressed to pm, referencing an intake issue.**

```bash
comm -12 \
  <(python3 agents/postmaster/ledger.py inbox --role pm --all --json \
      | jq -r '.[] | select(.intent=="INTAKE_TICKET") | .refs.issue' | sort -u) \
  <(gh issue list --label intake --state all --json number --jq '.[].number' | sort -u)
```
PASS: prints at least one issue number (a ticket in the shared mailroom whose
`refs.issue` matches an intake-labeled GitHub issue). Empty output = FAIL.
Note: `inbox` exits 3 while HALT is set — correct behavior, P1 already gates this.

> Known blocker at time of writing: `bot.py` `write_outbox()` targets the
> obsolete per-clone `.mailroom/outbox` (dead path per ADR-0002), so D4 fails
> until the bot writes the ticket via `agents/postmaster/ledger.py send`
> (or an equivalent append into `$POB_LEDGER_DIR/messages/`). That fix is part
> of bot deployment (TASK-401 scope).

**D5 — welcome_setup.md has been posted to `#poe`** (via `ANNOUNCE_CHANNEL_ID`; the gate's completion latch — set by the firing rule below, checked here so the gate reads PASSED exactly once the action has happened).

```bash
curl -sf -H "Authorization: Bot $DISCORD_TOKEN" \
  "https://discord.com/api/v10/channels/$ANNOUNCE_CHANNEL_ID/messages?limit=100" \
  | jq -e 'any(.[]; .content | contains("[doc:welcome_setup]"))'
```
PASS: prints `true`, exit 0.

## GATE-MVP

**M1 — verdict card snapshot artifacts for all 4 states are on `origin/main`.**

```bash
for s in UPGRADE SIDEGRADE DOWNGRADE CANT_EVALUATE; do
  git ls-tree -r --name-only origin/main -- overlay web \
    | grep -i snap | grep -qi "$s" || echo "MISSING $s"
done
```
PASS: no output. Any `MISSING <state>` line = FAIL. (States are the
`verdict` enum in `contracts/verdict.schema.json`; filenames per the snapshot
naming convention above.)

**M2 — snapshot tests are green in CI on the `main` HEAD.**

```bash
want="success $(git rev-parse origin/main)"
got="$(gh run list --workflow ci --branch main --limit 1 --json conclusion,headSha \
       --jq '.[0].conclusion + " " + .[0].headSha')"
[ "$got" = "$want" ] && echo PASS || echo "FAIL: got '$got' want '$want'"
```
PASS: prints `PASS` — the latest `ci` run on `main` concluded `success` **and**
ran against the current `origin/main` commit (which, given M1, contains the
snapshot tests).

**M3 — the contract route answers on the contract port.** `POST /api/v0/diff`
(`contracts/openapi.yaml`) on `127.0.0.1:${MOCK_PORT:-47791}` must return a
schema-valid VerdictCard. (Served by the TASK-206 fixture mock until TASK-202
lands; by the real server after — same port and route. TASK-202's definition of
done deletes the mock, so at gate time this exercises the real server.)

```bash
curl -sf -X POST "http://127.0.0.1:${MOCK_PORT:-47791}/api/v0/diff" \
  -H 'Content-Type: application/json' \
  -d '{"item_text":"Rarity: Rare\nFixture Ring\nTwo-Stone Ring\n--------\n+50 to maximum Life"}' \
| python3 -c '
import json, sys
from jsonschema import validate
card = json.load(sys.stdin)
validate(card, json.load(open("contracts/verdict.schema.json")))
print("PASS", card["verdict"])'
```
PASS: prints `PASS <STATE>` where `<STATE>` is one of the 4 verdict states.
Connection refused, non-200, or a `jsonschema.ValidationError` traceback = FAIL.

**M4 — the MVP PR(s) are merged to `main` with none left open.**

```bash
for t in TASK-202 TASK-203 TASK-301; do   # MVP task set — see conventions table
  m=$(gh pr list --state merged --base main --search "$t in:title" --json number --jq 'length')
  o=$(gh pr list --state open --search "$t in:title" --json number --jq 'length')
  { [ "$m" -ge 1 ] && [ "$o" -eq 0 ]; } && echo "PASS $t" || echo "FAIL $t merged=$m open=$o"
done
```
PASS: one `PASS <task>` line per task in the MVP task set, no `FAIL` lines.

**M5 — mvp_launch.md has been posted to `#poe`** (via `ANNOUNCE_CHANNEL_ID`; completion latch, mirror of D5).

```bash
curl -sf -H "Authorization: Bot $DISCORD_TOKEN" \
  "https://discord.com/api/v10/channels/$ANNOUNCE_CHANNEL_ID/messages?limit=100" \
  | jq -e 'any(.[]; .content | contains("[doc:mvp_launch]"))'
```
PASS: prints `true`, exit 0.

## Firing rules (the only writes)

Notification mechanism: the ledger cannot address the human (`--to` is
pm/backend/frontend only), so "notify the human" = create a GitHub issue with
the exact title below; the human watches the repo. Issue existence doubles as
the notification latch.

### When D1–D4 PASS and D5 FAILs → fire GATE-DISCORD

1. Precondition — the doc exists, and every `---`-separated block (after
   stripping the leading POSTING INSTRUCTIONS comment) fits one message:
   ```bash
   python3 - docs/announcements/welcome_setup.md <<'PY'
   import re, sys
   raw = open(sys.argv[1]).read()
   raw = re.sub(r'\A\s*<!--.*?-->\s*', '', raw, flags=re.S)  # strip POSTING INSTRUCTIONS
   blocks = [b.strip() for b in re.split(r'\n-{3,}\n', raw) if b.strip()]
   bad = [i for i, b in enumerate(blocks, 1) if len(b) > 1900]
   sys.exit(f"FAIL: blocks over 1900 chars: {bad}" if bad else print("OK", len(blocks), "blocks"))
   PY
   ```
   If not `OK`: do not fire; file/fix the doc first (pm owns `docs/`).
2. **pm has the bot post welcome_setup.md** to `#poe` via `ANNOUNCE_CHANNEL_ID` (bot identity =
   bot token), one message per block in order, marker appended to the final block:
   ```bash
   python3 - docs/announcements/welcome_setup.md '[doc:welcome_setup]' <<'PY'
   import json, os, re, subprocess, sys
   raw = open(sys.argv[1]).read()
   raw = re.sub(r'\A\s*<!--.*?-->\s*', '', raw, flags=re.S)
   blocks = [b.strip() for b in re.split(r'\n-{3,}\n', raw) if b.strip()]
   blocks[-1] += "\n" + sys.argv[2]
   for b in blocks:
       subprocess.run(["curl", "-sf", "-X", "POST",
           f"https://discord.com/api/v10/channels/{os.environ['ANNOUNCE_CHANNEL_ID']}/messages",
           "-H", f"Authorization: Bot {os.environ['DISCORD_TOKEN']}",
           "-H", "Content-Type: application/json",
           "-d", json.dumps({"content": b})], check=True)
       print("posted block", len(b), "chars")
   PY
   ```
   Success: exit 0, one `posted block` line per block. Re-run D5 to confirm the latch.
3. **pm notifies the human** (idempotent):
   ```bash
   [ "$(gh issue list --state all --search '"[GATE] GATE-DISCORD passed" in:title' --json number --jq 'length')" -eq 0 ] \
   && gh issue create --title "[GATE] GATE-DISCORD passed — Discord intake is live" \
        --body "All GATE-DISCORD checks in docs/runbooks/setup_complete_checklist.md pass. welcome_setup.md is posted to #poe. Human: verify the post renders correctly and announce wider if desired."
   ```

After firing, GATE-DISCORD reads fully PASSED (D1–D5) on the next heartbeat and
no further action is taken.

### When GATE-DISCORD (D1–D5) and M1–M4 PASS and M5 FAILs → fire GATE-MVP

1. Preconditions: the same block-size/existence check against
   `docs/announcements/mvp_launch.md`, **plus** the doc's own placeholder guard —
   its posting instructions forbid posting while "Install & run" still reads TBD:
   ```bash
   ! grep -q 'TBD' docs/announcements/mvp_launch.md && echo OK
   ```
   If not `OK`: do not fire; the release task must fill in the install section first.
2. **pm has the bot post mvp_launch.md** — step 2 above with
   `docs/announcements/mvp_launch.md` and marker `[doc:mvp_launch]`. Re-run M5 to confirm.
3. **pm notifies the human** (idempotent): step 3 above with title
   `"[GATE] GATE-MVP passed — MVP launched"` and a body linking the merged PRs
   and the green `ci` run on `main`.

When both gates read fully PASSED, this runbook is satisfied: the heartbeat
stops evaluating it and reverts to the normal triage protocol
(`agents/roles/pm.md`).
