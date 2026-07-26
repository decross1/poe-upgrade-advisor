# RFC-0001: VerdictCard semantics — codify the conventions the golden fixtures assume

- Status: draft
- Author: pm
- Task: TASK-TBD (golden UI fixtures for the verdict card; assign id at triage)

## Problem

`contracts/verdict.schema.json` and `contracts/openapi.yaml` constrain the *shape* of
a VerdictCard but leave its *semantics* unspecified. A frontend cannot be built, nor a
backend serializer verified, without answers to: delta units and sign convention; what
the required numeric deltas mean under `CANT_EVALUATE` (null is not allowed); whether
`Assumption.label` is server-templated; which field (`id` vs `source_rule`) is echoed
back as `overrides[].assumption_id`; what `value` to POST on a one-tap flip for
non-boolean assumptions; whether `impactful: false` entries may appear in
`assumptions`; and ordering/truncation when more than 6 rules fire.

The golden fixtures in `contracts/fixtures/` (see its README, "Conventions these
fixtures pin down") embody working answers so FE/BE can proceed. Those conventions are
currently documentation, not contract. This RFC proposes codifying them.

## Proposal

Fold the nine conventions from `contracts/fixtures/README.md` into
`contracts/openapi.yaml` as `description` text (no structural change, no constraint
loosening):

1. `offense_delta_pct`/`defense_delta_pct`: percent points (12.4 = +12.4%), positive =
   candidate better; both `0` as non-rendered sentinels when `verdict=CANT_EVALUATE`.
2. `cant_evaluate_reasons`: best-effort, free-form, rule-id-prefixed when applicable;
   may be absent even for CANT_EVALUATE.
3. `Assumption.label`: server-rendered final text, ≤40 chars, FE does no templating.
4. `Assumption.id`: the value echoed as `overrides[].assumption_id`; `source_rule` is
   provenance only. Flip semantics: negate booleans, replace strings.
5. `assumptions[]`: may include `impactful:false` entries; server orders
   impactful-first and truncates to `maxItems` 6.
6. `diff_id`: opaque; TTL to be defined (separate decision; today FE treats
   `/breakdown` 404 as expiry).

Open question deliberately NOT resolved here: typing `Assumption.value` (e.g.
`oneOf [boolean, string, number]`) — that is a structural schema change to a
protected file; propose only if a real assumption ever carries another type.

## Doctrine impact

None adverse. I2: no new fields, no constraint loosening — description-only.
I3: sharpens the one-tap-flip contract (id + flipped value). I5: fixtures encode the
0.55/0.75 thresholds from `assumptions/rules/confidence.yaml` without duplicating
them into the API, keeping thresholds as data.

## Contract impact

`contracts/openapi.yaml`: description-text additions on `VerdictCard.offense_delta_pct`,
`.defense_delta_pct`, `.cant_evaluate_reasons`, `Assumption.id`, `.label`, `.value`,
`.source_rule`, and the `/diff` `overrides` request property. `verdict.schema.json`:
untouched. New directory `contracts/fixtures/` (7 golden JSONs + README) validated
against `verdict.schema.json`; suggested CI hook: run the README validation command in
the contract-check job.

## Alternatives considered

- **Add a `low_confidence: boolean` field to VerdictCard** so the FE need not read
  `confidence.yaml` thresholds: rejected — widens the I2-capped card; raw
  `confidence` plus data-file thresholds suffices.
- **Make `cant_evaluate_reasons` required when verdict=CANT_EVALUATE** (`if/then` in
  verdict.schema.json): deferred — engine cannot always produce a reason (see
  `edge_degraded_minimal.json`), and touching the enforcement schema needs its own
  protected-change task.
- **Nullable deltas for CANT_EVALUATE**: rejected — loosening a required type in the
  enforcement schema is exactly the gate-weakening AGENTS.md rule 6 forbids; the 0
  sentinel + "do not render" rule is strictly simpler.

## Rollout / migration

No wire change (descriptions only), so no version bump. Sequence: accept RFC →
description-edit PR on `contracts/openapi.yaml` (protected-change label) → FE/BE cite
fixture filenames in their tests. Revisit if a non-boolean, non-string assumption
value or a structured-reasons need appears (that becomes an RFC-0001 amendment).
