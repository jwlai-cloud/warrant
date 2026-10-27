"""Record the live run that public visitors replay.

    .venv/bin/python scripts/record_replay.py     # -> src/warrant/api/static/replay.json

On the public deployment only judges (WARRANT_JUDGE_KEY) run Nemotron live;
everyone else watches this recording, played back in their own browser. It is
a real run, not a script: the same two live runs the video films (first run
refused and escalated, steward approves, second run finds CLM-3606), captured
event by event with their real timings, plus the model, the audit log and the
grant request at each point, so the replay console needs nothing from the
server. Rejected, like a video take, unless it lands on the published numbers.
"""
from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src" / "warrant" / "api" / "static" / "replay.json"
PORT = 8025
URL = f"http://127.0.0.1:{PORT}"


def _env(audit: Path) -> dict:
    env = dict(os.environ, WARRANT_CONFIG="config/warrant.yaml", PYTHONPATH="src",
               WARRANT_AUDIT_PATH=str(audit))
    env.pop("WARRANT_JUDGE_KEY", None)
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith(("WARRANT_TF_API_KEY=", "WARRANT_TF_BASE_URL=")):
            k, v = line.split("=", 1)
            env[k] = v.strip().strip('"').strip("'")
    return env


def stream(c: httpx.Client) -> tuple[list[dict], dict]:
    events = []
    with c.stream("GET", "/v1/demo/stream", timeout=None) as r:
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            e = json.loads(line[6:])
            if e["kind"] == "done":
                return events, e["result"]
            if e["kind"] == "error":
                raise RuntimeError(e["text"])
            events.append(e)
    raise RuntimeError("stream ended without a result")


def take(c: httpx.Client) -> dict:
    c.post("/v1/demo/reset").raise_for_status()
    model = c.get("/v1/model").json()
    ev1, res1 = stream(c)
    audit1 = c.get("/v1/audit?limit=200").json()["entries"]
    if res1["at_risk"] != 2561.0:
        raise ValueError(f"first run at £{res1['at_risk']}, published £2,561.00")
    reqs = [r for r in res1["grant_requests"] if r["state"] == "pending"]
    rec = (reqs[0].get("review") or {}).get("recommendation", "") if reqs else ""
    if len(reqs) != 1 or "approve" not in rec:
        raise ValueError(f"expected one pending request the Steward Agent would approve, got {rec!r}")
    owner = {e["id"]: e["owner_org"] for e in model["data_entities"]}[reqs[0]["data_entity"]]
    conds = reqs[0]["review"].get("conditions") or []
    note = ("Approved with the Steward Agent's conditions: " + "; ".join(conds) + "."
            if conds else "Approved for Q3 close. Scope limited to allowance verification.")
    d = c.post(f"/v1/grant-requests/{reqs[0]['id']}/decision",
               json={"decided_by": owner, "approve": True, "note": note})
    d.raise_for_status()
    ev2, res2 = stream(c)
    audit2 = c.get("/v1/audit?limit=200").json()["entries"]
    if res2["at_risk"] != 2851.0:
        raise ValueError(f"second run at £{res2['at_risk']}, published £2,851.00")
    return {
        "recorded_at": datetime.date.today().isoformat(),
        "tiers": c.get("/healthz").json()["tiers"],
        "model": model,
        "runs": [{"events": ev1, "result": res1, "audit": audit1},
                 {"events": ev2, "result": res2, "audit": audit2,
                  "approved": d.json()}],
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        server = subprocess.Popen(
            [str(ROOT / ".venv/bin/python"), "-m", "uvicorn", "warrant.api.app:app",
             "--port", str(PORT)], cwd=ROOT, env=_env(Path(tmp) / "warrant.jsonl"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            time.sleep(4)
            with httpx.Client(base_url=URL, timeout=120) as c:
                for attempt in range(1, 4):
                    try:
                        rec = take(c)
                        break
                    except ValueError as exc:          # model variance: retake
                        print(f"  take {attempt} rejected: {exc}")
                else:
                    sys.exit("three takes rejected; nothing written")
        finally:
            server.terminate()
    OUT.write_text(json.dumps(rec, separators=(",", ":")))
    print(f"  wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size // 1024} KB): "
          f"£{rec['runs'][0]['result']['at_risk']:,.2f} -> £{rec['runs'][1]['result']['at_risk']:,.2f}")


if __name__ == "__main__":
    main()
