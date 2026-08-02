# Unacknowledged ledger queue — triage, 2026-08-02

Blocker #3 from `current-state-2026-08-02.md` §7. Seven `pm` messages and one
`frontend` message are unacknowledged. They are not a backlog; they are the
wreckage of the 2026-07-27 redelivery cascade. Six of the seven `pm` messages
are the ones that were re-fanned 100–180 times each.

**Removing `HALT` with these still queued restarts the cascade on the first
poll.** They must be dispositioned first.

None of these messages is long or hard. Every one is a short status or sync.
They looped because the `pm` agent could not run Bash to acknowledge them — not
because the work was difficult.

## Disposition

| # | id | From | Intent | Loops | Disposition |
|---|---|---|---|---:|---|
| 1 | `0fc1b84f` | human | SYNC ORG (#90) | 180 | **Superseded.** Announces the 2026-07-27 reconfiguration; that reconfiguration is now history and is recorded in the Phase 0 file. Ack. |
| 2 | `733e57a0` | human | SYNC ORG (#89) | 175 | **Expired.** A FOCUS SPRINT directive scoped "now until 2026-07-27T22:05Z". That window closed six days ago. Ack. |
| 3 | `fafc491e` | frontend | STATUS TASK-209 | 3 | **Self-superseding.** States that issue #75 is closed + needs-triage and PR #82 merged. Ack. |
| 4 | `11536792` | backend | STATUS ORG (#89) | 100 | **Informational, absorbed.** Deployability check at `a04c8b3`, CI green, v0.1.0 assets intact, bot unit active. Its runbook-drift finding is fixed (see below). Ack. |
| 5 | `67cefe20` | backend | STATUS TASK-102 (PR #87) | 177 | **Live.** PR #87 approved at `dde7e04`, ten checks green, blocked only on the empty `MERGE_ROBOT_TOKEN` (robot run 30273258937, HTTP 401). Awaits manual ADR-0003 merge by pm. Carry forward, then ack. |
| 6 | `9c496f1f` | frontend | STATUS TASK-210 (PR #91) | 175 | **Live.** PR #91 approved at `95b67cb`, checks green, same 401. Explicitly asks that issue #79 **not** be closed. Carry forward, then ack. |
| 7 | `63719892` | backend | STATUS TASK-210 (PR #91) | 170 | **Answered by ADR-0008.** Requested a process ruling reconciling stage PRs with merge-robot condition 4, and refused to bypass the gate. Ruling now recorded. Ack. |

Frontend's single unacked message is the counterpart of #6 and is dispositioned
with it.

## What was actually decided or fixed here

- **ADR-0008** answers message 7. Stage PRs use `Refs #<parent>`; the merge
  robot resolves the task structurally via `parent_of` rather than from
  issue-closing keywords. PR #91 is the acceptance case. This was blocked for
  six days purely because the message asking for it could not be retired.
- **Runbook drift from message 4 is fixed.** `docs/runbooks/discord_setup.md`
  named `poe-intake-bot.service` in six places; the deployed unit is
  `poe-upgrade-bot.service`. An operator following the runbook to restart the
  bot would have got "unit not found". Also marked the
  `poe-intake-flush.service`/`.timer` pair superseded — neither is deployed,
  `bot/bot.py:142` shells `ledger.py` directly, and 5 `INTAKE_TICKET` messages
  reached the ledger without the bridge.
- **Two PRs remain merge-blocked on a human-only prerequisite** (#87, #91).
  Both are approved with evidence at an exact head and green checks. Neither
  can merge until `MERGE_ROBOT_TOKEN` exists or pm merges manually under
  ADR-0003.

## Operator step — not performed by any agent

Acknowledgment writes to `mailroom/cursors/pm.acked`, which is **append-only
and cannot be undone**. It is live operational state outside the repository, so
it is left to the operator rather than executed by a session. Run this after
reviewing the table above, and before removing `HALT`:

```bash
cd /home/decross1/projects/poe-discord-proj/worktrees/pm

# Live items — merge these two first if you are merging manually (ADR-0003),
# or leave them unacked until the merge robot is provisioned.
#   PR #87  TASK-102  head dde7e04
#   PR #91  TASK-210  head 95b67cb   (per ADR-0008: Refs #79, do NOT close #79)

python3 agents/postmaster/ledger.py ack --role pm \
  --id 0fc1b84f --id 733e57a0 --id fafc491e --id 11536792 --id 63719892

# Only after #87 and #91 are merged (or deliberately parked):
python3 agents/postmaster/ledger.py ack --role pm --id 67cefe20 --id 9c496f1f
python3 agents/postmaster/ledger.py ack --role frontend --all-new

# Verify the queue is empty before lifting HALT:
python3 agents/postmaster/ledger.py inbox --role pm
```

## Why this is not merely housekeeping

The hardening program treats the cascade as a spend problem: ~1,157 wasted
invocations. This queue shows the other half of the cost. Message 7 was a
correctly-escalated request for a PM ruling. It was delivered 170 times and
answered zero times, and PR #91 sat approved and unmergeable for six days as a
result.

The missing acknowledgment path did not only waste capacity. It silently
dropped every decision those messages were waiting on, with no signal that a
decision was outstanding — the queue looked busy rather than stuck. Any restart
readiness check must therefore assert that the queue is empty *and* that no
message predates the current dispatcher, which is why W1-6 gained that check.
