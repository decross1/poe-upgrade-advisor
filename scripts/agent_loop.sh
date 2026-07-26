#!/bin/bash
# agent_loop.sh v2 — headless heartbeat + fan-out runner for one agent role
# (postmaster-lite; retired when TASK-005 ports the real daemon).
#
# Usage: scripts/agent_loop.sh <pm|backend|frontend> [poll_seconds]
# Env:   MAX_PARALLEL=3        max concurrent per-message invocations
#        HEARTBEAT_EVERY=4     empty-inbox heartbeat every Nth poll
#        INVOKE_TIMEOUT=1800   wall-clock cap per invocation (seconds)
#
# Fan-out: every unacked ledger message gets its own invocation in its own
# throwaway git worktree (.fan/<role>-<msgid>), so up to MAX_PARALLEL tasks per
# role run concurrently without racing each other. A per-message flock prevents
# double-processing across polls. Empty-inbox heartbeats run single, in the
# role clone, so the agent still checks its issues and review queue.
#
# NOTE: do not run an interactive session for a role while its loop is up.
set -u
ROLE=${1:?usage: agent_loop.sh <pm|backend|frontend> [poll_seconds]}
POLL=${2:-900}
MAX_PARALLEL=${MAX_PARALLEL:-3}
HEARTBEAT_EVERY=${HEARTBEAT_EVERY:-4}
INVOKE_TIMEOUT=${INVOKE_TIMEOUT:-1800}

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

# $1 = prompt, $2 = working dir
invoke() {
  local prompt=$1 dir=$2
  case $ROLE in
    pm)
      (cd "$dir" && env -u ANTHROPIC_API_KEY claude -p "$prompt" --permission-mode acceptEdits) ;;
    backend)
      # bwrap userns sandboxing fails headless on this box (RTM_NEWADDR EPERM),
      # so run unsandboxed; poll cadence + HALT + MAX_PARALLEL are the containment.
      (cd "$dir" && codex exec --dangerously-bypass-approvals-and-sandbox "$prompt") ;;
    frontend)
      eval "$(grep '^export KIMI_API_KEY' ~/.bashrc)"
      (cd "$dir" && pi --provider moonshot --model kimi-k3 --no-session -p "$prompt") ;;
  esac
}

fan_worker() { # $1 = full message_id
  local id=$1 id8=${1:0:8}
  local lockf=$MAILROOM/locks/$ROLE-msg-$id8.lock
  exec 8>"$lockf"
  flock -n 8 || return 0
  local marker=$MAILROOM/locks/running/$ROLE-$id8
  echo $$ >"$marker"
  trap 'rm -f "$marker"' EXIT
  local wt=$FANROOT/$ROLE-$id8
  git -C "$DIR" fetch -q origin
  git -C "$DIR" worktree add --detach "$wt" origin/main >/dev/null 2>&1 || {
    echo "[$(date -Is)] [$ROLE:$id8] worktree add failed" >>"$LOG"; return 1; }
  local prompt="You are the $ROLE agent of the PoE Upgrade Advisor org, invoked headlessly to process EXACTLY ONE ledger message. Startup reads, in order: AGENTS.md, agents/roles/$ROLE.md, PRODUCT_DOCTRINE.md. Your message: run 'python3 agents/postmaster/ledger.py show --id $id8' and handle ONLY that message per the AGENTS.md work protocol. You are in a detached throwaway worktree at origin/main — create your task branch from here and push it; commits not pushed are lost. Other $ROLE invocations run in parallel on OTHER messages: do not touch their tasks, do not process other inbox messages. When handled (or blocked, with a RESUME: issue comment), ack: python3 agents/postmaster/ledger.py ack --role $ROLE --id $id8"
  echo "[$(date -Is)] [$ROLE:$id8] fan invoke start" >>"$LOG"
  timeout "$INVOKE_TIMEOUT" bash -c 'invoke "$1" "$2"' _ "$prompt" "$wt" >>"$LOG" 2>&1 </dev/null
  echo "[$(date -Is)] [$ROLE:$id8] fan invoke done rc=$?" >>"$LOG"
  git -C "$DIR" worktree remove "$wt" >/dev/null 2>&1 \
    || echo "[$(date -Is)] [$ROLE:$id8] worktree dirty — left at $wt" >>"$LOG"
  git -C "$DIR" worktree prune >/dev/null 2>&1
}

export ROLE MAILROOM DIR FANROOT LOG INVOKE_TIMEOUT
export -f invoke fan_worker

n=0
echo "[$(date -Is)] loop v2 start role=$ROLE poll=${POLL}s max_parallel=$MAX_PARALLEL heartbeat_every=$HEARTBEAT_EVERY" | tee -a "$LOG"
while true; do
  if [ -f "$MAILROOM/HALT" ]; then
    echo "[$(date -Is)] HALT set — idle" >>"$LOG"
    sleep "$POLL"; continue
  fi
  git -C "$DIR" pull --ff-only --quiet 2>>"$LOG"
  ids=$(cd "$DIR" && python3 agents/postmaster/ledger.py inbox --role "$ROLE" --json 2>>"$LOG" \
        | python3 -c 'import json,sys; [print(m["message_id"]) for m in json.load(sys.stdin)]' 2>/dev/null)
  n=$((n + 1))
  if [ -n "$ids" ]; then
    for id in $ids; do
      running=$(ls "$MAILROOM/locks/running/" 2>/dev/null | grep -c "^$ROLE-" || true)
      [ "$running" -ge "$MAX_PARALLEL" ] && { echo "[$(date -Is)] at cap ($running/$MAX_PARALLEL)" >>"$LOG"; break; }
      nohup bash -c 'fan_worker "$1"' _ "$id" >/dev/null 2>&1 &
    done
  elif [ $((n % HEARTBEAT_EVERY)) -eq 0 ]; then
    echo "[$(date -Is)] heartbeat invoke (poll #$n)" >>"$LOG"
    hb="You are the $ROLE agent of the PoE Upgrade Advisor org, invoked headlessly on an empty-inbox heartbeat. Startup reads: AGENTS.md, agents/roles/$ROLE.md, PRODUCT_DOCTRINE.md. Check your assigned open issues and review queue (gh issue list --label role:$ROLE --state open; gh pr list) and act per your role file. Batch everything ready now; this is one governed invocation."
    timeout "$INVOKE_TIMEOUT" bash -c 'invoke "$1" "$2"' _ "$hb" "$DIR" >>"$LOG" 2>&1 </dev/null
    echo "[$(date -Is)] heartbeat done rc=$?" >>"$LOG"
  fi
  sleep "$POLL"
done
