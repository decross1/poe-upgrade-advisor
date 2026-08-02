# ADR-0008: Stage PRs link their parent with `Refs`, and the merge robot resolves tasks structurally

- Status: accepted
- Date: 2026-08-02
- Task: TASK-210 / PR #91 / issue #79; generalises to all multi-stage work
- Deciders: pm

## Context

Backend filed a merge-process blocker on approved PR #91 and refused to bypass
it:

> Its body uses `Refs #79` so the multi-stage issue remains open, but Merge
> Robot SPEC condition 4 requires `Fixes` against an open TASK issue. ADR-0003
> substitutes only conditions 2/3 and requires every other robot condition.
> Please triage by creating/linking a Stage 1 TASK issue or recording a process
> ruling that reconciles partial-stage PRs with condition 4. **Backend will not
> bypass the gate.**

That was the correct escalation — a gate was in the way, and the agent asked
for a ruling instead of weakening it (`AGENTS.md` rule 6). The ruling was never
made, because the message asking for it was one of the seven that could not be
acknowledged during the 2026-07-27 redelivery cascade. It was re-delivered 170
times and answered zero times.

The underlying conflict is structural, not incidental:

- `merge_robot.py:60` requires `Fixes #<issue>` in the PR body and resolves the
  task from it.
- GitHub closes an issue when a PR containing `Fixes #N` merges.
- A **stage** of multi-stage work must merge without closing its parent —
  TASK-210's native Windows, packaging, and latency stages were still
  outstanding when PR #91 became mergeable.

So a stage PR can satisfy condition 4 or preserve its parent, but not both.
TASK-209's lanes A–D hit the same wall earlier.

## Decision

**Stage PRs use `Refs #<parent>`. The merge robot stops inferring the task from
issue-closing keywords and resolves it structurally instead.**

1. A PR that completes an entire task keeps `Fixes #<issue>`. Unchanged.
2. A PR that completes one **stage** uses `Refs #<parent-issue>` and names its
   stage in the branch and PR title as `TASK-<n>-S<k>`.
3. Merge-robot condition 4 is satisfied by **either**:
   - `Fixes #<issue>` where the issue is an open TASK; **or**
   - `Refs #<parent>` where the parent is an open TASK **and** the head branch
     or PR title carries a well-formed stage ID whose parent, derived by
     `agents/interfaces/packet.py::parent_of`, equals that issue.
4. On merging a stage PR the robot comments the stage completion on the parent
   issue and **does not close it**. The parent closes when a human or the PM
   closes it, or when a final `Fixes` PR merges.
5. Stage identity is **derived from the ID, never declared separately**, so a
   stage cannot disagree with itself about who its parent is.

This is a strengthening of condition 4, not a waiver. Today the condition can
be satisfied by any `Fixes #N` pointing at any open TASK issue, including one
unrelated to the diff. After this change a stage PR must present a parent that
its own stage ID resolves to.

## Consequences

**PR #91 becomes mergeable** under the existing manual ADR-0003 path once the
robot logic lands: it already carries an evidence-bearing backend approval at
head `95b67cb`, all substantive checks green, and `Refs #79`. Issue #79 stays
open, which is what frontend explicitly asked for. PR #87 (TASK-102) is a whole-task
PR with `Fixes #7` and is unaffected.

**Lane B implements this in W2-5.** It is now a specified ruling rather than an
open question, and PR #91 is the concrete acceptance case. Test 20 — "a task
stage completes and merges without closing the parent" — tests exactly this.

**Harder:** the robot needs branch/title parsing it did not previously need,
which is a new place for a regression. Mitigated by `parent_of` already being
committed and unit-tested in the frozen interface package.

**A process observation worth keeping.** This ruling was blocked for six days
not because it was difficult — it took one reading of the message to decide —
but because the transport could not retire the message that requested it. The
cost of the missing acknowledgment path was not only ~1,157 wasted invocations;
it was also every decision those messages were waiting on. Throughput controls
and correctness controls are the same controls.

## Related

- ADR-0002 — ledger transport
- ADR-0003 — shared-identity merge exception (substitutes conditions 2/3 only)
- ADR-0007 — pre-restart hardening scope
- `docs/agent-org/current-state-2026-08-02.md` §2, §6 — the cascade and the
  unacknowledged queue
