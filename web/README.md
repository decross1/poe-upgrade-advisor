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
