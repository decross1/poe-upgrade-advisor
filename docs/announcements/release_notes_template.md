<!--
RELEASE NOTES TEMPLATE — copy per release, fill every <placeholder>, strip
this comment before publishing as a GitHub Release / #poe announcement.

Platform rules (decision on issue #75, 2026-07-26, not negotiable in copy):
  - Windows x86-64 is the ONLY supported player platform. Install steps are
    Windows steps.
  - macOS is dropped — never mentioned, not even as "coming later".
  - Linux appears only as a dev/CI note, never as a player install path.
  - Unsupported platforms must be described as hitting the honest
    "engine cannot start on this machine" failure — never as "untested".
-->

# PoE Upgrade Advisor <vX.Y.Z>

<One sentence: what this release gives the player.>

## Highlights

- <user-visible change, one line each>

## Install & run (Windows)

1. **Download** `<asset-name>.zip`:
   <https://github.com/decross1/poe-upgrade-advisor/releases/download/<tag>/<asset-name>.zip>
2. **Extract it anywhere** (right-click → Extract All…), then open the folder.
3. **Run it:** double-click `run.bat`.
4. Your browser opens `http://127.0.0.1:47791/` — paste your Path of Building
   code, pick an item, read the verdict.
5. Stop it with `Ctrl+C` in the terminal window.

**You need:** Windows 10/11 x86-64 · Python 3.10+ (the python.org `py`
launcher) · ~<N> MB free disk · internet once on first run if `pyyaml` is
missing. On any other platform the launcher stops with an honest "engine
cannot start on this machine" message instead of guessing.

*Dev note: Linux x86-64 builds (`run.sh`) exist for development and CI only
and are not a supported player platform.*

## Upgrade from <previous tag>

<steps, or "extract the new zip anywhere and run it — your imports are not
carried over, re-import your PoB code">

## Fixed

- <bug fix, one line each, link issue>

## Known limitations

- <carried + new limitations; keep the CAN'T EVALUATE honesty paragraph from
  mvp_launch.md in every release that ships the verdict card>

## Report a wrong verdict

`/suggest` in #poe with your **PoB code** and the **item text** (`Ctrl+C`
output). Wrong-assumption reports become permanent test fixtures before the
fix merges.
