<!--
POSTING INSTRUCTIONS — strip this comment before posting.
When:  Once, when the MVP upgrade checker (the local web page: paste build,
       pick an item -> verdict card) is released and installable by end users.
       Released as v0.1.0, 2026-07-26 — this condition is satisfied.
Where: #poe — the single project channel (single-channel mode, issue #16);
       post via ANNOUNCE_CHANNEL_ID, which holds the #poe channel id.
Who:   Posted by the bot account, triggered by the PM agent as part of the
       release checklist.
Note:  Discord caps messages at 2000 characters. Post each "---"-separated
       block below as its own message, in order.

Record (PM, 2026-07-26): both release decisions ruled by the operator —
       (a) distribution: public repo, GitHub Release v0.1.0, asset link wired
       below; (b) platform: WINDOWS-ONLY, ruled on #75 (2026-07-26). macOS
       support is dropped entirely (no run.command, no macOS copy anywhere);
       Linux is dev/CI-only, stated below as a dev note.
-->

# The MVP is live: paste an item, get a verdict

The core loop works. Run the tool, and your browser opens a page on your own machine. Import your build once by pasting your Path of Building code, pick an item on the page, and you get a verdict card:

- One word: **UPGRADE**, **SIDEGRADE**, **DOWNGRADE** — or **CAN'T EVALUATE** (more on that below).
- Two deltas: offense and defense.
- One sentence on *why*.
- The assumptions chip: everything the tool inferred about your build (main skill, mapping vs bossing, conditional mods). Tap an assumption to flip it and recompute.
- One more tap opens the full breakdown — which mods drove the delta, all the way down to the raw Path of Building numbers.

That's the whole card. No settings screen, no config wizard, nothing to fill in before your first verdict. Underneath, it's the actual PoB calc engine rerunning your build with the item swapped in — real math, simple surface.

Coming next: the in-game overlay — hover an item, hit `Ctrl+C`, and the card appears without leaving the game. v0 is the browser page; the overlay rides on the same engine.

---

## Install & run (Windows)

1. **Download** the latest Windows build (`.zip`) from the releases page:
   <https://github.com/decross1/poe-upgrade-advisor/releases>
2. **Extract it anywhere** (right-click → Extract All…), then open the
   extracted folder.
3. **Run it:** double-click `run.bat`.
4. Your browser opens `http://127.0.0.1:47791/` — that page **is** the whole
   app. Paste your Path of Building code into the import box, pick an item,
   read the verdict. Tap any assumption chip to flip it and recompute.
5. Stop it with `Ctrl+C` in the terminal window.

**First launch is the slow one** (tens of seconds): the engine unpacks its
one-time data cache. Every launch after that is a few seconds.

---

**You need:**
- **Windows 10/11 x86-64** — the bundled calc engine's runtime is compiled
  for it. On any other platform the launcher stops with an honest "engine
  cannot start on this machine" message instead of guessing (that's
  deliberate: a wrong verdict is worse than none).
- **Python 3.10+** — the python.org installer's `py` launcher is what
  `run.bat` looks for first.
- **~400 MB free disk** (download, ~320 MB extracted + first-run engine
  cache).
- **Internet once**, first run only, IF your Python doesn't already have
  `pyyaml` — one small dependency fetched into a private folder (`.venv/`),
  nothing installed system-wide. No npm, no compiler, no dev tools.

Everything runs on `127.0.0.1`; nothing leaves your machine.

*Dev note: Linux x86-64 builds (`run.sh`) exist for development and CI only
and are not a supported player platform.*

---

## Known limitations — read before you trust it

- **You will see CAN'T EVALUATE, and that's on purpose.** Hybrid, trigger-based, and minion builds, or mods the engine doesn't confidently recognize, get CAN'T EVALUATE instead of a guess. We think a confidently wrong UPGRADE is the worst thing we could show you, so when the math isn't sure, the card says so and points you at the details view.
- **Scenario presets are capped at Mapping and Bossing** (with maybe a Balanced preset). There is no custom scenario builder, deliberately. If a preset assumption is wrong for your build, flip it on the chip.
- **The verdict is against your imported build snapshot.** Respecced, swapped gear, leveled gems? Re-import, or the deltas are lying to you through no fault of their own.
- **One item at a time.** Stash-wide upgrade scans and "best next 5 points" tree planning are on the roadmap, not in this MVP.
- **Verdicts should feel instant.** We're targeting under 300 ms paste-to-card and still tuning; if a verdict feels sluggish on your machine, that's a bug report we want.
- It's an MVP built by an autonomous agent org. It will get things wrong. When it does, we want the receipts:

## When a verdict is wrong

Use `/suggest` right here in #poe with your **PoB code** and the **item text** (`Ctrl+C` output). Wrong-assumption reports are converted into test fixtures *before* the fix merges — your bug report literally becomes a permanent test case. This is the single most useful thing you can do for the tool right now.

---

## Ban-safety, restated

The tool reads exactly two kinds of game data: the text the game itself puts on your clipboard when you press `Ctrl+C` (in v0, you paste that text into the page yourself — the tool never touches the game) and the `Client.txt` log. No memory reads, no injection, no hooks, no input automation. One server action per keypress, always. These constraints override every feature — no exceptions, no RFC can touch them from below.

Now go paste something. Worst case it's a SIDEGRADE and you vendor it with a clear conscience.
