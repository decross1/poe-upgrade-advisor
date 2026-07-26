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
