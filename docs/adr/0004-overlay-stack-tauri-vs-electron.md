# ADR-0004: Overlay stack — Tauri v2 provisional, Electron fallback, decision thresholds pre-registered

- Status: proposed (auto-accepts to `accepted` when the follow-up provisioned-box run lands and confirms the thresholds below)
- Date: 2026-07-26
- Task: TASK-201 / issue #9
- Deciders: frontend (owner), review by backend per L1

## Context

The overlay stack is hard to reverse; Doctrine I6 demands data, not taste. The
frontend charter states "Tauri preferred; decide via ADR in TASK-201."
TASK-201's acceptance criteria: a committed benchmark harness (cold start,
memory, overlay latency) and an ADR with numbers and a reversal condition.

**What was measured on this box** (Ubuntu 24.04 arm64, 20c/124GB, headless,
software raster — dev box, *not* player hardware). Harness:
`overlay/bench/`; evidence: `overlay/bench/results/2026-07-26-linux-arm64-headless-electron.json`
(15 cold starts, 600 renders, Electron 43.2.0, identical I2 card UI + fixtures
both stacks share):

| metric | p50 | p95 |
|---|---|---|
| cold start, spawn→paint (external) | 232 ms | 250 ms |
| cold start, main-entry→paint (internal) | 110 ms | 126 ms |
| render, trigger→frame committed | 31.7 ms | 32.8 ms |
| clipboard read (headless floor, not representative) | 0.01 ms | 0.01 ms |
| steady memory (process-tree PSS / RSS-sum) | 195 MB / 494 MB | — |

**The Tauri leg could not run on this box**: WebKitGTK requires a display
server (none; no sudo for Xvfb) and building requires a Rust toolchain +
`libwebkit2gtk-4.1-dev` (no sudo for either). Pretending otherwise would
masquerade a degraded path as the primary one, so the Tauri variant ships
unbuilt-but-complete (`overlay/bench/tauri/`, one `cargo build --release` +
`xvfb-run` away on a provisioned box) and its numbers are pending, tracked by
the follow-up issue.

## Decision

1. **Tauri v2 is the provisional overlay stack.** Rationale: the charter's
   standing preference; footprint matters for an always-resident overlay
   (Electron idles at ~195 MB PSS for one 420×260 card here); Tauri's system
   webview (WebView2, present on every supported Windows) avoids shipping a
   second Chromium. Development continues stack-agnostic by construction: the
   card UI (`overlay/bench/shared/`) runs on both stacks today and is the seed
   of the production card.
2. **Electron is the designated fallback and the interim dev/CI stack** — it
   is proven on this box, meets the ≤50 ms render budget (p95 32.8 ms even
   under software rasterization), and runs headless, which Tauri never will.
3. **Pre-registered thresholds** for the provisioned-box run (same harness,
   same box, real display, both legs — the human's Windows game box is the
   natural reference for I6). Tauri is confirmed iff all hold:
   - cold start p95 ≤ Electron p95 on that box,
   - render p95 ≤ 50 ms (frontend charter budget),
   - steady PSS ≥ 30 % below Electron's on that box.
4. **Reversal condition.** If the provisioned run fails any threshold, or
   Tauri/WebView2 proves operationally broken for this card UI (rendering
   defects, clipboard or always-on-top APIs missing on a supported platform,
   toolchain unbuildable in CI), the stack **reverses to Electron** by
   amendment of this ADR — no new doctrine needed; the harness and Electron
   numbers above already satisfy I6's data requirement for that fallback.

## Consequences

- Easier: verdict-card UI work (the PM's queued TASK_ASSIGN) starts
  immediately against `shared/` with zero stack lock-in; the final stack
  decision reduces to one mechanical harness run with pre-agreed thresholds —
  no second taste debate.
- Harder: the Tauri leg's first `cargo build` may need trivial fixes
  (authored blind, flagged in `overlay/bench/README.md`); the provisional
  state persists until the provisioned run lands.
- Follow-up filed: provisioned-box run of both legs (needs a display-capable
  box — PM to route).
