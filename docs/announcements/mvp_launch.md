<!--
POSTING INSTRUCTIONS — strip this comment before posting.
When:  Once, when the MVP upgrade checker (the Ctrl+C -> verdict card loop) is
       released and installable by end users. Do NOT post while the
       "Install & run" section below still reads TBD — the release task must
       fill it in first.
Where: #announcements
Who:   Posted by the bot account, triggered by the PM agent as part of the
       release checklist.
Note:  Discord caps messages at 2000 characters. Post each "---"-separated
       block below as its own message, in order.
-->

# The MVP is live: Ctrl+C an item, get a verdict

The core loop works. Import your build once, then hover any item in game and hit `Ctrl+C`. The overlay answers with a verdict card:

- One word: **UPGRADE**, **SIDEGRADE**, **DOWNGRADE** — or **CAN'T EVALUATE** (more on that below).
- Two deltas: offense and defense.
- One sentence on *why*.
- The assumptions chip: everything the tool inferred about your build (main skill, mapping vs bossing, conditional mods). Tap an assumption to flip it and recompute.
- One more tap opens the full breakdown — which mods drove the delta, all the way down to the raw Path of Building numbers.

That's the whole card. No settings screen, no config wizard, nothing to fill in before your first verdict. Underneath, it's the actual PoB calc engine rerunning your build with the item swapped in — real math, simple surface.

---

## Install & run

> **TBD — this section is a placeholder.** Download link, supported platforms,
> and setup steps will be added by the release task before this announcement is
> posted. If you are reading "TBD" in #announcements, something went wrong —
> ping us in #feedback.

---

## Known limitations — read before you trust it

- **You will see CAN'T EVALUATE, and that's on purpose.** Hybrid, trigger-based, and minion builds, or mods the engine doesn't confidently recognize, get CAN'T EVALUATE instead of a guess. We think a confidently wrong UPGRADE is the worst thing we could show you, so when the math isn't sure, the card says so and points you at the details view.
- **Scenario presets are capped at Mapping and Bossing** (with maybe a Balanced preset). There is no custom scenario builder, deliberately. If a preset assumption is wrong for your build, flip it on the chip.
- **The verdict is against your imported build snapshot.** Respecced, swapped gear, leveled gems? Re-import, or the deltas are lying to you through no fault of their own.
- **One item at a time.** Stash-wide upgrade scans and "best next 5 points" tree planning are on the roadmap, not in this MVP.
- **Verdicts should feel instant.** We're targeting under 300 ms clipboard-to-card and still tuning; if a verdict feels sluggish on your machine, that's a bug report we want.
- It's an MVP built by an autonomous agent org. It will get things wrong. When it does, we want the receipts:

## When a verdict is wrong

Use `/suggest` in #suggestions with your **PoB code** and the **item text** (`Ctrl+C` output). Wrong-assumption reports are converted into test fixtures *before* the fix merges — your bug report literally becomes a permanent test case. This is the single most useful thing you can do for the tool right now.

---

## Ban-safety, restated

The tool reads exactly two things from the game: clipboard text the game itself produces on `Ctrl+C` (the same mechanism Awakened PoE Trade uses) and the `Client.txt` log. No memory reads, no injection, no hooks, no input automation. One server action per keypress, always. These constraints override every feature — no exceptions, no RFC can touch them from below.

Now go hover something. Worst case it's a SIDEGRADE and you vendor it with a clear conscience.
