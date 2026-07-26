# SPEC — Verdict Card & Assumptions Chip (Overlay MVP, Tier 1)

Status: **NORMATIVE** for TASK-203 (overlay MVP) and TASK-204 (assumptions chip).
Owner: PM. Implementer: Frontend. Server counterpart: TASK-202 implements the same rulings.

This spec is written to be implemented **without asking questions**. Where the
contracts are silent, this document makes the ruling and cites it as
`[RULING-n]`. Rulings are binding on both frontend and backend until superseded
by an RFC. If observed server behavior ever contradicts a ruling, file an issue
referencing this spec — do not silently adapt the UI.

Contract sources (read-only for FE; the stricter always wins):

- `contracts/verdict.schema.json` — Doctrine I2 enforcement schema (strict: `additionalProperties: false`).
- `contracts/openapi.yaml` — `POST /api/v0/diff` request/response, `Assumption` shape (lines 139–148), `VerdictCard` (lines 149–167).
- `PRODUCT_DOCTRINE.md` — invariants I1–I8, safety S1–S3.
- `assumptions/rules/confidence.yaml` — I5 thresholds as data.
- `overlay/README.md` — shell hard rules (≤50 ms render after response, no settings surface, snapshot-test all four verdict states).

Scope: the card's contents, states, and interactions. Shell concerns (global
hotkey, clipboard read, always-on-top, focus-hide, window placement) belong to
TASK-201/TASK-203 shell work and are out of scope here except where cited.

---

## 1. The card at a glance

Doctrine **I2 [CI]** caps the card at exactly five elements. Nothing else may
ever appear on the card (`contracts/verdict.schema.json` enforces the data
side; `scripts/check_invariants.py` polices the code side).

```
┌──────────────────────────────────────────────┐
│  UPGRADE                          ◦low conf  │   1. Verdict word (+ optional low-confidence modifier)
│                                              │
│  Offense  ▐█████████░░░░░░░░░  +12.4%        │   2. Delta bar: offense
│  Defense  ▐██░░░░░░░░░░░░░░░░   −1.8%        │   2. Delta bar: defense
│                                              │
│  "Adds 210 flat cold to Vortex; you lose     │   3. One sentence (≤140 chars, verbatim)
│   a suffix of spell suppression."            │
│                                              │
│  [crit recently] [enemy chilled] [flasks up] │   4. Assumptions chip (strip of ≤6 chips)
│  [skill: Vortex]                             │
│                                              │
│                            Open details  ▸   │   5. One "open details" affordance
└──────────────────────────────────────────────┘
```

Visual hierarchy, top to bottom, by decreasing weight:

| Rank | Element | Sizing guidance | Doctrine / contract citation |
|---|---|---|---|
| 1 | Verdict word | Largest text on card (~1.6× sentence size), bold, colored per §3 | I2 ("one verdict word"); `verdict` enum, `verdict.schema.json` line 11 |
| 2 | Two delta bars + numbers | Medium; numbers right-aligned, monospace/tabular figures | I2 ("two deltas"); `offense_delta_pct`/`defense_delta_pct` |
| 3 | Sentence | Body text, max 2 lines, quoted verbatim from server | I2 ("one explanation sentence, schema-capped at 140 chars"); `sentence` maxLength 140 |
| 4 | Assumptions chip strip | Small chips, ≤2 wrapped rows, all visible | I3 ("every assumption visible, one-tap reversible"); `assumptions` maxItems 6 |
| 5 | Open details | Smallest interactive element, bottom-right | I2 ("one 'open details' affordance"); I7 (Tier 1 → Tier 2 promotion path) |

Hard bans on card content (all violate I2's "Nothing else"):

- No preset name/picker on the card. `preset` is in the payload but is **not rendered** in the overlay MVP. `[RULING-1]`
- No numeric confidence display. `confidence` drives the low-confidence modifier (§4) only. `[RULING-2]`
- No `compute_ms` display (I6 telemetry only — may be logged, never rendered).
- No `diff_id` display (used only to build the details link).
- No `cant_evaluate_reasons` on the card — they live behind "open details" (§3.4). `[RULING-3]`
- No settings, preferences, close buttons, pin buttons, resize handles, titles, logos, or timestamps (I1: overlay bundle contains **no** settings surface — CI scans `overlay/src/` filenames for `settings|preferences|configpanel|optionsmenu`; do not use those substrings in any file name).

Card is fixed-width (suggested 340 px logical), height auto to content. Render
within **50 ms of receiving the response** (`overlay/README.md`), so: no
network fetches at render time, no font loading on the hot path, no animation
that delays first paint (entrance animations are out of scope, §10).

---

## 2. Data contract recap (what the card receives)

`POST /api/v0/diff` → `VerdictCard` (200). Exactly these fields — the strict
schema has `additionalProperties: false`; if the server ever sends an unknown
field, that is a server bug, not something to render:

| Field | Type | Card usage |
|---|---|---|
| `diff_id` | string | Details link target: web deep-link to Tier-2 breakdown for this diff. Never rendered. |
| `verdict` | `UPGRADE \| SIDEGRADE \| DOWNGRADE \| CANT_EVALUATE` | Verdict word (§3). Render **exactly the server's verdict** — the FE must never derive or second-guess a verdict from the deltas. `[RULING-4]` |
| `offense_delta_pct` | number | Offense bar (§5). |
| `defense_delta_pct` | number | Defense bar (§5). |
| `sentence` | string ≤140 | Rendered verbatim, plain text (never interpret as HTML/markdown). |
| `assumptions` | array ≤6 of `Assumption` | Chip strip (§6). |
| `confidence` | number 0–1 | Low-confidence modifier only (§4). |
| `preset` | enum | Not rendered (RULING-1). Echo when re-diffing (§7). |
| `cant_evaluate_reasons?` | string[] | Not rendered on card (RULING-3). |
| `compute_ms?` | integer | Telemetry only. |

`Assumption` (openapi.yaml — the strict schema leaves items unconstrained, so
openapi's shape governs): `{ id, label (≤40), value, impactful (bool),
reversible (const true), source_rule? }`.

**Delta semantics `[RULING-5]`** (contract is silent; this ruling binds TASK-202):

- Values are **percentage points, pre-multiplied**: `offense_delta_pct: 12.4` means +12.4%, NOT a 0.124 fraction.
- Positive is always better for the player. `defense_delta_pct: +3.0` = more survivable.
- Offense summarizes the main skill's full DPS under the active preset config; defense summarizes EHP. (Consistent with `Breakdown.stat` examples `total_dps`, `ehp` in openapi.yaml line 182.)

---

## 3. Verdict states

Four states, exactly matching the `verdict` enum. All four MUST have snapshot
tests (`overlay/README.md`, TASK-203 acceptance).

### 3.1 UPGRADE

- Word: `UPGRADE`. Color: success green (suggested `#4caf7d` on dark; must pass 4.5:1 contrast).
- Both bars render normally (§5). Mixed signs are normal (offense up, defense down can still be an UPGRADE — trust the server, RULING-4).

### 3.2 SIDEGRADE

- Word: `SIDEGRADE`. Color: neutral gray (`#9aa0a6`-class).
- Bars render normally; deltas are typically small or offsetting.

### 3.3 DOWNGRADE

- Word: `DOWNGRADE`. Color: danger red (`#e05c5c`-class).
- Bars render normally.

### 3.4 CANT_EVALUATE

- Word displays as **`CAN'T EVALUATE`** (with apostrophe — I2's exact wording; the enum value `CANT_EVALUATE` is wire format only). Color: warning amber (`#d9a441`-class).
- Doctrine I5: this state appears whenever aggregate confidence < 0.55 (`assumptions/rules/confidence.yaml: cant_evaluate_below`). The server decides; the FE never computes this threshold.
- **Bars are suppressed** `[RULING-6]`: the schema still requires numeric deltas (null not allowed), so the server will send numbers, but the FE renders both bar slots as an em-dash `—` with an empty track and no sign/color. Numbers in this state are not trustworthy and must not be shown.
- The sentence carries the primary human-readable reason (server's job).
- `cant_evaluate_reasons` is NOT rendered on the card (RULING-3, keeps I2). It is available in Tier 2 behind "open details".
- The **"open details" affordance is visually emphasized** in this state (I5's exact phrasing is "CAN'T EVALUATE — open details"): render the details affordance at full opacity/accent color while the rest of the card dims slightly. This is a treatment of the existing affordance, not a new element.
- Chips still render and are still tappable (§6): flipping an assumption may raise confidence and produce a real verdict on re-diff.

### State → fixture mapping

| State | Fixture (see §9) |
|---|---|
| UPGRADE | `contracts/fixtures/upgrade_mapping.json` |
| SIDEGRADE | `contracts/fixtures/sidegrade_bossing.json` |
| DOWNGRADE | `contracts/fixtures/downgrade_mapping.json` |
| CANT_EVALUATE | `contracts/fixtures/cant_evaluate_trigger_build.json` (scored path) and `contracts/fixtures/edge_degraded_minimal.json` (degraded minimal) |

---

## 4. Low-confidence modifier (I5)

When `verdict != CANT_EVALUATE` **and** `confidence < 0.75`
(`assumptions/rules/confidence.yaml: low_confidence_badge_below`), the verdict
word gets a low-confidence treatment:

- A small `◦ low confidence` tag rendered **as part of the verdict-word element** (same line, right of the word, ~55% of its size, muted color). It is a modifier of element 1, not a sixth card element — this is how the treatment stays inside I2's cap. `[RULING-7]`
- The threshold **0.75 is hardcoded as a single named constant** with a comment citing `assumptions/rules/confidence.yaml`. The API does not expose the threshold; drift risk is accepted for MVP and noted here deliberately. Exposing a `low_confidence` flag in the schema is a protected change (AGENTS.md rule 5) and is out of MVP scope. `[RULING-8]`

```ts
/** Mirror of assumptions/rules/confidence.yaml: low_confidence_badge_below.
 *  If that file changes, this constant must change with it (checked in review). */
export const LOW_CONFIDENCE_BADGE_BELOW = 0.75;
```

Below 0.55 the server already downgrades to CANT_EVALUATE, so the practical
badge range is `0.55 ≤ confidence < 0.75`.

Fixtures: `contracts/fixtures/upgrade_rich_assumptions_chip.json` (UPGRADE with
`confidence: 0.7`, in the badge zone) and
`contracts/fixtures/sidegrade_balanced_low_confidence.json` (SIDEGRADE with
`confidence: 0.62`). Snapshot-test the badge on and off.

---

## 5. The two delta bars

One row per delta, in fixed order: **Offense** first, **Defense** second.

Layout per row: `label — signed horizontal bar — numeric value`.

- **Number formatting**: explicit sign, one decimal place, `%` suffix: `+12.4%`, `−1.8%`, `0.0%`. Use U+2212 minus (or hyphen-minus consistently — pick one, snapshot it). Tabular figures so rows align.
- **Near-zero**: `|delta| < 0.05` renders as `0.0%`, unsigned, neutral gray, empty bar. `[RULING-9]`
- **Bar geometry**: single-direction fill from the left edge (no center-zero axis at this card size). Fill fraction = `clamp(|delta| / 25, 0, 1)` — i.e. full scale is 25 percentage points. `[RULING-10]`
- **Overflow**: `|delta| > 25` → bar is full plus a small `»` chevron at the bar's end; the number is always exact (e.g. `+312.0%`).
- **Color**: fill green when the delta is positive, red when negative, gray at 0.0 — **independently per bar** (offense can be green while defense is red). Positive-is-better per RULING-5, so no sign inversion anywhere.
- **Not color-only**: the sign in the number is the accessible carrier of direction; never encode direction only in color.
- CANT_EVALUATE: both rows render label + empty track + `—` (RULING-6).

Doctrine citation: I2 "two deltas (offense, defense)" — exactly two rows, never
a third (no "total"/"score" row; that would violate I2).

---

## 6. Assumptions chip (I3) — TASK-204

"The assumptions chip" (I2, singular) is implemented as **one card element: a
strip of up to 6 small chips**. All chips are always visible — no overflow
menu, no "+2 more", no collapse (I3: "No hidden assumptions"). The schema's
`maxItems: 6` with `label ≤ 40` chars bounds worst-case size. The strip wraps
to as many rows as the schema worst case requires — 2 rows is the design
target for typical cards, but **clipping or hiding a chip is never acceptable**
(I3 outranks layout aesthetics); the card grows vertically within its
max-height budget instead. `[RULING-23, resolves issue #65]`

### 6.1 Rendering

- Render the `assumptions` array **verbatim, in server order**. No client-side sorting, filtering, or truncation. `[RULING-11]`
- Chip text = `Assumption.label`, verbatim (server pre-renders any templating such as `skill: Vortex` — the FE never does `{skill}` substitution; a label containing literal `{` is a server bug, render it as-is). `[RULING-12]`
- `Assumption.value` is **never rendered** — the label already encodes the meaning ("flasks up", "enemy chilled"). `[RULING-13]`
- `impactful: true` → normal (full-opacity) chip. `impactful: false` → dimmed (~55% opacity) chip, still visible (I3 requires visibility; dimming communicates "didn't move this verdict").
- A chip whose assumption is currently overridden by the user this session (§7) renders in an "overridden" style: inverted/outlined with a small `↺` glyph, communicating "tap again to restore".

Known chip labels for fixtures/snapshots (from `assumptions/rules/*.yaml`):
`crit recently`, `enemy chilled`, `enemy shocked`, `flasks up`,
`power charges`, `skill: {skill}`, `skill: {skill} (yours)`, `trigger build`.

### 6.2 One-tap override (the I3 interaction)

Tap semantics — **boolean values only in MVP** `[RULING-14]`:

- If `typeof value === "boolean"`: the chip is **tappable**. One tap issues exactly one `POST /diff` (§7) with the flipped value (`!value`). This includes `main_skill.trigger_ambiguity` (`trigger build`, boolean `value: true` in `cant_evaluate_trigger_build.json`): flipping it to `false` asserts "not actually ambiguous — trust the detected skill", which removes the confidence penalty and may turn CANT_EVALUATE into a real verdict on re-diff (§3.4; `contracts/fixtures/README.md` convention 6 requires even de-emphasized chips to stay flippable).
- If `value` is anything else (string skill name, number, etc.): the chip is **display-only** in MVP. Render without hover/press affordance (no pointer cursor). Non-boolean overrides (e.g. changing the main skill) live in the web app's Tier-3 area per I1 ("configuration lives only in the web app's Tier-3 area") and are reachable via the card's existing "open details" affordance. **Deliberate, temporary I3 narrowing**: I3 promises every assumption is one-tap reversible; a one-tap *flip* of a string value has no defined target, so MVP restricts flips to booleans. This is recorded — not routed around silently — in `docs/rfc/RFC-0001-verdict-card-semantics.md` (flip semantics: "negate booleans, replace strings"); extending one-tap reversal to non-boolean assumptions is that RFC's follow-up, not an FE improvisation.
- `reversible` is `const true` in the contract, so it carries no information — tappability is determined by the value-type rule above, not by `reversible`. `[RULING-15]`

Safety framing: one tap = one server action = one `POST /diff`. Never batch,
never auto-retry without a user action, never poll (S2: "One server action per
explicit user keypress"). Chips are disabled while a re-diff is in flight
(§8.3) so a double-tap cannot fan out into two requests.

### 6.3 Override payload `[RULING-16]`

The `overrides[].assumption_id` echoed to the server is **`Assumption.id`**
(described in openapi.yaml as "Stable rule id from assumptions/rules"), never
`source_rule`. `source_rule` is provenance metadata only; the FE may ignore it.

---

## 7. Re-diff on chip tap

State the card keeps per verdict session (one hotkey press = one session):

```ts
interface CardSession {
  itemText: string;                 // canonicalized clipboard text of this session
  preset?: Preset;                  // echo of last response's `preset` field
  appliedOverrides: Map<string, unknown>; // assumption_id -> overridden value
}
```

On tap of chip with assumption `a`:

1. Toggle: if `a.id` is in `appliedOverrides`, **remove** it (restore inference); otherwise **add** `{ [a.id]: !a.value }`.
2. Issue exactly one request:

```json
POST /api/v0/diff
{
  "item_text": "<session itemText, unchanged>",
  "preset": "<session preset>",
  "overrides": [ { "assumption_id": "...", "value": ... } /* ALL entries of appliedOverrides */ ]
}
```

   Overrides **accumulate** within a session (flipping "enemy chilled" then
   "flasks up" sends both), because each `/diff` is stateless. `[RULING-17]`
3. On 200: replace the entire card with the new `VerdictCard` (new `diff_id`, new deltas, possibly new verdict/assumptions). No partial/optimistic updates — the tapped chip shows a pending state until the response lands (§8.3).
4. A new hotkey press (new item) starts a fresh session: `appliedOverrides` is cleared. Overrides never leak across items. `[RULING-18]`

Doctrine trace: I3 "Tapping an assumption flips it and recomputes";
`overlay/README.md` "tap assumption chip = one re-diff with override"; S2 one
action per keypress.

---

## 8. Loading, error, and no-build states

These are **overlay UI states, not VerdictCards** — I2 governs the verdict
card's contents; a state that renders because there is no card is a distinct
minimal panel. Keep them to one short line + at most one affordance each, in
the same card frame. No error state may introduce settings/config UI (I1).

### 8.1 LOADING (initial diff in flight)

- Trigger: hotkey pressed, `POST /diff` sent.
- To avoid flash: render nothing for the first **120 ms**; if still pending, show the card frame with the single line `Evaluating…` (no spinner armies, no progress bars).
- Timeout: **3000 ms** without a response → ERROR_UNAVAILABLE. `[RULING-19]` (I6 targets 300 ms p95, so 3 s means something is wrong.)

### 8.2 Error states

| State | Trigger | Card text (exact) | Affordance |
|---|---|---|---|
| ERROR_NO_BUILD | `/diff` → 404 ("No active build") | `No build imported.` | `Import a build ▸` — deep-links web app import. This is the state's one affordance. |
| ERROR_UNPARSEABLE | `/diff` → 422 ("Item text unparseable") | `Couldn't read that item — copy it in game with Ctrl+C.` | None. Card auto-dismisses on next hotkey. |
| ERROR_UNAVAILABLE | network error / timeout / 5xx | `Advisor engine isn't running.` | None. |

Error responses have **no body schema** in the contract — the FE must key off
the **HTTP status code only** and never attempt to parse or render an error
body. `[RULING-20]`

### 8.3 REDIFFING (chip tap in flight)

- The existing card stays fully rendered; the tapped chip shows an inline spinner replacing its label glyph; **all** chips are non-interactive until resolution (S2 protection).
- Success → replace card (§7.3).
- Failure (any non-200/timeout at 3000 ms) → revert the tapped chip to its previous state, undo the `appliedOverrides` mutation, and temporarily replace the sentence line with `Couldn't recompute — tap the chip to retry.` for 3 s, then restore the original sentence. Reusing the sentence slot keeps I2's element count intact. `[RULING-21]`

### 8.4 State machine

```
HIDDEN ──hotkey──▶ LOADING ──200──▶ VERDICT ◀──────────────┐
                     │404 ▶ ERROR_NO_BUILD                 │200 (replace card)
                     │422 ▶ ERROR_UNPARSEABLE              │
                     │t/o ▶ ERROR_UNAVAILABLE       REDIFFING
                                                           ▲│error: revert,
   VERDICT ──chip tap (boolean value only)─────────────────┘└─transient msg
   any state ──hotkey──▶ LOADING (new session)
   any state ──game loses focus──▶ HIDDEN   (overlay/README.md)
```

---

## 9. Fixtures — `contracts/fixtures/` (coordinated naming)

The FE builds **entirely fixture-driven** (no server exists yet; TASK-202
pending). The golden fixtures have landed in `contracts/fixtures/` (see its
README, which is authoritative for the fixture index and the semantics they pin
down; codification tracked in `docs/rfc/RFC-0001-verdict-card-semantics.md`).
NOTE: `contracts/` is a protected path (AGENTS.md rule 5) — fixture changes
land via a task carrying the `protected-change` label; the FE consumes them
read-only. Cases not yet covered by a golden fixture (marked below) may be
covered by local copies under `overlay/test/fixtures/` until a golden fixture
lands.

Every fixture MUST validate against `contracts/verdict.schema.json` **and**
openapi's `VerdictCard`/`Assumption` shapes (stricter wins). Add a fixture
validation step to the FE test suite.

| File | Purpose | Characteristics |
|---|---|---|
| `upgrade_mapping.json` | Happy path | `verdict: UPGRADE`, mixed-sign deltas (`+12.4` / `−1.8` — mixed signs are normal, RULING-4), `confidence: 0.8` (no badge), 3 assumptions incl. `config.flasks_up` and one `impactful: false`; `source_rule` both present and absent |
| `sidegrade_bossing.json` | Neutral | `verdict: SIDEGRADE`, small offsetting deltas (`+0.6` / `−0.4`), bossing preset, user-overridden main skill (`main_skill.user_override`, chip `skill: Boneshatter (yours)`), `confidence: 0.9` |
| `downgrade_mapping.json` | Negative | `verdict: DOWNGRADE`, negative offense with positive defense (`−18.2` / `+3.1`) — the card must not spin a tradeoff into an upgrade |
| `cant_evaluate_trigger_build.json` | I5 path | `verdict: CANT_EVALUATE`, `confidence: 0.5` (< 0.55), `cant_evaluate_reasons` present, assumptions incl. `main_skill.trigger_ambiguity` chip (`trigger build`, boolean → tappable per §6.2) and best-guess skill chip (string → display-only) |
| `upgrade_rich_assumptions_chip.json` | §4 badge + layout stress | `verdict: UPGRADE`, `confidence: 0.7` (in `[0.55, 0.75)`), **exactly 6 assumptions = schema `maxItems`**, incl. `impactful: false` entries the chip de-emphasizes |
| `sidegrade_balanced_low_confidence.json` | Enum coverage + §4 badge | `verdict: SIDEGRADE`, `preset: "balanced"` (valid per the API enum even though no preset file exists — the FE must tolerate all three enum values), `confidence: 0.62` (badge zone) |
| `edge_degraded_minimal.json` | Degradation edge | `verdict: CANT_EVALUATE`, required fields only: empty `assumptions`, NO `cant_evaluate_reasons`, no `compute_ms`, `confidence: 0`, sentinel deltas `0`, sentence at exactly 140 chars (schema max) |

Not yet covered by a golden fixture (keep local `overlay/test/fixtures/`
copies until one lands via a `protected-change` task): a delta `> 25` to
exercise bar overflow (`»`, RULING-10) and a 40-char label; a §7 re-diff
response for a flipped override (different `diff_id`/deltas for the same item).

Fixture-authoring rules: `sentence` ≤140 chars plain text; labels ≤40; `assumptions` ≤6;
`reversible: true` on every assumption. The **overlay** never sends or renders
`balanced` — it is in the API enum but has no preset file in
`assumptions/presets/`; treat it as reserved for requests. Exactly one golden
fixture (`sidegrade_balanced_low_confidence.json`) deliberately carries
`preset: "balanced"` so the FE proves it tolerates all three enum values in
*responses*; new fixtures use `mapping|bossing` only. `[RULING-22]`
Deltas must be plausible percentage points per RULING-5. Realistic scenario
content can be cribbed from `assumptions/fixtures/example_eo_chill_occultist.yaml`
(bossing, EO + chill, conf ≥0.75) and `example_shock_trigger_trickster.yaml`
(mapping, trigger ambiguity → CANT_EVALUATE path).

Error states need no JSON fixtures (RULING-20: status-code only) — the mock
layer (MSW/fake localhost server honoring `contracts/openapi.yaml`) must be
able to return bare 404/422/timeout for `/diff`.

### Snapshot test matrix (TASK-203/204 acceptance)

One snapshot per row; all must exist before the overlay PR is reviewable
(`overlay/README.md`: "Snapshot-test all four verdict states including CANT_EVALUATE"):

1. UPGRADE (`upgrade_mapping.json`)
2. SIDEGRADE (`sidegrade_bossing.json`)
3. DOWNGRADE (`downgrade_mapping.json`)
4. CAN'T EVALUATE (`cant_evaluate_trigger_build.json`) — bars suppressed, details emphasized
5. CAN'T EVALUATE, degraded minimal (`edge_degraded_minimal.json`) — empty chip strip, absent reasons, max-length sentence without overflow
6. UPGRADE + low-confidence tag + max (6) assumptions (`upgrade_rich_assumptions_chip.json`)
7. `balanced`-preset tolerance (`sidegrade_balanced_low_confidence.json`)
8. Bar overflow `»` (local fixture with a delta `> 25`; no golden fixture yet — see §9 gap note)
9. Overridden-chip style (render `sidegrade_balanced_low_confidence.json` with `appliedOverrides` containing `config.chill_from_setup`)
10. LOADING, ERROR_NO_BUILD, ERROR_UNPARSEABLE, ERROR_UNAVAILABLE (no fixture; state-driven)
11. REDIFFING (pending chip, disabled strip)

---

## 10. Explicitly OUT of MVP scope

Do not build any of these; several are doctrine-gated, not merely deferred:

| Item | Why out |
|---|---|
| Preset picker / preset display on card | I2 "nothing else"; I1 zero-config. Preset selection is web Tier-3. Overlay always uses the build default (omit `preset` on the first `/diff` of a session). |
| `balanced` preset in requests or UI | No `assumptions/presets/balanced.yaml` exists; the overlay never sends or renders it, but the FE must tolerate it in responses (RULING-22, `sidegrade_balanced_low_confidence.json`). |
| Non-boolean overrides (change main skill, numeric configs) | Undefined flip semantics; web Tier-3 concern (RULING-14). |
| Rendering `cant_evaluate_reasons`, `confidence` number, `compute_ms`, `preset`, `diff_id` | I2 bans; §1 hard-ban list. |
| Any settings/preferences surface, hotkey configuration UI | I1 [CI]; the invariant checker scans `overlay/src/` for banned filenames. |
| Tier-2 drivers view in the overlay | I7: Tier 2 is a tap away **in the web app**; promotion to the overlay requires an RFC. Overlay's details affordance only deep-links out. |
| `/scan`, stash ranking UI | Tier 3 (TASK-301+). |
| Diff history, pinning, compare-two-items | Not in doctrine's card; would need RFC. |
| Optimistic verdict updates on chip tap | §7.3 forbids; wait for server truth. |
| Entrance/exit animations, themes, localization | Perf budget (I6/50 ms render) and MVP focus; sentence/labels are English server-side today. |
| Client-side verdict/threshold logic (UPGRADE vs SIDEGRADE cutoffs) | Server-owned; FE renders verbatim (RULING-4). Only the 0.75 badge constant is mirrored client-side (RULING-8). |
| Auto re-diff on clipboard change / polling | S2 (one server action per explicit keypress); S1 (clipboard read only on hotkey). |
| Retry buttons that auto-fire requests | S2; every request needs a fresh explicit tap/keypress. |

---

## 11. Rulings index (for TASK-202 server alignment)

| ID | Ruling | Binds |
|---|---|---|
| RULING-1 | `preset` not rendered on card | FE |
| RULING-2 | `confidence` never shown numerically | FE |
| RULING-3 | `cant_evaluate_reasons` only behind details (Tier 2) | FE, web |
| RULING-4 | FE renders server verdict verbatim; no client thresholds | FE |
| RULING-5 | Deltas are pre-multiplied percentage points; positive = better; offense=main-skill DPS, defense=EHP | **BE + FE** |
| RULING-6 | CANT_EVALUATE suppresses bars (render `—`) | FE; BE should send `0` for both deltas in this state |
| RULING-7 | Low-confidence tag is a modifier of the verdict word, not a new element | FE |
| RULING-8 | 0.75 badge threshold mirrored as one named FE constant citing confidence.yaml | FE |
| RULING-9 | `\|delta\| < 0.05` renders `0.0%` neutral | FE |
| RULING-10 | Bar full-scale = 25 pp; overflow chevron | FE |
| RULING-11 | Chip strip renders array verbatim in server order | FE; **BE owns ordering** (impactful first recommended) |
| RULING-12 | Server pre-renders chip labels (no `{skill}` templating client-side); rendered label still ≤40 | **BE + FE** |
| RULING-13 | `value` never rendered | FE |
| RULING-14 | Only boolean-valued assumptions are tappable in MVP | FE |
| RULING-15 | Tappability from value type, not `reversible` | FE |
| RULING-16 | `overrides.assumption_id` = `Assumption.id` | **BE + FE** |
| RULING-17 | Overrides accumulate per session; full set sent each re-diff | **BE + FE** |
| RULING-18 | New hotkey/item clears overrides | FE |
| RULING-19 | 120 ms loading-flash guard; 3000 ms timeout | FE |
| RULING-20 | Error handling by HTTP status only; never parse error bodies | FE; BE may add bodies later via RFC |
| RULING-21 | Re-diff failure reverts chip and reuses sentence slot for transient message | FE |
| RULING-22 | Overlay never sends/renders `balanced` (reserved for requests); new fixtures use `mapping`/`bossing`, with one golden `balanced` fixture pinning FE enum tolerance | FE, fixtures |

Anything this spec does not answer is a spec bug: open an issue tagged
`spec:verdict-card` and block on PM, per AGENTS.md work protocol. Do not
invent behavior beyond these rulings, and never loosen `contracts/` to make a
ruling easier (AGENTS.md rule 6).
