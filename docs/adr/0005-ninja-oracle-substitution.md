# ADR-0005: poe.ninja cross-validation replaces desktop captures as the TASK-101 parity oracle

- Status: accepted
- Date: 2026-07-26
- Task: TASK-101 / issue #6
- Deciders: human operator (directive: ninja oracle, ≤1% accuracy threshold), pm

## Context

TASK-101's original oracle — five hand-made desktop PoB captures — is blocked:
the operator is not currently playing and cannot produce them. A pm feasibility
probe (workflow wf_ab619825) verified that poe.ninja's internal builds API
serves, per ladder character, a complete `pathOfBuildingExport` code decoding
to full PoB XML **including the exact enemy ConfigSet ninja used**, plus a
machine-readable stat vector (per-skill DPS family, 47 defensive stats incl.
EHP) and a published rules list (`/poe1/api/builds/pob-rules`). An adversarial
assessment enumerated the false-confidence modes and mitigations; its verdict:
this oracle is *practically stronger* than the manual one (15 machine-checked
builds vs 5 hand-transcribed; frozen raw responses vs screenshots; embedded
config vs manual config-setting), while sharing the manual oracle's one real
weakness identically (desktop PoB IS PoB Community Fork — neither oracle tests
the engine core independently).

## Decision

1. TASK-101's parity oracle becomes **ninja cross-validation**: N=15 frozen
   raw character-detail responses (≥7 archetypes, incl. mines/triggers/minions/
   CI-LL, ≥1 mapping-style and ≥1 bossing-style config), committed under
   `engine/corpus/seed/ninja/` with fetch metadata sidecars. The engine imports
   each embedded export **with its embedded ConfigSet verbatim** (product
   presets explicitly not applied) and emits the full stat JSON.
2. **Pass bar (human directive): relative |Δ| ≤ 1%** per compared stat vs
   ninja's value. Diagnostic tiers reported but not gating: exact
   (≤0.5 ULP of printed precision) and ≤0.1%.
3. Every stat cell outside 1% gets a GAPS.md entry classified as exactly one
   of: our-bug (blocks GO until fixed) / PoB-version-skew (requires
   reproduction evidence) / documented-limitation (pm sign-off required).
   The corpus manifest lists every build fetched, including ones that failed
   import — no survivor-only corpora.
4. Mitigations binding on the implementation: harness canary self-test
   (corrupted stat must fail; export/JSON identity mismatch must abort);
   production-code-path property test (equipped item re-rendered through OUR
   clipboard parser and diffed → zero delta on every compared stat);
   determinism (10 byte-identical runs, two locales) and warm p95 < 150 ms
   retained from the original ACs.
5. **Policy scope:** poe.ninja's builds API is internal/undocumented — it is a
   dev-time oracle only. Live calls happen manually/politely (descriptive UA,
   cached, a handful per corpus refresh); CI and product runtime consume only
   the frozen committed responses. Never called per-user.
6. **Desktop captures: deferred, not deleted.** The capture manifest stays
   committed with per-build PoB codes so any human (operator or a community
   volunteer via #poe) can later supply true desktop confirmation; if supplied,
   those numbers outrank ninja's on any disputed cell.

## What GO can and cannot claim under this oracle

CAN: our headless harness deterministically reproduces PoB Community Fork
calculations — the engine family the product promises and the same one
poe.ninja runs — across 15 real builds within 1%, warm p95 < 150 ms, every
divergence root-caused. CANNOT: exact parity with any specific desktop PoB
version a user runs (ninja's PoB version is unpublished), nor independent
validation of PoB's math itself (no oracle we have access to provides that).

## Consequences

- The engine spike unblocks immediately with zero human dependency.
- Reversal condition: if desktop captures later disagree with ninja beyond 1%
  on any cell, desktop wins and this ADR's oracle is demoted to secondary.
- Follow-up: TASK-103 GO/NO-GO ADR will cite the committed comparison report.
