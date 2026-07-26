#!/usr/bin/env bash
# TASK-208/#36 clean-room install check — simulates a tester machine:
# fresh extract dir, fresh HOME, env -i (no dev env vars), /usr/bin:/bin only.
# Nothing from the repo checkout is used except the tarball itself.
#
# Usage:  scripts/cleanroom_check.sh dist/poe-upgrade-advisor-v0-<sha>.tar.gz
# Exit 0 = every check passed; the full transcript is the evidence artifact.
#
# Legs: (1) fast path — system python3 with pyyaml runs launch.py directly;
#       (2) slow path — a shim python3 without third-party packages (-S)
#           triggers run.sh's first-run .venv bootstrap, then reuse on rerun.
# Both legs drive the same-origin stack end to end: statics, hashed asset
# MIME, SPA fallback, traversal guard, contract 404 semantics, build import,
# UPGRADE and CANT_EVALUATE diffs through the proxy, port-in-use error,
# clean stop + port release.
#
# Provenance: produced the clean-room evidence posted on issue #36 at
# 2026-07-26T08:28Z (tarball sha256:fe98da81..., transcript
# EVIDENCE-SHA256:166e8e15...). Reuse for the future non-dev-box run —
# passing on THIS box does NOT check issue #54's non-dev-box criterion.
set -uo pipefail

TARBALL="${1:?usage: cleanroom.sh <tarball>}"
WORK="$(mktemp -d /tmp/poe-cleanroom-run.XXXXXX)"
echo "WORK=$WORK"
echo "TARBALL=$TARBALL ($(du -h "$TARBALL" | cut -f1), sha256:$(sha256sum "$TARBALL" | cut -d' ' -f1))"
echo "date: $(date -u +%FT%TZ)"
echo

fail=0
check() { # check <name> <actual> <expected>
  if [ "$2" = "$3" ]; then echo "PASS: $1 ($2)"; else echo "FAIL: $1 (got '$2', want '$3')"; fail=1; fi
}

wait_listen() { # wait_listen <logfile> <pid>
  for _ in $(seq 1 60); do
    grep -q "listening on" "$1" 2>/dev/null && return 0
    kill -0 "$2" 2>/dev/null || return 1
    sleep 0.25
  done
  return 1
}

B="http://127.0.0.1:47791"

#############################
echo "=== LEG 1: fast path (system python3 has pyyaml) ==="
mkdir -p "$WORK/home1"
tar -xzf "$TARBALL" -C "$WORK"
cd "$WORK"/poe-upgrade-advisor-v0*
ls -1 | tr '\n' ' '; echo

env -i HOME="$WORK/home1" PATH=/usr/bin:/bin TERM=dumb ./run.sh >"$WORK/fast.log" 2>&1 &
APP=$!
if wait_listen "$WORK/fast.log" $APP; then
  echo "--- launcher output:"; cat "$WORK/fast.log"
else
  echo "FAIL: launcher did not report listening; log:"; cat "$WORK/fast.log"; exit 1
fi

sleep 0.6  # let the --open browser attempt settle so any noise lands in the log
echo "--- launcher output after --open settle:"
cat "$WORK/fast.log"

check "GET / status"            "$(curl -s -o /dev/null -w '%{http_code}' $B/)" 200
echo "GET / body marker: $(curl -s $B/ | grep -o 'mvp-stand-in' || echo '(no marker)') title: $(curl -s $B/ | grep -o '<title>[^<]*</title>')"
ASSET="$(curl -s $B/ | grep -o 'assets/[^"]*\.js' | head -1)"
check "GET /$ASSET status"      "$(curl -s -o /dev/null -w '%{http_code}' $B/$ASSET)" 200
case "$(curl -s -o /dev/null -w '%{content_type}' $B/$ASSET)" in text/javascript*) echo "PASS: asset content-type (text/javascript*)";; *) echo "FAIL: asset content-type"; fail=1;; esac
check "SPA fallback /tier3/x"   "$(curl -s -o /dev/null -w '%{http_code}' $B/tier3/whatever)" 200
TRAV_BODY="$(curl -s --path-as-is "$B/../server/app.py")"
echo "$TRAV_BODY" | grep -q "import" && check "traversal /../server/app.py leaks source" "yes" "no" || check "traversal serves index, no leak" "no-leak" "no-leak"
check "GET /api/v0/build (fresh, expect 404)" "$(curl -s -o /dev/null -w '%{http_code}' $B/api/v0/build)" 404
check "POST /api/v0/diff with no build (expect 404)" "$(curl -s -o /dev/null -w '%{http_code}' -X POST $B/api/v0/diff -H 'content-type: application/json' --data '{"item_text":"@fixture:upgrade_mapping"}')" 404
check "POST /api/v0/build" "$(curl -s -o "$WORK/build.json" -w '%{http_code}' -X POST $B/api/v0/build -H 'content-type: application/json' --data '{"pob_code":"@skill:Fireball;@tag:chill","character_class":"Witch","level":90}')" 200
echo "build main_skill: $(grep -o '"name": *"[^"]*"' "$WORK/build.json" | head -1)"
check "POST /api/v0/diff (@fixture:upgrade_mapping)" "$(curl -s -o "$WORK/verdict.json" -w '%{http_code}' -X POST $B/api/v0/diff -H 'content-type: application/json' --data '{"item_text":"Rarity: RARE\nDoom Wrap\n--------\nclean-room tester item\n@fixture:upgrade_mapping"}')" 200
echo "verdict card JSON: $(cat "$WORK/verdict.json")"
check "POST /api/v0/diff CANT_EVALUATE fixture renders honestly (I5)" "$(curl -s -o "$WORK/verdict_ce.json" -w '%{http_code}' -X POST $B/api/v0/diff -H 'content-type: application/json' --data '{"item_text":"@fixture:cant_evaluate_trigger_build"}')" 200
echo "cant-evaluate verdict: $(grep -o '\"verdict\": *\"[^\"]*\"' "$WORK/verdict_ce.json")"
check "GET /api/v0/build (after import)" "$(curl -s -o /dev/null -w '%{http_code}' $B/api/v0/build)" 200

echo "--- port-in-use: second instance while first runs"
env -i HOME="$WORK/home1" PATH=/usr/bin:/bin TERM=dumb ./run.sh >"$WORK/portbusy.log" 2>&1
RC=$?
check "second instance exit code nonzero" "$([ $RC -ne 0 ] && echo nonzero)" "nonzero"
echo "second instance says: $(cat "$WORK/portbusy.log")"

# NOTE: SIGINT cannot be exercised from this non-interactive driver (bash sets
# SIGINT to ignore in background children; Python honors that). Interactive
# Ctrl+C hits launch.py's KeyboardInterrupt handler (foreground flow). We stop
# background instances with SIGTERM and verify the port is released.
stop_app() { kill -TERM "$1" 2>/dev/null; for _ in $(seq 1 20); do kill -0 "$1" 2>/dev/null || return 0; sleep 0.2; done; kill -9 "$1" 2>/dev/null; }
stop_app $APP
check "SIGTERM stops launcher" "$(kill -0 $APP 2>/dev/null && echo alive || echo dead)" "dead"
sleep 0.3
check "port released after stop" "$(curl -s -o /dev/null -m 2 $B/ >/dev/null 2>&1 && echo open || echo refused)" "refused"
echo

#############################
echo "=== LEG 2: slow path (tester python3 WITHOUT pyyaml -> venv bootstrap) ==="
mkdir -p "$WORK/home2" "$WORK/shim" "$WORK/extract2"
cat > "$WORK/shim/python3" <<'SHIM'
#!/bin/sh
# Simulated tester python3: no third-party packages visible (-S drops dist-packages).
exec /usr/bin/python3 -S "$@"
SHIM
chmod +x "$WORK/shim/python3"
echo "shim check: shim-python import yaml -> $("$WORK/shim/python3" -c 'import yaml' 2>&1 | tail -1)"

tar -xzf "$TARBALL" -C "$WORK/extract2"
cd "$WORK/extract2"/poe-upgrade-advisor-v0*
env -i HOME="$WORK/home2" PATH="$WORK/shim:/usr/bin:/bin" TERM=dumb ./run.sh >"$WORK/slow.log" 2>&1 &
APP2=$!
if wait_listen "$WORK/slow.log" $APP2; then
  echo "--- launcher output (first run):"; cat "$WORK/slow.log"
else
  echo "FAIL: slow-path launcher did not report listening; log:"; cat "$WORK/slow.log"; exit 1
fi
check "venv created" "$([ -x .venv/bin/python ] && echo yes)" "yes"
check "GET / via venv python" "$(curl -s -o /dev/null -w '%{http_code}' $B/)" 200
curl -s -o /dev/null -X POST $B/api/v0/build -H 'content-type: application/json' --data '{"pob_code":"@skill:Fireball;@tag:chill","character_class":"Witch","level":90}'
check "POST /api/v0/diff via venv python (after import)" "$(curl -s -o /dev/null -w '%{http_code}' -X POST $B/api/v0/diff -H 'content-type: application/json' --data '{"item_text":"@fixture:upgrade_mapping"}')" 200
stop_app $APP2

echo "--- second run reuses venv (no reinstall expected)"
env -i HOME="$WORK/home2" PATH="$WORK/shim:/usr/bin:/bin" TERM=dumb ./run.sh >"$WORK/slow2.log" 2>&1 &
APP3=$!
wait_listen "$WORK/slow2.log" $APP3
echo "--- launcher output (second run):"; cat "$WORK/slow2.log"
grep -q "first run" "$WORK/slow2.log" && check "second run skips bootstrap" "reinstalled" "reused" || check "second run skips bootstrap" "reused" "reused"
check "GET / second run" "$(curl -s -o /dev/null -w '%{http_code}' $B/)" 200
stop_app $APP3

echo
echo "=== RESULT: $([ $fail -eq 0 ] && echo ALL-PASS || echo FAILURES-PRESENT) ==="
echo "WORK preserved at $WORK"
exit $fail
