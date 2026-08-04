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
   at `473c167`, S3 at `8cd7d0a`, S4 at `78765c1`. PRs #110 and #112 close as
   superseded-by-main (their heads are content-identical to what merged), and
   no S2/S3/S4 review is redispatched. Ruling: ADR-0010 — packet preconditions
   gate dispatch, not review; that settlement covers stale preconditions only
   and never a cancellation, supersession, or scope change.
5. **Finish the Windows overlay** — remaining TASK-210 scope, parent **issue
   #79** (human-reopened 2026-08-03T16:04:04Z; the reopen is authoritative, so
   #79 is the live parent and the TASK-211 successor issue #113 is closed as
   superseded — ADR-0010 decision 4). Stages: build-snapshot deep link (once,
   then zero interaction — I1), `run.bat` packaging into the Windows bundle
   (#75), capture→card p95 against I6's 300 ms — the last is already packeted
   as TASK-210-S5 (`378db32`, `issue: 79`); the first two still need packets.
   Frontend on kimi; $25 `cost_ceiling_usd` per stage under the $50 org-side
   wall. TTL 2026-08-17. Revisit if the #75 bundle changes target platform.
6. **Fan out TASK-901..904** (packets validated, dependency-ready) — unblocked
   now that the canary gate is open.
7. **Release loop**: extend bot/ announce plumbing with release announcements;
   triage Discord feedback via INTAKE_TICKET (intake backlog: #92, #93 pending).

## Close the end-to-end gap — 2026-08-03 (issue #97, orchestrator directive a4f731f4)

The mission sentence is "a player copies an item in game and sees a real
verdict card driven by the real engine." Landed so far: the clipboard
pipeline, e2e snapshots, the hotkey, the latency budget, the parity harness,
the release-note renderer. Three seams still stand between that inventory and
a player. Each is a green stage; each is dispatched with a packet.

7. **TASK-211-S1** (frontend, issue #90 — P0). The shipped page IS
   `web/src/demo/App.tsx`: its "Hotkey item" picker holds two hardcoded
   entries, so a tester cannot evaluate a single item they own. The stage adds
   the paste box and makes it the primary path, including the paste-anywhere
   route. The zip rebuild / release-asset / #poe correction criteria on #90
   are a LATER stage — this one is code only.
8. **TASK-212-S1** (backend, issue #119 — new). Every item this repo has ever
   calculated is in PoB EXPORT format. `grep -rl "Item Class:"` hits only
   `overlay/`. The overlay forwards game clipboard text unchanged on a stated
   "the server canonicalizes" contract that does not exist anywhere in
   `server/`. The stage shows the real engine real in-game text for the first
   time and either canonicalizes at the server boundary or records the failure
   in `engine/GAPS.md`. Nothing silently becomes CANT_EVALUATE (I5).
   **LANDED `69a1f6a` / PR #121. Answer: the engine accepts game clipboard
   text directly.** The pinned real worker read all three new fixtures
   (`engine/tests/fixtures/game_clipboard/`) with no normalizer: corrupted
   Hubris Circlet DOWNGRADE, rare Vaal Spirit Shield SIDEGRADE, unidentified
   Prophecy Wand DOWNGRADE. The overlay's "the server canonicalizes" contract
   needed no implementation because upstream `Item:ParseRaw` already handles
   the shape; no `engine/GAPS.md` entry was warranted. Canonicalization is
   therefore OFF the critical path (see the dispatch note below). Follow-up
   TASK-213 (#123) fixes the CI regression the merge introduced.
9. **TASK-210-S6** (frontend, issue #79). Every overlay test runs against a
   stub `postDiff` or the fixture mock; the web app has a real-server e2e and
   the overlay has none. The stage drives the production
   `createClipboardPipeline` composition against a real `python3 -m server`,
   stubbing only the Electron clipboard seam. Independent of #119 by design —
   it uses the existing golden item.

Dispatch order: 7 and 8 in parallel (different roles); 9 after 7 clears
frontend's queue. Revisit if TASK-212-S1 finds the engine rejects real game
text — that outcome promotes canonicalization to the critical path and
TASK-210-S6 should then re-run its e2e against a game-format fixture.
**RESOLVED (2026-08-03): it does not reject.** The reversal condition did not
fire. Canonicalization stays off the critical path and TASK-210-S6 keeps its
golden-item e2e. Revisit only if a player report shows a real clipboard shape
the engine rejects — that becomes a fixture first (I8), then a fix.

10. **TASK-213** (backend, issue #123 — ~~P0, blocks everything~~ **P0 LEG
    LANDED 2026-08-03 at `ead5b5a`**; residual scope below is P2 and NOT
    dispatchable to backend — see the routing note after this item). `main` was
    red on the required `engine-integration` check and had been since `69a1f6a`.
    TASK-212-S1 correctly added a contract-schema assertion importing
    `jsonschema`, but that job's `pip install` lists only `pyyaml`, so
    `unittest discover` dies at collection. One-line fix in
    `.github/workflows/ci.yml`; `protected-change` is on the issue to
    authorize it. This is the second instance of a job-local dependency list
    drifting from what its entrypoints import (`docs/runbooks/
    restart-readiness.md` records the `packet-validation` mirror image), so
    the task also asks for a recurrence guard or a filed issue saying why not.
    Nothing else should dispatch while a required check is red on main.

    **Closed out (2026-08-03).** The one-line dep fix landed at `ead5b5a` and
    `main` CI is green again (run 30842373663, `f08b119`). The orchestrator also
    swept the rest of the workflow for the same class of drift: the other two
    bare-`pyyaml` jobs are clean (`assumptions-fixtures` runs a stdlib-only
    script, `windows-runtime-build` runs PowerShell, neither does test
    discovery), so `engine-integration` was the only affected job. **Do not
    dispatch a task to fix this regression — it is fixed.** What remains open on
    #123 is only the recurrence guard, and `ead5b5a` explicitly left it undone.

    **Routing note — the recurrence guard cannot be packeted (2026-08-03).** A
    dependency-drift guard has to live in `.github/`, and no builder role can
    touch `.github/` at all. Backend circuit-broke on completion proof #12
    attempting exactly that. The mechanism matters for every future packet:
    `protected-change` is a MERGE-TIME label the merge robot checks (condition
    5), but proof #12 fires far earlier, at dispatch-time completion
    verification, and it does not consult labels. So a `protected-change` label
    does **not** make a PROTECTED path packetable — putting one in
    `files_in_scope` is unwinnable for every role except pm's narrow
    `tasks/packets/*` carve-out. Protected work routes to the orchestrator, not
    into a packet. This is why the guard is not queued as a stage.

Not packeted, deliberately: shipping the overlay itself to players. The MVP
zip (`scripts/package_mvp.sh`, `packaging/launch.py`) contains no overlay at
all and running it needs npm + Electron. That is a real gap, it is bigger than
one green stage, and it is worth nothing until the three seams above hold.

Constraints (binding, from #97): green tier default; frontier only via frontier
gates; concurrency per effort.env; packets+issues for all work; gates never
weakened; completion dispatcher-verified (proofs #1–#15).

## Tier-2 is the last honest gap in the mission sentence — 2026-08-03 (issue #125)

All three legs of #97 are proven against the real engine (9d63b72, b8620b5,
1846df2). The mission sentence now holds: a player copies an item in game and
sees a real verdict card. What the card cannot do is say WHY.

**Numbering correction (2026-08-03): these stages are TASK-214-S1/S2, not
TASK-213-S1/S2.** I authored them as TASK-213-* while item 10 above had already
assigned TASK-213 to the CI regression on issue #123; both landed on `main` and
contradicted each other. TASK-213 stays with #123 (the earlier assignment, and
its fix is already merged under that ID); Tier-2 takes the next free parent,
**TASK-214**, on issue #125. Packets renamed to `tasks/packets/TASK-214-S1.json`
and `TASK-214-S2.json`; issue #125 retitled. Nothing was dispatched under the
old IDs, so no branch or PR needs renaming. The collision is not cosmetic — the
same mistake on TASK-212-S1 an hour earlier mislabelled two branches and left a
stale assignment that burned frontend invocations on already-merged work.
**Standing rule: before numbering a new parent task, grep `tasks/BACKLOG.md` and
`tasks/packets/` for the ID — a concurrent author may already hold it.**

10. **TASK-214-S1** (backend, issue #125 — P0). `GET /breakdown/{diff_id}` is
    specified at `contracts/openapi.yaml:129` and **has never existed**:
    `grep -n breakdown server/*.py` returns nothing, and `_diff_id()` hashes a
    calculation the server then discards. The whole web client has been wired
    to it since TASK-301 (`DetailsPanel` → `detailsClient` → generated
    `getBreakdown`), so on the real server the "open details" tap renders
    *Breakdown unavailable*; against the mock it renders
    `web/mock/fixtures/breakdown/*.json` drivers that were never computed from
    anyone's item. The stage adds a bounded per-diff store and computes
    drivers by **leave-one-out re-evaluation** — remove one modifier line,
    re-run the engine, and the movement in the delta IS that mod's
    contribution. Real measurements or an empty list; never an estimate (I5).
    Contract surface: **none** — implementing a ratified path needs no RFC.
11. **TASK-214-S2** (frontend, issue #125). `web/test/realServer.e2e.test.tsx`
    has never opened details, which is precisely why nobody noticed the route
    was missing. The stage drives the affordance against a live
    `python3 -m server` and asserts the panel shows the server's drivers.
    Test-only; `web/src/**` out of scope.

Dispatch order: **S1 now; S2 the moment S1 merges** — S2 cannot go green
before the route exists, so frontend is idle by sequencing for exactly one
stage. Revisit if S1 finds leave-one-out attribution is not tractable against
the warm worker; the fallback is a stat-level breakdown with no mod
attribution, which needs a contract conversation and therefore comes back to
pm.

**Ruling — TASK-102-S3/S4/S5 are DEFERRED, not cancelled.** They replay frozen
seed builds 16–25 into `engine/corpus/`, a protected path, so they are red tier
and each one spends a full review round-trip from the counterpart role. The
corpus gate is green at 15 builds and no parity defect has been traced to a
build outside it; buying breadth we have no failing evidence for, at review
prices, while a Tier-2 promise sits unimplemented, is the wrong trade. Revisit
when either is true: (a) a parity defect appears in a build outside the
15-build corpus, or (b) backend goes idle with no green product work queued —
then dispatch S3 first, since inert data is the cheapest red-tier stage the
org has. Ordering stays binding: S3 → S4 → S5, manifest flips last.

**Still not packeted, deliberately: shipping the overlay itself to players.**
The Windows bundle (`scripts/package_mvp_windows.ps1`, `packaging/run.bat`)
carries the web app, the server and the pinned engine runtime — no overlay,
which needs npm + Electron on the tester's box. The three seams now hold, so
this is no longer worthless work; it is still Electron bundling, which is
larger than one green stage and needs decomposition before it is dispatched.
Revisit at the next routing pass, ahead of TASK-102-S3.

## TASK-214-S1 is TASK-213-S1 and it already landed — 2026-08-03 (issue #125)

Backend reported TASK-214-S1 COMPLETE at `7171228` on
`backend/TASK-214-S1-breakdown` (PR #133, 14/14 CI green). The report is
substantively true and materially stale: the tree it carries is **already on
`main`**. `git diff origin/main 7171228` is empty — `main^{tree}` and
`7171228^{tree}` are both `11ec57c3`. The implementation landed as `c05ae0e`
(PR #128's head) via merge `e77a343` while the renumber was still in flight.

**Ruling: the stage is ACCEPTED as delivered at `c05ae0e`; PR #133 is CLOSED as
a zero-diff duplicate.** Merging it would add a merge commit that changes no
file. Backend closed #128 as "superseded" believing #133 would carry the work,
but #128's commit had already merged — the supersession ran the wrong way.
No new backend invocation is owed; nothing is lost.

**The ID stays TASK-213-S1.** The earlier renumber to TASK-214 was reversed by
the landed ruling on #125: renaming stages would invalidate a merged packet, a
pushed branch and a landed PR to fix a label, so the finished CI regression was
renamed `TASK-213-CI` (#123) instead and the Tier-2 stages kept `TASK-213-S1/S2`
(#125). `tasks/packets/` already matches that ruling — there is no
`TASK-214-*.json` and none should be created. Treat `TASK-214-S1` as a dead
alias for `TASK-213-S1`; it names no distinct work.

**Flagged for the next triage pass, not touched here:** PRs #130, #131 and #132
are pm branches that still propose the reversed renumber. They are superseded by
the ruling above and would reintroduce a resolved collision if landed. Whoever
routes next should close them; this invocation owned only the #133 disposition.

**Remaining on #125: TASK-213-S2 (frontend), already dispatched** — its
precondition was S1 on `main`, which has held since `e77a343`. #125 stays open
until S2 is green. Revisit if a fourth thing claims the `TASK-213` prefix; the
next free integer is cheaper than more disambiguation.

## Ship, feedback, and the done rule — 2026-08-04 (issue #97, orchestrator ruling 99029738)

The operator has put shipping and user feedback inside the SDLC. "All tests
pass" is no longer done. The loop is:

    build -> prove -> ANNOUNCE to #poe -> await feedback
        -> feedback?  yes: triage, packet, build, announce again
                      no:  the mission is done

**Announce is a required stage of every mission**, not a follow-on. A mission
that never told a player it shipped is not finished.

### What is already built (found, not rebuilt)

- `/suggest` (TASK-401, issue #16) is LIVE in `bot/bot.py` and is the org's
  intake path: scrub -> `untrusted` fence -> `quarantine_check` -> GitHub issue
  labeled `intake` -> `INTAKE_TICKET` to pm -> `[DECISION]` comment relayed back
  into a public thread. It has already carried real tickets (#38, #40, #86,
  #92, #93). Nothing about intake needs building.
- `bot/release_notes.py` (TASK-300-S1) renders a commit range into one
  player-facing message, render-only by construction, and returns `None` when
  there is nothing to say.
- `bot/bot.py` already resolves `ANNOUNCE_CHANNEL_ID` for the weekly digest and
  already demonstrates the durable-marker exactly-once pattern (`weekly_digest`).
- **TASK-404** (issue #27, PR #30, `backend/task-404-feedback-piping` @3b78c29)
  built a passive `#feedback` message-content listener. It is PARKED under a
  standing `[DECISION]` with `needs-redesign`: in single-channel mode it means
  classifying general chat, at 3–5 users that is poor signal, and it needs the
  privileged Message Content intent that only a human can enable. **It stays
  parked.** Un-park trigger unchanged: ~25 members, or a demonstrated
  feedback-volume problem.

So the only real gap is the wiring, dispatched as **TASK-300-S2 (backend,
green)** — at-most-once posting of a release range to the live channel, a v0
headline for the four shipped legs, a footer pointing at `/suggest`, and an
`on_message` nudge that answers a human reply in the announce channel without
ever reading its content (works under `Intents.default()`, no privileged
intent, no operator portal change).

### The done rule (pm ruling — disagree with the number, not a vibe)

**The mission is DONE when v0 has been announced in #poe and 72 hours have
passed with no qualifying feedback.**

- **Clock starts** at the timestamp of the successful v0 announcement (the
  `release_announce` row in `BOT_DB`; the same fact is recorded on #97).
- **Qualifying feedback** is exactly one thing: an `intake`-labeled issue
  created after that timestamp. That is the only form of feedback the org can
  actually act on.
- A bare reply in the channel is a signal, not work. It gets the `/suggest`
  nudge and **restarts the 72-hour clock once**. If it never becomes an intake
  ticket within that window, it stops holding the mission open — the org
  answered, the player did not follow through.
- **On qualifying feedback:** triage within 24h to a `[DECISION]` comment,
  packet it, build it, announce again. The new announcement restarts the clock
  at 72h. Feedback is never a reason to declare done early or late.
- **Whoever runs the clock:** pm, on the first invocation after
  `announce_at + 72h`. Check is mechanical —
  `gh issue list --label intake --state all --search "created:><announce_at>"`.
  Empty result: record the done ruling on #97 and in this file. Non-empty:
  triage it.

**Why 72 hours.** The triage SLA is 24h (TASK-402), so 72h is three full SLA
windows and always spans a weekend — a 3–5 person server plays on its own
cadence, and a 24h rule would call the mission done before a player who works
weekdays has logged in. A week would idle the org against a channel that is
empty in the first hour and stay idle for six more days, which the invocation
ruling explicitly forbids. 72h is the shortest interval that cannot be
mistaken for "nobody was given a chance to answer."

**Reversal conditions.** Shorten to 24h if any single announcement draws more
than three intake tickets — at that point signal arrives fast and waiting is
just latency. Revisit the whole rule (and the TASK-404 un-park) if the server
grows past ~25 members. Extend only if the operator says the audience was not
reachable during the window.
