# RFC-0002: Tree planner endpoint — /tree/suggestions

- Status: accepted (pm-authored; contracts are pm-owned — implementation may
  begin against this; openapi.yaml lands with the implementing PR for atomicity)
- Date: 2026-07-26
- Task: TASK-303 (issue #15)

## Motivation

"Best next N points" per the product paragraph. The engine rates allocatable
passive nodes by marginal power for the active build; the web UI renders the
top suggestions. No new session concepts: operates on the active build like
/diff does.

## Endpoint

`GET /api/v0/tree/suggestions?points={1..10}&preset={mapping|bossing|balanced}`

- `points` (default 5): how many sequential allocations to plan.
- `preset` (default per active session, same semantics as /diff): scenario
  under which power is scored. Same preset rules as ADR-0005/pob_translation —
  the evaluator supplies the ConfigSet; the endpoint never takes raw config.

### Response 200 (application/json)

```json
{
  "plan_id": "opaque-string",
  "preset": "mapping",
  "suggestions": [
    {
      "step": 1,
      "node_id": 26725,
      "node_name": "string",
      "offense_delta_pct": 1.8,
      "defense_delta_pct": 0.0,
      "combined_score": 1.44,
      "path_cost": 1,
      "path_node_ids": [26725]
    }
  ],
  "compute_ms": 1234
}
```

- `suggestions` ordered by allocation sequence (step 1..N), **greedy
  sequential**: each step scored against the tree state including all prior
  steps' allocations. Not N independent rankings.
- `combined_score` = the deterministic scalar used for ranking; formula is
  engine-owned but MUST be documented in engine docs and stable within a
  translation_version. Deltas use the exact /diff semantics (percentage
  points, positive = better).
- `path_cost`/`path_node_ids`: unallocated travel nodes required, included in
  the step's point spending; a step whose path_cost would exceed remaining
  points is not suggested.

### Errors

- 404 no active build (same body as /diff's 404).
- 422 invalid `points` (outside 1..10).
- Determinism: identical build+preset+points ⇒ byte-identical response
  (excluding `compute_ms`).

## Constraints

- Perf budget: p95 < 30 s for points=5 on reference corpus builds (it's a
  planner, not a keypress path; UI shows progress). Record actuals in the PR.
- I2 discipline: the card surface is unaffected; this feeds the web Tier-2+
  planner view only.
- Fixtures: ≥2 golden response fixtures (one mapping, one bossing) validating
  against the schema added to openapi.yaml in the implementing PR.

## Sequencing

BE half (engine rating + endpoint) first per TASK-303; FE "best next 5
points" view is a follow-on issue filed at BE completion. Contract changes
beyond this RFC (field additions, new params) require a new RFC.
