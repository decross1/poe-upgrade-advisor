# PRODUCT DOCTRINE

This file is the product's constitution. It exists so that an autonomous org without human taste-checks cannot drift into complexity. Invariants marked **[CI]** are enforced mechanically by `scripts/check_invariants.py` and the merge robot; the rest are enforced by review protocol. Changing this file is a **protected-path change** (see `agents/merge_robot/SPEC.md`) and requires an RFC + ADR.

## North star

> PoB-deep math, Raidbots-simple surface. A new player gets a correct, honest verdict on their first `Ctrl+C` with zero configuration. An expert can drill down to the full Path of Building breakdown in two taps.

## Invariants

**I1 — Zero config before first verdict. [CI]**
From "build imported" to "verdict rendered" there are no required questions, wizards, or settings. The Assumptions Engine infers everything. The overlay bundle must contain no settings/preferences surface; configuration lives only in the web app's Tier-3 area.

**I2 — Verdict card is minimal. [CI]**
The overlay card contains at most: one verdict word (`UPGRADE | SIDEGRADE | DOWNGRADE | CAN'T EVALUATE`), two deltas (offense, defense), one explanation sentence (schema-capped at 140 chars), the assumptions chip, and one "open details" affordance. Nothing else. Enforced via `contracts/verdict.schema.json` constraints.

**I3 — Every assumption is visible and one-tap reversible.**
Every inferred config value that materially affected the verdict appears on the assumptions chip. Tapping an assumption flips it and recomputes. No hidden assumptions.

**I4 — At most 3 scenario presets. [CI]**
`assumptions/presets/` may contain at most three presets (Mapping, Bossing, optionally Balanced). Presets are versioned data, not code.

**I5 — Honest under uncertainty.**
If inference confidence is low (weird hybrid/trigger/minion builds, unrecognized mods), the verdict downgrades to `CAN'T EVALUATE — open details` rather than guessing. A confidently wrong UPGRADE is the worst possible output. Confidence thresholds live in `assumptions/rules/` as data.

**I6 — Fast. [CI-target]**
p95 clipboard→verdict under 300 ms with a warm engine on reference hardware. A perf smoke test gates release promotion (not PR merge) once the engine exists.

**I7 — Progressive disclosure, three tiers.**
Tier 1 overlay card → Tier 2 tap: which mods drove the delta → Tier 3 web app: full PoB breakdown, tree planning, stash scan. Features enter at the deepest tier that serves them; promotion to a shallower tier requires an RFC.

**I8 — Every inference rule has fixtures. [CI]**
Each rule file in `assumptions/rules/` must be referenced by at least one fixture in `assumptions/fixtures/`. User bug reports about wrong assumptions are converted into fixtures *before* the fix is merged (test-first, mechanically checkable).

## Safety (game ToS) — overrides everything above

**S1.** Clipboard text and the game's `Client.txt` log are the only inputs from the game. No memory reads, no injection, no hooks, no pixel-botting.
**S2.** One server action per explicit user keypress. No game-input automation.
**S3.** Any PR introducing process-inspection, input-simulation, or network calls to GGG endpoints outside documented public APIs is auto-rejected (protected pattern list in `agents/merge_robot/SPEC.md`).

## Language for agents

When a change conflicts with an invariant, the change is wrong — not the invariant. If you believe an invariant itself is wrong, open an RFC; do not route around it.
