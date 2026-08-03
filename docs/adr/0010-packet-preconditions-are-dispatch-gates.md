# ADR-0010: Packet preconditions gate dispatch, not review; a closed parent never orphans merged work

- Status: accepted
- Date: 2026-08-03
- Task: TASK-210-S2 / PR #110 / issue #79 → successor issue #113
- Deciders: pm

## Context

Frontend escalated a genuine deadlock (ledger `91f65538`) instead of routing
around it:

> Issue #79 is CLOSED, but `tasks/packets/TASK-210-S2.json` has precondition
> `issue_state=open`, so backend review of PR #110 is blocked per AGENTS.md
> ("the issue wins"). Frontend will not reopen a human-closed issue
> unilaterally, and will not edit the packet precondition (gate-weakening).

That is the correct behavior on both counts, and the same block sat on S3
(PR #111) and S4 (PR #112).

The block was real but the review it gated was already moot, which is the
part worth writing down:

- TASK-210-S2's diff merged to main at `473c167` on 2026-08-03T07:22Z —
  **nine minutes before** #79 was closed at 07:31:07Z.
- PR #110's head `02fbc20` is byte-identical to `origin/main` across all
  eight of the packet's in-scope files. The only delta in the range is the
  later S4 hotkey wiring in `main.ts`.
- S3 merged at `8cd7d0a`; S4 merged at `78765c1`.

So a precondition written to gate *dispatch* was still being evaluated after
merge, and it held three shipped stages hostage to the state of an issue whose
work was already on main. A precondition is a statement about whether work
should *start*; re-reading it at review time makes an issue's later lifecycle
retroactively invalidate work that was correctly dispatched under it.

## Decision

1. **`preconditions` in a task packet are evaluated at dispatch only, and that
   settlement covers precondition staleness — nothing else.** Once a packet is
   dispatched, its preconditions are settled for that attempt: a reviewer MUST
   NOT refuse review *solely* because a packet precondition would no longer
   evaluate true (the parent's `issue_state` flipped, a required label was
   removed).

   A reviewer MUST still honor every live authority signal that is not a
   precondition: **cancellation** of the task, **supersession** by another PR
   or ruling, a **scope change** issued by the PM, and any **human action** on
   the issue lifecycle. AGENTS.md work-protocol step 2 is unchanged — the issue
   still wins. If the current issue, ledger, or a human says *this work should
   not land*, the reviewer stops and escalates to pm@ rather than reviewing
   past it.

   The test that separates the two: ask whether current state says the work
   should not land. If yes, honor it. If the only thing that changed is that a
   dispatch-time check would no longer evaluate true, review the diff. This
   clause creates no cancellation or supersession bypass; a stale `issue_state`
   check is not a cancellation, and a cancellation is never merely a stale
   check.
2. **Repointing a packet's `issue` to a live successor is not gate-weakening;
   deleting or loosening the `issue_state` check is.** Only the PM repoints,
   and only to an issue that is open and is the true parent of that stage ID
   per `parent_of`. Implementing roles still never edit preconditions —
   frontend's refusal here was right.
3. **Work already merged to main is never re-gated.** Where a stage's diff is
   on main, the stage is done: close its PR as superseded-by-main, cite the
   merge commit, and do not redispatch review. Verification of that claim is
   a content comparison against `origin/main`, not a status comment.
4. **An agent replaces a closed parent; it never reopens one. A human moves the
   lifecycle in either direction, and that move is authoritative.** Per
   ADR-0008 §4 a parent closes when a human or the PM closes it. No agent may
   reopen a human-closed issue to satisfy a machine precondition — that
   inverts the authority order. If scope remains, the PM mints a successor
   parent carrying the unshipped checklist and points subsequent packets at
   it (ADR-0009 D3; D3 governs where the two ADRs touch).

   The converse binds equally: **when a human reopens a parent, the reopen is
   the org's live truth**, and any successor parent minted while it was closed
   yields to it. The PM closes the redundant successor as superseded and
   repoints its scope back onto the reopened parent's stage IDs. Two open
   parents carrying the same checklist is the duplicate-parent hazard D3
   exists to prevent, and the human-authored one wins.

## Consequences

**Numbering.** This ADR was authored as 0009 and renumbered to 0010 on
discovery that a concurrent pm invocation (TASK-210-S4) had already pushed
`docs/adr/0009-duplicate-implementations-and-closed-parent-issues.md` at
`0485133`. The two rulings are complementary, not competing: ADR-0009 rules on
duplicate implementations and on lineage under a closed parent (D3); this one
rules on *when* a precondition is evaluated. Where they touch, ADR-0009 D3
governs. Concurrent ADR authorship racing on the next free number is itself
retro material — the collision was caught by reading the remote, not by any
mechanism.

**Immediate — #79 is open again, and it is the parent.** This ADR was drafted
while #79 was closed. The human (`decross1`) reopened it at
2026-08-03T16:04:04Z, ~8.5 hours after closing it at 07:31:07Z. Under decision
4 that reopen is authoritative, so:

- **Issue #79 is the live parent for TASK-210.** Its shipped items — clipboard
  watcher (`473c167`), e2e golden snapshots (`8cd7d0a`), always-on-top card +
  `POST /diff` → `VerdictCard`, global hotkey (`78765c1`) — stay shipped and
  are not re-done.
- **Issue #113 (TASK-211) closes as superseded by the reopen.** It was minted
  solely as a successor parent while #79 was closed; the reopen removes its
  reason to exist, and leaving both open would leave two parents carrying one
  checklist. Its three items — build-snapshot deep link, `run.bat` packaging,
  capture→card p95 (I6) — return to #79 as TASK-210 stages. The org had already
  converged there: the concurrently authored TASK-210-S5 packet (`378db32`)
  points at issue 79.
- **The `issue_state=open` precondition on TASK-210-S2/S3 is true again**, so
  the original deadlock is moot on its facts as well as on this ruling. The
  ruling still stands on its own: a precondition that flips *after* dispatch
  must not strand a correctly dispatched attempt, and the org must not depend
  on a human happening to flip it back.

PRs #110 and #112 still close as superseded-by-main (`473c167`, `78765c1`);
PR #111 already merged. That determination is content-based — the heads are
identical to main across the packets' in-scope files — and is independent of
issue state, so the reopen does not disturb it. No S2/S3/S4 review is
redispatched, saving three review invocations on shipped code.

**Easier.** A stage can no longer be stranded by its parent's lifecycle, and
"is this done?" is answered by comparing the diff to main rather than by
reconciling issue state with ledger claims.

**Harder.** Dispatch-time-only evaluation means a stale packet can dispatch
against a parent that closed since the packet was written. Mitigated because
the dispatcher reads preconditions at dispatch, which is exactly when the
check is meaningful. Revisit if a packet is ever re-dispatched long after
authoring — a re-attempt is a new dispatch and re-evaluates.

**Process note.** Both roles behaved correctly and the org still stalled:
frontend refused to weaken a gate, backend refused to review past one, and the
gate itself was pointed at the wrong moment in the lifecycle. Gate placement
is a correctness control, not a formality.

## Review history

Backend returned REQUEST_CHANGES on PR #115 at head `6f7b908` (ledger
`51d666aa`; full suite 583 passed / 7 skipped, doctrine invariants OK,
`EVIDENCE-SHA256:02a5fc4e2385bee30033e071ce3fe097451f7828c89633078b47cbd9c3a8a9c1`).
Both objections are sustained and are why decisions 1 and 4 read as they do:

1. *Decision 1 created a cancellation/supersession bypass* — as first written
   it told reviewers to ignore issue lifecycle state wholesale, which would let
   a task dispatched while open, then cancelled by a human or the PM, still be
   reviewed and landed. Narrowed to precondition staleness only, with
   cancellation, supersession, scope change, and human lifecycle action
   explicitly binding on reviewers.
2. *The "#79 stays closed" claim was false* — the human reopened #79 while this
   PR was in review. Decision 4 now covers the reopen direction and the
   consequences reconcile #79 against #113 rather than asserting a state that
   no longer held.

The pre-existing lint `F821` backend flagged is unrelated to this diff, is not
waived by this ADR, and needs its own issue.

## Related

- ADR-0009 — duplicate implementations; closed-parent lineage (D3 governs where
  this ADR and it overlap)
- ADR-0008 — stage PRs use `Refs`; parent closure semantics (§4)
- ADR-0003 — shared-identity merge exception
- AGENTS.md rule 6 — never weaken a gate to pass it
- Issue #79 (reopened by human 2026-08-03T16:04:04Z — live parent), issue #113
  (successor parent, closed as superseded by the reopen), PRs #110/#111/#112
