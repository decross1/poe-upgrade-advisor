# results/ — committed benchmark runs

One JSON per (box, stack, display mode), produced by `../run_bench.py`.
Files here are append-only evidence: never edit, re-run instead.

## 2026-07-26-linux-arm64-headless-electron.json

- **Box**: org dev box, Ubuntu 24.04 arm64, 20 cores, 124 GB RAM, no display
  server, no GPU (software rasterization). **Not representative player
  hardware** (players: Windows x64 desktops).
- **Stack**: Electron 43.2.0, `--ozone-platform=headless --no-sandbox
  --disable-gpu`, nodeIntegration off, sandboxed renderer.
- **Why the Tauri leg is missing**: Tauri cannot run on this box — WebKitGTK
  needs a display server (none; no sudo to install Xvfb), and building needs
  a Rust toolchain + `libwebkit2gtk-4.1-dev` (no sudo for either). See
  ADR-0004; the provisioned-box run is tracked as a follow-up issue.
- **Headless caveats** (see ../README.md): clipboard_read_ms is a floor (no
  real clipboard server); render_ms is inflated by software raster and has a
  ~2-vsync floor (~33 ms @60 Hz) from the double-rAF confirmation.

## 2026-08-03-capture-to-card-budget.md

- **Kind**: budget ledger, not a run JSON — one row per capture→card segment
  (issue #79 / I6) with number, source, and conditions, including the two
  segments NOT measured by that stage: the backend-owned server /diff call and
  the CLIPBOARD_POLL_MS=100 detection lag (0–100 ms, mean ~50 ms).
- **Box**: same org dev box as the 2026-07-26 run (Ubuntu 24.04 arm64,
  20 cores, headless). Node v22.22.2, vitest 2.1.9, node environment.
- **New measurement**: shell overhead — clipboard sample observes item text →
  VERDICT ShellState at onState — ≤0.09 ms per golden fixture against a 20 ms
  budget, from overlay/test/captureLatency.test.ts (real pipeline composition;
  only clipboard source and postDiff stubbed).
- **No I6 claim**: the record states explicitly that no end-to-end p95
  < 300 ms follows from it, and names what remains to be measured.
