# 2026-08-03 — capture→card budget (issue #79 / I6)

One row per segment of the clipboard→verdict-card path, with its number,
source, and measurement conditions. Segments this stage did not measure are
marked **NOT measured** — stated, not estimated.

- **Box**: org dev box, Ubuntu 24.04.4 arm64, 20 cores, 121 GB RAM, headless.
  **Not representative player hardware** (players: Windows x64 desktops).
- **Conditions for the new measurement**: Node v22.22.2, vitest 2.1.9, node
  environment (no jsdom, no Electron), `postDiff` stubbed to resolve each
  golden fixture immediately (zero network/server time), watcher driven by
  direct `pollNow()` calls (zero polling wait).

## Segments

| # | Segment | Number | Source | Status |
|---|---------|--------|--------|--------|
| 1 | Clipboard change → next poll tick (detection lag) | 0–100 ms, mean ~50 ms | `CLIPBOARD_POLL_MS = 100` in `overlay/src/clipboardWatcher.ts` | **NOT measured** — structural charge of the polling design (Electron exposes no clipboard-change event); bounds follow from the constant |
| 2 | Poll observes item text → VERDICT `ShellState` at `onState` (shell overhead) | ≤ 0.09 ms per golden fixture (max 0.09, min 0.01), budget 20 ms | `overlay/test/captureLatency.test.ts` (this stage) | **Measured** on this box; real `createClipboardPipeline` composition, only clipboard source + `postDiff` stubbed |
| 3 | Server `POST /diff` (backend-owned) | — | backend owns this segment | **NOT measured** by this stage |
| 4 | Response receipt → committed card (render) | < 50 ms per golden fixture (asserted) | `overlay/test/renderBudget.test.tsx` | Measured (headless jsdom assertion, standing) |
| 5 | Trigger → frame, native stack | p95 32.8 ms | `2026-07-26-linux-arm64-headless-electron.json` (ADR-0004) | Measured on this box under software rasterization; see that file's caveats |

## Segment 2 detail (the new number)

Per-fixture elapsed ms from the `pollNow()` that observes the new item text
to the VERDICT state arriving at `onState`, as logged by the test run on this
box:

| Fixture | ms |
|---------|----|
| upgrade_mapping | 0.070 |
| sidegrade_bossing | 0.022 |
| downgrade_mapping | 0.020 |
| cant_evaluate_trigger_build | 0.089 |
| edge_degraded_minimal | 0.017 |
| upgrade_rich_assumptions_chip | 0.014 |
| sidegrade_balanced_low_confidence | 0.012 |

The 20 ms shell-overhead budget holds with ~200× headroom; no `overlay/src`
change follows from this stage. The measured span covers watcher header
detection, the session machine transition, and the `ShellState` projection +
delivery — the entire shell-owned share of capture→card.

## What this record does NOT claim (I5)

**No end-to-end capture→card p95 < 300 ms (I6) claim follows from this
artifact.** The segments above come from different harnesses and conditions,
two of them are unmeasured, and none ran on player hardware. Summing the
measured numbers is not an end-to-end p95. To make the I6 claim, still needed:

1. A measured server `POST /diff` p95 (backend-owned segment 3) under a warm
   engine.
2. The detection-lag distribution (segment 1) either accepted as its
   structural 0–100 ms bound or measured on a real Windows desktop.
3. All segments exercised together, end to end, on representative player
   hardware (Windows x64) in a single run — the perf smoke test I6 describes,
   which gates release promotion.
