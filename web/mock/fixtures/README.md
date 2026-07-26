# web/mock/fixtures — FE-local mock fixtures (NOT golden)

FE-local fixtures the TASK-206 mock server serves from disk (never inlined).
This directory exists because `contracts/fixtures/` is PM-owned and a
protected path (AGENTS.md rule 5; merge robot SPEC condition 5): adding a
fixture there requires a task issue carrying the `protected-change` label,
applied by the PM at triage. TASK-207 (issue #29) does not carry that label,
so the build-import fixture lives here — the same gap-fixture convention
TASK-205 used for `web/test/fixtures/`.

**Promotion path:** when the PM files a `protected-change` task for it,
`build_summary.json` moves to `contracts/fixtures/` and the mock's
`BUILD_FIXTURE_PATH` default is repointed. Until then this file is the single
source of truth for both the mock server and the web tests (they import the
file, never a copy). The same applies to `breakdown/` (TASK-301, issue #13 —
also no `protected-change` label): one Breakdown fixture per golden verdict
fixture, promoted together when a `protected-change` task exists.

| File | Served by | Shape |
|---|---|---|
| `build_summary.json` | `POST /api/v0/build` (200), `GET /api/v0/build` | `BuildSummary` from `contracts/openapi.yaml` — validated in `web/test/buildImportFixture.test.ts` and `web/mock/mock.test.mjs` |
| `breakdown/<name>.json` | `GET /api/v0/breakdown/{diff_id}` (200) | `Breakdown` from `contracts/openapi.yaml` — one per `contracts/fixtures/<name>.json`, same `diff_id`; validated in `web/test/breakdownFixture.test.ts` and `web/mock/mock.test.mjs` |
