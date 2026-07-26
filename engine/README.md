# engine/ — Headless PoB wrapper (Owner: Backend)

Vendors Path of Building unmodified as a submodule and exposes its calc engine
as a deterministic CLI/JSON-RPC service. **This is the Phase 1 go/no-go spike.**

## Setup
```
git submodule update --init
engine/runtime/build.sh
```
PoB ships a headless entry point (`HeadlessWrapper.lua` in the repo root) used by
community sites for server-side calcs. `runtime/build.sh` builds the pinned
LuaJIT and lua-utf8 revisions from source into ignored `engine/.runtime/`;
`pobcalc` discovers that runtime automatically. An alternate installation can
be selected with `POBCALC_RUNTIME`, or its binary/module can be selected
individually with `POBCALC_LUA` and `POBCALC_LUA_CPATH`.

Never patch vendored PoB code (see backend.md); wrap gaps and document them in
`GAPS.md`.

## TASK-101 spike contract (go/no-go)
```
pobcalc diff --build build.xml --item item.txt --preset bossing --json
```
→ stdout JSON: `{ baseline: {total_dps, ehp, ...}, candidate: {...}, deltas: {...},
   slot: "...", breakdown_ref: "..." }`
Acceptance: matches desktop PoB numbers exactly for 5 hand-verified build+item
pairs committed to `corpus/seed/`; warm-run < 150 ms; deterministic across runs.

For warm invocations, start `pobcalc serve` once and send one JSON-RPC 2.0
request per line:
```
{"jsonrpc":"2.0","id":"1","method":"diff","params":{"build":"/abs/build.xml","item":"/abs/item.txt","preset":"bossing"}}
```
The worker emits one response per line and flushes it immediately. Keeping the
worker alive excludes PoB initialization from per-diff latency measurements.
When consecutive requests have byte-identical build XML and the same preset,
the worker reuses the prepared upstream calculator and baseline. It still
reads and compares the build bytes on every request, so changing a file in
place invalidates the cache.

Measure warm latency with a real build/item pair:
```
python3 engine/bench/benchmark_worker.py \
  --build build.xml --item item.txt --preset bossing \
  --samples 100 --warmup 5
```
The command exits nonzero when p95 is not below the 150 ms TASK-101 budget.

## corpus/ — the differential oracle
~100 builds × swaps, including adversarial ones (mines, triggers, minion hybrids,
CI/LL, totems). `run_corpus.sh` executes all and diffs against recorded desktop-PoB
outputs. Corpus files are a protected path: adding entries is normal work; editing
recorded expected outputs requires a `protected-change` task (prevents "fix the
test by changing the answer").
