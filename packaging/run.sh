#!/bin/sh
# PoE Upgrade Advisor — MVP v0 launcher (TASK-208).
# `./run.sh` on the Linux dev/CI tarball (the tester-facing build is the
# Windows zip with run.bat; macOS is dropped — issue #75). No dev tooling
# needed: uses the system python3 and bootstraps its one dependency into a
# private venv.
set -eu
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
command -v "$PYTHON" >/dev/null 2>&1 || {
  echo "error: python3 not found. Install Python 3.10+ from https://www.python.org/" >&2
  exit 1
}

# Fast path: pyyaml already importable — run straight off the system python.
if "$PYTHON" -c "import yaml" 2>/dev/null; then
  exec "$PYTHON" packaging/launch.py --open "$@"
fi

# Slow path (first run only): private venv + the server's one dependency.
if [ ! -x .venv/bin/python ]; then
  echo "first run: creating a private Python environment (.venv/)..."
  "$PYTHON" -m venv .venv
  .venv/bin/pip install --quiet --disable-pip-version-check "pyyaml>=6.0" || {
    echo "error: could not install pyyaml (needs an internet connection, once)." >&2
    exit 1
  }
fi
exec .venv/bin/python packaging/launch.py --open "$@"
