# ADR-0006: Engine spike GO ruling (TASK-103)

- Status: accepted
- Date: 2026-07-26
- Task: TASK-103 / issues #6, #8; evidence on PR #57 (branch heads 9d39506, warm-perf lane)
- Deciders: pm

## Context

Phase 1 gated everything on proving the headless PoB engine. Evidence per
ADR-0005's oracle (15 frozen poe.ninja builds, ≥7 archetypes incl. mines,
CoC trigger, minions ×2, CI/LL, DoT, totem, brand):

- **Import**: 15/15 builds import (timeless-jewel headless host gap fixed,
  vendor untouched).
- **Parity**: 1431/1435 stat cells bit-exact (99.7%) — far inside the human
  directive's ≤1% band, without needing it. The 4 non-exact cells (mana cost)
  carry exact replay evidence attributing them to an upstream PoB cost-order
  change (961363511 vs our pinned 592c2407) — classified PoB-version-skew per
  ADR-0005 §3 with reproduction; pm signs off. Zero our-bug cells.
- **Hygiene**: canary self-test proves the harness can fail; two-locale ×10
  determinism; classification gate green; engine 15/15, repo 30/30, doctrine
  and fixture checks pass.
- **Performance** (profiled, not guessed): one-time build import+first-calc
  389ms (cached rerun 0.03ms; removable duplicate adapter calc 28ms);
  steady-state same-build item diff **4.3ms p95** — the per-keypress path.

## Decision

**GO.** The vertical slice proceeds on this engine.

Perf gates re-derived to match what I6 ("verdict feels instant") actually
constrains — the Ctrl+C→card path, not one-time session setup:

1. Same-build item diff: warm p95 < 150 ms (measured 4.3 ms — 35× headroom).
2. Build import/session load: p95 < 2000 ms budget with UI affordance
   (measured ≤ ~550 ms). Not on the keypress path.
3. The low-risk duplicate-calc removal is authorized; snapshot/tree-cache
   optimization is NOT required for MVP (file as post-MVP perf task if wanted).

The 4 version-skew cells are accepted and recorded in GAPS.md; reversal
condition: if desktop captures or an oracle refresh at matched PoB versions
show the same cells diverging, they reclassify to our-bug and reopen the gate.

## Consequences

- TASK-202b (real calc adapter behind the server interface) is unblocked and
  assigned; TASK-208 completes packaging against the real engine; GATE-MVP
  becomes reachable.
- PR #57 (harness + fixes + report) proceeds through normal review to merge —
  this ADR's evidence must land on main with it.
- NO-GO paths (compiled-PoB alternatives) are closed unexamined — correctly,
  because the spike passed; revisit only if the reversal condition fires.
