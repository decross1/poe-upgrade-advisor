# overlay/bench — stack decision benchmark harness (TASK-201)

One-command, reproducible comparison of the two overlay stack candidates —
**Electron** vs **Tauri v2** — for ADR-0004 (Doctrine I6: decide with data,
not taste). Both variants render the **same** verdict card UI
(`shared/card.html|css|js`, Doctrine-I2-faithful) from the **same** fixtures
(`fixtures/verdict_*.json`, validated against `contracts/verdict.schema.json`
by `tests/test_bench_fixtures.py`).

## What it measures

| metric | definition |
|---|---|
| cold start | process spawn → first card painted (external wall clock), plus main-entry → paint (app-reported) |
| memory | steady-state + peak **process-tree** RSS, and PSS where the OS exposes it (Linux `smaps_rollup`) |
| render latency | trigger → **real platform clipboard read** → card updated and frame committed (double `requestAnimationFrame`), split into `clipboard_ms` (host) and `render_ms` (renderer) |

The render leg mirrors the production hotkey path (clipboard read → render).
No game, no network, no global hotkey registration is involved; the trigger
arrives over stdin instead of a hotkey so the harness runs headless and in CI
(Doctrine S1/S2 untouched: clipboard is read, never written, input is never
synthesized).

## Protocol (stack-neutral, JSON lines on stdio)

```
runner -> app : {"cmd":"render","seq":N,"fixture_name":"upgrade"}   # seq 0 = cold-start paint, no clipboard read
                {"cmd":"quit"}
app -> runner : {"bench":"cold_start","seq":0,"main_to_paint_ms":X,...}
                {"bench":"render","seq":N,"clipboard_ms":C,"render_ms":R}
```

## Running

### Electron (works headless)

```bash
npm install --prefix overlay/bench/electron
python3 overlay/bench/run_bench.py --stack electron --headless \
    --runs 15 --renders 40 --out overlay/bench/results/<box-name>.json
```

On a box **with** a display, drop `--headless` (real GPU + real window
manager + real clipboard; the honest mode for the final decision).

### Tauri (needs display + Rust toolchain + system webview)

Tauri has **no headless mode**: WebKitGTK/WebView2 require a display server.
On a provisioned Linux box:

```bash
sudo apt install libwebkit2gtk-4.1-dev libgtk-3-dev libayatana-appindicator3-dev  # + xvfb if headless
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
cd overlay/bench/tauri/src-tauri && cargo build --release
xvfb-run -a python3 ../../run_bench.py --stack tauri \
    --tauri-bin ./target/release/verdict-overlay-bench \
    --runs 15 --renders 40 --out ../../results/<box-name>.json
```

On Windows (the actual player platform; Tauri uses the ever-present WebView2):
install Rust, `cargo build --release`, run the same runner from PowerShell —
no Xvfb needed on a logged-in desktop.

`tauri/src-tauri/src/main.rs` was authored on a box with no Rust toolchain and
**has not been compiled yet**; expect trivial first-build fixes. This is
tracked in ADR-0004 and its follow-up issue.

### Compare

```bash
python3 overlay/bench/run_bench.py compare results/electron.json results/tauri.json
```

## Honest caveats (read before quoting numbers)

1. **Comparability**: numbers are only comparable across stacks when collected
   on the same box, same display mode. `--headless` Electron uses Chromium's
   offscreen ozone platform with software rasterization — fine for smoke/CI,
   but the deciding run must use a real display on representative hardware
   (players are on Windows x64).
2. **Clipboard in headless mode**: ozone-headless has no real clipboard
   server, so `clipboard_ms` there (~0) under-represents the real X11/Wayland/
   Win32 round-trip. Treat headless clipboard numbers as a floor.
3. **render_ms floor**: the double-rAF confirmation makes `render_ms` ≥ ~2
   vsync intervals (~33 ms at 60 Hz) regardless of stack; differences between
   stacks show up in the spread, not the floor.
4. **RSS vs PSS**: RSS is summed over the whole process tree and
   double-counts shared pages; PSS is the fairer cross-stack number where
   available.

Results are committed under `results/` with the box description in the
filename. Do not edit committed result files; re-run and commit new ones.
