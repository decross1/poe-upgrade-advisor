# Adversarial Review Protocol (L1)

Purpose: replace human code review with a loop that cannot rubber-stamp, cannot nitpick forever, and settles disputes deterministically.

## Roles per PR
- **Author**: the agent whose branch it is.
- **Reviewer**: the counterpart agent (FE↔BE review each other; PM reviews contract/assumption/doctrine-adjacent PRs; PM's own PRs are reviewed by BE).
- **Arbiter**: PM (or fallback per `agents/postmaster/config.yaml` if PM circuit-breaks).

## The rules

1. **Review is execution, not reading.** The reviewer must check out the branch, run the test suite and any task-relevant repro, and attach evidence: the tail of the run log plus a line `EVIDENCE-SHA256:<sha256 of full log>` in the review comment. The merge robot ignores approvals without evidence.
2. **Objections must be falsifiable.** A `REQUEST_CHANGES` must contain at least one of: (a) a failing test committed to a `review/<task-id>` branch reproducing the claim, (b) a doctrine invariant ID, (c) a contract violation citation (file + line of `contracts/`). Style-only objections are not grounds for blocking; file a `chore` issue instead.
3. **Bounded rounds.** Maximum 3 review rounds (round = one REQUEST_CHANGES + one author response). At round 3 without approval, either party sends `ARBITRATION_REQUEST` to the arbiter.
4. **Arbitration is binding and recorded.** The arbiter reads both positions, may run code, and issues a ruling committed as `docs/adr/NNNN-task-<id>-ruling.md` (use `docs/adr/TEMPLATE.md`). The ruling states what merges, what changes, and why. No appeals; a new RFC is the only way to revisit.
5. **Self-approval is void.** Author identity must differ from reviewer identity (enforced by merge robot via commit/PR author metadata).
6. **Review SLA.** Reviewers respond within 2 heartbeats. Silence past TTL escalates to the arbiter automatically (postmaster tracks `REVIEW_REQUEST` age).

## What reviewers verify, in order
1. Tests pass locally (evidence attached).
2. Task acceptance criteria from the issue are met.
3. No doctrine violation (`PRODUCT_DOCTRINE.md`), especially I1/I2/I5/S1–S3.
4. Contract conformance for anything crossing `contracts/`.
5. No gate-weakening: deleted/skipped tests, loosened schemas, CI edits, coverage drops.
6. Blast radius: does this touch protected paths without `protected-change`?
