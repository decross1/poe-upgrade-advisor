PoE Upgrade Advisor — MVP v0 (test build)
==========================================

WHAT THIS IS
  A local app with an in-game hotkey overlay: import your Path of
  Building build, copy an item, and get an honest UPGRADE / SIDEGRADE /
  DOWNGRADE / CAN'T EVALUATE verdict against the build you imported.
  Verdicts are LIVE
  calculations — the real Path of Building engine is bundled inside
  (engine/), not canned answers. Everything runs on your own machine
  (127.0.0.1); nothing you do in the tool leaves your computer.
  A complete build includes overlay/PoEUpgradeAdvisorOverlay.exe. If
  overlay/OVERLAY-STUB.txt is present instead, this is an explicit stub
  build: the launcher reports that no overlay is included and the local
  web page remains available.

REQUIREMENTS
  - Windows x86-64: this is the shipping platform (decision 2026-07-26,
    issue #75). The bundled engine's runtime is compiled for it. If the
    engine runtime in your download is still a stub (early fast-follow
    zips), the launcher stops with an honest "engine cannot start"
    message rather than guessing — grab the latest zip; the Windows
    runtime is wired in as issue #75 lands. Linux tarballs are for the
    dev/CI pipeline only. macOS is dropped entirely — it will not ship.
  - Python 3.10 or newer: https://www.python.org/downloads/
    (the python.org installer's "py" launcher is what run.bat looks for
    first, then python3, then python on PATH)
  - ~400 MB free disk (the engine unpacks a one-time data cache on
    first launch, which is also why first launch takes tens of seconds).
  - An internet connection ONCE, on first run only, to fetch one small
    Python dependency into a private folder (.venv/) if your Python
    doesn't have it already. No other tooling, no npm, no compiler.

RUN
  Windows: double-click "run.bat"  (THE entrypoint)
  Linux:   ./run.sh                 (dev/CI tarball only)

  The overlay starts automatically with run.bat. Its default hotkey is
  Ctrl+Alt+D; set OVERLAY_HOTKEY before launch to override it. Showing
  the card never steals game focus, and "open details" opens the browser
  page. Use "run.bat --no-overlay" to run the web page alone.

  Your browser opens http://127.0.0.1:47791/ for the full app.
  Stop it with Ctrl+C in the terminal window.

  If the browser doesn't open by itself, visit that address manually.

FIRST VERDICT (zero config)
  1. Paste your Path of Building code into the import box.
  2. In Path of Exile, hover an item and press Ctrl+C, then press
     Ctrl+Alt+D (or your OVERLAY_HOTKEY override) to show the verdict.
     The overlay starts automatically with run.bat and never steals game
     focus. Use "open details" for the browser page, or start with
     "run.bat --no-overlay" to use that page alone.
  3. Read the verdict card. Tap any assumption chip to flip it and
     recompute — that's the point of the tool; try to break it.

REPORTING A WRONG VERDICT
  /suggest in #poe with your PoB code and the item's Ctrl+C text.
  Your report becomes a permanent test fixture before the fix merges.

PRIVACY / SAFETY
  The overlay reads only clipboard text the game itself produces on
  Ctrl+C and the Client.txt log. No memory reads, no injection, no input
  automation, and one action per explicit keypress. The app binds
  localhost only; nothing is sent to a remote service.
