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

1. **`preconditions` in a task packet are evaluated at dispatch only.** Once a
   packet is dispatched, its preconditions are settled for that attempt. A
   reviewer MUST NOT refuse review because a packet precondition has since
   become false. Reviewers gate on the diff, the doctrine, the contracts, and
   the required checks — never on issue lifecycle state.
2. **Repointing a packet's `issue` to a live successor is not gate-weakening;
   deleting or loosening the `issue_state` check is.** Only the PM repoints,
   and only to an issue that is open and is the true parent of that stage ID
   per `parent_of`. Implementing roles still never edit preconditions —
   frontend's refusal here was right.
3. **Work already merged to main is never re-gated.** Where a stage's diff is
   on main, the stage is done: close its PR as superseded-by-main, cite the
   merge commit, and do not redispatch review. Verification of that claim is
   a content comparison against `origin/main`, not a status comment.
4. **A closed parent is replaced, not reopened.** Per ADR-0008 §4 a parent
   closes when a human or the PM closes it; that close stands. If scope
   remains, the PM mints a successor parent issue carrying the unshipped
   checklist, and subsequent stage packets point at it. Reopening a
   human-closed issue to satisfy a machine precondition inverts the
   authority order. This is ADR-0009 D3 applied to unshipped *scope* rather
   than to lineage: where D3 says a sub-packet asks the PM for a dedicated
   issue instead of reviving the parent, issue #113 is that issue for
   TASK-210's remainder. ADR-0009 D3 governs; this clause only names the
   instance.

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

**Immediate.** #79 stays closed — its core (watcher, card, `POST /diff`,
hotkey) is merged and the close is honest. Issue #113 becomes the open parent
for the three unshipped items: build-snapshot deep link, `run.bat` packaging,
capture→card p95 latency (I6). PRs #110 and #112 close as superseded-by-main
(`473c167`, `78765c1`); PR #111 already merged. No S2/S3/S4 review is
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

## Related

- ADR-0009 — duplicate implementations; closed-parent lineage (D3 governs where
  this ADR and it overlap)
- ADR-0008 — stage PRs use `Refs`; parent closure semantics (§4)
- ADR-0003 — shared-identity merge exception
- AGENTS.md rule 6 — never weaken a gate to pass it
- Issue #79 (closed), issue #113 (successor parent), PRs #110/#111/#112
