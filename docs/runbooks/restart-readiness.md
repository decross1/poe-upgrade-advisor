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
