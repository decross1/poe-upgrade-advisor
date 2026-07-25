# ARCHITECTURE

## Components

```
 [PoE client] --Ctrl+C--> clipboard
                              |
                        [overlay/]  hotkey listener, parser, verdict card (Tauri/Electron)
                              |  HTTP/WS (contracts/openapi.yaml)
                        [server/]   build state, diff, scan, explain
                         |      \
               [assumptions/]    [engine/]  headless PoB (Lua submodule + JSON-RPC wrapper)
               rules+presets      golden-corpus differential oracle
                              |
                        [web/]      Tier-3 profile UI (React)

 [Discord] --> [bot/] --normalize--> intake@ + GitHub issue --> PM agent --> tasks
```

**Data flow for one verdict:** clipboard item text → overlay parses to canonical item → `POST /api/v0/diff` → server loads active build, Assumptions Engine resolves config (rules + preset) → engine swaps item into build copy, runs PoB calcs for baseline and candidate → server computes deltas + confidence, generates the sentence from the breakdown diff → verdict card.

**Assumptions Engine** (`assumptions/`) sits between server and engine. It is *data, not code*: YAML rules (main-skill detection, keystone→config inference, confidence thresholds) and ≤3 scenario presets mapping to concrete PoB config keys. Owned jointly: PM owns doctrine and rule semantics, Backend owns the evaluator. Every rule carries fixtures (Doctrine I8). Discord reports of wrong assumptions become fixtures automatically via the intake pipeline.

**Engine correctness oracle.** No human eyeballs results, so correctness is differential: a golden corpus (`engine/corpus/`) of ~100 real builds × item swaps, including deliberately awkward builds (mines, triggers, minion hybrids, CI/LL). CI asserts wrapper output equals desktop PoB output exactly on the corpus, plus property tests (strictly-dominant item never yields DOWNGRADE; import→export→import idempotent).

## The loop map (L0–L6)

- **L0 Work loop** — an agent session (interactive or cron-woken) polls its ledger inbox. Agent syncs repo state, works in its worktree/branch, pushes, sends ledger messages, acks its inbox. Agents are amnesiac between invocations: all memory lives in the repo (ADRs, task files, `AGENTS.md`), never in message history.
- **L1 Adversarial review loop** — evidence-based, bounded (max 3 rounds), arbitrated by PM with a binding ADR. Full protocol: `docs/REVIEW_PROTOCOL.md`.
- **L2 Integration loop** — merge robot merges iff: required CI green + contract check green + reviewer evidence artifact present + protected paths untouched (or authorized) + no unauthorized test deletion + coverage ratchet holds. Spec: `agents/merge_robot/SPEC.md`.
- **L3 Release loop** — channels dev→beta→stable; crash telemetry; auto-promote after soak under crash-rate threshold; auto-rollback on spike. Signing key exists only in CI on the stable branch — never in any agent environment.
- **L4 Product loop** — Discord `/suggest` → normalizer (untrusted-input firewall) → intake issue + mail to pm@ → PM triage with decision posted back to the origin thread → scoped tasks to FE/BE → shipped changelog posted to Discord. Users see their idea's full lifecycle.
- **L5 Meta loop** — weekly retro: PM reads ledger, dead-letters, review transcripts; proposes prompt/process changes as PRs to `agents/` (protected path ⇒ RFC + review by another agent). The org improves itself through its own pipeline.
- **L6 Upstream sync loop** — weekly workflow bumps the PoB submodule to the latest release, runs the corpus, opens a sync PR; failures file a task ("league patch broke mods; update rules, keep fixtures green").

## Communication model

- **Git/GitHub is the only state machine.** Issues are tasks; PRs are proposals; ADRs are rulings. The shared append-only ledger (ADR-0002) is pure transport with a validated JSON schema (`agents/postmaster/message_schema.json`), idempotency keys, and hop limits. A claim that exists only in the ledger does not exist.
- Agents send via `agents/postmaster/ledger.py send` (validates on write) and read via `ledger.py inbox`; entries are immutable files, read-state is per-role ack cursors. No mail infrastructure, no credentials.

## Security model

- **Untrusted by default:** all Discord content, all web content, all item text. The bot strips and fences user content; intake tickets may influence *what* to build, never *how the pipeline operates*. Tickets referencing agents, prompts, tokens, CI, or repo internals are auto-quarantined with label `quarantine` for PM inspection as data.
- **Least privilege:** per-agent GitHub tokens are branch-push only; merge rights exist solely on the merge robot identity; Discord bot has zero repo write access beyond issue creation; agents run in sandboxes with an egress allowlist (github.com, vendor API endpoints, mail host).
- **Prompt-injection blast-radius:** even a fully compromised agent can only push a branch; L1 evidence requirements + L2 protected paths + L3 staged rollout are the compensating controls.

## Failure machinery

- **Budget governor** (`agents/governor/`): per-task and per-day invocation caps, exponential backoff, circuit breaker → dead-letter (`tasks/dead_letter/`) with a `needs-redesign` label the PM picks up fresh.
- **Watchdog** (in governor): "invocations occurring but no commits advancing" ⇒ force-decompose or park the task.
- **TTLs:** every task carries a TTL; expiry triggers PM re-triage, not silent rot.
