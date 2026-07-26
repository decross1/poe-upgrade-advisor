#!/bin/bash
# agent_loop.sh — headless heartbeat loop for one agent role (postmaster-lite;
# retired when TASK-005 ports the real daemon).
#
# Usage: scripts/agent_loop.sh <pm|backend|frontend> [poll_seconds]
#
# Every poll: honor HALT, sync the role clone, check the ledger inbox (cheap).
# Invoke the role's CLI only when unacked messages exist, or every
# HEARTBEAT_EVERY-th poll regardless (so agents still check their issues and
# review queue with an empty inbox). One instance per role (flock).
#
# NOTE: do not run a role's loop while an interactive session for that role is
# open in the same clone — two agents in one worktree race each other.
set -u
ROLE=${1:?usage: agent_loop.sh <pm|backend|frontend> [poll_seconds]}
POLL=${2:-900}
HEARTBEAT_EVERY=${HEARTBEAT_EVERY:-4}
INVOKE_TIMEOUT=${INVOKE_TIMEOUT:-1800}

# Project root = nearest ancestor of this script containing mailroom/ (same
# resolution rule as ledger.py).
HERE=$(cd "$(dirname "$0")" && pwd)
PROJ=$HERE
while [ "$PROJ" != "/" ] && [ ! -d "$PROJ/mailroom" ]; do PROJ=$(dirname "$PROJ"); done
[ -d "$PROJ/mailroom" ] || { echo "no mailroom/ ancestor found" >&2; exit 1; }
MAILROOM=$PROJ/mailroom
DIR=$PROJ/worktrees/$ROLE
[ -d "$DIR" ] || { echo "no role clone at $DIR" >&2; exit 1; }
LOG=$MAILROOM/logs/$ROLE.log
mkdir -p "$MAILROOM/logs" "$MAILROOM/locks"

exec 9>"$MAILROOM/locks/$ROLE.lock"
flock -n 9 || { echo "another $ROLE loop is already running" >&2; exit 1; }

PROMPT="You are the $ROLE agent of the PoE Upgrade Advisor org, invoked headlessly by the heartbeat loop. Startup reads, in order: AGENTS.md, agents/roles/$ROLE.md, PRODUCT_DOCTRINE.md. Then process your inbox: python3 agents/postmaster/ledger.py inbox --role $ROLE — follow the AGENTS.md work protocol for each message and ack it when handled. If the inbox is empty, check your assigned open issues and review queue (gh issue list, gh pr list) and act per your role file. Batch everything ready now; this is one governed invocation."

invoke() {
  case $ROLE in
    pm)
      env -u ANTHROPIC_API_KEY claude -p "$PROMPT" --permission-mode acceptEdits ;;
    backend)
      # bwrap userns sandboxing fails headless on this box (RTM_NEWADDR EPERM),
      # so run unsandboxed; the poll interval + HALT are the containment.
      codex exec --dangerously-bypass-approvals-and-sandbox "$PROMPT" ;;
    frontend)
      eval "$(grep '^export KIMI_API_KEY' ~/.bashrc)"
      pi --provider moonshot --model kimi-k3 --no-session -p "$PROMPT" ;;
  esac
}

export ROLE MAILROOM PROMPT
export -f invoke

n=0
echo "[$(date -Is)] loop start role=$ROLE poll=${POLL}s heartbeat_every=$HEARTBEAT_EVERY" | tee -a "$LOG"
while true; do
  if [ -f "$MAILROOM/HALT" ]; then
    echo "[$(date -Is)] HALT set — idle" >>"$LOG"
    sleep "$POLL"; continue
  fi
  git -C "$DIR" pull --ff-only --quiet 2>>"$LOG"
  unread=$(cd "$DIR" && python3 agents/postmaster/ledger.py inbox --role "$ROLE" --json 2>>"$LOG" \
           | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null || echo 0)
  n=$((n + 1))
  if [ "$unread" -gt 0 ] || [ $((n % HEARTBEAT_EVERY)) -eq 0 ]; then
    echo "[$(date -Is)] invoke (unread=$unread, poll #$n)" | tee -a "$LOG"
    ( cd "$DIR" && timeout "$INVOKE_TIMEOUT" bash -c invoke ) >>"$LOG" 2>&1 </dev/null
    echo "[$(date -Is)] invoke done rc=$?" | tee -a "$LOG"
  fi
  sleep "$POLL"
done
