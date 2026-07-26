# server/ — Local API service (Owner: Backend)

Implements `contracts/openapi.yaml` exactly (generated contract tests must pass).
Hosts: build state (import via PoB code/XML or account+character using PoB's own
import path; respect GGG rate limits), the Assumptions Engine evaluator
(`assumptions/` data), diff orchestration against `engine/`, sentence generation.

Sentence generation v1 is TEMPLATED from the breakdown drivers (deterministic,
corpus-testable). An optional LLM-polish pass is Phase 5 and must degrade
gracefully to templates (I5: never block a verdict on a network call).
Bind 127.0.0.1 only. Localhost is the trust boundary; no auth in v0, no remote bind ever.

## Run the TASK-202a skeleton

```bash
python3 -m server
```

The service binds the contract address, `127.0.0.1:47791/api/v0`. The current
calculator is deliberately a fixture-backed fake behind `Calculator`; TASK-202b
replaces it with the real PoB adapter. Import a fake build first with `POST
/api/v0/build`, then use `@fixture:<fixture-basename>` in `item_text` to select
one of the golden response oracles in `contracts/fixtures/`.
