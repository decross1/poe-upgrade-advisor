#!/usr/bin/env bash
# TASK-208: one-command MVP v0 distributable — real engine inside.
#
# ADR-0004 fallback applies: the native shell (Tauri leg) is unproven on the
# dev box (issue #34), so v0 ships the web bundle + local API + the real PoB
# calc engine + launcher. Produces dist/poe-upgrade-advisor-v0-<sha>.tar.gz.
#
# PLATFORM (issue #75, 2026-07-26): the product is WINDOWS-ONLY — this
# Linux tarball is a dev/CI-only artifact now; the tester-facing Windows
# zip is built by scripts/package_mvp_windows.ps1 (run.bat entrypoint).
# macOS is dropped entirely: no macOS entrypoint or copy anywhere.
# The tarball contains everything needed except python3 itself (run.sh
# bootstraps the rest).
#
# Packaging-machine prerequisites (NOT tester prerequisites): npm, git,
# cc + make (only for engine/runtime/build.sh, whose output is shipped
# prebuilt). Testers need no dev tooling.
#
# PLATFORM: the pinned Lua runtime (engine/.runtime) is compiled for the
# packaging machine's platform — Linux x86-64 from CI/this repo. The engine
# worker itself (engine/pobcalc) runs through the bundle's Python interpreter.
# Testers without a native pinned Lua runtime get an honest launcher error,
# not fixture verdicts (I5).
#
# Usage: scripts/package_mvp.sh [--skip-web-build]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

SKIP_WEB_BUILD=0
[ "${1:-}" = "--skip-web-build" ] && SKIP_WEB_BUILD=1

if [ "$SKIP_WEB_BUILD" -eq 0 ]; then
  echo "== building web bundle (npm ci && npm run build)"
  (cd web && npm ci --no-audit --no-fund && npm run build)
fi
[ -f web/dist/index.html ] || { echo "error: web/dist missing; run without --skip-web-build" >&2; exit 1; }

# --- Engine prerequisites (packaging machine only) -------------------------
VENDOR=engine/vendor/PathOfBuilding
if [ ! -f "$VENDOR/src/HeadlessWrapper.lua" ]; then
  echo "== initializing vendored PathOfBuilding submodule"
  git submodule update --init "$VENDOR"
fi
echo "== ensuring pinned Lua runtime (engine/runtime/build.sh; no-op if present)"
engine/runtime/build.sh
[ -x engine/.runtime/bin/luajit ] || { echo "error: engine/.runtime/bin/luajit missing after build" >&2; exit 1; }

NAME="poe-upgrade-advisor-v0"
STAGE="dist/$NAME"
SHA="$(git rev-parse --short HEAD)"

echo "== staging $STAGE"
rm -rf "$STAGE"
mkdir -p "$STAGE/web" "$STAGE/engine/.runtime" "$STAGE/engine/vendor/PathOfBuilding"

# API + data (runtime dep: pyyaml only; see packaging/run.sh).
cp -r server "$STAGE/server"
cp -r assumptions "$STAGE/assumptions"

# Real engine: worker entrypoint, Lua adapter, preset/timeless helpers the
# server imports and the worker shells out to.
cp engine/pobcalc engine/pobcalc.lua engine/preset_config.py engine/timeless_cache.py "$STAGE/engine/"
chmod +x "$STAGE/engine/pobcalc"

# Pinned Lua runtime, PREBUILT — testers never need cc/make/git. The local
# timeless-data cache (engine/.runtime/timeless-data, ~67M decompressed) is
# deliberately NOT shipped: timeless_cache.py regenerates it from the
# vendored zips on the tester's first run.
cp -r engine/.runtime/bin engine/.runtime/lib engine/.runtime/share engine/.runtime/manifest \
  "$STAGE/engine/.runtime/"

# Vendored PoB: the headless calc needs src/ and runtime/lua only. TreeData
# GUI sprites (*.png/*.jpg/*.webp, ~400M) are excluded — HeadlessWrapper
# stubs image handles and PoB skips missing sprite files without any network
# fetch (main.allowTreeDownload is disabled upstream). All tree.lua /
# sprites.lua / Assets.lua data files for EVERY tree version ship so any
# tester build imports, current league or legacy. runtime/{*.dll,
# SimpleGraphic} is the Windows GUI host — not used headless.
tar -cf - -C "$VENDOR" \
  --exclude='src/TreeData/*.png' \
  --exclude='src/TreeData/*.jpg' \
  --exclude='src/TreeData/*.webp' \
  --exclude='src/TreeData/*/*.png' \
  --exclude='src/TreeData/*/*.jpg' \
  --exclude='src/TreeData/*/*.webp' \
  --exclude='./.git' \
  src runtime/lua LICENSE.md | tar -xf - -C "$STAGE/engine/vendor/PathOfBuilding"

# Prebuilt bundle — testers never touch npm.
cp -r web/dist/. "$STAGE/web/"

# Launcher + tester docs. Linux dev/CI tarball: run.sh entrypoint (run.bat
# rides along as documentation of the Windows zip's entrypoint; macOS is
# dropped — issue #75).
cp -r packaging "$STAGE/packaging"
cp packaging/run.sh "$STAGE/run.sh"
cp packaging/run.bat "$STAGE/run.bat"      # Windows zip entrypoint (see package_mvp_windows.ps1)
chmod +x "$STAGE/run.sh"
cp packaging/README.txt "$STAGE/README.txt"

# Never ship caches, a previous bootstrap venv, or repo-side test files.
find "$STAGE" -type d \( -name __pycache__ -o -name .venv \) -prune -exec rm -rf {} +
rm -f "$STAGE"/packaging/test_launch.py   # repo-side smoke test, not for testers

TARBALL="dist/$NAME-$SHA.tar.gz"
tar -czf "$TARBALL" -C dist "$NAME"
echo "== wrote $TARBALL ($(du -h "$TARBALL" | cut -f1))"
echo "   clean-room check: extract elsewhere, ./run.sh, open http://127.0.0.1:47791/"
