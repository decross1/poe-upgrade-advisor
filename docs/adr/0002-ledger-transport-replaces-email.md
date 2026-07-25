# ADR-0002: Append-only filesystem ledger replaces email as agent transport

- Status: accepted
- Date: 2026-07-25
- Task: ORG (pre-ignition, human-directed)
- Deciders: human (derrick@derrickcross.com), pm

## Context

The original design used email (IMAP/SMTP via `agents/postmaster/postmaster.py`)
as the inter-agent transport. That requires paid mailboxes, DNS setup, and
credential management — cost and friction with no benefit while all three role
sessions run as separate clones on one machine. The human operator directed:
free, quick to set up, easy to manage, write-only.

## Decision

Transport is a shared append-only filesystem ledger at `<project>/mailroom/`
(sibling of the role clones; this box: `~/projects/poe-discord-proj/mailroom/`),
operated exclusively through `agents/postmaster/ledger.py`:

- Messages are immutable JSON files in `mailroom/messages/`, one per message,
  validated against `agents/postmaster/message_schema.json` at send time.
  Never edited, never deleted (write-only; `open(..., "x")` enforces no
  overwrite).
- Read-state is per-role append-only cursor files (`mailroom/cursors/<role>.acked`).
- Idempotency keys are enforced at send (duplicate sends are dropped), hop
  limits at send, schema-invalid messages are rejected before they enter the
  ledger.
- Kill switch moves from per-clone `.mailroom/HALT` to shared `mailroom/HALT`;
  `ledger.py inbox` refuses while it exists.
- The message schema, intents, hop limits, untrusted-content fencing, and
  "git is truth" rule are unchanged. Email is gone; nothing else moved.

The ledger is transport, not truth: it lives outside every clone and is not
committed. Anything durable must still land in git/issues/ADRs.

## Consequences

- Easier: zero cost, zero external accounts, instant local delivery, the whole
  bus is greppable and auditable as plain files.
- Harder: single-box only — if agents ever move to separate machines, revisit
  (reversal condition: any role session leaves this box → RFC for a hosted
  queue or return to email).
- `postmaster.py` (IMAP/SMTP daemon + governed agent spawner) is not deleted
  but is dormant; its mail I/O no longer matches the transport. Porting its
  polling/governor/spawn loop to the ledger is filed as TASK-005.
- `.mailroom/outbox/`, `.mailroom/sent/` per-clone directories are obsolete for
  new work; `AGENTS.md` now instructs `ledger.py send` directly.
