#!/usr/bin/env bash
# Prove the seam across real process boundaries.
#
# The unit tests cover verify_warrant with stubs and the console demo runs the
# graph in-process. Neither exercises an actual cross-service call, which is the
# thing ARCHITECTURE.md claims. This does: three processes, real HTTP, real
# rows on the wire.
set -euo pipefail
cd "$(dirname "$0")/.."
export WARRANT_CONFIG="${WARRANT_CONFIG:-config/warrant.offline.yaml}"

pids=()
cleanup() { for p in "${pids[@]:-}"; do kill "$p" 2>/dev/null || true; done; rm -rf audit/smoke; }
trap cleanup EXIT INT TERM

PYTHONPATH=src python -m warrant.cli serve --port 8000 >/tmp/warrant-plane.log 2>&1 &
pids+=($!)
sleep 3
PYTHONPATH=src python -m warrant.cli serve-agent roster-planner >/tmp/warrant-roster.log 2>&1 &
pids+=($!)
sleep 3

python - <<'PY'
import asyncio, os, sys
sys.path.insert(0, os.path.join(os.getcwd(), "src"))
import httpx
from warrant.agents.base import governed_call

PLANE, ROSTER = "http://127.0.0.1:8000", "http://127.0.0.1:8103"
fails = []

async def main():
    async with httpx.AsyncClient(timeout=15) as c:
        g = await governed_call(c, PLANE, caller="expense-auditor",
                                callee="roster-planner", callee_url=ROSTER,
                                purpose="which staff travelled in Q3, from the roster")
        rows = (g.data or {}).get("rows", {})
        print(f"1/3 granted call returns rows      : {g.granted} {list(rows)}")
        if not (g.granted and rows.get("Employee.Roster")):
            fails.append("granted call returned no rows")

        d = await governed_call(c, PLANE, caller="expense-auditor",
                                callee="roster-planner", callee_url=ROSTER,
                                purpose="verify allowance claims against compensation bands")
        print(f"2/3 refused call returns no data   : granted={d.granted}")
        if d.granted or d.data:
            fails.append("refused call still returned data")

        r = await c.post(f"{ROSTER}/data",
                         json={"warrant_id": g.warrant_id, "caller": "vendor-scout"})
        print(f"3/3 warrant reuse by another caller: {r.status_code}")
        if r.status_code != 403:
            fails.append(f"callee accepted a warrant issued to someone else ({r.status_code})")

asyncio.run(main())
if fails:
    print("\nFAIL:"); [print("  -", f) for f in fails]; sys.exit(1)
print("\nPASS - the seam holds across processes.")
PY
