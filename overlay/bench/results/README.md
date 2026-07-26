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
