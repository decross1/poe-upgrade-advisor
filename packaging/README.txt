PoE Upgrade Advisor — MVP v0 (test build)
==========================================

WHAT THIS IS
  A local web page: paste your Path of Building build, pick an item,
  and get an honest UPGRADE / SIDEGRADE / DOWNGRADE / CAN'T EVALUATE
  verdict against the build you imported. Verdicts are LIVE
  calculations — the real Path of Building engine is bundled inside
  (engine/), not canned answers. Everything runs on your own machine
  (127.0.0.1); nothing you do in the tool leaves your computer.
  (The in-game hotkey overlay ships in a later build; this v0 page
  stands in for it.)

REQUIREMENTS
  - Windows 10/11 x86-64: the bundled engine's runtime is compiled for
    it. On any other platform the launcher stops with an honest
    "engine cannot start" message rather than guessing.
    (Dev note: Linux x86-64 builds are for development/CI only and are
    not a supported player platform.)
  - Python 3.10 or newer: https://www.python.org/downloads/
    (the python.org installer's "py" launcher is what run.bat looks
    for first)
  - ~400 MB free disk (the engine unpacks a one-time data cache on
    first launch, which is also why first launch takes tens of seconds).
  - An internet connection ONCE, on first run only, to fetch one small
    Python dependency into a private folder (.venv/) if your Python
    doesn't have it already. No other tooling, no npm, no compiler.

RUN
  Windows: double-click "run.bat"
  (Dev/CI only, Linux: ./run.sh)

  Your browser opens http://127.0.0.1:47791/ — that's the whole app.
  Stop it with Ctrl+C in the terminal window.

  If the browser doesn't open by itself, visit that address manually.

FIRST VERDICT (zero config)
  1. Paste your Path of Building code into the import box.
  2. Pick an item (hotkey overlay lands in a later build; the v0 page
     stands in for it).
  3. Read the verdict card. Tap any assumption chip to flip it and
     recompute — that's the point of the tool; try to break it.

REPORTING A WRONG VERDICT
  /suggest in #poe with your PoB code and the item's Ctrl+C text.
  Your report becomes a permanent test fixture before the fix merges.

PRIVACY / SAFETY
  v0 reads nothing from the game — you paste into a localhost page.
  The upcoming overlay will read only clipboard text the game itself
  produces on Ctrl+C and the Client.txt log. No memory reads, no
  injection, no input automation, one action per keypress.
  Binds localhost only.
