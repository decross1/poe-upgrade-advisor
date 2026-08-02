# Merge Robot — Specification

The merge robot is the **only identity with merge rights** on `main`. It is deterministic; it has no model, no judgment, no exceptions. Agents persuade each other; only the robot merges.

## Trigger
Runs on: PR labeled `ready-to-merge`; PR review submitted; schedule (every 30 min sweep).

## Merge conditions — ALL must hold

| # | Condition | Mechanism |
|---|-----------|-----------|
| 1 | Required CI checks green (lint, test, contracts, doctrine-invariants, assumptions-fixtures) | Checks API |
| 2 | ≥1 APPROVED review whose body contains `EVIDENCE-SHA256:` | Reviews API |
| 3 | Reviewer identity ≠ author identity (self-approval void) | Review/PR author metadata |
| 4 | PR body contains `Fixes #<n>` linking a real open issue with a `TASK-` title | Issues API |
| 5 | Protected paths untouched, OR linked issue carries label `protected-change` | diff vs base × PROTECTED_PATHS |
| 6 | No banned patterns introduced (Doctrine S3): process-memory APIs, input synthesis (e.g. `SendInput`, `keybd_event`, `WriteProcessMemory`), undocumented GGG endpoints | diff grep, list in `merge_robot.py` |
| 7 | No test deletions/skips (removed lines matching test signatures or added skip markers) unless issue has label `test-change-authorized` | diff grep |
| 8 | Coverage ratchet: `coverage.json` uploaded by CI ≥ recorded floor − 0.1 pt; merging updates the floor upward | CI artifact + `merge_robot/coverage_floor.json` |
| 9 | Branch up to date with `main` (else robot rebases via merge queue and re-runs) | Git API |

On success: **squash-merge**, comment `MERGED by robot: all 9 conditions verified`, delete branch, close loop by commenting on the task issue.
On failure: comment the first failed condition (mechanical text, no advice), remove `ready-to-merge`. Three failed sweeps on the same PR → notify PM via outbox-style issue comment `@pm ARBITRATION_REQUEST`.

## PROTECTED_PATHS
```
agents/*  .github/*  contracts/*  PRODUCT_DOCTRINE.md  AGENTS.md
engine/corpus/*  scripts/check_invariants.py  tasks/packets/*
```
`protected-change` labels can only be applied at task-creation time by the PM identity; the robot verifies the label's audit log actor.

## Explicit non-goals
The robot never evaluates code quality, style, or design — that is L1's job. The robot never merges its own config changes (condition 5 applies to itself; a protected-change task + counterpart review is required, keeping the meta loop honest).
