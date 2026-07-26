#!/usr/bin/env bash
# TASK-208: one-command MVP v0 distributable.
#
# ADR-0004 fallback applies: the native shell (Tauri leg) is unproven on the
# dev box (issue #34), so v0 ships the web bundle + local API + launcher.
# Produces dist/poe-upgrade-advisor-v0-<sha>.tar.gz containing everything a
# tester needs except python3 itself (run.sh bootstraps the rest).
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

NAME="poe-upgrade-advisor-v0"
STAGE="dist/$NAME"
SHA="$(git rev-parse --short HEAD)"

echo "== staging $STAGE"
rm -rf "$STAGE"
mkdir -p "$STAGE/web" "$STAGE/contracts"

# API + data (runtime dep: pyyaml only; see packaging/run.sh).
cp -r server "$STAGE/server"
cp -r assumptions "$STAGE/assumptions"
cp -r contracts/fixtures "$STAGE/contracts/fixtures"

# Prebuilt bundle — testers never touch npm.
cp -r web/dist/. "$STAGE/web/"

# Launcher + tester docs.
cp -r packaging "$STAGE/packaging"
cp packaging/run.sh "$STAGE/run.sh"
cp packaging/run.sh "$STAGE/run.command"   # macOS double-click
cp packaging/run.bat "$STAGE/run.bat"      # Windows double-click
chmod +x "$STAGE/run.sh" "$STAGE/run.command"
cp packaging/README.txt "$STAGE/README.txt"

# Never ship caches or a previous bootstrap venv.
find "$STAGE" -type d \( -name __pycache__ -o -name .venv \) -prune -exec rm -rf {} +
rm -f "$STAGE"/packaging/test_launch.py   # repo-side smoke test, not for testers

TARBALL="dist/$NAME-$SHA.tar.gz"
tar -czf "$TARBALL" -C dist "$NAME"
echo "== wrote $TARBALL ($(du -h "$TARBALL" | cut -f1))"
echo "   clean-room check: extract elsewhere, ./run.sh, open http://127.0.0.1:47791/"
