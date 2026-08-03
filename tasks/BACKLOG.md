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
orchestrator ruling 003c6e0b; dispatch state recorded by pm from orchestrator
message 3037eb09. The canary (TASK-999) is GREEN and CLOSED — the gate is open
and canary bookkeeping is over.

**PR #102 is landed and closed.** Its substance is on main at 9f8ecd5 (all six
packets, the `tests/test_packets.py` registry entries, and this section). The
orchestrator directed "rebase onto current origin/main, then merge"; performed,
the rebase is EMPTY — `git diff origin/main..origin/role/org-repacketize-parked-prs`
shows the branch is strictly BEHIND main by L-14/L-16/L-17/L-18 and contains no
packet delta. Merging it could only have re-litigated already-merged content, so
the PR was closed with evidence rather than merged. This also retires backend's
REQUEST_CHANGES (ledger a68a52d4): its two objections were merge-gate conditions
(#4 single TASK link, #5 protected-change authorization) on a merge that no
longer needs to happen; the substance objection was explicitly none. The
mis-templated branch `role/org-repacketize-parked-prs` is dead with the PR —
`<role>` is a placeholder (AGENTS.md clarified at afad20f).

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
   **S2 DISPATCHED** to backend 2026-08-03T06:29Z (ledger 53643012, idempotency
   `mission-102-s2-20260803`, refs issue #7). S3/S4/S5 stay parked until S2
   lands — the ordering is the whole reason the stages exist.
4. **Repacketize parked PR #91** (TASK-210, issue #79 stays open; ADR-0008
   stage semantics) — PACKETS FILED: TASK-210-S2 (core watcher→pipeline→card
   + watcher tests), TASK-210-S3 (e2e golden snapshots; depends on S2).
   Frontend on kimi; the $50 org-side cash wall is split as a $25
   `cost_ceiling_usd` per stage.
   **S2 DISPATCHED** to frontend 2026-08-03T06:29Z (ledger eb219746, idempotency
   `mission-210-s2-20260803`, refs issue #79). This is the operator's stated
   priority — the in-game overlay path — and frontend's kimi lane had not been
   invoked once this cycle. S3 depends on S2 and stays parked.
5. **Fan out TASK-901..904** — **HELD, not dispatched.** Two reasons, both
   mechanical, neither a re-litigation of the fan-out decision:
   (a) *Capacity.* Both executor lanes are occupied by the stages above, and
   TASK-901-S1 is frontend-owned — it would contend directly with TASK-210-S2
   for the single kimi lane and the same $50 org-side cash wall. The
   orchestrator's own ordering says "then TASK-901..904 **as capacity allows**";
   capacity is spoken for until the S2 stages return.
   (b) *Defect, and this one blocks regardless of capacity.* All four packets
   carry `"issue": null`. The ledger refuses any non-refless intent without
   `--ref issue=N | pr=N` (`ledger.py:113`), so TASK_ASSIGN for these four
   cannot be sent at all. Four tracking issues must be created and written into
   the packets first. `tasks/packets/*` is protected, so that edit needs a
   triage-time `protected-change` authorization on the new issues (L-4).
   Revisit: when either S2 stage lands, or immediately if the orchestrator wants
   the four issues created ahead of capacity.
6. **Release loop**: extend bot/ announce plumbing with release announcements;
   triage Discord feedback via INTAKE_TICKET. The current intake backlog is
   already triaged: #92 DEFER to TASK-301 (Tier-2 side-by-side, open as the
   requirement tracker), #93 REJECT and closed. No intake is awaiting a
   [DECISION].
   Gated on stage landings — there is nothing to announce until a stage merges,
   and the directive is to extend the existing announce plumbing, not rebuild
   it. First trigger: TASK-210-S2 merging (that is the user-visible one).

Constraints (binding, from #97): green tier default; frontier only via frontier
gates; concurrency per effort.env; packets+issues for all work; gates never
weakened; completion dispatcher-verified (proofs #1–#15).
