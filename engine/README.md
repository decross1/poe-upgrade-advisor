# engine/ — Headless PoB wrapper (Owner: Backend)

Vendors Path of Building unmodified as a submodule and exposes its calc engine
as a deterministic CLI/JSON-RPC service. **This is the Phase 1 go/no-go spike.**

## Setup
```
git submodule add https://github.com/PathOfBuildingCommunity/PathOfBuilding vendor/PathOfBuilding
```
PoB ships a headless entry point (`HeadlessWrapper.lua` in the repo root) used by
community sites for server-side calcs. Run it under LuaJIT. Never patch vendored
code (see backend.md); wrap gaps and document them in `GAPS.md`.

## TASK-101 spike contract (go/no-go)
```
pobcalc diff --build build.xml --item item.txt --preset bossing --json
```
→ stdout JSON: `{ baseline: {total_dps, ehp, ...}, candidate: {...}, deltas: {...},
   slot: "...", breakdown_ref: "..." }`
Acceptance: matches desktop PoB numbers exactly for 5 hand-verified build+item
pairs committed to `corpus/seed/`; warm-run < 150 ms; deterministic across runs.

## corpus/ — the differential oracle
~100 builds × swaps, including adversarial ones (mines, triggers, minion hybrids,
CI/LL, totems). `run_corpus.sh` executes all and diffs against recorded desktop-PoB
outputs. Corpus files are a protected path: adding entries is normal work; editing
recorded expected outputs requires a `protected-change` task (prevents "fix the
test by changing the answer").
