#!/usr/bin/env bash
# Start the whole topology: the authorization plane (which also serves the
# console) and the two serving agents, each as its own process on the port
# ARCHITECTURE.md names.
#
# One command, because a judge must never be asked to orchestrate three
# terminals. Ctrl-C stops all of them.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${WARRANT_CONFIG:=config/warrant.offline.yaml}"
export WARRANT_CONFIG
echo "profile: ${WARRANT_CONFIG}"

pids=()
cleanup() { echo; echo "stopping..."; for p in "${pids[@]:-}"; do kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT INT TERM

python -m warrant.cli serve --port 8000 &
pids+=($!)
sleep 2
python -m warrant.cli serve-agent inventory-reconciler &
pids+=($!)
python -m warrant.cli serve-agent roster-planner &
pids+=($!)

cat <<'NEXT'

  plane + console   http://127.0.0.1:8000
  inventory-reconciler   :8102
  roster-planner         :8103

  Ctrl-C to stop all three.
NEXT
wait
