# ADR-0007: Pre-restart hardening implements Waves 1–2, not the full restart program

- Status: accepted
- Date: 2026-08-02
- Task: ORG / pre-restart hardening
- Deciders: pm

## Context

Three planning documents govern bringing the autonomous org back online:

- `poe_autonomous_org_restart_program_v1.0.md` — 16 phases, the canonical
  target architecture and readiness framework
- `HANDOFF-pre-restart-hardening.md` — an adversarial review of an earlier
  hardening plan, merging it into two ~1-week waves
- `unattended-run-plan.md` — the 7–10 day unattended operating model
- `poe-upgrade-advisor-cost-audit.md` — the underlying diagnosis

They do not all specify the same work, and two of them disagree with each other
on points that matter. The restart program is broader and more rigorous about
*governance*; the merged handoff is an evidence-based *narrowing* of it, and it
identifies three places where following the program literally would make things
worse. A decision was required before work could be split across two concurrent
dev sessions.

Phase 0 evidence (`docs/agent-org/current-state-2026-08-02.md`) also
contradicted several premises shared by all four documents.

## Decision

**Implement `HANDOFF-pre-restart-hardening.md` §4 Waves 1 and 2 — eleven units,
W1-1…W1-6 and W2-1…W2-5 — mapped onto the restart program's phase register and
governed by the restart program's readiness-verdict framework.** Wave 3 is out
of scope.

Specifically:

### 1. Build a new `agents/dispatch.py`; do not promote `postmaster.py`

The restart program prefers promoting the postmaster to the authoritative
dispatcher. Reject. `postmaster.py` has never run in production, acks
unconditionally on failure, was built for IMAP and retrofitted to the ledger,
and lacks per-message `flock`, worktree isolation, and marker pruning —
all of which `agent_loop.sh` has and has exercised for three days. Promoting
the never-run component over the production-hardened one, with the safety net
off, inverts the risk. `agent_loop.sh` stays the process supervisor;
`postmaster.py` is retired to `agents/attic/`.

### 2. The ack decision is dispatcher-side and attempt-capped

The restart program's acknowledgment rule — ack only on `completed`, a
validated `blocked`, or an explicit `terminated` — **does not fix the incident
it cites, and would make it permanent.** An agent whose Bash is blocked cannot
write a result, cannot write a blocked state, and cannot ack; under that rule
its message is never retired and is redelivered forever.

The dispatcher increments a per-message attempt ledger **before** invoking, and
dead-letters plus acks past the cap, independent of whether the agent
functioned at all. Phase 0 measured this failure mode at ~1,157 redelivered
invocations across ten messages, so the correction is load-bearing, not
theoretical.

### 3. Cut the model router; record its inputs instead

The restart program's Phase 10 specifies four tiers and eleven routing inputs,
then resolves them to a two-branch conditional, and its shadow decisions have
nothing to be scored against because the telemetry that would score them does
not exist yet. Record the routing *inputs* in telemetry — subsystems touched,
protected-path touch, prior failures, tier assigned — so the router is built
later from a labelled dataset. `result.schema.json` reserves a `route` object
for this.

### 4. Cut the changed-path CI selector

It optimises the execution cost of gates that do not exist. Ship the gates.

### 5. Cut sandboxing from this program

The permission bypasses exist because bwrap userns fails headless on this host
(`RTM_NEWADDR EPERM`). That is an infrastructure problem, not a code change,
and attempting it consumes the session. The stated security model —
"a compromised agent can only push a branch; protected paths are the
compensating control" — is currently **false**, not because a sandbox is
missing but because the merge robot was never deployed. Deploying it restores
the real control for a fraction of the effort.

### 6. Task packets carry ten enforceable fields, not twenty-four

A packet field the dispatcher does not read is documentation, not control. And
packets are authored by the PM, whose capacity is the binding constraint;
twenty-four fields × 40–60 tasks is a meaningful draw on the scarcest resource.

### 7. Delete the `ORG` exemption rather than exempting it differently

`budget_governor.py::allow` places the per-task cap, the circuit breaker, and
backoff all inside `if task_id != "ORG":`. `ORG` gets its own execution class
with its own caps and its own breaker.

### 8. Add `pm-lite`, which no phase of the restart program contains

The PM consumed 3.5× the capacity of the role that wrote the code, almost all
of it on a mechanical checklist. A deterministic scheduler is the single
largest capacity lever available and it is absent from all sixteen phases.

### 9. Split execution policy across two files

`policy.yaml` (per-task execution) and `run_policy.yaml` (aggregate, run,
degradation), merged by `agents/interfaces/policy.py::load_policy`, which
raises if a key appears in both. This exists so two concurrent dev lanes never
edit the same YAML; it is a coordination artifact and should be revisited once
the lanes converge.

## Consequences

**Easier.** Two lanes can work the same repository concurrently without
collision, against a frozen `agents/interfaces/` seam. After Wave 1 the loops
are safe to restart supervised; after Wave 2 they are structurally ready for an
unattended run.

**Harder.** The repository temporarily carries a two-file policy split and a
port-and-default-implementation layer that a single-session implementation
would not need. Both are reversible once the lanes merge.

**Deferred, with the gate each waits on:**

| Item | Gate |
|---|---|
| Changed-path CI selector | the jobs existing (W1-5) and CI cost being non-zero |
| Model router + open-weight shadow decisions | W2-1 telemetry producing a labelled dataset |
| Containerised / capability sandbox | host userns fix or container infra; merge robot deployed first |
| Packet fields beyond v1 | evidence the dispatcher can enforce them |
| Resource-lock service | observed lock contention in W2 telemetry |
| Splitting `server/calculator.py` | property tests in CI first |
| Repository Intelligence Layer (program Phase 9) | Wave 2 landing; it is a cost optimisation, not a safety control, and nothing in the restart path depends on it |

**Verdict ceiling.** `MERGE_ROBOT_TOKEN`, branch protection, and distinct bot
identities are human-only and unprovisioned. `GO-UNATTENDED-7D` is therefore
unreachable by this program regardless of execution quality; the achievable
ceiling is `GO-SUPERVISED`. This is recorded here so that a later session does
not read a supervised verdict as an implementation failure.

**Follow-up filed:** the Phase 0 record corrects seven factual premises shared
by the planning documents, including a ~17× understatement of total invocations
and a 25-point error in the coverage baseline. Every `[E]` cost figure derived
from those premises must be re-derived from W2-1 telemetry before it is used to
set a cap.
