#!/usr/bin/env bash
# TASK-208 (issue #36) item 3: clean-room test of the PACKAGED real-engine
# bundle — the exact tarball a tester would download, in a fresh directory,
# with no dev tooling and no repo access on the app's environment side.
#
#   entrypoint up -> POST /api/v0/build with the golden corpus PoB code
#   -> POST /api/v0/diff with the golden item -> a REAL engine verdict
#   (the fixture path is provably absent from the artifact).
#
# Method: fresh extract dir + fresh HOME; the entrypoint runs under
# `env -i` with PATH=/usr/bin:/bin (no node, no git, no repo). The test
# driver (this script's python3 heredocs) talks HTTP from the host side,
# standing in for the tester's browser. Golden inputs come from the repo
# on the HOST side only — the app under test sees them as ordinary HTTP
# request bodies, exactly like a tester pasting their own PoB code.
#
# Usage: scripts/cleanroom_real_engine_check.sh [path-to-tarball]
#   (default: newest dist/poe-upgrade-advisor-v0-*.tar.gz)
# Exit 0 = every check passed. Transcript goes to stdout; capture with
#   scripts/cleanroom_real_engine_check.sh 2>&1 | tee cleanroom.log
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

TARBALL="${1:-$(ls -t dist/poe-upgrade-advisor-v0-*.tar.gz 2>/dev/null | head -1)}"
[ -n "$TARBALL" ] && [ -f "$TARBALL" ] || { echo "FAIL: no tarball found (run scripts/package_mvp.sh first)"; exit 1; }

GOLDEN_BUILD="engine/corpus/seed/ninja/12-elementalist-ci-cold-snap.json"
GOLDEN_ITEM="engine/tests/fixtures/item.txt"
PORT=47791

PASS=0
FAIL=0
ok()   { PASS=$((PASS+1)); echo "PASS: $*"; }
bad()  { FAIL=$((FAIL+1)); echo "FAIL: $*"; }

WORK="$(mktemp -d /tmp/poe-mvp-cleanroom.XXXXXX)"
SERVER_PID=""
cleanup() {
  [ -n "$SERVER_PID" ] && kill -- -"$SERVER_PID" 2>/dev/null
  wait "$SERVER_PID" 2>/dev/null
  rm -rf "$WORK"
}
trap cleanup EXIT

echo "== clean-room real-engine check (TASK-208 / issue #36)"
echo "repo HEAD:        $(git rev-parse HEAD)"
echo "tarball:          $TARBALL"
echo "tarball sha256:   $(sha256sum "$TARBALL" | cut -d' ' -f1)"
echo "tarball size:     $(du -h "$TARBALL" | cut -f1)"
echo "extract dir:      $WORK (fresh mktemp)"
echo "date:             $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# --- 1. Extract exactly like a tester --------------------------------------
tar -xzf "$TARBALL" -C "$WORK"
APP="$WORK/poe-upgrade-advisor-v0"
[ -x "$APP/run.sh" ] && [ -f "$APP/run.bat" ] \
  && ok "entrypoints present (run.sh dev/CI / run.bat for the Windows zip)" \
  || bad "entrypoints missing"
[ ! -e "$APP/run.command" ] \
  && ok "run.command ABSENT — macOS dropped (issue #75 decision)" \
  || bad "run.command present (macOS packaging must be gone)"

# --- 2. Provenance: real engine in, fixture path out -----------------------
[ -x "$APP/engine/.runtime/bin/luajit" ] \
  && ok "prebuilt LuaJIT runtime ships (testers need no cc/make/git)" \
  || bad "engine/.runtime/bin/luajit missing"
echo "   luajit: $(file -b "$APP/engine/.runtime/bin/luajit" | cut -d, -f1-3)"
[ -f "$APP/engine/vendor/PathOfBuilding/src/HeadlessWrapper.lua" ] \
  && ok "vendored PathOfBuilding src ships" \
  || bad "vendored PoB src missing"
TREE_COUNT="$(find "$APP/engine/vendor/PathOfBuilding/src/TreeData" -name tree.lua | wc -l)"
[ "$TREE_COUNT" -ge 39 ] \
  && ok "all $TREE_COUNT passive-tree data files ship (any league's build imports)" \
  || bad "only $TREE_COUNT tree.lua files shipped"
SPRITES="$(find "$APP/engine/vendor/PathOfBuilding/src/TreeData" \( -name '*.png' -o -name '*.jpg' -o -name '*.webp' \) | wc -l)"
[ "$SPRITES" -eq 0 ] \
  && ok "0 GUI sprites shipped (headless stub; no network-fetch path)" \
  || bad "$SPRITES GUI sprites leaked into the bundle"
[ ! -e "$APP/contracts" ] \
  && ok "contracts/fixtures ABSENT from the artifact — fixture verdicts are impossible" \
  || bad "contracts/ present in artifact (fixture path reachable?)"
[ ! -d "$APP/engine/.runtime/timeless-data" ] \
  && ok "timeless-data cache not shipped (regenerates from vendored zips on first run)" \
  || bad "timeless-data cache shipped (double payload)"

# --- 3. Launch the entrypoint as a tester (env -i, fresh HOME) -------------
mkdir -p "$WORK/home"
setsid env -i HOME="$WORK/home" PATH=/usr/bin:/bin \
  sh -c "cd '$APP' && ./run.sh" >"$WORK/server.log" 2>&1 &
SERVER_PID=$!
echo "== entrypoint launched (env -i HOME=<fresh> PATH=/usr/bin:/bin ./run.sh), pid $SERVER_PID"

READY=0
for _ in $(seq 1 120); do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "FAIL: entrypoint died during startup; server log follows"
    cat "$WORK/server.log"
    exit 1
  fi
  if python3 -c "import socket,sys; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1',$PORT))" 2>/dev/null; then
    READY=1
    break
  fi
  sleep 1
done
[ "$READY" -eq 1 ] && ok "entrypoint up on http://127.0.0.1:$PORT/ (first run incl. engine boot + timeless-cache build)" \
  || { bad "entrypoint never listened on $PORT"; cat "$WORK/server.log"; exit 1; }
grep -q "listening on http://127.0.0.1:$PORT/" "$WORK/server.log" \
  && ok "launcher printed its listening line: $(grep -m1 listening "$WORK/server.log")" \
  || bad "listening line missing from server log"

# --- 4. Exercise the full slice over HTTP (host = tester's browser) --------
export CLEANROOM_PORT="$PORT" GOLDEN_BUILD GOLDEN_ITEM CLEANROOM_COUNTS="$WORK/http-counts"
python3 - <<'PY'
import json, os, re, sys, urllib.error, urllib.request

port = os.environ["CLEANROOM_PORT"]
base = f"http://127.0.0.1:{port}"

def get(path):
    try:
        with urllib.request.urlopen(base + path, timeout=10) as r:
            return r.status, r.headers.get("content-type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type", ""), e.read()

def post(path, payload, timeout=30):
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode(),
        headers={"content-type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        return e.code, json.loads(raw) if raw else None

counts = [0, 0]

def check(name, cond):
    counts[cond == 0] += 1
    print(("PASS: " if cond else "FAIL: ") + name)
    return cond

ok = True

status, ctype, body = get("/")
ok &= check("GET / -> 200 text/html (the whole app)", status == 200 and ctype.startswith("text/html"))
m = re.search(rb'/assets/[^"]+\.js', body)
if m:
    status, ctype, _ = get(m.group(0).decode())
    ok &= check("GET hashed JS asset -> 200 text/javascript", status == 200 and ctype.startswith("text/javascript"))
else:
    ok &= check("index.html references a hashed JS asset", False)

status, _, _ = get("/api/v0/build")
ok &= check("GET /api/v0/build pre-import -> honest 404", status == 404)

pob_code = json.load(open(os.environ["GOLDEN_BUILD"]))["pathOfBuildingExport"]
status, build = post("/api/v0/build", {"pob_code": pob_code})
ok &= check("POST /api/v0/build (golden corpus PoB code) -> 200", status == 200)
print("   build readback:", json.dumps(build, sort_keys=True))
if status == 200:
    ok &= check("main skill readback is the real engine's (Vaal Cold Snap)",
                build["main_skill"]["name"] == "Vaal Cold Snap")

item_text = open(os.environ["GOLDEN_ITEM"], encoding="utf-8").read()
status, verdict = post("/api/v0/diff", {"item_text": item_text})
ok &= check("POST /api/v0/diff (golden item) -> 200", status == 200)
print("   verdict:", json.dumps(verdict, sort_keys=True))
if status == 200:
    ok &= check("verdict word is contract-valid",
                verdict["verdict"] in ("UPGRADE", "SIDEGRADE", "DOWNGRADE", "CANT_EVALUATE"))
    # The retired fixture path answered EVERY item with +12.4 / -1.8 UPGRADE.
    ok &= check("NOT the fixture signature (+12.4/-1.8 UPGRADE)",
                not (verdict["verdict"] == "UPGRADE"
                     and verdict["offense_delta_pct"] == 12.4
                     and verdict["defense_delta_pct"] == -1.8))
    # Independently recorded real-engine E2E on PR #72 for this exact
    # build+item+preset: SIDEGRADE +15.4 / -11.8, deterministic engine.
    ok &= check("matches the real-engine E2E numbers from PR #72 (SIDEGRADE +15.4/-11.8)",
                verdict["verdict"] == "SIDEGRADE"
                and verdict["offense_delta_pct"] == 15.4
                and verdict["defense_delta_pct"] == -11.8)
    ok &= check("assumption chips present (I3)", len(verdict["assumptions"]) >= 1)
    ok &= check("sentence within 140-char cap (I2)", len(verdict["sentence"]) <= 140)

    status, flipped = post("/api/v0/diff", {
        "item_text": item_text,
        "overrides": [{"assumption_id": "config.flasks_up", "value": False}],
    })
    ok &= check("I3 override round-trip -> 200", status == 200)
    if status == 200:
        chips = {a["id"]: a["value"] for a in flipped["assumptions"]}
        ok &= check("flasks_up chip flipped true->false on override", chips.get("config.flasks_up") is False)
        print("   overridden verdict:", json.dumps(flipped, sort_keys=True))

status, _ = post("/api/v0/diff", {"item_text": "Rarity: RARE\nnot a real item\n"})
ok &= check("unparseable item -> honest 422 (I5)", status == 422)

with open(os.environ["CLEANROOM_COUNTS"], "w") as fh:
    fh.write(f"{counts[0]} {counts[1]}")
sys.exit(0 if ok else 1)
PY
HTTP_RESULT=$?
[ "$HTTP_RESULT" -eq 0 ] || FAIL=$((FAIL+1))

# --- 5. Clean stop -----------------------------------------------------------
kill -- -"$SERVER_PID" 2>/dev/null
wait "$SERVER_PID" 2>/dev/null
SERVER_PID=""
python3 -c "import socket; s=socket.socket(); s.settimeout(1); s.connect(('127.0.0.1',$PORT))" 2>/dev/null \
  && bad "port $PORT still bound after stop" \
  || ok "server stopped, port $PORT released"

HTTP_PASS=0; HTTP_FAIL=1
[ -f "$WORK/http-counts" ] && read -r HTTP_PASS HTTP_FAIL <"$WORK/http-counts"
echo "== clean-room result: $((PASS+HTTP_PASS)) passed, $((FAIL+HTTP_FAIL)) failed"
[ "$FAIL" -eq 0 ] && [ "$HTTP_RESULT" -eq 0 ]
