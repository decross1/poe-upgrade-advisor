# BACKLOG (seed)

PM: on bootstrap, convert each task below into a GitHub issue using the Task
template, refine acceptance criteria, set TTLs, and assign. Sizes: S/M only.
Sequence gates are strict: Phase 1 is go/no-go for everything downstream.

## Phase 0 — Org online
- **TASK-001 (pm, S)** File all backlog tasks as issues; verify labels exist
  (`task, intake, quarantine, protected-change, test-change-authorized, needs-redesign, ready-to-merge, upstream-sync`).
- **TASK-002 (backend, S)** CI hardening: make ruff hard-fail; add `tests/` with a
  smoke test; commit initial `agents/merge_robot/coverage_floor.json` (`{"floor": 0.0}`).
- **TASK-003 (frontend, S)** Prove the loop: trivial PR (repo badge in README)
  through full L1 review (evidence!) + robot merge. Acceptance: robot comment
  "MERGED by robot" exists.
- **TASK-004 (pm, S)** Round-trip comms test: TASK_ASSIGN → STATUS → REVIEW_REQUEST
  → REVIEW_VERDICT via mailboxes; confirm ledger entries + idempotent redelivery.

## Phase 1 — Engine spike (GO/NO-GO)
- **TASK-101 (backend, M)** `pobcalc diff` per `engine/README.md`. Acceptance:
  5 seed pairs match desktop PoB exactly; warm < 150 ms; deterministic; `GAPS.md` started.
- **TASK-102 (backend, M)** Corpus v1: 25 builds incl. ≥5 adversarial archetypes;
  `run_corpus.sh` in CI; replace placeholder fixture build with a real one.
- **TASK-103 (pm, S)** GO/NO-GO ADR on spike results. NO-GO path: evaluate
  compiled-PoB alternatives, re-plan.

## Phase 2 — Vertical slice
- **TASK-201 (frontend, S)** ADR: Tauri vs Electron, with I6 benchmark data.
- **TASK-202 (backend, M)** `server/` implementing /build, /diff per contract;
  Assumptions evaluator over `assumptions/` data; templated sentences; contract tests green.
- **TASK-203 (frontend, M)** Overlay MVP: hotkey→clipboard→/diff→card, all 4 verdict
  states snapshot-tested; strengthen the I1 checker with real component paths.
- **TASK-204 (frontend, S)** Assumptions chip with one-tap override (I3) — P0 quality bar.

## Phase 3 — Tier 2/3
- **TASK-301 (frontend, M)** web/: Tier-2 drivers view + Tier-3 raw breakdown.
- **TASK-302 (backend, M)** /scan with ranked results; perf: 500 items < 30 s.
- **TASK-303 (backend+frontend, M each, sequenced)** Tree planner: engine exposes
  node power ratings; web renders "best next 5 points".

## Phase 4 — Community loop
- **TASK-401 (backend, S)** Deploy bot; PM digest post to #poe weekly (single-channel mode, issue #16).
- **TASK-402 (pm, S)** Triage SLA live: intake→[DECISION] within 24h verified end-to-end.
- **TASK-403 (backend, S)** Wrong-assumption intake auto-scaffolds a fixture file
  in the filed task (I8 pipeline complete).

## Phase 5 — Release + polish
- **TASK-501 (backend, M)** Release loop: dev/beta/stable channels, crash telemetry,
  soak-gated auto-promote, auto-rollback. Signing key CI-only (protected-change).
- **TASK-502 (backend, S)** Optional LLM sentence polish, template fallback (I5).
- **TASK-503 (pm, S)** First L5 retro; mutation-testing job added to weekly CI.

## Ignition (human sends once to pm@)
```json
{
  "schema_version": "1.0",
  "message_id": "00000000-0000-4000-8000-000000000001",
  "idempotency_key": "bootstrap:1",
  "task_id": "ORG",
  "from_role": "human",
  "to_role": "pm",
  "intent": "BOOTSTRAP",
  "hop_count": 0,
  "max_hops": 6,
  "refs": {},
  "body_markdown": "Org is live. Execute TASK-001 from tasks/BACKLOG.md: file the backlog as issues, then assign Phase 0 tasks via TASK_ASSIGN messages. Doctrine governs; ship the vertical slice."
}
```

## Mission resume — 2026-08-03 (issue #97, operator directive)

Sequenced by pm from ledger message f3239313; re-sequenced by pm from
orchestrator ruling 003c6e0b. The canary (TASK-999) is GREEN and CLOSED —
the gate is open and canary bookkeeping is over.

1. ~~TASK-999-S2~~ **SUPERSEDED** (ruling 003c6e0b): its substance landed at
   main ee1f030; issue #99 is closed. The packet stays registered as a record;
   its `issue_state: open` precondition now fails closed, so it cannot
   dispatch. The CC-1 rejection of its `-k`-deselecting required_check STANDS
   (forbidden-fix class F1): narrow a check by PATH, never by deselection.
2. ~~Merge PR #98~~ **DONE** — landed via PR #100 at d90a1cc under ADR-0003.
3. **Repacketize parked PR #87** (TASK-102, issue #7, `protected-change`) —
   PACKETS FILED: TASK-102-S2 (harness/fixtures/CI code), -S3/-S4 (frozen
   seed builds 16–24, inert), -S5 (build 25 + manifest flip activates the
   25-build gate). Ordering is binding — code first, data inert until the
   manifest flips last — so every intermediate merge stays green.
   `engine/reports/ninja-parity.json` (7,820 generated lines) exceeds every
   tier's diff budget and is OUT of all stage scopes; its refresh is
   escalated to the orchestrator on issue #7. Revisit if budget policy
   gains a generated-artifact lane.
4. ~~**Repacketize parked PR #91**~~ **DONE** (TASK-210, issue #79) — S2 landed
   at `473c167`, S3 at `8cd7d0a`, S4 at `78765c1`. Issue #79 is closed and
   STAYS closed; PRs #110 and #112 close as superseded-by-main (their heads
   are content-identical to what merged). No S2/S3/S4 review is redispatched.
   Ruling: ADR-0010 — packet preconditions gate dispatch, not review, and a
   closed parent is replaced rather than reopened.
5. **TASK-211 — finish the Windows overlay** (issue #113, successor parent to
   #79): S1 build-snapshot deep link (once, then zero interaction — I1),
   S2 `run.bat` packaging into the Windows bundle (#75), S3 capture→card p95
   measured and recorded against I6's 300 ms. Sequenced S1→S2→S3; frontend on
   kimi; $25 `cost_ceiling_usd` per stage under the $50 org-side wall.
   Packets not yet filed. TTL 2026-08-17.
6. **Fan out TASK-901..904** (packets validated, dependency-ready) — unblocked
   now that the canary gate is open.
7. **Release loop**: extend bot/ announce plumbing with release announcements;
   triage Discord feedback via INTAKE_TICKET (intake backlog: #92, #93 pending).

Constraints (binding, from #97): green tier default; frontier only via frontier
gates; concurrency per effort.env; packets+issues for all work; gates never
weakened; completion dispatcher-verified (proofs #1–#15).
