#!/bin/bash
# agent_loop.sh v3 — process supervisor for one agent role (W1-2).
#
# Usage: scripts/agent_loop.sh <pm|backend|frontend> [poll_seconds]
# Env:   MAX_PARALLEL=3        max concurrent per-message invocations
#        INVOKE_TIMEOUT=900    supervisor-side wall-clock cap per dispatch
#
# v3: this script no longer contains model-spawn logic. Every message is
# handed to agents/dispatch.py — the single governed entry point that owns
# preflight, the governor, the run budget, the attempt ledger (incremented
# BEFORE invoking), the model call, result validation, and the ack decision.
# The shell keeps what it is good at: flock, nohup, timeout, marker pruning,
# and worktree setup. A bare model command reappearing in this file is a
# regression; tests/test_dispatch.py greps for exactly that.
#
# v3 also removes the empty-inbox model heartbeat (v2 invoked a model every
# 4th empty poll — 82 such invocations measured in the 2026-07 logs, every
# one rc=0). An empty inbox now records a suppressed-decision telemetry line
# and costs zero tokens.
#
# NOTE: do not run an interactive session for a role while its loop is up.
set -u
ROLE=${1:?usage: agent_loop.sh <pm|backend|frontend> [poll_seconds]}
POLL=${2:-900}
MAX_PARALLEL=${MAX_PARALLEL:-3}
INVOKE_TIMEOUT=${INVOKE_TIMEOUT:-900}

HERE=$(cd "$(dirname "$0")" && pwd)
PROJ=$HERE
while [ "$PROJ" != "/" ] && [ ! -d "$PROJ/mailroom" ]; do PROJ=$(dirname "$PROJ"); done
[ -d "$PROJ/mailroom" ] || { echo "no mailroom/ ancestor found" >&2; exit 1; }
MAILROOM=$PROJ/mailroom
DIR=$PROJ/worktrees/$ROLE
FANROOT=$PROJ/worktrees/.fan
[ -d "$DIR" ] || { echo "no role clone at $DIR" >&2; exit 1; }
LOG=$MAILROOM/logs/$ROLE.log
mkdir -p "$MAILROOM/logs" "$MAILROOM/locks/running" "$FANROOT"

exec 9>"$MAILROOM/locks/$ROLE.lock"
flock -n 9 || { echo "another $ROLE loop is already running" >&2; exit 1; }

fan_worker() { # $1 = full message_id
  # set -a so tuned values are exported and actually reach the child process
  [ -f "$MAILROOM/effort.env" ] && { set -a; . "$MAILROOM/effort.env"; set +a; }
  local id=$1 id8=${1:0:8}
  local lockf=$MAILROOM/locks/$ROLE-msg-$id8.lock
  exec 8>"$lockf"
  flock -n 8 || return 0
  # HALT re-check at spawn time: a worker fanned just before HALT was set
  # must not start work after it (v2 only checked in the poll loop).
  [ -f "$MAILROOM/HALT" ] && { echo "[$(date -Is)] [$ROLE:$id8] HALT set — worker aborting" >>"$LOG"; return 0; }
  local marker=$MAILROOM/locks/running/$ROLE-$id8
  trap 'rm -f "$marker"' EXIT TERM INT HUP
  echo $$ >"$marker"
  local wt=$FANROOT/$ROLE-$id8
  git -C "$DIR" fetch -q origin
  git -C "$DIR" worktree add --detach "$wt" origin/main >/dev/null 2>&1 || {
    echo "[$(date -Is)] [$ROLE:$id8] worktree add failed" >>"$LOG"; return 1; }
  echo "[$(date -Is)] [$ROLE:$id8] dispatch start" >>"$LOG"
  timeout "$INVOKE_TIMEOUT" python3 "$wt/agents/dispatch.py" \
    --role "$ROLE" --message-id "$id" --worktree "$wt" >>"$LOG" 2>&1 </dev/null
  echo "[$(date -Is)] [$ROLE:$id8] dispatch done rc=$?" >>"$LOG"
  # Never delete work: remove only if clean; a dirty tree is left in place
  # and logged (W1-4 adds the recovery bundle + quarantine on top of this).
  git -C "$DIR" worktree remove "$wt" >/dev/null 2>&1 \
    || echo "[$(date -Is)] [$ROLE:$id8] worktree dirty — left at $wt" >>"$LOG"
}

export ROLE MAILROOM DIR FANROOT LOG INVOKE_TIMEOUT
export -f fan_worker

n=0
echo "[$(date -Is)] loop v3 start role=$ROLE poll=${POLL}s max_parallel=$MAX_PARALLEL" | tee -a "$LOG"
while true; do
  [ -f "$MAILROOM/effort.env" ] && { set -a; . "$MAILROOM/effort.env"; set +a; }  # live effort/timeout tuning
  if [ -f "$MAILROOM/HALT" ]; then
    echo "[$(date -Is)] HALT set — idle" >>"$LOG"
    sleep "$POLL"; continue
  fi
  git -C "$DIR" pull --ff-only --quiet 2>>"$LOG"
  ids=$(cd "$DIR" && python3 agents/postmaster/ledger.py inbox --role "$ROLE" --json 2>>"$LOG" \
        | python3 -c 'import json,sys; [print(m["message_id"]) for m in json.load(sys.stdin)]' 2>/dev/null)
  n=$((n + 1))
  if [ -n "$ids" ]; then
    for m in "$MAILROOM/locks/running/$ROLE-"*; do  # prune markers of SIGKILLed workers
      [ -f "$m" ] && ! kill -0 "$(cat "$m" 2>/dev/null)" 2>/dev/null && rm -f "$m"
    done
    for id in $ids; do
      running=$(ls "$MAILROOM/locks/running/" 2>/dev/null | grep -c "^$ROLE-" || true)
      [ "$running" -ge "$MAX_PARALLEL" ] && { echo "[$(date -Is)] at cap ($running/$MAX_PARALLEL)" >>"$LOG"; break; }
      nohup bash -c 'fan_worker "$1"' _ "$id" >/dev/null 2>&1 &
    done
  else
    # Deterministic empty-inbox record. Zero model calls, one telemetry line.
    (cd "$DIR" && python3 agents/dispatch.py --role "$ROLE" \
      --record-suppressed empty_inbox >>"$LOG" 2>&1) || true
  fi
  sleep "$POLL"
done
