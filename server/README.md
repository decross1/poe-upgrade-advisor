# server/ — Local API service (Owner: Backend)

Implements `contracts/openapi.yaml` exactly (generated contract tests must pass).
Hosts: build state (import via PoB code/XML or account+character using PoB's own
import path; respect GGG rate limits), the Assumptions Engine evaluator
(`assumptions/` data), diff orchestration against `engine/`, sentence generation.

Sentence generation v1 is TEMPLATED from the breakdown drivers (deterministic,
corpus-testable). An optional LLM-polish pass is Phase 5 and must degrade
gracefully to templates (I5: never block a verdict on a network call).
Bind 127.0.0.1 only. Localhost is the trust boundary; no auth in v0, no remote bind ever.

## Run the local server

```bash
git submodule update --init
engine/runtime/build.sh
python3 -m server
```

The service binds the contract address, `127.0.0.1:47791/api/v0`, starts one
persistent `pobcalc serve` worker, and keeps the imported build warm between
item comparisons. `POST /api/v0/build` accepts raw PoB XML or the usual
compressed PoB code. `POST /api/v0/diff` accepts real clipboard item text.
Golden files in `contracts/fixtures/` remain serializer/response-shape oracles;
they are not served by the runtime.

`POST /api/v0/scan` evaluates up to 2,000 item texts under one preset and returns
the contract's original input indexes in ranked order. Honest verdict class
outranks the aggregate score (`UPGRADE`, `SIDEGRADE`, `DOWNGRADE`, then
`CANT_EVALUATE`); within a class, offense plus defense percentage delta sorts
descending, with original input order breaking exact ties. The CI integration
suite exercises a 500-item fixture against the real warm engine and requires
the complete request to finish in under 30 seconds. An item that PoB cannot
parse remains in the result as `CANT_EVALUATE` instead of aborting the batch.

`GET /api/v0/tree/suggestions?points=5&preset=mapping` plans up to the
requested point budget against the active build. Each returned step includes
its connected-first allocation path, marginal `/diff`-style deltas, and the
versioned engine ranking score. The planner is Tier 2+ and does not add fields
to the verdict card.
