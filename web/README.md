# web/ — Tier-2/3 profile UI (Owner: Frontend)

React + generated API client from `contracts/openapi.yaml` (never hand-rolled).
Tier 2: delta drivers view (Breakdown.drivers). Tier 3: full PoB breakdown,
stash scan (POST /scan) ranked results, tree planner ("best next 5 points" —
engine exposes PoB's node power ratings), and the ONLY place user configuration
may live. Overrides set here become sticky build state server-side.

## Toolchain (TASK-205)

Vite 5 + React 18 + TypeScript (strict), Vitest 2 + jsdom + @testing-library for
tests (DOM snapshots via vitest's built-in serializer), Ajv (2020-12) to validate
fixtures against `contracts/verdict.schema.json` and openapi's VerdictCard/Assumption
shapes in tests. Types are generated from `contracts/openapi.yaml` with
openapi-typescript (`npm run gen:types`) — never hand-rolled. Chosen for: zero-config
ESM, fast jsdom snapshots, and a component tree that ports unchanged into whichever
shell TASK-201 picks. `npm install && npm test` runs the suite with no server;
`npm run dev` starts a fixture-driven card harness; `npm run build` typechecks and bundles.

## Layout

- `src/lib/` — generated API types + pure presentation/override rules (every rule cites its spec ruling).
- `src/components/` — `VerdictCard`, `DeltaBar`, `AssumptionsChip`. Props in, payload callbacks out; no network, no engine/server imports (enforced by `test/sourceHygiene.test.ts`).
- `src/demo/` — fixture-driven harness (`npm run dev`) with a fixture picker, override-payload preview, and the details affordance's Tier-2 preview (the only place `cant_evaluate_reasons` render).
- `test/` — snapshot matrix (docs/specs/verdict_card.md §9 rows 1–9), chip interaction, fixture schema validation, format units, source hygiene (I1 banned filenames per PM-REFINEMENT on #25).
- `test/fixtures/` — FE-local fixtures ONLY for §9 gap cases (no golden fixture yet): bar overflow >25pp, near-zero, 40-char label.

## API client (generated, never hand-rolled)

`src/generated/` is produced by
[openapi-typescript-codegen](https://github.com/ferdikoomen/openapi-typescript-codegen)
from `contracts/openapi.yaml`. Regenerate after any contract change:

```bash
cd web && npm install && npm run generate:client
```

Never edit files under `src/generated/`; change the contract (PM-owned, RFC)
and regenerate. The client's default base URL is `servers[0].url` from the
spec: `http://127.0.0.1:47791/api/v0`.

## Fixture mock server (TASK-206 — temporary)

**This server is deleted when TASK-202 lands** (deletion is part of TASK-202's
definition of done). Until then it stands in for `server/` so the UI exercises
the real HTTP contract — generated client, real port, real status codes —
making TASK-202 a config swap, not an integration project.

One-command startup (no dependency on `engine/` or `server/`):

```bash
cd web && npm install && npm run mock
# mock POST /api/v0/diff on http://127.0.0.1:47791 (N fixtures loaded)
```

It implements exactly one route, `POST /api/v0/diff`, at the exact server URL
from `contracts/openapi.yaml`. Responses are VerdictCard JSON loaded from disk
at startup out of `contracts/fixtures/` — fixtures are never inlined in code,
and the mock never modifies anything under `contracts/`.

### Deterministic fixture selection (request-driven rule)

The mock scans `item_text` for a marker; first match wins:

| `item_text` contains | Response |
|---|---|
| `@error:404` | bare `404` (no active build) |
| `@error:422` | bare `422` (item text unparseable) |
| `@fixture:<name>` | `200` with `contracts/fixtures/<name>.json`, verbatim |
| (no marker) | `200` with `upgrade_mapping.json` (documented default) |

`<name>` is a fixture basename without `.json` (e.g.
`@fixture:cant_evaluate_trigger_build`). An unknown name is a `422`. Error
bodies are empty — error states are status-code only (spec RULING-20).
Requests with missing/empty/non-string `item_text`, or a malformed JSON body,
are `422`. Every verdict state is reachable: the fixture set covers UPGRADE,
SIDEGRADE, DOWNGRADE, and CANT_EVALUATE.

Two contract conveniences on `200` responses:

- `preset`: a valid request `preset` is echoed into the response, mirroring the
  stateless re-diff flow (spec §7).
- `overrides` (I3 one-tap round-trip, spec RULING-16/17): a non-empty
  `overrides: [{assumption_id, value}]` array returns a **different** response
  with a fresh `diff_id` (`<base-diff-id>#ovr-<sha256[:12]>` of the overrides,
  deterministic). Each override whose `assumption_id` matches an
  `Assumption.id` in the fixture sets that assumption's `value` in the
  response — booleans flipped by the FE come back flipped. Unknown ids are
  ignored. This proves the re-diff shape end to end; it does not re-run
  inference (that is TASK-202's engine).

### Tests

```bash
cd web && npm test
```

Starts the mock on the real contract port and asserts over HTTP: every fixture
served from disk validates against `contracts/verdict.schema.json`
(draft 2020-12), all four verdict states are reachable, 404/422 paths behave,
the overrides round-trip yields a new `diff_id` with applied values, and the
generated client round-trips (including `ApiError` on 404/422) into a
renderable card. `mock/renderSmoke.mjs` is a wire-smoke renderer only — the
product verdict card is TASK-205's.
