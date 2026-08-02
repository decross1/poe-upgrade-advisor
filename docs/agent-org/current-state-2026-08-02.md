# Current operating state — 2026-08-02

**Phase 0 deliverable** of the PoE Upgrade Advisor Autonomous Organization
Restart Program v1.0. Establishes authoritative current state *before* the
control plane is edited.

**Baseline:** `main` @ `a04c8b3`, clean, in sync with `origin/main`. This is the
program's stated audit baseline (`a04c8b35df74…`), so the HANDOFF §8 rule-7
"repository state contradicts §1, stop" condition does **not** trigger.

Evidence tags: `[O]` observed directly · `[E]` estimate with stated arithmetic ·
`[A]` assumption, not measured truth.

---

## 1. Freeze status

| Check | State | Evidence |
|---|---|---|
| `mailroom/HALT` present | **yes**, 0 bytes, mtime 2026-07-27T22:07 | `[O]` |
| `flock` free for `pm`, `backend`, `frontend` | all three free — no loop running | `[O]` |
| Live loop / postmaster / governor processes | **none** | `[O]` `ps aux` |
| systemd user units that can invoke a model | **none**. `poe-upgrade-bot.service` is active but is the Discord intake bot (`bot/bot.py`), not an agent loop | `[O]` |
| cron entries | none | `[O]` |
| Stale markers in `mailroom/locks/running/` | **9**, every PID confirmed dead | `[O]` |

The org is halted. Nothing on this host can currently invoke a model
autonomously.

**Authoritative launcher: `scripts/agent_loop.sh`.** `agents/postmaster/
postmaster.py` is invoked by nothing in the repository; ADR-0002 records it as
superseded by the ledger transport. `[O]`

---

## 2. The central finding — the loop was ~20× worse than documented

Every prior document in this program states the largest waste event as
"**~50 burned invocations**" from the 2026-07-27 `acceptEdits` incident. The
logs on this host say otherwise. They were unavailable to the earlier analyses
(`HANDOFF` §9 open question 3 flags exactly this gap).

### 2.1 Invocation census, from `mailroom/logs/*.log` `[O]`

| Role | Fan invocations | Heartbeat invocations | Total |
|---|---:|---:|---:|
| `pm` | 980 | 0 | 980 |
| `frontend` | 258 | 12 | 270 |
| `backend` | 88 | 70 | 158 |
| **Total** | **1,326** | **82** | **1,408** |

### 2.2 How many of those were redeliveries of the same message `[O]`

`pm` — six message IDs account for **977 of 980** invocations:

| Message | Invocations |
|---|---:|
| `0fc1b84f` | 180 |
| `67cefe20` | 177 |
| `9c496f1f` | 175 |
| `733e57a0` | 175 |
| `63719892` | 170 |
| `11536792` | 100 |
| `fafc491e` | 3 |

`frontend` — four message IDs account for **180 of 258**: 59, 58, 33, 30.

`backend` — **zero redeliveries.** Every message invoked exactly once. The
backend lane was healthy throughout.

### 2.3 The confirmation

The seven message IDs that appear in `pm.log` are **exactly** the seven
messages still unacked in `mailroom/cursors/pm.acked` today `[O]`:

```
0fc1b84f  11536792  63719892  67cefe20  733e57a0  9c496f1f  fafc491e
```

That is the mechanism closing on itself. `agent_loop.sh:72` instructs the
*agent* to ack its own message. `acceptEdits` blocked all Bash in the throwaway
`.fan` worktrees. No Bash means no ack; no ack means the message is never
retired; every poll re-fans it. The messages that could not ack are precisely
the messages that looped, and they are still unacked six days later.

`0fc1b84f` ran from **15:53:53 to 22:06:41 on 2026-07-27** — 6 h 13 min, 180
invocations, one every ~2 minutes `[O]`. The log ends one minute before `HALT`
was created. A human stopped it.

### 2.4 Every invocation exited zero

Across all 1,408 invocations in all three logs, **the exit code was `0` every
single time** `[O]`:

```
pm        fan  980 × rc=0     heartbeat   0
frontend  fan  258 × rc=0     heartbeat  11 × rc=0
backend   fan   88 × rc=0     heartbeat  69 × rc=0
```

There is no stronger available evidence for the program's "exit code 0 is not
success" requirement. The process exit code carried **zero bits of information**
about whether anything happened. A dispatcher trusting it would have recorded
1,408 successes.

### 2.5 Restated waste

| Class | Invocations | Basis |
|---|---:|---|
| `pm` redelivery loop | ~977 | `[O]` |
| `frontend` redelivery loop | ~180 | `[O]` |
| Empty-inbox heartbeats | 82 | `[O]` |
| **Produced nothing** | **~1,239** | `[O]` |
| Total invocations | 1,408 | `[O]` |
| **Waste fraction** | **~88%** | `[E]` from the two `[O]` rows |

The audit estimated the run at 150–300 total invocations `[E]`. The measured
figure is **1,408** `[O]`. Its estimate of ~73 recoverable invocations is
therefore low by roughly 17×.

### 2.6 What this changes

- **It does not change the plan.** Every control the program specifies —
  dispatcher-side attempt ledger, structured results, blocker-fingerprint
  suppression, no model heartbeats — targets exactly this. The diagnosis was
  right; only the magnitude was wrong.
- **It does change the calibration.** `per_task_max_invocations: 12` in
  `policy.yaml` would still have permitted 72 invocations across those six
  messages. The binding control has to be the **per-message** attempt cap of
  2–3 in the dispatcher, not the per-task cap in the governor.
- **It raises the value of the fix.** ~88% of a run's invocations were waste.
  The economic case for this program is stronger than any document in it claims.
- **It makes the `[E]` cost model unreliable in both directions.** Every
  per-invocation figure in `unattended-run-plan.md` divides a known total cost
  by an assumed invocation count that was wrong by ~5–10×. Those numbers must be
  re-derived from telemetry, not copied. Flagged for W2-3.

---

## 3. Control-plane inventory `[O]`

| Component | Path | Lines | In the live path? |
|---|---|---:|---|
| Launcher | `scripts/agent_loop.sh` | 112 | **yes** |
| Ledger transport | `agents/postmaster/ledger.py` | 218 | yes (shelled at `:93`) |
| Message schema | `agents/postmaster/message_schema.json` | 62 | yes; CI-validated |
| Governed daemon | `agents/postmaster/postmaster.py` | 248 | **no** — invoked by nothing |
| Budget governor | `agents/governor/budget_governor.py` | 134 | **no** — only caller is `postmaster.py` |
| Governor policy | `agents/governor/policy.yaml` | 11 | loaded only by the dormant path |
| Merge robot | `agents/merge_robot/merge_robot.py` | 124 | **no** — never run |
| Live config (gitignored, secret-bearing) | `agents/postmaster/config.yaml` | 33 | yes |

`agents/governor/ledger.sqlite3` and `agents/postmaster/postmaster.sqlite3`
**do not exist on disk** `[O]`. The governor has never recorded a single row.
Across three days, nine-way concurrency and a 977-invocation cascade, the
3-strike circuit breaker fired **zero** times, and `tasks/dead_letter/` is
empty `[O]`.

`agent_loop.sh` invokes models directly at two sites, with no governor call
anywhere in the file `[O]`:

- `:46-47` — `claude -p … --dangerously-skip-permissions` (pm)
- `:52-54` — `codex exec --dangerously-bypass-approvals-and-sandbox` (backend **and** frontend)

Containment on the live path is poll cadence + `HALT` + `MAX_PARALLEL` only.

### Live runtime configuration `[O]`

`mailroom/effort.env`:
```
CODEX_MODEL=gpt-5.6-sol
CODEX_EFFORT=high
INVOKE_TIMEOUT=1800
MAX_PARALLEL=6
```

Three divergences from the planning documents, all `[O]`:

1. **Kimi is already retired.** `frontend` runs codex (#89, credits exhausted).
   Every Kimi figure in `unattended-run-plan.md` describes a configuration that
   no longer exists. With no metered provider in the live path, the binding
   constraint is now *entirely* subscription capacity — which no CLI is known
   to report.
2. **`MAX_PARALLEL=6`**, not the 3 the documents assume and not the 2 the
   unattended plan specifies.
3. **`INVOKE_TIMEOUT=1800`**, not the 900 the hardening plan requires.

`arbiter_fallback: backend` is declared in the **gitignored** live
`config.yaml`, is absent from the tracked `config.example.yaml`, and is read by
no code `[O]`. An org control that exists only in an untracked file is a
control nobody can review.

---

## 4. Gate inventory `[O]`

| Gate | State |
|---|---|
| Python tests | 86 pass, ~1.3 s. Total coverage **68.4%** |
| `lint` | `ruff --select E9,F63,F7,F82` — syntax and undefined-name only |
| **`web/` (5,003 LOC)** | `npm test` defined; **not referenced by CI** |
| **`overlay/` (2,401 LOC)** | `npm test` defined; **not referenced by CI** |
| Coverage ratchet | inert twice: floor is `0.0`, **and** CI prints `COVERAGE:` to stdout while `merge_robot.py:88` reads it from a check-run `output.summary` |
| `REQUIRED_CHECKS` | `{lint, test, contracts, doctrine-invariants, assumptions-fixtures}` — excludes engine and all four Windows jobs |
| Merge robot | never run: no `MERGE_ROBOT_TOKEN`, no Actions secret, `main` unprotected |
| Non-author approval | mechanically unsatisfiable — all roles and the human share one identity (ADR-0003) |
| `watchdog.yml` | entire job body is `run: echo`. No cron runs the real watchdog |
| `upstream-sync.yml` | its corpus verification calls `engine/run_corpus.sh`, **which does not exist** — a silent no-op |
| `packaging/test_launch.py` | 12 tests that `pytest tests` never collects |
| Contract validation | proves the OpenAPI document is well-formed; does **not** prove runtime responses conform |
| Generated-client drift | no regeneration check |

**Correction to the record:** `HANDOFF-pre-restart-hardening.md` §4 W1-5 and
`unattended-run-plan.md` §7 G2 both state the measured coverage baseline as
**43%**. Measured here with the exact command CI runs, it is **68.4%** `[O]`.
Setting the floor to 43 would lower the effective gate by 25 points while
appearing to activate it.

---

## 5. Unrecovered work on disk `[O]`

**13 `.fan` worktrees hold uncommitted changes right now:**

| Worktree | Dirty files |
|---|---:|
| `frontend-c4c78ba2` | 21 |
| `frontend-301-r2` | 9 |
| `backend-9da1b541` | 9 |
| `frontend-d4f0ed2d` | 5 |
| `frontend-66908fb7`, `backend-5e157a9c` | 4 each |
| `backend-2142cf84` | 3 |
| six others | 1 each |

`backend-2142cf84` and `backend-5e157a9c` share the branch
`role/task-209-windows-runtime-build` at the same head.

This is the failure class W1-4 exists to prevent, sitting on disk, unrecovered
six days later. `agent_loop.sh:76-77` leaves a dirty worktree in place and logs
it — better than deleting, but it produces no recovery artifact, no quarantine
state, and nothing that would ever surface it to an operator.

**These must not be pruned or cleaned** during this program. A registered
scratchpad worktree at `/tmp/claude-1000/.../parityrun` would also be
unregistered by `git worktree prune`.

---

## 6. Ledger state `[O]`

296 messages. Append-only by construction (`ledger.py:120` opens with `"x"`).

| Role | Addressed | Acked | Unacked |
|---|---:|---:|---:|
| `pm` | 98 | 91 | **7** |
| `backend` | 107 | 107 | 0 |
| `frontend` | 91 | 90 | **1** |

The 7 unacked `pm` messages are the loop of §2.3. They are not a backlog; they
are wreckage. They must be resolved deliberately — dead-lettered with a reason,
or re-triaged — before any restart. Removing `HALT` with them still in the queue
restarts the cascade on the first poll.

Log volume: `backend.log` 59 MB, `frontend.log` 2.1 MB, `pm.log` 692 KB.

---

## 7. Blockers to implementation

| # | Blocker | Owner | Effect |
|---|---|---|---|
| 1 | `MERGE_ROBOT_TOKEN` unset; `main` unprotected; no distinct bot identity (TASK-007) | **human only** | Caps the achievable verdict at `GO-SUPERVISED`. `GO-UNATTENDED-7D` is unreachable until this lands. |
| 2 | All roles share one GitHub identity (ADR-0003) | **human only** | Non-author approval is mechanically unsatisfiable; merge-robot conditions 2/3 can never pass |
| 3 | 7 unacked `pm` messages | pm | Must be resolved before `HALT` is lifted |
| 4 | 13 dirty `.fan` worktrees | pm / W1-4 | Unrecovered work; must be preserved and triaged |
| 5 | 9 stale running markers | W1-6 | Readiness must handle a marker whose PID has been recycled |
| 6 | bwrap userns fails headless (`RTM_NEWADDR EPERM`) | **human / infra** | Sandboxing is a host problem; documented accepted risk with expiry |
| 7 | Every file this program touches is a protected path | pm | Authorisation granted for the exercise; not enforced today because the robot is not deployed |
| 8 | No provider CLI known to report subscription-allowance usage | W2-1 | Run budgets for the two subscription roles rest on manual daily readings |

---

## 8. Exit criteria for Phase 0

| Criterion | Met |
|---|---|
| Loops confirmed halted | **yes** `[O]` |
| No unknown active process can invoke a model | **yes** `[O]` |
| Authoritative launcher named | **yes** — `scripts/agent_loop.sh` |
| Live vs documented architecture differences recorded | **yes** — §2.6, §3, §4 |
| Secrets excluded from repository artifacts | **yes** — `config.yaml` referenced by structure only; no values reproduced |
| Blockers to implementation identified | **yes** — §7 |

**Phase 0: complete.**

---

## 9. Corrections this document makes to the program

Recorded here rather than silently absorbed, per the program's instruction that
where evidence differs from the plan the difference is documented and the plan
updated through a reviewable change.

| Program statement | Measured | Source |
|---|---|---|
| "~50 burned invocations" | **~1,157 redelivered + 82 heartbeat ≈ 1,239 of 1,408** | §2 |
| Run totalled 150–300 invocations `[E]` | **1,408** `[O]` | §2.1 |
| Coverage baseline 43% | **68.4%** | §4 |
| Kimi is the frontend model | already retired; frontend runs codex | §3 |
| `MAX_PARALLEL` is 3 | **6** | §3 |
| `tasks/dead_letter/` does not exist | exists, empty | §3 |
| Governor "implemented but disconnected" | also **never executed** — no sqlite file was ever created | §3 |
