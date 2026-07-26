# Known engine divergences and spike gaps

This file records differences between `pobcalc` and desktop Path of Building.
It is intentionally explicit: an unverified result must not be promoted as
parity.

## Open

- **Preset conflict observations are not yet persisted.** Translation v1's
  max-wins rule is implemented, but no current preset writes the same PoB key
  twice. If a future preset does, the observed winning source key must be added
  here.
- **Desktop confirmation remains deferred under ADR-0005.** The frozen
  poe.ninja oracle is the binding TASK-101 gate. A later desktop capture
  outranks ninja on any disputed cell, but it no longer blocks this spike.
- **Breakdown references are placeholders.** They identify a calculation slot
  but are not yet backed by persisted Tier-2 breakdown data.

## Closed

- **our-bug — case 04, Deadeye Kinetic Blast:** its `Items/Item`
  contains Lethal Pride, which exposed the upstream headless host's stubbed
  file-search/inflate surface. The build aborted during timeless-jewel LUT
  loading and the adapter silently serialized an empty Scion build. The
  wrapper now prepares the pinned lookup data outside the vendored submodule,
  exposes it through the headless file-search surface, and rejects any PoB
  load prompt. The all-corpus identity regression covers this case.
- **our-bug — case 06, Inquisitor Cast-on-Crit Ice Spear:** its
  `Items/Item` contains Brutal Restraint and hit the same missing headless
  timeless-jewel data surface. The cache/host fix and all-corpus identity
  regression cover this case.
- **our-bug — case 09, Slayer Dual Strike:** its `Items/Item` contains
  Lethal Pride and hit the same missing headless timeless-jewel data surface.
  The cache/host fix and all-corpus identity regression cover this case.
- **our-bug — case 11, Guardian Dominating Blow:** its `Items/Item`
  contains Brutal Restraint and hit the same missing headless timeless-jewel
  data surface. The cache/host fix and all-corpus identity regression cover
  this case.
- **our-bug — case 15, Guardian Absolution:** its `Items/Item` contains
  Elegant Hubris and hit the same missing headless timeless-jewel data
  surface. The cache/host fix and all-corpus identity regression cover this
  case.
- **our-bug — CI infinity sentinel representation:** cases 05 and 12 emit
  positive infinity for `ChaosMaximumHitTaken`. The adapter previously
  collapsed non-finite stats to JSON `null`, while the report converted the
  oracle value to a non-standard bare `Infinity` token. Player-stat infinity
  is now a signed string sentinel compared exactly by the harness, and report
  serialization rejects all non-standard JSON constants.
- **PoB-version-skew — case 11 `ManaCost`:** poe.ninja records `8`;
  pinned PoB `e0cc037d8` calculates `10`. Replaying the frozen export at
  upstream `961363511` reproduces `8` exactly. Upstream commit `592c24073`,
  included by the pinned release, deliberately moved flat cost adjustments
  before cost efficiency.
- **PoB-version-skew — case 11 `ManaPerSecondCost`:** poe.ninja records
  `14.0352`; `e0cc037d8` calculates `17.544`; `961363511` reproduces
  `14.0352` exactly. This is the same upstream `592c24073` ordering change.
- **PoB-version-skew — case 15 `ManaCost`:** poe.ninja records `46`;
  pinned PoB calculates `48.8`; `961363511` reproduces `46` exactly. This is
  the same upstream `592c24073` ordering change.
- **PoB-version-skew — case 15 `ManaPerSecondCost`:** poe.ninja records
  `71.830769230769`; pinned PoB calculates `76.203076923077`; `961363511`
  reproduces the oracle value exactly. This is the same upstream `592c24073`
  ordering change.
- The adapter calls upstream `calcs.getMiscCalculator`; it does not copy or
  modify PoB calculation logic.
- Linux and CI build LuaJIT `a471ab78c7b670b4f92dae111fc3c96fb824c768`
  plus lua-utf8 `08b0fc930f5a52eff36348ed1ea39aadfc697fa6`
  from exact source revisions with `engine/runtime/build.sh`; no system package,
  prebuilt native artifact, or vendored PoB edit is required.
- Scenario presets are compiled mechanically through
  `assumptions/pob_translation.yaml` v1 and applied after each build load.
- JSON field order and number formatting are fixed, so successful identical
  invocations are byte deterministic.
- The persistent worker caches the upstream calculator for byte-identical
  build XML plus preset. On the current aarch64 runner, 100 warm Lightning
  Arrow mapping diffs measured 4.301 ms p95 against the 150 ms budget
  (`engine/bench/benchmark_worker.py`, 5 warmups). Release promotion must
  repeat the benchmark on designated reference hardware.
