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
