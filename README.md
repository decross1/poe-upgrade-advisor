# PoE Upgrade Advisor

**Path of Building's math. Raidbots' simplicity. Built and maintained by an autonomous three-agent org.**

An overlay + web tool for Path of Exile that answers one question instantly — *"is this item an upgrade?"* — with zero configuration, powered by the full Path of Building calculation engine underneath, and offering progressive disclosure into deep build analysis for those who want it.

This repository is also an **agent-native organization**: a PM/Architect agent (Claude Code), a Backend agent (Codex CLI), and a Frontend agent (Kimi Code CLI) coordinate via a structured append-only message ledger, work in git, adversarially review each other, and ship without human-in-the-loop approvals. Humans set budgets and hold a kill switch; nothing else waits on a human.

---

## The product in one paragraph

Player presses `Ctrl+C` over an item in-game (PoE copies hovered item text to the clipboard — the same ban-safe mechanism Awakened PoE Trade uses). The overlay parses the text, sends it to a local server that holds the player's imported build, swaps the item into a copy of the build, reruns Path of Building's calc engine headlessly, and renders a verdict card: **UPGRADE / SIDEGRADE / DOWNGRADE**, two bars (offense/defense), and one generated sentence explaining *why*. An **Assumptions Engine** infers all PoB configuration (main skill, boss vs mapping scenario, conditional mods) so the user never touches a settings screen — every assumption is visible on the card and reversible in one tap. A full web UI offers stash-wide upgrade scans, tree planning ("best next 5 points"), and the raw PoB breakdown.

## Non-negotiable safety constraints (game ToS)

1. **Clipboard only.** We read item text that the game itself puts on the clipboard via `Ctrl+C`. We never read process memory, never inject, never hook the client.
2. **One server action per user keypress.** No automation of game actions.
3. Overlay is a separate always-on-top window; game runs in windowed-fullscreen.

Any PR that violates these is rejected by policy (see `PRODUCT_DOCTRINE.md` §Safety).

## Repository map

```
PRODUCT_DOCTRINE.md      CI-enforceable UX invariants — the product's constitution
ARCHITECTURE.md          Components, the L0–L6 loop map, security model
AGENTS.md                Shared operating rules every agent loads on every invocation
CLAUDE.md                Pointer file so Claude Code loads AGENTS.md + its role
agents/roles/            Role prompts: pm.md, backend.md, frontend.md
agents/postmaster/       Message transport: ledger.py (append-only filesystem bus, ADR-0002)
agents/governor/         Budget governor: quotas, backoff, circuit breaker, dead-letter
agents/merge_robot/      The only identity that can merge. Spec + implementation.
contracts/               OpenAPI + JSON Schemas. PM-owned. FE/BE code against these.
assumptions/             The Assumptions Engine: rules, scenario presets, fixtures
engine/                  Headless PoB wrapper (PoB as git submodule) — Phase 1 spike
server/                  Local API service (build state, diff, scan, explain)
overlay/                 Hotkey + clipboard + verdict card (Tauri/Electron)
web/                     Full profile UI
bot/                     Discord intake bot (untrusted-input firewall)
docs/adr/                Architecture Decision Records (agent rulings live here)
docs/rfc/                RFCs for contract-level changes
docs/REVIEW_PROTOCOL.md  Adversarial review: evidence-based, bounded, arbitrated
tasks/BACKLOG.md         Phased backlog with acceptance criteria (TASK-ids)
scripts/                 CI checks incl. doctrine invariant checker
```

## Boot sequence (one-time human setup, ~1 evening)

1. **Repo**: create a GitHub repo, push this scaffold. Add the PoB engine:
   `git submodule add https://github.com/PathOfBuildingCommunity/PathOfBuilding engine/vendor/PathOfBuilding`
2. **Ledger**: create a shared `mailroom/` directory beside the role clones (e.g. `<project>/mailroom/`). No accounts, no credentials — messages are append-only JSON files written/read via `agents/postmaster/ledger.py` (ADR-0002).
3. **Agent CLIs** on the worker box (can be one machine, three git worktrees):
   - Claude Code (Claude Max login) — PM/Architect
   - Codex CLI (ChatGPT login) — Backend
   - Kimi Code CLI (Kimi login) — Frontend
   Verify each CLI's current headless/non-interactive flags and put the exact command templates in `config.yaml` (`{prompt_file}` placeholder). **Check each vendor's ToS for automated use and whether headless invocations bill outside your subscription — set governor caps accordingly.**
4. **Identities**: create three GitHub machine users (or fine-grained PATs) with *branch-push only* rights, plus one for the merge robot with merge rights. Branch protection on `main`: only the merge robot can merge; required checks per `.github/workflows/ci.yml`.
5. **Governor**: review `agents/governor/policy.yaml` caps — this is your spend firewall.
6. **Sessions**: run each role's CLI session (interactive, or cron-woken with a prompt that says "process your ledger inbox per AGENTS.md"). Heartbeat prompts make each agent check its assigned issues even with an empty inbox.
7. **Discord**: create the bot (see `bot/README.md`), point it at `intake@` and the repo, invite it, create the `#suggestions` forum and `#dev-log` channels.
8. **Ignition**: append the bootstrap message in `tasks/BACKLOG.md` §Ignition to the ledger addressed to `pm`. The PM triages Phase 0/1 tasks and the org starts running.

## Human controls (the only two)

- **Kill switch**: `touch <project>/mailroom/HALT` (ledger inbox refuses all reads) and/or revoke the merge robot token.
- **Budgets**: `agents/governor/policy.yaml`.

Everything else — planning, coding, review, arbitration, merging, releasing, community triage — is agent-driven per `docs/REVIEW_PROTOCOL.md` and `ARCHITECTURE.md`.

## License

MIT for this repository. Path of Building is included as a submodule under its own MIT license; we vendor it unmodified and interact via its headless entry point.
