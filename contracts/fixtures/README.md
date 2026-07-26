# contracts/fixtures — Golden VerdictCard fixtures

Golden `/api/v0/diff` **response** JSONs. The frontend builds the Tier-1 verdict card
against these files; the backend's serializer must be able to reproduce payloads of
exactly this shape. Every fixture MUST validate against `contracts/verdict.schema.json`
(the Doctrine-I2 enforcement schema, `additionalProperties: false`) and the
`Assumption` item shape in `contracts/openapi.yaml`.

The `tree_suggestions/` subdirectory contains complete golden
`GET /api/v0/tree/suggestions?points=5` responses for the RFC-0002 mapping and
bossing corpus cases. Their `compute_ms` is normalized to `0`; every other
field byte-matches the real pinned PoB runtime and validates against the
OpenAPI `TreePlan` schema.

## Validation

Run from the repo root (CI-suitable; exits non-zero on any failure):

```bash
python3 -c "
import json, glob, sys
from jsonschema import Draft202012Validator, validate
schema = json.load(open('contracts/verdict.schema.json'))
ok = True
for f in sorted(glob.glob('contracts/fixtures/*.json')):
    try:
        validate(json.load(open(f)), schema, cls=Draft202012Validator)
        print(f, 'OK')
    except Exception as e:
        ok = False; print(f, 'FAIL:', e)
sys.exit(0 if ok else 1)
"
```

## Fixture index

| File | Verdict | Covers |
|---|---|---|
| `upgrade_mapping.json` | UPGRADE | Happy path. Mapping preset, positive offense / small negative defense delta, mixed `impactful` flags, `source_rule` present and absent. |
| `sidegrade_bossing.json` | SIDEGRADE | Bossing preset, near-zero deltas, user-overridden main skill (`main_skill.user_override`, chip `skill: Boneshatter (yours)`), high confidence (0.9, no badge). |
| `downgrade_mapping.json` | DOWNGRADE | Negative offense with positive defense delta — the card must not spin a tradeoff into an upgrade. |
| `cant_evaluate_trigger_build.json` | CANT_EVALUATE | Doctrine I5: trigger build sinks confidence to 0.5 (< `cant_evaluate_below` 0.55). Includes `cant_evaluate_reasons`, the `trigger build` penalty chip, and the best-guess skill chip. |
| `upgrade_rich_assumptions_chip.json` | UPGRADE | Rich chip: **6 assumptions = schema `maxItems`**. Confidence 0.7 → low-confidence badge zone. Includes `impactful: false` entries the chip may de-emphasize. |
| `sidegrade_balanced_low_confidence.json` | SIDEGRADE | `preset: "balanced"` — valid per the API enum even though `assumptions/presets/balanced.yaml` does not exist; FE must handle all three enum values. Confidence 0.62 (badge zone). |
| `edge_degraded_minimal.json` | CANT_EVALUATE | **Degradation edge case**: required fields only. Empty `assumptions`, NO `cant_evaluate_reasons` (optional even for CANT_EVALUATE), no `compute_ms`, confidence 0, sentinel deltas 0, sentence at exactly 140 chars (schema max). The UI must render an empty chip, tolerate absent reasons, and not overflow on a max-length sentence. |

## Conventions these fixtures pin down

The schemas leave several semantics unspecified. The fixtures embody the following
PM rulings; they are **contract semantics pending codification** — see
`docs/rfc/RFC-0001-verdict-card-semantics.md`. Backend implementations must match
them or amend the RFC first.

1. **Delta units & sign.** `offense_delta_pct` / `defense_delta_pct` are percent
   *points* already multiplied out: `12.4` means +12.4%, not 0.124. Positive =
   candidate item better than currently equipped on that axis.
2. **CANT_EVALUATE sentinel.** Both deltas are exactly `0` when
   `verdict = CANT_EVALUATE` and the UI MUST NOT render them (they are sentinels,
   not measurements).
3. **`cant_evaluate_reasons` is best-effort.** Optional even when the verdict is
   CANT_EVALUATE (see the edge fixture); strings are free-form,
   human-readable, prefixed with the offending rule id when one exists. Render
   verbatim in Tier 2; do not parse.
4. **Labels are server-rendered.** `Assumption.label` arrives fully templated
   (`skill: Vortex`, never `skill: {skill}`) and always ≤ 40 chars. The FE does no
   substitution.
5. **`id` is the override key.** `Assumption.id` is the stable rule id from
   `assumptions/rules/` and is exactly what the FE echoes back as
   `overrides[].assumption_id` on a one-tap flip, with the flipped `value`
   (booleans: negate; strings such as the skill name: the replacement value).
   `source_rule` is optional provenance only — never send it back.
6. **`impactful: false` entries may appear** in `assumptions` (the array is "what
   was inferred", the flag is "what moved this verdict"). The chip may de-emphasize
   but must still allow flipping them. Server orders entries impactful-first and
   truncates to 6.
7. **Confidence thresholds are data, not API.** The low-confidence badge boundary
   (0.75) and the CANT_EVALUATE floor (0.55) live in
   `assumptions/rules/confidence.yaml`; the card intentionally ships only the raw
   `confidence` number. Fixture confidences are consistent with those thresholds
   (never a scored verdict below 0.55, badge-zone cards between 0.55 and 0.75).
8. **`diff_id` is opaque.** Only meaningful as the `/breakdown/{diff_id}` path
   parameter; no format may be assumed. Its TTL is currently undefined — treat a
   404 from `/breakdown` as expiry, not error.
9. **Verdict display text.** The enum value `CANT_EVALUATE` renders as
   `CAN'T EVALUATE` with the "open details" affordance emphasized (Doctrine I2/I5).

## Editing rules

- This directory is `contracts/` — a protected path (AGENTS.md rule 5). Fixture
  additions/changes ride on tasks with the `protected-change` label.
- Never loosen a fixture to make an implementation pass (AGENTS.md rule 6). If a
  fixture is wrong, change it via a PM-reviewed PR referencing RFC-0001.
- These are **API-shape** fixtures. Engine rule-firing fixtures live in
  `assumptions/fixtures/` and serve Doctrine I8; do not mix the two.
