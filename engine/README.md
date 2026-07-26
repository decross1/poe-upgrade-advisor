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

The Windows x86-64 runtime is built natively with the Visual Studio MSVC
toolchain, rather than cross-compiled. From an x64 Developer PowerShell:
```
engine/runtime/build-windows.ps1
```
This produces `engine/.runtime/bin/{luajit.exe,lua51.dll}` and
`engine/.runtime/lib/lua/5.1/lua-utf8.dll`. The `windows-runtime-build` CI job
runs the same script on `windows-latest`, smoke-tests `require("lua-utf8")`,
and publishes an artifact named
`pobcalc-runtime-windows-x64-luajit-a471ab78c7b670b4f92dae111fc3c96fb824c768-luautf8-08b0fc930f5a52eff36348ed1ea39aadfc697fa6`.
Both platform scripts fetch those same exact LuaJIT and lua-utf8 revisions,
which are also recorded in the runtime manifest.

CI also runs `engine/runtime_parity.py` against three frozen poe.ninja builds:
CI/LL support, Cast on Critical Strike, and mines. Linux and Windows execute
the same unmodified PoB adapter with their pinned native runtimes, upload the
raw stat JSON reports, and a dependent job requires the report files to be
byte-identical. The spot-check is offline and makes no live poe.ninja calls.

Never patch vendored PoB code (see backend.md); wrap gaps and document them in
`GAPS.md`.

## TASK-101 spike contract (go/no-go)
```
pobcalc diff --build build.xml --item item.txt --preset bossing --json
```
→ stdout JSON: `{ baseline: {total_dps, ehp, ...}, candidate: {...}, deltas: {...},
   slot: "...", breakdown_ref: "..." }`
ADR-0005 replaces the original five desktop captures with frozen poe.ninja
exports under `corpus/seed/ninja/`; TASK-102 expands that strict oracle from 15
to 25 active builds. Every embedded PlayerStat must be within 1% or carry an
accepted ADR-0005 classification, and output must be deterministic. ADR-0006
sets separate performance gates: same-build item diff warm p95 below 150 ms and
one-time build import p95 below 2,000 ms.

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

## Passive tree planner

The warm worker method `tree_suggestions` wraps PoB's own passive graph,
allocation, and miscellaneous-calculator surfaces. It greedily selects each
target against the tree state containing all earlier selections, then restores
the imported build before returning. Paths are reported in connected-first
allocation order and include the target node.

For `pob_translation.yaml` version 1, each candidate's marginal offense and
defense use the same `total_dps`/`ehp` percentage-delta semantics as `/diff`.
The stable ranking scalar is:

```
combined_score = (0.8 * offense_delta_pct + 0.2 * defense_delta_pct) / path_cost
```

Deltas are rounded to one decimal before scoring; the score is rounded to
three decimals. Exact ties prefer lower path cost, then lower numeric node ID.
The planner considers non-ascendancy Normal, Notable, and Keystone targets;
travel nodes of any allocatable type are included in the path cost. Masteries
are not targets because the v0 contract has no mastery-effect identifier.

ADR-0005 parity work uses the preset-free stats surface, which loads the
export's active ConfigSet verbatim and returns the recalculated PlayerStat
vector:
```
engine/pobcalc stats --build build.xml --json
python3 engine/parity_harness.py
```
The parity harness is offline: it reads only the 25 active frozen poe.ninja
responses under `corpus/seed/ninja/`, runs its corrupted-stat and identity-mismatch
canaries, checks 10 byte-identical runs in two locales, and writes
`reports/ninja-parity.json`. Signed infinity in the PlayerStat vector is
encoded as the strict-JSON string sentinel `"Infinity"` or `"-Infinity"` and
compared exactly; a missing or `null` stat is still an over-band failure.
Every over-band report cell must carry one of ADR-0005's explicit
classifications or the classification gate remains red. Its timed build
switches are checked against ADR-0006's 2,000 ms import budget; the separate
worker benchmark above gates the 150 ms same-build keypress path.

Run the strict corpus gate with:
```
engine/corpus/run_corpus.sh
```
The manifest also inventories rejected fetches so an invalid or stale oracle
cannot disappear through survivor-only selection.

## corpus/ — the differential oracle
~100 builds × swaps, including adversarial ones (mines, triggers, minion hybrids,
CI/LL, totems). `run_corpus.sh` executes all and diffs against recorded desktop-PoB
outputs. Corpus files are a protected path: adding entries is normal work; editing
recorded expected outputs requires a `protected-change` task (prevents "fix the
test by changing the answer").
