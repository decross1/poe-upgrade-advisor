# Restart readiness record

**Status: IN PROGRESS — no verdict issued.** This is a living record; it is
updated as each unit is verified, not written from memory at the end. A verdict
appears at the bottom only when every mandatory gate for the claimed level has
an evidence row.

- Program: `poe_autonomous_org_restart_program_v1.0.md`, narrowed per **ADR-0007**
- Current state: `docs/agent-org/current-state-2026-08-02.md` (Phase 0)
- Baseline: `a04c8b3` · Integration branch: `main`
- Loops: **halted**. `mailroom/HALT` present since 2026-07-27T22:07, verified at
  every unit acceptance.

Evidence tags: `[O]` observed · `[E]` estimate · `[A]` assumption · `[X]` experiment required.

---

## 1. Unit status

Eleven units, two lanes, executed concurrently against a frozen interface seam
(`agents/interfaces/`). Every accepted unit was verified by pm independently —
mechanically, then structurally, then by mutation where there was logic to break.

| Unit | Lane | Status | Evidence |
|---|---|---|---|
| W1-1 characterisation tests | A | **ACCEPTED** | `d897de2`. 57 tests. `budget_governor.py` 20.3% -> 89.9%, `ledger.py` 19.6% -> 98.6%. Zero production diff. **9/9 mutation probes caught.** |
| W1-2 governed dispatcher | A | **ACCEPTED** | `1a985dd`+`5fb068f`+`7b839f6`. Attempt ledger increments before invoke; per-message cap; ORG exemption deleted. **7/7 mutation probes caught** after the ORG per-task-cap follow-up. |
| W1-3 preflight + no-op suppression | A | **ACCEPTED** | `f13c3c8`+`3192395`. 39 tests. All ★ cases. **4/4 mutation probes caught**, including three ways of breaking the blocker fingerprint. |
| W1-4 worktree recovery | A | **ACCEPTED** | `5804a08`+`00488d6`+`03a5f88`. Validated against **real data**: 13 unrecovered `.fan` worktrees, **166,770 bytes** of six-day-old work captured. Submodule-pointer gap found and closed. |
| W1-5 CI hard blockers | B | **ACCEPTED** | `e932f32`+`405d74f`. `web-test`/`overlay-test`/`coverage-floor` are real jobs and required checks; every required check maps to a real job; coverage gate exits 1 below floor. |
| W1-6 readiness gate | B | **ACCEPTED** | `a4ec5cc`. 14 tests. All four modes exit 1 correctly; mode escalation matrix verified; ran against real state with a before/after mailroom snapshot — **wrote nothing**. |
| W2-1 telemetry + metrics | B | **ACCEPTED** | `05bfc16`. Fail-closed at open, write and read; fail-open telemetry; unknown never zero. 33-agent adversarial pass: every *high* downgraded. |
| W2-2 pm-lite scheduler | B | **ACCEPTED** | `28f3eef`. Injected model spawn into `poll()` -> **CAUGHT**. Judgement triggers idempotent across polls. |
| W2-3 run budgets + degradation | B | **ACCEPTED** | `c8355d6`+`87f2342`. Seven postures; stale allowance denies headroom; weekly reset read as new-cycle use; mode-aware. |
| W2-4 anti-loop controller | A | **ACCEPTED** | `03a5f88`+`a54ac8f`+`aabc201`. 4/4 fingerprint mutations caught after the strategy-component follow-up. |
| W2-5 task packets + stage identity | B | **ACCEPTED** | `aed57f6`. ADR-0008 stage logic; `Fixes` on a stage PR refused; diagnostic split landed. |

**Integration:** trial merge of both lanes run early rather than at checkpoint.
`merge-tree` clean both ways; integrated suite **235 passed**; lint, doctrine
invariants and fixture coverage green; integrated coverage **83.03%** `[O]`.

---

## 2. Mandatory gates for `GO-CANARY`

| Gate | Status | Evidence |
|---|---|---|
| HALT works and is honoured | **PASS** | `[O]` present throughout; `agent_loop.sh` idles on it; W1-4 adds an in-worker re-check |
| Readiness checker | **PASS** | `scripts/check_agent_readiness.py`, 4 modes, zero model calls, fails closed `[O]` |
| One governed dispatcher | **PASS** | `agents/dispatch.py`; no bare model command remains in `agent_loop.sh` `[O]` |
| Preflight + structured results | **PASS** | W1-3; `exit 0` is not success — enforced and mutation-tested |
| Telemetry | partial | `JsonlTelemetry` live and fail-open; durable store is W2-1 |
| Task budgets | **PASS** | `execution_classes` green/yellow/red/org; packet overrides may only tighten |
| Worktree recovery | pending | W1-4 tests in flight |
| Core orchestration tests | **PASS** | 235 integrated |
| Human observing | operator | not a code gate |

## 3. Mandatory gates for `GO-SUPERVISED`

All canary gates plus:

| Gate | Status | Evidence |
|---|---|---|
| Task packets | pending | W2-5 |
| Loop detection | pending | W2-4 |
| Frontend CI | **PASS** | `web-test` + `overlay-test` required `[O]` |
| Contract + generated-client gates | **partial** | contract validation exists; generated-client drift check **not implemented** |
| Resource locks | **not implemented** | deferred per ADR-0007 (no observed contention yet) |
| Multi-role test at conservative concurrency | pending | canary |
| Accepted-task metrics | pending | W2-1 |

## 4. `GO-UNATTENDED-7D` — **not reachable by this program**

Recorded here so a later session does not read a supervised verdict as an
implementation failure. Three prerequisites are human-only and unprovisioned:

| Prerequisite | State |
|---|---|
| `MERGE_ROBOT_TOKEN` | unset `[O]` (401s observed in the ledger) |
| Branch protection on `main` | absent `[O]` |
| Distinct bot identities | absent — all roles and the human share one login (ADR-0003) `[O]` |

**And provisioning all three is necessary but not sufficient.** See
`current-state-2026-08-02.md` §7 blocker 2a: the evidence-bearing-approval read
path has never worked. Replayed against the two live approved PRs, merge-robot
condition 2/3 fails on both — #87 has zero review objects (its evidence is in a
PR issue comment the robot never reads), #91 has one review whose state is
`COMMENTED`, which the `APPROVED` filter drops. Neither failure is the shared
identity ADR-0003 substitutes for. That is a code fix, tracked to W2-5.

---

## 5. Findings that changed the plan

Each of these contradicted a premise shared by all four planning documents.

1. **The cascade was ~20× larger than documented.** 1,408 invocations, not the
   "~50 burned" every document states; ~1,239 (~88%) produced nothing. Six `pm`
   messages re-fanned 100–180 times each. The seven message IDs in `pm.log` are
   exactly the seven still unacked today. `[O]`
2. **Every one of those 1,408 invocations exited `rc=0`.** The process exit code
   carried zero bits about whether anything happened. `[O]`
3. **Coverage baseline is 68.4%, not 43%** — and integrated, 83.03%. Setting the
   floor from the documents would have weakened the gate by ~39 points under a
   commit message claiming to activate it. `[O]`
4. **Kimi is already retired.** No metered provider remains in the live path, so
   the binding constraint is entirely subscription capacity. Per finding 8 that
   is the one quantity neither CLI reports, which promotes
   `allowance_pct_source` from supplementary to load-bearing. `[O]`
5. **Four gates of identical shape — each reading from a place nothing writes
   to**, none ever observed because the components were never exercised: `[O]`

   | Gate | Read from | Written by |
   |---|---|---|
   | coverage ratchet | check-run `output.summary` | nothing — CI printed to stdout |
   | `TEST_SIG` condition 7 | `^\+.*xit\(` | matched `sys.exit(`, not just excluded tests |
   | evidence-bearing approval | `/pulls/{n}/reviews` state `APPROVED` | org wrote issue comments and `COMMENTED` reviews |
   | readiness `github_auth` | `mailroom/readiness.yaml` | nothing — file does not exist |

   `mailroom/readiness.yaml` also carries the operator-selected
   `operating_mode` (`canary`, `supervised`, `unattended-7d`, or
   `unattended-10d`). The run-budget loader reads that same value. A missing or
   invalid value defaults to `unattended-10d`; it never silently grants the
   supervised missing-allowance exception.

   The fourth is in the readiness gate itself. It fails closed, so it cannot
   cause an unsafe restart, but it reports operator attestation for a fact
   (`gh auth status`) that is directly measurable. **This is the single most
   repeated defect in this control plane** and it deserves a standing review
   question: *what writes the thing this gate reads?*
6. **Dead-letters evaporated with the throwaway worktree** — `_dead_letter`
   wrote into the `.fan` worktree that cleanup removes, so the artifact would
   have been lost even had the breaker fired. `[O]`
7. **A PM ruling sat unanswered for six days** because the message requesting it
   could not be acknowledged. PR #91 was blocked the whole time. Resolved in
   ADR-0008. The missing ack path cost decisions, not only capacity.
8. **Provider CLIs *do* emit machine-readable token usage — but not allowance.**
   Resolves `HANDOFF` §9 open questions 1 and 2, which every prior document
   left as `[A]`. Determined without invoking a model.

   | Question | Answer |
   |---|---|
   | `codex exec` machine-readable usage? | **yes** — `--json` prints JSONL events including `inputTokens`, `cachedInputTokens`, `outputTokens`, reasoning tokens |
   | `claude -p` machine-readable usage? | **yes** — `--output-format json\|stream-json` exposes `usage` (input/output/cache tokens) and total cost |
   | Subscription weekly-allowance percentage? | **no** — neither CLI exposes a trustworthy figure |

   pm verified the **flags** exist `[O]` (`codex exec --help` -> `--json  Print
   events to stdout as JSONL`; `claude --help` -> `--output-format ... "stream-json"`).
   The **field names** are `[E]` — Lane B took them from strings in the
   installed binaries, not from a documented output schema or a live
   invocation, and said so unprompted when asked to distinguish. They may
   change under a CLI update. W2-1's adapter therefore accepts both snake_case
   and camelCase variants and, for a non-empty `usage` object with no
   recognised fields, records every measurement as `None` and emits
   `TELEMETRY-DEGRADED` with the observed keys — it neither records zero nor
   fails silently.

   Consequence: per-invocation token and cash accounting is mechanically
   obtainable and should not be estimated. But the **binding** constraint —
   subscription capacity, now that Kimi is retired and no metered provider
   remains — is not machine-readable, so `allowance_pct_source:
   manual_daily_reading` and the W2-1 calibration factor are load-bearing
   rather than supplementary. A run budget for the two subscription roles rests
   on a human reading a dashboard once a day.

---

## 6. Accepted risks, with expiry

| Risk | Mitigation | Expires |
|---|---|---|
| No sandbox — agents run with permission bypasses because host userns fails (`RTM_NEWADDR EPERM`) `[O]` | Branch-push-only scope; protected paths enforced by a **deployed** merge robot; HALT; concurrency cap | Wave 3, or on the first protected-path violation attempt |
| `server/calculator.py` at 47% coverage remains Red | Routed to frontier only; property tests deferred | First verdict-correctness incident |
| Allowance percentage is not machine-readable `[O]` — confirmed, not assumed | Daily manual dashboard reading + W2-1 calibration factor over duration x invocation weight | When a provider exposes it |
| 13 dirty `.fan` worktrees hold unrecovered work `[O]` | Preserved untouched; **must not be pruned**; triage after W1-4 lands | Before `HALT` is lifted |
| 8 unacknowledged ledger messages, 7 of them the ones that looped `[O]` | Triaged in `unacked-queue-triage-2026-08-02.md`; operator acks | Before `HALT` is lifted |
| Every budget number in the planning documents is `[E]` from a run measured at 1/5th its true invocation count | Ship structure with values marked placeholder; re-derive from W2-1 telemetry | First shakedown |

---

## 7. Verdict

## **CONDITIONAL GO-CANARY**

All eleven units are implemented, integrated and independently verified. The
control plane is ready. **The readiness checker exits 1 for every mode**, and it
is right to — the org's own operational state is not yet clean. Every failure is
an operator action; none is a code defect.

A bare `GO` without an operational level is invalid, and a `GO-CANARY` whose
readiness checker fails is a claim contradicted by the tool built to test it. So
the verdict is conditional, in the program's required format:

```
approved_mode:        GO-CANARY — one bounded task, concurrency 1, actively observed
temporary_exception:  none; no gate is waived
risk:                 low — per-task budgets, attempt cap, preflight, recovery
                      and the anti-loop controller are all live and mutation-tested
mitigation:           the seven conditions below are mechanical, enumerated, and
                      each verifiable by re-running the readiness checker
owner:                human operator (Derrick)
expiration_date:      2026-08-16 — re-verify if the canary has not run by then
shutdown_condition:   touch mailroom/HALT
work_required_for_full_go: sections 3 and 4 below
```

### The seven conditions, in order

Four collapse to one action:

1. **Create `mailroom/readiness.yaml`** from
   `docs/runbooks/readiness.example.yaml`, set `operating_mode: canary`, and
   fill `worktrees`, `model_clis` and `github` from observed state. This clears
   `operating_mode`, `model_clis`, `github_auth` and `worktrees`.
2. **Clear the 9 stale running markers** — every PID confirmed dead
   (`mailroom/locks/running/`).
3. **Acknowledge the 8 unacked ledger messages** per
   `docs/agent-org/unacked-queue-triage-2026-08-02.md`. Two of them
   (PRs #87, #91) should be merged or deliberately parked first. **This is not
   housekeeping** — those seven `pm` messages are the ones that were re-fanned
   977 times, and lifting `HALT` with them queued restarts the cascade on the
   first poll.
4. **Create `mailroom/telemetry/`.**

Then `python3 scripts/check_agent_readiness.py --mode canary` must exit 0. Do
not start anything until it does.

### Gate evidence at `main`

| Gate | Result |
|---|---|
| Test suite | **389 passed** (from 55 at baseline) |
| Lint | clean |
| Doctrine invariants + fixture coverage | OK |
| Coverage | **87.45%**, floor **86.8** — ratchet active and proven to fire |
| `agent_loop.sh` bare model commands | **0** (4 `dispatch.py` call sites) |
| `mailroom/HALT` | **set** throughout |
| Live loop processes | **0** |
| Ledger corpus | 296 messages, unmodified |
| Dirty `.fan` worktrees | 13, **preserved untouched** |

### What is NOT approved

**`GO-SUPERVISED`** — reachable, but it needs the canary to have run first and
the merge-automation warning cleared.

**`GO-UNATTENDED-7D` / `-10D`** — **NO-GO**, and not reachable by this program at
any level of execution quality. `MERGE_ROBOT_TOKEN` is unset, `main` is
unprotected, and all roles share one GitHub identity. Provisioning those is
necessary but **not sufficient**: §4 records that the evidence-bearing-approval
read path never worked, so both live approved PRs would still fail merge-robot
condition 2/3 on the day the token appears. That is now fixed in code; it has
never been exercised against real GitHub.

The readiness checker enforces this itself — `unattended-7d` fails 10 checks and
`unattended-10d` fails 11, including `shakedown` and `reserve_budget`, which
cannot be satisfied except by running the 48-hour shakedown with its hour-24
injected fault. **No shakedown has been run.** Nothing in this program should be
read as approving unattended operation.

### Honest limits of this verification

- **No model was invoked.** `HALT` was set throughout; every executor is a fake.
  The dispatcher has never driven a real model end to end.
- **No CI job has run.** `web-test`, `overlay-test` and `coverage-floor` are
  defined and their underlying commands pass locally; the *jobs* are unverified
  until they run on GitHub.
- **The merge robot has still never executed.** Its logic is now tested against
  monkeypatched fixtures, not GitHub.
- **Nothing is pushed.** All work is local on `main`.
- Provider usage **field names** are `[E]`, taken from binary strings, not a
  documented schema.

### Follow-ups carried, none blocking

`agents/interfaces/` accumulated three defects of the same class — the frozen
seam both lanes were forbidden to edit proved the least reliable file in the
repo, and each was found by adversarial probing rather than by review. The
standing question that would have caught all of them, and the five gate defects
in §5: **what writes the thing this gate reads?**

Outstanding: `github.authenticated` should be measured rather than attested;
M1/M4 ledger-atomicity tests; a real GitHub exercise of the merge robot.

---

*Verdict issued by pm on 2026-08-02 against `main`. The organization remains
offline until an operator completes §7 and the readiness checker exits 0.*

---

## Post-push CI evidence — appended 2026-08-02 after `main` was pushed

The push to `origin/main` at `cfc503e` was the **first time any of the new CI
jobs had ever executed**. §7 recorded "no CI job has run" as a limit of the
verification; that is now resolved, and it produced three findings that local
runs could not.

### Passing, first time in the repository's history

`web-test` — **green**. 5,003 lines of `web/` had no mechanical gate at all
before this program. `lint`, `contracts`, `doctrine-invariants`,
`assumptions-fixtures`, `engine-integration`, `windows-runtime-build`,
`windows-package-cleanroom`, `windows-worker-pipes` and
`runtime-parity-cross-platform` also green.

### Two CI-only defects in my own work, fixed in `bfe0751`

1. **`packet-validation`** installed only `jsonschema`, but
   `agents/packets/validate.py` imports `agents.interfaces`, whose `__init__`
   pulls `policy.py` -> `yaml`. An AST scan of the script's own imports missed
   it because the dependency arrives through a package `__init__`.
2. **`test` and `coverage-floor`** both failed on
   `test_every_unique_example_required_check_exists_and_runs`, which shelled
   `npm --prefix web run test` from a Python-only job. It failed on a missing
   toolchain rather than a bad packet. Narrowed to assert the check is
   well-formed and its workspace exists, and to execute only where the
   toolchain is present — running the npm suites is `web-test`/`overlay-test`'s
   job, and both are required checks.

Both reproduced against a clean `git archive` export before being fixed.

### `overlay-test` — a real, pre-existing defect the gate caught immediately

```
FAIL test/diffFlow.test.ts > diffFlow — chip tap -> one re-diff (I3/§7, issue #64)
  × RULING-21: each failed retry keeps its own transient state
  × a re-diff timing out counts as failure (RULING-19/21)
  AssertionError: expected { kind: 'ERROR_UNAVAILABLE' }
                  to deeply equal { kind: 'VERDICT', ...(3) }
2 failed of 17 in diffFlow.test.ts — reproduced identically on two consecutive
CI runs (30731148600, 30731359010), so it is deterministic under CI load rather
than intermittent.
```

**Not a CI configuration problem.** `overlay/test/diffFlow.test.ts` asserts
request-supersession semantics using wall-clock delays (`setTimeout(r, 100)`,
`sleep(50)`). Locally the suite passes **5 runs out of 5**; on a loaded CI
runner the ordering inverts and a request that should return a verdict reports
unavailable.

This is the clearest justification for the program that exists. `overlay/` is
2,401 lines that had **never been mechanically checked**, its `node_modules`
was not even installed on this box, and the very first CI execution surfaced a
latent timing defect. The audit predicted exactly this: *"initial red builds on
latent failures. That is information, not cost."*

**Disposition — the gate stays required.** `overlay-test` remains in
`REQUIRED_CHECKS`. Removing it to make `main` green would be gate-weakening,
which `AGENTS.md` calls the one behaviour treated as adversarial, and it would
discard the only mechanical check the overlay has ever had. Fixing the overlay
tests is frontend product work and an explicit non-goal of this program
(ADR-0007).

**It becomes the first canary task.** A flaky required check is a merge blocker
and erodes trust in the gate faster than a missing one, so it is not something
to sit on — but it is also precisely the right shape for the canary: bounded,
well-specified, in a single subsystem, with a mechanical pass condition, and
now covered by a gate. The control plane's first real job is fixing the defect
its own gate found.

**Consequence for the verdict:** unchanged. `CONDITIONAL GO-CANARY` already
required an operator to clear §7 before anything runs. This adds a known-red
required check to the record rather than a new class of risk, and the canary
task is now identified rather than hypothetical.

---

## Correction: pm's own probes wrote to the real mailroom

Appended after the final state check, because I asserted more than I had
verified.

I verified with a byte/mtime snapshot that **`check_agent_readiness.py` writes
nothing**, and that holds. I then generalised it to "nothing has been written to
the real mailroom during this entire exercise, by anyone". That was wrong.

`agents/run_budget.load()` resolves the **real** project mailroom and constructs
an `AccountingBudgetLedger` at `mailroom/governor/budget_ledger.sqlite3`, and
every `check()` records a governor decision — because I asked Lane B to make
every verdict fail-closed recorded. My mode-ruling probes therefore created a
ledger and wrote **141 `governor_decisions` rows** plus one `run_state` row.

What it did **not** do, verified directly:

```
spend:               0 rows      <- no model was ever invoked
attempts:            0 rows      <- no message was ever dispatched
allowance_readings:  0 rows
messages: 296 · cursors 91/107/90 · HALT mtime 2026-07-27T22:07:04
```

Every decision row reads `deny — codex allowance reading missing or stale`,
which is the fail-closed path working exactly as designed. `HALT` was never
touched, the queue never moved, and no model ran.

**Disposition.** The file was created entirely by my probes — Phase 0 recorded
that no governor sqlite existed — and it contains no real data, but 141 phantom
decisions would pollute the first genuine `agent_metrics.py` output an operator
reads. Moved aside rather than deleted, because it is operational state even
when I am the one who created it:

```
mailroom/governor/budget_ledger.sqlite3.pm-probe-residue-20260802
```

Delete it whenever convenient; the org recreates the ledger on first run.

**The lesson is the program's own.** I checked one component for writes,
observed none, and generalised the finding to components I had not checked.
That is the same shape as every gate defect catalogued in §5 — a claim about a
thing nobody actually looked at. The readiness record should say what was
measured, not what was inferred from an adjacent measurement.

---

## Second probe incident, and two perishable measurements — appended 2026-08-02T18:45Z

### The sidecar files: my probes touched the quarantined residue

During today's read-only evidence sweep (pre-dispatch verification for the
critical-closure program), one of my probe agents opened
`mailroom/governor/budget_ledger.sqlite3.pm-probe-residue-20260802` — the
quarantined residue itself — in read-write mode at 17:15:40Z, creating WAL
sidecar files inside the evidence mailroom:

```
budget_ledger.sqlite3.pm-probe-residue-20260802       53248 bytes, mtime 03:02:54 — UNTOUCHED
  sha256 807558428832c1d8dd433568d254a7efa2ca6dc66c8a2f7c4b984b8e2ca54029
...-wal   0 bytes     sha256 e3b0c442... (the empty-string hash: ZERO frames, nothing written)
...-shm   32768 bytes SQLite shared-memory index, no durable content
```

The main database's bytes, size and mtime are unchanged and the WAL is empty:
no rows were created or altered. The two sidecars were my probe's artifacts
and were REMOVED at ~18:50Z the same day, after the checksums above were
recorded; the main file's sha256 was re-verified unchanged after the removal.
(Correction per the reconstruction audit DELTA-8: an earlier revision of this
paragraph said "are to be removed" after they were already gone — records
must trail actions, not intentions.) The instruction to that
probe said read-only in three places; the lesson is the one this file already
records twice — a constraint stated is not a constraint enforced. A8/B3
(CI-enforced write-free snapshot regression) is the enforcement.

### The stale-marker measurement is perishable — recorded here before it decays

All nine `mailroom/locks/running/` marker PIDs (1558003, 1789116, 1789153,
1789159, 1789165, 1789175, 1789185, 1789194, 1789202) were verified DEAD at
2026-08-02 ~17:15–17:45Z by two independent probes: `/proc/<pid>` absent for
every one, `ps -p` empty, full `ps -eo` scan of the surrounding PID bands.

That fact CANNOT be re-derived later: the PID allocator has already wrapped at
least twice this boot (proved by non-monotonic PID-vs-start-time pairs, e.g.
PID 1507689 started Jun 30 vs PID 1528509 started Jul 27), `ns_last_pid` was
~4,039,000 of `pid_max` 4,194,304 at 17:26Z burning ~412k PIDs/day — the next
wrap is HOURS away and reuse of the marker band follows within days. After
that, `os.kill(pid, 0)` on these markers may find an unrelated live process and
the readiness checker's `stale_markers` will silently flip FAIL→PASS on aliased
PIDs. An earlier draft justified "dead" with "the allocator has not wrapped";
that justification was WRONG (adversarial review caught it) — the measurement
above, not the reasoning, is the record.

Consequences carried into the program: (1) markers are to be MOVED aside, not
deleted — eight of nine role-log trails end "fan invoke done rc=0", so the
markers are the only surviving artifact of the leak itself (the EXIT-trap bug
in agent_loop.sh's fan_worker: `local marker` is popped before the EXIT trap
runs, reproduced standalone); (2) `_stale_markers`' bare `os.kill(pid, 0)` needs
start-time corroboration — folded into Lane B's B3 unit.

### One more standing fact

The scheduled `merge-robot` workflow has been firing roughly hourly and failing
every run (observed 12:59, 14:28, 15:36, 16:42, 17:48Z today) — 401 by design
while `MERGE_ROBOT_TOKEN` is unset. Disposition is the operator's; recorded so
the failure stream is not mistaken for new breakage.

## GO-LIVE — the org is online. Canary GREEN, 2026-08-03T04:04Z

`HALT` lifted 04:03:27Z after the readiness gate exited **0** for the first
time in its existence (20 checks PASS, `merge_automation` WARN only). The
canary dispatched one second later and completed in **81 seconds**.

```
approved_mode:        GO-SUPERVISED — concurrency per effort.env, human observed
temporary_exception:  none; no gate waived
risk:                 low-moderate — controls proven live; three live defects
                      found and fixed in-session; recalibration deferred
mitigation:           per-message attempt cap, anti-loop, preflight, dispatcher-run
                      checks, 15 completion proofs, per-day caps, $50 kimi wall
owner:                human operator (Derrick)
expiration_date:      2026-08-17 — re-verify if idle by then
shutdown_condition:   touch mailroom/HALT
work_required_for_full_go: the carry-list below; GO-UNATTENDED remains NO-GO
```

### Canary evidence — TASK-999-S1, run `a6228fff`, all fifteen proofs PASS

Real `codex` invocation, real branch, real push. Verified by pm from the
artifacts, not from the exit code:

| Proof | Result |
|---|---|
| #1–#2 result valid, completed fields | PASS |
| #3 pushed · #4 branch `canary/TASK-999-S1` conforms | PASS |
| #5 commit `c877430` exists · #6 descends from `e346c4c` | PASS |
| #7 tree clean after CC-3 sweep | PASS |
| #8 remote agreement — `ls-remote` raw output persisted | PASS |
| #9 **1 dispatcher-run check rc=0; the agent's `tests[]` was not consulted** | PASS |
| #10 2 ACs, exact id-set, evidence present | PASS |
| #11 scope · #12 protected paths · #13 banned patterns | PASS |
| #14 budgets · #15 accounting before ack, bundle persisted | PASS |

Spend recorded: 249,826 in / 3,085 out tokens. Message acked. **v1.1's
central finding is closed in production: the system no longer asks the agent
whether the agent succeeded.**

### What the first live run found that no fake could

1. **The pm `claude` spawn was broken.** The first real pm invocation
   (mission SYNC) died in 1.2s: `--output-format stream-json` with `-p`
   *requires* `--verbose`. Every prior exercise of that branch used a fake —
   §7's "no model was invoked" limit was hiding exactly this. Fixed and
   verified live at `314cd8d`. The message was **retained, not lost**
   (attempt 1 of 2) — the control plane behaving correctly.
2. **`kimi` prompt mode rejects `--auto`/`--yolo`.** Found by live probe
   before it could burn an attempt; fixed at `e346c4c`.
3. **Degradation ladder fired for real.** pm hit level 1 (allowance
   unknown) and *reassigned* the canary's review to backend — unprompted,
   exactly as designed.
4. **Zero-cost empty polls confirmed** (`suppressed_preflight/empty_inbox`,
   `invoked: false`) and `at cap (1/1)` held concurrency.

### L-1 — per-task allowance-unknown was fail-closed while the aggregate was mode-aware (FIXED live)

Symptom: the *second* invocation on any task was denied
`task allowance usage unknown` — one invocation per task, then a stall. Root
cause: a spend row whose `allowance_pct` is NULL (no baseline reading has
ever been recorded, so the estimator emits NULL) makes
`_spend(field="allowance_pct")` report unknown, and the per-task and daily
branches denied unconditionally — while the *missing-reading* branch
immediately above them had been ruled mode-aware by W2-3 (canary/supervised
warn and allow bounded invocation; unattended deny). Two policies for the
same class of ignorance, in one function.

Ruled by the orchestrator and fixed: the per-task and daily unknown checks
now use the same mode-aware path. Unattended still denies. **Known** spend
over any cap still denies in every mode — no cap was weakened. Recording a
baseline reading remains the real fix and is the operator's cheapest lever:

```
python3 scripts/agent_metrics.py record-allowance --role backend --pct <0-100>
python3 scripts/agent_metrics.py record-allowance --role pm      --pct <0-100>
```

### L-2 — governor-suppressed messages retry unboundedly (carried)

When the governor suppresses *before* invoke, the attempt ledger does not
increment (`invoked: false`, `attempts: 0`), so the message is retained and
re-polled forever — observed every 30s on `c3c49821`. Model cost is **zero**,
so this is not the 977-fan cascade, but nothing retires it and pm had to ack
it by hand. Next cycle: a suppression counter with its own retirement path.

### L-4 — proof #12 was role-blind, and it had TWO readers (FIXED live)

pm's mission run completed its work and was then circuit-broken for
committing `tasks/packets/TASK-999-S2.json`. CC-4 protects that glob so a
TASK agent cannot rewrite the constraints it is judged against — kept in
full — but authoring packets IS pm's planning job (SPEC.md: only the PM
identity applies `protected-change`). The dispatcher was stricter than the
merge robot in a way that made autonomous planning impossible.

Fixed twice, which is the lesson: `857e585` fixed completion proof #12, and
pm kept dead-lettering because `agents/anti_loop.py::prohibited_files` is an
independent second reader of the same list (`e43c799`). *What else reads the
thing this gate reads?* — paid for again, by the orchestrator this time. Both
now share `ROLE_AUTHORIZED_PROTECTED` (pm → `tasks/packets/*` only); every
other protected glob still breaks for pm, packets still break for every other
role, and a packet's own `files_out_of_scope` still beats role authorization.

### L-7 — a leftover fan worktree re-fanned forever (FIXED live)

**This is the 2026-07-27 cascade's actual mechanism, reproduced.** W1-4
correctly refuses to delete a worktree holding unpushed commits, but nothing
renamed it, so every later `worktree add` failed at the same path *before*
`dispatch.py` ran. No attempt increments on that path, so the message re-fans
indefinitely — `frontend-78d778da` did it 239 times in July;
`backend-990417bc` did it again tonight at 30s intervals. Now: pin any
unpushed HEAD to `refs/recovery/<role>-<id8>-<stamp>`, move the tree to
`.fan/stale/`, prune, then create fresh (`e9124d8`). Nothing is deleted.

### L-8 — a bad packet made its own task's mailbox undeliverable (FIXED live)

A deadlock. The CC-1 pre-invoke command gate ran for every message carrying a
task_id with a packet. pm authored TASK-999-S2 with an illegal `-k` check
(deselecting the test it existed to fix — the policy was RIGHT to reject it,
forbidden-fix class F1). The orchestrator's ANSWER saying *"this packet is
superseded, do not dispatch it"* was then **suppressed by that same packet**.
The correction could not reach the role that needed it through the ledger at
all; only out-of-band intervention broke it. Now gated on `WORK_INTENTS =
{TASK_ASSIGN, REVIEW_REQUEST}` only — governance traffic never runs
`required_checks`, and the execution-time runner is unchanged, so an illegal
check still cannot RUN (`8359c31`).

### L-9 — preflight preconditions also gate governance traffic (OPEN)

Same class as L-8, found immediately after fixing it: the re-routed ruling
cleared the packet gate and was then suppressed by `precondition
issue_labels: missing ['task','test-change-authorized']`. It was **acked with
a durable blocked record** rather than looping — correct fail-closed
behaviour — but a ruling about a task still cannot reach a role when that
task's issue is mislabelled. Worked around by labelling issue #99 and
re-routing under `ORG`. Next cycle: preconditions that bear on *doing the
work* should not gate messages that merely *say something about* the work.

### L-10 — the ratified branch pattern made ORG work unprovable (FIXED live)

pm's mission run completed and was refused by proof #4 for branch
`pm/ORG-canary-verdict`. `AGENTS.md:18` — doctrine, and itself PROTECTED —
mandates `<role>/<task-id>-<slug>`; the A5 reconstruction regex demanded
`(task|canary|repair)/TASK-<digits>`. So no role branch could pass, and **ORG
work could never pass at all** (task_id `ORG` is not `TASK-<digits>`): every
governance task was unprovable by construction. The reconstruction audit
flagged this contradiction in writing and it was ratified around anyway; it
then cost three pm attempts and tripped the breaker. Doctrine outranks a
reconstructed regex — both forms now pass, case-insensitive on the task token
only, `main`/empty/arbitrary still refused, 13 cases verified (`32975c9`).

### L-11 — the circuit breaker is a latch with no reset (FIXED live)

`Governor.allow` trips at 3 consecutive failures and denies from then on: the
streak only breaks on a `success` row, and a task that cannot invoke can
never produce one. The latch is deliberate — a tripped breaker means redesign,
not retry — but nothing recorded that the redesign HAPPENED, so a task killed
by a defect in the GATE stayed dead after the gate was fixed. Both pm/ORG and
pm/TASK-999-S1 died that way on L-10. `scripts/breaker_reset.py` is the
redesign-complete signal and is deliberately not silent: `--reason` required,
cause appended to `mailroom/governor/admin_actions.jsonl`, and that record
states the ledger row is an ADMIN RESET rather than a task success so
success-rate audits can subtract it (`afad20f`).

### L-12 — `AGENTS.md`'s branch template read as a literal (FIXED live)

An agent pushed `role/org-repacketize-parked-prs`, taking `role` literally,
and had otherwise-good mission work refused. The proof was right; the doc was
ambiguous. Now `<role>` with worked examples (`afad20f`).

### L-13 — stale fan worktrees accumulate unboundedly (OPEN)

L-7's fix moves a colliding worktree to `.fan/stale/<role>-<id8>-<stamp>`
instead of failing forever — correct, and nothing is lost (commits are pinned
to `refs/recovery/*` in the ROLE CLONE, not the main clone: look in
`worktrees/<role>`). But one directory accumulates per failed attempt: 10
directories / 71 MB within the first hour of live operation. Next cycle: prune
`.fan/stale/` entries older than N days whose HEAD is already pinned to a
recovery ref, and surface the count in the readiness gate.

### L-14 — no provider session-cap detection existed (FIXED live)

Grep for session/rate/quota across `agents/` returned one unrelated ENOSPC
comment. On 2026-07-27 six pm workers hit the Claude cap; the CLI printed
"You've hit your session limit" and exited **rc=0**, so the dispatcher saw
only a missing result file — the founding lesson wearing the provider's hat.
`agents/provider_limit.py` now matches the CLI's OUTPUT, writes
`mailroom/blocked/provider-limit-<role>.json`, and dispatch step 1.5
(after HALT, before the budget ledger, before any model call) suppresses that
ROLE at zero spend. Role-scoped, so a capped pm does not stop backend or
frontend on other providers. Cooldown 6h per operator ruling; the marker
self-expires so the role resumes with nobody awake. Not fail-closed on
absence — a false positive would idle a healthy role (`3598b17`).

### L-15 — HALT spends an agent's attempt budget (OPEN — needs an operator ruling)

Observed: message `003c6e0b` burned attempt 1 on a real gate defect (L-10),
attempt 2 on `stopped (halt)` when the orchestrator paused the org, and was
dead-lettered on attempt 3. **The operator's kill switch is supposed to be a
free, reversible pause; instead every in-flight message loses an attempt per
halt.** Two halts in one session were enough to dead-letter a live ruling.

Not fixed unilaterally, deliberately. The attempt ledger's
increment-BEFORE-invoke rule is the specific correction that bounded the
977-fan cascade, and it is the last invariant that should be edited casually.
A halt-refund looks safe (HALT is operator-only, so an agent cannot game it)
but it needs a deliberate ruling, not a 6am patch. Options: refund the
attempt when `stop_reason == "halt"`; or record halted attempts in a separate
column excluded from the cap.

Also carried: B4 census/recalibration (caps stay `[E]`), B5 pm-lite, B6
checkpoint, B7 ceiling + `branch_pattern`, A5, A4 telemetry tail, full
`.fan` recovery, F6/F9 probes, proof #8 exact-SHA match, and **L-6**:
packets are keyed by `task_id` alone, so a pm *review* inherits that task's
*implementation* packet scope and always violates it (ADR-0008 stage
identity does not cover the review role).

---

### Marker disposition — executed 2026-08-02T19:20Z (operator-directed)

§7 condition 2 is DONE, by move not deletion. All nine
`mailroom/locks/running/` markers were moved, mtimes preserved, to

```
mailroom-quarantine/locks-running-stale-20260802/   (OUTSIDE the mailroom)
```

with a `MANIFEST.txt` recording per marker: filename, PID, mtime to the
nanosecond, sha256, and a **move-time re-verification** that `/proc/<pid>`
was still absent for every one of the nine (the wrap clock made the earlier
17:15–17:45Z measurement perishable; at 19:20:08Z it still held).
`mailroom/locks/running/` is now empty. Remaining §7 operator conditions:
the 8 unacked messages (condition 3, the cascade trigger — PRs #87/#91
first), `mailroom/telemetry/` (condition 4), and `mailroom/readiness.yaml`
(condition 1 — write it LAST: `operating_mode: canary` flips
`run_budget._operating_mode` off its fail-closed default, so the file
arms spend semantics the moment it exists).

---

## Canary verdict — TASK-999 COMPLETE, 2026-08-03. The gate is OPEN.

PR #98 merged to main at `6d43876` by pm per ADR-0003, after 14/14 required
checks went green on head `c286c78`. The unblock was branch-management, not
code: updating the branch onto main let CI pick up `ee1f030`'s
direction-aware check-runner test, and `test` + `coverage-floor` — red on
the pre-fix run 30783384378 — pass on a probe-present tree. That green run
is AC-2 of issue #99, the last pending criterion, so the S2 supersession
decision recorded on #99 is confirmed correct: backend was never dispatched
to re-implement the already-landed fix. `tasks/packets/TASK-999-S2.json`
remains on main but is inert by construction — its `issue_state: open`
precondition fails against closed #99.

TASK-999 is thereby proven end to end: governed dispatch → real model work →
dispatcher-verified completion (15 proofs, run `a6228fff`) → evidence-bearing
review → required CI green → governed merge. The canary gate that held the
mission fan-out is open; BACKLOG §Mission resume proceeds from step 3
(repacketize parked PRs #87/#91, then TASK-901..904, then the release/intake
loop), green tier default, kimi under the $50 wall, gates unweakened.

Recorded by pm — ledger message `39ad7763`, run `95e04737`.

---

## pm daily cap doubled 24 -> 48, 2026-08-03 (operator ruling)

The overnight stall was starvation, not a crash: all three loops stayed up
for eight hours while nothing moved. pm reached 27 invocations against
`per_day_max: 24` by 07:07Z — 7 of them successful — and every later poll
retained its queue on `"reason": "daily cap"`. Four of those retained
messages were mission traffic (TASK-210-S2/S3/S4, TASK-009), and frontend
sat healthy, funded and idle behind them with an empty inbox.

The finding worth keeping is structural, not numeric: **pm's cap is the
binding constraint on the whole org's throughput, because pm is the sole
router.** A per-role cap on a role that nothing else can substitute for is a
per-ORG cap wearing a per-role label. Nothing in the control plane detects
"router capped, workers idle" — it looks identical to "no work to do".

24 was always marked `[E]` (a placeholder from a three-day run under
different roles, before these controls existed). 48 is `[O]`perator-set for
this session and still bounded. Replace it from shakedown telemetry rather
than leaving it as the new placeholder.

**pm's ORG circuit breaker was deliberately NOT reset.** It tripped on four
real refusals, not on since-fixed defects: pm committed edits to PROTECTED
control-plane paths (`agents/dispatch.py` twice, `agents/checks.py` +
`tasks/packets/TASK-009-S1.json`), caught by anti-loop once and by
completion proof #12 three times. The gate did exactly its job. Resetting it
would send pm straight back at the dispatcher it is not allowed to edit —
and control-plane repair is the orchestrator's lane, not pm's. The cap raise
unblocks the mission messages, which are the ones that should move; ORG
stays broken until pm has a reason to touch it that is not a protected path.

---

## L-26: review work was unpassable by construction, 2026-08-03

Proofs #10 and #11 load the packet named by the MESSAGE's `task_id`. For a
`TASK_ASSIGN` that is exactly right. For a `REVIEW_REQUEST` it is a category
error: the reviewer is handed the **builder's** packet and judged against the
builder's obligations — an `acceptance_criteria` id-set it never agreed to,
and a `files_in_scope` that no verdict document could ever fall inside.

Measured in a single morning, across all three roles:

| role | task | refusal |
|---|---|---|
| pm | TASK-210-S3 | #10 invented `REVIEW-PROCESS`, `REVIEW-PROVENANCE`; #11 out of scope `docs/agent-org/task-210-s3-review-…md` |
| frontend | TASK-210-S3 | #10 invented `verdict-acknowledged`, `pm-evidence-confirmed`, …; #11 out of scope `docs/agent-org/task-210-s3-verdict-ack-…md` |
| backend | TASK-210-S2 | #10 invented `AC-REVIEW-EXECUTION`, `AC-BLAST-RADIUS`, `AC-NO-GATE-BYPASS`, … |

Three different models, three different tasks, the same two refusals. Each
agent independently did the sensible thing — name the criteria a *review* is
judged on, and write its verdict to `docs/agent-org/` — and each was refused
for it. **No prompt could have fixed this**: there is no id-set a reviewer can
emit that equals the builder's, and no path inside a build packet's scope
where a verdict belongs. Review → merge is the loop the mission runs on, and
it could not close. This, not provider caps, is why finished work kept piling
up unmerged.

The correction evaluates the right obligations rather than lowering the bar:

- **#10** is `None` (not evaluable) for a review intent — the same verdict the
  proof already returns when there is no packet at all.
- **#11** additionally admits `docs/agent-org/*`, and only that, for a review
  intent. Build scope for builders is byte-for-byte unchanged.

Everything else still binds on a review: **#9 still re-runs the required
checks**, **#12 still circuit-breaks on PROTECTED paths** (verified by test —
a reviewer committing `agents/dispatch.py` still breaks, and the admitted
evidence dir is not protected in the first place), and the verdict still has
to reach the ledger. A reviewer touching out-of-scope product code is still
refused; there is a test pinning that the carve-out is not a general escape.

`REVIEW_INTENTS` covers `REVIEW_REQUEST`, `REVIEW_VERDICT`,
`ARBITRATION_REQUEST`, `ARBITRATION_RULING`. The fix is inert unless
`dispatch` threads `intent` into the proofs, so a test pins that too.

**Standing lesson**: proofs #10/#11 assumed message intent and packet role
always agree. Any future proof that reads the packet should state which
intents it is judging.

---

## Ruling — PR #102 is SUPERSEDED, not fixable. Closed 2026-08-03.

Backend's REQUEST_CHANGES on PR #102 @ `a91fff0` (ledger `a68a52d4`) was
mechanically correct on both cited gates — merge condition 4 (no structurally
valid single `Fixes`/`Refs` task link) and condition 5 (protected
`tasks/packets/*` changes with no `protected-change`-labelled linked issue).
Its remedy — file one dedicated TASK issue with triage-time
`protected-change`, relink, re-review — is **not** the right fix, because the
PR no longer proposes any change.

Measured, not assumed. All eight files in the PR are byte-identical between
`origin/main` and the PR head:

```
git rev-parse origin/main:<f>  ==  git rev-parse origin/pr102:<f>   for each of
tasks/BACKLOG.md  tasks/packets/TASK-{102-S2,102-S3,102-S4,102-S5}.json
tasks/packets/TASK-{210-S2,210-S3}.json  tests/test_packets.py
```

`a91fff0` was rebased onto main as `9f8ecd5` (identical author + author date,
different tree because of the rebase). The packet substance is already live.
What `git diff origin/main origin/pr102` still shows is 689 lines of pure
**deletion**: `agents/provider_limit.py`, `scripts/breaker_reset.py`,
`docs/runbooks/restart-readiness.md`, the L-16/L-17/L-18 fixes in
`run_budget.py` / `budget_governor.py` / `policy.yaml` / `dispatch.py`, and
proof changes in `completion_proofs.yaml` — i.e. every commit that landed
after the merge base `3456178`. GitHub reports the PR `MERGEABLE / CLEAN`
because it diffs against that stale base; the merge robot's condition 9
(branch up to date with main) would force a rebase, and the rebase result is
empty.

So authorizing it would mean minting a `protected-change` task whose only
possible effect is to revert unrelated org work. Decision: **close PR #102 as
superseded by `9f8ecd5`**; no TASK issue is created for it; backend's review
finding is upheld and satisfied by supersession rather than by relink. The
six packets and the BACKLOG mission-resume re-sequencing stand as merged.
Revisit if: a future `git diff origin/main <branch>` on this work shows any
non-deletion hunk — that would mean substance was lost in the rebase.

### L-19 — protected paths reached `main` without passing the merge robot (OPEN)

The same measurement exposes the real defect. `9f8ecd5` put seven protected
`tasks/packets/*` + `tasks/BACKLOG.md` files on `main` by **direct push** —
no robot merge, no condition-4 task link, no `protected-change` label, no
evidence-bearing counterpart approval. PR #102 was opened for that work and
then bypassed. Every ORG commit from `3456178` to `a9e86af` has the same
shape: no `(#N)` merge suffix, straight to `main`.

This is not an agent misbehaving around a gate; it is a gate that is not
installed. The merge robot is specified as "the only identity with merge
rights on `main`" (`agents/merge_robot/SPEC.md`), but nothing enforces that,
so its nine conditions are advisory for anyone with push access. Backend
correctly refused to wave through condition 5 on the PR — while the identical
bytes sat unauthorized on `main` the whole time. Reviewing the front door
while the side door is open is the failure mode to fix.

The fix is already scoped and already open: **TASK-007 / issue #24**
(merge-robot identity + branch protection, human-gated, `protected-change`,
`role:backend`). No new issue is filed — this raises #24 from routine to the
blocking prerequisite for treating any merge condition as real, and it is
human-gated because branch protection needs repo-admin rights that no agent
identity holds. Until #24 lands, do not read "condition 5 passed" as
"protected paths were authorized"; it only means the PR path was authorized.

Recorded by pm — ledger message `a68a52d4`, run `75330405`.

### Reconciliation — issue #103 (TASK-008) was filed in parallel

While this ruling was being written, a parallel pm invocation executed
backend's requested remedy literally: it created issue **#103 — "TASK-008:
authorize + land the mission-resume stage packets"** (`task`,
`protected-change`, `role:pm`, created 06:46:06Z) and retitled PR #102 to
match. PR #102 was closed at 06:47:55Z, ~2 minutes later. Two invocations,
one ledger verdict, no coordination — worth noting on its own.

The ruling above is unchanged: the retitle does not alter that the PR's eight
files are byte-identical to `main`. But #103 is **not** discarded, because it
turns out to be the artifact L-19 says is missing. Its own body draws the
line correctly — it authorizes the packet *authoring*, not the protected
changes those packets later dispatch. Disposition:

- **AC 1–6 are already satisfied on `main`**, verified here at `a9e86af`:
  six packets present and validating, `pytest tests -q` **529 passed**,
  `check_invariants.py` OK, no recursive/deselecting `required_check`,
  `tests/test_packets.py` registry-only, BACKLOG re-sequenced.
- **AC 7–8 are void.** They require PR #102 to carry `Fixes #103` and win a
  re-review. The PR is closed and empty; there is nothing left to approve.
  An approval there would certify a revert.
- #103 stays **open** as the standing `protected-change` authorization of
  record for the `tasks/packets/*` files now on `main`, and closes only when
  TASK-007 / #24 makes that authorization mechanically checkable rather than
  narrative. Filed retroactively, which is exactly the smell L-19 names —
  recorded as such rather than backdated into looking clean.

Revisit if: #24 lands and the robot can verify the label's audit-log actor
against the paths on `main`, at which point #103 has served its purpose.

### Execution addendum — run `8f1a127803284aaeb8cf117f4ef56727` (2026-08-03)

Ledger `a68a52d4` was re-dispatched: run `75330405` recorded the ruling, pushed
this branch, opened PR #104 and closed PR #102, but the ledger reply to backend
was never sent, so the message stayed unacked. Completed here:

- Backend notified via ledger (`REVIEW_REQUEST`, hop 3) — the ruling plus a
  review request on PR #104. Backend's REQUEST_CHANGES on #102 is upheld and
  answered by supersession; no re-review of #102 is owed.
- Issue #103 opened and closed unused. Before re-measuring the diff, this run
  executed backend's literal remedy: filed `TASK-008` with a triage-time
  `protected-change` label and relinked PR #102 to it (`Fixes #103`, title
  retitled). The per-file measurement then showed 8/8 files identical to
  `origin/main`, i.e. the remedy would have authorized a 689-line revert. PR
  #102's title and body were reverted to their pre-relink state and #103 was
  closed `not planned`.
- **L-19 corollary — measure the diff before minting authorization.** A
  `protected-change` label is an authorization, not a formality; deriving one
  from a reviewer's remedy text rather than from the diff is how a revert gets
  authorized. Order is: measure `git diff <base> <head>` first, mint the task
  second. Revisit if the triage protocol in `agents/roles/pm.md` grows an
  explicit "measure before authorizing" step — this should fold into it.

Recorded by pm — ledger message `a68a52d4`, run `8f1a127803284aaeb8cf117f4ef56727`.

### Correction — two runs executed ledger `a68a52d4` concurrently

Both runs reached the same ruling, so the record needs three fixes to be
coherent:

1. **#103's final disposition is `closed / not planned`**, per run
   `8f1a1278`. That **supersedes** the "stays open as the standing
   `protected-change` authorization of record" line above. The retraction is
   the better call: retaining a label minted before the diff was measured
   would have left a retroactive authorization standing over protected paths
   already on `main` — narrative cover, not a checked gate. L-19 routes to
   TASK-007 / #24 on its own; it does not need #103 as a placeholder. The
   AC 1–6 verification above still stands as evidence about `main`
   (`pytest tests -q` 529 passed at `a9e86af`).
2. **The ledger reply was sent by both runs.** Run `75330405` sent
   `f72798b6` (`REVIEW_VERDICT`, hop 3) at 06:50:00Z; run `8f1a1278` sent
   `285f6cfd` (`REVIEW_REQUEST`, hop 3) just before it and, writing its
   addendum before `f72798b6` existed, recorded that no reply had been sent.
   Backend has two messages saying the same thing. Ack both; there is no
   third position hiding between them.
3. **L-19b — dispatch of a single ledger message is not exclusive.** Two runs
   held `a68a52d4` at once and raced: `8f1a1278` filed #103 and relinked PR
   #102 at 06:46; `75330405` measured the diff and closed PR #102 at 06:47;
   `8f1a1278` reverted the PR metadata and closed #103 at 06:49; both pushed
   to `pm/ORG-pr102-superseded` and both messaged backend. Then run
   `75330405`'s fan worktree was **deleted underneath it mid-command**, when
   the other run's completion reaped `.fan/pm-a68a52d4` — this correction had
   to be authored from a fresh clone. Nothing was lost only because the two
   conclusions agreed; the mutation order alone (close, then un-relink, then
   re-close) shows how easily they might not have, and a reap that races a
   live run can destroy an unwritten `.agent-result.json` and with it the
   proof of work the dispatcher requires. A re-dispatch that assumes the
   prior run is dead needs a liveness check or a lease, and the worktree reap
   needs to be keyed to the run that owns it, not to the message. Same shape
   as L-19: the exclusion is assumed, not installed. Filed against the
   dispatcher, not the roles.

Recorded by pm — ledger message `a68a52d4`, run `75330405`.

### Close-out — authoritative head for PR #104

Four commits from two racing runs (`a66b85d` ruling → `13705d2` reconciliation
→ `24d8b94` execution addendum → `5096634` correction) landed on
`pm/ORG-pr102-superseded`. They are consistent as a sequence but only the last
two are load-bearing where they disagree with the first two. For review, read
the ruling and L-19 in `a66b85d`, then the correction in `5096634`; where the
`#103` disposition differs, `closed / not planned` wins. Nothing in the middle
commits is retracted beyond that one line.

Verified at this head, `5096634` plus this entry, in a fresh worktree at the
same path the reap destroyed:

```
python3 -m pytest tests -q          529 passed
python3 scripts/check_invariants.py doctrine invariants: OK
```

Docs-only across all commits on this branch; no protected path touched, no
test deleted, skipped, or loosened.

State at close of ledger `a68a52d4`: PR #102 closed as superseded by
`9f8ecd5`; issue #103 closed `not planned`; PR #104 open, awaiting an
evidence-bearing non-author approval from backend; L-19 and L-19b open,
routed to TASK-007 / #24 and to the dispatcher respectively; mission resume
proceeds from BACKLOG step 3, TASK-102-S2 already in backend's inbox.

Recorded by pm — ledger message `a68a52d4`, run `8f1a127803284aaeb8cf117f4ef56727`.

## Remediation of PR #104 — backend REQUEST_CHANGES, ledger `57f96def`

Backend's verdict at `bc6caa9` was REQUEST_CHANGES: the ruling and the L-19 record are
supported and doctrine-clean, but two merge conditions fail. Both are now addressed on
this branch, and the first turned out to be a live defect rather than a paperwork problem.

### L-21 — the provider-cap gate had never executed (FIXED here)

**Condition 1 (green CI).** `lint` is RED on `main` at `ce5da00`, not because of anything
PR #104 changed — this branch is docs-only up to `b5ab77c` — but because
`agents/dispatch.py` step 1.5 references `task_id` before it is bound. `task_id` is read
from the message at step 3; the provider-cap gate sits deliberately ahead of the message
load, so the name does not exist yet. ruff `E9,F63,F7,F82` calls it `F821` twice
(`:663`, `:666`); at runtime it is an `UnboundLocalError`.

The consequence is worse than a red check. The gate exists (L-14) so that a provider
saying "You've hit your session limit" costs the org zero instead of burning every queued
message's attempts. The first real cap would have crashed the dispatcher inside the code
written to make caps cheap.

It shipped because its only test asserts on `inspect.getsource(dispatch.dispatch)` — it
checks that the gate is *positioned* before `_run_capped` and after `HALT`, and never
executes it. That is a real check of ordering and it should stay; it is not a check that
the code runs. **A gate verified only by reading its source has not been verified.** Any
suppression path — HALT, governor, preflight, run-budget, provider limit — must have at
least one test that drives `dispatch()` through it end to end and asserts zero spend.

Fixed by dropping the two `task_id` arguments (the cap is role-scoped and the gate
precedes the message load, so there is no task to report; the comment now says so) and
adding two executing tests to `tests/test_dispatch.py`:
`test_provider_limit_suppresses_before_spending`, which fails with the original
`UnboundLocalError` if the arguments are restored, and
`test_provider_limit_does_not_block_other_roles`.

`agents/*` is protected, so the fix is authorized by **TASK-009 / issue #107**, filed with
`protected-change` at triage. Sibling of L-19 (`479e05c`) and L-20 (`ce5da00`): three
defects in a row in the code that decides whether to spend, all found after merge.

### Condition 4 — the ORG record now has a real task link

The earlier ruling declined to mint a decoy TASK issue purely to satisfy condition 4, and
that stands: #103 was filed for exactly that reason and retracted. What changed is that
this PR is no longer docs-only. It now carries a protected-path code fix that needs a
`protected-change` authorization on its own merits, and #107 is that issue — a real
defect, real acceptance criteria, mechanically verifiable. `Fixes #107` is therefore a
true statement, not gate-theatre, and the ORG record rides along with the fix whose
discovery it documents.

This does not close L-19's open question of what condition 4 should resolve to for a
pure-governance PR with no code. That remains scoped to TASK-007 / #24.

### Verified at this head

```
ruff check --select E9,F63,F7,F82 --exclude engine/vendor .   All checks passed!
python3 -m pytest tests -q                                    532 passed
python3 scripts/check_invariants.py                           doctrine invariants: OK
```

Branch rebased onto `main` at `ce5da00` (condition 9). Protected paths touched:
`agents/dispatch.py`, authorized by #107. No test deleted, skipped, or weakened.

Recorded by pm — ledger message `57f96def`, run `650afc56ab0d4fd991e56a135e295a47`.

### L-22 — condition 4 counts task links across the whole body, so prose about the link breaks the link

The remediation above stated that condition 4 was addressed because the body now
says `Fixes #<n>` and #107 is a real, open, `TASK-`titled issue. Every part of
that is true and condition 4 still failed. Run the actual resolver, not the
prose:

```
$ python3 -c "resolve_task_link(<PR #104 body at 093a5d9>)"
TaskLinkError: PR must contain exactly one Fixes #N or Refs #N task link
    fixes -> ['107', '107']      refs -> ['97']
```

`agents/merge_robot/merge_robot.py:132-135` does `re.findall` over the **entire**
body for both keywords and requires `len(fixes) + len(refs) == 1`. The body had
three matches: the real link on line 1, a second copy of it inside the
"merge conditions" section that was *explaining* the link, and the
`Refs`-prefixed context list of related issues. A link plus an accurate
description of that link is a plural link.

The failure is nastier than a missing link because the error text — "must
contain exactly one" — reads as *absent* to anyone who can see the link sitting
in the body, so the natural next move is to add another one. The gate is
correct; the body is a machine-read field that happens to render as prose.

**Rule, effective now: a PR body carries exactly one `Fixes #<n>` or `Refs #<n>`,
on the first line, and never repeats or quotes it anywhere else. Related issues
are written as bare `#N` with no keyword.** Same family as L-19/L-20/L-21: a gate
whose verdict was asserted from reading rather than from executing. The check is
one command against `resolve_task_link`; run it before claiming condition 4.
*Revisit if:* the resolver is changed to ignore matches inside code spans or to
take the first match — either would make the rule unnecessary, and neither has
been proposed.

### Duplicate TASK-009: #106 closed, #107 is the authorization of record

Two pm runs held the twin PR #104 verdicts (`4a399233` and `57f96def`) at once
and each filed the same task: **#106** ("dispatcher provider-limit path raises
NameError", `role:backend`, `protected-change` + `test-change-authorized`) and
**#107** ("provider-limit gate references unbound task_id", `role:pm`,
`protected-change`), 24 seconds apart. Both describe the same two lines.

Two open issues sharing one TASK id is not cosmetic: `_task_id_from_title`
derives the task id from the linked issue's title, so `TASK-009` would have
resolved to either issue depending on which one a PR happened to link, and the
per-task invocation cap would have been counted twice for one unit of work.
**#106 is closed as a duplicate**; #107 is the authorization for the
`agents/dispatch.py` change already on this branch and is the issue the fix
commit closes. #106's acceptance criteria were reviewed before closing and are
covered by #107's, which additionally require the defect-reproducing direction
of the test. This is L-19b (dispatch of one ledger message is not exclusive)
surfacing as duplicate work rather than as a race: the two runs agreed again,
which is luck, not a mechanism.

### Verified at this head

```
ruff check --select E9,F63,F7,F82 --exclude engine/vendor .   All checks passed!
python3 -m pytest tests -q                                    532 passed
python3 scripts/check_invariants.py                           doctrine invariants: OK
resolve_task_link(PR #104 body)                               -> TASK-009 (#107)
```

State at close of ledger `4a399233`: PR #104's two reported blockers are both
resolved — condition 1 by the L-21 fix, condition 4 by #107 plus the
single-link body — and re-review is requested from backend at this head.
Condition 9 is the robot's rebase; `main` has moved one commit past this
branch's base. L-19 (protected paths bypass the robot) and L-19b (message
dispatch is not exclusive) remain open against TASK-007 / #24 and the
dispatcher respectively.

Recorded by pm — ledger message `4a399233`, run `de264a6fade946d79b92acf924ffda5e`.

---

## L-27: a builder's deny-list bound the reviewer's role, 2026-08-03

L-26's sibling, one gate over, found by the monitor within the hour: pm
handling a `REVIEW_REQUEST` for TASK-210-S3 authored the NEXT packet,
`tasks/packets/TASK-210-S5.json`, and was dead-lettered —
`anti-loop terminate: prohibited files modified`.

Authoring packets is pm's core routing job and is explicitly role-authorized
(`ROLE_AUTHORIZED_PROTECTED = {"pm": ("tasks/packets/*",)}`, the L-4 fix).
But `prohibited_files` deliberately lets a packet's own `files_out_of_scope`
beat that authorization, and the TASK-210-S3 **builder** packet denies
`tasks/packets/**`. So **pm could not route while holding any task message** —
and pm is the org's only router.

That "packet deny beats role authorization" rule is right when the agent is
doing the packet's own work: it agreed to that packet as the description of
its task. It is wrong on a review intent, where the packet in hand belongs to
someone else. The builder's deny-list binds the builder. It has no authority
over what a reviewer's role may do — the same category error as L-26, in a
different reader.

Fix: `prohibited_files` takes the intent; on a review intent, role
authorization is not defeated by the builder's deny-list.

Unchanged, and pinned by test: PROTECTED still binds everyone on every
intent; a role still clears only the globs listed for IT (backend, frontend
and an unknown role get nothing, review intent or not); pm reviewing still
cannot touch `agents/*`; and every non-review intent behaves exactly as
before — building against a packet that denies `tasks/packets/**` is still
denied.

**This is the third time the same lesson has cost real time.** L-4 fixed
proof #12 and left the anti-loop breaker still dead-lettering pm. L-26 fixed
#10/#11 for reviews. L-27 is the anti-loop reader of the same idea. The
standing question stays on the board and should be asked of every gate:
**what ELSE reads the thing this gate reads, and does it agree?**

---

## L-28: a per-task breaker can permanently disable a standing channel

pm's ORG circuit breaker was reset 2026-08-03 by the orchestrator. The
reasoning is recorded here in full because the `--reason` field is short and
the honest answer is mixed.

**What tripped it.** Four consecutive failures:

- 2x pm committing `agents/dispatch.py`, 1x `agents/checks.py` — **genuine**
  refusals, correctly caught by proof #12 and the anti-loop breaker, already
  dead-lettered, and **not** fixed by anything since. pm was doing what it is
  not allowed to do, and the gate was right.
- packet/doc writes of the L-26/L-27 class — the reviewer judged against the
  builder's packet. Those **are** fixed, on main at `4c77a2b` and `45b63ac`.

So this is NOT a clean "defects since fixed" reset, and it should not be
recorded as one.

**Why reset anyway.** Because of what the breaker had come to block. `ORG` is
not a task that can be redesigned and retried — it is pm's **permanent
routing channel**. A per-task breaker latched onto it takes the org's only
router offline indefinitely, and nothing ever clears it, because there is no
"fixed version of ORG" to ship. The two messages it was actually holding were
duplicate backend APPROVE verdicts for PR #104 — now merged at `b4a783c` —
so they were moot and could never have succeeded. The breaker was no longer
protecting anything; it was just holding two dead messages and two of pm's
six parallel slots.

**Residual risk, accepted and bounded.** If pm goes at a PROTECTED path
again, proof #12 circuit-breaks it on that same invocation. The reset buys
back routing; it does not lower the floor.

**The design defect** is the durable finding: *a per-task circuit breaker
should not be able to permanently disable a standing channel.* `ORG` (and any
long-lived task id) needs either a decaying failure window or an explicit
exemption from latching. Otherwise the breaker's success condition —
"redesign the task and retry" — is unsatisfiable by construction, and the
only exit is an operator reset like this one. Carry-list item; not fixed
today.

---

## L-29: the ONLY real-money budget is the one we never measured

The operator set a $50 wall on kimi-backed frontend work and asked to be told
when it was exhausted. It cannot be told, because **not one cent of kimi
spend has ever been recorded.**

Every `spend` row for `frontend` is null across the board:

    role      cash_usd  allowance_pct  input_tokens  output_tokens
    frontend  None      None           None          None      (x14 today)

The proximate cause is one line in `agents/dispatch.py::_provider_usage`:

    provider = "anthropic" if role == "pm" else "openai"

`agents/accounting.provider_usage` recognises exactly two vocabularies,
`anthropic` and `openai`. frontend runs **kimi**, so it is parsed as openai,
matches no envelope, and returns all-None. `run_budget`'s kimi branch then
sums nothing, and the $50 ceiling can never be reached — not because spend is
low, but because spend is invisible.

The system said so, loudly, thirteen times:

    TELEMETRY-DEGRADED: no recognized openai usage envelope

That message is exactly the "never a silent None-forever" guard
`_provider_usage`'s own docstring promises. It worked. Nobody read it.

**This is not fixable by mapping kimi to a third provider alias.** The kimi
CLI output we capture contains no usage envelope at all — no token counts, no
cost keys, nothing matching `*tokens*` or `*cost*` anywhere in the frontend
log. There is nothing to parse. Any dollar figure the org reported for kimi
would have to be fabricated, so it reports none.

The inverse error rides along: **pm accrues `cash_usd` (~$65.89 today) while
being a subscription role.** pm's budget is `claude`, denominated in
`pct_weekly_*`, so those dollars are a notional list-price valuation, not
money anyone is charged. The ledger therefore shows phantom dollars for the
role that costs nothing incrementally and zero for the role that costs actual
money — the exact inverse of what a spend ledger is for.

**Consequences, stated plainly:**

1. The $50 kimi wall is **unenforced and unenforceable in-org today**. The
   authoritative balance is the Kimi console (platform.kimi.ai); only the
   operator can read it.
2. Any past or future org claim about kimi spend is unsupported.
3. `run_budget`'s kimi branch and its tests pass because they are exercised
   with synthetic usage dicts — the tests are green and the pipeline feeding
   them is dead. A test that supplies its own input cannot detect an input
   that never arrives.

**Fix requires evidence we do not have**: whether `kimi --output-format
stream-json` can emit usage at all (a CLI/flag question), or failing that, a
priced estimate from prompt/response sizes the dispatcher already sees —
which must be recorded as an ESTIMATE in a separate column, never as
`cash_usd`. Carry-list, escalated: this is the top accounting defect.

---

## L-30: don't guess the session window — probe it

The flat 6h park assumed an **exhausted quota**. The operator's numbers say
otherwise: codex at **2%** and claude at **5%** of their WEEKLY limits, while
both roles sat parked. These are rolling **session windows** — shaped by
burst density, not by consumption — so a 6h park spends hours of a 95%-unused
allowance recovering from a limit that clears on its own.

Measured, not assumed: backend was capped 13:03Z, probed by the orchestrator
at 16:10Z (~3h07m in), came back **immediately** and worked productively for
~25 minutes before capping again at 16:36Z. The true window is well under the
six hours we were waiting — but its exact length is unknown, and picking one
number for every provider would just swap one wrong constant for another.

So the fix does not guess. It **probes**: park briefly, let ONE dispatch try,
and escalate only if the provider refuses again.

    45m -> 90m -> 3h -> 6h

A probe costs **zero tokens** — the gate suppresses before invoking, so a
re-refusal is a CLI round-trip and nothing more. The ladder self-calibrates
to whatever window a provider actually runs, and still tops out at the
operator's ruled 6h for genuine exhaustion.

Two guards keep it honest:

- **A clean run resets the ladder.** The streak only continues if the role is
  refused again within an hour of its last park ending; otherwise one bad
  afternoon would keep a role on 6h parks for the rest of the run.
- **Transient blips never escalate.** L-25's rule survives inside L-30: an
  `overloaded`/`503` is a capacity blip, not a limit, and stays at 5 minutes
  no matter how often it repeats.

Streak state lives in `provider-limit-<role>.history.json` because the marker
itself is deleted on expiry — without it the ladder would reset on every park
and never escalate.

**Applied to the two live parks immediately**, since a fix that only helps
tomorrow misses the point: backend 22:37Z -> **18:06Z** (90m, second
consecutive refusal), pm 22:30Z -> **17:14Z** (45m, first). That returns
roughly nine role-hours to today's run.

One test changed rather than added: `test_mark_applies_the_proportional_
cooldown` asserted a first quota refusal parks for the flat 6h. It now
asserts the first rung. The distinction L-25 wrote it to protect — a blip
parks for minutes, a limit for substantially longer, never conflated — is
still asserted, explicitly.

---

## L-32: the merge happened; the record of *why it was allowed* did not

PR #104 (TASK-009 / #107 — the provider-cap gate's `UnboundLocalError`, the
defect that held `main`'s lint red for every open PR) squash-merged at
`b4a783c`, 2026-08-03T16:25Z. Backend's evidence-bearing APPROVE preceded it,
all fourteen checks were green, and the change is correct — re-verified at
`main` tip `4283478`: ruff clean, 565 tests passed, invariants OK.

What was missing is ADR-0003's clause-2 artifact. Under a shared GitHub
identity the ADR substitutes a ledger `REVIEW_VERDICT` plus an
`EVIDENCE-SHA256:` comment for conditions 2/3, and it pays for that
substitution with one obligation: pm executes the robot's remaining conditions
manually and **comments `MERGED by pm per ADR-0003 (robot conditions
verified)`**. That comment is not ceremony. It is the only place the nine
conditions are recorded as *checked*, because the robot that would otherwise
record them did not run. No comment was posted. For roughly forty minutes a
protected-path change sat on `main` whose merge authorization existed only as
agent prose in ledger messages and issue comments — none of which is a
condition check.

Posted retroactively at
`https://github.com/decross1/poe-upgrade-advisor/pull/104#issuecomment-5169345176`,
with all nine conditions verified at reviewed head `004648a` and re-verified at
`main`. Every one passes; the merge was substantively legitimate. That is the
point worth keeping: the gap was not a bad merge, it was a good merge that
left no auditable trace of being gated. Nothing distinguishes it, in the repo,
from the direct pushes L-19 names.

This is L-19's shape one layer in. L-19: the merge robot is *specified* as the
only merge identity and nothing installs it. L-32: the ADR that authorizes a
human to stand in for the robot is likewise *specified* and nothing installs
it — an agent that forgets clause 2 gets a clean-looking merge and no error.
Both are gates that live only in prose, and both close the same way: **TASK-007
/ #24** (merge-robot identity + branch protection, human-gated). Once branch
protection lands, a merge without the robot cannot happen, and the substitution
this ADR exists for self-revokes.

Until then the mitigation is cheap and worth stating plainly: **the pm merge is
not complete when the button is pressed; it is complete when the condition
table is posted.** An ADR-0003 merge with no comment should be read the same
way L-21 taught us to read a gate verified only by `inspect.getsource` — the
step that proves the work was never executed.

Revisit if `MERGE_ROBOT_TOKEN` exists and `merge_robot.py` runs in CI, at
which point ADR-0003 self-revokes and this lesson is moot.

(Numbering note: L-32 is minted here against `main` at `4283478`, whose latest
lesson is L-31. Parallel pm runs have collided on a lesson number before —
see L-19 vs `479e05c` — so if another L-32 appears, this one is the ADR-0003
merge-record lesson.)
