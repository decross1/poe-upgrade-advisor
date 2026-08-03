# ADR-0009: Duplicate packet implementations, and packets under a closed parent issue

- Status: accepted
- Date: 2026-08-03
- Task: TASK-210-S4 / PR #112 (ledger b2430ae5, in reply to review verdict e6887a52)
- Deciders: pm (binding)

## Context

TASK-210-S4 (wire the overlay show/hide hotkey) completed **twice** and produced
two independent implementations from the same packet:

- `frontend/TASK-210-S4-global-hotkey` @ `78765c1` — the surgical variant.
- `frontend/TASK-210-S4-hotkey-toggle` @ `459b7e32` — PR #112, reviewed and
  APPROVED by backend under ADR-0003 with `EVIDENCE-SHA256:4c1d5c58…`.

The human owner landed the *first* on main as merge `346c8da` before pm's merge
heartbeat ran. (Record defect: `346c8da`'s message names the merged branch as
`-hotkey-toggle`; the commit it actually merges, `78765c1`, is on
`-global-hotkey`. `459b7e32` is **not** an ancestor of `origin/main`. The
described diff sizes — 9 lines vs 58 — identify the merged variant correctly;
only the branch name in the prose is wrong.)

PR #112 therefore arrives for ADR-0003 merge verification against a main that
already implements its packet, and it additionally carries a red required `lint`
check caused by an unrelated base defect (`agents/dispatch.py` F821, issue #107,
fix in flight as PR #109). AGENTS.md rule 6 forbids merging past that gate.

Separately, and for the second time (TASK-210-S2, ledger `91f65538`), a role has
asked what to do when the parent issue — #79 — is CLOSED by the human owner while
sub-packets are still in flight against it.

## Decision

**D1 — Verification is against main, not against the PR.** pm's ADR-0003 duty is
to establish that the packet's acceptance criteria hold on `origin/main`, not
that a particular branch merges. Verified first-hand at `ccd032e`: hotkey
registered in `main.ts` with `OVERLAY_HOTKEY ?? DEFAULT_HOTKEY`
(`CommandOrControl+Alt+D`), toggle uses `showInactive()` only — no `show()` or
`focus()` on the hotkey path — registration failure logged and non-fatal,
`unregisterAllHotkeys` on `will-quit`, and `npm --prefix overlay run test` green
at 66/66 across 7 files. AC-1 through AC-4 **pass on main**. TASK-210-S4 is DONE.

**D2 — The losing duplicate is closed as superseded, never merged.** When a
packet yields two implementations and one has landed, the unlanded PR is closed
with a `SUPERSEDED by <sha>` comment and **its branch is preserved, not deleted**.
Merging it would re-land shipped behaviour and manufacture a conflict; here it
would also require bypassing a red required gate, which is never permitted. The
review that was performed is not wasted — it stands as recorded evidence and its
verdict is honoured by this ruling. PR #112 is closed on those terms.

**D3 — A closed parent issue does not block its sub-packets.** Sub-packets
reference the parent for lineage only. Post status comments on the closed issue
(GitHub permits this); **do not reopen it** — closure is the human owner's
signal about the parent's tracking state and reopening overwrites that signal.
If a sub-packet needs its own open tracking surface, ask pm for a dedicated
issue rather than reviving the parent. This settles the question raised at
TASK-210-S2 (ledger `91f65538`) and again here.

**D4 — Duplicate dispatch is a dispatcher defect, not a role defect.** Neither
frontend invocation did anything wrong. The waste belongs to whatever let one
packet be claimed twice; it is retro material (L-26), not a review finding.

## Consequences

- Easier: a landed-by-human packet no longer deadlocks pm's merge heartbeat, and
  no role burns invocations rebasing a PR whose work already shipped.
- Harder: reviewer effort on a duplicate branch is sunk. Accepted — cheaper than
  the merge conflict and the gate pressure the alternative creates.
- The red `lint` gate is untouched by this ruling; #107 / PR #109 remain the only
  path to green, and nothing here authorizes a bypass.
- Reversal condition for D2: revisit if a duplicate is ever found *materially
  better* than the landed variant — then the ruling is a revert-and-relaunch
  decision, not a merge, and it needs its own ADR.
- Follow-up: retro entry L-26 (duplicate dispatch of TASK-210-S4) at the next L5
  pass; `346c8da`'s misnamed branch is corrected here rather than by rewriting
  history on main.
