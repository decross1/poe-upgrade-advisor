PoE Upgrade Advisor — MVP v0 (test build)
==========================================

WHAT THIS IS
  A local tool: hover an item in Path of Exile, and get an honest
  UPGRADE / SIDEGRADE / DOWNGRADE / CAN'T EVALUATE verdict against the
  build you imported. Everything runs on your own machine (127.0.0.1);
  nothing you do in the tool leaves your computer.

REQUIREMENTS
  - Python 3.10 or newer: https://www.python.org/downloads/
    (macOS: the system python3 works; Windows support is coming)
  - An internet connection ONCE, on first run only, to fetch one small
    Python dependency into a private folder (.venv/). No other tooling,
    no npm, no dev environment.

RUN
  macOS:  double-click "run.command"
          (if Gatekeeper blocks it: right-click -> Open -> Open)
  Linux:  ./run.sh

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
  Reads only clipboard text the game itself produces on Ctrl+C and the
  Client.txt log. No memory reads, no injection, no input automation,
  one action per keypress. Binds localhost only.
