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
ADR-0005 replaces the original five desktop captures with the 15 frozen
poe.ninja exports under `corpus/seed/ninja/`. Every embedded PlayerStat must be
within 1% or carry an accepted ADR-0005 classification, and output must be
deterministic. ADR-0006 sets separate performance gates: same-build item diff
warm p95 below 150 ms and one-time build import p95 below 2,000 ms.

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

ADR-0005 parity work uses the preset-free stats surface, which loads the
export's active ConfigSet verbatim and returns the recalculated PlayerStat
vector:
```
engine/pobcalc stats --build build.xml --json
python3 engine/parity_harness.py
```
The parity harness is offline: it reads only the 15 frozen poe.ninja responses
under `corpus/seed/ninja/`, runs its corrupted-stat and identity-mismatch
canaries, checks 10 byte-identical runs in two locales, and writes
`reports/ninja-parity.json`. Signed infinity in the PlayerStat vector is
encoded as the strict-JSON string sentinel `"Infinity"` or `"-Infinity"` and
compared exactly; a missing or `null` stat is still an over-band failure.
Every over-band report cell must carry one of ADR-0005's explicit
classifications or the classification gate remains red. Its timed build
switches are checked against ADR-0006's 2,000 ms import budget; the separate
worker benchmark above gates the 150 ms same-build keypress path.

## corpus/ — the differential oracle
~100 builds × swaps, including adversarial ones (mines, triggers, minion hybrids,
CI/LL, totems). `run_corpus.sh` executes all and diffs against recorded desktop-PoB
outputs. Corpus files are a protected path: adding entries is normal work; editing
recorded expected outputs requires a `protected-change` task (prevents "fix the
test by changing the answer").
